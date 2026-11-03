def instalar(apps, schema_editor):
    alias = schema_editor.connection.alias
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    tipo, _ = ContentType.objects.using(alias).get_or_create(app_label='inventario', model='pagoproveedor')
    permisos = []
    for accion in ('view', 'add', 'change', 'delete'):
        permiso, _ = Permission.objects.using(alias).get_or_create(content_type=tipo,
            codename=accion + '_pagoproveedor', defaults={'name': accion.title() + ' pago a proveedor'})
        permisos.append(permiso)
    for grupo in Group.objects.using(alias).filter(name__in=['ADMINISTRADOR', 'ENCARGADO']):
        grupo.permissions.add(*permisos)
