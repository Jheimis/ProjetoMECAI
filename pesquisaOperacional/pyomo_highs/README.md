# Agendamento de bombas da ETA com Pyomo + HiGHS

Este guia descreve a implementação em Python do modelo de programação linear inteira mista (MILP) para planejar o bombeamento de uma estação de tratamento de água. O modelo usa dados tarifários da ANEEL e pode ser executado pelo terminal ou por uma interface gráfica Tkinter.

## Arquivos

- [`pyomo_highs/eta_dados.py`](pyomo_highs/eta_dados.py): parâmetros da ETA, cenário de demanda de exemplo, busca/leitura do CSV e consulta das tarifas de energia e demanda.
- [`pyomo_highs/eta_pyomo.py`](pyomo_highs/eta_pyomo.py): formulação MILP em Pyomo e resolução com o solver HiGHS.
- [`pyomo_highs/eta_gui.py`](pyomo_highs/eta_gui.py): interface gráfica para configurar e visualizar um plano horário.
- [`pyomo_highs/eta_mip.py`](pyomo_highs/eta_mip.py): implementação alternativa do modelo usando python-mip com CBC.

## Instalação

Execute os comandos na raiz do repositório, no PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install pyomo highspy
```

O arquivo principal de dependências instala os pacotes usados pela análise e pelos notebooks. `pyomo` e `highspy` são dependências adicionais desta implementação. A interface usa Tkinter, incluído normalmente na instalação do Python para Windows.

## Abrir a interface gráfica

Com o ambiente virtual ativo e o terminal na raiz do projeto:

```powershell
python pesquisaOperacional\pyomo_highs\eta_gui.py
```

A aplicação procura automaticamente `dados/tarifas-homologadas-distribuidoras-energia-eletrica.csv`. Se não localizar o arquivo, abre uma janela para selecioná-lo. Informe a demanda diária de água, a tolerância MIPGap, o limite de tempo, a distribuidora, a modalidade Azul/Verde e a data de referência; depois, clique em **Otimizar**. Os resultados incluem custos, energia, potência, horários das bombas e gráficos.

![Exemplo da interface gráfica da ETA](../images/tela_exemplo.png)

## Executar pelo terminal

O script `eta_pyomo.py` resolve o cenário padrão de um dia:

```powershell
python pesquisaOperacional\pyomo_highs\eta_pyomo.py
```

Opcionalmente, informe primeiro o caminho do CSV e depois o número de dias:

```powershell
python pesquisaOperacional\pyomo_highs\eta_pyomo.py "C:\caminho\para\tarifas.csv" 2
```

O script consulta a tarifa padrão configurada em `eta_dados.py` e imprime o número de variáveis, as tarifas, o custo, o gap, o tempo e o estado de término do solver. A execução pelo terminal usa tolerância de gap de 1% e limite de 600 segundos por padrão.

### Alternativa python-mip/CBC

Para experimentar a implementação alternativa, instale `mip` e passe o caminho do CSV como argumento:

```powershell
python -m pip install mip
python pesquisaOperacional\pyomo_highs\eta_mip.py "C:\caminho\para\tarifas.csv"
```

## Como o modelo funciona

O cenário configurado representa 24 horas, seis bombas, cinco reservatórios e doze setores de consumo. O modelo escolhe quais bombas ligar e os fluxos da rede, respeitando os limites de vazão e armazenamento, a capacidade total de bombeamento da ETA e o atendimento da demanda horária. A função objetivo minimiza o custo de energia calculado com potência em kW, duração de uma hora e tarifa horária em R$/kWh.

A demanda é sintética: usa uma demanda-base por setor multiplicada por uma curva de verão em `eta_dados.py`. O horário de ponta é configurado como 17h, 18h e 19h. A tela permite alterar a demanda total, mas mantém a distribuição horária proporcional à curva definida no código. As tarifas Azul/Verde são lidas da base ANEEL para o subgrupo A4; a data de referência pode ser informada na interface.

## Premissas e limitações

- O CSV de tarifas deve existir em `dados/` na raiz do repositório ou ser selecionado manualmente na interface. A base não contém a UF, então a lista de distribuidoras paulistas em `eta_dados.py` é mantida manualmente.
- O horário de ponta fixo do modelo é uma premissa de exemplo; os horários reais dependem da distribuidora e da regulação aplicável.
- A configuração da ETA, a topologia, as capacidades e o perfil de demanda são dados ilustrativos, não um cadastro de instalação real.
- Tributos, bandeiras tarifárias e tarifas finais de fatura não são incluídos no custo de energia do modelo.
- A demanda contratada não é variável de decisão. Qualquer estimativa adicional de custo de demanda não deve ser interpretada como uma otimização desse componente.
- Antes de usar o agendamento em operação, valide dados, unidades, restrições, tarifas e resultados com responsáveis técnicos da instalação.
