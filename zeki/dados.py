"""Ponto único de acesso ao dado curado.

O painel local lê a camada prata inteira; a versão publicada lê só os agregados
da camada ouro. As duas passam por aqui, então nenhum gráfico precisa saber onde
está rodando — ele pergunta se a tabela existe e se adapta.
"""

import os

import duckdb

from zeki.config import OURO, PRATA

EPOCA = "timestamp '2017-01-01'"

# Detalhes de causa que dependem do tempo. Usado para separar o que o clima
# poderia explicar do que ele não explicaria de jeito nenhum.
DETALHES_CLIMA = (
    "VENTO",
    "DESCARGA ATMOSFERICA",
    "ARVORE OU VEGETACAO",
    "INUNDACAO",
    "EROSAO",
    "QUEIMA OU INCENDIO",
)


def _existe(base, nome) -> bool:
    return (base / f"{nome}.parquet").exists()


def preparar_sessao(con):
    """Ajustes que o DuckDB guarda por sessão — e um cursor é sessão nova.

    O fuso é o que dói: `con.cursor()` volta ao fuso do sistema operacional, e
    como o painel consulta sempre por cursor, a análise de clima rodava em
    America/Sao_Paulo enquanto os dados foram gravados em UTC. Não dá erro, só
    desloca tudo três horas — a taxa de base subia de 0,180 para 0,194 e o
    multiplicador da rajada caía de 4,2× para 3,6× no painel local, contra o
    número certo na versão publicada, que lê o mart pronto.
    """
    con.execute("load icu")
    con.execute("set TimeZone='UTC'")
    con.execute("set enable_progress_bar=false")


def _registrar_cubos(con, tem_fato: bool):
    """Os cubos do painel, vindos do fato ou do ouro.

    É aqui, e só aqui, que a instalação local difere da publicada. Todo gráfico
    consulta os mesmos nomes de tabela nos dois casos.
    """
    from zeki.curadoria.marts import CUBOS

    for nome, sql in CUBOS.items():
        arquivo = OURO / f"{nome}.parquet"
        if tem_fato:
            con.execute(f"create or replace view {nome} as {sql}")
        elif arquivo.exists():
            con.execute(f"create or replace view {nome} as "
                        f"select * from read_parquet('{arquivo.as_posix()}')")


def conectar(base=None) -> duckdb.DuckDBPyConnection:
    # ZEKI_MODO=publicado lê só o ouro mesmo quando a prata existe, para dar
    # para conferir localmente o que o avaliador vai ver. Trocar a camada
    # inteira, e não só esconder o fato: a tabela horária de clima também mora
    # na prata, e deixá-la visível fazia a página de clima tentar a análise ao
    # vivo — que precisa do fato — e quebrar com "interrupcoes does not exist".
    if base is None:
        base = OURO if os.environ.get("ZEKI_MODO") == "publicado" else PRATA
    con = duckdb.connect()
    # ICU traz o banco de fusos. Sem ele não dá para converter horário local
    # brasileiro em UTC respeitando o horário de verão, que existiu até 2019.
    con.execute("install icu")
    preparar_sessao(con)

    fato = base / "interrupcoes"
    if fato.exists():
        clima = ", ".join(f"'{d}'" for d in DETALHES_CLIMA)
        con.execute(f"""
            create or replace view interrupcoes as
            select
                * exclude (inicio_s, duracao_s),
                {EPOCA} + to_seconds(inicio_s)              as inicio,
                {EPOCA} + to_seconds(inicio_s + duracao_s)  as fim,
                duracao_s / 60.0                            as duracao_min,
                -- 6,8% dos registros não têm detalhe de causa. Sem o coalesce a
                -- coluna fica nula e some do denominador de qualquer média, o
                -- que empurra a fração climática de 24,0% para 25,7%. Contar
                -- desconhecido como não-climático é a leitura conservadora: o
                -- número vira "pelo menos tanto".
                coalesce(detalhe in ({clima}), false)       as causa_climatica
            from read_parquet('{(fato / "**" / "*.parquet").as_posix()}',
                              hive_partitioning=true, union_by_name=true)
        """)

    for tabela in ("dim_municipio", "dim_conjunto", "ponte_conjunto_municipio",
                   "geo_municipio", "geo_conjunto",
                   "clima_conjunto_hora", "clima_conjunto_dia", "grade_clima",
                   "peso_conjunto_celula"):
        for camada in (base, OURO):
            if _existe(camada, tabela):
                arquivo = camada / f"{tabela}.parquet"
                con.execute(
                    f"create or replace view {tabela} as "
                    f"select * from read_parquet('{arquivo.as_posix()}')"
                )
                break

    _registrar_cubos(con, tem_fato=fato.exists())

    # Resultados de análise já calculados. Existem para a versão publicada, que
    # não carrega os 42,7 milhões de pares conjunto×hora para refazer a conta.
    for arquivo in sorted(OURO.glob("mart_clima_*.parquet")):
        con.execute(f"create or replace view {arquivo.stem} as "
                    f"select * from read_parquet('{arquivo.as_posix()}')")

    return con


def modo(con) -> str:
    """'completo' quando a prata está presente, 'publicado' quando só há ouro."""
    return "completo" if "interrupcoes" in tabelas(con) else "publicado"


def tabelas(con) -> set[str]:
    return {linha[0] for linha in con.execute("show tables").fetchall()}
