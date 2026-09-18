"""Bronze -> prata: normaliza, ordena e grava o fato de interrupções."""

import logging
import re

import duckdb

from zeki.config import BRONZE, PRATA
from zeki.curadoria import esquema

log = logging.getLogger(__name__)

ANO_NO_ARQUIVO = re.compile(r"interrupcoes-(\d{4})\.parquet$")


def _colunas(con, caminho) -> list[str]:
    return [
        linha[0]
        for linha in con.execute(
            f"describe select * from read_parquet('{caminho.as_posix()}')"
        ).fetchall()
    ]


def anos_disponiveis() -> dict[int, object]:
    achados = {}
    for arquivo in sorted(BRONZE.glob("interrupcoes-*.parquet")):
        m = ANO_NO_ARQUIVO.search(arquivo.name)
        if m:
            achados[int(m.group(1))] = arquivo
    return achados


def curar(anos: list[int] | None = None, con=None) -> dict[int, int]:
    con = con or duckdb.connect()
    destino = PRATA / "interrupcoes"
    destino.mkdir(parents=True, exist_ok=True)

    escritos = {}
    for ano, bronze in anos_disponiveis().items():
        if anos and ano not in anos:
            continue

        sql = esquema.sql_normalizacao(bronze, _colunas(con, bronze), ano)
        saida = destino / f"ano={ano}"
        saida.mkdir(parents=True, exist_ok=True)
        arquivo = saida / "parte-0.parquet"

        # Ordenar antes de gravar é o que faz a compressão valer a pena: medido
        # na base de 2025, cai de 7,5 para 6,1 bytes por linha.
        con.execute(f"""
            copy ({sql} order by conjunto, inicio)
            to '{arquivo.as_posix()}'
            (format parquet, compression zstd, compression_level 9)
        """)

        linhas = con.execute(
            f"select count(*) from read_parquet('{arquivo.as_posix()}')"
        ).fetchone()[0]
        escritos[ano] = linhas
        log.info(
            "ano %s curado: %s linhas, %.0f MB (%.2f B/linha)",
            ano, f"{linhas:,}", arquivo.stat().st_size / 1e6,
            arquivo.stat().st_size / linhas,
        )

    return escritos
