from decimal import Decimal

from django import forms
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from barberos.models import Barbero
from servicios.models import Servicio
from .models import DetalleVenta
from .pagos_calculos import total_en_usd
from .reportes import FiltrosServiciosForm


class FiltroHistorico(FiltrosServiciosForm):
    tipo = None
    servicio = forms.ModelChoiceField(
        Servicio.objects.order_by("nombre", "pk"), required=False, empty_label="Todos",
        label="Tipo de servicio",
    )
    cliente = forms.CharField(required=False, max_length=100, label="Nombre del cliente")


def _nombre_prestador(fila):
    if fila["barbero_id"] is None:
        return "Sin prestador registrado"
    return f'{fila["barbero__nombre"]} {fila["barbero__apellido"]}'


def _nombre_servicio(fila):
    return f'{fila["servicio__codigo"]} · {fila["servicio__nombre"]}'


def _anexar_facturas(lineas, pagina, importe, por_prestador):
    clave = "barbero_id" if por_prestador else "servicio_id"
    nombre = _nombre_prestador if por_prestador else _nombre_servicio
    padres = {fila[clave]: fila for fila in pagina}
    grupos = {pk: {} for pk in padres}
    cero = Decimal("0.00")
    total_usd = cero
    filas = lineas.values(
        "servicio_id", "servicio__nombre", "servicio__codigo", "barbero_id", "barbero__nombre", "barbero__apellido",
        "documento_id", "documento__fecha", "documento__cliente__nombre",
        "documento__cliente__apellido", "documento__reverso__sellado", "documento__tasa_bcv",
    ).annotate(cantidad=Sum("cantidad_servicio"), total_bs=Sum(importe))
    orden = ("servicio__nombre", "servicio_id") if por_prestador else ("barbero__nombre", "barbero__apellido", "barbero_id")
    for factura in filas.order_by(*orden, "-documento__fecha", "-documento_id").iterator():
        padre_id = factura[clave]
        hijo_id = factura["servicio_id" if por_prestador else "barbero_id"]
        vigente = not factura["documento__reverso__sellado"]
        tasa = factura["documento__tasa_bcv"]
        factura["total_usd"] = total_en_usd(factura["total_bs"], tasa) if tasa > 0 else None
        importe_usd = factura["total_usd"] or cero
        if vigente:
            total_usd += importe_usd
        if padre_id not in padres:
            continue
        hijo = grupos[padre_id].setdefault(hijo_id, {
            "id": hijo_id or 0,
            "nombre": _nombre_servicio(factura) if por_prestador else _nombre_prestador(factura),
            "facturas": [], "cantidad": 0, "total_bs": cero, "total_usd": cero,
        })
        hijo["facturas"].append(factura)
        if vigente:
            hijo["cantidad"] += factura["cantidad"]
            hijo["total_bs"] += factura["total_bs"]
            hijo["total_usd"] += importe_usd
    for pk, padre in padres.items():
        padre["id"] = pk or 0
        padre["nombre"] = nombre(padre)
        padre["grupos"] = list(grupos[pk].values())
        padre["total_usd"] = sum((h["total_usd"] for h in padre["grupos"]), cero)
    return total_usd


@login_required
@permission_required("ventas.view_documentoventa", raise_exception=True)
@require_GET
def historico(request, servicio_id=None, prestador_id=None, por_prestador=False):
    filtro = FiltroHistorico(request.GET)
    servicio = get_object_or_404(Servicio, pk=servicio_id) if servicio_id is not None else None
    prestador = get_object_or_404(Barbero, pk=prestador_id) if prestador_id else None
    lineas = DetalleVenta.objects.filter(documento__tipo_documento="FA", documento__sellado=True)
    vigentes = Q(documento__reverso__isnull=True) | Q(documento__reverso__sellado=False)
    if filtro.is_valid():
        datos = filtro.cleaned_data
        for campo, lookup in (("desde", "documento__fecha__gte"), ("hasta", "documento__fecha__lte"),
                              ("servicio", "servicio"), ("prestador", "barbero")):
            if datos[campo]:
                lineas = lineas.filter(**{lookup: datos[campo]})
        for palabra in datos["cliente"].split():
            lineas = lineas.filter(Q(documento__cliente__nombre__icontains=palabra)
                                   | Q(documento__cliente__apellido__icontains=palabra))
    else:
        lineas = lineas.none()

    if servicio is not None:
        lineas = lineas.filter(servicio=servicio)
    if prestador_id is not None:
        lineas = lineas.filter(barbero=prestador)

    # La base histórica no siempre se almacenaba. No incluir propinas ni otros renglones de la factura.
    importe = Coalesce("base_imponible_bs", F("monto_servicio_bs") - F("monto_descuento_bs")) + F("monto_impuesto")
    sumas = {"cantidad": Sum("cantidad_servicio", filter=vigentes, default=0),
             "total_bs": Sum(importe, filter=vigentes, default=0)}
    total = lineas.aggregate(**sumas)
    if prestador_id is not None:
        nivel = "facturas"
        nombre_total = f"{prestador.nombre} {prestador.apellido}" if prestador else "Sin prestador registrado"
        filas = lineas.values("documento_id", "documento__fecha", "documento__cliente__nombre",
                             "documento__cliente__apellido", "documento__reverso__sellado").annotate(
            cantidad=Sum("cantidad_servicio"), total_bs=Sum(importe),
        ).order_by("-documento__fecha", "-documento_id")
    elif servicio is not None:
        nivel, nombre_total = "prestadores", servicio.nombre
        filas = lineas.values("barbero_id", "barbero__nombre", "barbero__apellido").annotate(
            **sumas,
        ).order_by("barbero__nombre", "barbero__apellido", "barbero_id")
    elif por_prestador:
        nivel, nombre_total = "servicios", "general"
        filas = lineas.values("barbero_id", "barbero__nombre", "barbero__apellido").annotate(
            **sumas,
        ).order_by("barbero__nombre", "barbero__apellido", "barbero_id")
    else:
        nivel, nombre_total = "servicios", "general"
        filas = lineas.values("servicio_id", "servicio__codigo", "servicio__nombre").annotate(
            **sumas,
        ).order_by("servicio__nombre", "servicio_id")

    query = request.GET.copy()
    query.pop("page", None)
    pagina = Paginator(filas, 15).get_page(request.GET.get("page"))
    plantilla = "ventas/historico.html"
    total_usd = None
    if nivel == "servicios":
        total_usd = _anexar_facturas(lineas, pagina, importe, por_prestador)
        plantilla = "ventas/historico_expandible.html"
    return render(request, plantilla, {
        "filtro": filtro, "nivel": nivel, "servicio": servicio, "nombre_total": nombre_total,
        "pagina": pagina, "por_prestador": por_prestador,
        "total": total, "total_usd": total_usd, "query": query.urlencode(),
    })
