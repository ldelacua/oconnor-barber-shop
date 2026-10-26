"""Desglose de IVA incluido; mantiene valores y reglas de documentos anteriores."""
from importlib import import_module


def agregar_columnas(apps, schema_editor):
    if schema_editor.connection.vendor != 'sqlite':
        raise RuntimeError('Esta protección de Ventas requiere SQLite.')
    # ADD COLUMN evita reconstruir tablas referenciadas por disparadores de liquidaciones.
    schema_editor.execute('ALTER TABLE ventas_documentoventa ADD COLUMN iva_incluido bool NOT NULL DEFAULT 0')
    schema_editor.execute('ALTER TABLE ventas_detalleventa ADD COLUMN base_imponible_usd decimal NULL')
    schema_editor.execute('ALTER TABLE ventas_detalleventa ADD COLUMN base_imponible_bs decimal NULL')


def sentencias():
    reglas = import_module('ventas.migrations._descuentos_sql')
    resultado = []
    for sql in reglas.sentencias():
        if 'CREATE TRIGGER ventas_doc_no_editar ' in sql:
            sql = sql.replace('AND NEW.registrado_por IS OLD.registrado_por',
                              'AND NEW.iva_incluido IS OLD.iva_incluido AND NEW.registrado_por IS OLD.registrado_por')
        elif 'CREATE TRIGGER ventas_doc_validar ' in sql:
            sql = sql.replace('WHEN NEW.descuento_porcentaje<0', 'WHEN NEW.iva_incluido NOT IN (0,1) OR NEW.descuento_porcentaje<0')
            sql = sql.replace("NEW.tipo_documento = 'FA' AND", "NEW.tipo_documento = 'FA' AND NEW.iva_incluido=1 AND")
            sql = sql.replace('AND o.cliente_id = NEW.cliente_id', 'AND o.iva_incluido=NEW.iva_incluido AND o.cliente_id = NEW.cliente_id')
        elif 'CREATE TRIGGER ventas_doc_sellar ' in sql:
            sql = sql.replace('SUM(monto_servicio-monto_descuento_usd)', 'SUM(CASE WHEN NEW.iva_incluido=1 THEN base_imponible_usd ELSE monto_servicio-monto_descuento_usd END)')
            sql = sql.replace('SUM(monto_servicio_bs-monto_descuento_bs)', 'SUM(CASE WHEN NEW.iva_incluido=1 THEN base_imponible_bs ELSE monto_servicio_bs-monto_descuento_bs END)')
        elif 'CREATE TRIGGER ventas_detalle_validar ' in sql:
            anterior = 'AND ABS(NEW.monto_impuesto-ROUND((NEW.monto_servicio_bs-NEW.monto_descuento_bs)*d.impuesto/100.0,2))<0.005'
            nuevo = '''AND (
   (d.iva_incluido=0 AND NEW.base_imponible_usd IS NULL AND NEW.base_imponible_bs IS NULL
    AND ABS(NEW.monto_impuesto-ROUND((NEW.monto_servicio_bs-NEW.monto_descuento_bs)*d.impuesto/100.0,2))<0.005)
   OR (d.iva_incluido=1 AND NEW.base_imponible_usd IS NOT NULL AND NEW.base_imponible_bs IS NOT NULL
    AND NEW.base_imponible_usd>=0 AND NEW.base_imponible_bs>=0
    AND ABS(NEW.base_imponible_usd-ROUND((NEW.monto_servicio-NEW.monto_descuento_usd)/(1.0+d.impuesto/100.0),2))<0.005
    AND ABS(NEW.base_imponible_bs-ROUND((NEW.monto_servicio_bs-NEW.monto_descuento_bs)/(1.0+d.impuesto/100.0),2))<0.005
    AND ABS(NEW.monto_impuesto-(NEW.monto_servicio_bs-NEW.monto_descuento_bs-NEW.base_imponible_bs))<0.005)
  )'''
            if anterior not in sql:
                raise RuntimeError('No se encontró la regla de impuesto anterior.')
            sql = sql.replace(anterior, nuevo)
            sql = sql.replace('AND o.monto_descuento_usd=-NEW.monto_descuento_usd', '''AND NEW.base_imponible_usd IS -o.base_imponible_usd
  AND NEW.base_imponible_bs IS -o.base_imponible_bs
  AND o.monto_descuento_usd=-NEW.monto_descuento_usd''')
        resultado.append(sql)
    return resultado


def instalar(apps, schema_editor):
    import_module('ventas.migrations.0002_proteger_documentos').retirar(apps, schema_editor)
    for sql in sentencias():
        schema_editor.execute(sql)
