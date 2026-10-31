"""Modelo MILP da ETA em Pyomo — resolve com HiGHS (appsi_highs) ou CBC, sem limite de variáveis."""
import time
import pyomo.environ as pyo
from eta_dados import *

def construir(c_fora, c_ponta, dias=1, horas_ponta=HORAS_PONTA, fator_demanda=1.0):
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
    m.obj = pyo.Objective(expr=sum(C[t] * PARAM_BOMBAS[p][0] * m.x[p, t] for p in m.P for t in m.H), sense=pyo.minimize)

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
    m = construir(fp, pt, dias=dias)
    n_var = sum(1 for _ in m.component_data_objects(pyo.Var))
    print(f"{dias} dia(s): {n_var} variáveis | fora ponta R$ {fp:.4f}/kWh, ponta R$ {pt:.4f}/kWh")
    dt, custo, gap, term = resolver(m)
    print(f"HiGHS: custo R$ {custo:.2f} | gap {gap*100:.2f}% | {dt:.1f} s | {term}")
