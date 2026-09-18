# Interrupções de energia × clima

Painel e pipeline sobre os dados abertos de **interrupções de energia elétrica nas redes de
distribuição** da ANEEL, cruzados com reanálise climática horária em Minas Gerais.

## O problema

A ANEEL publica todo mês um dos maiores conjuntos de dados abertos do setor elétrico brasileiro:
toda interrupção de energia nas redes de distribuição do país. São **77 milhões de registros**
entre 2017 e 2026. E quase ninguém consegue usar: os arquivos têm gigabytes, o formato mudou no
meio da série, e o campo mais óbvio que alguém procuraria — *em que cidade foi?* — **não existe**
em nove dos dez anos.

O resultado é que a informação fica inacessível justamente para quem mais precisaria dela:
alguém que queira saber **onde a rede cai mais, por quê, e se dá para antecipar**.

Escolhi atacar essa pergunta na ponta mais acionável: **o tempo explica as quedas de energia?**
Se a resposta for sim e mensurável, ela vira insumo de planejamento — dimensionar equipe de
emergência antes de um temporal, priorizar poda de árvore onde o vento pesa mais, saber que tipo
de evento leva quanto tempo para normalizar.

**Para quem:** área de operação e planejamento de uma distribuidora, e analistas de regulação
que acompanham qualidade de serviço. O recorte de clima é **Minas Gerais**, o segundo estado em
volume de interrupções — 10.093.625 registros, atrás só de São Paulo — com 503 conjuntos
elétricos, o que dá massa suficiente para a análise horária sem estourar o custo de reanálise
climática. O painel de interrupções cobre o país inteiro.

## A solução

Um pipeline que se atualiza sozinho e um painel em cima dele.

**O requisito central do desafio é a atualização mensal**, e é o eixo do desenho. O sistema
consulta a API do portal da ANEEL, compara `last_modified`, tamanho e hash de cada recurso com o
que está registrado no `manifesto.json`, e rebaixa **só o que mudou** — na prática, o ano
corrente. Rodar duas vezes seguidas não transfere um byte.

E ninguém precisa lembrar de rodar: **o painel confere a fonte quando abre**, baixa em segundo
plano e avisa na tela que há versão nova. Quem preferir agendador tem o mesmo ciclo em um
comando, `cli.py mensal`. Os detalhes, inclusive por que o download é do ano inteiro e não do mês,
estão em [Atualização mensal](#atualização-mensal).

O que o sistema entrega:

- **Painel do Brasil** — 77.153.904 interrupções, 2017 a 2026, com filtros por região, UF,
  município, distribuidora, causa e tipo. Série temporal, mapa por área de conjunto elétrico,
  rankings, composição por causa, distribuição de duração e mapa de calor hora × dia da semana.
- **Painel de Minas Gerais** — as mesmas interrupções cruzadas com chuva e rajada de vento hora
  a hora, dez anos de reanálise ERA5. Curva de risco por faixa e análise de defasagem.
- **A resposta** — sim, o tempo explica, e **o vento explica mais que a chuva**: rajada acima de
  60 km/h multiplica por **4,2** a taxa de interrupção. E vem antes da queda: o pico é uma hora
  após o início do temporal.

**Tecnologia:** Python, DuckDB sobre Parquet e Streamlit. Sem banco para manter, sem servidor
para subir — o dado é um arquivo que se copia. As razões de cada escolha estão em
[Decisões de engenharia](#decisões-de-engenharia).

**Uso de IA:** o projeto foi desenvolvido com apoio do Claude Code, em par. As descobertas sobre
os dados, as decisões de modelagem e as correções de método estão documentadas abaixo porque
foram o trabalho de fato — o código é a parte fácil.

## Como rodar do zero

**Dependências:** Python 3.11 ou superior e Git. Todo o resto está em `requirements.txt` —
validado em 3.11.9 num clone limpo, Windows. Para ver o painel bastam DuckDB, Streamlit, Plotly,
pandas e pyarrow; `cdsapi`, `xarray` e `netCDF4` só entram em `cli.py clima`, que baixa o ERA5.

### Se a máquina ainda não tem Python

No **Windows**, pelo gerenciador que já vem no sistema:

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
```

Depois **feche e reabra o terminal** — o PATH só vale em sessão nova.

Pelo instalador, em [python.org/downloads](https://www.python.org/downloads/), a única coisa que
importa é marcar **"Add python.exe to PATH"** na primeira tela. Ela vem desmarcada, e é a causa
mais comum de `python não é reconhecido` logo depois.

No **Linux** (Debian ou Ubuntu):

```bash
sudo apt install python3 python3-venv git
```

No **macOS**, com Homebrew:

```bash
brew install python git
```

Confira com `python --version`. **Se isso abrir a Microsoft Store** em vez de responder uma
versão, o culpado é o atalho que a Microsoft instala por padrão: Configurações → Aplicativos →
Aliases de execução de aplicativo, e desligue as entradas `python.exe` e `python3.exe`. Como
alternativa, use `py` no lugar de `python`.

Qualquer versão entre 3.11 e 3.13 serve. Vale evitar a mais recente recém-lançada, porque nem
todo pacote binário tem versão compilada no primeiro mês.

### Caminho rápido — o painel completo, sem baixar nada

A camada `ouro` (46 MB de agregados) **vai versionada no repositório** justamente para isto:
clonar, instalar e abrir. Nada de conta em serviço nenhum, nada de 2 GB da ANEEL.

No **Windows**, em um PowerShell:

```powershell
git clone --depth 1 https://github.com/TomasAugusto/InterrupcoesDeEnergia.git
cd InterrupcoesDeEnergia
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe cli.py painel
```

No **Linux ou macOS**:

```bash
git clone --depth 1 https://github.com/TomasAugusto/InterrupcoesDeEnergia.git
cd InterrupcoesDeEnergia
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python cli.py painel
```

O navegador abre sozinho em `http://localhost:8501`, com os 77 milhões de interrupções e a
análise de clima já prontos. Se a porta estiver ocupada: `cli.py painel --porta 8599`.

O `--depth 1` traz só a ponta da história: como a camada ouro é versionada, cada republicação
deixou uma cópia dos agregados no histórico, e o clone raso baixa 93 MB em vez de 225 MB. Para
ler os commits, `git clone` sem a opção — ou o próprio GitHub.

Chamar o Python de dentro do `.venv` evita ativar o ambiente — que no PowerShell costuma
esbarrar em política de execução. Quem preferir ativar: `.venv\Scripts\Activate.ps1` no Windows,
`source .venv/bin/activate` no resto, e daí em diante `python cli.py painel`.

### Reconstruindo tudo da fonte

```bash
python cli.py atualizar     # ~2 GB da ANEEL, só o que mudou desde a última vez
python cli.py curar         # 77 milhões de linhas em 593 MB, mais dimensões e geometria
python cli.py clima         # ERA5 horário de MG: 117 meses, ~5h de fila no CDS
python cli.py curar-clima   # grade, pesos e clima por conjunto
python cli.py publicar      # regera a camada ouro
```

O passo de clima exige conta gratuita no Copernicus — veja
[Clima: o que é preciso para rodar](#clima-o-que-é-preciso-para-rodar). Os outros quatro não
exigem cadastro em nada.

Para um giro rápido com um ano só: `python cli.py amostra`.

### Atualização mensal

A ANEEL republica o arquivo do ano corrente todo mês. O painel confere isso sozinho ao abrir:
uma chamada ao catálogo, comparada com o `manifesto.json`, que leva cerca de dois segundos. Se
houver dado novo e a camada prata estiver presente, ele **dispara o ciclo em segundo plano** —
baixa, cura o ano que mudou, regera os agregados — e avisa na tela quando terminar, com um botão
que recarrega a base nova. Sem rede ou com o portal fora do ar, nada disso aparece: atualizar é
um extra, nunca condição para desenhar gráfico.

Numa cópia enxuta, aquela que veio do `git clone` com a camada ouro e sem a prata, a conferência
continua acontecendo, mas o painel só **avisa** que existe versão nova — regerar agregados a
partir de um ano só é impossível sem os outros nove, e reconstruir tudo custa 2 GB. Quem quiser
reconstruir tem o botão.

Para desligar: `ZEKI_AUTOATUALIZAR=0`.

O mesmo ciclo existe em um comando, para rodar na mão ou em agendador:

```bash
python cli.py mensal              # baixa o que mudou, cura e regera os agregados
python cli.py mensal --conferir   # só diz se há novidade; sai com 1 quando há
python cli.py mensal --com-clima  # busca também os meses de ERA5 que faltam
```

No Windows, uma vez por mês, às 3 da manhã do dia 5:

```powershell
schtasks /create /tn "Interrupcoes - atualizacao mensal" /sc monthly /d 5 /st 03:00 ^
  /tr "C:\caminho\InterrupcoesDeEnergia\.venv\Scripts\python.exe C:\caminho\InterrupcoesDeEnergia\cli.py mensal"
```

**Por que baixar o ano inteiro, e não só o mês.** O portal não publica recurso mensal: é um
arquivo por ano, com `datastore_active: false` — não existe consulta linha a linha. Dá para ser
mais esperto do que parece, porque o servidor aceita `Range` e o Parquet vem quase ordenado por
data: lendo só o rodapé do arquivo remoto (4 segundos), os 35 grupos de linhas mostram que o
período novo cabe em 8 deles, **48,7 MB dos 204,5 MB**. O que segura essa otimização não é a
viabilidade, é o que ela assumiria: que o passado do arquivo não mudou. A ANEEL reescreve o ano
inteiro, e retificação de registro antigo é rotina no setor. Além disso o download não é o
gargalo — dos cerca de sete minutos do ciclo, ele é um; o resto é regerar agregado sobre 77
milhões de linhas. Trocar integridade garantida por um minuto seria um mau negócio.

**E o clima?** O ERA5 tem cerca de cinco dias de latência e *revisa* o que é recente, então a
ingestão refaz a cauda dos últimos dois meses em vez de só emendar — quem compara apenas "o
arquivo existe" congela o dado provisório para sempre. A atualização é incremental do mesmo
jeito, mas **não roda sozinha**: depende de conta no Copernicus, que é de quem roda e não do
projeto, e a fila do CDS costuma levar horas. Quando há credencial na máquina e meses faltando,
o painel diz isso e oferece o botão.

### Testes e auditoria

```bash
pytest testes -q          # 43 testes
python cli.py verificar   # audita a base curada
```

A auditoria é um **detector de regressão**, não um semáforo permanente: os defeitos que a fonte
já trazia entram com um limite tolerado, e só passar desse limite falha. Uma verificação que vive
vermelha ninguém lê. Ela confere valores impossíveis, integridade referencial, se o total do fato
fecha com o do cubo, e se a grade de clima está cheia.

---

## O que o levantamento encontrou

Quatro descobertas mudaram o desenho do projeto. Elas estão aqui porque são a parte que não
aparece no código pronto.

### 1. A ANEEL mudou o layout no meio da série

Os arquivos de **2017 a 2025** têm 18 colunas, o grão é o *conjunto elétrico* e **não existe
município**. O arquivo de **2026** tem 26 colunas, com `CodMunicipioIBGE`, a causa decomposta em
quatro níveis, contagem de consumidores afetados e vínculo com ocorrências emergenciais.

O dicionário de dados publicado descreve **apenas o layout novo** — quem seguir só a documentação
escreve um leitor que falha em nove dos dez anos.

O pipeline declara os dois esquemas e normaliza para um. Coluna desconhecida **derruba a carga de
propósito** (`testes/test_esquema.py`): o layout já mudou uma vez e pode mudar de novo, e ingerir
errado em silêncio é pior que parar.

### 2. A causa vem num texto com três separadores diferentes

No layout velho a causa é um campo único como
`INTERNA - NAO PROGRAMADA - MEIO AMBIENTE - VENTO`. Só que as distribuidoras usam `-`, `;` **e**
`/`, com e sem prefixo `***`, em maiúscula e minúscula, com e sem acento.

Tratando só o hífen, 48% dos registros quebram nos quatro níveis. Com os três separadores e
normalização de acento e caixa, **94,6%**. Isso é o que permite comparar 2017–2025 com 2026 na
mesma taxonomia.

### 3. Município não é um dado da fonte até 2025 — é uma inferência

O conjunto elétrico é uma unidade regulatória: não respeita divisa de município. Medido na base de
2025, **apenas 19,3% das interrupções vêm de conjuntos que cobrem uma cidade só**. O maior
conjunto do país cobre 49 municípios; São Paulo capital é atendida por 201 conjuntos.

A decisão foi **não ratear**. O fato é guardado no grão do conjunto, o mapa pinta a área do
conjunto (união dos polígonos municipais do IBGE) e o filtro por cidade é rotulado no painel como
o que de fato é: *as interrupções dos conjuntos que atendem aquela cidade*. Nenhum número
municipal estimado é apresentado como se fosse da ANEEL.

A ponte oficial (`indqual-municipio`) tem um defeito próprio: **0,7% dos conjuntos aparecem
ligados a municípios de outras UFs por homonímia**. O conjunto 15457 é gaúcho — 37 municípios do
RS — mas carrega *Soledade/PB* e *Sarandi/PR*, xarás de cidades gaúchas. A limpeza mantém só os
vínculos da UF majoritária e descarta 164 ligações.

### 4. A API de clima de conveniência não aguenta carga histórica

O Open-Meteo cobra por peso: `locais × max(1, variáveis/10) × max(1, dias/14)`. Um ponto por 3.550
dias custa **~254 chamadas**, e as ~756 células de grade de MG dariam ~192.000 contra um teto de
10.000/dia. Dividir em pedaços não ajuda — o peso é o mesmo.

O ERA5 é uma grade, então vem da fonte (Copernicus CDS), um mês por requisição. E o grão **precisa**
ser horário por um motivo extra: a variável de rajada
`10m_wind_gust_since_previous_post_processing` saiu do produto diário derivado em junho de 2026 e
só existe no horário.

O ARCO-ERA5 do Google, que seria um caminho sem conta, foi testado e descartado: os blocos são de
uma hora do planeta inteiro, então extrair MG custaria ~85 GB de tráfego para obter 250 MB.

---

## O que o cruzamento com o clima mostrou

Base: reanálise ERA5 horária de 2017 a 2026 sobre Minas Gerais, agregada por **média de área** —
a chuva de um conjunto é a média ponderada das células de 25 km que ele cobre, não o valor de um
ponto. São 42,7 milhões de pares conjunto×hora.

### O vento é o que derruba

Interrupções por conjunto-hora, por faixa de rajada:

| rajada | taxa | vs. tempo calmo |
|---|---|---|
| até 20 km/h | 0,180 | — |
| 20–30 | 0,305 | 1,7× |
| 30–40 | 0,351 | 1,9× |
| 40–50 | 0,408 | 2,3× |
| 50–60 | 0,524 | 2,9× |
| **60 km/h ou mais** | **0,753** | **4,2×** |

Monotônica em toda a faixa. A chuva também eleva, mas menos — e para de subir no topo:

| chuva na hora | taxa | vs. sem chuva | conjunto-horas |
|---|---|---|---|
| sem chuva | 0,175 | — | 25,9 M |
| até 0,5 mm | 0,311 | 1,8× | 13,6 M |
| 0,5–1 mm | 0,386 | 2,2× | 1,6 M |
| 1–2 mm | 0,428 | 2,5× | 1,1 M |
| 2–5 mm | 0,488 | **2,8×** | 479 mil |
| 5 mm ou mais | 0,457 | 2,6× | 31 mil |

A última faixa cair abaixo da anterior não é contradição: são 31 mil observações contra 479 mil,
e o valor é média de área — nessa ponta a curva já é ruído. O número que o painel destaca é o da
faixa mais alta, 2,6×, porque é o que o rótulo do cartão afirma. De qualquer leitura, vento
acima de 60 km/h pesa mais que qualquer faixa de chuva.

### E vem antes da queda

Perfil das interrupções em torno do **início** de um temporal, em razão sobre o esperado:

| | |
|---|---|
| 6h antes | 1,04× — normal |
| hora +1 | **1,39×** |
| 6h depois | 1,25× |
| ±24h | 0,96× e 0,93× |

### Três armadilhas no caminho, e o que cada uma fazia

**O ERA5 rotula o acumulado pelo fim do intervalo.** `tp` marcado 15:00 é a chuva de 14:00 às
15:00, mas a interrupção das 14:30 cai no balde das 14:00. Sem recuar uma hora na ingestão, o
perfil dá pico em **−1h** — a luz caindo *antes* de chover. Não era erro de fuso, era convenção de
rótulo.

**Chuva é autocorrelacionada.** Centrando em qualquer hora chuvosa, o perfil sai simétrico por
construção: se choveu forte às 15h, provavelmente choveu às 13h e às 17h. Só ancorando no
*início* do temporal — primeira hora com 5 mm depois de 6 horas secas — é que dá para falar em
direção.

**Temporal em MG cai de tarde, e de tarde já há mais interrupção.** Sem descontar o ciclo diário,
o perfil mostra picos falsos de 24 em 24 horas e o efeito parecia 1,97×. Normalizando pelo
esperado de cada hora-do-dia e mês, os picos espúrios somem e o efeito real aparece: 1,39×.

### Limite honesto do método

A média de área dilui o extremo. O máximo horário de um conjunto em dez anos é 24,3 mm e o
percentil 99 é 2,2 mm — um pluviômetro pontual registraria bem mais. Por isso as faixas de chuva
seguem a distribuição medida, não números redondos: faixas de 10 em 10 mm deixariam as duas de
cima com algumas dezenas de observações.

---

## Decisões de engenharia

**DuckDB sobre Parquet, sem banco.** 77M de linhas respondem entre 100 ms e 1,9 s nas consultas do
painel, com cache do Streamlit por cima. Não há servidor para subir.

**Offline por necessidade, não por escolha.** O portal da ANEEL tem `datastore_active: false` em
todos os recursos — não existe consulta linha a linha, só o arquivo anual inteiro. Uma única peça
do sistema fala com a internet: `cli.py atualizar`.

**8,1 bytes por linha.** O que funcionou foi medir em vez de supor:

| | B/linha |
|---|---|
| Esquema direto, tudo string, dois timestamps | 13,0 |
| Star schema com chaves inteiras | 12,7 |
| Sem `fim`, tempo como offset int32 em segundos | **8,1** |

Star schema rendeu 0,3% — o Parquet já faz dicionário sozinho. O peso real estava em `inicio` e
`fim` em microssegundos, que custavam 8,7 dos 13 bytes. `fim` sai de `inicio + duracao_s` sem
perda, e a duração é guardada em segundos porque **63% dos registros têm precisão sub-minuto**.

**Ordenar antes de gravar.** Por `(conjunto, inicio)` o fato cai de 7,5 para 6,1 B/linha nas
colunas medidas isoladamente. Ordenar por tempo piora: as outras colunas perdem localidade.

---

## Cuidados que o painel toma

**As pontas da base não são comparáveis.** 2017 tem ~1.300 conjuntos reportando contra ~3.080 de
2018 em diante — a obrigação entrou em vigor no meio do ano. E agosto de 2026 tem **56 registros
de 25 conjuntos**: o arquivo do ano corrente termina de fato em julho. A série mostra tudo, com os
dois trechos sombreados e nomeados, em vez de cortá-los escondido.

**Cor não muda quando o filtro muda.** A paleta categórica é atribuída por entidade, ancorada na
ordem global de frequência — não na posição do ranking filtrado. Quem aprendeu que "meio ambiente
é laranja" continua certo depois de filtrar.

**"Ligadas ao tempo" é um piso, e o painel diz isso.** 6,8% dos registros não trazem detalhe de
causa. Deixar essa coluna nula os tiraria do denominador de qualquer média e empurraria o
indicador de 24,0% para 25,7% — uma diferença que ninguém veria. Desconhecido conta como
não-climático, e o número é apresentado como mínimo.

**O grão de reporte varia entre distribuidoras, e isso muda o ranking.** Um único evento da RGE
SUL aparece na base como **1.418 registros** — um por unidade consumidora, cada um com
`CodInterrupcao` próprio (`691286683_489`, `691286683_454`…). Já a CEMIG agrega o mesmo tipo de
evento em uma linha. No país, 52,9% dos registros afetam exatamente um consumidor, e essa fatia
vai de 22% (CELESC) a 77% (EQUATORIAL PA). Contar registros, portanto, compara **prática de
reporte** tanto quanto confiabilidade. O ranking de distribuidoras vem por consumidores afetados
por padrão, e avisa quando se troca para contagem.

**A cauda de duração não vira uma barra.** 15,4% das interrupções passam de 12 horas e 4,9%
passam de 24 — e a base tem registros de até **730 dias exatos**, que são ano digitado errado no
campo de fim, não apagão de dois anos. Empilhar isso numa barra "12h ou mais" a tornava a mais
alta do histograma, parecendo uma moda quando é balde de sobra, e misturava apagão real de 13
horas com erro de digitação. O gráfico vai até 12 horas em faixas iguais; o que passa disso está
escrito em número embaixo, com a ressalva.

**O total fecha.** ~0,12% das interrupções vêm de conjuntos que não constam na ponte da ANEEL. Com
join interno elas sumiriam do total sem aviso; o painel usa `left join`, então o número bate com a
curadoria e essas linhas só ficam de fora quando há filtro geográfico — o que é correto, já que
não se sabe onde ficam.

**Nenhum gráfico de dois eixos.** Alinhar duas escalas diferentes no mesmo plano inventa uma
correlação que não está no dado. Chuva, vento e interrupções aparecem em três faixas empilhadas
compartilhando o eixo do tempo.

---

## Duas versões, um código

O painel nunca lê o fato linha a linha — ele lê três cubos. Local esses cubos são *views* sobre
os 77 milhões de registros; publicados são Parquet. Nenhum gráfico sabe em qual dos dois está, e o
`zeki/dados.py` é o único arquivo onde a diferença existe.

| | Lê | Tamanho | Alcance |
|---|---|---|---|
| Completa | prata + ouro | ~1 GB | tudo |
| Reduzida | só ouro | **46 MB** | tudo, menos o drill até a interrupção individual |

A versão reduzida é a que **vem no repositório** — é ela que faz um clone abrir o painel completo
sem baixar nada — e é também a que sobe para o Streamlit Cloud.

```bash
python cli.py publicar              # monta a camada ouro
python cli.py painel --publicado    # confere localmente o que o avaliador vê
```

O build falha de propósito se algum arquivo passar de 100 MB, que é o limite do GitHub.

O grão mais fino do cubo é o mês — e isso vale **nos dois modos**, para os números serem idênticos.
Pelo mesmo motivo a duração mediana é interpolada dentro de faixas de 15 minutos: 193,3 min
contra 193 min da mediana exata.

## Estrutura

```
zeki/
├── fontes/        aneel.py, era5.py, ibge (em geometria.py)
├── curadoria/     esquema.py, dimensoes.py, geometria.py, fato.py
├── analise/       clima.py
├── painel/        app.py, brasil.py, clima.py, consultas.py, graficos.py, tema.py
└── dados.py       ponto único de acesso ao dado curado

Dados/
├── bronze/        downloads crus — descartáveis depois de curar
├── prata/         fato particionado por ano + dimensões
├── ouro/          agregados do painel
└── manifesto.json url, hash e last_modified de cada recurso baixado
```

O `manifesto.json` é versionado: é ele que permite reproduzir exatamente o mesmo estado da base,
mesmo com os dados fora do repositório.

## Clima: o que é preciso para rodar

O ERA5 exige conta gratuita no Copernicus:

1. Cadastro em <https://cds.climate.copernicus.eu>
2. Aceitar a licença em
   <https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download#manage-licences>
3. Gravar `~/.cdsapirc` com `url:` e `key:`
4. `python cli.py clima --checar` para conferir antes de baixar — ele distingue credencial
   ausente, token recusado e licença não aceita, que é a falha mais comum e a de mensagem mais
   obscura

O download é reiniciável: o que já está em disco é pulado, então dá para interromper à vontade.

O recorte agregado de MG viaja no repositório, então **a análise de clima abre sem conta** — a
ingestão completa é que exige.

## Testes

```bash
pytest testes -q
```

São 43, e cobrem o que quebra em silêncio: os dois layouts, coluna desconhecida, os três
separadores de causa, detalhe com hífen, sinônimos, precisão da duração, homonímia de UF, detecção
de mudança no manifesto, a conversão de fuso com horário de verão, o recuo de uma hora da grade do
ERA5 e a cobertura das faixas de chuva e rajada.

Cinco deles guardam bugs que não dão erro de banco. O primeiro: o painel consultava por uma
conexão DuckDB compartilhada entre as threads do Streamlit, e `execute(sql).df()` são dois passos
— outra thread executava entre eles e a primeira buscava o resultado errado. Reproduzido: 54
resultados trocados em 80 consultas com duas threads, aparecendo como `KeyError` numa coluna que
existe. Um dos testes é uma varredura que proíbe consulta direta na conexão compartilhada.

O segundo saiu da correção do primeiro. `con.cursor()` abre uma **sessão nova**, e configuração de
sessão não se herda: o cursor voltava ao fuso do sistema operacional enquanto o dado foi gravado
em UTC. Nada falha — a análise de clima ao vivo apenas desloca três horas, e o painel local
mostrava rajada forte a 3,6× o risco de base onde a versão publicada, que lê o mart pronto,
mostrava 4,2×. Duas telas do mesmo projeto discordando é o tipo de defeito que só aparece quando
alguém compara. Hoje o cursor é preparado no mesmo lugar que a conexão, e um teste checa o fuso.

O terceiro é de seleção, não de banco: o ranking e o mapa cortavam o "top N" **sempre por contagem
de registros**, mesmo quando a tela desenhava consumidores afetados. A CELESC, quinta do país em
consumidores, não aparecia no gráfico de distribuidoras; no mapa, 288 dos 900 conjuntos eram os
errados para a pergunta, e a cobertura caía de 61,5% para 53,7% dos consumidores. O corte agora
sai da mesma coluna que a cor.
