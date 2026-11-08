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
from .reportes import FiltrosServiciosForm


class FiltroHistorico(FiltrosServiciosForm):
    tipo = None
    servicio = forms.ModelChoiceField(
        Servicio.objects.order_by("nombre", "pk"), required=False, empty_label="Todos",
        label="Tipo de servicio",
    )
    cliente = forms.CharField(required=False, max_length=100, label="Nombre del cliente")


@login_required
@permission_required("ventas.view_documentoventa", raise_exception=True)
@require_GET
def historico(request, servicio_id=None, prestador_id=None):
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
    else:
        nivel, nombre_total = "servicios", "general"
        filas = lineas.values("servicio_id", "servicio__codigo", "servicio__nombre").annotate(
            **sumas,
        ).order_by("servicio__nombre", "servicio_id")

    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "ventas/historico.html", {
        "filtro": filtro, "nivel": nivel, "servicio": servicio, "nombre_total": nombre_total,
        "pagina": Paginator(filas, 15).get_page(request.GET.get("page")),
        "total": total, "query": query.urlencode(),
    })
