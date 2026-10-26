from decimal import Decimal
from django.core.exceptions import ValidationError
from tasas_bcv.models import TasaBCV
from ventas.calculos import leer_impuesto

def iva_vigente():
    try:
        return leer_impuesto()
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        raise ValidationError("No se pudo leer el IVA de ventas/config/impuesto.json. Revisa su configuración.") from exc

def tasa_para_fecha(fecha):
    registro = TasaBCV.objects.filter(fecha=fecha).first()
    if not registro:
        raise ValidationError("No hay tasa BCV para la fecha de compra. Regístrala en Tasas BCV.")
    tasa = registro.tasa_bcv
    if not tasa.is_finite() or tasa <= Decimal("0"):
        raise ValidationError("La tasa BCV registrada no es válida.")
    return tasa
