import json
from decimal import Decimal, localcontext
from pathlib import Path
from .calculos import dinero


def leer_tipos_pago():
    ruta = Path(__file__).resolve().parent / "config" / "tipos_pago.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, list) or not datos:
        raise ValueError("El catálogo de pagos debe ser una lista no vacía.")
    catalogo = {}
    for fila in datos:
        codigo = fila["id"]
        nombre = fila["nombre"]
        moneda = fila["moneda"]
        if type(codigo) is not int or codigo <= 0 or codigo in catalogo:
            raise ValueError("Cada tipo de pago necesita un código entero positivo único.")
        if not isinstance(nombre, str) or not nombre.strip() or len(nombre) > 100 or moneda not in {"USD", "BS"}:
            raise ValueError("Cada tipo de pago necesita nombre y moneda USD o BS.")
        afecta_banco = fila.get('afecta_banco', codigo in (1, 2, 3, 4))
        if type(afecta_banco) is not bool:
            raise ValueError('Afecta banco debe ser verdadero o falso.')
        catalogo[codigo] = {"id": codigo, "nombre": nombre, "moneda": moneda, "afecta_banco": afecta_banco}
    return catalogo


def total_en_usd(total_bs, tasa):
    with localcontext() as contexto:
        contexto.prec = 60
        return dinero(Decimal(str(total_bs)) / Decimal(str(tasa)))


def preparar_pagos(filas, total_bs, tasa, catalogo):
    """Valida en la moneda de cobro; no confía en la moneda enviada por el navegador."""
    if not filas:
        raise ValueError("Registra al menos una forma de pago.")
    total_bs = dinero(total_bs)
    tasa = Decimal(str(tasa))
    total_usd = total_en_usd(total_bs, tasa)
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
        raise ValueError(f"{accion} {abs(diferencia):,.2f} {moneda} en los pagos. Deben cubrir exactamente el total con impuesto.")
    # El ajuste solo concilia centavos de conversión cuando se cobra en USD.
    # No altera el importe realmente recibido ni admite faltantes/excedentes.
    ajuste = dinero(total_bs - sum((p["equivalente_bs"] for p in pagos), Decimal("0.00")))
    if ajuste:
        ultimo_usd = next((p for p in reversed(pagos) if p["moneda"] == "USD"), None)
        if ultimo_usd is None:
            raise ValueError("Los pagos en Bs. no coinciden con el total.")
        ultimo_usd["ajuste_redondeo_bs"] = ajuste
    return pagos


def validar_pagos_guardados(pagos, total_bs, tasa, *, total_usd_objetivo=None):
    """Revalida montos y conversiones antes de finalizar un documento positivo."""
    total_bs = dinero(total_bs)
    tasa = Decimal(str(tasa))
    if tasa <= 0:
        raise ValueError('La tasa de cambio debe ser positiva.')
    if not pagos:
        if total_bs != 0:
            raise ValueError('El documento necesita pagos.')
        return
    if total_bs <= 0:
        raise ValueError('Un total cero o negativo no admite estos pagos.')
    suma_usd = Decimal('0.00')
    suma_bs = Decimal('0.00')
    equivalente_total = Decimal('0.00')
    ultimo_usd = next((i for i in range(len(pagos) - 1, -1, -1) if pagos[i].moneda == 'USD'), None)
    with localcontext() as contexto:
        contexto.prec = 60
        for indice, pago in enumerate(pagos):
            if pago.ajuste_redondeo_bs != 0 and indice != ultimo_usd:
                raise ValueError('El ajuste de conversión debe estar en el último pago en dólares.')
            if pago.moneda not in ('USD', 'BS') or pago.monto <= 0:
                raise ValueError('La moneda o el monto del pago no son válidos.')
            equivalente = dinero(pago.monto * tasa) if pago.moneda == 'USD' else pago.monto
            if pago.equivalente_bs != equivalente:
                raise ValueError('El equivalente del pago no coincide con la tasa.')
            if pago.moneda == 'BS':
                if pago.ajuste_redondeo_bs != 0:
                    raise ValueError('Un pago en bolívares no admite ajuste de conversión.')
                suma_bs += pago.monto
            else:
                suma_usd += pago.monto
            equivalente_total += pago.equivalente_bs + pago.ajuste_redondeo_bs
        if dinero(equivalente_total) != total_bs:
            raise ValueError('Los pagos no coinciden con el total del documento.')
        if all(p.moneda == 'USD' for p in pagos):
            esperado = dinero(total_usd_objetivo) if total_usd_objetivo is not None else total_en_usd(total_bs, tasa)
            if dinero(suma_usd) != esperado:
                raise ValueError('Los pagos en dólares no coinciden con el total.')
        elif dinero(dinero(suma_usd * tasa) + suma_bs) != total_bs:
            raise ValueError('Los pagos no coinciden con el total en bolívares.')
