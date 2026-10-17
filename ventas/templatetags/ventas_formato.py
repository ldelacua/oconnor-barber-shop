from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from django import template

register = template.Library()


@register.filter
def monto_venta(valor):
    """Formato fijo: 1,234.56, independiente del idioma del navegador."""
    try:
        with localcontext() as contexto:
            contexto.prec = 60
            numero = Decimal(str(valor))
            if not numero.is_finite():
                return "—"
            numero = numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return f"{numero:,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "—"


@register.filter
def porcentaje_venta(valor):
    try:
        numero = Decimal(str(valor))
        return format(numero, "f").rstrip("0").rstrip(".") if "." in format(numero, "f") else format(numero, "f")
    except (InvalidOperation, TypeError, ValueError):
        return ""


@register.filter
def nombre_prestador(valor):
    """Oculta el código de la descripción antigua sin modificar el registro."""
    texto = str(valor or "")
    codigo, separador, nombre = texto.partition(" - ")
    return nombre if separador else texto
