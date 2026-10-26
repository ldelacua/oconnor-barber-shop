from decimal import Decimal, localcontext
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from clientes.models import Cliente
from inventario.models import Producto
from inventario.condiciones import tasa_para_fecha, iva_vigente
from inventario.existencias import existencia_producto
from inventario.precision import disponible_visible
from ventas.calculos import dinero
from ventas.pagos_calculos import preparar_pagos, leer_tipos_pago
from .models import DocumentoProducto, LineaProducto, PagoProducto
from .precios import precio_producto,descuento_para

def decimal_valido(valor, decimales, limite, nombre):
    try:
        numero = Decimal(str(valor))
        if not numero.is_finite() or numero <= 0 or numero >= limite or numero != numero.quantize(Decimal(1).scaleb(-decimales)):
            raise ValueError()
        return numero
    except (ValueError, ArithmeticError):
        raise ValidationError(f"{nombre}: introduce un valor positivo con hasta {decimales} decimales.")

def sellar(doc):
    if DocumentoProducto.objects.filter(pk=doc.pk, sellado=False).update(sellado=True) != 1:
        raise ValidationError("No se pudo registrar el documento.")
    doc.sellado=True

@transaction.atomic
def registrar_venta(*, fecha, cliente, lineas, pagos, clave, usuario, observacion=""):
    existente = DocumentoProducto.objects.filter(clave=clave, sellado=True).first()
    if existente: return existente
    # La primera escritura serializa las operaciones en SQLite antes de consultar stock.
    doc = DocumentoProducto.objects.create(tipo="VP", fecha=fecha, cliente_id=cliente.pk,
        descripcion_cliente="", observacion=observacion.upper(), tasa_bcv=1, iva=0,
        subtotal_usd=0, subtotal_bs=0, impuesto_bs=0, total_bs=0,
        clave=clave, registrado_por=usuario.get_username())
    try:
        cliente = Cliente.objects.get(pk=cliente.pk, activo=True)
    except Cliente.DoesNotExist:
        raise ValidationError("El cliente no está activo.")
    from django.apps import apps
    if apps.is_installed("control_inventario"):
        from control_inventario.servicios import validar_fecha
        validar_fecha(fecha)
    tasa, iva = tasa_para_fecha(fecha), iva_vigente()
    preparadas, vistos = [], set()
    if not lineas or len(lineas) > 50: raise ValidationError("Registra entre 1 y 50 productos.")
    for fila in lineas:
        try:
            producto = Producto.objects.select_for_update().select_related("unidad_medida").get(pk=fila["producto"].pk, activo=True)
        except Producto.DoesNotExist:
            raise ValidationError("Un producto ya no está activo.")
        if producto.pk in vistos: raise ValidationError("Cada producto debe aparecer una sola vez. Suma las cantidades.")
        vistos.add(producto.pk)
        cantidad = decimal_valido(fila["cantidad"],2,Decimal("100000000000"),"Cantidad")
        calculado=precio_producto(producto,fecha)
        precio=calculado["precio_unitario_usd"]
        disponible = existencia_producto(producto.pk)
        if cantidad > disponible:
            raise ValidationError(f"Existencias insuficientes para {producto.codigo_producto} · {producto.nombre_producto}. "
                                  f"Disponible: {disponible_visible(disponible):,.2f}. Cantidad solicitada: {cantidad:,.2f}.",
                                  code="stock_insuficiente",params={"producto_id":producto.pk})
        with localcontext() as contexto:
            contexto.prec=60
            subtotal_usd=dinero(cantidad*precio)
            subtotal_bs=dinero(subtotal_usd*tasa)
            impuesto_bs=dinero(subtotal_bs*iva/Decimal("100"))
        if subtotal_usd <= 0:
            raise ValidationError(f"El importe de {producto.codigo_producto} debe ser al menos USD 0.01.")
        preparadas.append(dict(producto=producto, codigo=producto.codigo_producto,
            descripcion=str(producto), cantidad=cantidad, **calculado,
            subtotal_usd=subtotal_usd, subtotal_bs=subtotal_bs, impuesto_bs=impuesto_bs))
    unidades=sum((p["cantidad"] for p in preparadas),Decimal("0.00"))
    regla_descuento=descuento_para(unidades)
    porcentaje_descuento=regla_descuento.porcentaje if regla_descuento else Decimal("0.00")
    for p in preparadas:
        with localcontext() as contexto:
            contexto.prec=60
            rebaja=dinero(p["subtotal_usd"]*porcentaje_descuento/Decimal("100"))
            neto_bs=dinero((p["subtotal_usd"]-rebaja)*tasa)
            p["descuento_usd"]=rebaja
            p["descuento_bs"]=p["subtotal_bs"]-neto_bs
            p["impuesto_bs"]=dinero(neto_bs*iva/Decimal("100"))
    totales = {campo:sum((p[campo] for p in preparadas),Decimal("0.00"))
               for campo in ("subtotal_usd","subtotal_bs","impuesto_bs","descuento_usd","descuento_bs")}
    total=totales["subtotal_bs"]-totales["descuento_bs"]+totales["impuesto_bs"]
    if total < 0 or any(abs(v)>=Decimal("10000000000000000") for p in preparadas for v in
        (p["subtotal_usd"],p["subtotal_bs"],p["impuesto_bs"])) or any(abs(v)>=Decimal("10000000000000000") for v in [*totales.values(),total]):
        raise ValidationError("El importe de la venta está fuera del límite permitido.")
    try:
        if total==0:
            if pagos: raise ValueError("El total es cero. Quita los pagos de esta factura.")
            preparados=[]
        else:
            preparados=preparar_pagos(pagos,total,tasa,leer_tipos_pago())
    except (ValueError,KeyError,TypeError,OSError,ArithmeticError) as exc:
        raise ValidationError(str(exc)) from exc
    DocumentoProducto.objects.filter(pk=doc.pk,sellado=False).update(
        descripcion_cliente=str(cliente).upper(), tasa_bcv=tasa, iva=iva,total_bs=total,
        descuento_porcentaje=porcentaje_descuento,unidades_total=unidades,
        descuento_nivel=regla_descuento.nivel if regla_descuento else None,
        umbral_descuento=regla_descuento.unidades_mayor_que if regla_descuento else None,
        precio_automatico=True,**totales)
    for datos in preparadas: LineaProducto.objects.create(documento=doc,**datos)
    for datos in preparados:
        datos["nombre_tipo_pago"]=datos["nombre_tipo_pago"].upper()
        datos["referencia"]=datos["referencia"].upper()
        datos["observacion"]=datos["observacion"].upper()
        PagoProducto.objects.create(documento=doc,**datos)
    sellar(doc)
    return DocumentoProducto.objects.get(pk=doc.pk)

@transaction.atomic
def registrar_reverso(*, documento_id, motivo, usuario):
    original=DocumentoProducto.objects.select_for_update().get(pk=documento_id,sellado=True)
    if original.tipo != "VP": raise ValidationError("Solo se reversan ventas de productos.")
    if DocumentoProducto.objects.filter(documento_original=original).exists():
        raise ValidationError("La venta ya tiene un reverso.")
    motivo=motivo.strip().upper()
    if not motivo or len(motivo)>1000: raise ValidationError("Indica un motivo de hasta 1000 caracteres.")
    doc=DocumentoProducto.objects.create(tipo="RP",fecha=timezone.localdate(),cliente_id=original.cliente_id,
        descripcion_cliente=original.descripcion_cliente, observacion="",tasa_bcv=original.tasa_bcv,iva=original.iva,
        subtotal_usd=-original.subtotal_usd,subtotal_bs=-original.subtotal_bs,impuesto_bs=-original.impuesto_bs,
        total_bs=-original.total_bs,documento_original=original,motivo=motivo,registrado_por=usuario.get_username(),
        descuento_porcentaje=original.descuento_porcentaje,descuento_usd=-original.descuento_usd,
        descuento_bs=-original.descuento_bs,unidades_total=original.unidades_total,
        descuento_nivel=original.descuento_nivel,umbral_descuento=original.umbral_descuento,
        precio_automatico=original.precio_automatico)
    from django.apps import apps
    if apps.is_installed("control_inventario"):
        from control_inventario.servicios import validar_fecha
        validar_fecha(doc.fecha)
    for l in original.detalles.all():
        LineaProducto.objects.create(documento=doc,producto_id=l.producto_id,descripcion=l.descripcion,codigo=l.codigo,
            cantidad=l.cantidad,precio_unitario_usd=l.precio_unitario_usd,
            subtotal_usd=-l.subtotal_usd,subtotal_bs=-l.subtotal_bs,impuesto_bs=-l.impuesto_bs,linea_original=l,
            costo_unitario_usd=l.costo_unitario_usd,porcentaje_venta=l.porcentaje_venta,
            descuento_usd=-l.descuento_usd,descuento_bs=-l.descuento_bs)
    for p in original.pagos.all():
        PagoProducto.objects.create(documento=doc,tipo_pago=p.tipo_pago,nombre_tipo_pago=p.nombre_tipo_pago,
            moneda=p.moneda,fecha=doc.fecha,referencia=p.referencia,observacion=p.observacion,monto=-p.monto,
            equivalente_bs=-p.equivalente_bs,ajuste_redondeo_bs=-p.ajuste_redondeo_bs,pago_original=p)
    sellar(doc)
    return doc
