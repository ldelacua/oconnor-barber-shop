from decimal import Decimal, localcontext

from django import forms
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_GET

from barberos.models import Barbero
from inventario.models import GrupoProducto
from liquidaciones.models import ComisionVentaProducto
from ventas.calculos import dinero

CERO = Decimal("0.00")
PERMISOS = ("ventas_productos.view_documentoproducto", "liquidaciones.view_liquidacion")


class FiltroComisionesPagadas(forms.Form):
    desde = forms.DateField(required=False, label="Pago desde", widget=forms.DateInput(attrs={"type": "date"}))
    hasta = forms.DateField(required=False, label="Pago hasta", widget=forms.DateInput(attrs={"type": "date"}))
    prestador = forms.ModelChoiceField(Barbero.objects.order_by("nombre", "apellido", "pk"),
        required=False, label="Prestador de servicio", empty_label="Todos")
    grupo = forms.ModelChoiceField(GrupoProducto.objects.all(), required=False, empty_label="Todos")
    producto = forms.CharField(required=False, max_length=100, label="Código o nombre de producto")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs["class"] = "form-select" if isinstance(campo.widget, forms.Select) else "form-control"

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            self.add_error("hasta", "La fecha hasta debe ser igual o posterior a la fecha desde.")
        return datos


def _repartir_comision(comision):
    # Repartir la comisión registrada, sin volver a calcularla con la escala vigente.
    acumulado = asignado = CERO
    with localcontext() as contexto:
        contexto.prec = 60
        for linea in comision.venta.detalles.all():
            if linea.sin_comision:
                continue
            acumulado += linea.neto_usd
            parte_acumulada = dinero(comision.comision_usd * acumulado / comision.base_usd) if comision.base_usd else CERO
            yield linea, parte_acumulada - asignado
            asignado = parte_acumulada


def _fila(**datos):
    return {"cantidad": CERO, "monto": CERO, "comision": CERO, **datos}


def _agrupar(filtros, por_producto=False):
    raiz, total = {}, _fila()
    if not filtros.is_valid():
        return [], total
    datos = filtros.cleaned_data
    comisiones = ComisionVentaProducto.objects.filter(periodo__liquidacion__sellado=True).select_related(
        "periodo__prestador",
    ).prefetch_related("venta__detalles__producto__grupo").order_by(
        "periodo__prestador__nombre", "periodo__prestador__apellido", "periodo__prestador_id", "pk",
    )
    for campo, lookup in (("desde", "periodo__liquidacion__fecha_cancelacion__gte"),
                          ("hasta", "periodo__liquidacion__fecha_cancelacion__lte"),
                          ("prestador", "periodo__prestador")):
        if datos[campo]:
            comisiones = comisiones.filter(**{lookup: datos[campo]})
    palabras = datos["producto"].upper().split()
    grupo_filtro = datos["grupo"]
    for comision in comisiones.iterator(chunk_size=500):
        prestador = comision.periodo.prestador
        for linea, pagada in _repartir_comision(comision):
            producto = linea.producto
            if grupo_filtro and producto.grupo_id != grupo_filtro.pk:
                continue
            texto = f"{producto.codigo_producto} {producto.nombre_producto} {linea.codigo} {linea.descripcion}".upper()
            if not all(palabra in texto for palabra in palabras):
                continue
            claves = (
                (prestador.pk, f"{prestador.nombre} {prestador.apellido}"),
                (producto.grupo_id or 0, str(producto.grupo or "Sin grupo")),
                (producto.pk, f"{producto.codigo_producto} · {producto.nombre_producto}"),
            )
            if por_producto:
                claves = (claves[1], claves[2], claves[0])
            nivel = raiz
            filas = [total]
            for clave, nombre in claves:
                nodo = nivel.setdefault(clave, _fila(id=clave, nombre=nombre, hijos={}))
                filas.append(nodo)
                nivel = nodo["hijos"]
            for fila in filas:
                fila["cantidad"] += linea.cantidad
                fila["monto"] += linea.neto_usd
                fila["comision"] += pagada
    def ordenar(nivel):
        filas = sorted(nivel.values(), key=lambda f: (f["nombre"].casefold(), f["id"]))
        for fila in filas:
            fila["hijos"] = ordenar(fila["hijos"])
        return filas

    return ordenar(raiz), total


@login_required(login_url="iniciar_sesion")
@permission_required(PERMISOS, raise_exception=True)
@require_GET
def historico_comisiones(request, por_producto=False):
    filtros = FiltroComisionesPagadas(request.GET)
    filas, total = _agrupar(filtros, por_producto)
    pagina = Paginator(filas, 25).get_page(request.GET.get("page"))
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "ventas_productos/historico_comisiones.html", {
        "filtros": filtros, "pagina": pagina, "total": total, "por_producto": por_producto,
        "paginas": pagina.paginator.get_elided_page_range(pagina.number), "parametros": parametros.urlencode(),
    })
