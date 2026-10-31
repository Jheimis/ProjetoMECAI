"""Tela (Tkinter) para o agendamento de bombas da ETA com tarifas ANEEL — solver HiGHS via Pyomo.

Executar (a partir da raiz do projeto, com o .venv ativo):
    python pesquisaOperacional\\pyomo_highs\\eta_gui.py
"""
import datetime as dt
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import pyomo.environ as pyo
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import eta_pyomo
from eta_dados import (BOMBAS, DEMANDA_DIARIA_BASE, DISTRIBUIDORAS_SP, HORAS_PONTA, PARAM_BOMBAS, PARAM_RES,
                       Q_ETA_MAX, RESERVATORIOS, SETORES, achar_csv, data_efetiva, demanda, tarifa_aneel,
                       tarifa_demanda_kw)

CAPACIDADE_DIA = Q_ETA_MAX * 24  # m³/dia


def br(v, nd=0):
    """Formata número no padrão brasileiro: 12.787,2"""
    return f"{v:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ----------------------------------------------------------------------------- núcleo (sem Tkinter)
def otimizar(csv, demanda_m3, gap, limite, distribuidora, modalidade, data_ref, subgrupo="A4"):
    """Resolve o modelo e devolve um dicionário com tudo que a tela precisa mostrar."""
    data_uso, aviso = data_efetiva(csv, distribuidora, modalidade, subgrupo, data_ref)
    fp, pt = tarifa_aneel(csv, distribuidora, modalidade, subgrupo, data_uso)
    fator = demanda_m3 / DEMANDA_DIARIA_BASE
    m = eta_pyomo.construir(fp, pt, fator_demanda=fator)
    try:
        tempo, custo, gap_final, term = eta_pyomo.resolver(m, gap=gap, limite=limite)
    except Exception as e:  # HiGHS sem solução viável (inviável ou limite de tempo)
        raise RuntimeError("Não foi encontrada solução viável dentro do limite de tempo. Tente aumentar o limite de "
                           "tempo ou o MIPGap, ou reduzir a demanda (o máximo atendível aparece no painel de "
                           "entrada).") from e
    if "nfeasible" in term:
        raise RuntimeError("Modelo inviável para essa demanda (a ETA não consegue atendê-la).")

    D = demanda(1, fator)
    horas = []
    for t in range(24):
        ligadas = [p for p in BOMBAS if pyo.value(m.x[p, t]) > 0.5]
        horas.append({"t": t, "ponta": t in HORAS_PONTA, "tarifa": pt if t in HORAS_PONTA else fp, "ligadas": ligadas,
                      "vazao": sum(pyo.value(m.q[p, t]) for p in BOMBAS),
                      "kw": sum(PARAM_BOMBAS[p][0] for p in ligadas),
                      "demanda": sum(D[s, t] for s in SETORES)})
    vol = {r: [PARAM_RES[r][2]] + [pyo.value(m.V[r, t]) for t in range(24)] for r in RESERVATORIOS}
    kwh = sum(h["kw"] for h in horas)
    kwh_ponta = sum(h["kw"] for h in horas if h["ponta"])
    kw_ponta = max(h["kw"] for h in horas if h["ponta"])
    kw_fora = max(h["kw"] for h in horas if not h["ponta"])
    dem_dia = None
    try:
        td = tarifa_demanda_kw(csv, distribuidora, modalidade, subgrupo, data_uso)
        mes = (td["ponta"] * kw_ponta + td["fora_ponta"] * kw_fora) if modalidade == "Azul" \
            else td["unica"] * max(kw_ponta, kw_fora)
        dem_dia = mes / 30
    except Exception:
        pass
    return {"horas": horas, "vol": vol, "custo": custo, "kwh": kwh, "kwh_ponta": kwh_ponta,
            "kw_max": max(h["kw"] for h in horas), "kw_medio": kwh / 24, "gap": gap_final, "tempo": tempo,
            "term": term, "fp": fp, "pt": pt, "aviso": aviso, "dem_dia": dem_dia, "demanda_m3": demanda_m3,
            "total_est": custo + dem_dia if dem_dia is not None else None, "distribuidora": distribuidora,
            "modalidade": modalidade, "vigencia_ref": pd_fmt(data_uso)}


def pd_fmt(d):
    return d.strftime("%d/%m/%Y")


def intervalos(horas_ligadas):
    """[0,1,2,5] -> ['00:00–03:00', '05:00–06:00']"""
    out, ini, ant = [], None, None
    for h in sorted(horas_ligadas):
        if ini is None:
            ini = ant = h
        elif h == ant + 1:
            ant = h
        else:
            out.append((ini, ant + 1)); ini = ant = h
    if ini is not None:
        out.append((ini, ant + 1))
    return [f"{a:02d}:00–{b:02d}:00" for a, b in out]


def desenhar(fig, r):
    fig.clear()
    gs = fig.add_gridspec(3, 1, height_ratios=[2.2, 1.6, 2.0], hspace=0.42, left=0.15, right=0.80, top=0.95, bottom=0.10)
    ax1 = fig.add_subplot(gs[0]); ax2 = fig.add_subplot(gs[1], sharex=ax1); ax3 = fig.add_subplot(gs[2], sharex=ax1)
    H = r["horas"]; x = list(range(24))

    ax1.bar(x, [h["vazao"] for h in H], width=1, align="edge", color="#2196F3", alpha=0.85, edgecolor="white",
            label="Vazão bombeada (m³/h)")
    dem = [h["demanda"] for h in H]
    ax1.step(range(25), dem + [dem[-1]], where="post", color="#37474F", linestyle="--", linewidth=1.6,
             label="Demanda dos setores (m³/h)")
    ax1.axhline(Q_ETA_MAX, color="#9E9E9E", linestyle=":", linewidth=1)
    ax1.set_ylim(0, max(max(dem), Q_ETA_MAX) * 1.3)
    ax1.set_ylabel("m³/h"); ax1.set_title("Bombeamento × demanda × tarifa de energia (por hora)", fontsize=11)
    tw = ax1.twinx()
    tar = [h["tarifa"] for h in H]
    tw.step(range(25), tar + [tar[-1]], where="post", color="#E65100", linewidth=2, label="Tarifa (R$/kWh)")
    tw.set_ylabel("R$/kWh", color="#E65100"); tw.tick_params(axis="y", labelcolor="#E65100")
    tw.set_ylim(0, max(tar) * 1.25)
    h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = tw.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8, ncol=3)

    for p in BOMBAS:
        on = [(h["t"], 1) for h in H if p in h["ligadas"]]
        if on:
            ax2.broken_barh(on, (p - 0.4, 0.8), facecolors="#43A047", edgecolor="white")
    ax2.set_ylim(6.6, 0.4)
    ax2.set_yticks(list(BOMBAS)); ax2.set_yticklabels([f"Bomba {p} ({PARAM_BOMBAS[p][0]} kW)" for p in BOMBAS], fontsize=8)
    ax2.set_title("Horários em que cada bomba fica LIGADA (verde)", fontsize=11)
    ax2.grid(True, axis="x", linestyle="--", alpha=0.4)

    cores = ["#2E7D32", "#7CB342", "#C0CA33", "#FBC02D", "#FB8C00"]
    for i, rsv in enumerate(RESERVATORIOS):
        ax3.plot(range(25), r["vol"][rsv], marker="o", markersize=3, linewidth=1.8, color=cores[i],
                 label=f"Reserv. {rsv}")
    ax3.set_ylabel("m³"); ax3.set_xlabel("Hora do dia (faixa [h, h+1))")
    ax3.set_title("Nível dos reservatórios (carregam fora da ponta e descarregam na ponta)", fontsize=11)
    ax3.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8); ax3.grid(True, linestyle="--", alpha=0.4)

    for ax in (ax1, ax2, ax3):
        ax.axvspan(min(HORAS_PONTA), max(HORAS_PONTA) + 1, color="red", alpha=0.10, zorder=0)
    ax1.set_xlim(0, 24); ax3.set_xticks(range(0, 25, 2))
    for ax in (ax1, ax2):
        ax.tick_params(labelbottom=False)


# ----------------------------------------------------------------------------- interface
def _num(s):
    s = str(s).strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ETA — agendamento de bombas com tarifas ANEEL (Pyomo + HiGHS)")
        self.geometry("1320x860"); self.minsize(1100, 720)
        try:
            self.csv = achar_csv([Path(__file__).resolve().parent, *Path(__file__).resolve().parents])
        except FileNotFoundError:
            from tkinter import filedialog
            caminho = filedialog.askopenfilename(title="Selecione o CSV de tarifas homologadas da ANEEL",
                                                 filetypes=[("CSV", "*.csv")])
            if not caminho:
                self.ok = False; return
            self.csv = Path(caminho)
        self.ok = True
        self.fila = queue.Queue()
        self.dem_max = eta_pyomo.demanda_maxima_viavel()   # LP rápido, calculado ao abrir
        self._montar()

    def _montar(self):
        esq = ttk.Frame(self, padding=10); esq.grid(row=0, column=0, sticky="ns")
        dir_ = ttk.Frame(self, padding=(0, 10, 10, 10)); dir_.grid(row=0, column=1, sticky="nsew")
        self.columnconfigure(1, weight=1); self.rowconfigure(0, weight=1)

        ent = ttk.LabelFrame(esq, text="Dados de entrada", padding=10); ent.pack(fill="x")
        self.v_dem = tk.StringVar(value=f"{DEMANDA_DIARIA_BASE:.1f}".replace(".", ","))
        self.v_gap = tk.StringVar(value="1")
        self.v_lim = tk.StringVar(value="60")
        self.v_dist = tk.StringVar(value=DISTRIBUIDORAS_SP[0])
        self.v_mod = tk.StringVar(value="Verde")
        self.v_data = tk.StringVar(value=dt.date.today().strftime("%d/%m/%Y"))
        linhas = [("Demanda de água do dia (m³/dia)", ttk.Entry(ent, textvariable=self.v_dem, width=18)),
                  ("MIPGap (%)", ttk.Entry(ent, textvariable=self.v_gap, width=18)),
                  ("Limite de tempo (s)", ttk.Entry(ent, textvariable=self.v_lim, width=18)),
                  ("Distribuidora", ttk.Combobox(ent, textvariable=self.v_dist, values=DISTRIBUIDORAS_SP,
                                                 state="readonly", width=16)),
                  ("Modalidade (A4)", ttk.Combobox(ent, textvariable=self.v_mod, values=["Verde", "Azul"],
                                                   state="readonly", width=16)),
                  ("Data de referência", ttk.Entry(ent, textvariable=self.v_data, width=18))]
        for i, (txt, w) in enumerate(linhas):
            ttk.Label(ent, text=txt).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 8)); w.grid(row=i, column=1, pady=3)
        ttk.Label(ent, foreground="#555", wraplength=300, justify="left",
                  text=f"Demanda do cenário do notebook: {br(DEMANDA_DIARIA_BASE, 1)} m³/dia. Capacidade máxima da "
                       f"ETA: {br(CAPACIDADE_DIA)} m³/dia (600 m³/h × 24 h), mas com a curva de demanda e os "
                       f"reservatórios do modelo o máximo atendível é {br(self.dem_max)} m³/dia. O consumo de "
                       "energia (kWh) é o resultado da otimização."
                  ).grid(row=len(linhas), column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.btn = ttk.Button(esq, text="Otimizar", command=self._executar); self.btn.pack(fill="x", pady=(10, 4))
        self.pb = ttk.Progressbar(esq, mode="indeterminate"); self.pb.pack(fill="x")
        self.status = tk.StringVar(value="Informe os dados e clique em Otimizar.")
        ttk.Label(esq, textvariable=self.status, wraplength=320, foreground="#333").pack(anchor="w", pady=(4, 8))

        res = ttk.LabelFrame(esq, text="Resultado", padding=8); res.pack(fill="both", expand=True)
        self.txt = tk.Text(res, width=44, height=22, font=("Consolas", 10), wrap="word", relief="flat",
                           background=self.cget("background"))
        self.txt.pack(fill="both", expand=True); self.txt.configure(state="disabled")

        self.abas = ttk.Notebook(dir_); self.abas.pack(fill="both", expand=True)
        aba1 = ttk.Frame(self.abas); aba2 = ttk.Frame(self.abas)
        self.abas.add(aba1, text="Gráficos por hora"); self.abas.add(aba2, text="Horários das bombas")
        self.fig = Figure(figsize=(9, 8), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=aba1); self.canvas.get_tk_widget().pack(fill="both", expand=True)

        ttk.Label(aba2, text="Quando ligar cada bomba", font=("", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.t_bombas = ttk.Treeview(aba2, columns=("bomba", "horarios", "horas"), show="headings", height=6)
        for c, tx, w in (("bomba", "Bomba", 120), ("horarios", "Ligada nos horários", 520), ("horas", "Horas ligada", 100)):
            self.t_bombas.heading(c, text=tx); self.t_bombas.column(c, width=w, anchor="w")
        self.t_bombas.pack(fill="x", padx=8)
        ttk.Label(aba2, text="Plano hora a hora", font=("", 11, "bold")).pack(anchor="w", padx=8, pady=(12, 2))
        fr = ttk.Frame(aba2); fr.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.t_horas = ttk.Treeview(fr, columns=("hora", "faixa", "tarifa", "bombas", "vazao", "dem", "kw"),
                                    show="headings")
        for c, tx, w in (("hora", "Hora", 110), ("faixa", "Faixa", 90), ("tarifa", "Tarifa R$/kWh", 100),
                         ("bombas", "Bombas ligadas", 170), ("vazao", "Vazão m³/h", 90),
                         ("dem", "Demanda m³/h", 100), ("kw", "Potência kW", 90)):
            self.t_horas.heading(c, text=tx); self.t_horas.column(c, width=w, anchor="center")
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.t_horas.yview); self.t_horas.configure(yscrollcommand=sb.set)
        self.t_horas.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.t_horas.tag_configure("ponta", background="#FFEBEE")

    # -- leitura e execução
    def _ler(self):
        try:
            dem = _num(self.v_dem.get()); gap = _num(self.v_gap.get()); lim = _num(self.v_lim.get())
        except ValueError:
            raise ValueError("Use apenas números nos campos de demanda, MIPGap e limite de tempo.")
        if dem <= 0: raise ValueError("A demanda deve ser maior que zero.")
        if dem > self.dem_max:
            raise ValueError(f"Demanda acima do máximo que o modelo consegue atender ({br(self.dem_max)} m³/dia). "
                             f"A capacidade de {br(CAPACIDADE_DIA)} m³/dia só vale se a demanda fosse constante o dia "
                             "todo; com picos e o armazenamento limitado dos reservatórios, não dá.")
        if not 0 < gap <= 50: raise ValueError("O MIPGap deve estar entre 0 e 50 (%).")
        if lim < 1: raise ValueError("O limite de tempo deve ser de pelo menos 1 s.")
        s = self.v_data.get().strip()
        for f in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                data = dt.datetime.strptime(s, f); break
            except ValueError:
                data = None
        if data is None: raise ValueError("Data inválida. Use DD/MM/AAAA.")
        return dict(demanda_m3=dem, gap=gap / 100, limite=lim, distribuidora=self.v_dist.get(),
                    modalidade=self.v_mod.get(), data_ref=data)

    def _executar(self):
        try:
            p = self._ler()
        except ValueError as e:
            messagebox.showwarning("Dados inválidos", str(e)); return
        self.btn.configure(state="disabled"); self.pb.start(12)
        self.status.set(f"Resolvendo ({p['distribuidora']} · {p['modalidade']})... pode levar até {p['limite']:.0f} s.")

        def trabalho():
            try:
                self.fila.put(("ok", otimizar(self.csv, **p)))
            except Exception as e:
                self.fila.put(("erro", str(e)))
        threading.Thread(target=trabalho, daemon=True).start()
        self.after(200, self._verificar)

    def _verificar(self):
        try:
            tipo, dado = self.fila.get_nowait()
        except queue.Empty:
            self.after(200, self._verificar); return
        self.pb.stop(); self.btn.configure(state="normal")
        if tipo == "erro":
            self.status.set("Falha na otimização."); messagebox.showerror("Erro", dado); return
        self._mostrar(dado)

    # -- apresentação
    def _mostrar(self, r):
        ok = r["term"] == "optimal"
        self.status.set(f"Pronto em {br(r['tempo'], 1)} s: solução a no máximo {br(r['gap']*100, 2)}% do ótimo "
                        + ("(dentro do MIPGap pedido)." if ok else "(limite de tempo atingido antes do MIPGap pedido)."))
        L = [f"{r['distribuidora']} · {r['modalidade']} · A4", f"Tarifa consultada em {r['vigencia_ref']}", "",
             f"Tarifa fora ponta: R$ {br(r['fp'], 4)}/kWh", f"Tarifa ponta:      R$ {br(r['pt'], 4)}/kWh", "",
             f"Demanda de água:   {br(r['demanda_m3'])} m³/dia",
             f"CUSTO DE ENERGIA:  R$ {br(r['custo'], 2)}/dia",
             f"Energia (kWh/dia): {br(r['kwh'])}",
             f"  na ponta:        {br(r['kwh_ponta'])} kWh ({br(r['kwh_ponta']/r['kwh']*100, 1)}%)",
             f"Potência média:    {br(r['kw_medio'])} kW", f"Potência máxima:   {br(r['kw_max'])} kW",
             f"Custo médio:       R$ {br(r['custo']/r['kwh'], 3)}/kWh"]
        if r["dem_dia"] is not None:
            L += ["", f"Demanda estimada:  R$ {br(r['dem_dia'], 2)}/dia",
                  f"TOTAL ESTIMADO:    R$ {br(r['total_est'], 2)}/dia",
                  "(demanda estimada pela potência máx.;", " não é otimizada pelo modelo)"]
        if r["aviso"]:
            L += ["", "AVISO: " + r["aviso"]]
        self.txt.configure(state="normal"); self.txt.delete("1.0", "end"); self.txt.insert("1.0", "\n".join(L))
        self.txt.configure(state="disabled")

        desenhar(self.fig, r); self.canvas.draw()
        for t in (self.t_bombas, self.t_horas):
            t.delete(*t.get_children())
        for p in BOMBAS:
            hs = [h["t"] for h in r["horas"] if p in h["ligadas"]]
            self.t_bombas.insert("", "end", values=(f"Bomba {p} ({PARAM_BOMBAS[p][0]} kW)",
                                                    ", ".join(intervalos(hs)) or "— (não liga)", len(hs)))
        for h in r["horas"]:
            self.t_horas.insert("", "end", tags=("ponta",) if h["ponta"] else (), values=(
                f"{h['t']:02d}:00–{h['t']+1:02d}:00", "PONTA" if h["ponta"] else "fora ponta",
                br(h['tarifa'], 4), ", ".join(map(str, h["ligadas"])) or "—", f"{h['vazao']:.0f}",
                f"{h['demanda']:.0f}", f"{h['kw']:.0f}"))


if __name__ == "__main__":
    app = App()
    if app.ok:
        app.mainloop()
