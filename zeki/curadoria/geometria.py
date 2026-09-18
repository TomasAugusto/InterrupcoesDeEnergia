"""Geometria dos municípios e dos conjuntos elétricos.

O conjunto não tem polígono publicado em lugar nenhum: ele é uma unidade
regulatória, não territorial. O que dá para fazer é uni-lo a partir dos
municípios que ele atende, via a ponte da ANEEL. O resultado é a área de
atuação do conjunto — grosseira nas bordas, mas honesta, e é sobre ela que o
mapa pinta e que a chuva é ponderada.
"""

import json
import logging

import duckdb
import pyarrow as pa
import requests
from shapely import to_wkt, union_all
from shapely.geometry import MultiPolygon, shape
from shapely.geometry.polygon import orient

from zeki.config import BRONZE, IBGE_MALHAS, PRATA

log = logging.getLogger(__name__)

UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
]

# A malha "minima" é suficiente para mapa e para ponderação de célula de 25 km,
# e é ~40x menor que a "maxima".
QUALIDADE = "minima"


def orientar(geom):
    """Anel externo no sentido horário.

    É o contrário do que a RFC 7946 do GeoJSON pede, e de propósito: o d3-geo,
    que o Plotly usa por baixo, trata o polígono como esférico e entende anel
    anti-horário como "todo o resto do planeta". Com a orientação da norma o
    mapa sai como um retângulo preenchido com um buraco no formato da área
    certa — o complemento, não o polígono.
    """
    if geom.geom_type == "Polygon":
        return orient(geom, sign=-1.0)
    if geom.geom_type == "MultiPolygon":
        return MultiPolygon([orient(p, sign=-1.0) for p in geom.geoms])
    return geom


def baixar_malhas() -> dict[str, dict]:
    destino = BRONZE / "malhas"
    destino.mkdir(parents=True, exist_ok=True)

    malhas = {}
    for uf in UFS:
        arquivo = destino / f"{uf}.geojson"
        if not arquivo.exists():
            r = requests.get(
                f"{IBGE_MALHAS}/estados/{uf}",
                params={
                    "formato": "application/vnd.geo+json",
                    "intrarregiao": "municipio",
                    "qualidade": QUALIDADE,
                },
                timeout=(30, 300),
            )
            r.raise_for_status()
            arquivo.write_text(r.text, encoding="utf-8")
            log.info("malha %s baixada (%.0f KB)", uf, arquivo.stat().st_size / 1e3)
        malhas[uf] = json.loads(arquivo.read_text(encoding="utf-8"))

    return malhas


def geo_municipios(malhas) -> list[dict]:
    linhas = []
    for uf, colecao in malhas.items():
        for feicao in colecao["features"]:
            geom = shape(feicao["geometry"])
            if not geom.is_valid:
                geom = geom.buffer(0)
            geom = orientar(geom)
            centro = geom.representative_point()
            linhas.append({
                "municipio_ibge": int(feicao["properties"]["codarea"]),
                "uf": uf,
                "wkt": to_wkt(geom, rounding_precision=5),
                "lon": centro.x,
                "lat": centro.y,
                "area_graus": geom.area,
            })
    return linhas


def geo_conjuntos(con) -> int:
    """Une os polígonos municipais de cada conjunto num só."""
    vinculos = con.execute("""
        select p.conjunto, g.wkt
        from ponte_conjunto_municipio p
        join geo_municipio g using (municipio_ibge)
        order by p.conjunto
    """).fetchall()

    from shapely import from_wkt

    por_conjunto = {}
    for conjunto, wkt in vinculos:
        por_conjunto.setdefault(conjunto, []).append(from_wkt(wkt))

    linhas = []
    for conjunto, partes in por_conjunto.items():
        geom = partes[0] if len(partes) == 1 else union_all(partes).buffer(0)
        geom = orientar(geom)
        centro = geom.representative_point()
        linhas.append({
            "conjunto": conjunto,
            "wkt": to_wkt(geom, rounding_precision=5),
            "lon": centro.x,
            "lat": centro.y,
            "area_graus": geom.area,
        })

    con.register("geo_conj", pa.Table.from_pylist(linhas))
    con.execute("create or replace table geo_conjunto as select * from geo_conj")
    return len(linhas)


def construir() -> dict:
    con = duckdb.connect()
    con.execute("set enable_progress_bar=false")
    con.execute(f"""
        create or replace view ponte_conjunto_municipio as
        select * from read_parquet('{(PRATA / "ponte_conjunto_municipio.parquet").as_posix()}')
    """)

    malhas = baixar_malhas()
    municipios = geo_municipios(malhas)
    con.register("geo_mun", pa.Table.from_pylist(municipios))
    con.execute("create or replace table geo_municipio as select * from geo_mun")

    conjuntos = geo_conjuntos(con)

    for tabela in ("geo_municipio", "geo_conjunto"):
        destino = PRATA / f"{tabela}.parquet"
        con.execute(
            f"copy {tabela} to '{destino.as_posix()}' (format parquet, compression zstd)"
        )
        log.info("%s: %.1f MB", tabela, destino.stat().st_size / 1e6)

    log.info("geometria: %s municípios, %s conjuntos", len(municipios), conjuntos)
    return {"municipios": len(municipios), "conjuntos": conjuntos}
