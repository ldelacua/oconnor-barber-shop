"""Distribución de un cobro real entre facturas sin crear cobros bancarios ficticios."""
from decimal import Decimal

from django.core.exceptions import ValidationError

from .calculos import dinero
from .pagos_calculos import preparar_pagos, total_en_usd


def distribuir_pago_unico(pago, total_servicios_bs, total_productos_bs, tasa, catalogo):
    """Retorna las asignaciones contables; la fila original sigue siendo el único cobro.

    Cada factura conserva su total y sus reglas de redondeo. Cuando la suma de
    los equivalentes individuales difiere por un centavo del cobro en USD,
    no se inventa un faltante ni un excedente: se pide cobrar en bolívares.
    """
    totales = (total_servicios_bs, total_productos_bs)
    if any(total < 0 for total in totales) or not any(totales):
        raise ValidationError("La venta combinada debe tener un total positivo.")
    try:
        tipo = catalogo[int(pago["tipo_pago"])]
        preparar_pagos([pago], sum(totales), tasa, catalogo)
    except (KeyError, ValueError, TypeError, ArithmeticError) as error:
        raise ValidationError(str(error)) from error

    importe = Decimal(str(pago["monto"]))
    montos = (tuple(total_en_usd(total, tasa) for total in totales)
              if tipo["moneda"] == "USD" else tuple(dinero(total) for total in totales))
    if sum(montos) != importe or any(total > 0 and monto == 0 for total, monto in zip(totales, montos)):
        raise ValidationError(
            "No se puede repartir este cobro en USD sin alterar el redondeo de las facturas. "
            "Selecciona una forma de pago en bolívares."
        )
    return tuple(
        [{**pago, "monto": monto, "cuenta_bancaria": None}] if monto else []
        for monto in montos
    )


def registrar_venta_combinada(*, fecha, cliente, servicios, productos, pago, clave, usuario,
                               prestador=None, **opciones_servicio):
    from uuid import UUID, uuid5

    from django.core.exceptions import PermissionDenied
    from django.db import transaction

    from bancos.models import CuentaBancaria, CierreBancario, MovimientoInterno
    from mysql_nuevo.bloqueos import serializar_operacion
    from ventas_productos.servicios import registrar_venta as registrar_productos

    from .models import CobroCompartido
    from .pagos_calculos import leer_tipos_pago
    from .servicios import registrar_venta as registrar_servicios

    if not usuario.has_perms(("ventas.add_documentoventa", "ventas_productos.add_documentoproducto")):
        raise PermissionDenied
    if opciones_servicio.get("codigo_regalo"):
        raise ValidationError("El canje de tarjetas de regalo no está habilitado en ventas combinadas.")
    clave = UUID(str(clave))
    with transaction.atomic():
        serializar_operacion()
        existente = CobroCompartido.objects.filter(clave=clave).first()
        if existente:
            return existente
        catalogo = leer_tipos_pago()
        tipo = catalogo.get(int(pago.get("tipo_pago") or 0))
        if not tipo:
            raise ValidationError("Selecciona una forma de pago válida.")
        cuenta = pago.get("cuenta_bancaria")
        if tipo["afecta_banco"] != bool(cuenta):
            raise ValidationError("Indica el banco y la cuenta únicamente para un pago bancario.")
        resultados = {}

        def asignar_servicios(total_servicios, tasa):
            def asignar_productos(total_productos, tasa_productos):
                if tasa != tasa_productos:
                    raise ValidationError("Ambas facturas deben usar la misma tasa.")
                partes = distribuir_pago_unico(pago, total_servicios, total_productos, tasa, catalogo)
                resultados["servicios"] = partes[0]
                resultados["pago"] = preparar_pagos([pago], total_servicios + total_productos, tasa, catalogo)[0]
                return partes[1]

            resultados["productos"] = registrar_productos(
                fecha=fecha, cliente=cliente, lineas=productos, pagos=[], clave=uuid5(clave, "productos"),
                usuario=usuario, prestador=prestador, _asignar_pago=asignar_productos)
            return resultados["servicios"]

        factura = registrar_servicios(fecha=fecha, cliente=cliente, lineas=servicios, pagos=[],
                                      clave=uuid5(clave, "servicios"), usuario=usuario,
                                      _asignar_pago=asignar_servicios, **opciones_servicio)
        if cuenta:
            if not usuario.has_perms(("bancos.view_cuentabancaria", "bancos.add_movimientointerno")):
                raise PermissionDenied
            cuenta = CuentaBancaria.objects.select_for_update().select_related("banco").get(pk=cuenta.pk)
            if not cuenta.activa or not cuenta.banco.activo or cuenta.moneda != tipo["moneda"]:
                raise ValidationError("Selecciona una cuenta activa en la moneda del cobro.")
            if CierreBancario.objects.filter(cuenta=cuenta, fecha_cierre__gte=resultados["pago"]["fecha"].replace(day=1)).exists():
                raise ValidationError("El mes está cerrado para la cuenta del cobro.")
        cobro = CobroCompartido.objects.create(clave=clave, servicios=factura,
                                             productos=resultados["productos"], cuenta=cuenta, **resultados["pago"])
        if cuenta:
            MovimientoInterno.objects.create(cuenta=cuenta, origen="COBRO_COMPARTIDO", pago_id=cobro.pk,
                                            fecha=cobro.fecha, referencia=cobro.referencia, monto=cobro.monto)
        return cobro
