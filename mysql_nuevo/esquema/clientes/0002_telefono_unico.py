from django.db import migrations, models
from django.db.models import Count
from clientes.models import validar_telefono


def comprobar(apps, editor):
    clientes = apps.get_model("clientes", "Cliente").objects.using(editor.connection.alias)
    if clientes.values("telefono").annotate(n=Count("pk")).filter(n__gt=1).exists():
        raise RuntimeError("Hay teléfonos duplicados en Clientes. Corrígelos antes de activar el portal; no se eliminó ningún cliente.")


class Migration(migrations.Migration):
    dependencies = [("clientes", "0001_initial")]
    operations = [
        migrations.RunPython(comprobar, migrations.RunPython.noop),
        migrations.AlterField("cliente", "telefono", models.CharField(max_length=20, unique=True, validators=[validar_telefono])),
    ]
