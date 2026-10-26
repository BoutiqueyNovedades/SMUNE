"""Calculadoras financieras puras para escenarios de inversión."""


def valor_presente_neto(inversion, flujo_anual, tasa, anios, valor_residual=0):
    """VPN con desembolso inicial en t=0 y flujos netos uniformes."""
    vpn = -inversion
    for periodo in range(1, anios + 1):
        flujo = flujo_anual
        if periodo == anios:
            flujo += valor_residual
        vpn += flujo / ((1 + tasa) ** periodo)
    return vpn


def tasa_interna_retorno(inversion, flujo_anual, anios, valor_residual=0):
    """TIR aproximada por bisección para un flujo convencional de inversión."""
    if inversion <= 0 or anios <= 0 or flujo_anual < 0:
        return None

    def vpn(tasa):
        return valor_presente_neto(
            inversion, flujo_anual, tasa, anios, valor_residual
        )

    bajo, alto = -0.99, 1.0
    valor_bajo = vpn(bajo)
    valor_alto = vpn(alto)
    while valor_alto > 0 and alto < 1_000_000:
        alto = (alto * 2) + 1
        valor_alto = vpn(alto)
    if (valor_bajo > 0) == (valor_alto > 0):
        return None

    for _ in range(200):
        medio = (bajo + alto) / 2
        valor = vpn(medio)
        if abs(valor) < 1e-8:
            return medio
        if (valor_bajo > 0) != (valor > 0):
            alto = medio
            valor_alto = valor
        else:
            bajo = medio
            valor_bajo = valor
    return (bajo + alto) / 2


def factor_recuperacion_capital(tasa, anios):
    if anios <= 0:
        raise ValueError("El plazo debe ser mayor que cero.")
    if tasa == 0:
        return 1 / anios
    potencia = (1 + tasa) ** anios
    return tasa * potencia / (potencia - 1)


def costo_anual_equivalente(inversion, costo_anual, tasa, anios, valor_residual=0):
    """CAE de costos: inversión anualizada + costos - valor residual anualizado."""
    factor = factor_recuperacion_capital(tasa, anios)
    if tasa == 0:
        recuperacion_residual = valor_residual / anios
    else:
        recuperacion_residual = valor_residual * tasa / (((1 + tasa) ** anios) - 1)
    return inversion * factor + costo_anual - recuperacion_residual


def analizar_escenario(inversion, ingresos_anuales, costos_anuales, tasa, anios, valor_residual=0):
    flujo_neto = ingresos_anuales - costos_anuales
    vpn = valor_presente_neto(inversion, flujo_neto, tasa, anios, valor_residual)
    tir = tasa_interna_retorno(inversion, flujo_neto, anios, valor_residual)
    cae = costo_anual_equivalente(
        inversion, costos_anuales, tasa, anios, valor_residual
    )
    factor = factor_recuperacion_capital(tasa, anios)
    return {
        "vpn": vpn,
        "tir": tir,
        "cae": cae,
        "flujo_neto_anual": flujo_neto,
        "beneficio_anual_equivalente": vpn * factor,
    }
