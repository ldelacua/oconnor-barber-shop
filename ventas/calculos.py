import json
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path

CENTIMO = Decimal("0.01")


def dinero(valor):
    with localcontext() as contexto:
        contexto.prec = 60
        return Decimal(str(valor)).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def leer_impuesto():
    ruta = Path(__file__).resolve().parent / "config" / "impuesto.json"
    valor = Decimal(str(json.loads(ruta.read_text(encoding="utf-8"))["porcentaje"]))
    if not valor.is_finite() or not Decimal("0") <= valor <= Decimal("100") or valor != dinero(valor):
        raise ValueError("El impuesto debe estar entre 0 y 100, con hasta dos decimales.")
    return valor


def calcular_linea(precio, cantidad, tasa, porcentaje):
    with localcontext() as contexto:
        contexto.prec = 60
        usd = dinero(Decimal(str(precio)) * cantidad)
        bs = dinero(usd * Decimal(str(tasa)))
        impuesto = dinero(bs * Decimal(str(porcentaje)) / Decimal("100"))
    return {"monto_servicio": usd, "monto_servicio_bs": bs, "monto_impuesto": impuesto}



def calcular_linea_descuento(precio, cantidad, tasa, impuesto, descuento=Decimal("0.00")):
    with localcontext() as contexto:
        contexto.prec = 60
        bruto = dinero(Decimal(str(precio)) * cantidad)
        rebaja = dinero(bruto * descuento / Decimal("100"))
        neto = bruto - rebaja
        bruto_bs = dinero(bruto * tasa)
        neto_bs = dinero(neto * tasa)
        return {
            "monto_servicio": bruto, "monto_servicio_bs": bruto_bs,
            "monto_descuento_usd": rebaja, "monto_descuento_bs": bruto_bs - neto_bs,
            "monto_impuesto": dinero(neto_bs * impuesto / Decimal("100")),
        }


def calcular_linea_iva_incluido(precio, cantidad, tasa, impuesto, descuento=Decimal("0.00")):
    """Conserva el precio original para comisiones; extrae el IVA del cobro neto."""
    with localcontext() as contexto:
        contexto.prec = 60
        bruto = dinero(Decimal(str(precio)) * cantidad)
        rebaja = dinero(bruto * descuento / Decimal("100"))
        neto = bruto - rebaja
        bruto_bs = dinero(bruto * tasa)
        neto_bs = dinero(neto * tasa)
        divisor = Decimal("1") + impuesto / Decimal("100")
        base_usd = dinero(neto / divisor)
        base_bs = dinero(neto_bs / divisor)
        return {
            "monto_servicio": bruto, "monto_servicio_bs": bruto_bs,
            "monto_descuento_usd": rebaja, "monto_descuento_bs": bruto_bs - neto_bs,
            "base_imponible_usd": base_usd, "base_imponible_bs": base_bs,
            "monto_impuesto": neto_bs - base_bs,
        }


def calcular_linea_segun_retencion(precio, cantidad, tasa, impuesto, descuento, retencion):
    if retencion:
        return calcular_linea_iva_incluido(precio, cantidad, tasa, impuesto, descuento)
    valores = calcular_linea_descuento(precio, cantidad, tasa, impuesto, descuento)
    valores["base_imponible_usd"] = valores["monto_servicio"] - valores["monto_descuento_usd"]
    valores["base_imponible_bs"] = valores["monto_servicio_bs"] - valores["monto_descuento_bs"]
    return valores
