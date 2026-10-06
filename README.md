# Projeto MECAI — Tarifas ANEEL e operação de ETA

Projeto de análise das tarifas horossazonais da ANEEL e otimização do agendamento de bombas de uma estação de tratamento de água (ETA).

## Conteúdo

- [`analiseTarifas/`](analiseTarifas/): notebook de análise nacional e estudo das tarifas de São Paulo em R$/kWh.
- [`pesquisaOperacional/`](pesquisaOperacional/): modelo MILP de bombeamento em 24 horas, com comparação de custos por tarifa e distribuidora.
- [`dados/`](dados/): base CSV de tarifas da ANEEL usada pelos notebooks.
- [`images/`](images/): gráficos das análises.

## Executar

Com Python instalado, crie/ative o ambiente virtual e instale as dependências:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Abra os notebooks no VS Code/Jupyter e execute as células em ordem. O modelo de otimização também requer `gurobipy` e uma licença válida do Gurobi.

Consulte [`analiseTarifas/README.md`](analiseTarifas/README.md) e [`pesquisaOperacional/README.md`](pesquisaOperacional/README.md) para metodologia, resultados e limitações.