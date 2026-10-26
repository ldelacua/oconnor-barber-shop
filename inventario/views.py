from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Q, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET
from datetime import date
from .forms import ProductoForm, ProveedorForm, UnidadMedidaForm, CompraForm, DetalleFormSet, FiltroCompras
from .models import Compra, Producto, Proveedor, UnidadMedida
from .condiciones import tasa_para_fecha, iva_vigente
from .services import actualizar_compra, guardar_borrador, eliminar_borrador

def regreso(request, defecto="inventario:compras"):
    valor = request.POST.get("next") or request.GET.get("next", "")
    # Solo rutas locales; también impide esquemas y rutas // externas.
    if valor.startswith("/") and not valor.startswith("//") and "\\" not in valor and not any(ord(c) < 32 for c in valor):
        return valor
    return reverse(defecto)

def paginar(request, datos):
    pagina = Paginator(datos, 25).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return pagina, query.urlencode()

@login_required(login_url="iniciar_sesion")
def compras(request):
    filtro = FiltroCompras(request.GET)
    datos = Compra.objects.select_related("proveedor").prefetch_related("detalles__producto__unidad_medida")
    if filtro.is_valid():
        f = filtro.cleaned_data
        if f.get("proveedor"): datos = datos.filter(proveedor=f["proveedor"])
        if f.get("desde"): datos = datos.filter(fecha_compra__gte=f["desde"])
        if f.get("hasta"): datos = datos.filter(fecha_compra__lte=f["hasta"])
        if f.get("factura"): datos = datos.filter(numero_factura__icontains=f["factura"])
        if f.get("producto"): datos = datos.filter(detalles__producto__codigo_producto__icontains=f["producto"]).distinct()
    else:
        datos = datos.none()
    pagina, query = paginar(request, datos)
    return render(request, "inventario/compras.html", {"filtro": filtro, "pagina": pagina, "query": query})

@login_required(login_url="iniciar_sesion")
def maestro_lista(request, tipo):
    es_producto = tipo == "productos"
    modelo = {"productos": Producto, "proveedores": Proveedor, "unidades": UnidadMedida}[tipo]
    datos = modelo.objects.all()
    q = request.GET.get("q", "").strip().upper()
    if es_producto:
        from .existencias import productos_con_existencia
        datos = productos_con_existencia(datos.select_related("unidad_medida"))
        if q:
            datos = datos.filter(Q(codigo_producto__icontains=q) | Q(nombre_producto__icontains=q))
    elif q:
        datos = datos.filter(Q(nombre__icontains=q) | (Q(codigo__icontains=q) if tipo == "unidades" else Q(rif__icontains=q)))
    datos = datos.order_by("codigo_producto", "pk") if es_producto else datos.order_by("nombre", "pk")
    pagina, query = paginar(request, datos)
    return render(request, "inventario/maestros.html", {
        "pagina": pagina, "query": query, "tipo": tipo, "es_producto": es_producto,
        "titulo": {"productos": "Consulta de productos", "proveedores": "Proveedores de inventario", "unidades": "Unidades de medida"}[tipo],
        "q": q, "regresar": regreso(request), "ruta_actual": request.get_full_path()})

@login_required(login_url="iniciar_sesion")
def maestro_form(request, tipo, pk=None):
    es_producto = tipo == "productos"
    modelo, clase = {"productos": (Producto, ProductoForm), "proveedores": (Proveedor, ProveedorForm),
                     "unidades": (UnidadMedida, UnidadMedidaForm)}[tipo]
    objeto = get_object_or_404(modelo, pk=pk) if pk else None
    form = clase(request.POST or None, instance=objeto)
    destino = regreso(request, "inventario:" + tipo)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except IntegrityError:
            form.add_error(None, "El código o RIF ya está registrado. Revisa los datos.")
        else:
            messages.success(request, "Registro guardado.")
            return redirect(destino)
    return render(request, "inventario/maestro_form.html", {
        "form": form, "regresar": destino, "es_producto": es_producto, "ruta_actual": request.get_full_path(),
        "titulo": ("Editar " if pk else "Nuevo ") + {"productos": "producto", "proveedores": "proveedor de inventario", "unidades": "unidad de medida"}[tipo]})

@login_required(login_url="iniciar_sesion")
def compra_form(request, pk=None):
    compra = get_object_or_404(Compra, pk=pk) if pk else Compra()
    destino = regreso(request)
    if compra.estado == Compra.ACTUALIZADA:
        return redirect(reverse("inventario:detalle", args=[compra.pk]) + "?" + urlencode({"next": destino}))
    form = CompraForm(request.POST or None, instance=compra)
    detalles = DetalleFormSet(request.POST or None, instance=compra, prefix="detalles",
                              form_kwargs={"iva": form.iva_automatico})
    if request.method == "POST":
        valido = form.is_valid()
        valido_detalle = detalles.is_valid()
        if valido and valido_detalle:
            try:
                compra = guardar_borrador(form, detalles, request.user.get_username())
            except ValidationError as e:
                form.add_error(None, e)
            except (IntegrityError, OperationalError):
                form.add_error(None, "No se guardó la compra. Puede existir esa factura o haber cambios simultáneos. Recarga y verifica.")
            else:
                messages.success(request, "Borrador guardado. Aún no afecta las existencias.")
                return redirect(reverse("inventario:detalle", args=[compra.pk]) + "?" + urlencode({"next": destino}))
    return render(request, "inventario/compra_form.html", {
        "form": form, "detalles": detalles, "compra": compra, "regresar": destino,
        "retorno_editor": request.get_full_path()})

@login_required(login_url="iniciar_sesion")
def detalle(request, pk):
    compra = get_object_or_404(Compra.objects.select_related("proveedor").prefetch_related("detalles__producto__unidad_medida"), pk=pk)
    return render(request, "inventario/detalle.html", {"compra": compra, "regresar": regreso(request)})

@login_required(login_url="iniciar_sesion")
def actualizar(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    compra = get_object_or_404(Compra, pk=pk)
    destino = regreso(request)
    try:
        revision = int(request.POST.get("revision", "-1"))
        cambio = actualizar_compra(compra.pk, request.user.get_username(), revision)
    except (ValidationError, ValueError) as e:
        messages.error(request, " ".join(e.messages) if isinstance(e, ValidationError) else "Versión inválida. Recarga la compra.")
    except (IntegrityError, OperationalError):
        messages.error(request, "No se actualizó el inventario. Recarga la compra y verifica si otro usuario la actualizó.")
    else:
        messages.success(request, "Inventario actualizado. La compra quedó bloqueada." if cambio else "La compra ya estaba actualizada; no se duplicaron las existencias.")
    return redirect(reverse("inventario:detalle", args=[pk]) + "?" + urlencode({"next": destino}))

@login_required(login_url="iniciar_sesion")
def eliminar(request, pk):
    compra = get_object_or_404(Compra, pk=pk)
    destino = regreso(request)
    if request.method == "POST":
        try:
            eliminar_borrador(pk, int(request.POST.get("revision", "-1")))
        except (ValidationError, ValueError) as e:
            messages.error(request, " ".join(e.messages) if isinstance(e, ValidationError) else "Versión inválida.")
        except (IntegrityError, OperationalError):
            messages.error(request, "No se eliminó. Recarga para comprobar el estado de la compra.")
        else:
            messages.success(request, "Borrador eliminado.")
            return redirect(destino)
        return redirect(reverse("inventario:detalle", args=[pk]) + "?" + urlencode({"next": destino}))
    return render(request, "inventario/eliminar.html", {"compra": compra, "regresar": destino})


@login_required(login_url="iniciar_sesion")
@require_GET
def condiciones_compra(request):
    try:
        fecha = date.fromisoformat(request.GET.get("fecha", ""))
    except ValueError:
        return JsonResponse({"error": "Fecha de compra no válida."}, status=400)
    try:
        tasa = tasa_para_fecha(fecha)
        iva = iva_vigente()
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=422)
    return JsonResponse({"tasa": str(tasa), "iva": str(iva)})
