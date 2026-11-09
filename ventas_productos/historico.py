from django import forms
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from barberos.models import Barbero
from inventario.models import GrupoProducto, Producto
from .models import LineaProducto


class FiltroHistorico(forms.Form):
    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    producto = forms.CharField(required=False, max_length=100, label="Código o nombre del producto")
    grupo = forms.ModelChoiceField(GrupoProducto.objects.all(), required=False, empty_label="Todos")
    vendedor = forms.ChoiceField(required=False, label="Venta realizada por")
    comision = forms.ChoiceField(required=False, label="Comisión",
        choices=[("", "Todas"), ("si", "Con comisión"), ("no", "Sin comisión")])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vendedor"].choices = [
            ("", "Todos"), ("barberia", "Barbería"),
            *((str(p.pk), str(p)) for p in Barbero.objects.order_by("nombre", "apellido", "pk")),
        ]
        for campo in self.fields.values():
            campo.widget.attrs["class"] = "form-select" if isinstance(campo.widget, forms.Select) else "form-control"

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            self.add_error("hasta", "La fecha hasta debe ser igual o posterior a la fecha desde.")
        return datos


def lineas_filtradas(filtro):
    if not filtro.is_valid():
        return LineaProducto.objects.none()
    datos = filtro.cleaned_data
    lineas = LineaProducto.objects.filter(documento__tipo="VP", documento__sellado=True)
    if datos["desde"]:
        lineas = lineas.filter(documento__fecha__gte=datos["desde"])
    if datos["hasta"]:
        lineas = lineas.filter(documento__fecha__lte=datos["hasta"])
    for palabra in datos["producto"].upper().split():
        lineas = lineas.filter(Q(codigo__icontains=palabra) | Q(descripcion__icontains=palabra)
                               | Q(producto__codigo_producto__icontains=palabra)
                               | Q(producto__nombre_producto__icontains=palabra))
    if datos["grupo"]:
        lineas = lineas.filter(producto__grupo=datos["grupo"])
    if datos["vendedor"] == "barberia":
        lineas = lineas.filter(documento__prestador__isnull=True)
    elif datos["vendedor"]:
        lineas = lineas.filter(documento__prestador_id=datos["vendedor"])
    if datos["comision"]:
        lineas = lineas.filter(sin_comision=datos["comision"] == "no")
    return lineas


def _desglosar(lineas, pagina, campo, por_prestador):
    grupos = {fila[campo]: fila for fila in pagina}
    ids = [pk for pk in grupos if pk is not None]
    seleccion = Q(**{f"{campo}__in": ids})
    if None in grupos:
        seleccion |= Q(**{f"{campo}__isnull": True})
    desglose = {pk: {} for pk in grupos}
    for linea in lineas.filter(seleccion).select_related(
        "producto__grupo", "documento__prestador", "documento__reverso",
    ).order_by("producto__grupo__descripcion", "producto__codigo_producto", "-documento__fecha", "-documento_id", "pk").iterator():
        documento = linea.documento
        pk = documento.prestador_id if por_prestador else linea.producto.grupo_id
        grupo = desglose[pk].setdefault(linea.producto.grupo_id, {
            "id": linea.producto.grupo_id or 0, "nombre": str(linea.producto.grupo or "Sin grupo"),
            "cantidad": 0, "facturas_ids": set(), "productos": {},
        })
        grupo["facturas_ids"].add(documento.pk)
        producto = grupo["productos"].setdefault(linea.producto_id, {
            "id": linea.producto_id, "codigo": linea.producto.codigo_producto,
            "nombre": linea.producto.nombre_producto, "cantidad": 0, "facturas": [],
        })
        producto["facturas"].append(linea)
        reverso = getattr(documento, "reverso", None)
        if not reverso or not reverso.sellado:
            producto["cantidad"] += linea.cantidad
            grupo["cantidad"] += linea.cantidad
    for pk, fila in grupos.items():
        fila["id"] = pk or 0
        if por_prestador:
            fila["nombre"] = (f'{fila["documento__prestador__nombre"]} {fila["documento__prestador__apellido"]}'
                              if pk is not None else "Barbería")
        else:
            fila["nombre"] = fila["producto__grupo__descripcion"] or "Sin grupo"
        if por_prestador:
            fila["grupos"] = list(desglose[pk].values())
            for grupo in fila["grupos"]:
                grupo["facturas"] = len(grupo.pop("facturas_ids"))
                grupo["productos"] = list(grupo["productos"].values())
        else:
            fila["productos"] = list(desglose[pk][pk]["productos"].values())


@login_required(login_url="iniciar_sesion")
@permission_required("ventas_productos.view_documentoproducto", raise_exception=True)
@require_GET
def historico(request, producto_id=None, por_prestador=False, vendedor_id=None):
    filtro = FiltroHistorico(request.GET)
    lineas = lineas_filtradas(filtro)
    producto = vendedor = None
    detalle = producto_id is not None or vendedor_id is not None
    vigentes = Q(documento__reverso__isnull=True) | Q(documento__reverso__sellado=False)
    campo = None
    if por_prestador and not detalle:
        campo = "documento__prestador_id"
        filas = lineas.values("documento__prestador_id", "documento__prestador__nombre",
                             "documento__prestador__apellido").annotate(
            cantidad=Sum("cantidad", filter=vigentes, default=0),
            facturas=Count("documento_id", distinct=True),
        ).order_by("documento__prestador__nombre", "documento__prestador__apellido", "documento__prestador_id")
    elif vendedor_id is not None:
        vendedor = get_object_or_404(Barbero, pk=vendedor_id) if vendedor_id else "Barbería"
        filas = lineas.filter(documento__prestador_id=vendedor_id or None).select_related(
            "documento__reverso",
        ).order_by("-documento__fecha", "-documento_id", "pk")
    elif producto_id is None:
        campo = "producto__grupo_id"
        filas = lineas.values(campo, "producto__grupo__descripcion").annotate(
            cantidad=Sum("cantidad", filter=vigentes, default=0),
            facturas=Count("documento_id", distinct=True),
        ).order_by("producto__grupo__descripcion", campo)
    else:
        producto = get_object_or_404(Producto, pk=producto_id)
        filas = lineas.filter(producto=producto).select_related(
            "documento__prestador", "documento__reverso",
        ).order_by("-documento__fecha", "-documento_id")
    pagina = Paginator(filas, 25).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    plantilla = "ventas_productos/historico.html"
    if campo:
        _desglosar(lineas, pagina, campo, por_prestador)
        plantilla = "ventas_productos/historico_expandible.html"
    return render(request, plantilla, {
        "filtro": filtro, "pagina": pagina, "query": query.urlencode(), "producto": producto,
        "paginas": pagina.paginator.get_elided_page_range(pagina.number),
        "por_prestador": por_prestador, "detalle": detalle, "vendedor": vendedor,
    })
