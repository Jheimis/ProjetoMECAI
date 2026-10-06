# Agendamento de bombas da ETA com tarifas horossazonais

Este diretório contém [`ETA_agendamento_bombas_tarifa_aneel_sp.ipynb`](ETA_agendamento_bombas_tarifa_aneel_sp.ipynb), um modelo de otimização para planejar o bombeamento de uma estação de tratamento de água (ETA) ao longo de 24 horas. O modelo atende à demanda horária de 12 setores usando 6 bombas e 5 reservatórios, buscando reduzir o custo de energia de acordo com tarifas horossazonais reais da ANEEL.

## Como executar

Execute as células do notebook na ordem:

1. **Tarifas ANEEL:** localiza o CSV, carrega e converte datas e valores.
2. **Modelo de otimização:** define os dados operacionais, constrói o problema e define a tarifa por hora.
3. **Otimização:** resolve o modelo com Gurobi.
4. **Gráficos e resultados:** visualiza o agendamento e os níveis dos reservatórios.
5. **Cenários tarifários:** compara o custo para tarifas reais das distribuidoras paulistas e para um cenário hipotético de referência.

O CSV esperado é `dados/tarifas-homologadas-distribuidoras-energia-eletrica.csv`, na pasta `dados` da raiz do projeto. O notebook procura essa pasta na pasta de trabalho atual e em suas pastas ancestrais, portanto pode ser aberto a partir da raiz ou de `pesquisaOperacional`.

Dependências Python:

- `pandas`
- `numpy`
- `matplotlib`
- `gurobipy` — requer instalação e licença Gurobi válidas. O notebook foi executado com uma licença restrita para uso não comercial.

Com o ambiente virtual do projeto ativo, instale as dependências de análise já listadas no arquivo principal:

```powershell
python -m pip install -r ..\requirements.txt
```

Instale `gurobipy` conforme a licença e o método de instalação disponibilizados pela Gurobi para o seu ambiente. A licença restrita usada na execução registrada tinha limite temporal e pode não estar mais válida.

## Tarifas utilizadas

O cenário tarifário padrão está configurado no notebook:

| Parâmetro | Valor inicial |
|---|---|
| Distribuidora | `ELETROPAULO` (Enel SP, ex-Eletropaulo) |
| Modalidade | `Verde` |
| Subgrupo | `A4` |
| Data de referência | `2026-10-06` |

Esses valores podem ser alterados na primeira célula. O CSV não contém UF; o notebook também mantém uma lista de distribuidoras paulistas para a análise comparativa.

A função de consulta filtra a tarifa de aplicação vigente na data escolhida, modalidade e subgrupo selecionados, registros padrão sem classe/detalhe especial e unidades `MWh` para energia. O custo por posto é calculado como:

```text
Tarifa de energia (R$/kWh) = (TUSD (R$/MWh) + TE (R$/MWh)) / 1.000
```

Na execução registrada, para ELETROPAULO, Verde, A4, a vigência encontrada foi de **04/07/2026 a 03/07/2027**:

| Posto | Tarifa de energia |
|---|---:|
| Fora ponta | R$ 0,4525/kWh |
| Ponta | R$ 1,4048/kWh |

O valor de ponta corresponde a aproximadamente **3,10 vezes** o valor fora ponta.

## Modelo de otimização

O notebook formula um problema linear inteiro misto (MILP) com 24 períodos horários e os seguintes elementos:

- **Bombas:** 6 unidades, com potência e vazão máxima próprias.
- **Reservatórios:** 5 unidades, com volume mínimo, máximo e volume inicial.
- **Setores de consumo:** 12 pontos com demanda horária.
- **Topologia:** ligações permitidas entre bombas e reservatórios e entre reservatórios e setores são definidas por listas de arcos no código.
- **Capacidade da ETA:** vazão total de até **600 m³/h**.

### Variáveis e objetivo

As variáveis binárias indicam se cada bomba está ligada em cada hora. Variáveis contínuas representam vazão das bombas, fluxo nos arcos da rede e volume armazenado em cada reservatório.

O objetivo minimiza o custo diário da energia de bombeamento:

```text
min Σ(horas, bombas) tarifa_hora × potência_bomba × bomba_ligada
```

A tarifa de ponta é aplicada às horas **17h, 18h e 19h**; às demais horas aplica-se a tarifa fora ponta. A energia de uma hora é calculada como potência em kW × 1 hora.

### Restrições principais

- Vazão de cada bomba limitada pela faixa operacional e zerada quando desligada.
- Vazão total da ETA limitada a 600 m³/h.
- Atendimento exato da demanda horária de cada setor.
- Conservação de volume em cada reservatório, considerando vazões de entrada e saída.
- Volume de cada reservatório mantido entre os limites mínimo e máximo.
- Nível final de cada reservatório não inferior ao volume inicial.

## Demanda usada no exemplo

O notebook trabalha com um **cenário sintético de verão**, definido por uma curva horária que multiplica a demanda-base dos setores. A demanda-base soma **333 m³/h**; a curva concentra o consumo durante a manhã e o início da noite, com alívio na madrugada. O pico agregado indicado no código é aproximadamente **1.132 m³/h**, acima da capacidade instantânea de bombeamento, razão pela qual o armazenamento dos reservatórios é essencial.

Esses valores são premissas do exemplo e devem ser substituídos por dados operacionais medidos antes de usar o agendamento como recomendação para uma ETA real.

## Comparação de cenários tarifários

Uma etapa posterior reaproveita a estrutura do modelo e altera os coeficientes da função objetivo para cada combinação de distribuidora e modalidade A4. O cenário hipotético anterior (R$ 0,60/kWh fora ponta e R$ 2,80/kWh na ponta) é mantido como referência. Para cada cenário, o notebook calcula custo diário de energia, consumo de energia, consumo na ponta e custo médio por kWh.

Na análise adicional, estima-se a demanda a partir da maior potência das bombas ligadas em cada período e converte-se essa parcela para um custo diário, considerando um mês de 30 dias. Essa demanda é apenas uma **estimativa de comparação**: ela não é variável de decisão do modelo e não é minimizada pelo solver.

### Resultados registrados no notebook

- Com tarifas reais, o custo diário de energia reportado fica entre **R$ 2.231 e R$ 3.365**, comparado a **R$ 4.208/dia** no cenário hipotético.
- Mesmo com tarifa de ponta elevada, o modelo mantém bombeamento durante o horário de ponta. A tentativa de desligar as bombas às 17h–19h torna o modelo inviável no cenário de demanda utilizado: a demanda dessas horas supera o volume útil agregado dos reservatórios.
- Considerando a estimativa de demanda, a modalidade Azul fica de **2% a 6% abaixo** da Verde nas distribuidoras testadas. O próprio notebook alerta que essa comparação é indicativa, pois a demanda real contratada não está modelada e a solução pode ter gap de até 1%.
- Diferenças de custo entre distribuidoras são influenciadas principalmente pela tarifa fora ponta, que se aplica à maior parte das horas do dia.

O solver está configurado com limite de **60 segundos** e `MIPGap` de **1%**. Na execução salva no notebook, o Gurobi encontrou uma solução ótima dentro dessa tolerância, com custo de energia de aproximadamente **R$ 2.883,73/dia** para o cenário padrão. Esse valor é resultado das premissas registradas, não uma tarifa ou custo universal da ETA.

## Limitações e interpretação

- Os valores tarifários usados não incluem ICMS, PIS/COFINS nem bandeiras tarifárias.
- O período de ponta foi fixado em 17h–19h no modelo; os horários efetivos dependem da distribuidora e da resolução tarifária aplicável.
- A TUSD em R$/kW é uma cobrança de demanda e não pode ser convertida diretamente em R$/kWh. A estimativa comparativa do notebook usa potência máxima observada no agendamento como aproximação, não a demanda contratada real.
- O cenário de verão, as capacidades e a topologia da rede são parâmetros do estudo e precisam ser validados com dados da instalação.
- A classificação de distribuidoras paulistas é manual porque o CSV não tem coluna de UF.
- A conclusão Azul versus Verde depende do perfil de consumo, da demanda contratada e das premissas adotadas; o custo de energia isolado não é suficiente para uma comparação comercial definitiva.

## Referências

- [Dados abertos da ANEEL — Tarifas de distribuidoras de energia elétrica](https://dadosabertos.aneel.gov.br/dataset/tarifas-distribuidoras-energia-eletrica)
- Dicionário de dados e demais materiais do projeto na pasta `analiseTarifas`.