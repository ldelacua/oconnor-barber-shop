from django import template
from seguridad.accesos import enlace_permitido
register=template.Library()

@register.simple_tag(takes_context=True)
def puede_url(context,url):
    return enlace_permitido(context['request'].user,url)

@register.simple_tag(takes_context=True)
def menu_url(context,modulo):
    from seguridad.accesos import entrada_modulo
    return entrada_modulo(context['request'].user,modulo)
