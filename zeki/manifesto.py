"""Registro do que já foi baixado, para não rebaixar o que não mudou.

Guarda por recurso o `last_modified`, o tamanho e o hash que o CKAN informou no
momento do download. A comparação com o catálogo atual decide o que refazer.
"""

import json
from datetime import datetime, timezone

from zeki.config import MANIFESTO


def carregar() -> dict:
    if not MANIFESTO.exists():
        return {}
    return json.loads(MANIFESTO.read_text(encoding="utf-8"))


def salvar(dados: dict):
    MANIFESTO.parent.mkdir(parents=True, exist_ok=True)
    MANIFESTO.write_text(
        json.dumps(dados, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def mudou(registro: dict | None, recurso: dict) -> bool:
    """True se o recurso do catálogo difere do que está registrado."""
    if registro is None:
        return True

    # O hash vem vazio em boa parte dos recursos da ANEEL, então ele só serve
    # como desempate quando existe dos dois lados.
    atual, anterior = recurso.get("hash") or "", registro.get("hash") or ""
    if atual and anterior:
        return atual != anterior

    return (
        registro.get("last_modified") != recurso.get("last_modified")
        or registro.get("size") != recurso.get("size")
    )


def registrar(dados: dict, chave: str, recurso: dict, arquivo, linhas=None):
    dados[chave] = {
        "url": recurso["url"],
        "last_modified": recurso.get("last_modified"),
        "size": recurso.get("size"),
        "hash": recurso.get("hash") or None,
        "arquivo": str(arquivo.name),
        "baixado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if linhas is not None:
        dados[chave]["linhas"] = linhas
