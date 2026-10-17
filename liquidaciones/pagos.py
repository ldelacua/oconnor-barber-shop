import json
from decimal import Decimal, localcontext
from pathlib import Path
from ventas.calculos import dinero
from ventas.pagos_calculos import leer_tipos_pago


def total_en_usd(total_bs, tasa):
    with localcontext() as contexto:
        contexto.prec = 60
        return dinero(Decimal(str(total_bs)) / Decimal(str(tasa)))


def preparar_pagos(filas, total_bs, tasa, catalogo, *, total_usd_objetivo):
    """Valida en la moneda de cobro; no confía en la moneda enviada por el navegador."""
    if not filas:
        raise ValueError("Registra al menos una forma de pago.")
    total_bs = dinero(total_bs)
    tasa = Decimal(str(tasa))
    total_usd = dinero(total_usd_objetivo)
    pagos = []
    for fila in filas:
        tipo = catalogo.get(int(fila["tipo_pago"]))
        if not tipo:
            raise ValueError("Una forma de pago no existe en el catálogo.")
        importe = Decimal(str(fila["monto"]))
        if not importe.is_finite() or importe <= 0 or importe != dinero(importe) or importe >= Decimal("10000000000000000"):
            raise ValueError("Cada pago debe tener un monto positivo con hasta dos decimales.")
        with localcontext() as contexto:
            contexto.prec = 60
            equivalente = dinero(importe * tasa) if tipo["moneda"] == "USD" else importe
        if abs(equivalente) >= Decimal("10000000000000000"):
            raise ValueError("Un pago supera el límite de importes del documento.")
        pagos.append({
            "tipo_pago": tipo["id"], "nombre_tipo_pago": tipo["nombre"], "moneda": tipo["moneda"],
            "fecha": fila["fecha"], "referencia": fila.get("referencia", ""),
            "observacion": fila.get("observacion", ""), "monto": importe,
            "equivalente_bs": equivalente, "ajuste_redondeo_bs": Decimal("0.00"),
        })
    suma_usd = sum((p["monto"] for p in pagos if p["moneda"] == "USD"), Decimal("0.00"))
    suma_bs = sum((p["monto"] for p in pagos if p["moneda"] == "BS"), Decimal("0.00"))
    solo_usd = all(p["moneda"] == "USD" for p in pagos)
    with localcontext() as contexto:
        contexto.prec = 60
        diferencia = dinero(total_usd - suma_usd) if solo_usd else dinero(total_bs - dinero(suma_usd * tasa) - suma_bs)
    moneda = "USD" if solo_usd else "Bs."
    if diferencia:
        accion = "Faltan" if diferencia > 0 else "Sobran"
        raise ValueError(f"{accion} {abs(diferencia):,.2f} {moneda} en los pagos. Deben cubrir exactamente el total de la liquidación.")
    # El ajuste solo concilia centavos de conversión cuando se cobra en USD.
    # No altera el importe realmente recibido ni admite faltantes/excedentes.
    ajuste = dinero(total_bs - sum((p["equivalente_bs"] for p in pagos), Decimal("0.00")))
    if ajuste:
        ultimo_usd = next((p for p in reversed(pagos) if p["moneda"] == "USD"), None)
        if ultimo_usd is None:
            raise ValueError("Los pagos en Bs. no coinciden con el total.")
        ultimo_usd["ajuste_redondeo_bs"] = ajuste
    return pagos
