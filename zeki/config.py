from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

DADOS = RAIZ / "Dados"
BRONZE = DADOS / "bronze"
PRATA = DADOS / "prata"
OURO = DADOS / "ouro"
MANIFESTO = DADOS / "manifesto.json"

CKAN = "https://dadosabertos.aneel.gov.br/api/3/action"
DATASET_INTERRUPCOES = "interrupcoes-de-energia-eletrica-nas-redes-de-distribuicao"
DATASET_MUNICIPIO = "indqual-municipio"

IBGE_MALHAS = "https://servicodados.ibge.gov.br/api/v3/malhas"
IBGE_LOCALIDADES = "https://servicodados.ibge.gov.br/api/v1/localidades"

PRIMEIRO_ANO = 2017

# Recorte do estudo de clima. MG porque é onde fica a empresa.
UF_CLIMA = "MG"

# O fato guarda data/hora como minutos inteiros desde esta referência.
EPOCA = "2017-01-01"

ANO_AMOSTRA = 2025
UF_AMOSTRA = "MG"


def preparar_diretorios():
    for d in (BRONZE, PRATA, OURO):
        d.mkdir(parents=True, exist_ok=True)
