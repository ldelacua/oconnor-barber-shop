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

CATALOGOS={
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
    registros=RegistroGasto.objects.select_related("gasto__grupo","proveedor")
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


@login_required
def formulario_registro(request,pk=None):
    registro=get_object_or_404(RegistroGasto,pk=pk) if pk else None
    form=RegistroForm(request.POST if request.method=="POST" else None,instance=registro)
    if request.method=="POST" and form.is_valid():
        try:
            with transaction.atomic():objeto=form.save()
        except IntegrityError:
            form.add_error(None,"No se pudo guardar. Comprueba que no exista esa factura para el mismo proveedor y que los importes sean válidos.")
        else:
            messages.success(request,"El gasto fue guardado correctamente.")
            return redirect("gastos:ver",pk=objeto.pk)
    return render(request,"gastos/formulario.html",{"form":form,"titulo":"Editar gasto" if registro else "Registrar gasto","seccion":"registros","volver":"gastos:inicio"})


@login_required
def ver_registro(request,pk):
    objeto=get_object_or_404(RegistroGasto.objects.select_related("gasto__grupo","proveedor"),pk=pk)
    return render(request,"gastos/documento.html",{"objeto":objeto,"seccion":"registros"})


@login_required
def eliminar_registro(request,pk):
    objeto=get_object_or_404(RegistroGasto,pk=pk)
    if request.method=="POST":
        try:objeto.delete()
        except ProtectedError:messages.warning(request,"El gasto tiene registros asociados y no puede eliminarse.")
        else:messages.success(request,"El gasto fue eliminado correctamente.")
        return redirect("gastos:inicio")
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
