from datetime import datetime

import duckdb
import numpy as np
import pytest

from zeki.analise import clima as analise


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("install icu; load icu; set TimeZone='UTC'")
    return c


def para_utc(con, local: str) -> datetime:
    return con.execute(
        f"select cast((timestamp '{local}' at time zone '{analise.FUSO}')"
        " as timestamp)"
    ).fetchone()[0]


@pytest.mark.parametrize("local,esperado_utc", [
    # Horário de verão vigente: MG em UTC-2.
    ("2017-01-15 12:00:00", "2017-01-15 14:00:00"),
    ("2018-12-15 12:00:00", "2018-12-15 14:00:00"),
    # Fora do horário de verão, e depois que ele acabou de vez em fev/2019.
    ("2017-07-15 12:00:00", "2017-07-15 15:00:00"),
    ("2019-03-15 12:00:00", "2019-03-15 15:00:00"),
    ("2020-01-15 12:00:00", "2020-01-15 15:00:00"),
    ("2026-01-15 12:00:00", "2026-01-15 15:00:00"),
])
def test_conversao_respeita_horario_de_verao(con, local, esperado_utc):
    """Offset fixo de -3 erraria os verões de 2017, 2018 e o começo de 2019.

    Uma hora de erro chega a inverter o sinal do perfil de defasagem, que é
    justamente o gráfico que diz se a chuva antecede a queda.
    """
    assert para_utc(con, local) == datetime.fromisoformat(esperado_utc)


def test_verao_e_inverno_diferem_de_uma_hora(con):
    verao = para_utc(con, "2018-01-15 12:00:00")
    inverno = para_utc(con, "2018-07-15 12:00:00")
    assert (inverno.hour - verao.hour) == 1


def test_recuo_de_uma_hora_na_grade():
    """O ERA5 rotula o acumulado pelo fim do intervalo.

    `tp` às 15:00 é a chuva de 14:00 a 15:00, enquanto a interrupção das 14:30
    cai no balde das 14:00. Sem recuar, a chuva parece anteceder a queda em 1h.
    """
    rotulado = np.array(["2017-01-01T15:00:00"], dtype="datetime64[ns]")
    inicio_do_intervalo = rotulado - np.timedelta64(1, "h")
    assert str(inicio_do_intervalo[0]) == "2017-01-01T14:00:00.000000000"


def test_faixas_de_chuva_cobrem_tudo_sem_sobrepor(con):
    """Cada valor cai em exatamente uma faixa."""
    casos = [0.0, 0.0001, 0.4999, 0.5, 0.9999, 1.0, 1.9999, 2.0, 4.9999, 5.0, 99.0]
    for valor in casos:
        combina = [
            cond for _, cond in analise.FAIXAS_CHUVA
            if con.execute(
                f"select {cond.replace('chuva', str(valor))}"
            ).fetchone()[0]
        ]
        assert len(combina) == 1, f"chuva={valor} casou com {len(combina)} faixas"


def test_faixas_de_rajada_cobrem_tudo_sem_sobrepor(con):
    for valor in [0.0, 19.99, 20.0, 29.99, 30.0, 49.99, 50.0, 59.99, 60.0, 200.0]:
        combina = [
            cond for _, cond in analise.FAIXAS_RAJADA
            if con.execute(
                f"select {cond.replace('rajada', str(valor))}"
            ).fetchone()[0]
        ]
        assert len(combina) == 1, f"rajada={valor} casou com {len(combina)} faixas"
