"""Construtores de gráfico.

Regras seguidas aqui: um eixo por gráfico (nada de dois eixos y, que inventa
correlação), cor por entidade e não por posição no ranking, escala sequencial de
um tom só para magnitude, e marca fina com grade discreta.
"""

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from shapely import from_wkt

from zeki.painel import tema

DIAS = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"]


def _vazio(texto="Sem dados para este filtro"):
    fig = go.Figure()
    fig.add_annotation(text=texto, showarrow=False,
                       font=dict(color=tema.TINTA_FRACA, size=14))
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False),
                      height=260)
    return fig


def serie_temporal(df, coluna, titulo, rotulo, janela_cheia=None):
    if df.empty:
        return _vazio()

    fig = go.Figure(go.Scatter(
        x=df["periodo"], y=df[coluna], mode="lines",
        line=dict(width=2, color=tema.CATEGORICAS[0]),
        name=rotulo, hovertemplate=f"%{{y:,.0f}} {rotulo}<extra></extra>",
    ))

    # As pontas da base têm menos distribuidoras reportando. Em vez de cortar,
    # sombreia e explica — senão o gráfico some com dado real sem avisar.
    if janela_cheia:
        # A janela atravessa o cache do Streamlit e volta com o tipo de data
        # variando; comparar sem normalizar quebra na hora de ordenar as pontas.
        inicio, fim = (pd.Timestamp(v) if v is not None else None
                       for v in janela_cheia)
        # Sem texto dentro do gráfico: a faixa da direita tem a largura de um
        # mês e qualquer rótulo vaza pela borda. A legenda vai abaixo, em texto.
        for x0, x1 in ((df["periodo"].min(), inicio),
                       (fim, df["periodo"].max())):
            if x0 is None or x1 is None or x0 >= x1:
                continue
            fig.add_vrect(x0=x0, x1=x1, line_width=0,
                          fillcolor=tema.TINTA_FRACA, opacity=0.07,
                          layer="below")

    # Dois ajustes de eixo: em coluna estreita o Plotly escolheria passo de
    # década ("2020, 2030" numa série de 2017 a 2026), e a anotação da faixa
    # sombreada estica o alcance para além do último dado.
    fig.update_layout(
        title=titulo, height=340, showlegend=False,
        xaxis=dict(dtick="M12", tickformat="%Y",
                   range=[df["periodo"].min(), df["periodo"].max()]),
    )
    return fig


def composicao_causa(df, titulo, ordem_global):
    if df.empty:
        return _vazio()

    df, ordem = tema.dobrar_cauda(df, "causa", "interrupcoes", ordem_global)
    df = df.groupby(["periodo", "causa"], as_index=False)["interrupcoes"].sum()
    cores = tema.cor_por_entidade(ordem_global)
    cores["Outras"] = tema.CINZA_CAUDA

    fig = go.Figure()
    # Da maior para a menor, com "Outras" sempre no topo da pilha.
    for causa in ordem:
        parte = df[df["causa"] == causa]
        if parte.empty:
            continue
        rotulo = causa.capitalize()
        fig.add_bar(
            x=parte["periodo"], y=parte["interrupcoes"], name=rotulo,
            marker=dict(color=cores[causa],
                        line=dict(width=2, color=tema.SUPERFICIE)),
            hovertemplate=f"{rotulo}: %{{y:,.0f}}<extra></extra>",
        )
    fig.update_layout(barmode="stack", title=titulo, height=420,
                      bargap=0.28, hovermode="x unified",
                      margin=dict(t=100),
                      legend=dict(traceorder="reversed"),
                      xaxis=dict(dtick="M12", tickformat="%Y"))
    return fig


def ranking(df, rotulo_col, valor_col, titulo, sufixo=""):
    if df.empty:
        return _vazio()

    df = df.sort_values(valor_col)
    fig = go.Figure(go.Bar(
        x=df[valor_col], y=df[rotulo_col].astype(str), orientation="h",
        marker=dict(color=tema.CATEGORICAS[0]),
        hovertemplate=f"%{{y}}: %{{x:,.0f}}{sufixo}<extra></extra>",
    ))
    fig.update_layout(
        title=titulo, height=max(280, 26 * len(df) + 100), hovermode="closest",
        xaxis=dict(showgrid=True, gridcolor=tema.GRADE),
        # Sem type="category" o Plotly lê código de conjunto como número e
        # espalha o eixo numa escala contínua em vez de listar as barras.
        yaxis=dict(showgrid=False, type="category",
                   ticklabelposition="outside"),
        margin=dict(l=8, r=16, t=56, b=8),
    )
    return fig


def mapa_conjuntos(df, valor_col, titulo, rotulo):
    """Coroplético pintando a área do conjunto, não o município.

    O conjunto é a unidade real do dado até 2025. Desenhar município seria
    inventar precisão que a fonte não tem.
    """
    if df.empty:
        return _vazio("Sem conjuntos para este filtro")

    feicoes, limites = [], []
    for linha in df.itertuples():
        geom = from_wkt(linha.wkt)
        limites.append(geom.bounds)
        feicoes.append({
            "type": "Feature",
            "id": str(linha.conjunto),
            "geometry": json.loads(json.dumps(geom.__geo_interface__)),
            "properties": {},
        })

    fig = px.choropleth(
        df.assign(conjunto=df["conjunto"].astype(str)),
        geojson={"type": "FeatureCollection", "features": feicoes},
        locations="conjunto", featureidkey="id", color=valor_col,
        color_continuous_scale=tema.SEQUENCIAL,
        hover_data={"conjunto": False, "nome": True, "uf": True,
                    "qtd_municipios": True, valor_col: ":,.0f"},
    )

    # `fitbounds="locations"` erra o enquadramento com muitos polígonos
    # sobrepostos — e conjuntos se sobrepõem por construção, já que dividem
    # municípios. O recorte vai calculado à mão.
    lon0 = min(b[0] for b in limites)
    lat0 = min(b[1] for b in limites)
    lon1 = max(b[2] for b in limites)
    lat1 = max(b[3] for b in limites)
    folga = max(lon1 - lon0, lat1 - lat0) * 0.04

    fig.update_geos(
        visible=False, bgcolor=tema.SUPERFICIE, projection_type="mercator",
        lonaxis_range=[lon0 - folga, lon1 + folga],
        lataxis_range=[lat0 - folga, lat1 + folga],
    )
    fig.update_traces(marker_line_width=0.3, marker_line_color=tema.SUPERFICIE)
    fig.update_layout(
        title=titulo, height=560, hovermode="closest",
        coloraxis_colorbar=dict(title=rotulo, thickness=10, len=0.6,
                                outlinewidth=0, tickfont=dict(size=11)),
        margin=dict(l=0, r=0, t=56, b=0),
    )
    return fig


def calor_hora_semana(df, titulo):
    if df.empty:
        return _vazio()

    matriz = (df.pivot(index="dia_semana", columns="hora", values="interrupcoes")
                .reindex(range(7)).fillna(0))

    fig = go.Figure(go.Heatmap(
        z=matriz.values, x=matriz.columns, y=[DIAS[i] for i in matriz.index],
        colorscale=tema.SEQUENCIAL, xgap=2, ygap=2,
        hovertemplate="%{y}, %{x}h: %{z:,.0f}<extra></extra>",
        colorbar=dict(title="", thickness=10, len=0.7, outlinewidth=0),
    ))
    fig.update_layout(
        title=titulo, height=300, hovermode="closest",
        xaxis=dict(title="hora do dia", dtick=3, showgrid=False),
        yaxis=dict(showgrid=False, autorange="reversed"),
    )
    return fig


def histograma_duracao(df, titulo):
    """Só até 12 horas, em faixas de 15 minutos iguais.

    A cauda fica de fora de propósito. Ela é aberta — vai de 12 horas a 730 dias
    — e desenhá-la como uma barra só a transformava na mais alta do gráfico,
    parecendo uma moda quando é um balde de sobra. Faixas de larguras diferentes
    lado a lado mentem sobre proporção. O que a cauda tem está escrito embaixo,
    em número.
    """
    if df is None or df.empty:
        return _vazio()

    corpo = df[df["faixa_min"] < 720].sort_values("faixa_min")
    if corpo.empty:
        return _vazio()

    fig = go.Figure(go.Bar(
        x=corpo["faixa_min"] / 60, y=corpo["interrupcoes"],
        width=0.23,
        marker=dict(color=tema.CATEGORICAS[0]),
        customdata=corpo["faixa_min"],
        hovertemplate=("%{customdata:.0f}–%{customdata:.0f} min: "
                       "%{y:,.0f}<extra></extra>"),
    ))
    fig.update_layout(
        title=titulo, height=320, bargap=0.05, hovermode="closest",
        xaxis=dict(title="duração (horas)", dtick=2, range=[-0.3, 12.2]),
    )
    return fig


def texto_da_cauda(df) -> str | None:
    """As faixas acima de 12h em texto, já que não cabem no histograma."""
    if df is None or df.empty:
        return None

    total = df["interrupcoes"].sum()
    if not total:
        return None

    def pct(limite, casas=1):
        fatia = df.loc[df["faixa_min"] >= limite, "interrupcoes"].sum() / total
        return f"{100 * fatia:.{casas}f}".replace(".", ",")

    return (f"Acima de 12 horas ficam <b>{pct(720)}%</b> das interrupções, e "
            f"acima de 24 horas, <b>{pct(1440)}%</b>. Os <b>{pct(4320, 2)}%</b> "
            "que passam de três dias incluem registros que parecem ano digitado "
            "errado no campo de fim — o mais longo da base dura 730 dias exatos.")


def cobertura(df, titulo):
    """Conjuntos que reportaram por ano. Explica o degrau de 2017 para 2018."""
    fig = go.Figure(go.Bar(
        x=df["ano"], y=df["conjuntos"],
        marker=dict(color=[tema.ATENCAO if a == 2017 else tema.CATEGORICAS[0]
                           for a in df["ano"]]),
        hovertemplate="%{x}: %{y:,.0f} conjuntos<extra></extra>",
    ))
    fig.update_layout(title=titulo, height=260, bargap=0.3, hovermode="closest",
                      xaxis=dict(dtick=1))
    return fig


def curva_de_risco(df, titulo, rotulo_x, nota_pico=None):
    """Risco por faixa, em MULTIPLICADOR sobre a faixa de base.

    A taxa crua ("0,753 interrupções por conjunto-hora") não diz nada a quem
    lê. O mesmo dado como "4,2x" é conclusão pronta. O eixo é o múltiplo e a
    linha de 1x marca o tempo bom.
    """
    if df is None or df.empty:
        return _vazio()

    base = df["taxa"].iloc[0] or 1
    mult = df["taxa"] / base
    topo = float(mult.max())

    # A barra de base fica cinza: ela é a régua, não um resultado.
    cores = [tema.CINZA_CAUDA] + [tema.CATEGORICAS[0]] * (len(df) - 1)

    fig = go.Figure(go.Bar(
        x=df["faixa"].astype(str), y=mult,
        marker=dict(color=cores),
        text=[("base" if i == 0 else f"{m:.1f}×".replace(".", ","))
              for i, m in enumerate(mult)],
        textposition="outside", textfont=dict(size=13),
        customdata=df[["conjunto_horas", "taxa"]],
        hovertemplate=("%{text} o risco do tempo bom<br>"
                       "%{customdata[1]:.3f} por conjunto-hora<br>"
                       "%{customdata[0]:,.0f} horas observadas<extra></extra>"),
    ))
    fig.add_hline(y=1, line=dict(color=tema.TINTA_FRACA, width=1, dash="dot"))
    fig.update_layout(
        title=titulo, height=360, bargap=0.3, hovermode="closest",
        xaxis=dict(title=rotulo_x, type="category"),
        yaxis=dict(title="risco vs. tempo bom", range=[0, topo * 1.18],
                   tickformat=".1f"),
        margin=dict(t=62),
    )
    return fig


def defasagem(df, titulo):
    """Interrupções em torno do início do temporal, descontado o ciclo diário.

    O eixo é razão entre observado e esperado para aquela hora do dia e aquele
    mês. Sem esse desconto o perfil mostra picos falsos de 24 em 24 horas: em MG
    o temporal cai de tarde, e de tarde já há mais interrupção de qualquer jeito.
    """
    if df is None or df.empty:
        return _vazio()

    # Tom mais claro antes do evento, cheio depois: a leitura do gráfico é
    # justamente de que lado do zero a massa cai.
    cores = [tema.CATEGORICAS[0] if h >= 0 else "#9ec5f4" for h in df["hora_rel"]]

    fig = go.Figure(go.Bar(
        x=df["hora_rel"], y=df["lift"], marker=dict(color=cores),
        customdata=df[["taxa", "taxa_esperada"]],
        hovertemplate=("%{x:+d}h do início: %{y:.2f}x o normal<br>"
                       "%{customdata[0]:.3f} observado contra "
                       "%{customdata[1]:.3f} esperado<extra></extra>"),
    ))
    fig.add_hline(y=1, line=dict(color=tema.TINTA_FRACA, width=1, dash="dot"))
    fig.add_annotation(xref="paper", x=0.01, y=1, yanchor="bottom",
                       text="o normal para a hora e o mês", showarrow=False,
                       font=dict(color=tema.TINTA_FRACA, size=11))
    fig.add_vline(x=0, line=dict(color=tema.CRITICO, width=2))
    fig.add_annotation(x=0, yref="paper", y=1.0, text="início do temporal",
                       showarrow=False, xanchor="left", xshift=6,
                       font=dict(color=tema.CRITICO, size=12))
    fig.update_layout(
        title=titulo, height=380, bargap=0.15, hovermode="closest",
        xaxis=dict(title="horas em relação ao início do temporal", dtick=12),
        yaxis=dict(title="interrupções vs. o esperado"),
    )
    return fig
