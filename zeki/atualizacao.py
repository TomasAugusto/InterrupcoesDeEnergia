"""Atualização mensal: o que mudou na fonte, e a execução do ciclo.

A ANEEL republica o arquivo do ano corrente todo mês. Quem abre o painel não
tem como saber disso, então a conferência acontece sozinha na abertura: uma
chamada ao catálogo comparada com o manifesto. Sem rede, portal fora do ar ou
resposta estranha, o painel segue como se nada fosse — atualizar é um extra, e
não pode ser condição para desenhar gráfico.

O ciclo em si roda em outro processo, chamado pelo próprio `cli.py`. O painel
só dispara e lê o andamento deste arquivo de estado. Isso mantém o Streamlit
livre e deixa o mesmo caminho servir ao agendador de tarefas, que não tem
painel nenhum.
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zeki import manifesto
from zeki.config import BRONZE, DADOS, PRATA, RAIZ

log = logging.getLogger(__name__)

ESTADO = DADOS / "atualizacao.json"

# Conferir o catálogo é coisa de abertura de tela: ou responde rápido, ou fica
# para a próxima. O timeout da carga em si continua o do módulo da ANEEL.
TIMEOUT_CONFERENCIA = (5, 20)

# O ERA5 sai com cerca de cinco dias de atraso e ainda revisa o que é recente.
LATENCIA_ERA5 = timedelta(days=6)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def base_completa() -> bool:
    """Se a camada prata existe, dá para atualizar só o ano que mudou."""
    return (PRATA / "interrupcoes").exists()


def pendencias() -> dict:
    """O que o catálogo da ANEEL tem além do que está no manifesto."""
    from zeki.fontes import aneel

    try:
        recursos = aneel.interrupcoes_por_ano(timeout=TIMEOUT_CONFERENCIA)
        ponte = aneel.ponte_municipio(timeout=TIMEOUT_CONFERENCIA)
    except Exception as erro:
        log.info("conferência de atualização não completou: %s", erro)
        return {"online": False, "motivo": str(erro), "anos": [], "ponte": False}

    registro = manifesto.carregar()
    anos = [
        ano for ano, recurso in recursos.items()
        if manifesto.mudou(registro.get(f"aneel:interrupcoes:{ano}"), recurso)
    ]
    return {
        "online": True,
        "anos": anos,
        "ponte": manifesto.mudou(registro.get("aneel:indqual-municipio"), ponte),
        "publicado_em": max(
            (r.get("last_modified") or "" for r in recursos.values()), default=""
        ),
        "conferido_em": _agora(),
    }


def clima_pendente() -> dict:
    """Meses de ERA5 que faltam a uma base de clima que já existe.

    Duas condições, e as duas importam. Sem `.cdsapirc` não há o que oferecer: a
    conta no Copernicus é de quem roda, não do projeto. E sem nenhum mês em
    disco não se trata de atraso — é uma instalação que vive dos resultados de
    clima já calculados, onde propor dez anos de fila do CDS não faria sentido
    nenhum.
    """
    credencial = Path(os.path.expanduser("~/.cdsapirc"))
    tem_credencial = credencial.exists() or bool(os.environ.get("CDSAPI_URL"))

    baixados = sorted((BRONZE / "era5").glob("era5-mg-*.nc"))
    ultimo = baixados[-1].stem.split("-")[-1] if baixados else None

    limite = datetime.now(timezone.utc) - LATENCIA_ERA5
    disponivel = f"{limite.year}{limite.month:02d}"

    return {
        "credencial": tem_credencial,
        "ultimo_mes": ultimo,
        "disponivel_ate": disponivel,
        "atrasado": bool(ultimo and ultimo < disponivel),
    }


def estado() -> dict:
    if not ESTADO.exists():
        return {}
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def registrar(**campos):
    atual = estado()
    atual.update(campos)
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(atual, indent=2, ensure_ascii=False),
                      encoding="utf-8")


def em_andamento() -> bool:
    return estado().get("situacao") == "rodando"


def executar(anos=None, com_ponte=False, com_clima=False) -> dict:
    """O ciclo inteiro: baixar o que mudou, curar e regerar os agregados.

    Escreve cada passo no arquivo de estado enquanto anda, que é como o painel
    acompanha sem ficar preso a este processo.
    """
    from zeki.curadoria import dimensoes, fato, geometria, marts
    from zeki.fontes import aneel

    registrar(situacao="rodando", passo="conferindo a ANEEL",
              inicio=_agora(), erro=None, anos=anos or [])
    try:
        atualizados = aneel.sincronizar(anos)
        if not atualizados and not com_clima:
            registrar(situacao="pronto", passo="nada mudou na fonte",
                      fim=_agora(), anos=[])
            return {"anos": [], "clima": []}

        if com_ponte:
            registrar(passo="refazendo dimensões")
            dimensoes.construir()
            if not (PRATA / "geo_conjunto.parquet").exists():
                geometria.construir()

        if atualizados:
            registrar(passo=f"normalizando {', '.join(map(str, atualizados))}",
                      anos=atualizados)
            fato.curar(atualizados)

        meses = []
        if com_clima:
            from zeki.curadoria import clima as curadoria_clima
            from zeki.fontes import era5

            registrar(passo="baixando o ERA5 que falta")
            meses = era5.baixar()
            if meses:
                registrar(passo="montando a grade de clima")
                curadoria_clima.grade()
                curadoria_clima.por_conjunto()

        registrar(passo="regerando os agregados")
        marts.construir()

        registrar(situacao="pronto", passo="concluído", fim=_agora())
        return {"anos": atualizados, "clima": meses}
    except Exception as erro:
        log.exception("atualização falhou")
        registrar(situacao="erro", erro=str(erro), fim=_agora())
        raise


def disparar(anos=None, com_ponte=False, com_clima=False) -> bool:
    """Roda o ciclo em outro processo. False se já havia um andando."""
    if em_andamento():
        return False

    comando = [sys.executable, str(RAIZ / "cli.py"), "mensal"]
    if anos:
        comando += ["--anos", *map(str, anos)]
    if com_ponte:
        comando.append("--com-ponte")
    if com_clima:
        comando.append("--com-clima")

    registrar(situacao="rodando", passo="iniciando", inicio=_agora(),
              erro=None, anos=list(anos or []))
    # Sem pipes: a saída vai para o log do processo filho e o painel lê o
    # estado do JSON. Herdar os pipes do Streamlit trava quando o buffer enche.
    subprocess.Popen(comando, cwd=str(RAIZ),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
