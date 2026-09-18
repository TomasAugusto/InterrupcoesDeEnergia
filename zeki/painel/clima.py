import streamlit as st

from zeki import dados
from zeki.config import UF_CLIMA
from zeki.painel import consultas, graficos


@st.cache_data(show_spinner=False)
def _analise(nome: str, f: consultas.Filtro):
    """Roda a análise ao vivo quando há a tabela horária; senão usa o mart.

    Local o cruzamento roda sobre 42,7 milhões de linhas em poucos segundos. Na
    versão publicada só existe o resultado pré-calculado do período inteiro.
    """
    con = consultas.cursor()
    tabelas = dados.tabelas(con)

    if "clima_conjunto_hora" in tabelas:
        from zeki.analise import clima as analise

        return getattr(analise, nome)(con, f)

    mart = f"mart_clima_{nome}"
    if mart in tabelas:
        return con.execute(f"select * from {mart}").df()
    return None


def _tem_clima() -> bool:
    t = dados.tabelas(consultas.cursor())
    return "clima_conjunto_hora" in t or "mart_clima_risco_por_chuva" in t


def _multiplicador(df) -> float | None:
    """Quantas vezes a faixa mais alta é mais arriscada que a de base.

    É a última faixa, não o máximo da curva: o rótulo do número diz "60 km/h ou
    mais" e "5 mm/h ou mais", e na chuva as duas coisas não coincidem — a faixa
    de 2 a 5 mm dá 2,8× contra 2,6× da mais alta, que tem quinze vezes menos
    observações. Usar o máximo punha no cartão um número de outra faixa.
    """
    if df is None or df.empty or not df["taxa"].iloc[0]:
        return None
    return float(df["taxa"].iloc[-1] / df["taxa"].iloc[0])


def _resposta(chuva, rajada, defasagem):
    """O achado em três frases, antes de qualquer gráfico.

    A versão anterior desta página abria direto nos gráficos, com o eixo em
    "interrupções por conjunto-hora". Ninguém lê 0,753 e conclui alguma coisa —
    a conclusão existia, mas exigia que o leitor fizesse a divisão de cabeça.
    """
    m_rajada = _multiplicador(rajada)
    m_chuva = _multiplicador(chuva)

    pico = None
    if defasagem is not None and not defasagem.empty:
        linha = defasagem.loc[defasagem["lift"].idxmax()]
        antes = defasagem[(defasagem["hora_rel"] >= -6) & (defasagem["hora_rel"] < 0)]
        pico = (int(linha["hora_rel"]), float(linha["lift"]),
                float(antes["lift"].mean()) if len(antes) else None)

    st.markdown("### A resposta")

    colunas = st.columns(3)
    if m_rajada:
        colunas[0].metric("Vento forte multiplica o risco por",
                          f"{m_rajada:.1f}×".replace(".", ","),
                          help="Rajada de 60 km/h ou mais, comparada a horas "
                               "com menos de 20 km/h.")
    if m_chuva:
        colunas[1].metric("Chuva forte multiplica por",
                          f"{m_chuva:.1f}×".replace(".", ","),
                          help="Chuva de 5 mm/h ou mais na média de área do "
                               "conjunto, comparada a horas sem chuva.")
    if pico:
        colunas[2].metric("Pico depois do temporal começar",
                          f"{pico[0]:+d}h".replace("+", "+"),
                          help="Hora em que a taxa de interrupção mais se "
                               "afasta do normal para aquele horário e mês.")

    partes = []
    if m_rajada and m_chuva:
        partes.append(
            f"Em {UF_CLIMA}, <b>o vento explica mais que a chuva</b>: hora com "
            f"rajada acima de 60 km/h tem <b>{m_rajada:.1f}× o risco</b> de "
            f"interrupção de uma hora de tempo calmo, contra {m_chuva:.1f}× da "
            "chuva forte.".replace(".", ",", 2)
        )
    if pico and pico[2] is not None:
        partes.append(
            f"E o tempo <b>vem antes da queda</b>: nas seis horas que antecedem "
            f"um temporal a taxa está em {pico[2]:.2f}× o normal — ou seja, "
            f"normal — e o pico vem <b>{pico[0]:+d} hora</b> depois que ele "
            f"começa.".replace(".", ",", 1)
        )

    if partes:
        st.markdown(
            f'<p class="nota" style="font-size:.95rem">{" ".join(partes)}</p>',
            unsafe_allow_html=True,
        )


def desenhar(filtro):
    st.title(f"{UF_CLIMA}: o tempo explica as quedas de energia?")
    st.markdown(
        f'<p class="nota">Dez anos de reanálise ERA5 horária cruzados com as '
        f'interrupções de {UF_CLIMA} — 42,7 milhões de pares conjunto×hora. A '
        f'chuva e o vento de cada conjunto são a <b>média ponderada pela área</b> '
        f'das células de 25 km que ele cobre.</p>',
        unsafe_allow_html=True,
    )

    filtro_mg = consultas.Filtro(**{**filtro.__dict__, "ufs": (UF_CLIMA,)})

    if not _tem_clima():
        st.info(
            "A camada de clima ainda não foi carregada. Rode "
            "`python cli.py clima` e depois `python cli.py curar-clima`."
        )
        st.plotly_chart(
            graficos.composicao_causa(consultas.por_causa(filtro_mg, "year"),
                                      f"Composição por causa em {UF_CLIMA}",
                                      consultas.opcoes()["causas"]),
            width="stretch",
        )
        return

    chuva = _analise("risco_por_chuva", filtro_mg)
    rajada = _analise("risco_por_rajada", filtro_mg)
    defas = _analise("perfil_defasagem", filtro_mg)

    _resposta(chuva, rajada, defas)
    st.divider()

    st.markdown("### A evidência")
    st.markdown(
        '<p class="nota">Cada barra é o risco daquela faixa comparado ao tempo '
        'bom. O denominador inclui as horas de céu limpo — sem elas a "taxa" '
        'seria só contagem disfarçada.</p>',
        unsafe_allow_html=True,
    )

    esquerda, direita = st.columns(2)
    with esquerda:
        st.plotly_chart(
            graficos.curva_de_risco(rajada, "Quanto o vento pesa", "rajada"),
            width="stretch",
        )
    with direita:
        st.plotly_chart(
            graficos.curva_de_risco(chuva, "Quanto a chuva pesa",
                                    "chuva na hora (mm)"),
            width="stretch",
        )
    st.markdown(
        '<p class="nota">A faixa de chuva para em 5 mm/h porque o valor é média '
        'de área: espalhado sobre as ~11 células de um conjunto, o extremo de um '
        'ponto se dilui. O percentil 99 da série é 2,2 mm/h — e é por isso que a '
        'última faixa fica <i>abaixo</i> da anterior: são 31 mil conjunto-horas '
        'contra 479 mil, e nessa ponta a curva já é ruído. O vento não tem esse '
        'problema: sobe faixa a faixa até o fim.</p>',
        unsafe_allow_html=True,
    )

    st.divider()
    st.markdown("### Antes ou depois?")
    st.markdown(
        '<p class="nota">Correlação não diz direção. Para saber se a chuva '
        '<b>precede</b> a queda, cada evento aqui é o <b>início</b> de um '
        'temporal — primeira hora com 5 mm ou mais depois de pelo menos 6 horas '
        'sem chuva forte. E o eixo desconta o ciclo diário e a sazonalidade: '
        'temporal em MG cai de tarde, e de tarde já há mais interrupção de '
        'qualquer jeito.</p>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(
        graficos.defasagem(defas, "Risco em torno do início do temporal"),
        width="stretch",
    )
    st.markdown(
        '<p class="nota"><b>Como ler:</b> barras claras são antes do temporal, '
        'escuras são depois. À esquerda do zero a linha fica colada no 1× — '
        'tempo normal. A partir do zero ela sobe e só volta ao normal umas 16 '
        'horas depois. É essa assimetria que separa causa de coincidência.</p>',
        unsafe_allow_html=True,
    )

    with st.expander("O que isso não prova"):
        st.markdown(
            '<p class="nota">A análise mostra <b>direção e tamanho</b>, não causa '
            'isolada. Não foram controlados idade da rede, arborização nem '
            'histórico de manutenção — fatores que também explicam por que um '
            'conjunto cai mais que outro sob o mesmo temporal. O que dá para '
            'afirmar é que o tempo é um dos motores, que o vento pesa mais que a '
            'chuva, e que o efeito aparece depois do evento, não antes.</p>',
            unsafe_allow_html=True,
        )
