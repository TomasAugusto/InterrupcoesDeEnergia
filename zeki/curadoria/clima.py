"""ERA5 bruto -> grade, pesos e clima por conjunto.

O ERA5 é uma grade de 0,25° e o conjunto elétrico é um polígono irregular. A
ligação entre os dois é a fração da área do conjunto que cai em cada célula —
média de área, não valor do centroide. Conjunto grande atravessa várias células
e cada uma entra com o seu peso.
"""

import io
import logging
import zipfile

import duckdb
import numpy as np
import pyarrow as pa
import xarray as xr
from shapely import box, from_wkt
from shapely.strtree import STRtree

from zeki.config import BRONZE, PRATA, UF_CLIMA
from zeki.fontes import era5

log = logging.getLogger(__name__)

RESOLUCAO = 0.25

# Escalas para guardar em int16 sem perda que importe: chuva em centésimos de
# milímetro, rajada em centésimos de km/h.
ESCALA_CHUVA = 100
ESCALA_RAJADA = 100


def _celulas_da_grade(ds) -> tuple[np.ndarray, np.ndarray]:
    return ds["latitude"].values, ds["longitude"].values


def _id_celula(lat: float, lon: float) -> int:
    """Identificador estável a partir das coordenadas do canto da célula."""
    return int(round((lat + 90) / RESOLUCAO)) * 10_000 + int(
        round((lon + 180) / RESOLUCAO)
    )


def pesos(con=None) -> int:
    """Fração da área de cada conjunto que cai em cada célula da grade.

    Só conjuntos da UF do estudo entram, e só células que realmente cruzam algum
    deles — o retângulo pedido ao CDS tem 1.739 células, mas boa parte cai fora
    do estado.
    """
    con = con or duckdb.connect()
    con.execute("set enable_progress_bar=false")
    for t in ("geo_conjunto", "dim_conjunto"):
        con.execute(f"create or replace view {t} as "
                    f"select * from read_parquet('{(PRATA / f'{t}.parquet').as_posix()}')")

    conjuntos = con.execute(f"""
        select g.conjunto, g.wkt
        from geo_conjunto g join dim_conjunto d using (conjunto)
        where d.uf = '{UF_CLIMA}'
    """).fetchall()

    norte, oeste, sul, leste = era5.AREA
    lats = np.arange(sul, norte + RESOLUCAO / 2, RESOLUCAO)
    lons = np.arange(oeste, leste + RESOLUCAO / 2, RESOLUCAO)

    # A célula é o quadrado centrado no ponto da grade.
    meia = RESOLUCAO / 2
    caixas, ids = [], []
    for la in lats:
        for lo in lons:
            caixas.append(box(lo - meia, la - meia, lo + meia, la + meia))
            ids.append(_id_celula(la, lo))
    arvore = STRtree(caixas)

    linhas = []
    for conjunto, wkt in conjuntos:
        geom = from_wkt(wkt)
        area = geom.area
        if area <= 0:
            continue
        for k in arvore.query(geom):
            parte = geom.intersection(caixas[k])
            if parte.is_empty:
                continue
            fracao = parte.area / area
            if fracao < 1e-4:       # célula que só encosta na borda
                continue
            linhas.append({
                "conjunto": conjunto,
                "celula": ids[k],
                "lat": float(caixas[k].centroid.y),
                "lon": float(caixas[k].centroid.x),
                "peso": fracao,
            })

    # Renormaliza: descartar as bordas de <0,01% faz a soma fugir de 1.
    total = {}
    for l in linhas:
        total[l["conjunto"]] = total.get(l["conjunto"], 0.0) + l["peso"]
    for l in linhas:
        l["peso"] /= total[l["conjunto"]]

    con.register("pesos_tmp", pa.Table.from_pylist(linhas))
    con.execute("create or replace table peso_conjunto_celula as "
                "select * from pesos_tmp")
    destino = PRATA / "peso_conjunto_celula.parquet"
    con.execute(f"copy peso_conjunto_celula to '{destino.as_posix()}' "
                "(format parquet, compression zstd)")

    celulas = len({l["celula"] for l in linhas})
    log.info("pesos: %s conjuntos, %s células usadas, %s pares",
             f"{len(total):,}", f"{celulas:,}", f"{len(linhas):,}")
    return len(linhas)


def _ler_mes(caminho) -> xr.Dataset:
    """Junta os dois membros do zip que o CDS devolve.

    Precipitação e rajada vêm em arquivos separados porque têm `stepType`
    diferente — acumulado e máximo.
    """
    partes = []
    with zipfile.ZipFile(caminho) as z:
        for item in z.infolist():
            if not item.filename.endswith(".nc"):
                continue
            ds = xr.open_dataset(io.BytesIO(z.read(item.filename)),
                                 engine="h5netcdf")
            partes.append(ds.drop_vars(["number", "expver"], errors="ignore"))
    return xr.merge(partes, compat="override")


def grade(celulas_usadas: set[int] | None = None) -> int:
    """Converte os NetCDF mensais numa tabela célula × hora."""
    con = duckdb.connect()
    con.execute("set enable_progress_bar=false")

    if celulas_usadas is None:
        caminho = PRATA / "peso_conjunto_celula.parquet"
        celulas_usadas = {
            r[0] for r in con.execute(
                f"select distinct celula from read_parquet('{caminho.as_posix()}')"
            ).fetchall()
        }

    destino = PRATA / "clima_grade"
    destino.mkdir(parents=True, exist_ok=True)

    arquivos = sorted(BRONZE.glob("era5/era5-mg-*.nc"))
    total = 0
    for arquivo in arquivos:
        competencia = arquivo.stem.split("-")[-1]
        saida = destino / f"{competencia}.parquet"
        # O ERA5 revisa o dado recente e a ingestão rebaixa a cauda: comparar só
        # a existência deixava o mês provisório congelado na prata para sempre.
        if saida.exists() and saida.stat().st_mtime >= arquivo.stat().st_mtime:
            continue

        ds = _ler_mes(arquivo)
        lats, lons = _celulas_da_grade(ds)
        malha_lat, malha_lon = np.meshgrid(lats, lons, indexing="ij")
        ids = np.array([[_id_celula(la, lo) for lo in lons] for la in lats])

        manter = np.isin(ids, list(celulas_usadas))
        if not manter.any():
            continue

        # O ERA5 rotula o acumulado pelo FIM do intervalo: `tp` em 15:00 é a
        # chuva que caiu entre 14:00 e 15:00, e `fg10` é a rajada máxima do
        # mesmo intervalo. A interrupção das 14:30, por sua vez, cai no balde
        # das 14:00. Sem recuar uma hora, a chuva parece anteceder a queda em
        # 1h — medido: o pico do perfil de defasagem aparece em -1h, o que se
        # leria como a luz caindo antes de chover.
        instantes = ds["valid_time"].values - np.timedelta64(1, "h")
        chuva = (ds["tp"].values * 1000.0)          # m -> mm
        rajada = (ds["fg10"].values * 3.6)          # m/s -> km/h

        n_tempo = len(instantes)
        idx = np.where(manter.ravel())[0]
        chuva_f = chuva.reshape(n_tempo, -1)[:, idx]
        rajada_f = rajada.reshape(n_tempo, -1)[:, idx]
        ids_f = ids.ravel()[idx]

        tabela = pa.table({
            "celula": pa.array(np.tile(ids_f, n_tempo), pa.int32()),
            "instante_utc": pa.array(
                np.repeat(instantes, len(ids_f)), pa.timestamp("s")
            ),
            "chuva_c": pa.array(
                np.round(np.clip(chuva_f, 0, 320) * ESCALA_CHUVA)
                .astype(np.int16).ravel(), pa.int16()
            ),
            "rajada_c": pa.array(
                np.round(np.clip(rajada_f, 0, 320) * ESCALA_RAJADA)
                .astype(np.int16).ravel(), pa.int16()
            ),
        })
        con.register("mes_tmp", tabela)
        con.execute(f"""
            copy (select * from mes_tmp order by celula, instante_utc)
            to '{saida.as_posix()}'
            (format parquet, compression zstd, compression_level 9)
        """)
        total += tabela.num_rows
        log.info("%s: %s linhas, %.1f MB", competencia,
                 f"{tabela.num_rows:,}", saida.stat().st_size / 1e6)

    return total


def por_conjunto(con=None) -> int:
    """Média de área da grade para cada conjunto, hora a hora.

    Só conjuntos que aparecem no fato: não adianta guardar clima onde não há
    interrupção para cruzar. Fica em UTC, que é como o ERA5 vem; a conversão
    para horário local acontece do lado da interrupção, que é uma coluna só em
    vez de dezenas de milhões.
    """
    from zeki import dados

    con = con or dados.conectar()
    grade_glob = (PRATA / "clima_grade" / "*.parquet").as_posix()
    destino = PRATA / "clima_conjunto_hora.parquet"

    con.execute(f"""
        copy (
            select
                p.conjunto,
                g.instante_utc,
                cast(round(sum(g.chuva_c  * p.peso)) as smallint) as chuva_c,
                cast(round(sum(g.rajada_c * p.peso)) as smallint) as rajada_c
            from read_parquet('{grade_glob}') g
            join peso_conjunto_celula p using (celula)
            where p.conjunto in (select distinct conjunto from interrupcoes)
            group by 1, 2
            order by 1, 2
        )
        to '{destino.as_posix()}'
        (format parquet, compression zstd, compression_level 9)
    """)

    linhas = con.execute(
        f"select count(*) from read_parquet('{destino.as_posix()}')"
    ).fetchone()[0]
    log.info("clima por conjunto: %s linhas, %.0f MB",
             f"{linhas:,}", destino.stat().st_size / 1e6)
    return linhas
