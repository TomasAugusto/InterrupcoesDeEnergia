# Interrupções de energia × clima

Painel e pipeline sobre os dados abertos de interrupções de energia elétrica da ANEEL, cruzados
com reanálise climática horária em Minas Gerais.

## O problema

A ANEEL publica toda interrupção de energia nas redes de distribuição do país: 77 milhões de
registros entre 2017 e 2026. Usar isso é mais difícil do que parece. Os arquivos têm gigabytes, o
formato mudou no meio da série e o campo que qualquer um procuraria primeiro, em que cidade foi,
não existe em nove dos dez anos.

Escolhi a pergunta que me pareceu mais acionável: o tempo explica as quedas de energia? Se der
para medir, ela serve para planejar — dimensionar equipe antes de um temporal, priorizar poda onde
o vento pesa mais. Pensei em quem trabalha com operação e planejamento numa distribuidora. O
recorte de clima é Minas Gerais, segundo estado em volume de interrupções; o painel cobre o país
inteiro.

## A solução

Um pipeline que se mantém atualizado e um painel em cima dele.

O desafio pede que a solução considere a atualização mensal, e foi daí que parti. O sistema
consulta a API do portal, compara `last_modified`, tamanho e hash com o `manifesto.json` e rebaixa
só o que mudou, que na prática é o ano corrente. Rodar duas vezes seguidas não transfere nada. E
não depende de alguém lembrar: o painel confere a fonte quando abre, baixa em segundo plano e
avisa na tela. Quem preferir agendador usa `cli.py mensal`.

A resposta: o tempo explica, e o vento explica mais que a chuva. Rajada acima de 60 km/h
multiplica por 4,2 a taxa de interrupção, contra 2,6 da chuva forte. E vem antes da queda: nas
seis horas anteriores ao temporal a taxa está normal (1,04×) e o pico chega uma hora depois que
ele começa (1,39×).

Python, DuckDB sobre Parquet e Streamlit. Sem banco para manter, sem servidor para subir.

Uso de IA: desenvolvi o projeto com apoio do Claude Code, em par.

## Como rodar

Precisa de Python 3.11+ e Git. Se a máquina não tiver, no Windows é
`winget install -e --id Python.Python.3.12` e `winget install -e --id Git.Git` (depois reabra o
terminal); no Linux, `sudo apt install python3 python3-venv git`; no macOS, `brew install python git`.
Pelo instalador do python.org, marque "Add python.exe to PATH" na primeira tela.

A camada `ouro` tem 46 MB de agregados e vai versionada justamente para isto: clonar, instalar e
abrir, sem baixar dado nenhum.

```powershell
git clone --depth 1 https://github.com/TomasAugusto/InterrupcoesDeEnergia.git
cd InterrupcoesDeEnergia
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe cli.py painel
```

No Linux ou macOS, os dois últimos viram `.venv/bin/pip install -r requirements.txt` e
`.venv/bin/python cli.py painel`.

O navegador abre sozinho em `http://localhost:8501`. Se a porta estiver ocupada, use
`cli.py painel --porta 8599`.

Para reconstruir da fonte:

```bash
python cli.py atualizar     # ~2 GB da ANEEL, só o que mudou
python cli.py curar         # 77 milhões de linhas em 593 MB
python cli.py clima         # ERA5 de MG: 117 meses, ~5h de fila no CDS (exige conta no Copernicus)
python cli.py curar-clima   # grade, pesos e clima por conjunto
python cli.py publicar      # regera a camada ouro
```

Testes e auditoria: `pytest testes -q` (43 testes) e `python cli.py verificar`.

## O que achei nos dados

**Dois layouts.** De 2017 a 2025 são 18 colunas, sem município, com grão de conjunto elétrico. Em
2026 são 26, com código IBGE. O dicionário publicado descreve só o formato novo, então quem segue
a documentação escreve um leitor que falha em nove dos dez anos. O pipeline declara os dois e para
a carga se aparecer coluna desconhecida.

**A causa vem em texto com três separadores.** As distribuidoras usam `-`, `;` e `/`, com e sem
`***`, com e sem acento. Tratando só o hífen, 48% dos registros quebram nos quatro níveis; com os
três e normalização de caixa, 94,6%.

**Município é inferência até 2025.** Só 19,3% das interrupções vêm de conjuntos que cobrem uma
cidade só, e o maior deles cobre 49 municípios. Decidi não ratear: o fato fica no grão do
conjunto, o mapa pinta a área do conjunto e o filtro por cidade é rotulado pelo que faz. A ponte
oficial ainda liga 0,7% dos conjuntos a municípios de outras UFs por homonímia; a limpeza descarta
164 ligações.

**API de clima fácil não aguenta carga histórica.** O Open-Meteo cobra por peso, e as 756 células
de MG dariam 192 mil chamadas contra teto de 10 mil por dia. Busquei na fonte, no Copernicus, um
mês por requisição.

## O resultado

Interrupções por conjunto-hora, por faixa de rajada:

| rajada | taxa | vs. tempo calmo |
|---|---|---|
| até 20 km/h | 0,180 | — |
| 30–40 | 0,351 | 1,9× |
| 50–60 | 0,524 | 2,9× |
| 60 km/h ou mais | 0,753 | 4,2× |

A curva sobe faixa a faixa até o fim. A chuva eleva menos e para de subir no topo: 2,8× na faixa
de 2 a 5 mm e 2,6× acima disso, onde há só 31 mil observações contra 479 mil.

Três coisas quase estragaram esses números. O ERA5 rotula o acumulado pelo fim do intervalo, então
sem recuar uma hora na ingestão o perfil dava pico em −1h, com a luz caindo antes de chover. Chuva
é autocorrelacionada, e por isso o evento tem que ser o início do temporal, não uma hora chuvosa
qualquer. E temporal em MG cai de tarde, quando já há mais interrupção: sem descontar o ciclo
diário o efeito parecia 1,97× em vez de 1,39×.

Limite: a média de área dilui o extremo, e não controlei idade da rede, arborização nem
manutenção. O que está aqui mostra direção, não causa isolada.

## Detalhes de engenharia

O painel nunca lê o fato linha a linha, lê três cubos. Local eles são views sobre os 77 milhões de
registros; publicados, são Parquet, e `zeki/dados.py` é o único arquivo onde a diferença existe.

O fato ocupa 8,1 bytes por linha. Star schema rendeu 0,3%, porque o Parquet já dicionariza
sozinho; o ganho veio de descartar `fim` (sai de `inicio + duracao_s`) e guardar o tempo como
offset int32 em segundos, já que 63% dos registros têm precisão sub-minuto.

O ranking de distribuidoras abre por consumidores afetados, não por contagem: 52,9% dos registros
do país afetam um único consumidor, e essa fatia vai de 22% a 77% conforme a empresa, então contar
registros compara prática de reporte tanto quanto confiabilidade.

```
zeki/
├── fontes/        aneel.py, era5.py
├── curadoria/     esquema.py, dimensoes.py, geometria.py, fato.py, marts.py, clima.py
├── analise/       clima.py
├── painel/        app.py, brasil.py, clima.py, consultas.py, graficos.py
├── atualizacao.py conferência da fonte e ciclo mensal
└── dados.py       ponto único de acesso ao dado curado
```
