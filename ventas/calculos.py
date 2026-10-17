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
