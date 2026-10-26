"""Guarda el tratamiento fiscal por línea, sin alterar ventas anteriores."""
from importlib import import_module


def agregar(apps, schema_editor):
    schema_editor.execute('ALTER TABLE ventas_detalleventa ADD COLUMN retencion_impuesto bool NULL')


def instalar(apps, schema_editor):
    anterior = import_module('ventas.migrations._iva_incluido_sql')
    reglas = anterior.sentencias()
    import_module('ventas.migrations.0002_proteger_documentos').retirar(apps, schema_editor)
    for sql in reglas:
        if 'CREATE TRIGGER ventas_detalle_validar ' in sql:
            sql = sql.replace("(d.tipo_documento='FA' AND NEW.linea_original_id IS NULL", """(d.tipo_documento='FA' AND NEW.linea_original_id IS NULL
  AND NEW.retencion_impuesto IS NOT NULL AND NEW.retencion_impuesto IN (0,1)
  AND NEW.retencion_impuesto=(SELECT retencion_impuesto FROM servicios_servicio WHERE id=NEW.id_servicio)""")
            sql = sql.replace('(1.0+d.impuesto/100.0)', '(1.0+CASE WHEN NEW.retencion_impuesto=1 THEN d.impuesto ELSE 0 END/100.0)')
            sql = sql.replace('AND NEW.base_imponible_usd IS -o.base_imponible_usd', 'AND NEW.retencion_impuesto IS o.retencion_impuesto\n  AND NEW.base_imponible_usd IS -o.base_imponible_usd')
        schema_editor.execute(sql)
