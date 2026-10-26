from importlib import import_module
from django.db import migrations, models


def agregar(apps, schema_editor):
    schema_editor.execute('ALTER TABLE ventas_detalleventa ADD COLUMN impuesto_normal bool NOT NULL DEFAULT 0')


def instalar(apps, schema_editor):
    # Recrea las reglas congeladas previas y amplía solo la validación de detalle.
    import_module('ventas.migrations._retencion_sql').instalar(apps,schema_editor)
    with schema_editor.connection.cursor() as c:
        c.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='ventas_detalle_validar'")
        sql=c.fetchone()[0]
    sql=sql.replace("(d.tipo_documento='FA' AND NEW.linea_original_id IS NULL", """(d.tipo_documento='FA' AND NEW.linea_original_id IS NULL
  AND NEW.impuesto_normal IN (0,1) AND NEW.impuesto_normal=1-NEW.retencion_impuesto""")
    viejo='AND ABS(NEW.monto_impuesto-(NEW.monto_servicio_bs-NEW.monto_descuento_bs-NEW.base_imponible_bs))<0.005'
    nuevo='''AND ABS(NEW.monto_impuesto-CASE WHEN NEW.impuesto_normal=1
     THEN ROUND((NEW.monto_servicio_bs-NEW.monto_descuento_bs)*d.impuesto/100.0,2)
     ELSE NEW.monto_servicio_bs-NEW.monto_descuento_bs-NEW.base_imponible_bs END)<0.005'''
    if viejo not in sql:
        raise RuntimeError('No se encontró la regla fiscal anterior.')
    sql=sql.replace(viejo,nuevo).replace('AND NEW.retencion_impuesto IS o.retencion_impuesto','AND NEW.impuesto_normal=o.impuesto_normal\n  AND NEW.retencion_impuesto IS o.retencion_impuesto')
    schema_editor.execute('DROP TRIGGER ventas_detalle_validar')
    schema_editor.execute(sql)


class Migration(migrations.Migration):
    dependencies=[('ventas','0007_retencion_por_servicio')]
    operations=[
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(agregar)],
            state_operations=[migrations.AddField('detalleventa','impuesto_normal',models.BooleanField(default=False,editable=False))],
        ),
        migrations.RunPython(instalar),
    ]
