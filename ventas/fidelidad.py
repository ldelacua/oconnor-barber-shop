from django.db.models import Case, When, Value
from .models import DetalleVenta, TarjetaFidelidad


def tarjetas(cliente, incluir_historial=False):
    configuraciones = list(TarjetaFidelidad.objects.filter(activa=True, servicio__activo=True).select_related("servicio"))
    por_servicio = {t.servicio_id: t for t in configuraciones}
    for t in configuraciones:
        t.acumulados = 0
        t.facturas = {}
        t.ciclo = []
    lineas = DetalleVenta.objects.filter(
        documento__cliente=cliente, documento__tipo_documento="FA", documento__sellado=True,
        servicio_id__in=por_servicio,
    ).exclude(documento_id__in=DetalleVenta.objects.filter(
        documento__tipo_documento="RE", documento__sellado=True, documento__cliente=cliente,
    ).values("documento__documento_original_id")).order_by("documento_id", Case(When(promocion="FIDELIDAD", then=Value(0)), default=Value(1)), "pk").values_list(
        "servicio_id", "documento_id", "documento__fecha", "promocion", "cantidad_servicio", "monto_servicio", "monto_descuento_usd",
    )
    for servicio, documento, fecha, promocion, cantidad, bruto, descuento in lineas:
        t = por_servicio[servicio]
        if fecha < t.desde:
            continue
        if promocion == "FIDELIDAD":
            if incluir_historial:
                for factura in t.ciclo:
                    factura["canje"] = documento
                t.ciclo = []
            t.acumulados = 0
        elif not promocion and bruto > descuento:
            t.acumulados += cantidad
            if incluir_historial:
                if documento not in t.facturas:
                    t.facturas[documento] = {"numero": documento, "fecha": fecha, "cortes": 0, "canje": None}
                    t.ciclo.append(t.facturas[documento])
                t.facturas[documento]["cortes"] += cantidad
    for t in configuraciones:
        t.faltan = max(0, t.cortes - t.acumulados)
        t.disponible = not t.faltan
    return configuraciones
