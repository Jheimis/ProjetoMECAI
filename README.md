# Projeto MECAI — tarifas de energia e operação de ETA

O projeto reúne duas frentes de trabalho relacionadas às tarifas horossazonais da ANEEL:

1. **Análise tarifária:** exploração da base nacional de tarifas homologadas e estudo aplicado às distribuidoras paulistas, incluindo comparação entre postos horários e estimativa de custos em R$/kWh.
2. **Pesquisa operacional:** formulação de um modelo MILP para programar o bombeamento de uma estação de tratamento de água (ETA), atendendo à demanda de água com menor custo de energia.

## Estrutura

- [`analiseTarifas/`](analiseTarifas/): notebook de análise tarifária e seu guia de execução.
- [`pesquisaOperacional/guroby/`](pesquisaOperacional/guroby/): notebook de otimização que usa o solver Gurobi.
- [`pesquisaOperacional/pyomo_highs/`](pesquisaOperacional/pyomo_highs/): modelo em Python com Pyomo e HiGHS, interface gráfica e alternativa com python-mip/CBC.
- [`dados/`](dados/): CSV de tarifas da ANEEL usado pelos notebooks e modelos.
- [`images/`](images/): gráficos da análise e captura da interface da ETA.
- [`requirements.txt`](requirements.txt): dependências base dos notebooks e da análise.

## Preparar o ambiente

Os comandos abaixo devem ser executados no PowerShell, na raiz do repositório:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Se o PowerShell bloquear a ativação do ambiente, abra um terminal que permita ativar o ambiente ou execute os programas pelo caminho `.\.venv\Scripts\python.exe`.

## Executar a análise de tarifas

Abra `analiseTarifas/analise_horossazonal_aneel.ipynb` no VS Code com a extensão Jupyter, escolha o interpretador `.venv` e execute as células em ordem. O notebook procura automaticamente a base `dados/tarifas-homologadas-distribuidoras-energia-eletrica.csv` na raiz ou em uma pasta ancestral. Uma das últimas etapas exporta a tabela de tarifas paulistas para `dados/tarifa_horossazonal_sp_vigente_kwh.csv`.

## Executar o modelo de otimização da ETA

Há duas implementações:

- **Pyomo + HiGHS:** para abrir a interface gráfica ou executar o modelo pelo terminal, instale as dependências adicionais e siga o [guia Pyomo/HiGHS](pesquisaOperacional/pyomo_highs/README.md). O aplicativo pode ser iniciado da raiz com:

  ```powershell
  python -m pip install pyomo highspy mip
  python pesquisaOperacional\pyomo_highs\eta_gui.py
  ```

- **Comparação de solvers:** o notebook `pesquisaOperacional/pyomo_highs/ETA_agendamento_bombas_pyomo_highs.ipynb` inclui uma seção para comparar HiGHS, Gurobi e CBC no mesmo cenário. HiGHS e CBC podem ser usados com as dependências acima; Gurobi requer instalação e licença válidas.
- **Gurobi:** abra `pesquisaOperacional/guroby/ETA_agendamento_bombas_tarifa_aneel_sp.ipynb` no VS Code/Jupyter e execute as células em ordem. Consulte o [guia do notebook Gurobi](pesquisaOperacional/guroby/README.md). É necessária uma instalação/licença válida do Gurobi para resolver o modelo.

O modelo usa parâmetros de exemplo para bombas, reservatórios, topologia e demanda horária. Os resultados são demonstrativos e precisam ser validados com dados operacionais antes de orientar decisões reais.

## Guias e interpretação

- [Análise de tarifas ANEEL](analiseTarifas/README.md): dados, metodologia, gráficos, resultados e limitações.
- [Modelo Pyomo + HiGHS](pesquisaOperacional/pyomo_highs/README.md): instalação, interface, comparação de solvers, execução e premissas do modelo.
- [Modelo Gurobi](pesquisaOperacional/guroby/README.md): execução do notebook, formulação e resultados registrados.

As tarifas apresentadas nos estudos não incluem necessariamente tributos ou bandeiras. TUSD em R$/kW representa demanda e não deve ser somada diretamente a valores de energia em R$/MWh.
