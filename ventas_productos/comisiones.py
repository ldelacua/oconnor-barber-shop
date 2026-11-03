"""Cálculos puros de comisión de productos por período.

No modifica ventas ni liquidaciones. Las reglas activas se consultan por el
servicio que cierra el período y se conservan junto con el resultado liquidado.
"""
from decimal import Decimal, InvalidOperation, localcontext
from django.core.exceptions import ValidationError
from ventas.calculos import dinero


def calcular_comision_periodo(ventas, escalas):
    """Recibe importes netos sin IVA y unidades de ventas no reversadas."""
    unidades = Decimal('0')
    base = Decimal('0')
    try:
        for venta in ventas:
            cantidad = Decimal(str(venta['unidades']))
            importe = Decimal(str(venta['base_usd']))
            if not cantidad.is_finite() or not importe.is_finite() or cantidad <= 0 or importe < 0:
                raise ValueError
            unidades += cantidad
            base += importe
        disponibles = []
        for escala in escalas:
            minimo = Decimal(str(escala['unidades']))
            porcentaje = Decimal(str(escala['porcentaje']))
            if not minimo.is_finite() or not porcentaje.is_finite() or minimo < 0 or not 0 <= porcentaje <= 100:
                raise ValueError
            if minimo <= unidades:
                disponibles.append((minimo, porcentaje))
        if len({x[0] for x in disponibles}) != len(disponibles):
            raise ValidationError('Hay escalas de comisión con el mismo mínimo de unidades.')
        if unidades and not disponibles:
            raise ValidationError('No hay una escala de comisión aplicable a las unidades del período.')
        minimo, porcentaje = max(disponibles, default=(Decimal('0'), Decimal('0')))
        with localcontext() as contexto:
            contexto.prec = 60
            total = dinero(base * porcentaje / Decimal('100'))
        return {'unidades': unidades, 'base_usd': dinero(base), 'porcentaje': porcentaje,
                'minimo_unidades': minimo, 'comision_usd': total}
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError) as error:
        raise ValidationError('Las unidades, importes o escalas de comisión no son válidos.') from error
