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
from ventas.pagos_calculos import preparar_pagos, leer_tipos_pago, validar_pagos_guardados
from .models import DocumentoProducto, LineaProducto, PagoProducto
from .precios import precio_producto,descuento_para

def decimal_valido(valor, decimales, limite, nombre):
    try:
        numero = Decimal(str(valor))
        if not numero.is_finite() or numero <= 0 or numero >= limite or numero != numero.quantize(Decimal(1).scaleb(-decimales)):
            raise ValueError()
        return numero
    except (ValueError, ArithmeticError):
        if decimales == 0:
            raise ValidationError(f"{nombre}: introduce un número entero positivo.")
        raise ValidationError(f"{nombre}: introduce un valor positivo con hasta {decimales} decimales.")

def descuento_renglon(subtotal, precio, cantidad, porcentaje, promocion):
    if promocion and cantidad < 1:
        raise ValidationError("La promoción requiere al menos una unidad del producto.")
    base_pagada = dinero((cantidad - 1) * precio) if promocion else subtotal
    return subtotal - base_pagada + dinero(base_pagada * porcentaje / Decimal("100"))


def _validar_sello(doc):
    doc.refresh_from_db()
    lineas = list(doc.detalles.all())
    pagos = list(doc.pagos.all())
    if not lineas:
        raise ValidationError("La venta necesita productos.")
    cero = Decimal("0.00")
    for campo in ("subtotal_usd", "subtotal_bs", "impuesto_bs", "descuento_usd", "descuento_bs"):
        if getattr(doc, campo) != sum((getattr(linea, campo) for linea in lineas), cero):
            raise ValidationError("Los importes no coinciden con los productos.")
    if doc.total_bs != doc.subtotal_bs - doc.descuento_bs + doc.impuesto_bs:
        raise ValidationError("El total de la venta es incorrecto.")
    if doc.total_bs != sum((p.equivalente_bs + p.ajuste_redondeo_bs for p in pagos), cero):
        raise ValidationError("Los pagos no coinciden con el total de la venta.")
    if doc.total_bs == 0 and pagos:
        raise ValidationError("Una venta de total cero no admite pagos.")
    for pago in pagos:
        if pago.moneda not in ('USD', 'BS') or pago.tipo_pago <= 0 or not pago.nombre_tipo_pago:
            raise ValidationError("La forma de pago es inválida.")
        equivalente = dinero(pago.monto * doc.tasa_bcv) if pago.moneda == 'USD' else pago.monto
        if pago.equivalente_bs != equivalente:
            raise ValidationError("El equivalente del pago no coincide con la tasa.")
    if doc.tipo == "VP":
        if doc.prestador_id and not doc.prestador.activo:
            raise ValidationError('El prestador de servicio no está activo.')
        if (doc.documento_original_id is not None or doc.total_bs < 0 or not doc.precio_automatico
            or not Decimal('0') <= doc.descuento_porcentaje <= Decimal('100')
            or not Decimal('0') <= doc.descuento_usd <= doc.subtotal_usd
            or not Decimal('0') <= doc.descuento_bs <= doc.subtotal_bs):
            raise ValidationError("La venta o su descuento no son válidos.")
        if any(p.monto <= 0 or p.pago_original_id is not None for p in pagos):
            raise ValidationError("El pago de la venta es inválido.")
        try:
            validar_pagos_guardados(pagos, doc.total_bs, doc.tasa_bcv)
        except ValueError as error:
            raise ValidationError(str(error)) from error
        if doc.unidades_total != sum((l.cantidad for l in lineas), cero):
            raise ValidationError("Las unidades no coinciden con los productos.")
        for linea in lineas:
            if linea.cantidad > existencia_producto(linea.producto_id):
                raise ValidationError("Existencias insuficientes para " + linea.codigo)
            if (linea.costo_unitario_usd is None or linea.costo_unitario_usd <= 0
                or linea.porcentaje_venta is None or linea.porcentaje_venta < 0):
                raise ValidationError("La venta necesita un costo y porcentaje válidos.")
            if (linea.linea_original_id is not None or linea.cantidad <= 0
                or linea.subtotal_usd <= 0 or linea.subtotal_bs < 0 or linea.impuesto_bs < 0
                or not Decimal('0') <= linea.descuento_usd <= linea.subtotal_usd
                or not Decimal('0') <= linea.descuento_bs <= linea.subtotal_bs):
                raise ValidationError("El producto o su descuento no son válidos.")
            precio = dinero(linea.costo_unitario_usd * (Decimal('1') + linea.porcentaje_venta / Decimal('100')))
            subtotal = dinero(linea.cantidad * precio)
            subtotal_bs = dinero(subtotal * doc.tasa_bcv)
            porcentaje = Decimal("0") if linea.sin_comision else doc.descuento_porcentaje
            descuento_usd = descuento_renglon(subtotal, precio, linea.cantidad, porcentaje, linea.promocion)
            descuento_bs = subtotal_bs - dinero((subtotal - descuento_usd) * doc.tasa_bcv)
            impuesto_bs = dinero((subtotal_bs - descuento_bs) * doc.iva / Decimal('100'))
            esperados = (precio, subtotal, subtotal_bs, descuento_usd, descuento_bs, impuesto_bs)
            actuales = (linea.precio_unitario_usd, linea.subtotal_usd, linea.subtotal_bs,
                        linea.descuento_usd, linea.descuento_bs, linea.impuesto_bs)
            if actuales != esperados:
                raise ValidationError("El precio, descuento o impuesto del producto es incorrecto.")
    elif doc.tipo == "RP":
        original = doc.documento_original
        if not original or not original.sellado or original.tipo != "VP":
            raise ValidationError("El reverso necesita una venta original registrada.")
        if len(lineas) != original.detalles.count() or len(pagos) != original.pagos.count():
            raise ValidationError("El reverso debe contener todos los productos y pagos originales.")
        iguales = ('cliente_id', 'prestador_id', 'tasa_bcv', 'iva', 'descuento_porcentaje', 'unidades_total',
                   'descuento_nivel', 'umbral_descuento')
        negativos = ('subtotal_usd', 'subtotal_bs', 'impuesto_bs', 'total_bs', 'descuento_usd', 'descuento_bs')
        if (not doc.motivo.strip() or any(getattr(doc,c) != getattr(original,c) for c in iguales)
            or any(getattr(doc,c) != -getattr(original,c) for c in negativos)):
            raise ValidationError("El reverso no coincide con la venta original.")
        for linea in lineas:
            anterior = linea.linea_original
            iguales_linea = ('producto_id', 'cantidad', 'precio_unitario_usd', 'costo_unitario_usd', 'porcentaje_venta', 'promocion', 'sin_comision')
            negativos_linea = ('subtotal_usd', 'subtotal_bs', 'impuesto_bs', 'descuento_usd', 'descuento_bs')
            if (not anterior or anterior.documento_id != original.pk
                or any(getattr(linea,c) != getattr(anterior,c) for c in iguales_linea)
                or any(getattr(linea,c) != -getattr(anterior,c) for c in negativos_linea)):
                raise ValidationError("Los productos del reverso no coinciden con la venta original.")
        for pago in pagos:
            anterior = pago.pago_original
            if (not anterior or anterior.documento_id != original.pk
                or any(getattr(pago,c) != getattr(anterior,c) for c in ('tipo_pago','moneda'))
                or any(getattr(pago,c) != -getattr(anterior,c) for c in ('monto','equivalente_bs','ajuste_redondeo_bs'))):
                raise ValidationError("Los pagos del reverso no coinciden con la venta original.")
    else:
        raise ValidationError("Tipo de documento inválido.")


def sellar(doc):
    _validar_sello(doc)
    if DocumentoProducto.objects.filter(pk=doc.pk, sellado=False).update(sellado=True) != 1:
        raise ValidationError("No se pudo registrar el documento.")
    doc.sellado=True

def puede_dar_promocion(usuario):
    return bool(usuario and (usuario.is_superuser or usuario.groups.filter(name__iexact="ENCARGADO").exists()))


def calcular_productos(fecha, lineas, *, bloquear=False, usuario=None):
    tasa, iva = tasa_para_fecha(fecha), iva_vigente()
    consulta = Producto.objects.select_related("unidad_medida")
    if bloquear:
        consulta = consulta.select_for_update()
    preparadas, vistos = [], set()
    if not lineas or len(lineas) > 50: raise ValidationError("Registra entre 1 y 50 productos.")
    for fila in lineas:
        try:
            producto = consulta.get(pk=fila["producto"].pk, activo=True)
        except Producto.DoesNotExist:
            raise ValidationError("Un producto ya no está activo.")
        if producto.pk in vistos: raise ValidationError("Cada producto debe aparecer una sola vez. Suma las cantidades.")
        vistos.add(producto.pk)
        promocion = bool(fila.get("promocion"))
        if promocion and not puede_dar_promocion(usuario):
            raise ValidationError("Solo el encargado o un superusuario puede aplicar promociones de productos.")
        if promocion and not producto.promocionable:
            raise ValidationError(f"{producto.codigo_producto} no está marcado como promocionable.")
        cantidad = decimal_valido(fila["cantidad"],0,Decimal("100000000000"),"Cantidad")
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
            descripcion=str(producto), cantidad=cantidad, promocion=promocion, sin_comision=producto.sin_comision, **calculado,
            subtotal_usd=subtotal_usd, subtotal_bs=subtotal_bs, impuesto_bs=impuesto_bs))
    unidades=sum((p["cantidad"] for p in preparadas),Decimal("0.00"))
    unidades_elegibles = sum((p["cantidad"] for p in preparadas if not p["sin_comision"]), Decimal("0"))
    regla_descuento = descuento_para(unidades_elegibles) if unidades_elegibles else None
    porcentaje_descuento=regla_descuento.porcentaje if regla_descuento else Decimal("0.00")
    for p in preparadas:
        with localcontext() as contexto:
            contexto.prec=60
            porcentaje = Decimal("0") if p["sin_comision"] else porcentaje_descuento
            rebaja = descuento_renglon(p["subtotal_usd"], p["precio_unitario_usd"], p["cantidad"], porcentaje, p["promocion"])
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
    return tasa, iva, preparadas, unidades, regla_descuento, porcentaje_descuento, totales, total


@transaction.atomic
def registrar_venta(*, fecha, cliente, lineas, pagos, clave, usuario, observacion="", prestador=None, _asignar_pago=None):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    existente = DocumentoProducto.objects.filter(clave=clave, sellado=True).first()
    if existente: return existente
    # La primera escritura serializa las operaciones en SQLite antes de consultar stock.
    if prestador is not None:
        from barberos.models import Barbero
        if not Barbero.objects.filter(pk=prestador.pk, activo=True).exists():
            raise ValidationError("El prestador de servicio no está activo.")
        from liquidaciones.models import PeriodoComisionProductos
        if PeriodoComisionProductos.objects.filter(prestador=prestador, liquidacion__sellado=True,
                                                     desde__lte=fecha, hasta__gte=fecha).exists():
            raise ValidationError("El período de comisiones del prestador ya está liquidado para esta fecha.")
    doc = DocumentoProducto.objects.create(tipo="VP", fecha=fecha, cliente_id=cliente.pk, prestador=prestador,
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
    tasa, iva, preparadas, unidades, regla_descuento, porcentaje_descuento, totales, total = calcular_productos(fecha, lineas, bloquear=True, usuario=usuario)
    if _asignar_pago is not None:
        pagos = _asignar_pago(total, tasa)
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
    creados = []
    for datos in preparados:
        datos["nombre_tipo_pago"]=datos["nombre_tipo_pago"].upper()
        datos["referencia"]=datos["referencia"].upper()
        datos["observacion"]=datos["observacion"].upper()
        creados.append(PagoProducto.objects.create(documento=doc,**datos))
    sellar(doc)
    from bancos.vinculacion import vincular_pagos_nuevos
    vincular_pagos_nuevos(usuario, 'PRODUCTOS', pagos, creados)
    return DocumentoProducto.objects.get(pk=doc.pk)

@transaction.atomic
def registrar_reverso(*, documento_id, motivo, usuario):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    original=DocumentoProducto.objects.select_for_update().get(pk=documento_id,sellado=True)
    if original.tipo != "VP": raise ValidationError("Solo se reversan ventas de productos.")
    if DocumentoProducto.objects.filter(documento_original=original).exists():
        raise ValidationError("La venta ya tiene un reverso.")
    motivo=motivo.strip().upper()
    if not motivo or len(motivo)>1000: raise ValidationError("Indica un motivo de hasta 1000 caracteres.")
    doc=DocumentoProducto.objects.create(tipo="RP",fecha=timezone.localdate(),cliente_id=original.cliente_id,prestador_id=original.prestador_id,
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
            cantidad=l.cantidad,precio_unitario_usd=l.precio_unitario_usd,promocion=l.promocion,sin_comision=l.sin_comision,
            subtotal_usd=-l.subtotal_usd,subtotal_bs=-l.subtotal_bs,impuesto_bs=-l.impuesto_bs,linea_original=l,
            costo_unitario_usd=l.costo_unitario_usd,porcentaje_venta=l.porcentaje_venta,
            descuento_usd=-l.descuento_usd,descuento_bs=-l.descuento_bs)
    for p in original.pagos.all():
        PagoProducto.objects.create(documento=doc,tipo_pago=p.tipo_pago,nombre_tipo_pago=p.nombre_tipo_pago,
            moneda=p.moneda,fecha=doc.fecha,referencia=p.referencia,observacion=p.observacion,monto=-p.monto,
            equivalente_bs=-p.equivalente_bs,ajuste_redondeo_bs=-p.ajuste_redondeo_bs,pago_original=p)
    sellar(doc)
    from bancos.vinculacion import reflejar_reversos_venta
    reflejar_reversos_venta('PRODUCTOS', doc.pagos.all())
    return doc
