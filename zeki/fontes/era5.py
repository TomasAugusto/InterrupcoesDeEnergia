"""ERA5 horário do Copernicus CDS, recortado em Minas Gerais.

A API de conveniência (Open-Meteo) não serve para carga histórica: o peso de uma
chamada é `locais × max(1, variáveis/10) × max(1, dias/14)`, então um ponto por
3.550 dias custa ~254 chamadas e as ~756 células de MG estourariam o teto de
10.000/dia. O ERA5 é uma grade e vem da fonte, um mês por requisição.

O CDS trabalha por fila: pedido grande demora e às vezes cai. A ingestão é
reiniciável — o que já está em disco não é pedido de novo.
"""

import logging
from datetime import date

from zeki.config import BRONZE

log = logging.getLogger(__name__)

DATASET = "reanalysis-era5-single-levels"

# `10m_wind_gust_since_previous_post_processing` é a rajada máxima da hora. Ela
# saiu do produto diário derivado em junho/2026 e só existe no horário — mais um
# motivo para o grão ser este.
VARIAVEIS = ["total_precipitation",
             "10m_wind_gust_since_previous_post_processing"]

# Caixa de MG encostada na grade de 0,25°: N, O, S, L.
AREA = [-14.0, -51.25, -23.0, -39.75]

PRIMEIRO_MES = (2017, 1)

# O ERA5 tem ~5 dias de latência e revisa o dado recente, então a atualização
# refaz a cauda em vez de só emendar.
DIAS_PARA_REFAZER = 30

HORAS = [f"{h:02d}:00" for h in range(24)]
DIAS = [f"{d:02d}" for d in range(1, 32)]


def _cliente():
    import cdsapi

    return cdsapi.Client(quiet=True, progress=False)


def destino(ano: int, mes: int):
    return BRONZE / "era5" / f"era5-mg-{ano}{mes:02d}.nc"


def meses(ate: str | None = None):
    fim = date.today()
    if ate:
        ano, mes = (int(p) for p in ate.split("-"))
        fim = date(ano, mes, 1)

    ano, mes = PRIMEIRO_MES
    while (ano, mes) <= (fim.year, fim.month):
        yield ano, mes
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def pedido(ano: int, mes: int) -> dict:
    return {
        "product_type": ["reanalysis"],
        "variable": VARIAVEIS,
        "year": [str(ano)],
        "month": [f"{mes:02d}"],
        "day": DIAS,
        "time": HORAS,
        "area": AREA,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def verificar() -> tuple[bool, str]:
    """Testa credencial e aceite da licença com o menor pedido possível.

    Vale rodar antes da carga: as duas falhas mais comuns são o arquivo de
    credencial ausente e a licença do dataset não aceita, e a segunda dá uma
    mensagem que não deixa claro o que fazer.
    """
    alvo = BRONZE / "era5" / "_teste.nc"
    alvo.parent.mkdir(parents=True, exist_ok=True)

    try:
        cliente = _cliente()
    except Exception as erro:
        return False, (
            f"não consegui montar o cliente do CDS ({erro}). "
            "Confira se existe o arquivo .cdsapirc na sua pasta de usuário."
        )

    magro = pedido(2025, 1) | {"day": ["01"], "time": ["12:00"],
                               "variable": [VARIAVEIS[0]]}
    try:
        cliente.retrieve(DATASET, magro, str(alvo))
    except Exception as erro:
        texto = str(erro)
        minusculo = texto.lower()
        if "licence" in minusculo or "license" in minusculo:
            # O CDS devolve dois links na mensagem: o do endpoint que recusou e
            # o da página de licenças. Só o segundo serve, e ele é o que aponta
            # para /datasets.
            link = next((p.rstrip(".") for p in texto.split()
                         if p.startswith("http") and "/datasets/" in p), None)
            return False, (
                "credencial ok, mas falta aceitar a licença do dataset.\n"
                + (f"Aceite em: {link}" if link else
                   f"Aceite na aba Download de "
                   f"https://cds.climate.copernicus.eu/datasets/{DATASET}")
            )
        if "401" in minusculo or "authentication" in minusculo:
            return False, "credencial recusada. Confira o token no .cdsapirc."
        return False, f"o CDS respondeu com erro: {erro}"

    tamanho = alvo.stat().st_size
    alvo.unlink(missing_ok=True)
    return True, f"conexão ok — pedido de teste voltou com {tamanho / 1e3:.0f} KB"


def baixar(ate: str | None = None, refazer_cauda: bool = True) -> list[tuple[int, int]]:
    cliente = _cliente()
    hoje = date.today()
    baixados = []

    for ano, mes in meses(ate):
        alvo = destino(ano, mes)
        if alvo.exists():
            idade = (hoje - date(ano, mes, 1)).days
            if not (refazer_cauda and idade <= DIAS_PARA_REFAZER + 31):
                continue
            log.info("refazendo %s-%02d (dado ainda provisório)", ano, mes)

        alvo.parent.mkdir(parents=True, exist_ok=True)
        parcial = alvo.with_suffix(".parcial")
        log.info("pedindo %s-%02d ao CDS", ano, mes)
        cliente.retrieve(DATASET, pedido(ano, mes), str(parcial))
        parcial.replace(alvo)
        baixados.append((ano, mes))
        log.info("%s-%02d: %.1f MB", ano, mes, alvo.stat().st_size / 1e6)

    return baixados


def construir(ate_mes: str | None = None):
    ok, recado = verificar()
    if not ok:
        raise SystemExit(recado)
    log.info(recado)

    baixados = baixar(ate_mes)
    log.info("%s meses baixados", len(baixados))
    return baixados
