"""Dimensões e a ponte conjunto <-> município.

O fato de 2017 a 2025 não tem município: o grão é o conjunto elétrico, que é uma
unidade regulatória e não respeita divisa municipal. A ANEEL publica a ligação no
dataset `indqual-municipio`, e é ela que permite filtrar por cidade.
"""

import logging

import duckdb
import pyarrow as pa
import requests

from zeki.config import BRONZE, IBGE_LOCALIDADES, PRATA

log = logging.getLogger(__name__)


def dim_municipio(con) -> int:
    """Municípios do IBGE com UF e região. Serve de apoio ao filtro e ao mapa."""
    r = requests.get(f"{IBGE_LOCALIDADES}/municipios", timeout=(30, 180))
    r.raise_for_status()

    linhas = [
        {
            "municipio_ibge": m["id"],
            "municipio": m["nome"],
            "uf": m["microrregiao"]["mesorregiao"]["UF"]["sigla"],
            "uf_nome": m["microrregiao"]["mesorregiao"]["UF"]["nome"],
            "regiao": m["microrregiao"]["mesorregiao"]["UF"]["regiao"]["nome"],
        }
        for m in r.json()
        if m.get("microrregiao")
    ]

    con.register("ibge_municipios", pa.Table.from_pylist(linhas))
    con.execute("create or replace table municipios as select * from ibge_municipios")
    destino = PRATA / "dim_municipio.parquet"
    con.execute(f"copy municipios to '{destino.as_posix()}' (format parquet, compression zstd)")
    return len(linhas)


def nomes(con) -> int:
    """Nome do conjunto, como a própria ANEEL o chama.

    O fato não carrega o nome — seria repeti-lo em 77 milhões de linhas. Ele sai
    do bronze uma vez e vira dimensão. É um rótulo bem melhor que o código, e
    melhor ainda que inventar um a partir dos municípios: o primeiro município
    em ordem alfabética sugeriria uma primazia que não existe.
    """
    arquivos = sorted(BRONZE.glob("interrupcoes-*.parquet"))
    if not arquivos:
        con.execute("create or replace table nome_conjunto"
                    " (conjunto integer, nome varchar)")
        return 0

    partes = []
    for arquivo in arquivos:
        colunas = {linha[0] for linha in con.execute(
            f"describe select * from read_parquet('{arquivo.as_posix()}')"
        ).fetchall()}
        chave = ("CodConjUnidadeConsumidora" if "CodMunicipioIBGE" in colunas
                 else "IdeConjuntoUnidadeConsumidora")
        partes.append(f"""
            select try_cast({chave} as integer)            as conjunto,
                   trim(DscConjuntoUnidadeConsumidora)     as nome
            from read_parquet('{arquivo.as_posix()}')
            where DscConjuntoUnidadeConsumidora is not null
        """)

    # Mais recente vence: conjunto renomeado deve aparecer com o nome atual.
    con.execute(f"""
        create or replace table nome_conjunto as
        select conjunto, mode(nome) as nome
        from ({" union all ".join(partes)})
        where conjunto is not null
        group by conjunto
    """)
    return con.execute("select count(*) from nome_conjunto").fetchone()[0]


def ponte_e_conjuntos(con) -> tuple[int, int]:
    """Ponte limpa e dimensão de conjunto derivada dela.

    A tabela da ANEEL tem um defeito: cerca de 0,7% dos conjuntos aparecem
    ligados a municípios de UFs diferentes por homonímia. O conjunto 15457 é
    gaúcho — 37 municípios do RS — mas carrega Soledade/PB e Sarandi/PR, que são
    xarás de Soledade/RS e Sarandi/RS. A regra é manter só os vínculos da UF
    majoritária do conjunto.
    """
    origem = BRONZE / "indqual-municipio.csv"

    con.execute(f"""
        create or replace table ponte_bruta as
        select
            cast(IdeConjUnidConsumidoras as integer) as conjunto,
            cast(CodMunicipio as integer)            as municipio_ibge,
            NomMunicipio                             as municipio,
            SigUF                                    as uf
        from read_csv('{origem.as_posix()}', delim=';', header=true, encoding='latin-1')
        where IdeConjUnidConsumidoras is not null and CodMunicipio is not null
    """)

    con.execute("""
        create or replace table ponte_conjunto_municipio as
        with contagem as (
            select conjunto, uf, count(*) n from ponte_bruta group by 1, 2
        ),
        majoritaria as (
            select conjunto, uf from contagem
            qualify row_number() over (partition by conjunto order by n desc, uf) = 1
        )
        select p.conjunto, p.municipio_ibge, p.municipio, p.uf
        from ponte_bruta p
        join majoritaria m on m.conjunto = p.conjunto and m.uf = p.uf
    """)

    descartados = con.execute("""
        select (select count(*) from ponte_bruta)
             - (select count(*) from ponte_conjunto_municipio)
    """).fetchone()[0]
    if descartados:
        log.info("ponte: %s vínculos descartados por homonímia de UF", descartados)

    nomes(con)
    con.execute("""
        create or replace table dim_conjunto as
        select
            p.conjunto,
            n.nome,
            any_value(p.uf)                as uf,
            count(*)                       as qtd_municipios,
            count(*) = 1                   as municipio_unico,
            min(p.municipio_ibge)          as municipio_ibge_unico,
            string_agg(p.municipio, ', ' order by p.municipio) as municipios
        from ponte_conjunto_municipio p
        left join nome_conjunto n using (conjunto)
        group by p.conjunto, n.nome
    """)

    for tabela in ("ponte_conjunto_municipio", "dim_conjunto"):
        destino = PRATA / f"{tabela}.parquet"
        con.execute(
            f"copy {tabela} to '{destino.as_posix()}' (format parquet, compression zstd)"
        )

    return (
        con.execute("select count(*) from ponte_conjunto_municipio").fetchone()[0],
        con.execute("select count(*) from dim_conjunto").fetchone()[0],
    )


def construir() -> dict:
    PRATA.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("set enable_progress_bar=false")

    municipios = dim_municipio(con)
    vinculos, conjuntos = ponte_e_conjuntos(con)

    log.info(
        "dimensões: %s municípios, %s conjuntos, %s vínculos",
        f"{municipios:,}", f"{conjuntos:,}", f"{vinculos:,}",
    )
    return {"municipios": municipios, "conjuntos": conjuntos, "vinculos": vinculos}
