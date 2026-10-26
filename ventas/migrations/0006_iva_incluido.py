from importlib import import_module
from django.db import migrations, models

reglas = import_module('ventas.migrations._iva_incluido_sql')


class Migration(migrations.Migration):
    dependencies = [('ventas', '0005_precios_descuentos')]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(reglas.agregar_columnas)],
            state_operations=[
                migrations.AddField('documentoventa', 'iva_incluido', models.BooleanField(default=True, editable=False)),
                migrations.AddField('detalleventa', 'base_imponible_usd', models.DecimalField(max_digits=18, decimal_places=2, null=True, editable=False)),
                migrations.AddField('detalleventa', 'base_imponible_bs', models.DecimalField(max_digits=18, decimal_places=2, null=True, editable=False)),
            ],
        ),
        migrations.RunPython(reglas.instalar),
    ]
