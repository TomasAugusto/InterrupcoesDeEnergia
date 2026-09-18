"""Cruzamento entre clima e interrupção, em Minas Gerais.

O ERA5 é UTC e a ANEEL grava horário local. A conversão acontece do lado da
interrupção — uma coluna, não 42 milhões de linhas — e usa o banco de fusos do
ICU, nunca offset fixo: o Brasil teve horário de verão até fevereiro de 2019 e
MG estava na área, então os verões de 2017, 2018 e o começo de 2019 são UTC-2 e
o resto UTC-3. Errar isso desloca tudo em uma hora e chega a inverter o sinal da
defasagem.
"""

FUSO = "America/Sao_Paulo"

# Em UTC, para casar direto com a grade do ERA5.
HORA_UTC = f"cast((i.inicio at time zone '{FUSO}') as timestamp)"

# As faixas seguem a distribuição medida, não números redondos: a média de área
# sobre ~11 células suaviza o extremo, então 60,7% das horas são zero, o
# percentil 99 fica em 2,2 mm e o máximo em 24,3 mm. Faixas de 10 em 10 mm
# deixariam as duas de cima com algumas dezenas de observações.
FAIXAS_CHUVA = [
    ("sem chuva", "chuva = 0"),
    ("até 0,5 mm", "chuva > 0 and chuva < 0.5"),
    ("0,5–1 mm", "chuva >= 0.5 and chuva < 1"),
    ("1–2 mm", "chuva >= 1 and chuva < 2"),
    ("2–5 mm", "chuva >= 2 and chuva < 5"),
    ("5 mm ou mais", "chuva >= 5"),
]

FAIXAS_RAJADA = [
    ("até 20 km/h", "rajada < 20"),
    ("20–30", "rajada >= 20 and rajada < 30"),
    ("30–40", "rajada >= 30 and rajada < 40"),
    ("40–50", "rajada >= 40 and rajada < 50"),
    ("50–60", "rajada >= 50 and rajada < 60"),
    ("60 km/h ou mais", "rajada >= 60"),
]

# Acima disso a hora conta como evento de chuva forte para o perfil de
# defasagem. 5 mm de média de área numa hora já é pancada, e dá 30.954
# eventos — em 10 mm sobrariam 1.296, pouco para um perfil estável.
LIMIAR_EVENTO_MM = 5
JANELA_H = 48


def _horas_com_interrupcao(filtro) -> str:
    return f"""
        select i.conjunto,
               date_trunc('hour', {HORA_UTC}) as hora_utc,
               count(*)                       as interrupcoes
        from interrupcoes i
        join dim_conjunto dc using (conjunto)
        where {filtro.where('i.ano')}
        group by 1, 2
    """


def _base(filtro) -> str:
    """Todas as horas de todos os conjuntos, com e sem interrupção.

    O left join é o ponto: sem as horas de zero interrupção não há denominador,
    e a taxa vira contagem disfarçada de taxa.
    """
    return f"""
        select c.conjunto,
               c.instante_utc,
               c.chuva_c  / 100.0            as chuva,
               c.rajada_c / 100.0            as rajada,
               coalesce(o.interrupcoes, 0)   as interrupcoes,
               hour(c.instante_utc at time zone 'UTC'
                    at time zone '{FUSO}')   as hora_local,
               month(c.instante_utc)         as mes
        from clima_conjunto_hora c
        left join ({_horas_com_interrupcao(filtro)}) o
               on o.conjunto = c.conjunto and o.hora_utc = c.instante_utc
    """


def _curva(con, filtro, faixas, coluna):
    casos = "\n".join(
        f"when {cond} then {i}" for i, (_, cond) in enumerate(faixas)
    )
    rotulos = ", ".join(f"'{r}'" for r, _ in faixas)
    return con.execute(f"""
        with base as ({_base(filtro)}),
        marcado as (
            select case {casos} end as faixa_id, interrupcoes from base
        )
        select
            [{rotulos}][faixa_id + 1]                as faixa,
            faixa_id,
            count(*)                                 as conjunto_horas,
            sum(interrupcoes)                        as interrupcoes,
            sum(interrupcoes) * 1.0 / count(*)       as taxa
        from marcado
        where faixa_id is not null
        group by 1, 2 order by faixa_id
    """).df()


def risco_por_chuva(con, filtro):
    return _curva(con, filtro, FAIXAS_CHUVA, "chuva")


def risco_por_rajada(con, filtro):
    return _curva(con, filtro, FAIXAS_RAJADA, "rajada")


# Horas secas exigidas antes de uma hora de chuva forte para ela contar como
# início de temporal.
SECAS_ANTES = 6


def perfil_defasagem(con, filtro, limiar=LIMIAR_EVENTO_MM, janela=JANELA_H,
                     so_inicio=True):
    """Interrupções por hora em torno do começo do temporal.

    Centrar em qualquer hora de chuva forte devolve um perfil quase simétrico, e
    isso não é sinal de nada: chuva é autocorrelacionada, então a hora -3 e a +3
    de uma hora chuvosa também costumam ser chuvosas. Para enxergar direção o
    evento precisa ser o **início** — primeira hora forte depois de um período
    seco. Aí, se a massa de interrupções ficar à direita do zero, a chuva
    precede a queda de verdade.
    """
    corte = (f"and not exists (select 1 from base a"
             f" where a.conjunto = base.conjunto"
             f" and a.instante_utc between base.instante_utc"
             f" - interval '{SECAS_ANTES} hours'"
             f" and base.instante_utc - interval '1 hour'"
             f" and a.chuva >= {limiar})") if so_inicio else ""

    return con.execute(f"""
        with base as ({_base(filtro)}),
        eventos as (
            select conjunto, instante_utc
            from base
            where chuva >= {limiar} {corte}
        ),
        -- Temporal em MG cai de tarde, e de tarde já há mais interrupção de
        -- qualquer jeito. Sem descontar o ciclo diário, o perfil mostra picos
        -- espúrios de 24 em 24 horas e superestima o efeito da chuva. A mesma
        -- conta desconta a sazonalidade, que também afeta os dois lados.
        esperado as (
            select mes, hora_local,
                   sum(interrupcoes) * 1.0 / count(*) as taxa_normal
            from base group by 1, 2
        ),
        vizinhanca as (
            select
                cast(date_diff('hour', e.instante_utc, b.instante_utc) as integer) as hora_rel,
                b.interrupcoes,
                n.taxa_normal
            from eventos e
            join base b
              on b.conjunto = e.conjunto
             and b.instante_utc between e.instante_utc - interval '{janela} hours'
                                    and e.instante_utc + interval '{janela} hours'
            join esperado n on n.mes = b.mes and n.hora_local = b.hora_local
        )
        select hora_rel,
               count(*)                                as conjunto_horas,
               sum(interrupcoes)                       as interrupcoes,
               sum(interrupcoes) * 1.0 / count(*)      as taxa,
               sum(taxa_normal) / count(*)             as taxa_esperada,
               sum(interrupcoes) / nullif(sum(taxa_normal), 0) as lift
        from vizinhanca
        group by 1 order by 1
    """).df()
