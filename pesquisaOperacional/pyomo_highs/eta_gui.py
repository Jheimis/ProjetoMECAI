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
from eta_comparacao import (ALTURAS_HIPOTETICAS_MCA, RENDIMENTO_GLOBAL_HIPOTETICO,
                            potencia_entrada_estimada_kw)
from eta_dados import (BOMBAS, DEMANDA_DIARIA_BASE, DISTRIBUIDORAS_SP, HORAS_PONTA, PARAM_BOMBAS, PARAM_RES,
                       Q_ETA_MAX, RESERVATORIOS, SETORES, achar_csv, data_efetiva, demanda, tarifa_aneel,
                       tarifa_demanda_kw)

CAPACIDADE_DIA = Q_ETA_MAX * 24  # m³/dia


def br(v, nd=0):
    """Formata número no padrão brasileiro: 12.787,2"""
    return f"{v:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def custo_plano(horas, tarifa_demanda, dias):
    """Calcula custo de energia e demanda usando o mesmo horizonte e tarifas."""
    energia = sum(h["kw"] * h["tarifa"] for h in horas)
    if "unica" in tarifa_demanda:
        pico = max(h["kw"] for h in horas)
        demanda_custo = dias / 30 * tarifa_demanda["unica"] * pico
    else:
        pico_ponta = max(h["kw"] for h in horas if h["ponta"])
        pico_fora = max(h["kw"] for h in horas if not h["ponta"])
        demanda_custo = dias / 30 * (
            tarifa_demanda["ponta"] * pico_ponta + tarifa_demanda["fora_ponta"] * pico_fora
        )
    return energia, demanda_custo


# ----------------------------------------------------------------------------- núcleo (sem Tkinter)
def otimizar(csv, demanda_m3, gap, limite, distribuidora, modalidade, data_ref, subgrupo="A4", dias=1):
    """Resolve o modelo e devolve um dicionário com tudo que a tela precisa mostrar."""
    if not isinstance(dias, int) or isinstance(dias, bool) or dias < 1:
        raise ValueError("A quantidade de dias deve ser um número inteiro positivo.")
    data_uso, aviso = data_efetiva(csv, distribuidora, modalidade, subgrupo, data_ref)
    fp, pt = tarifa_aneel(csv, distribuidora, modalidade, subgrupo, data_uso)
    td = tarifa_demanda_kw(csv, distribuidora, modalidade, subgrupo, data_uso)
    fator = demanda_m3 / DEMANDA_DIARIA_BASE
    referencia = eta_pyomo.construir_referencia_demanda(dias=dias, fator_demanda=fator)
    try:
        tempo_ref, _, gap_ref, term_ref = eta_pyomo.resolver(referencia, gap=gap, limite=limite)
    except Exception as e:
        raise RuntimeError("Não foi possível calcular a referência sem otimização tarifária. "
                           "Tente aumentar o limite de tempo.") from e
    horas_ref = []
    for t in referencia.H:
        if any(pyo.value(referencia.x[p, t]) is None for p in referencia.P):
            raise RuntimeError("O solver não encontrou um plano viável para a referência sem otimização tarifária.")
        horas_ref.append({
            "ponta": t % 24 in HORAS_PONTA,
            "tarifa": pt if t % 24 in HORAS_PONTA else fp,
            "kw": sum(PARAM_BOMBAS[p][0] for p in referencia.P
                      if pyo.value(referencia.x[p, t]) > 0.5),
        })
    energia_ref, demanda_ref = custo_plano(horas_ref, td, dias)
    total_ref = energia_ref + demanda_ref

    m = eta_pyomo.construir(fp, pt, dias=dias, fator_demanda=fator, tarifa_demanda=td)
    try:
        tempo, _, gap_final, term = eta_pyomo.resolver(m, gap=gap, limite=limite)
    except Exception as e:  # HiGHS sem solução viável (inviável ou limite de tempo)
        raise RuntimeError("Não foi encontrada solução viável dentro do limite de tempo. Tente aumentar o limite de "
                           "tempo ou o MIPGap, ou reduzir a demanda (o máximo atendível aparece no painel de "
                           "entrada).") from e
    if "nfeasible" in term:
        raise RuntimeError("Modelo inviável para essa demanda (a ETA não consegue atendê-la).")

    total_horas = 24 * dias
    D = demanda(dias, fator)
    horas = []
    for t in range(total_horas):
        ligadas = [p for p in BOMBAS if pyo.value(m.x[p, t]) > 0.5]
        horas.append({"t": t, "dia": t // 24 + 1, "hora": t % 24, "ponta": t % 24 in HORAS_PONTA,
                      "tarifa": pt if t % 24 in HORAS_PONTA else fp, "ligadas": ligadas,
                      "vazao": sum(pyo.value(m.q[p, t]) for p in BOMBAS),
                      "kw": sum(PARAM_BOMBAS[p][0] for p in ligadas),
                      "demanda": sum(D[s, t] for s in SETORES)})
    vol = {r: [PARAM_RES[r][2]] + [pyo.value(m.V[r, t]) for t in range(total_horas)]
           for r in RESERVATORIOS}
    kwh = sum(h["kw"] for h in horas)
    kwh_ponta = sum(h["kw"] for h in horas if h["ponta"])
    custo_energia = pyo.value(m.custo_energia)
    dem_dia = pyo.value(m.custo_demanda)
    total_otimizado = custo_energia + dem_dia
    economia = total_ref - total_otimizado
    economia_pct = 100 * economia / total_ref if total_ref else 0
    return {"horas": horas, "vol": vol, "dias": dias, "custo": custo_energia, "kwh": kwh,
            "kwh_ponta": kwh_ponta, "kw_max": max(h["kw"] for h in horas),
            "kw_medio": kwh / total_horas, "gap": gap_final, "tempo": tempo,
            "term": term, "fp": fp, "pt": pt, "aviso": aviso, "dem_dia": dem_dia, "demanda_m3": demanda_m3,
            "total_est": total_otimizado, "total_referencia": total_ref, "energia_referencia": energia_ref,
            "demanda_referencia": demanda_ref, "economia": economia, "economia_pct": economia_pct,
            "tempo_referencia": tempo_ref, "gap_referencia": gap_ref, "term_referencia": term_ref,
            "distribuidora": distribuidora,
            "modalidade": modalidade, "vigencia_ref": pd_fmt(data_uso)}


def pd_fmt(d):
    return d.strftime("%d/%m/%Y")


def intervalos(horas_ligadas):
    """[0,1,2,5] -> ['00:00–03:00', '05:00–06:00']"""
    por_dia = {}
    for hora in sorted(horas_ligadas):
        dia, hora_dia = divmod(hora, 24)
        por_dia.setdefault(dia, []).append(hora_dia)
    out = []
    for dia, horas in por_dia.items():
        ini = ant = horas[0]
        for hora in horas[1:]:
            if hora != ant + 1:
                out.append((dia, ini, ant + 1))
                ini = hora
            ant = hora
        out.append((dia, ini, ant + 1))
    return [f"Dia {dia + 1}: {a:02d}:00–{b:02d}:00" for dia, a, b in out]


def desenhar(fig, r):
    fig.clear()
    gs = fig.add_gridspec(3, 1, height_ratios=[2.2, 1.6, 2.0], hspace=0.42, left=0.15, right=0.80, top=0.95, bottom=0.10)
    ax1 = fig.add_subplot(gs[0]); ax2 = fig.add_subplot(gs[1], sharex=ax1); ax3 = fig.add_subplot(gs[2], sharex=ax1)
    H = r["horas"]; total_horas = 24 * r["dias"]; x = list(range(total_horas))

    ax1.bar(x, [h["vazao"] for h in H], width=1, align="edge", color="#2196F3", alpha=0.85, edgecolor="white",
            label="Vazão bombeada (m³/h)")
    dem = [h["demanda"] for h in H]
    ax1.step(range(total_horas + 1), dem + [dem[-1]], where="post", color="#37474F", linestyle="--", linewidth=1.6,
             label="Demanda dos setores (m³/h)")
    ax1.axhline(Q_ETA_MAX, color="#9E9E9E", linestyle=":", linewidth=1)
    ax1.set_ylim(0, max(max(dem), Q_ETA_MAX) * 1.3)
    ax1.set_ylabel("m³/h"); ax1.set_title("Bombeamento × demanda × tarifa de energia (por hora)", fontsize=11)
    tw = ax1.twinx()
    tar = [h["tarifa"] for h in H]
    tw.step(range(total_horas + 1), tar + [tar[-1]], where="post", color="#E65100", linewidth=2,
            label="Tarifa (R$/kWh)")
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
        ax3.plot(range(total_horas + 1), r["vol"][rsv], marker="o", markersize=3, linewidth=1.8, color=cores[i],
                 label=f"Reserv. {rsv}")
    ax3.set_ylabel("m³")
    if r["dias"] == 1:
        ax3.set_xlabel("Hora do dia (faixa [h, h+1))")
        ax3.set_xticks(range(0, total_horas + 1, 2))
    else:
        ax3.set_xlabel("Dia do horizonte")
        ax3.set_xticks([24 * dia + 12 for dia in range(r["dias"])])
        ax3.set_xticklabels([f"Dia {dia + 1}" for dia in range(r["dias"])])
    ax3.set_title("Nível dos reservatórios (carregam fora da ponta e descarregam na ponta)", fontsize=11)
    ax3.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8); ax3.grid(True, linestyle="--", alpha=0.4)

    for dia in range(r["dias"]):
        for ax in (ax1, ax2, ax3):
            ax.axvspan(24 * dia + min(HORAS_PONTA), 24 * dia + max(HORAS_PONTA) + 1,
                       color="red", alpha=0.10, zorder=0)
    ax1.set_xlim(0, total_horas)
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
        self.v_dias = tk.StringVar(value="1")
        self.v_gap = tk.StringVar(value="1")
        self.v_lim = tk.StringVar(value="60")
        self.v_dist = tk.StringVar(value=DISTRIBUIDORAS_SP[0])
        self.v_mod = tk.StringVar(value="Verde")
        self.v_data = tk.StringVar(value=dt.date.today().strftime("%d/%m/%Y"))
        linhas = [("Demanda de água do dia (m³/dia)", ttk.Entry(ent, textvariable=self.v_dem, width=18)),
                  ("Quantidade de dias", ttk.Entry(ent, textvariable=self.v_dias, width=18)),
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
                  text=f"Demanda do cenário do notebook: {br(DEMANDA_DIARIA_BASE, 1)} m³/dia. Capacidade teórica "
                       f"da ETA: {br(CAPACIDADE_DIA)} m³/dia. Para 1 dia, o máximo atendível estimado é "
                       f"{br(self.dem_max)} m³/dia. Com mais dias, a curva se repete e os reservatórios são "
                       "considerados continuamente; o tempo de solução pode aumentar."
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
        aba1 = ttk.Frame(self.abas); aba2 = ttk.Frame(self.abas); aba3 = ttk.Frame(self.abas)
        self.abas.add(aba1, text="Gráficos por hora"); self.abas.add(aba2, text="Horários das bombas")
        self.abas.add(aba3, text="Sensibilidade hidráulica")
        self.fig = Figure(figsize=(9, 8), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=aba1); self.canvas.get_tk_widget().pack(fill="both", expand=True)

        ttk.Label(aba3, text="Estimativa por porte de vazão (não representa modelos KSB)",
                  font=("", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 4))
        ttk.Label(
            aba3, justify="left", wraplength=950,
            text=("Potência de entrada estimada na vazão máxima cadastrada para cada bomba, "
                  f"com rendimento global hipotético de {RENDIMENTO_GLOBAL_HIPOTETICO:.0%}. "
                  "As alturas abaixo são cenários de sensibilidade, não medições da ETA. "
                  "O cálculo usa apenas potência hidráulica (densidade da água × gravidade × vazão × altura) "
                  "e não considera curvas reais, perdas da tubulação, variação de rendimento ou ponto de operação. "
                  "Não altera o solver nem o custo apresentado na otimização.")
        ).pack(anchor="w", padx=8, pady=(0, 8))
        colunas = ("bomba", "vazao", "nominal", *(f"h{h}" for h in ALTURAS_HIPOTETICAS_MCA))
        self.t_sensibilidade = ttk.Treeview(aba3, columns=colunas, show="headings", height=8)
        titulos = [("bomba", "Bomba"), ("vazao", "Vazão máxima (m³/h)"),
                   ("nominal", "Potência no modelo (kW)")]
        titulos.extend((f"h{h}", f"{h} mca (kW)") for h in ALTURAS_HIPOTETICAS_MCA)
        for coluna, titulo in titulos:
            self.t_sensibilidade.heading(coluna, text=titulo)
            self.t_sensibilidade.column(coluna, width=145, anchor="center")
        self.t_sensibilidade.pack(fill="x", padx=8)
        for p in BOMBAS:
            kw, _, qmax = PARAM_BOMBAS[p]
            valores = (f"Bomba {p}", br(qmax), br(kw))
            valores += tuple(br(potencia_entrada_estimada_kw(qmax, h), 1)
                             for h in ALTURAS_HIPOTETICAS_MCA)
            self.t_sensibilidade.insert("", "end", values=valores)

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
        try:
            dias = int(self.v_dias.get().strip())
        except ValueError:
            raise ValueError("A quantidade de dias deve ser um número inteiro positivo.")
        if dias < 1:
            raise ValueError("A quantidade de dias deve ser pelo menos 1.")
        if dem <= 0: raise ValueError("A demanda deve ser maior que zero.")
        if dias == 1 and dem > self.dem_max:
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
        return dict(demanda_m3=dem, dias=dias, gap=gap / 100, limite=lim,
                    distribuidora=self.v_dist.get(), modalidade=self.v_mod.get(), data_ref=data)

    def _executar(self):
        try:
            p = self._ler()
        except ValueError as e:
            messagebox.showwarning("Dados inválidos", str(e)); return
        self.btn.configure(state="disabled"); self.pb.start(12)
        self.status.set(f"Calculando referência e otimizando {p['dias']} dia(s) "
                        f"({p['distribuidora']} · {p['modalidade']})... cada etapa pode levar até "
                        f"{p['limite']:.0f} s.")

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
        L = [f"{r['distribuidora']} · {r['modalidade']} · A4", f"Tarifa consultada em {r['vigencia_ref']}",
             f"Horizonte: {r['dias']} dia(s)", "",
             f"Tarifa fora ponta: R$ {br(r['fp'], 4)}/kWh", f"Tarifa ponta:      R$ {br(r['pt'], 4)}/kWh", "",
             f"Demanda de água:   {br(r['demanda_m3'])} m³/dia",
             f"CUSTO DE ENERGIA:  R$ {br(r['custo'], 2)} no horizonte",
             f"Energia:           {br(r['kwh'])} kWh ({br(r['kwh']/r['dias'])}/dia)",
             f"  na ponta:        {br(r['kwh_ponta'])} kWh ({br(r['kwh_ponta']/r['kwh']*100, 1)}%)",
             f"Potência média:    {br(r['kw_medio'])} kW", f"Potência máxima:   {br(r['kw_max'])} kW",
             f"Custo médio:       R$ {br(r['custo']/r['dias'], 2)}/dia"]
        rotulo_diferenca = "Economia estimada" if r["economia"] >= 0 else "Aumento estimado"
        L += ["", f"Demanda estimada:  R$ {br(r['dem_dia'], 2)} no horizonte",
              f"TOTAL DO PLANO:    R$ {br(r['total_est'], 2)} no horizonte",
              f"Média por dia:     R$ {br(r['total_est']/r['dias'], 2)}/dia",
              "(energia + demanda de potência)", "",
              "REFERÊNCIA SEM OTIMIZAÇÃO TARIFÁRIA",
              f"Custo estimado:    R$ {br(r['total_referencia'], 2)} no horizonte",
              "(bombeamento acompanha a demanda horária)",
              f"{rotulo_diferenca}: R$ {br(abs(r['economia']), 2)} ({br(abs(r['economia_pct']), 2)}%)",
              f"Referência: {r['term_referencia']}, gap {br(r['gap_referencia']*100, 2)}%"]
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
                                                    "; ".join(intervalos(hs)) or "— (não liga)", len(hs)))
        for h in r["horas"]:
            self.t_horas.insert("", "end", tags=("ponta",) if h["ponta"] else (), values=(
                f"Dia {h['dia']} · {h['hora']:02d}:00–{(h['hora']+1)%24:02d}:00",
                "PONTA" if h["ponta"] else "fora ponta",
                br(h['tarifa'], 4), ", ".join(map(str, h["ligadas"])) or "—", f"{h['vazao']:.0f}",
                f"{h['demanda']:.0f}", f"{h['kw']:.0f}"))


if __name__ == "__main__":
    app = App()
    if app.ok:
        app.mainloop()
