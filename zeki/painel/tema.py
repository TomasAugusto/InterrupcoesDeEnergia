"""Paleta e template do Plotly.

As oito cores categóricas vêm numa ordem fixa e validada para daltonismo — a
ordem é o mecanismo de segurança, não enfeite. Elas são atribuídas por entidade,
nunca por posição no ranking: se o filtro tira uma distribuidora, as outras não
trocam de cor.
"""

import plotly.graph_objects as go
import plotly.io as pio

CATEGORICAS = [
    "#2a78d6",  # azul
    "#eb6834",  # laranja
    "#1baf7a",  # água
    "#eda100",  # amarelo
    "#e87ba4",  # magenta
    "#008300",  # verde
    "#4a3aa7",  # violeta
    "#e34948",  # vermelho
]

# Escala sequencial de um tom só, claro -> escuro. Rampa arco-íris em magnitude
# é erro clássico: inventa fronteira onde o dado é contínuo.
SEQUENCIAL = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec",
    "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab",
    "#184f95", "#104281", "#0d366b",
]

SUPERFICIE = "#fcfcfb"
TINTA = "#0b0b0b"
TINTA_FRACA = "#52514e"
GRADE = "#e8e7e3"

CRITICO = "#d03b3b"
ATENCAO = "#fab219"

MAX_SERIES = len(CATEGORICAS)


def registrar():
    modelo = go.layout.Template()
    modelo.layout = go.Layout(
        colorway=CATEGORICAS,
        colorscale=dict(sequential=[[i / (len(SEQUENCIAL) - 1), c]
                                    for i, c in enumerate(SEQUENCIAL)]),
        paper_bgcolor=SUPERFICIE,
        plot_bgcolor=SUPERFICIE,
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif",
                  size=13, color=TINTA),
        # O título mora na faixa do contêiner e a legenda logo acima da área de
        # plotagem; sem isso os dois brigam pelo mesmo pixel no topo.
        title=dict(font=dict(size=15, color=TINTA), x=0, xanchor="left",
                   yref="container", y=0.97, yanchor="top"),
        margin=dict(l=12, r=16, t=56, b=12),
        hoverlabel=dict(bgcolor=SUPERFICIE, bordercolor=GRADE,
                        font=dict(color=TINTA, size=12)),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01,
                    xanchor="left", x=0, title_text="",
                    font=dict(color=TINTA_FRACA, size=12)),
        xaxis=dict(showgrid=False, zeroline=False, linecolor=GRADE,
                   ticks="outside", tickcolor=GRADE, automargin=True,
                   tickfont=dict(color=TINTA_FRACA)),
        yaxis=dict(gridcolor=GRADE, gridwidth=1, zeroline=False,
                   linecolor=GRADE, automargin=True,
                   tickfont=dict(color=TINTA_FRACA)),
    )
    pio.templates["zeki"] = modelo
    pio.templates.default = "zeki"


CINZA_CAUDA = "#9a9892"


def cor_por_entidade(ordem_global) -> dict[str, str]:
    """Cor fixa por entidade, ancorada numa ordem que não depende do filtro.

    `ordem_global` precisa vir do conjunto inteiro de dados, não do recorte em
    tela. Se a cor viesse da posição no ranking filtrado, tirar uma categoria
    repintaria as outras e quem aprendeu "meio ambiente é azul" seria enganado.
    """
    cores = {e: CATEGORICAS[i] for i, e in enumerate(ordem_global[:MAX_SERIES])}
    for e in ordem_global[MAX_SERIES:]:
        cores[e] = CINZA_CAUDA
    return cores


def dobrar_cauda(df, coluna, valor, ordem_global, limite=MAX_SERIES - 1,
                 rotulo="Outras"):
    """Mantém as maiores categorias globais e junta o resto numa só.

    Quem fica de fora é decidido pela ordem global, não pelo que o filtro
    devolveu — assim a mesma causa nunca troca de cor entre duas telas. Passar
    de oito cores seria gerar tom indistinguível sob daltonismo.
    """
    mantidas = [c for c in ordem_global[:limite] if c in set(df[coluna])]
    df = df.copy()
    df[coluna] = df[coluna].where(df[coluna].isin(mantidas), rotulo)
    return df, mantidas + [rotulo]
