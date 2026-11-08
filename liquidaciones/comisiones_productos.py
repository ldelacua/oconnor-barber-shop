"""Prepara la comisión de productos y los reintegros pendientes de un prestador."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import Q
from ventas.calculos import dinero
from ventas_productos.models import DocumentoProducto, EscalaComisionProducto
from ventas_productos.comisiones import calcular_comision_periodo
from .models import PeriodoComisionProductos, ComisionVentaProducto


def reintegros_pendientes(prestador, fecha_cancelacion):
    return list(ComisionVentaProducto.objects.filter(
        periodo__prestador=prestador, periodo__liquidacion__sellado=True,
        venta__reverso__sellado=True, venta__reverso__fecha__lte=fecha_cancelacion,
        reintegro__isnull=True).select_related('venta__reverso', 'periodo').order_by('pk'))


def pendientes_productos(prestador, desde, hasta, fecha_cancelacion):
    if desde > hasta or hasta > fecha_cancelacion:
        raise ValidationError('Revisa el período y la fecha de cancelación.')
    ventas = list(DocumentoProducto.objects.filter(prestador=prestador, tipo='VP', sellado=True,
        fecha__range=(desde, hasta), comision_productos__isnull=True).filter(
            Q(reverso__isnull=True) | Q(reverso__sellado=False) | Q(reverso__fecha__gt=fecha_cancelacion)
        ).prefetch_related('detalles').order_by('fecha', 'pk'))
    ventas = [(v, *v.importes_comision()) for v in ventas]
    ventas = [(v, unidades, base) for v, unidades, base in ventas if unidades > 0]
    # Solo se cierra un nuevo período si hay ventas pendientes de productos.
    # Consultar servicios con la casilla marcada no debe reabrir lo ya liquidado.
    if ventas and PeriodoComisionProductos.objects.filter(prestador=prestador, liquidacion__sellado=True,
            desde__lte=hasta, hasta__gte=desde).exists():
        raise ValidationError('Hay productos pendientes, pero el período incluye fechas de productos ya liquidadas. Selecciona el período pendiente de productos.')
    escalas = list(EscalaComisionProducto.objects.filter(activo=True).values('unidades', 'porcentaje')) if ventas else []
    resumen = calcular_comision_periodo(
        [{'unidades': unidades, 'base_usd': base} for _, unidades, base in ventas], escalas)
    acumulado = Decimal('0.00')
    comision_acumulada = Decimal('0.00')
    lineas = []
    for venta, unidades, base in ventas:
        acumulado += base
        nueva_comision = dinero(acumulado * resumen['porcentaje'] / Decimal('100'))
        lineas.append({'venta': venta, 'unidades': unidades, 'base_usd': base,
                       'comision_usd': nueva_comision - comision_acumulada})
        comision_acumulada = nueva_comision
    reintegros = reintegros_pendientes(prestador, fecha_cancelacion)
    return {'resumen': resumen, 'ventas': lineas, 'reintegros': reintegros,
            'total_reintegros_usd': -sum((r.comision_usd for r in reintegros), Decimal('0.00'))}
