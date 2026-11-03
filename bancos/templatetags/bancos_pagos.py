from django import template
from bancos.models import MovimientoInterno

register = template.Library()


@register.simple_tag(takes_context=True)
def pagos_con_cuenta(context, pagos, origen):
    pagos = list(pagos)
    cuentas = {}
    if context.get('request') and context['request'].user.has_perm('bancos.view_cuentabancaria'):
        movimientos = MovimientoInterno.objects.filter(origen=origen, pago_id__in=[p.pk for p in pagos]).select_related('cuenta__banco')
        cuentas = {m.pago_id: m.cuenta for m in movimientos}
    return [(p, cuentas.get(p.pk)) for p in pagos]
