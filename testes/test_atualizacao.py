"""A conferência de atualização não pode atrapalhar quem só quer ver o painel.

Ela roda na abertura da tela, fala com a internet e pode falhar de muitas
formas — portal fora do ar, máquina sem rede, proxy corporativo. Nenhuma delas
pode virar erro na cara de quem abriu o painel.
"""

import pytest

from zeki import atualizacao


@pytest.fixture
def estado_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(atualizacao, "ESTADO", tmp_path / "atualizacao.json")
    return tmp_path


def test_sem_rede_a_conferencia_devolve_offline(monkeypatch):
    from zeki.fontes import aneel

    def cai(*_, **__):
        raise OSError("getaddrinfo falhou")

    monkeypatch.setattr(aneel, "interrupcoes_por_ano", cai)

    resultado = atualizacao.pendencias()
    assert resultado["online"] is False
    assert resultado["anos"] == []


def test_ano_republicado_entra_como_pendencia(monkeypatch):
    from zeki import manifesto
    from zeki.fontes import aneel

    recurso = {"url": "http://x/2026.parquet", "last_modified": "2026-10-03",
               "size": 210_000_000, "hash": ""}
    monkeypatch.setattr(aneel, "interrupcoes_por_ano", lambda timeout=None: {2026: recurso})
    monkeypatch.setattr(aneel, "ponte_municipio", lambda timeout=None: recurso)
    monkeypatch.setattr(manifesto, "carregar", lambda: {
        "aneel:interrupcoes:2026": {"last_modified": "2026-09-04",
                                    "size": 204_708_716, "hash": None},
        "aneel:indqual-municipio": {"last_modified": "2026-10-03",
                                    "size": 210_000_000, "hash": None},
    })

    resultado = atualizacao.pendencias()
    assert resultado["anos"] == [2026]
    assert resultado["ponte"] is False


def test_estado_sobrevive_a_arquivo_corrompido(estado_isolado):
    atualizacao.ESTADO.write_text("{isto não é json", encoding="utf-8")
    assert atualizacao.estado() == {}
    assert atualizacao.em_andamento() is False


def test_registrar_acumula_em_vez_de_substituir(estado_isolado):
    atualizacao.registrar(situacao="rodando", passo="baixando")
    atualizacao.registrar(passo="normalizando")

    estado = atualizacao.estado()
    assert estado["situacao"] == "rodando"
    assert estado["passo"] == "normalizando"
    assert atualizacao.em_andamento() is True


def test_nao_dispara_dois_ciclos_ao_mesmo_tempo(estado_isolado, monkeypatch):
    chamadas = []
    monkeypatch.setattr(atualizacao.subprocess, "Popen",
                        lambda *a, **k: chamadas.append(a))

    assert atualizacao.disparar(anos=[2026]) is True
    assert atualizacao.disparar(anos=[2026]) is False
    assert len(chamadas) == 1


def test_painel_dispara_sozinho_quando_ha_ano_novo(estado_isolado, monkeypatch):
    """A faixa do painel é o gatilho: ninguém deveria ter que saber do comando."""
    from zeki.painel import atualizador

    disparos = []
    monkeypatch.setattr(atualizador, "_pendencias",
                        lambda: {"online": True, "anos": [2026], "ponte": False,
                                 "publicado_em": "2026-10-03T10:00:00"})
    monkeypatch.setattr(atualizacao, "base_completa", lambda: True)
    monkeypatch.setattr(atualizacao, "disparar",
                        lambda **kw: disparos.append(kw) or True)

    atualizador.desenhar()
    assert disparos == [{"anos": [2026], "com_ponte": False}]


def test_sem_novidade_o_painel_fica_quieto(estado_isolado, monkeypatch):
    from zeki.painel import atualizador

    disparos = []
    monkeypatch.setattr(atualizador, "_pendencias",
                        lambda: {"online": True, "anos": [], "ponte": False})
    monkeypatch.setattr(atualizador, "_clima",
                        lambda: {"atrasado": False, "credencial": False,
                                 "ultimo_mes": "202609", "disponivel_ate": "202609"})
    monkeypatch.setattr(atualizacao, "disparar",
                        lambda **kw: disparos.append(kw) or True)

    atualizador.desenhar()
    assert disparos == []


def test_instalacao_sem_era5_nao_e_tratada_como_atrasada(monkeypatch, tmp_path):
    """Sem nenhum mês em disco não há atraso: há uma cópia que vive do mart.

    Oferecer dez anos de fila do CDS a quem clonou o repositório para ver o
    painel seria propor um download de dias por engano.
    """
    monkeypatch.setattr(atualizacao, "BRONZE", tmp_path)
    assert atualizacao.clima_pendente()["atrasado"] is False


def test_clima_atrasado_quando_ha_base_e_falta_mes(monkeypatch, tmp_path):
    era5 = tmp_path / "era5"
    era5.mkdir()
    (era5 / "era5-mg-202001.nc").write_bytes(b"")
    monkeypatch.setattr(atualizacao, "BRONZE", tmp_path)

    resultado = atualizacao.clima_pendente()
    assert resultado["atrasado"] is True
    assert resultado["ultimo_mes"] == "202001"
