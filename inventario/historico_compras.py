from decimal import Decimal

from django import forms
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .forms import FiltroCompras
from .models import Compra, DetalleCompra


class FiltroHistoricoCompras(FiltroCompras):
    producto = forms.CharField(required=False, max_length=100, label="Código o nombre de producto")
    divisa = forms.ChoiceField(required=False, choices=[("", "Todas"), ("BS", "Bs."), ("USD", "USD")])


@login_required(login_url="iniciar_sesion")
@permission_required("inventario.view_compra", raise_exception=True)
@require_GET
def historico_compras(request):
    filtros = FiltroHistoricoCompras(request.GET)
    detalles = DetalleCompra.objects.filter(compra__estado=Compra.ACTUALIZADA)
    if filtros.is_valid():
        datos = filtros.cleaned_data
        for campo, lookup in (
            ("proveedor", "compra__proveedor"), ("desde", "compra__fecha_compra__gte"),
            ("hasta", "compra__fecha_compra__lte"), ("factura", "compra__numero_factura__icontains"),
            ("divisa", "compra__divisa"),
        ):
            if datos[campo]:
                detalles = detalles.filter(**{lookup: datos[campo]})
        for palabra in datos["producto"].upper().split():
            detalles = detalles.filter(Q(producto__codigo_producto__icontains=palabra)
                                       | Q(producto__nombre_producto__icontains=palabra))
    else:
        detalles = detalles.none()

    resumen = detalles.values("producto_id", "producto__codigo_producto", "producto__nombre_producto",
                             "producto__unidad_medida__nombre").annotate(
        cantidad=Sum("cantidad"), facturas=Count("compra_id", distinct=True),
    ).order_by("producto__codigo_producto", "producto_id")
    pagina = Paginator(resumen, 25).get_page(request.GET.get("page"))
    productos = {fila["producto_id"]: fila for fila in pagina}
    for fila in productos.values():
        fila.update(detalles=[], bs=Decimal("0.00"), usd=Decimal("0.00"))
    lineas = detalles.filter(producto_id__in=productos).select_related("compra__proveedor").order_by(
        "-compra__fecha_compra", "-compra_id", "pk",
    )
    for linea in lineas.iterator():
        fila = productos[linea.producto_id]
        fila["detalles"].append(linea)
        fila[linea.compra.divisa.lower()] += linea.total
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "inventario/historico_compras.html", {
        "filtros": filtros, "pagina": pagina, "paginas": pagina.paginator.get_elided_page_range(pagina.number),
        "parametros": parametros.urlencode(),
    })
