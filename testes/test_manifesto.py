from zeki import manifesto


def rec(**kw):
    base = {"url": "u", "last_modified": "2026-08-04T18:09:48", "size": 100, "hash": ""}
    return base | kw


def test_recurso_novo_sempre_muda():
    assert manifesto.mudou(None, rec())


def test_igual_nao_muda():
    assert not manifesto.mudou(rec(), rec())


def test_data_diferente_muda():
    assert manifesto.mudou(rec(), rec(last_modified="2026-09-01T00:00:00"))


def test_tamanho_diferente_muda():
    assert manifesto.mudou(rec(), rec(size=101))


def test_hash_decide_quando_existe_dos_dois_lados():
    # A ANEEL publica hash só em parte dos recursos. Quando tem, ele vale mais
    # que a data: o portal reescreve last_modified em republicação idêntica.
    anterior = rec(hash="abc", last_modified="2026-01-01T00:00:00")
    atual = rec(hash="abc", last_modified="2026-09-01T00:00:00")
    assert not manifesto.mudou(anterior, atual)

    assert manifesto.mudou(anterior, rec(hash="def"))


def test_hash_so_de_um_lado_cai_na_data():
    anterior = rec(hash="")
    assert manifesto.mudou(anterior, rec(hash="abc", size=999))
