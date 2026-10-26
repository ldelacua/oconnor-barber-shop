from importlib import import_module
from django.db import migrations, models
reglas = import_module('ventas.migrations._retencion_sql')


class Migration(migrations.Migration):
    dependencies = [('ventas','0006_iva_incluido'), ('servicios','0003_retencion_impuesto')]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(reglas.agregar)],
            state_operations=[migrations.AddField('detalleventa','retencion_impuesto',models.BooleanField(null=True,editable=False))],
        ),
        migrations.RunPython(reglas.instalar),
    ]
