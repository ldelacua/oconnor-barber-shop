from django import template
from bancos.models import MovimientoInterno

register = template.Library()


@register.simple_tag(takes_context=True)
def pagos_con_cuenta(context, pagos, origen):
    request = context.get("request")
    return filas_con_cuenta(request.user if request else None, pagos, origen)


def filas_con_cuenta(usuario, pagos, origen):
    pagos = list(pagos)
    cuentas = {}
    if usuario is not None and usuario.has_perm("bancos.view_cuentabancaria"):
        movimientos = MovimientoInterno.objects.filter(origen=origen, pago_id__in=[p.pk for p in pagos]).select_related('cuenta__banco')
        cuentas = {m.pago_id: m.cuenta for m in movimientos}
        if origen in ("SERVICIOS", "PRODUCTOS"):
            from ventas.models import CobroCompartido
            campo = "servicios_id" if origen == "SERVICIOS" else "productos_id"
            faltantes = {p.documento_id for p in pagos if p.pk not in cuentas}
            if faltantes:
                compartidos = CobroCompartido.objects.filter(
                    **{f"{campo}__in": faltantes}, cuenta__isnull=False,
                ).select_related("cuenta__banco")
                por_documento = {getattr(c, campo): c.cuenta for c in compartidos}
                cuentas.update({p.pk: por_documento[p.documento_id] for p in pagos
                                if p.pk not in cuentas and p.documento_id in por_documento})
    return [(p, cuentas.get(p.pk)) for p in pagos]
