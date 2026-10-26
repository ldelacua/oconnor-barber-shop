from django.conf import settings
from django.core.checks import register, Error, Tags

@register(Tags.security)
def comprobar_permisos(app_configs,**kwargs):
    middleware=list(settings.MIDDLEWARE)
    seguridad='seguridad.middleware.PermisosModulosMiddleware'
    autenticacion='django.contrib.auth.middleware.AuthenticationMiddleware'
    if seguridad not in middleware or autenticacion not in middleware or middleware.index(seguridad)<=middleware.index(autenticacion):
        return [Error('Activa la protección de módulos después de AuthenticationMiddleware ejecutando instalar_seguridad_modulos.py.',id='seguridad.E001')]
    return []
