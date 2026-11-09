from django.core.exceptions import PermissionDenied, ValidationError
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Sum, Q, F, DecimalField
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .models import GrupoGasto, TipoGasto, Proveedor, RegistroGasto
from .forms import GrupoForm, TipoForm, ProveedorForm, RegistroForm, FiltrosForm

from bancos.models import CierreBancario, CuentaBancaria, MovimientoInterno, PartidaInterna
from seguridad.models import Auditoria
from .models import Producto
from .forms import ProductoForm, DetalleGastoFormSet

CATALOGOS={
    "productos":(Producto,ProductoForm,"Productos"),
    "grupos":(GrupoGasto,GrupoForm,"Grupos de gastos"),
    "tipos":(TipoGasto,TipoForm,"Tipos de gasto"),
    "proveedores":(Proveedor,ProveedorForm,"Proveedores"),
}

def _catalogo(nombre):
    if nombre not in CATALOGOS:raise Http404
    return CATALOGOS[nombre]


@login_required
def inicio(request):
    filtros=FiltrosForm(request.GET)
    registros = (
    RegistroGasto.objects
    .select_related("gasto__grupo", "proveedor")
    .prefetch_related("detalles__producto")
    )
    if filtros.is_valid():
        d=filtros.cleaned_data
        if d.get("desde"):registros=registros.filter(fecha_gasto__gte=d["desde"])
        if d.get("hasta"):registros=registros.filter(fecha_gasto__lte=d["hasta"])
        if d.get("grupo"):registros=registros.filter(gasto__grupo=d["grupo"])
        if d.get("gasto"):registros=registros.filter(gasto=d["gasto"])
        if d.get("proveedor"):registros=registros.filter(proveedor=d["proveedor"])
        if d.get("moneda"):registros=registros.filter(moneda=d["moneda"])
        if d.get("factura"):registros=registros.filter(numero_factura__icontains=d["factura"])
    else:registros=registros.none()
    totales=registros.aggregate(
        usd=Sum(F("monto_gasto")+F("monto_impuesto"),filter=Q(moneda="USD"),output_field=DecimalField(max_digits=30,decimal_places=2)),
        bs=Sum(F("monto_gasto")+F("monto_impuesto"),filter=Q(moneda="BS"),output_field=DecimalField(max_digits=30,decimal_places=2)),
    )
    totales={k:v if v is not None else Decimal("0.00") for k,v in totales.items()}
    pagina=Paginator(registros,30).get_page(request.GET.get("page"))
    parametros=request.GET.copy();parametros.pop("page",None)
    return render(request,"gastos/inicio.html",{"pagina":pagina,"filtros":filtros,"totales":totales,"parametros":parametros.urlencode(),"seccion":"registros"})


def movimiento_gasto(pk):
    return MovimientoInterno.objects.filter(origen='GASTO_OPERATIVO', pago_id=pk)


def _validar_mes_abierto(cuenta_id, fecha):
    if CierreBancario.objects.filter(cuenta_id=cuenta_id, fecha_cierre__gte=fecha).exists():
        raise ValidationError("El gasto afecta un período bancario cerrado y no se puede modificar.")


def _validar_movimiento_editable(movimiento):
    if movimiento is None:
        return
    _validar_mes_abierto(movimiento.cuenta_id, movimiento.fecha)
    if PartidaInterna.objects.filter(movimiento=movimiento).exists():
        raise ValidationError("El gasto está conciliado. Revierte la conciliación en Bancos antes de editarlo o eliminarlo.")


def _bloquear_cuentas(*ids):
    return {cuenta.pk: cuenta for cuenta in CuentaBancaria.objects.select_for_update().filter(
        pk__in={pk for pk in ids if pk is not None},
    ).order_by("pk")}


def _registrar_auditoria(usuario, accion, gasto_id):
    Auditoria.objects.create(usuario=usuario, accion=f"{accion} gasto #{gasto_id}")


def _redirigir_si_bloqueado(request, movimiento, pk):
    try:
        _validar_movimiento_editable(movimiento)
    except ValidationError as error:
        messages.warning(request, error.messages[0])
        return redirect("gastos:ver", pk=pk)
    return None


@login_required
def formulario_registro(request,pk=None):
    if pk is not None and not request.user.is_superuser:
        raise PermissionDenied
    registro=get_object_or_404(RegistroGasto,pk=pk) if pk else RegistroGasto()
    datos=request.POST if request.method=="POST" else None
    movimiento = movimiento_gasto(pk).first() if pk else None
    if request.method == "GET":
        bloqueo = _redirigir_si_bloqueado(request, movimiento, pk)
        if bloqueo:
            return bloqueo
    detalles=DetalleGastoFormSet(datos,instance=registro,prefix="detalles")
    detalles_validos = detalles.is_valid() if datos is not None else False
    admite_total_historico = bool(pk and not registro.detalles.filter(precio_unitario__isnull=False).exists())
    datos_encabezado = datos
    if datos is not None:
        datos_encabezado = datos.copy()
        importes = detalles.totales if detalles_validos else None
        if detalles_validos and importes is None and not admite_total_historico:
            detalles_validos = False
        if importes is None:
            importes = (registro.monto_gasto, registro.monto_impuesto) if pk else (Decimal("0.01"), Decimal("0"))
        datos_encabezado["monto_gasto"], datos_encabezado["monto_impuesto"] = map(str, importes)
        datos_encabezado["porcentaje_impuesto"] = str(registro.porcentaje_impuesto if pk else 0)
    form=RegistroForm(datos_encabezado,instance=registro,usuario=request.user,registro_detallado=True)
    if movimiento and "cuenta_bancaria" in form.fields:
        form.initial["cuenta_bancaria"] = movimiento.cuenta_id
    if request.method=="POST":
        encabezado_valido=form.is_valid()
        if not detalles_validos and not any(detalles.errors) and not detalles.non_form_errors():
            form.add_error(None, "Agrega al menos un renglón con precio para calcular el gasto.")
        if encabezado_valido and detalles_validos:
            try:
                with transaction.atomic():
                    if pk:
                        RegistroGasto.objects.select_for_update().get(pk=pk)
                        movimiento = movimiento_gasto(pk).first()
                    elegida = form.cleaned_data.get("cuenta_bancaria")
                    cuentas = _bloquear_cuentas(movimiento.cuenta_id if movimiento else None,
                                                elegida.pk if elegida else None)
                    _validar_movimiento_editable(movimiento)
                    cuenta = cuentas.get(elegida.pk) if elegida else None
                    if elegida:
                        if not cuenta or not cuenta.activa or not cuenta.banco.activo or cuenta.moneda != form.cleaned_data["moneda"]:
                            raise ValidationError("Selecciona una cuenta activa en la moneda del gasto.")
                        _validar_mes_abierto(cuenta.pk, form.cleaned_data["fecha_gasto"])
                    from ventas.pagos_calculos import total_en_usd
                    objeto = form.save(commit=False)
                    objeto.tasa_bcv = form.cleaned_data["tasa_bcv"]
                    objeto.monto_usd = objeto.total if objeto.moneda == "USD" else total_en_usd(objeto.total, objeto.tasa_bcv)
                    objeto.save()
                    detalles.instance=objeto
                    detalles.save()
                    if cuenta:
                        MovimientoInterno.objects.update_or_create(origen="GASTO_OPERATIVO", pago_id=objeto.pk,
                            defaults={"cuenta": cuenta, "fecha": objeto.fecha_gasto,
                                      "referencia": objeto.referencia_pago, "monto": -objeto.total})
                    elif movimiento:
                        movimiento.delete()
                    if pk:
                        _registrar_auditoria(request.user, "Editar", pk)
            except ValidationError as error:
                form.add_error(None, error)
            except IntegrityError:
                form.add_error(None,"No se pudo guardar. Comprueba la factura del proveedor y los datos de los productos.")
            else:
                messages.success(request,"El gasto fue guardado correctamente.")
                return redirect("gastos:ver",pk=objeto.pk)
    return render(request,"gastos/formulario.html",{
        "form":form,"detalles":detalles,"admite_total_historico":admite_total_historico,"titulo":"Editar gasto" if pk else "Registrar gasto",
        "seccion":"registros","volver":"gastos:inicio",
    })


@login_required
def ver_registro(request,pk):
    objeto=get_object_or_404(RegistroGasto.objects.select_related("gasto__grupo","proveedor").prefetch_related("detalles__producto"),pk=pk)
    movimiento = movimiento_gasto(pk).select_related('cuenta__banco').first()
    return render(request,"gastos/documento.html",{"objeto":objeto,"seccion":"registros",
        "cuenta_pago": movimiento.cuenta if movimiento and request.user.has_perm('bancos.view_cuentabancaria') else None})


@login_required
def eliminar_registro(request,pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    objeto=get_object_or_404(RegistroGasto,pk=pk)
    if request.method=="POST":
        try:
            with transaction.atomic():
                objeto = RegistroGasto.objects.select_for_update().get(pk=pk)
                movimiento = movimiento_gasto(pk).first()
                if movimiento:
                    _bloquear_cuentas(movimiento.cuenta_id)
                    _validar_movimiento_editable(movimiento)
                    movimiento.delete()
                objeto.delete()
                _registrar_auditoria(request.user, "Eliminar", pk)
        except ValidationError as error:
            messages.warning(request, error.messages[0])
        except ProtectedError:
            messages.warning(request, "El gasto tiene registros asociados y no puede eliminarse.")
        else:
            messages.success(request, "El gasto fue eliminado correctamente.")
        return redirect("gastos:inicio")
    bloqueo = _redirigir_si_bloqueado(request, movimiento_gasto(pk).first(), pk)
    if bloqueo:
        return bloqueo
    return render(request,"gastos/eliminar.html",{"objeto":objeto,"seccion":"registros","catalogo":"","volver":"gastos:inicio"})


@login_required
def lista_catalogo(request,catalogo):
    modelo,_,titulo=_catalogo(catalogo)
    objetos=modelo.objects.all()
    if catalogo=="tipos":objetos=objetos.select_related("grupo")
    q=request.GET.get("q","").strip()[:100]
    estado=request.GET.get("estado","")
    if q:
        consulta=Q(descripcion__icontains=q)
        if catalogo=="proveedores":consulta|=Q(rif__icontains=q)
        objetos=objetos.filter(consulta)
    if estado=="activos":objetos=objetos.filter(activo=True)
    elif estado=="inactivos":objetos=objetos.filter(activo=False)
    pagina=Paginator(objetos,30).get_page(request.GET.get("page"))
    parametros=request.GET.copy();parametros.pop("page",None)
    return render(request,"gastos/catalogo.html",{"pagina":pagina,"catalogo":catalogo,"titulo":titulo,"seccion":catalogo,"q":q,"estado":estado,"parametros":parametros.urlencode()})


@login_required
def formulario_catalogo(request,catalogo,pk=None):
    modelo,formulario,titulo=_catalogo(catalogo)
    objeto=get_object_or_404(modelo,pk=pk) if pk else None
    form=formulario(request.POST if request.method=="POST" else None,instance=objeto)
    if request.method=="POST" and form.is_valid():
        try:
            with transaction.atomic():form.save()
        except IntegrityError:form.add_error(None,"No se pudo guardar: comprueba los datos y posibles duplicados.")
        else:
            messages.success(request,"El registro fue guardado correctamente.")
            return redirect("gastos:catalogo",catalogo=catalogo)
    return render(request,"gastos/formulario.html",{"form":form,"titulo":("Editar · " if objeto else "Nuevo · ")+titulo,"catalogo":catalogo,"seccion":catalogo})


@login_required
@require_POST
def estado_catalogo(request,catalogo,pk):
    modelo,_,_=_catalogo(catalogo)
    objeto=get_object_or_404(modelo,pk=pk)
    objeto.activo=not objeto.activo;objeto.save(update_fields=["activo"])
    messages.success(request,"Estado actualizado correctamente.")
    return redirect("gastos:catalogo",catalogo=catalogo)


@login_required
def eliminar_catalogo(request,catalogo,pk):
    modelo,_,_=_catalogo(catalogo)
    objeto=get_object_or_404(modelo,pk=pk)
    if request.method=="POST":
        try:objeto.delete()
        except ProtectedError:messages.warning(request,"No puedes eliminar este registro porque tiene datos asociados. Puedes desactivarlo para conservar el historial.")
        else:messages.success(request,"El registro fue eliminado correctamente.")
        return redirect("gastos:catalogo",catalogo=catalogo)
    return render(request,"gastos/eliminar.html",{"objeto":objeto,"catalogo":catalogo,"seccion":catalogo})
