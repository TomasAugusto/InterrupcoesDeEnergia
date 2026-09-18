"""Download dos dados abertos da ANEEL.

O portal não expõe consulta linha a linha (`datastore_active` é falso em todos os
recursos), só o arquivo anual inteiro. Por isso o projeto baixa e guarda local.
Sempre que existe Parquet para o ano, ele é preferido ao ZIP: mesmo conteúdo em
um décimo do tamanho.
"""

import logging
import re
import shutil

import requests

from zeki import manifesto
from zeki.config import BRONZE, CKAN, DATASET_INTERRUPCOES, DATASET_MUNICIPIO, PRIMEIRO_ANO

log = logging.getLogger(__name__)

ANO_NO_NOME = re.compile(r"(20\d{2})")
TIMEOUT = (30, 300)


def catalogo(dataset: str, timeout=None) -> list[dict]:
    r = requests.get(f"{CKAN}/package_show", params={"id": dataset},
                     timeout=timeout or TIMEOUT)
    r.raise_for_status()
    return r.json()["result"]["resources"]


def interrupcoes_por_ano(timeout=None) -> dict[int, dict]:
    """Um recurso por ano, preferindo Parquet quando disponível."""
    escolhidos = {}
    for recurso in catalogo(DATASET_INTERRUPCOES, timeout):
        formato = (recurso.get("format") or "").upper()
        if formato not in ("PARQUET", "ZIP"):
            continue

        achado = ANO_NO_NOME.search(recurso.get("name") or "")
        if not achado:
            continue
        ano = int(achado.group(1))
        if ano < PRIMEIRO_ANO:
            continue

        anterior = escolhidos.get(ano)
        if anterior is None or (formato == "PARQUET" and anterior["formato"] == "ZIP"):
            escolhidos[ano] = {**recurso, "formato": formato, "ano": ano}

    return dict(sorted(escolhidos.items()))


def ponte_municipio(timeout=None) -> dict:
    for recurso in catalogo(DATASET_MUNICIPIO, timeout):
        if (recurso.get("format") or "").upper() == "CSV":
            return recurso
    raise RuntimeError("dataset indqual-municipio sem recurso CSV")


def baixar(recurso: dict, destino) -> int:
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".parcial")

    esperado = recurso.get("size") or 0
    log.info("baixando %s (%.0f MB)", destino.name, esperado / 1e6)

    with requests.get(recurso["url"], stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        with parcial.open("wb") as saida:
            for bloco in r.iter_content(chunk_size=1 << 20):
                saida.write(bloco)

    tamanho = parcial.stat().st_size
    if esperado and abs(tamanho - esperado) > esperado * 0.01:
        parcial.unlink()
        raise RuntimeError(
            f"{destino.name}: baixou {tamanho} bytes, catálogo dizia {esperado}"
        )

    shutil.move(parcial, destino)
    return tamanho


def sincronizar(anos: list[int] | None = None) -> list[int]:
    """Baixa o que mudou desde a última execução. Devolve os anos atualizados."""
    registro = manifesto.carregar()
    recursos = interrupcoes_por_ano()

    if anos:
        recursos = {a: r for a, r in recursos.items() if a in anos}
        faltando = set(anos) - set(recursos)
        if faltando:
            log.warning("anos sem recurso publicado: %s", sorted(faltando))

    atualizados = []
    for ano, recurso in recursos.items():
        chave = f"aneel:interrupcoes:{ano}"
        destino = BRONZE / f"interrupcoes-{ano}.{recurso['formato'].lower()}"

        if not manifesto.mudou(registro.get(chave), recurso) and destino.exists():
            log.info("%s sem alteração", ano)
            continue

        baixar(recurso, destino)
        manifesto.registrar(registro, chave, recurso, destino)
        atualizados.append(ano)

    recurso = ponte_municipio()
    chave = "aneel:indqual-municipio"
    destino = BRONZE / "indqual-municipio.csv"
    if manifesto.mudou(registro.get(chave), recurso) or not destino.exists():
        baixar(recurso, destino)
        manifesto.registrar(registro, chave, recurso, destino)

    manifesto.salvar(registro)
    return atualizados
