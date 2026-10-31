"""Dados do problema (iguais ao notebook ETA_agendamento_bombas_tarifa_aneel_sp.ipynb)."""
import functools
from pathlib import Path
import pandas as pd

HORAS_PONTA = (17, 18, 19)
BOMBAS = range(1, 7)
RESERVATORIOS = range(1, 6)
SETORES = range(1, 13)
ARCOS_PR = [(1,1),(2,1),(2,2),(2,3),(3,2),(4,3),(4,4),(5,5),(6,4),(6,5)]
ARCOS_RS = [(1,1),(1,2),(1,3),(2,2),(2,4),(2,5),(3,4),(3,6),(3,7),(4,4),(4,8),(4,9),(4,10),(4,12),
            (5,7),(5,10),(5,11),(5,12)]
PARAM_BOMBAS = {1:(60,0,150), 2:(120,0,280), 3:(70,0,150), 4:(80,0,180), 5:(50,0,120), 6:(70,0,150)}  # kW, Qmin, Qmax
Q_ETA_MAX = 600
PARAM_RES = {1:(135,900,270), 2:(90,600,180), 3:(90,600,180), 4:(90,600,180), 5:(45,300,90)}  # Vmin, Vmax, Vini
BASE_DEMANDA = {1:20,2:30,3:25,4:40,5:25,6:20,7:35,8:30,9:20,10:45,11:25,12:18}
CURVA_VERAO = [0.8,0.5,0.3,0.4,0.6,1.0, 1.8,2.0,1.9,1.7,1.5,1.5, 1.4,1.5,1.6,1.7,1.8,2.9, 3.4,3.0,2.6,2.0,1.5,1.0]
DISTRIBUIDORAS_SP = ["ELETROPAULO", "EDP SP", "CPFL-PAULISTA", "CPFL-PIRATINING", "CPFL Santa Cruz", "ELEKTRO"]
NOME_CSV = "tarifas-homologadas-distribuidoras-energia-eletrica.csv"

# Demanda diária de água do cenário do notebook (m³/dia) = soma(base) x soma(curva)
DEMANDA_DIARIA_BASE = round(sum(BASE_DEMANDA.values()) * sum(CURVA_VERAO), 1)   # 12.787,2

def demanda(dias=1, fator=1.0):
    """Demanda horária por setor (m³/h). `fator` escala a curva; dias>1 repete a curva."""
    return {(d, t): round(BASE_DEMANDA[d] * CURVA_VERAO[t % 24] * fator, 4)
            for d in SETORES for t in range(24 * dias)}

def achar_csv(extra=()):
    """Procura dados/<csv> na pasta atual, nas pastas acima dela e nas pastas do script."""
    bases = [Path.cwd(), *Path.cwd().parents, *[Path(p) for p in extra]]
    for b in bases:
        c = b / "dados" / NOME_CSV
        if c.is_file():
            return c
    raise FileNotFoundError(f"Arquivo dados/{NOME_CSV} não encontrado a partir de {Path.cwd()}")

@functools.lru_cache(maxsize=2)
def carregar_csv(csv):
    df = pd.read_csv(csv, sep=";", dtype=str)
    for c in ["DatInicioVigencia", "DatFimVigencia"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ["VlrTUSD", "VlrTE"]:
        df[c] = pd.to_numeric(df[c].str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")
    return df

def _filtro(df, distribuidora, modalidade, subgrupo, data_ref, unidade):
    d = pd.Timestamp(data_ref)
    return df[(df.SigAgente == distribuidora) & (df.DatInicioVigencia <= d) & (df.DatFimVigencia >= d)
              & (df.DscBaseTarifaria == "Tarifa de Aplicação") & (df.DscModalidadeTarifaria == modalidade)
              & (df.DscSubGrupo == subgrupo) & (df.DscClasse == "Não se aplica") & (df.DscSubClasse == "Não se aplica")
              & (df.DscDetalhe == "Não se aplica") & (df.SigAgenteAcessante == "Não se aplica")
              & (df.DscUnidadeTerciaria == unidade)]

def tarifa_aneel(csv, distribuidora="ELETROPAULO", modalidade="Verde", subgrupo="A4", data_ref="2026-10-06"):
    """(fora_ponta, ponta) em R$/kWh = (TUSD + TE)/1000 — mesma lógica do notebook."""
    f = _filtro(carregar_csv(str(csv)), distribuidora, modalidade, subgrupo, data_ref, "MWh")
    f = f[f.NomPostoTarifario.isin(["Ponta", "Fora ponta"])]
    if f.empty:
        raise ValueError(f"Sem tarifa para {distribuidora} / {modalidade} / {subgrupo} em {pd.Timestamp(data_ref).date()}")
    v = ((f.VlrTUSD.fillna(0) + f.VlrTE.fillna(0)) / 1000).groupby(f.NomPostoTarifario).first()
    return float(v["Fora ponta"]), float(v["Ponta"])

def tarifa_demanda_kw(csv, distribuidora="ELETROPAULO", modalidade="Verde", subgrupo="A4", data_ref="2026-10-06"):
    """Tarifa de demanda (TUSD em R$/kW). Azul: {'ponta','fora_ponta'}; Verde: {'unica'}."""
    f = _filtro(carregar_csv(str(csv)), distribuidora, modalidade, subgrupo, data_ref, "kW")
    por_posto = f.groupby("NomPostoTarifario")["VlrTUSD"].first()
    if modalidade == "Azul":
        return {"ponta": float(por_posto["Ponta"]), "fora_ponta": float(por_posto["Fora ponta"])}
    return {"unica": float(por_posto["Não se aplica"])}

def data_efetiva(csv, distribuidora, modalidade="Verde", subgrupo="A4", data_ref=None):
    """Data a usar na consulta de tarifa. Se o CSV não tiver vigência na data pedida (ex.: reajuste ainda não
    publicado), usa a vigência mais recente anterior e devolve um aviso. Retorna (data_usada, aviso|None)."""
    ref = pd.Timestamp(data_ref) if data_ref is not None else pd.Timestamp.today().normalize()
    df = carregar_csv(str(csv))
    f = df[(df.SigAgente == distribuidora) & (df.DscBaseTarifaria == "Tarifa de Aplicação")
           & (df.DscModalidadeTarifaria == modalidade) & (df.DscSubGrupo == subgrupo)
           & (df.DscClasse == "Não se aplica") & (df.DscSubClasse == "Não se aplica")
           & (df.DscDetalhe == "Não se aplica") & (df.SigAgenteAcessante == "Não se aplica")]
    anteriores = f[f.DatInicioVigencia <= ref]
    if anteriores.empty:
        raise ValueError(f"Sem tarifa de {distribuidora} / {modalidade} / {subgrupo} até {ref.date()}.")
    if ((anteriores.DatFimVigencia >= ref)).any():
        return ref, None
    ult = anteriores.sort_values(["DatInicioVigencia", "DatFimVigencia"]).iloc[-1]
    ini, fim = pd.Timestamp(ult.DatInicioVigencia), pd.Timestamp(ult.DatFimVigencia)
    return ini, (f"O CSV não tem tarifa vigente em {ref.strftime('%d/%m/%Y')} para {distribuidora}. "
                 f"Usada a vigência mais recente: {ini.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}.")
