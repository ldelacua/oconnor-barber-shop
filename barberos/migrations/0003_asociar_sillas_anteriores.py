from django.db import migrations


def asociar_sillas(apps, schema_editor):
    Silla = apps.get_model("horarios", "Silla")
    Barbero = apps.get_model("barberos", "Barbero")
    alias = schema_editor.connection.alias
    coincidencias = {}
    for silla in Silla.objects.using(alias).all():
        clave = silla.nombre.strip().casefold()
        coincidencias.setdefault(clave, []).append(silla.pk)
    for prestador in Barbero.objects.using(alias).filter(silla__isnull=True):
        clave = (prestador.codigo_silla or "").strip().casefold()
        ids = coincidencias.get(clave, [])
        if clave and len(ids) == 1:
            Barbero.objects.using(alias).filter(pk=prestador.pk).update(silla_id=ids[0])


class Migration(migrations.Migration):
    dependencies = [("barberos", "0002_silla_prestador")]
    operations = [migrations.RunPython(asociar_sillas, migrations.RunPython.noop)]
