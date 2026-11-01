"""Modelo MILP da ETA em Pyomo — resolve com HiGHS (appsi_highs) ou CBC, sem limite de variáveis."""
import time
import pyomo.environ as pyo
from eta_dados import *

def construir(c_fora, c_ponta, dias=1, horas_ponta=HORAS_PONTA, fator_demanda=1.0,
              tarifa_demanda=None):
    T = 24 * dias
    D = demanda(dias, fator_demanda)
    C = {t: (c_ponta if (t % 24) in horas_ponta else c_fora) for t in range(T)}
    m = pyo.ConcreteModel("ETA_bombas")
    m.H = pyo.RangeSet(0, T - 1)
    m.P = pyo.Set(initialize=list(BOMBAS)); m.R = pyo.Set(initialize=list(RESERVATORIOS)); m.S = pyo.Set(initialize=list(SETORES))
    m.APR = pyo.Set(initialize=ARCOS_PR, dimen=2); m.ARS = pyo.Set(initialize=ARCOS_RS, dimen=2)
    m.x = pyo.Var(m.P, m.H, within=pyo.Binary)
    m.q = pyo.Var(m.P, m.H, within=pyo.NonNegativeReals)
    m.fpr = pyo.Var(m.APR, m.H, within=pyo.NonNegativeReals)
    m.frs = pyo.Var(m.ARS, m.H, within=pyo.NonNegativeReals)
    m.V = pyo.Var(m.R, m.H, within=pyo.NonNegativeReals)
    m.kw_total = pyo.Expression(m.H, rule=lambda m, t: sum(PARAM_BOMBAS[p][0] * m.x[p, t] for p in m.P))
    m.custo_energia = pyo.Expression(
        expr=sum(C[t] * m.kw_total[t] for t in m.H)
    )
    custo_demanda_expr = 0
    if tarifa_demanda is not None:
        fator_periodo = dias / 30
        if "unica" in tarifa_demanda:
            m.kw_pico = pyo.Var(within=pyo.NonNegativeReals)
            m.limite_pico = pyo.Constraint(m.H, rule=lambda m, t: m.kw_pico >= m.kw_total[t])
            custo_demanda_expr = fator_periodo * tarifa_demanda["unica"] * m.kw_pico
        elif {"ponta", "fora_ponta"} <= tarifa_demanda.keys():
            horas_ponta = set(horas_ponta)
            m.kw_pico_ponta = pyo.Var(within=pyo.NonNegativeReals)
            m.kw_pico_fora = pyo.Var(within=pyo.NonNegativeReals)
            m.limite_pico_ponta = pyo.Constraint(
                m.H, rule=lambda m, t: m.kw_pico_ponta >= m.kw_total[t]
                if t % 24 in horas_ponta else pyo.Constraint.Skip
            )
            m.limite_pico_fora = pyo.Constraint(
                m.H, rule=lambda m, t: m.kw_pico_fora >= m.kw_total[t]
                if t % 24 not in horas_ponta else pyo.Constraint.Skip
            )
            custo_demanda_expr = fator_periodo * (
                tarifa_demanda["ponta"] * m.kw_pico_ponta
                + tarifa_demanda["fora_ponta"] * m.kw_pico_fora
            )
        else:
            raise ValueError("Tarifas de demanda inválidas: informe 'unica' ou 'ponta' e 'fora_ponta'.")
    m.custo_demanda = pyo.Expression(expr=custo_demanda_expr)
    m.obj = pyo.Objective(expr=m.custo_energia + m.custo_demanda, sense=pyo.minimize)

    m.qmin = pyo.Constraint(m.P, m.H, rule=lambda m, p, t: m.q[p, t] >= PARAM_BOMBAS[p][1] * m.x[p, t])
    m.qmax = pyo.Constraint(m.P, m.H, rule=lambda m, p, t: m.q[p, t] <= PARAM_BOMBAS[p][2] * m.x[p, t])
    m.qsoma = pyo.Constraint(m.P, m.H, rule=lambda m, p, t: m.q[p, t] == sum(m.fpr[a, r, t] for (a, r) in ARCOS_PR if a == p))
    m.eta = pyo.Constraint(m.H, rule=lambda m, t: sum(m.q[p, t] for p in m.P) <= Q_ETA_MAX)
    m.dem = pyo.Constraint(m.S, m.H, rule=lambda m, s, t: sum(m.frs[r, d, t] for (r, d) in ARCOS_RS if d == s) == D[s, t])

    def balanco(m, r, t):
        entra = sum(m.fpr[p, rr, t] for (p, rr) in ARCOS_PR if rr == r)
        sai = sum(m.frs[rr, s, t] for (rr, s) in ARCOS_RS if rr == r)
        ant = PARAM_RES[r][2] if t == 0 else m.V[r, t - 1]
        return m.V[r, t] == ant + entra - sai
    m.bal = pyo.Constraint(m.R, m.H, rule=balanco)
    for r in RESERVATORIOS:                       # limites de volume como bounds das variáveis
        for t in range(T):
            m.V[r, t].setlb(PARAM_RES[r][0]); m.V[r, t].setub(PARAM_RES[r][1])
    m.rec = pyo.Constraint(m.R, rule=lambda m, r: m.V[r, T - 1] >= PARAM_RES[r][2])
    return m


def construir_referencia_demanda(dias=1, fator_demanda=1.0):
    """Constrói referência que aproxima bombeamento da demanda, sem otimizar tarifas."""
    m = construir(0, 0, dias=dias, fator_demanda=fator_demanda)
    m.obj.deactivate()
    D = demanda(dias, fator_demanda)
    m.desvio_acima = pyo.Var(m.H, within=pyo.NonNegativeReals)
    m.desvio_abaixo = pyo.Var(m.H, within=pyo.NonNegativeReals)
    m.alvo_demanda = pyo.Constraint(
        m.H,
        rule=lambda m, t: sum(m.q[p, t] for p in m.P) - sum(D[s, t] for s in m.S)
        == m.desvio_acima[t] - m.desvio_abaixo[t],
    )
    max_potencia = sum(PARAM_BOMBAS[p][0] for p in BOMBAS)
    peso_desvio = max_potencia * 24 * dias + 1
    m.obj_referencia = pyo.Objective(
        expr=peso_desvio * sum(m.desvio_acima[t] + m.desvio_abaixo[t] for t in m.H)
        + sum(m.kw_total[t] for t in m.H),
        sense=pyo.minimize,
    )
    return m


def demanda_maxima_viavel():
    """Maior demanda diária (m³/dia) que o modelo consegue atender, mantendo a forma da curva horária.
    Como Q_min = 0, deixar todas as bombas disponíveis (x = 1) não restringe nada, então basta um LP:
    maximiza o fator f que multiplica a demanda."""
    T = 24
    base = demanda(1, 1.0)
    m = pyo.ConcreteModel()
    m.f = pyo.Var(bounds=(0, 5))
    m.q = pyo.Var(list(BOMBAS), range(T), bounds=(0, None))
    m.fpr = pyo.Var(ARCOS_PR, range(T), bounds=(0, None))
    m.frs = pyo.Var(ARCOS_RS, range(T), bounds=(0, None))
    m.V = pyo.Var(list(RESERVATORIOS), range(T))
    for r in RESERVATORIOS:
        for t in range(T):
            m.V[r, t].setlb(PARAM_RES[r][0]); m.V[r, t].setub(PARAM_RES[r][1])
    m.obj = pyo.Objective(expr=m.f, sense=pyo.maximize)
    m.c = pyo.ConstraintList()
    for p in BOMBAS:
        for t in range(T):
            m.c.add(m.q[p, t] <= PARAM_BOMBAS[p][2])
            m.c.add(m.q[p, t] == sum(m.fpr[a, r, t] for (a, r) in ARCOS_PR if a == p))
    for t in range(T):
        m.c.add(sum(m.q[p, t] for p in BOMBAS) <= Q_ETA_MAX)
        for s in SETORES:
            m.c.add(sum(m.frs[r, d, t] for (r, d) in ARCOS_RS if d == s) == m.f * base[s, t])
    for r in RESERVATORIOS:
        for t in range(T):
            ent = sum(m.fpr[p, rr, t] for (p, rr) in ARCOS_PR if rr == r)
            sai = sum(m.frs[rr, s, t] for (rr, s) in ARCOS_RS if rr == r)
            m.c.add(m.V[r, t] == (PARAM_RES[r][2] if t == 0 else m.V[r, t - 1]) + ent - sai)
        m.c.add(m.V[r, T - 1] >= PARAM_RES[r][2])
    pyo.SolverFactory("appsi_highs").solve(m)
    return pyo.value(m.f) * DEMANDA_DIARIA_BASE


def resolver(m, gap=0.01, limite=600, log=False, heuristica=0.3):
    """Resolve com HiGHS via Pyomo (appsi_highs). Retorna (segundos, custo, gap_final)."""
    s = pyo.SolverFactory("appsi_highs")
    s.highs_options = {"mip_rel_gap": gap, "time_limit": float(limite), "output_flag": log,
                       "mip_heuristic_effort": heuristica}
    t0 = time.time()
    res = s.solve(m)
    dt = time.time() - t0
    ub, lb = res.problem.upper_bound, res.problem.lower_bound
    return dt, ub, (ub - lb) / ub, str(res.solver.termination_condition)

if __name__ == "__main__":
    import sys
    csv = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else achar_csv()
    dias = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    fp, pt = tarifa_aneel(csv)
    td = tarifa_demanda_kw(csv)
    m = construir(fp, pt, dias=dias, tarifa_demanda=td)
    n_var = sum(1 for _ in m.component_data_objects(pyo.Var))
    print(f"{dias} dia(s): {n_var} variáveis | fora ponta R$ {fp:.4f}/kWh, ponta R$ {pt:.4f}/kWh")
    dt, objetivo, gap, term = resolver(m)
    print(f"HiGHS: energia R$ {pyo.value(m.custo_energia):.2f} | demanda rateada "
          f"R$ {pyo.value(m.custo_demanda):.2f} | total R$ {objetivo:.2f} | "
          f"gap {gap*100:.2f}% | {dt:.1f} s | {term}")
