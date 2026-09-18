"""Auditoria da base curada.

Existe porque a fonte é atualizada todo mês e o que chega no mês que vem pode
não se parecer com o que chegou neste. Rodar isto depois de cada `curar` mostra
se apareceu valor impossível novo, se a grade de clima ficou com buraco ou se
algum total parou de fechar.

Nada aqui corrige dado. O projeto não apaga registro da fonte: o que a ANEEL
publicou fica, e o que é suspeito é sinalizado.
"""

import logging

log = logging.getLogger(__name__)

# (rótulo, condição, tolerado)
#
# `tolerado` é o que a fonte já trazia quando isto foi escrito — defeito da
# ANEEL que não vai sumir e que o projeto não apaga. Passar do limite é que é
# notícia: ou a fonte piorou, ou a curadoria quebrou. Verificação que vive
# vermelha ninguém lê.
#
# None = qualquer ocorrência é falha.
FATO = [
    ("conjunto nulo", "conjunto is null", 0),
    ("início nulo", "inicio is null", 0),
    ("início fora de 2017–2026", "year(inicio) not between 2017 and 2026", 0),
    ("consumidores afetados negativo", "consumidores_afetados < 0", 0),
    ("duração negativa (fim antes do início)", "duracao_min < 0", 1),
    ("afetados maior que o conjunto inteiro",
     "consumidores_afetados > consumidores_conjunto", 5_055),
    ("ano de competência diferente do ano de início", "ano <> year(inicio)", None),
    ("duração zero", "duracao_min = 0", None),
    ("nenhum consumidor afetado", "consumidores_afetados = 0", None),
    ("sem detalhe de causa", "detalhe is null", None),
    ("sem causa", "causa is null", None),
    ("nível de tensão 9999 (sentinela de desconhecido)", "nivel_tensao = 9999", None),
    ("duração acima de três dias", "duracao_min > 4320", None),
]


def _linha(rotulo, n, total, tolerado):
    if tolerado is None:
        marca = "aviso" if n else "  ok "
    elif n > tolerado:
        marca = "FALHA"
    else:
        marca = "  ok "
    pct = f"{100 * n / total:7.3f}%" if n and total else ""
    limite = f"  (tolerado {tolerado:,})" if tolerado else ""
    return f"  {marca}  {rotulo:<48} {n:>11,} {pct}{limite}"


def auditar(con=None) -> list[str]:
    """Devolve os problemas graves encontrados. Lista vazia é o esperado."""
    from zeki import dados

    con = con or dados.conectar()
    tabelas = dados.tabelas(con)
    graves = []

    if "interrupcoes" not in tabelas:
        log.warning("camada prata ausente; auditando só o que houver no ouro")
    else:
        total = con.execute("select count(*) from interrupcoes").fetchone()[0]
        log.info("FATO — %s linhas", f"{total:,}")
        for rotulo, cond, tolerado in FATO:
            n = con.execute(
                f"select count(*) from interrupcoes where {cond}"
            ).fetchone()[0]
            log.info(_linha(rotulo, n, total, tolerado))
            if tolerado is not None and n > tolerado:
                graves.append(f"{rotulo}: {n:,} (tolerado {tolerado:,})")

        log.info("")
        log.info("INTEGRIDADE REFERENCIAL")
        for rotulo, sql, grave in [
            ("conjunto do fato fora da ponte da ANEEL", """
                select count(*) from interrupcoes i
                left join dim_conjunto d using (conjunto) where d.conjunto is null
             """, None),
            ("município da ponte fora do IBGE", """
                select count(*) from ponte_conjunto_municipio p
                left join dim_municipio m using (municipio_ibge)
                where m.municipio_ibge is null
             """, 0),
            ("conjunto da ponte sem geometria", """
                select count(*) from (select distinct conjunto
                                      from ponte_conjunto_municipio) p
                left join geo_conjunto g using (conjunto) where g.conjunto is null
             """, 0),
        ]:
            n = con.execute(sql).fetchone()[0]
            log.info(_linha(rotulo, n, total, grave))
            if grave is not None and n > grave:
                graves.append(f"{rotulo}: {n:,}")

        log.info("")
        log.info("O TOTAL FECHA ENTRE AS CAMADAS")
        cubo = con.execute("select sum(interrupcoes) from mart_mensal").fetchone()[0]
        bate = int(cubo or 0) == total
        log.info("  %s  fato %s  ×  cubo mensal %s",
                 "  ok " if bate else "FALHA", f"{total:,}", f"{int(cubo or 0):,}")
        if not bate:
            graves.append(f"fato ({total:,}) não bate com o cubo ({int(cubo or 0):,})")

    if "clima_conjunto_hora" in tabelas:
        log.info("")
        log.info("CLIMA")
        c, horas, conjuntos = con.execute("""
            select count(*), count(distinct instante_utc), count(distinct conjunto)
            from clima_conjunto_hora
        """).fetchone()
        for rotulo, cond in [
            ("chuva ou rajada nula", "chuva_c is null or rajada_c is null"),
            ("chuva negativa", "chuva_c < 0"),
            ("rajada não positiva", "rajada_c <= 0"),
            ("chuva acima de 100 mm/h", "chuva_c > 10000"),
            ("rajada acima de 150 km/h", "rajada_c > 15000"),
        ]:
            n = con.execute(
                f"select count(*) from clima_conjunto_hora where {cond}"
            ).fetchone()[0]
            log.info(_linha(rotulo, n, c, 0))
            if n:
                graves.append(f"clima, {rotulo}: {n:,}")

        # A grade tem que ser um retângulo cheio: todo conjunto tem todas as
        # horas. Buraco aqui vira denominador errado na curva de risco.
        completa = horas * conjuntos == c
        log.info("  %s  grade cheia: %s conjuntos × %s horas = %s",
                 "  ok " if completa else "FALHA",
                 f"{conjuntos:,}", f"{horas:,}", f"{c:,}")
        if not completa:
            graves.append(f"grade de clima com buracos: {horas * conjuntos - c:,} pares faltando")

    log.info("")
    if graves:
        log.warning("%s verificação(ões) grave(s) falharam", len(graves))
    else:
        log.info("nenhuma verificação grave falhou")
    return graves


def grao_por_distribuidora(con=None):
    """Quantos registros a distribuidora gasta para relatar um mesmo evento.

    Não é problema de qualidade, é diferença de prática — e muda a leitura de
    qualquer ranking por contagem. Distribuidora que abre uma linha por unidade
    consumidora aparece com mais "interrupções" que outra que agrega o mesmo
    evento numa linha só.
    """
    from zeki import dados

    con = con or dados.conectar()
    return con.execute("""
        select distribuidora,
               count(*)                                     as registros,
               sum(consumidores_afetados)                   as consumidores,
               100.0 * sum(case when consumidores_afetados = 1 then 1 else 0 end)
                     / count(*)                             as pct_uma_unidade
        from interrupcoes
        group by 1 having count(*) > 100000
        order by pct_uma_unidade desc
    """).df()
