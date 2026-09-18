"""O painel usa uma conexão por consulta, e isso não é detalhe.

O Streamlit roda cada execução do script numa thread própria, e a conexão vem de
`st.cache_resource` — a mesma para todas. Como `execute(sql).df()` são dois
passos, outra thread pode executar entre eles e a primeira busca o resultado
errado. Não dá exceção de banco: dá `KeyError` numa coluna, num gráfico
qualquer, de forma intermitente.

Medido quando o bug existia: 54 resultados trocados em 80 consultas com duas
threads.
"""

import threading

import pytest

from zeki.config import OURO


pytestmark = pytest.mark.skipif(
    not (OURO / "mart_mensal.parquet").exists(),
    reason="precisa da camada ouro; rode `python cli.py publicar`",
)


def _conexao():
    from zeki import dados

    return dados.conectar()


def test_cursor_enxerga_as_views_da_conexao():
    con = _conexao()
    assert con.cursor().execute(
        "select count(*) from mart_mensal"
    ).fetchone()[0] > 0


def test_duas_threads_nao_trocam_resultados():
    con = _conexao()
    trocas = []

    def consultar(sql, coluna, repeticoes=40):
        for _ in range(repeticoes):
            try:
                df = con.cursor().execute(sql).df()
            except Exception as erro:
                trocas.append(f"{coluna}: {type(erro).__name__}")
                continue
            if coluna not in df.columns:
                trocas.append(f"{coluna} recebeu {list(df.columns)}")

    threads = [
        threading.Thread(target=consultar, args=(
            "select causa, sum(interrupcoes) n from mart_mensal group by 1",
            "causa")),
        threading.Thread(target=consultar, args=(
            "select uf, count(*) n from dim_conjunto group by 1", "uf")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not trocas, f"resultados trocados entre threads: {trocas[:5]}"


def test_painel_nao_consulta_pela_conexao_compartilhada():
    """Toda consulta do painel tem que sair de `cursor()`, nunca de `conexao()`."""
    from pathlib import Path

    from zeki.config import RAIZ

    suspeitas = []
    for arquivo in (RAIZ / "zeki" / "painel").glob("*.py"):
        for numero, linha in enumerate(
            arquivo.read_text(encoding="utf-8").splitlines(), 1
        ):
            if "conexao()." in linha and "cursor()" not in linha:
                suspeitas.append(f"{arquivo.name}:{numero} {linha.strip()}")

    assert not suspeitas, "consulta direta na conexão compartilhada: " + str(suspeitas)


def test_cursor_do_painel_mantem_o_fuso_em_utc():
    """Cursor é sessão nova: sem preparo, volta ao fuso do sistema.

    O estrago é silencioso — a análise de clima ao vivo desloca três horas e o
    multiplicador da rajada cai de 4,2× para 3,6×, enquanto a versão publicada,
    que lê o mart pronto, mostra o número certo.
    """
    from zeki.painel import consultas

    fuso = consultas.cursor().execute(
        "select current_setting('TimeZone')"
    ).fetchone()[0]
    assert fuso == "UTC"


def test_top_n_segue_a_medida_que_a_tela_mostra():
    """O corte tem que ser pela medida escolhida, não sempre por contagem.

    Pedir os 15 com mais registros e desenhar por consumidores afetados deixava
    de fora a CELESC, que é a quinta do país em consumidores. No mapa o efeito
    era maior: 288 dos 900 conjuntos trocavam.
    """
    from zeki.painel import consultas

    por_registro = consultas.ranking_distribuidoras(
        consultas.Filtro(), "interrupcoes")
    por_consumidor = consultas.ranking_distribuidoras(
        consultas.Filtro(), "consumidores")

    assert list(por_registro["distribuidora"]) != list(por_consumidor["distribuidora"])
    assert por_consumidor["consumidores"].is_monotonic_decreasing
    assert por_registro["interrupcoes"].is_monotonic_decreasing


def test_medida_desconhecida_nao_chega_ao_sql():
    from zeki.painel import consultas

    with pytest.raises(ValueError):
        consultas.mapa_conjuntos(consultas.Filtro(), "1; drop table mart_mensal")
