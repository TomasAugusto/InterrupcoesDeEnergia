"""Normalização dos dois layouts que a ANEEL publica.

Até 2025 o arquivo tem 18 colunas, o grão é o conjunto elétrico e a causa vem
num único texto. A partir de 2026 são 26 colunas, com código IBGE do município e
a causa já decomposta em origem, tipo, causa e detalhe.

Os dois viram o mesmo esquema. Colunas desconhecidas derrubam a carga de
propósito: o layout mudou uma vez e pode mudar de novo, e é melhor falhar alto do
que ingerir errado em silêncio.
"""

import logging

log = logging.getLogger(__name__)

LEGADO = {
    "DatGeracaoConjuntoDados", "IdeConjuntoUnidadeConsumidora",
    "DscConjuntoUnidadeConsumidora", "DscAlimentadorSubestacao",
    "DscSubestacaoDistribuicao", "NumOrdemInterrupcao", "DscTipoInterrupcao",
    "IdeMotivoInterrupcao", "DatInicioInterrupcao", "DatFimInterrupcao",
    "DscFatoGeradorInterrupcao", "NumNivelTensao", "NumUnidadeConsumidora",
    "NumConsumidorConjunto", "NumAno", "NomAgenteRegulado", "SigAgente",
    "NumCPFCNPJ",
}

ATUAL = {
    "DatGeracaoConjuntoDados", "NumCNPJDistribuidora", "NomAgente", "SigAgente",
    "CodMunicipioIBGE", "CodInterrupcao", "CodEvento", "CodOcorrencia",
    "CodConjUnidadeConsumidora", "DscConjuntoUnidadeConsumidora",
    "CodAlimentador", "CodSubestacao", "AnoCompetencia", "MesCompetencia",
    "DscLocalizacaoInterrupcao", "DscMotivoExpurgo", "DatInicioInterrupcao",
    "DatFimInterrupcao", "DscFatoGeradorOrigem", "DscFatoGeradorTipo",
    "DscFatoGeradorCausa", "DscFatoGeradorDetalhe", "NumNivelTensao",
    "QtdConsumidoresAfetados", "QtdConsumidoresAtivos",
    "DscTipoElementoInterrompido",
}

COLUNAS = [
    "ano", "conjunto", "municipio_ibge", "distribuidora", "alimentador",
    "subestacao", "inicio_s", "duracao_s", "programada", "origem", "tipo",
    "causa", "detalhe", "localizacao", "motivo_expurgo", "nivel_tensao",
    "consumidores_afetados", "consumidores_conjunto",
]

# `localizacao` e `motivo_expurgo` só existem no layout de 2026 e ficam nulas
# antes disso. Custam quase nada comprimidas e valem pela análise: o expurgo
# marca interrupção em situação de emergência, que é o que um temporal gera.

# O fim não é guardado: sai de inicio_s + duracao_s sem perda. Guardar os dois
# timestamps em microssegundos custava 8,7 dos 13 bytes por linha medidos em
# 2025; o offset em segundos derruba o fato de 13,0 para 8,1 B/linha.
EPOCA = "timestamp '2017-01-01'"

# As distribuidoras escrevem a causa com três separadores diferentes e grafias
# distintas. Medido em 2025: `-` responde por ~90% dos registros, `;` e `/` pelo
# resto. Com os três, 94,6% quebram nos quatro níveis esperados.
SEPARADORES = r"\s*[-;/]\s*"

# Variações que são claramente o mesmo valor. Sem isso "INTERNO" e "INTERNA"
# viram duas categorias e o gráfico de causas fica errado.
SINONIMOS = {
    "INTERNO": "INTERNA",
    "EXTERNO": "EXTERNA",
    "NAO PROGAMADA": "NAO PROGRAMADA",
    "N??O PROGRAMADA": "NAO PROGRAMADA",
    "QUEIMADA OU INCENDIO": "QUEIMA OU INCENDIO",
    "MARESIA OU CORROSAO": "CORROSAO",
}


def detectar_layout(colunas) -> str:
    presentes = set(colunas)
    if "CodMunicipioIBGE" in presentes:
        esperado, nome = ATUAL, "atual"
    else:
        esperado, nome = LEGADO, "legado"

    sobrando = presentes - esperado
    faltando = esperado - presentes
    if sobrando or faltando:
        raise ValueError(
            f"layout {nome} não bate com o esperado. "
            f"colunas novas: {sorted(sobrando)}; ausentes: {sorted(faltando)}"
        )
    return nome


def _canonizar(expr: str) -> str:
    """Aplica os sinônimos sobre uma expressão SQL já normalizada."""
    casos = " ".join(f"when '{de}' then '{para}'" for de, para in SINONIMOS.items())
    return f"case {expr} {casos} else {expr} end"


def _partes_causa(coluna: str) -> str:
    limpo = f"upper(strip_accents(trim(both '* ' from {coluna})))"
    return f"regexp_split_to_array({limpo}, '{SEPARADORES}')"


def sql_normalizacao(caminho, colunas, ano: int) -> str:
    layout = detectar_layout(colunas)
    fonte = f"read_parquet('{caminho.as_posix()}')"

    if layout == "atual":
        origem = _canonizar("upper(strip_accents(trim(DscFatoGeradorOrigem)))")
        tipo = _canonizar("upper(strip_accents(trim(DscFatoGeradorTipo)))")
        causa = _canonizar("upper(strip_accents(trim(DscFatoGeradorCausa)))")
        detalhe = _canonizar("upper(strip_accents(trim(DscFatoGeradorDetalhe)))")
        campos = f"""
            try_cast(AnoCompetencia as integer)               as ano,
            try_cast(CodConjUnidadeConsumidora as integer)    as conjunto,
            try_cast(CodMunicipioIBGE as integer)             as municipio_ibge,
            trim(SigAgente)                                   as distribuidora,
            nullif(trim(cast(CodAlimentador as varchar)), '') as alimentador,
            nullif(trim(cast(CodSubestacao as varchar)), '')  as subestacao,
            DatInicioInterrupcao                              as inicio,
            DatFimInterrupcao                                 as fim,
            {origem}                                          as origem,
            {tipo}                                            as tipo,
            {causa}                                           as causa,
            {detalhe}                                         as detalhe,
            nullif(trim(DscLocalizacaoInterrupcao), '')       as localizacao,
            nullif(trim(DscMotivoExpurgo), '')                as motivo_expurgo,
            try_cast(NumNivelTensao as integer)               as nivel_tensao,
            try_cast(QtdConsumidoresAfetados as integer)      as consumidores_afetados,
            try_cast(QtdConsumidoresAtivos as integer)        as consumidores_conjunto
        """
    else:
        p = _partes_causa("DscFatoGeradorInterrupcao")
        # A partir do quarto pedaço tudo é detalhe: alguns detalhes contêm hífen
        # e virariam um quinto e sexto campo se a gente cortasse em 4.
        detalhe_bruto = f"""
            case when len({p}) >= 4
                 then array_to_string({p}[4:], ' - ')
            end
        """
        campos = f"""
            try_cast(NumAno as integer)                        as ano,
            try_cast(IdeConjuntoUnidadeConsumidora as integer) as conjunto,
            cast(null as integer)                              as municipio_ibge,
            trim(SigAgente)                                    as distribuidora,
            nullif(trim(DscAlimentadorSubestacao), '')         as alimentador,
            nullif(trim(DscSubestacaoDistribuicao), '')        as subestacao,
            DatInicioInterrupcao                               as inicio,
            DatFimInterrupcao                                  as fim,
            {_canonizar(f'{p}[1]')}                            as origem,
            {_canonizar(f'{p}[2]')}                            as tipo,
            {_canonizar(f'{p}[3]')}                            as causa,
            {_canonizar(f'({detalhe_bruto})')}                 as detalhe,
            cast(null as varchar)                              as localizacao,
            cast(null as varchar)                              as motivo_expurgo,
            try_cast(NumNivelTensao as integer)                as nivel_tensao,
            try_cast(NumUnidadeConsumidora as integer)         as consumidores_afetados,
            try_cast(NumConsumidorConjunto as integer)         as consumidores_conjunto
        """

    log.info("ano %s: layout %s", ano, layout)

    return f"""
        select
            ano, conjunto, municipio_ibge, distribuidora, alimentador, subestacao,
            cast(epoch(inicio) - epoch({EPOCA}) as integer)        as inicio_s,
            try_cast(date_diff('second', inicio, fim) as integer)  as duracao_s,
            tipo like 'PROGRAMADA%%'                               as programada,
            origem, tipo, causa, detalhe, localizacao, motivo_expurgo,
            nivel_tensao, consumidores_afetados, consumidores_conjunto
        from (select {campos} from {fonte})
        where inicio is not null
    """
