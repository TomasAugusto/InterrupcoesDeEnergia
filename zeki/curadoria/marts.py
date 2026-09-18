"""Prata -> ouro: os cubos que o painel realmente consulta.

O painel nunca lê o fato linha a linha. Ele lê três cubos, e é isso que permite
a mesma tela rodar local sobre 77 milhões de linhas e publicada sobre ~46 MB de
agregado: local os cubos são views sobre o fato, publicados são Parquet. Nenhum
gráfico sabe em qual dos dois está.
"""

import logging
import os
import time

import duckdb

from zeki.config import OURO, PRATA, UF_CLIMA

log = logging.getLogger(__name__)

# Grão mais fino que o painel oferece. Dia e interrupção individual só existem
# na instalação local, e a tela desabilita essas opções quando faltam.
CUBOS = {
    # Série mensal, composição por causa, rankings e mapa saem todos daqui.
    "mart_mensal": """
        select
            i.conjunto,
            date_trunc('month', i.inicio)  as mes,
            coalesce(i.causa, 'NAO INFORMADA') as causa,
            i.programada,
            i.causa_climatica,
            i.distribuidora,
            count(*)                       as interrupcoes,
            sum(i.consumidores_afetados)   as consumidores,
            sum(i.duracao_min)             as duracao_total_min,
            -- Consumidor-minuto precisa ser somado por interrupção. Multiplicar
            -- os dois somatórios depois daria um número sem significado.
            sum(i.duracao_min * i.consumidores_afetados) as consumidor_minuto
        from interrupcoes i
        group by 1, 2, 3, 4, 5, 6
    """,
    "mart_hora_semana": """
        select
            i.conjunto,
            i.ano,
            dayofweek(i.inicio) as dia_semana,
            hour(i.inicio)      as hora,
            i.causa_climatica,
            count(*)            as interrupcoes
        from interrupcoes i
        group by 1, 2, 3, 4, 5
    """,
    # Faixas de 15 min até 12 horas; acima disso, faixas largas. Jogar toda a
    # cauda num balde só escondia que 15,4% das interrupções passam de 12h e
    # 4,9% passam de 24h — e misturava apagão real de 13 horas com registro de
    # 730 dias, que é ano digitado errado no campo de fim.
    "mart_duracao": """
        select
            i.conjunto,
            i.ano,
            i.causa_climatica,
            case when i.duracao_min < 720  then floor(i.duracao_min / 15) * 15
                 when i.duracao_min < 1440 then 720
                 when i.duracao_min < 4320 then 1440
                 else 4320 end               as faixa_min,
            count(*) as interrupcoes
        from interrupcoes i
        where i.duracao_min >= 0
        group by 1, 2, 3, 4
    """,
}

# Dimensões e geometria são pequenas e vão inteiras para o ouro, para a versão
# publicada não depender da prata em nada.
COPIAR = ["dim_municipio", "dim_conjunto", "ponte_conjunto_municipio",
          "geo_conjunto"]

LIMITE_GITHUB_MB = 100


def _gravar(con, sql: str, alvo, compressao=9):
    """Grava num arquivo ao lado e só então substitui o bom.

    O painel lê esta pasta enquanto a atualização mensal roda, e `copy to`
    trunca o arquivo antes de reescrevê-lo — uma consulta que caísse no meio
    veria um Parquet pela metade. Com a troca no fim, a janela ruim é o próprio
    rename. No Windows ele falha se alguém estiver lendo bem naquele instante,
    daí as tentativas.
    """
    temporario = alvo.parent / (alvo.name + ".novo")
    con.execute(f"""
        copy ({sql})
        to '{temporario.as_posix()}'
        (format parquet, compression zstd, compression_level {compressao})
    """)

    for tentativa in range(5):
        try:
            os.replace(temporario, alvo)
            return
        except PermissionError:
            if tentativa == 4:
                raise
            time.sleep(0.5)


def _clima(con, resultado):
    """Resultados da análise de clima, já calculados.

    Os 42,7 milhões de pares conjunto×hora não cabem na versão publicada, mas o
    resultado da análise cabe: são algumas dezenas de linhas. O período é o
    inteiro — a página avisa que ali os filtros não valem.
    """
    if "clima_conjunto_hora" not in {t[0] for t in
                                     con.execute("show tables").fetchall()}:
        log.info("sem camada de clima, pulando os marts de clima")
        return

    from zeki.analise import clima as analise
    from zeki.painel.consultas import Filtro

    f = Filtro(ufs=(UF_CLIMA,))
    for nome, fn in (("risco_por_chuva", analise.risco_por_chuva),
                     ("risco_por_rajada", analise.risco_por_rajada),
                     ("perfil_defasagem", analise.perfil_defasagem)):
        df = fn(con, f)
        alvo = OURO / f"mart_clima_{nome}.parquet"
        con.register("clima_tmp", df)
        _gravar(con, "select * from clima_tmp", alvo, compressao=3)
        resultado[f"mart_clima_{nome}"] = (len(df), alvo.stat().st_size / 1e6)
        log.info("mart_clima_%s: %s linhas", nome, len(df))


def construir(con=None) -> dict[str, tuple[int, float]]:
    from zeki import dados

    con = con or dados.conectar()
    OURO.mkdir(parents=True, exist_ok=True)

    resultado = {}
    for nome, sql in CUBOS.items():
        alvo = OURO / f"{nome}.parquet"
        _gravar(con, f"{sql} order by conjunto, 2", alvo)
        linhas = con.execute(
            f"select count(*) from read_parquet('{alvo.as_posix()}')"
        ).fetchone()[0]
        mb = alvo.stat().st_size / 1e6
        resultado[nome] = (linhas, mb)
        log.info("%s: %s linhas, %.1f MB", nome, f"{linhas:,}", mb)

    for nome in COPIAR:
        origem = PRATA / f"{nome}.parquet"
        if not origem.exists():
            log.warning("%s não existe na prata, pulando", nome)
            continue
        alvo = OURO / f"{nome}.parquet"
        _gravar(con, f"select * from read_parquet('{origem.as_posix()}')",
                alvo, compressao=3)
        resultado[nome] = (0, alvo.stat().st_size / 1e6)

    _clima(con, resultado)

    grandes = [(n, mb) for n, (_, mb) in resultado.items()
               if mb > LIMITE_GITHUB_MB]
    if grandes:
        raise RuntimeError(
            "arquivos acima do limite de 100 MB do GitHub: "
            + ", ".join(f"{n} ({mb:.0f} MB)" for n, mb in grandes)
        )

    total = sum(mb for _, mb in resultado.values())
    log.info("ouro: %s arquivos, %.1f MB no total", len(resultado), total)
    return resultado
