import duckdb
import pytest

from zeki.curadoria import dimensoes


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(dimensoes, "PRATA", tmp_path)
    c = duckdb.connect()
    c.execute("set enable_progress_bar=false")
    return c


def _csv(tmp_path, linhas):
    caminho = tmp_path / "indqual-municipio.csv"
    cabecalho = "DatGeracaoConjuntoDados;IdeConjUnidConsumidoras;CodMunicipio;NomMunicipio;SigUF"
    caminho.write_text(
        "\n".join([cabecalho, *linhas]) + "\n", encoding="latin-1"
    )
    return caminho


def test_descarta_homonimo_de_outra_uf(con, tmp_path, monkeypatch):
    # O caso real é o conjunto 15457: gaúcho, com 37 municípios do RS, mas a
    # ANEEL grudou nele Soledade/PB e Sarandi/PR, xarás de cidades do RS.
    linhas = [
        "2026-09-09;15457;4318804;Soledade;RS",
        "2026-09-09;15457;4316808;Sarandi;RS",
        "2026-09-09;15457;4300001;Outra;RS",
        "2026-09-09;15457;2515302;Soledade;PB",
        "2026-09-09;15457;4126256;Sarandi;PR",
    ]
    monkeypatch.setattr(dimensoes, "BRONZE", tmp_path)
    _csv(tmp_path, linhas)

    dimensoes.ponte_e_conjuntos(con)
    ufs = con.execute(
        "select distinct uf from ponte_conjunto_municipio where conjunto = 15457"
    ).fetchall()
    assert ufs == [("RS",)]
    assert con.execute(
        "select count(*) from ponte_conjunto_municipio"
    ).fetchone()[0] == 3


def test_conjunto_de_municipio_unico_e_marcado(con, tmp_path, monkeypatch):
    monkeypatch.setattr(dimensoes, "BRONZE", tmp_path)
    _csv(tmp_path, [
        "2026-09-09;1;2929305;Sao Goncalo dos Campos;BA",
        "2026-09-09;3;2201002;Arraial;PI",
        "2026-09-09;3;2202075;Cajazeiras do Piaui;PI",
    ])

    dimensoes.ponte_e_conjuntos(con)
    resultado = dict(con.execute(
        "select conjunto, municipio_unico from dim_conjunto"
    ).fetchall())
    assert resultado[1] is True
    assert resultado[3] is False


def test_empate_de_uf_escolhe_deterministicamente(con, tmp_path, monkeypatch):
    monkeypatch.setattr(dimensoes, "BRONZE", tmp_path)
    _csv(tmp_path, [
        "2026-09-09;9;3100000;A;MG",
        "2026-09-09;9;3300000;B;RJ",
    ])

    dimensoes.ponte_e_conjuntos(con)
    # Com empate a ordem alfabética decide, para a carga ser reprodutível.
    assert con.execute(
        "select uf from dim_conjunto where conjunto = 9"
    ).fetchone()[0] == "MG"
