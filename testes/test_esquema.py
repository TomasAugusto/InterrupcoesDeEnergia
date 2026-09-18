from datetime import datetime

import duckdb
import pyarrow as pa
import pytest

from zeki.curadoria import esquema

INICIO = datetime(2025, 3, 1, 10, 0, 0)
FIM = datetime(2025, 3, 1, 10, 30, 30)


def test_detecta_layout_legado():
    assert esquema.detectar_layout(esquema.LEGADO) == "legado"


def test_detecta_layout_atual():
    assert esquema.detectar_layout(esquema.ATUAL) == "atual"


def test_coluna_desconhecida_derruba():
    # A ANEEL já mudou o layout uma vez. Se mudar de novo, é melhor a carga
    # falhar do que ingerir uma coluna nova em silêncio.
    with pytest.raises(ValueError, match="colunas novas"):
        esquema.detectar_layout(esquema.LEGADO | {"DscCampoNovo"})


def test_coluna_ausente_derruba():
    with pytest.raises(ValueError, match="ausentes"):
        esquema.detectar_layout(esquema.LEGADO - {"SigAgente"})


def _curar_legado(tmp_path, causas):
    """Roda a normalização sobre um parquet sintético no layout velho."""
    n = len(causas)
    tabela = pa.table({
        "DatGeracaoConjuntoDados": pa.array([None] * n, pa.date32()),
        "IdeConjuntoUnidadeConsumidora": pa.array(range(1, n + 1), pa.int64()),
        "DscConjuntoUnidadeConsumidora": ["X"] * n,
        "DscAlimentadorSubestacao": ["A1"] * n,
        "DscSubestacaoDistribuicao": ["S1"] * n,
        "NumOrdemInterrupcao": ["1"] * n,
        "DscTipoInterrupcao": ["Não Programada"] * n,
        "IdeMotivoInterrupcao": pa.array([0] * n, pa.int64()),
        "DatInicioInterrupcao": pa.array([INICIO] * n, pa.timestamp("us")),
        "DatFimInterrupcao": pa.array([FIM] * n, pa.timestamp("us")),
        "DscFatoGeradorInterrupcao": causas,
        "NumNivelTensao": pa.array([13800] * n, pa.int64()),
        "NumUnidadeConsumidora": pa.array([10] * n, pa.int64()),
        "NumConsumidorConjunto": pa.array([1000] * n, pa.int64()),
        "NumAno": pa.array([2025] * n, pa.int64()),
        "NomAgenteRegulado": ["DIST"] * n,
        "SigAgente": ["DST"] * n,
        "NumCPFCNPJ": pa.array([1] * n, pa.int64()),
    })
    caminho = tmp_path / "amostra.parquet"
    import pyarrow.parquet as pq

    pq.write_table(tabela, caminho)

    con = duckdb.connect()
    sql = esquema.sql_normalizacao(caminho, tabela.column_names, 2025)
    return con.execute(sql).fetchall(), [d[0] for d in con.description]


def test_quebra_causa_nos_tres_separadores(tmp_path):
    linhas, colunas = _curar_legado(tmp_path, [
        "INTERNA - NAO PROGRAMADA - MEIO AMBIENTE - VENTO",
        "***INTERNA;NAO PROGRAMADA;MEIO AMBIENTE;VENTO",
        "Interna/Não programada/Meio ambiente/Vento",
    ])
    i = {c: n for n, c in enumerate(colunas)}
    for linha in linhas:
        assert linha[i["origem"]] == "INTERNA"
        assert linha[i["tipo"]] == "NAO PROGRAMADA"
        assert linha[i["causa"]] == "MEIO AMBIENTE"
        assert linha[i["detalhe"]] == "VENTO"


def test_detalhe_com_hifen_nao_vira_quinto_campo(tmp_path):
    linhas, colunas = _curar_legado(tmp_path, [
        "INTERNA - NAO PROGRAMADA - PROPRIAS DO SISTEMA - ATUACAO DE SISTEMA - SEP",
    ])
    i = {c: n for n, c in enumerate(colunas)}
    assert linhas[0][i["detalhe"]] == "ATUACAO DE SISTEMA - SEP"


def test_sinonimos_sao_unificados(tmp_path):
    linhas, colunas = _curar_legado(tmp_path, [
        "INTERNO - NAO PROGAMADA - MEIO AMBIENTE - QUEIMADA OU INCENDIO",
    ])
    i = {c: n for n, c in enumerate(colunas)}
    assert linhas[0][i["origem"]] == "INTERNA"
    assert linhas[0][i["tipo"]] == "NAO PROGRAMADA"
    assert linhas[0][i["detalhe"]] == "QUEIMA OU INCENDIO"


def test_duracao_preserva_segundos(tmp_path):
    linhas, colunas = _curar_legado(tmp_path, ["INTERNA - NAO PROGRAMADA - X - Y"])
    i = {c: n for n, c in enumerate(colunas)}
    assert linhas[0][i["duracao_s"]] == 30 * 60 + 30


def test_inicio_e_offset_da_epoca(tmp_path):
    linhas, colunas = _curar_legado(tmp_path, ["INTERNA - NAO PROGRAMADA - X - Y"])
    i = {c: n for n, c in enumerate(colunas)}
    con = duckdb.connect()
    esperado = con.execute(
        "select cast(epoch(timestamp '2025-03-01 10:00:00')"
        " - epoch(timestamp '2017-01-01') as integer)"
    ).fetchone()[0]
    assert linhas[0][i["inicio_s"]] == esperado
