from django import forms
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import OuterRef, Q, Subquery
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from control_inventario.models import MovimientoStock
from inventario.models import GrupoProducto, Producto
from ventas.calculos import dinero
from .precios import precio_con_recargo


class FiltroConsultaPrecios(forms.Form):
    grupo = forms.ModelChoiceField(GrupoProducto.objects.all(), required=False, empty_label="Todos",
        widget=forms.Select(attrs={"class": "form-select"}))
    producto = forms.CharField(required=False, max_length=100, label="Código o nombre de producto",
        widget=forms.TextInput(attrs={"class": "form-control"}))
    activo = forms.ChoiceField(required=False, label="Estado del producto",
        choices=[("", "Todos"), ("si", "Activo"), ("no", "Inactivo")],
        widget=forms.Select(attrs={"class": "form-select"}))
    comercializacion = forms.ChoiceField(required=False, label="Comercialización",
        choices=[("", "Todos"), ("si", "Activa"), ("no", "Inactiva")],
        widget=forms.Select(attrs={"class": "form-select"}))

    aplica_venta = forms.ChoiceField(required=False, label="Aplica comisión en venta",
        choices=[("", "Todos"), ("si", "Sí"), ("no", "No")],
        widget=forms.Select(attrs={"class": "form-select"}))
    promocionable = forms.ChoiceField(required=False, label="Promocionable",
        choices=[("", "Todos"), ("si", "Sí"), ("no", "No")],
        widget=forms.Select(attrs={"class": "form-select"}))


@login_required(login_url="iniciar_sesion")
@permission_required("ventas_productos.view_porcentajeproducto", raise_exception=True)
@require_GET
def consulta_precios(request, descargar_pdf=False):
    filtro = FiltroConsultaPrecios(request.GET)
    productos = Producto.objects.select_related("grupo", "porcentaje_venta").order_by(
        "grupo__descripcion", "grupo_id", "codigo_producto", "pk",
    )
    if filtro.is_valid():
        datos = filtro.cleaned_data
        if datos["grupo"]:
            productos = productos.filter(grupo=datos["grupo"])
        for palabra in datos["producto"].upper().split():
            productos = productos.filter(Q(codigo_producto__icontains=palabra) | Q(nombre_producto__icontains=palabra))
        for campo in ("activo", "comercializacion", "promocionable"):
            if datos[campo]:
                productos = productos.filter(**{campo: datos[campo] == "si"})
        if datos["aplica_venta"]:
            productos = productos.filter(sin_comision=datos["aplica_venta"] == "no")
    else:
        productos = productos.none()
    costo = MovimientoStock.objects.filter(producto_id=OuterRef("pk"), fecha__lte=timezone.localdate(),
        costo_unitario_usd__gt=0).order_by("-registrado_en", "-id").values("costo_unitario_usd")[:1]
    productos = productos.annotate(ultimo_costo=Subquery(costo))
    if descargar_pdf:
        if not filtro.is_valid():
            return HttpResponse("Revisa los filtros de la lista de precios.", status=400)
        from .models import EscalaComisionProducto
        from .pdf_precios import generar_lista_precios

        escalas = None
        if request.user.has_perm("ventas_productos.view_escalacomisionproducto"):
            escalas = list(EscalaComisionProducto.objects.filter(activo=True).order_by("unidades"))
        for producto in productos:
            _asignar_precio(producto)
        respuesta = HttpResponse(generar_lista_precios(productos, escalas), content_type="application/pdf")
        respuesta["Content-Disposition"] = 'attachment; filename="lista_de_precios.pdf"'
        return respuesta
    pagina = Paginator(productos, 25).get_page(request.GET.get("page"))
    for producto in pagina:
        _asignar_precio(producto)
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "ventas_productos/consulta_precios.html", {
        "filtro": filtro, "pagina": pagina, "seccion_precios": True,
        "paginas": pagina.paginator.get_elided_page_range(pagina.number),
        "parametros": parametros.urlencode(),
    })


def _asignar_precio(producto):
    producto.precio_consulta = None
    regla = getattr(producto, "porcentaje_venta", None)
    if regla and regla.activo and producto.ultimo_costo is not None and dinero(producto.ultimo_costo) > 0:
        precio = precio_con_recargo(producto.ultimo_costo, regla.porcentaje)
        if 0 < precio < 10**16:
            producto.precio_consulta = precio
