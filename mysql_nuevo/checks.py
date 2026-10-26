from django.apps import apps
from django.conf import settings
from django.core.checks import Error, register, Tags

@register(Tags.database,Tags.models)
def verificar_perfil(app_configs,databases=None,**kwargs):
    if getattr(settings,'MYSQL_NUEVO_GENERANDO',False):return []
    errores=[]
    if settings.DATABASES['default']['ENGINE']!='django.db.backends.mysql':
        errores.append(Error('mysql_nuevo requiere el perfil config.settings_mysql.',id='mysql_nuevo.E001'))
    parciales={'cita_barbero_fecha_hora_unica','ci_un_conteo_abierto'}
    for m in apps.get_models():
        for c in m._meta.constraints:
            if c.__class__.__name__=='UniqueConstraint' and c.condition is not None and c.name not in parciales:
                errores.append(Error('Falta adaptar la restricción parcial '+c.name+' para MySQL.',id='mysql_nuevo.E002'))
    if databases and 'default' in databases:
        from django.db import connection
        if connection.vendor=='mysql' and (connection.mysql_is_mariadb or connection.mysql_version[:2]!=(8,4)):
            errores.append(Error('Este perfil está preparado para MySQL Community Server 8.4 LTS.',id='mysql_nuevo.E003'))
    return errores
