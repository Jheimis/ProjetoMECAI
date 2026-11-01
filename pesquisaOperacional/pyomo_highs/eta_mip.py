"""Mesmo modelo em python-mip (solver CBC embutido no pacote — nada a instalar além de `pip install mip`)."""
import time
import mip
from eta_dados import *

def construir(c_fora, c_ponta, dias=1, horas_ponta=HORAS_PONTA, solver=mip.CBC,
              tarifa_demanda=None, fator_demanda=1.0):
    T = 24 * dias
    D = demanda(dias, fator_demanda)
    C = {t: (c_ponta if (t % 24) in horas_ponta else c_fora) for t in range(T)}
    m = mip.Model("ETA_bombas", sense=mip.MINIMIZE, solver_name=solver)
    m.verbose = 0
    H = range(T)
    x = {(p, t): m.add_var(var_type=mip.BINARY, name=f"x_{p}_{t}") for p in BOMBAS for t in H}
    q = {(p, t): m.add_var(lb=0, name=f"q_{p}_{t}") for p in BOMBAS for t in H}
    fpr = {(p, r, t): m.add_var(lb=0) for (p, r) in ARCOS_PR for t in H}
    frs = {(r, s, t): m.add_var(lb=0) for (r, s) in ARCOS_RS for t in H}
    V = {(r, t): m.add_var(lb=PARAM_RES[r][0], ub=PARAM_RES[r][1]) for r in RESERVATORIOS for t in H}
    kw_total = {t: mip.xsum(PARAM_BOMBAS[p][0] * x[p, t] for p in BOMBAS) for t in H}
    custo_energia = mip.xsum(C[t] * kw_total[t] for t in H)
    custo_demanda = 0
    if tarifa_demanda is not None:
        fator_periodo = dias / 30
        if "unica" in tarifa_demanda:
            kw_pico = m.add_var(lb=0, name="kw_pico")
            for t in H:
                m += kw_pico >= kw_total[t]
            custo_demanda = fator_periodo * tarifa_demanda["unica"] * kw_pico
        elif {"ponta", "fora_ponta"} <= tarifa_demanda.keys():
            kw_pico_ponta = m.add_var(lb=0, name="kw_pico_ponta")
            kw_pico_fora = m.add_var(lb=0, name="kw_pico_fora")
            horas_ponta = set(horas_ponta)
            for t in H:
                if t % 24 in horas_ponta:
                    m += kw_pico_ponta >= kw_total[t]
                else:
                    m += kw_pico_fora >= kw_total[t]
            custo_demanda = fator_periodo * (
                tarifa_demanda["ponta"] * kw_pico_ponta
                + tarifa_demanda["fora_ponta"] * kw_pico_fora
            )
        else:
            raise ValueError("Tarifas de demanda inválidas: informe 'unica' ou 'ponta' e 'fora_ponta'.")
    m._custo_energia = custo_energia
    m._custo_demanda = custo_demanda
    m.objective = custo_energia + custo_demanda
    for p in BOMBAS:
        for t in H:
            m += q[p, t] >= PARAM_BOMBAS[p][1] * x[p, t]
            m += q[p, t] <= PARAM_BOMBAS[p][2] * x[p, t]
            m += q[p, t] == mip.xsum(fpr[a, r, t] for (a, r) in ARCOS_PR if a == p)
    for t in H:
        m += mip.xsum(q[p, t] for p in BOMBAS) <= Q_ETA_MAX
        for s in SETORES:
            m += mip.xsum(frs[r, d, t] for (r, d) in ARCOS_RS if d == s) == D[s, t]
    for r in RESERVATORIOS:
        for t in H:
            entra = mip.xsum(fpr[p, rr, t] for (p, rr) in ARCOS_PR if rr == r)
            sai = mip.xsum(frs[rr, s, t] for (rr, s) in ARCOS_RS if rr == r)
            ant = PARAM_RES[r][2] if t == 0 else V[r, t - 1]
            m += V[r, t] == ant + entra - sai
        m += V[r, T - 1] >= PARAM_RES[r][2]
    m._x = x
    return m

def resolver(m, gap=0.01, limite=600):
    m.max_mip_gap = gap
    t0 = time.time()
    st = m.optimize(max_seconds=limite)
    return time.time() - t0, st

if __name__ == "__main__":
    import sys
    csv = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else achar_csv()
    fp, pt = tarifa_aneel(csv)
    td = tarifa_demanda_kw(csv)
    m = construir(fp, pt, tarifa_demanda=td)
    dt, st = resolver(m)
    print(f"CBC (python-mip): energia={m._custo_energia.x:.2f} demanda={m._custo_demanda.x:.2f} "
          f"total={m.objective_value:.2f} limite_inf={m.objective_bound:.2f} em {dt:.1f}s")
