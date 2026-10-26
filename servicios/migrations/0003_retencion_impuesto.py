from django.db import migrations, models


def agregar(apps, schema_editor):
    # Conserva el desglose de los servicios existentes; los nuevos nacen sin marcar.
    schema_editor.execute('ALTER TABLE servicios_servicio ADD COLUMN retencion_impuesto bool NOT NULL DEFAULT 1')


class Migration(migrations.Migration):
    dependencies = [('servicios', '0002_precios_descuentos')]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(agregar)],
        state_operations=[migrations.AddField('servicio', 'retencion_impuesto', models.BooleanField(default=False, verbose_name='Retención de impuesto'))],
    )]
