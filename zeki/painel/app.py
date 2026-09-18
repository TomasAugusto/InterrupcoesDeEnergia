import sys
from pathlib import Path

import streamlit as st

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zeki.config import UF_CLIMA
from zeki.painel import atualizador, brasil, clima, consultas, tema

st.set_page_config(page_title="Interrupções de energia × clima",
                   page_icon="⚡", layout="wide")
tema.registrar()

ESTILO = """
<style>
  section.main > div { padding-top: 1.2rem; }
  [data-testid="stMetricValue"] { font-size: 1.7rem; }
  [data-testid="stMetricLabel"] { color: #52514e; }
  .nota { color:#52514e; font-size:0.86rem; line-height:1.45; }
</style>
"""


def barra_de_filtros():
    op = consultas.opcoes()
    ano_min, ano_max = op["anos"]

    with st.sidebar:
        st.markdown("### Filtros")
        anos = st.slider("Período", ano_min, ano_max, (ano_min, ano_max))

        regioes = st.multiselect("Região", op["regioes"],
                                 placeholder="Todas as regiões")
        ufs = st.multiselect("UF", op["ufs"], placeholder="Todas as UFs")

        municipios = consultas.municipios_da_uf(tuple(ufs))
        rotulos = ["(todos)"] + municipios["rotulo"].tolist()
        escolha = st.selectbox("Município", rotulos, index=0)
        municipio_ibge = None
        if escolha != "(todos)":
            municipio_ibge = int(
                municipios.loc[municipios["rotulo"] == escolha,
                               "municipio_ibge"].iloc[0]
            )
            st.caption(
                "O dado até 2025 é por conjunto elétrico. Este filtro traz as "
                "interrupções dos conjuntos que atendem a cidade."
            )

        distribuidoras = st.multiselect("Distribuidora", op["distribuidoras"],
                                        placeholder="Todas as distribuidoras")
        causas = st.multiselect("Causa", op["causas"],
                                placeholder="Todas as causas",
                                format_func=lambda c: c.capitalize())

        programada = st.radio(
            "Tipo", ["todas", "nao", "programada"], horizontal=True,
            format_func={"todas": "Todas", "nao": "Não programada",
                         "programada": "Programada"}.get,
        )
        so_clima = st.toggle(
            "Só causas ligadas ao tempo",
            help="Vento, descarga atmosférica, árvore ou vegetação, "
                 "inundação, erosão e queimada.",
        )

    return consultas.Filtro(
        ano_ini=anos[0], ano_fim=anos[1],
        ufs=tuple(ufs), regioes=tuple(regioes), municipio_ibge=municipio_ibge,
        distribuidoras=tuple(distribuidoras), causas=tuple(causas),
        programada=programada, so_climaticas=so_clima,
    )


def main():
    st.markdown(ESTILO, unsafe_allow_html=True)
    atualizador.desenhar()

    aba = st.sidebar.radio(
        "Painel", ["Brasil", f"{UF_CLIMA} e clima"], label_visibility="collapsed"
    )
    filtro = barra_de_filtros()

    if aba == "Brasil":
        brasil.desenhar(filtro)
    else:
        clima.desenhar(filtro)


main()
