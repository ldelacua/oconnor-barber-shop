from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import Compra, MovimientoInventario
from ventas.calculos import dinero

@transaction.atomic
def actualizar_compra(pk, usuario, revision):
    compra = Compra.objects.select_for_update().get(pk=pk)
    if compra.estado == Compra.ACTUALIZADA:
        return False
    if compra.revision != revision:
        raise ValidationError("La compra cambió mientras la consultabas. Recarga la pantalla.")
    # Adquiere la escritura y comprueba la versión antes de insertar movimientos.
    if Compra.objects.filter(pk=pk, estado=Compra.BORRADOR, revision=revision).update(revision=revision + 1) != 1:
        raise ValidationError("Otro usuario modificó la compra. Recarga la pantalla.")
    from django.apps import apps
    if apps.is_installed("control_inventario"):
        from control_inventario.servicios import validar_fecha
        validar_fecha(compra.fecha_compra)
    detalles = list(compra.detalles.select_related("producto"))
    if not detalles:
        raise ValidationError("La compra necesita al menos un producto.")
    compra.full_clean()
    if not compra.proveedor.activo:
        raise ValidationError("El proveedor está inactivo.")
    for detalle in detalles:
        detalle.full_clean()
        if detalle.cantidad!=dinero(detalle.cantidad) or detalle.precio_unitario!=dinero(detalle.precio_unitario):
            raise ValidationError("Edita el borrador y guarda cantidades y precios con un máximo de 2 decimales antes de actualizar.")
        if not detalle.producto.activo:
            raise ValidationError(f"El producto {detalle.producto} está inactivo.")
        costo = detalle.precio_unitario
        if compra.divisa == "BS":
            costo /= compra.tasa_cambio
        costo = costo.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if costo >= Decimal("10000000000000000"):
            raise ValidationError("El costo convertido excede el límite permitido. Revisa la tasa de cambio.")
        MovimientoInventario.objects.create(detalle=detalle, cantidad=detalle.cantidad, costo_unitario_usd=costo)
    Compra.objects.filter(pk=pk, estado=Compra.BORRADOR).update(
        estado=Compra.ACTUALIZADA, actualizada_en=timezone.now(), actualizada_por=usuario)
    return True

@transaction.atomic
def guardar_borrador(formulario, detalles, usuario):
    compra = formulario.instance
    from django.apps import apps
    if apps.is_installed("control_inventario"):
        from control_inventario.servicios import validar_fecha
        validar_fecha(compra.fecha_compra)
    if compra.pk:
        version = formulario.cleaned_data["version"]
        if Compra.objects.filter(pk=compra.pk, estado=Compra.BORRADOR, revision=version).update(revision=version + 1) != 1:
            raise ValidationError("La compra cambió o ya fue actualizada. Recarga antes de editar.")
        compra.revision = version + 1
    else:
        compra.registrada_por = usuario
    compra = formulario.save()
    detalles.instance = compra
    detalles.save()
    # También guarda el IVA automático cuando una fila existente no cambió.
    for fila in detalles.forms:
        if fila.cleaned_data and not fila.cleaned_data.get("DELETE") and fila.instance.pk:
            fila.instance.save()
    return compra

@transaction.atomic
def eliminar_borrador(pk, revision):
    compra = Compra.objects.select_for_update().get(pk=pk)
    if Compra.objects.filter(pk=pk, estado=Compra.BORRADOR, revision=revision).update(revision=revision + 1) != 1:
        raise ValidationError("La compra cambió o está actualizada. No se puede eliminar.")
    compra.delete()
