from django.db import migrations


def instalar(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    from mysql_nuevo.instalacion import definiciones
    from mysql_nuevo.protecciones_pagos import sentencias
    with schema_editor.connection.cursor() as c:
        c.execute('SELECT trigger_name FROM information_schema.triggers WHERE trigger_schema=DATABASE()')
        actuales = {r[0] for r in c.fetchall()}
    if not actuales:
        return
    if set(definiciones()['triggers']) - actuales:
        raise RuntimeError('Faltan protecciones de la instalación original; no se agregaron disparadores de pagos.')
    for nombre, sql in sentencias().items():
        schema_editor.execute('DROP TRIGGER IF EXISTS ' + schema_editor.quote_name(nombre))
        schema_editor.execute(sql)

class Migration(migrations.Migration):
    atomic = False
    dependencies = [('inventario', '0002_pagoproveedor'), ('mysql_nuevo', '0002_protecciones')]
    operations = [migrations.RunPython(instalar)]
