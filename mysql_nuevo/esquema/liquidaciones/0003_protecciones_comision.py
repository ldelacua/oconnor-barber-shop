from django.db import migrations


def instalar(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    from mysql_nuevo.instalacion import definiciones
    from mysql_nuevo.protecciones_comisiones import sentencias
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SELECT trigger_name FROM information_schema.triggers WHERE trigger_schema=DATABASE()')
        existentes = {r[0] for r in cursor.fetchall()}
    if not existentes:
        return  # perfil sin disparadores
    faltan = set(definiciones()['triggers']) - existentes
    if faltan:
        raise RuntimeError('La instalación de disparadores está incompleta; no se actualizó: ' + ', '.join(sorted(faltan)))
    cambios = sentencias()
    for nombre, sql in cambios.items():
        schema_editor.execute('DROP TRIGGER IF EXISTS ' + schema_editor.quote_name(nombre))
        schema_editor.execute(sql)

class Migration(migrations.Migration):
    atomic = False
    dependencies = [('liquidaciones', '0002_periodocomisionproductos_comisionventaproducto_and_more'),
                    ('mysql_nuevo', '0002_protecciones')]
    operations = [migrations.RunPython(instalar)]
