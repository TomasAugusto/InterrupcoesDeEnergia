import streamlit as st

from zeki.painel import consultas, graficos

# O cubo é mensal, então dia não é uma opção — nem local, para os dois
# modos darem exatamente o mesmo número.
GRANULARIDADE = {"Mês": "month", "Trimestre": "quarter", "Ano": "year"}


def _formatar(n, sufixo=""):
    if n is None:
        return "—"
    n = float(n)
    for corte, letra in ((1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
        if abs(n) >= corte:
            return f"{n / corte:,.1f} {letra}{sufixo}".replace(".", ",")
    return f"{n:,.0f}{sufixo}".replace(",", ".")


def _cabecalho(filtro):
    r = consultas.resumo(filtro).iloc[0]
    if not r["interrupcoes"]:
        st.warning("Nenhuma interrupção para este filtro.")
        return False

    colunas = st.columns(5)
    colunas[0].metric("Interrupções", _formatar(r["interrupcoes"]))
    colunas[1].metric("Consumidores afetados", _formatar(r["consumidores"]))
    colunas[2].metric("Duração mediana",
                      f"{r['duracao_mediana']:.0f} min".replace(".", ","))
    colunas[3].metric("Consumidor-hora sem energia",
                      _formatar(r["consumidor_hora"]))
    colunas[4].metric(
        "Ligadas ao tempo",
        f"{100 * r['fracao_climatica']:.1f}%".replace(".", ","),
        help="Vento, descarga atmosférica, árvore ou vegetação, inundação, "
             "erosão e queimada. É um piso: 6,8% dos registros não trazem "
             "detalhe de causa e entram aqui como não-climáticos.",
    )
    return True


def desenhar(filtro):
    st.title("Interrupções de energia no Brasil")
    st.markdown(
        '<p class="nota">Dados abertos da ANEEL, 2017 a 2026. '
        'Até 2025 o grão da fonte é o <b>conjunto elétrico</b>, uma unidade '
        'regulatória que não respeita divisa de município; a partir de 2026 a '
        'ANEEL passou a informar o município. Por isso os mapas e rankings são '
        'por conjunto, sem rateio.</p>',
        unsafe_allow_html=True,
    )

    if not _cabecalho(filtro):
        return

    st.divider()

    esquerda, direita = st.columns([3, 2])
    with esquerda:
        escala = st.radio("Granularidade", list(GRANULARIDADE), index=0,
                          horizontal=True, label_visibility="collapsed")
        grao = GRANULARIDADE[escala]
        st.plotly_chart(
            graficos.serie_temporal(
                consultas.serie(filtro, grao), "interrupcoes",
                "Interrupções ao longo do tempo", "interrupções",
                consultas.janela_completa(grao),
            ),
            width="stretch",
        )
        st.markdown(
            '<p class="nota">As faixas sombreadas marcam períodos de cobertura '
            'irregular: no início, distribuidoras ainda entrando na base; no '
            'fim, o mês corrente, que a ANEEL ainda não fechou.</p>',
            unsafe_allow_html=True,
        )
    with direita:
        st.plotly_chart(
            graficos.calor_hora_semana(
                consultas.hora_por_dia_semana(filtro),
                "Quando começam as interrupções",
            ),
            width="stretch",
        )

    st.plotly_chart(
        graficos.composicao_causa(consultas.por_causa(filtro, "year"),
                                  "Composição por causa, ano a ano",
                                  consultas.opcoes()["causas"]),
        width="stretch",
    )

    st.divider()
    st.subheader("Onde")

    # A medida é escolhida antes da consulta porque ela decide o corte, não só a
    # cor: pedir os 900 com mais registros e pintar por consumidores deixaria de
    # fora 288 conjuntos que pertencem ao mapa quando a pergunta é consumidores.
    medida = st.radio(
        "Medida do mapa", ["interrupcoes", "consumidores"], horizontal=True,
        format_func={"interrupcoes": "Interrupções",
                     "consumidores": "Consumidores afetados"}.get,
        label_visibility="collapsed",
    )
    mapa = consultas.mapa_conjuntos(filtro, medida)
    st.plotly_chart(
        graficos.mapa_conjuntos(
            mapa, medida,
            "Área de atuação dos conjuntos elétricos",
            "interrupções" if medida == "interrupcoes" else "consumidores",
        ),
        width="stretch",
    )
    if len(mapa) >= 900:
        st.caption(
            "Mapa limitado aos 900 conjuntos com mais "
            + ("interrupções" if medida == "interrupcoes"
               else "consumidores afetados")
            + ". Filtre por UF ou região para ver o resto."
        )

    st.divider()
    esquerda, direita = st.columns(2)
    with esquerda:
        # Contagem de registros compara prática de reporte tanto quanto
        # confiabilidade: 52,9% dos registros do país afetam uma única unidade
        # consumidora, e essa fatia vai de 22% a 77% dependendo da distribuidora.
        # Consumidores afetados é a medida comparável, e por isso é a padrão.
        medida_dist = st.radio(
            "Medida do ranking", ["consumidores", "interrupcoes"],
            horizontal=True, label_visibility="collapsed",
            format_func={"consumidores": "Consumidores afetados",
                         "interrupcoes": "Registros de interrupção"}.get,
        )
        st.plotly_chart(
            graficos.ranking(consultas.ranking_distribuidoras(filtro, medida_dist),
                             "distribuidora", medida_dist,
                             "Distribuidoras com mais " + (
                                 "consumidores afetados"
                                 if medida_dist == "consumidores"
                                 else "registros")),
            width="stretch",
        )
        if medida_dist == "interrupcoes":
            st.markdown(
                '<p class="nota">Cuidado ao comparar por contagem: as '
                'distribuidoras reportam em graus diferentes. Metade dos '
                'registros do país afeta uma única unidade consumidora, e essa '
                'fatia vai de 22% a 77% conforme a empresa — quem abre uma linha '
                'por consumidor aparece com mais "interrupções" que quem agrega o '
                'mesmo evento numa linha só.</p>',
                unsafe_allow_html=True,
            )
    with direita:
        conjuntos = consultas.ranking_conjuntos(filtro, "interrupcoes")
        st.plotly_chart(
            graficos.ranking(conjuntos, "rotulo", "interrupcoes",
                             "Conjuntos com mais interrupções"),
            width="stretch",
        )
        with st.expander("Que cidades são esses conjuntos?"):
            st.dataframe(
                conjuntos[["conjunto", "nome", "uf", "qtd_municipios",
                           "municipios", "interrupcoes"]],
                hide_index=True, width="stretch",
            )

    duracao = consultas.distribuicao_duracao(filtro)
    st.plotly_chart(
        graficos.histograma_duracao(duracao, "Quanto tempo duram"),
        width="stretch",
    )
    cauda = graficos.texto_da_cauda(duracao)
    if cauda:
        st.markdown(f'<p class="nota">{cauda}</p>', unsafe_allow_html=True)

    with st.expander("Cobertura da base por ano"):
        st.plotly_chart(
            graficos.cobertura(consultas.cobertura_por_ano(),
                               "Conjuntos que reportaram em cada ano"),
            width="stretch",
        )
        st.markdown(
            '<p class="nota">2017 aparece em destaque porque está incompleto: '
            'cerca de 1.300 conjuntos reportaram, contra ~3.080 de 2018 em '
            'diante. A queda de 2017 para 2018 é entrada de reportantes, não '
            'piora do serviço.</p>',
            unsafe_allow_html=True,
        )
