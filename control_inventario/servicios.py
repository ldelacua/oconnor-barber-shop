from datetime import date
from decimal import Decimal
from django.db import transaction
from django.db.models import Max
from django.core.exceptions import ValidationError
from django.utils import timezone
from inventario.models import Producto
from inventario.existencias import existencia_producto
from .models import CierreMensual,DocumentoAjuste,DetalleAjuste,DetalleCierre
from .saldos import fin_mes,siguiente_mes,costo_producto,reporte_stock,unidad
from ventas.calculos import dinero

def validar_fecha(fecha,cierre_id=None):
    ultimo=CierreMensual.objects.filter(estado="C").aggregate(p=Max("periodo"))["p"]
    if ultimo and fecha<=fin_mes(ultimo):
        raise ValidationError("El mes de esa fecha ya está cerrado. Usa una fecha de un mes abierto.")
    conteo=CierreMensual.objects.filter(estado="B").first()
    if conteo and fecha<=fin_mes(conteo.periodo) and cierre_id!=conteo.pk:
        raise ValidationError("Hay un conteo físico en curso. Finaliza o cancela el conteo antes de registrar movimientos en ese período.")

@transaction.atomic
def registrar_ajuste(*,tipo,fecha,observacion,lineas,usuario,clave,cierre=None,costos=None):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    existente=DocumentoAjuste.objects.filter(clave=clave,sellado=True).first()
    if existente:return existente
    if tipo not in ["EN","SA"]:raise ValidationError("Selecciona Entrada o Salida.")
    if not observacion.strip():raise ValidationError("Indica el motivo en Observación.")
    doc=DocumentoAjuste.objects.create(tipo=tipo,fecha=fecha,observacion=observacion.strip().upper(),
        clave=clave,registrado_por=usuario,cierre=cierre)
    validar_fecha(fecha,cierre.pk if cierre else None)
    if not lineas or len(lineas)>100:raise ValidationError("Registra entre 1 y 100 productos.")
    vistos=set()
    for fila in lineas:
        producto=Producto.objects.select_related("unidad_medida").get(pk=fila["producto"].pk)
        if producto.pk in vistos:raise ValidationError("Cada producto debe aparecer una sola vez.")
        vistos.add(producto.pk)
        try:
            cantidad=Decimal(str(fila["cantidad"]))
            if not cantidad.is_finite() or cantidad<=0 or cantidad>=Decimal("100000000000") or cantidad!=dinero(cantidad):raise ValueError()
        except (ValueError,ArithmeticError):
            raise ValidationError("La cantidad debe ser positiva, con hasta 2 decimales.")
        if tipo=="SA" and cantidad>existencia_producto(producto.pk):
            raise ValidationError(f"Existencias insuficientes para {producto.codigo_producto}. Corrige la cantidad.")
        costo,sin_previo=costo_producto(producto.pk,fecha)
        if costos is not None:
            costo=costos[producto.pk];sin_previo=costo==0
        DetalleAjuste.objects.create(documento=doc,producto=producto,descripcion=str(producto),
            cantidad=cantidad,costo_unitario_usd=costo,sin_costo_previo=sin_previo)
    DocumentoAjuste.objects.filter(pk=doc.pk,sellado=False).update(sellado=True)
    doc.sellado=True
    return doc

@transaction.atomic
def iniciar_cierre(*,periodo,observacion,usuario):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    if periodo.day!=1:raise ValidationError("Selecciona un mes válido.")
    if siguiente_mes(periodo)>timezone.localdate():
        raise ValidationError("Solo se pueden cerrar meses terminados.")
    existente=CierreMensual.objects.filter(periodo=periodo).first()
    if existente:return existente
    if CierreMensual.objects.filter(estado="B").exists():
        raise ValidationError("Ya existe un conteo en curso. Finalízalo o cancélalo.")
    ultimo=CierreMensual.objects.filter(estado="C").order_by("-periodo").first()
    if ultimo and periodo!=siguiente_mes(ultimo.periodo):
        raise ValidationError("Debes cerrar el mes inmediatamente siguiente al último cierre.")
    cierre=CierreMensual.objects.create(periodo=periodo,observacion=observacion.upper(),iniciado_por=usuario)
    filas=[]
    for p in reporte_stock(periodo).iterator():
        filas.append(DetalleCierre(cierre=cierre,producto=p,codigo=p.codigo_producto,descripcion=str(p),
            inicial=unidad(p.inicial),compras=unidad(p.compras),ventas=unidad(p.ventas),
            otros=unidad(p.otros),teorico=unidad(p.disponible),costo_unitario_usd=dinero(p.costo)))
    if not filas:raise ValidationError("No hay productos registrados para contar.")
    DetalleCierre.objects.bulk_create(filas,batch_size=100)
    return cierre

@transaction.atomic
def guardar_conteo(*,cierre_id,revision,filas,ids_pagina):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    if CierreMensual.objects.filter(pk=cierre_id,estado="B",revision=revision).update(revision=revision+1)!=1:
        raise ValidationError("El conteo cambió. Recarga antes de guardar.")
    if {f["renglon"] for f in filas}!=set(ids_pagina) or len(filas)!=len(ids_pagina):
        raise ValidationError("El conteo no coincide con los productos de esta página.")
    for fila in filas:
        valor=fila["fisico"]
        if valor<0 or valor!=dinero(valor) or valor>=Decimal("100000000000"):raise ValidationError("Conteo físico inválido.")
        DetalleCierre.objects.filter(pk=fila["renglon"],cierre_id=cierre_id).update(fisico=valor)

@transaction.atomic
def confirmar_cierre(*,cierre_id,revision,usuario):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    cierre=CierreMensual.objects.get(pk=cierre_id)
    if cierre.estado=="C":return cierre
    if CierreMensual.objects.filter(pk=cierre_id,estado="B",revision=revision).update(revision=revision+1)!=1:
        raise ValidationError("El conteo cambió. Recarga antes de cerrar.")
    detalles=list(cierre.detalles.select_related("producto"))
    if any(d.fisico is None for d in detalles):
        raise ValidationError("Debes registrar el físico de todos los productos, incluyendo los que tienen cero.")
    if any(d.fisico!=dinero(d.fisico) for d in detalles):
        raise ValidationError("Revisa y guarda el físico de este conteo con un máximo de 2 decimales antes de cerrar.")
    import uuid
    for tipo,signo in [("EN",1),("SA",-1)]:
        elegidos=[d for d in detalles if d.diferencia*signo>0]
        # Los cierres pueden abarcar más de 100 productos; son un solo documento automático.
        if elegidos:
            doc=DocumentoAjuste.objects.create(tipo=tipo,fecha=fin_mes(cierre.periodo),
                observacion=f"AJUSTE AUTOMÁTICO DEL CIERRE {cierre.periodo:%Y-%m}",cierre=cierre,
                registrado_por=usuario,clave=uuid.uuid5(uuid.NAMESPACE_URL,f"cierre-inventario:{cierre.pk}:{tipo}"))
            for d in elegidos:
                cantidad=abs(d.diferencia)
                if cantidad>=Decimal("100000000000"):
                    raise ValidationError("Una diferencia excede el máximo por producto.")
                if tipo=="SA" and cantidad>existencia_producto(d.producto_id):
                    raise ValidationError(f"El ajuste de {d.codigo} dejaría stock actual negativo. Revisa los movimientos posteriores.")
                DetalleAjuste.objects.create(documento=doc,producto=d.producto,descripcion=d.descripcion,
                    cantidad=cantidad,costo_unitario_usd=d.costo_unitario_usd,sin_costo_previo=d.costo_unitario_usd==0)
            DocumentoAjuste.objects.filter(pk=doc.pk,sellado=False).update(sellado=True)
    CierreMensual.objects.filter(pk=cierre.pk,estado="B").update(estado="C",
        cerrado_por=usuario,cerrado_en=timezone.now())
    return CierreMensual.objects.get(pk=cierre.pk)

@transaction.atomic
def cancelar_conteo(*,cierre_id,revision):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    if CierreMensual.objects.filter(pk=cierre_id,estado="B",revision=revision).update(revision=revision+1)!=1:
        raise ValidationError("El conteo cambió o ya está cerrado.")
    CierreMensual.objects.get(pk=cierre_id).delete()
