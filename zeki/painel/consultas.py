"""Consultas do painel, com cache.

Tudo fala com os cubos (`mart_*`), nunca com o fato linha a linha. Local os
cubos são views sobre os 77 milhões de registros; publicados são ~34 MB de
Parquet. Nenhuma consulta daqui sabe em qual dos dois está.
"""

from dataclasses import dataclass

import streamlit as st

from zeki import dados

# Largura da faixa do cubo de duração. A mediana do painel é interpolada dentro
# dela, o que a deixa idêntica nos dois modos em troca de ~7 min de resolução.
FAIXA_MIN = 15


@dataclass(frozen=True)
class Filtro:
    ano_ini: int = 2017
    ano_fim: int = 2026
    ufs: tuple[str, ...] = ()
    regioes: tuple[str, ...] = ()
    municipio_ibge: int | None = None
    distribuidoras: tuple[str, ...] = ()
    causas: tuple[str, ...] = ()
    programada: str = "todas"          # todas | programada | nao
    so_climaticas: bool = False

    def clausulas(self, ano="i.ano") -> list[str]:
        # `ano` é a expressão inteira: os cubos guardam `ano`, o mensal guarda
        # `mes` e precisa de year(i.mes).
        c = [f"{ano} between {self.ano_ini} and {self.ano_fim}"]

        if self.ufs:
            lista = ", ".join(f"'{u}'" for u in self.ufs)
            c.append(f"dc.uf in ({lista})")
        if self.regioes:
            lista = ", ".join(f"'{r}'" for r in self.regioes)
            c.append(f"""i.conjunto in (
                select p.conjunto from ponte_conjunto_municipio p
                join dim_municipio m using (municipio_ibge)
                where m.regiao in ({lista}))""")
        if self.municipio_ibge:
            # Semi-join de propósito: um conjunto que atende cinco cidades
            # multiplicaria as linhas num join comum.
            c.append(f"""i.conjunto in (
                select conjunto from ponte_conjunto_municipio
                where municipio_ibge = {self.municipio_ibge})""")
        if self.distribuidoras:
            lista = ", ".join(f"'{d}'" for d in self.distribuidoras)
            c.append(f"i.distribuidora in ({lista})")
        if self.causas:
            lista = ", ".join(f"'{x}'" for x in self.causas)
            c.append(f"i.causa in ({lista})")
        if self.programada == "programada":
            c.append("i.programada")
        elif self.programada == "nao":
            c.append("not i.programada")
        if self.so_climaticas:
            c.append("i.causa_climatica")

        return c

    def where(self, ano="i.ano") -> str:
        return " and ".join(self.clausulas(ano))

    def where_simples(self, ano="i.ano") -> str:
        """Só as condições que os cubos sem causa nem distribuidora suportam."""
        ignorar = ("i.distribuidora", "i.causa in", "i.programada",
                   "not i.programada")
        mantidas = [
            c for c in self.clausulas(ano)
            if not any(c.startswith(p) or c == p for p in ignorar)
        ]
        return " and ".join(mantidas)


# O corte de "top N" tem que ser pela mesma medida que a tela mostra. Só existem
# estas duas, e a lista fechada é o que mantém o nome longe da interpolação.
MEDIDAS = ("interrupcoes", "consumidores")


def _medida(nome: str) -> str:
    if nome not in MEDIDAS:
        raise ValueError(f"medida desconhecida: {nome}")
    return nome


# LEFT de propósito: ~0,12% das interrupções vêm de conjuntos que não constam
# na ponte da ANEEL. Com join interno elas sumiriam do total sem aviso; assim o
# total fecha e elas só ficam de fora quando há filtro geográfico, que é o
# comportamento certo — não se sabe onde ficam.
MENSAL = "from mart_mensal i left join dim_conjunto dc using (conjunto)"
ANO_MES = "year(i.mes)"


@st.cache_resource
def conexao():
    return dados.conectar()


def cursor():
    """Uma conexão derivada por consulta, obrigatoriamente.

    O Streamlit roda cada execução do script numa thread e a conexão vem de
    `cache_resource`, ou seja, é a mesma para todas. Só que `execute(sql).df()`
    são dois passos: outra thread pode executar entre eles e você busca o
    resultado dela. Medido: 54 resultados trocados em 80 consultas com duas
    threads — a tela pedia causa e recebia UF, o que aparece como KeyError num
    lugar qualquer do gráfico. O cursor enxerga as mesmas views e tem resultado
    próprio — mas não herda as configurações de sessão, daí o preparo.
    """
    cur = conexao().cursor()
    dados.preparar_sessao(cur)
    return cur


def _df(sql: str):
    return cursor().execute(sql).df()


@st.cache_data(show_spinner=False)
def modo() -> str:
    return dados.modo(cursor())


@st.cache_data(show_spinner=False)
def opcoes():
    con = cursor()
    return {
        "ufs": [r[0] for r in con.execute(
            "select distinct uf from dim_conjunto where uf is not null order by 1"
        ).fetchall()],
        "regioes": [r[0] for r in con.execute(
            "select distinct regiao from dim_municipio order by 1").fetchall()],
        "distribuidoras": [r[0] for r in con.execute(
            "select distinct distribuidora from mart_mensal order by 1").fetchall()],
        "causas": [r[0] for r in con.execute(
            "select causa, sum(interrupcoes) n from mart_mensal"
            " where causa is not null group by 1 order by n desc").fetchall()],
        "anos": con.execute(
            "select min(year(mes)), max(year(mes)) from mart_mensal").fetchone(),
    }


@st.cache_data(show_spinner=False)
def municipios_da_uf(ufs: tuple[str, ...]):
    filtro = ""
    if ufs:
        lista = ", ".join(f"'{u}'" for u in ufs)
        filtro = f"where uf in ({lista})"
    return _df(f"""
        select municipio_ibge, municipio || '/' || uf as rotulo
        from dim_municipio {filtro} order by municipio
    """)


@st.cache_data(show_spinner=False)
def duracao_mediana(f: Filtro) -> float | None:
    """Mediana interpolada dentro da faixa de 15 minutos do cubo."""
    linha = cursor().execute(f"""
        with faixas as (
            select i.faixa_min, sum(i.interrupcoes) as n
            from mart_duracao i left join dim_conjunto dc using (conjunto)
            where {f.where_simples()}
            group by 1
        ),
        acumulado as (
            select faixa_min, n,
                   sum(n) over (order by faixa_min) as ate_aqui,
                   sum(n) over ()                   as total
            from faixas
        )
        select faixa_min, n, ate_aqui, total
        from acumulado
        where ate_aqui >= total / 2.0
        order by faixa_min limit 1
    """).fetchone()

    if not linha:
        return None
    faixa, n, ate_aqui, total = linha
    antes = ate_aqui - n
    return faixa + FAIXA_MIN * (total / 2.0 - antes) / n if n else faixa


@st.cache_data(show_spinner=False)
def resumo(f: Filtro):
    df = _df(f"""
        select
            sum(i.interrupcoes)                             as interrupcoes,
            sum(i.consumidores)                             as consumidores,
            sum(i.consumidor_minuto) / 60.0                 as consumidor_hora,
            count(distinct i.conjunto)                      as conjuntos,
            sum(case when i.causa_climatica then i.interrupcoes else 0 end)
                / nullif(sum(i.interrupcoes), 0)            as fracao_climatica
        {MENSAL} where {f.where(ANO_MES)}
    """)
    df["duracao_mediana"] = duracao_mediana(f)
    return df


@st.cache_data(show_spinner=False)
def janela_completa(granularidade: str = "month"):
    """Primeiro e último período com cobertura cheia de reportantes.

    As pontas da base são irregulares: 2017 entrou aos poucos (cerca de 1.300
    conjuntos contra ~3.080 depois) e o arquivo do ano corrente termina com um
    resto de poucos reportantes — agosto de 2026 tem 56 registros de 25
    conjuntos. Plotado cru isso vira uma rampa e um precipício que são só
    calendário. O corte é por cobertura, não por posição.
    """
    return cursor().execute(f"""
        with base as (
            select date_trunc('{granularidade}', mes) as periodo,
                   count(distinct conjunto)           as conjuntos
            from mart_mensal group by 1
        )
        select min(periodo), max(periodo) from base
        where conjuntos >= 0.5 * (select median(conjuntos) from base)
    """).fetchone()


@st.cache_data(show_spinner=False)
def serie(f: Filtro, granularidade: str = "month"):
    """Série cheia. O trecho de cobertura baixa vem marcado, não removido."""
    return _df(f"""
        select date_trunc('{granularidade}', i.mes) as periodo,
               sum(i.interrupcoes)                  as interrupcoes,
               sum(i.consumidores)                  as consumidores
        {MENSAL} where {f.where(ANO_MES)}
        group by 1 order by 1
    """)


@st.cache_data(show_spinner=False)
def por_causa(f: Filtro, granularidade: str = "year"):
    return _df(f"""
        select date_trunc('{granularidade}', i.mes) as periodo,
               coalesce(i.causa, 'NAO INFORMADA')   as causa,
               sum(i.interrupcoes)                  as interrupcoes
        {MENSAL} where {f.where(ANO_MES)}
        group by 1, 2 order by 1
    """)


@st.cache_data(show_spinner=False)
def ranking_conjuntos(f: Filtro, medida: str = "interrupcoes", limite: int = 15):
    # O código sozinho não diz nada, então o rótulo usa o nome que a própria
    # ANEEL dá ao conjunto. Quando ele cobre mais de um município o rótulo diz
    # quantos, em vez de eleger uma cidade como se fosse a principal.
    return _df(f"""
        select i.conjunto, dc.nome, dc.uf, dc.qtd_municipios, dc.municipios,
               coalesce(dc.nome, 'Conjunto ' || i.conjunto)
                 || case when dc.qtd_municipios > 1
                         then ' · ' || dc.qtd_municipios || ' municípios'
                         else ' · ' || dc.municipios end  as rotulo,
               sum(i.interrupcoes) as interrupcoes,
               sum(i.consumidores) as consumidores
        {MENSAL} where {f.where(ANO_MES)}
        group by 1, 2, 3, 4, 5
        order by {_medida(medida)} desc limit {limite}
    """)


@st.cache_data(show_spinner=False)
def ranking_distribuidoras(f: Filtro, medida: str = "consumidores",
                           limite: int = 15):
    return _df(f"""
        select i.distribuidora,
               sum(i.interrupcoes) as interrupcoes,
               sum(i.consumidores) as consumidores,
               sum(case when i.causa_climatica then i.interrupcoes else 0 end)
                 / nullif(sum(i.interrupcoes), 0) as fracao_climatica
        {MENSAL} where {f.where(ANO_MES)}
        group by 1 order by {_medida(medida)} desc limit {limite}
    """)


@st.cache_data(show_spinner=False)
def mapa_conjuntos(f: Filtro, medida: str = "interrupcoes", limite: int = 900):
    return _df(f"""
        select i.conjunto, dc.nome, dc.uf, dc.municipios, dc.qtd_municipios,
               sum(i.interrupcoes) as interrupcoes,
               sum(i.consumidores) as consumidores,
               any_value(g.wkt)    as wkt
        {MENSAL}
        join geo_conjunto g using (conjunto)
        where {f.where(ANO_MES)}
        group by 1, 2, 3, 4, 5
        order by {_medida(medida)} desc limit {limite}
    """)


@st.cache_data(show_spinner=False)
def hora_por_dia_semana(f: Filtro):
    # Este cubo não guarda causa nem distribuidora — o filtro geográfico, o de
    # período e o de causa climática valem, os demais não se aplicam.
    return _df(f"""
        select i.dia_semana, i.hora, sum(i.interrupcoes) as interrupcoes
        from mart_hora_semana i left join dim_conjunto dc using (conjunto)
        where {f.where_simples()}
        group by 1, 2
    """)


@st.cache_data(show_spinner=False)
def distribuicao_duracao(f: Filtro):
    return _df(f"""
        select i.faixa_min, sum(i.interrupcoes) as interrupcoes
        from mart_duracao i left join dim_conjunto dc using (conjunto)
        where {f.where_simples()}
        group by 1 order by 1
    """)


@st.cache_data(show_spinner=False)
def cobertura_por_ano():
    return _df("""
        select year(mes) as ano, count(distinct conjunto) as conjuntos,
               sum(interrupcoes) as interrupcoes
        from mart_mensal group by 1 order by 1
    """)
