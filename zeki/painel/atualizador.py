"""A faixa de atualização no alto do painel.

Confere a fonte quando alguém abre a tela, dispara o ciclo em outro processo e
acompanha o andamento. Tudo aqui é opcional por construção: sem rede, ou com o
portal fora do ar, a faixa simplesmente não aparece.
"""

import os
from datetime import datetime

import streamlit as st

from zeki import atualizacao

# Conferir a cada abertura de aba seria pedir para irritar quem está navegando.
# Meia hora é mais que suficiente para um dado que muda uma vez por mês.
TTL_CONFERENCIA = 1800

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")


def _ligado() -> bool:
    return os.environ.get("ZEKI_AUTOATUALIZAR", "1") != "0"


@st.cache_data(ttl=TTL_CONFERENCIA, show_spinner=False)
def _pendencias():
    return atualizacao.pendencias()


@st.cache_data(ttl=TTL_CONFERENCIA, show_spinner=False)
def _clima():
    return atualizacao.clima_pendente()


def _quando(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    return f"{MESES[d.month - 1]} de {d.year}"


@st.fragment(run_every=5)
def _enquanto_roda():
    """Só o relógio do passo atual.

    O `run_every` fica restrito a este pedaço, e só enquanto há download em
    curso: um fragmento que se repete sozinho deixa a tela inteira em estado de
    recarga, e um painel piscando a cada cinco segundos é pior do que não
    avisar nada.
    """
    estado = atualizacao.estado()
    if estado.get("situacao") != "rodando":
        st.rerun(scope="app")
        return

    st.info(f"Atualizando a base em segundo plano — {estado.get('passo', '')}. "
            "Pode continuar navegando; o painel avisa quando terminar.")


def _limpar_e_recarregar():
    atualizacao.registrar(situacao="aplicado")
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()


def desenhar():
    if not _ligado():
        return

    estado = atualizacao.estado()
    situacao = estado.get("situacao")

    if situacao == "rodando":
        _enquanto_roda()
        return

    if situacao == "pronto":
        anos = ", ".join(str(a) for a in estado.get("anos") or [])
        st.success(f"Dados novos prontos{f' ({anos})' if anos else ''}.")
        if st.button("Ver os dados novos", type="primary"):
            _limpar_e_recarregar()
        return

    if situacao == "erro":
        st.warning(f"A atualização automática parou: {estado.get('erro')}. "
                   "Os dados que já estavam aqui continuam valendo.")
        if st.button("Dispensar"):
            atualizacao.registrar(situacao="dispensado")
            st.rerun()
        return

    pendentes = _pendencias()
    if not pendentes["online"] or not (pendentes["anos"] or pendentes["ponte"]):
        _oferecer_clima()
        return

    if atualizacao.base_completa():
        # O caminho curto: a camada prata está aqui, então só o ano que mudou
        # precisa ser rebaixado e recurado. Começa sozinho, que é a ideia — quem
        # abriu o painel não deveria precisar saber que existe um comando.
        atualizacao.disparar(anos=pendentes["anos"], com_ponte=pendentes["ponte"])
        st.toast("A ANEEL publicou dados novos. Baixando em segundo plano.")
        _enquanto_roda()
        return

    # Instalação enxuta: só a camada ouro veio no repositório, e sem a prata não
    # há como regerar os agregados a partir de um ano só. Reconstruir custa 2 GB
    # e uns quinze minutos, então isso não começa sem alguém mandar.
    publicado = _quando(pendentes.get("publicado_em"))
    st.info(
        "A ANEEL publicou uma versão mais nova dos dados"
        f"{f', de {publicado}' if publicado else ''}. Esta cópia usa os "
        "agregados que vieram no repositório, que continuam válidos. "
        "Incorporar o dado novo exige reconstruir a base da fonte: cerca de "
        "2 GB de download e quinze minutos."
    )
    if st.button("Baixar da ANEEL e reconstruir"):
        atualizacao.disparar(anos=None, com_ponte=True)
        st.rerun()


def _oferecer_clima():
    if not atualizacao.base_completa():
        return

    dados = _clima()
    if not dados["atrasado"] or not dados["credencial"]:
        return

    st.caption(
        f"O ERA5 já tem até {dados['disponivel_ate']} e esta base vai até "
        f"{dados['ultimo_mes']}. A fila do Copernicus costuma levar horas, "
        "então o clima não entra sozinho."
    )
    if st.button("Buscar os meses de clima que faltam"):
        atualizacao.disparar(anos=[], com_clima=True)
        st.rerun()
