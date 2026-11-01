"""Cálculos de sensibilidade hidráulica, sem alterar a otimização da ETA."""

ALTURAS_HIPOTETICAS_MCA = (30, 50, 80)
RENDIMENTO_GLOBAL_HIPOTETICO = 0.75
DENSIDADE_AGUA_KG_M3 = 1000
GRAVIDADE_M_S2 = 9.81


def potencia_entrada_estimada_kw(vazao_m3_h, altura_mca,
                                 rendimento=RENDIMENTO_GLOBAL_HIPOTETICO):
    """Estima potência de entrada usando Q×H; não substitui curva de bomba."""
    if vazao_m3_h < 0:
        raise ValueError("A vazão não pode ser negativa.")
    if altura_mca < 0:
        raise ValueError("A altura manométrica não pode ser negativa.")
    if not 0 < rendimento <= 1:
        raise ValueError("O rendimento deve ser maior que zero e menor ou igual a 1.")

    vazao_m3_s = vazao_m3_h / 3600
    potencia_hidraulica_w = DENSIDADE_AGUA_KG_M3 * GRAVIDADE_M_S2 * vazao_m3_s * altura_mca
    return potencia_hidraulica_w / rendimento / 1000
