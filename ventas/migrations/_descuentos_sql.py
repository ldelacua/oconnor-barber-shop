"""Reglas congeladas de ventas. Importe de servicio = base íntegra del prestador."""
import importlib


def sentencias():
    anterior = importlib.import_module('ventas.migrations.0003_barbero_detalle')
    pagos = importlib.import_module('ventas.migrations.0004_pagos_venta')
    sql = list(anterior.sentencias_nuevas())
    nuevos = []
    for s in sql:
        if 'CREATE TRIGGER ventas_doc_no_editar ' in s:
            s = s.replace('AND NEW.registrado_por IS OLD.registrado_por)',
                'AND NEW.registrado_por IS OLD.registrado_por AND NEW.descuento_porcentaje IS OLD.descuento_porcentaje AND NEW.descuento_usd IS OLD.descuento_usd AND NEW.descuento_bs IS OLD.descuento_bs)')
        elif 'CREATE TRIGGER ventas_doc_validar ' in s:
            s = s.replace('WHEN NEW.sellado != 0', 'WHEN NEW.descuento_porcentaje<0 OR NEW.descuento_porcentaje>100 OR NEW.sellado != 0')
            s = s.replace("NEW.tipo_documento = 'FA' AND", "NEW.tipo_documento = 'FA' AND NEW.descuento_usd>=0 AND NEW.descuento_bs>=0 AND")
            s = s.replace("NEW.tipo_documento = 'RE' AND", "NEW.tipo_documento = 'RE' AND NEW.descuento_usd<=0 AND NEW.descuento_bs<=0 AND")
            s = s.replace('AND o.total_bs = -NEW.total_bs)', 'AND o.total_bs = -NEW.total_bs AND o.descuento_porcentaje=NEW.descuento_porcentaje AND o.descuento_usd=-NEW.descuento_usd AND o.descuento_bs=-NEW.descuento_bs)')
        elif 'CREATE TRIGGER ventas_doc_sellar ' in s:
            s = s.replace('SUM(monto_servicio)', 'SUM(monto_servicio-monto_descuento_usd)').replace('SUM(monto_servicio_bs)', 'SUM(monto_servicio_bs-monto_descuento_bs)')
            condiciones = pagos.CONDICION_PAGOS.replace("NEW.tipo_documento='FA' AND NOT EXISTS", "NEW.tipo_documento='FA' AND NEW.total_bs>0 AND NOT EXISTS", 1)
            condiciones += '''
 OR ABS(NEW.descuento_usd-(SELECT COALESCE(SUM(monto_descuento_usd),0) FROM ventas_detalleventa WHERE id_documento=NEW.id_documento))>0.005
 OR ABS(NEW.descuento_bs-(SELECT COALESCE(SUM(monto_descuento_bs),0) FROM ventas_detalleventa WHERE id_documento=NEW.id_documento))>0.005
 OR (NEW.tipo_documento='RE' AND (SELECT COUNT(*) FROM ventas_detalleventa WHERE id_documento=NEW.id_documento)!=(SELECT COUNT(*) FROM ventas_detalleventa WHERE id_documento=NEW.documento_original_id))
'''
            s = s.replace('\n)\nBEGIN', condiciones + '\n)\nBEGIN')
        elif 'CREATE TRIGGER ventas_detalle_validar ' in s:
            s = DETALLE_SQL
        nuevos.append(s)
    return nuevos


DETALLE_SQL = """CREATE TRIGGER ventas_detalle_validar BEFORE INSERT ON ventas_detalleventa
WHEN NEW.cantidad_servicio<=0 OR NEW.precio_manual NOT IN (0,1) OR NOT EXISTS (
 SELECT 1 FROM ventas_documentoventa d WHERE d.id_documento=NEW.id_documento AND d.sellado=0 AND (
 (d.tipo_documento='FA' AND NEW.linea_original_id IS NULL
  AND NEW.barbero_id IS NOT NULL AND NEW.descripcion_barbero!=''
  AND NEW.precio_unitario_usd>=0 AND NEW.monto_servicio>=0 AND NEW.monto_servicio_bs>=0 AND NEW.monto_impuesto>=0
  AND NEW.monto_descuento_usd>=0 AND NEW.monto_descuento_bs>=0
  AND NEW.monto_descuento_usd<=NEW.monto_servicio AND NEW.monto_descuento_bs<=NEW.monto_servicio_bs
  AND EXISTS(SELECT 1 FROM servicios_servicio s WHERE s.id=NEW.id_servicio AND s.activo=1
   AND ((s.modo_precio='manual' AND NEW.precio_manual=1 AND NEW.precio_unitario_usd>0)
     OR (s.modo_precio='automatico' AND NEW.precio_manual=0 AND NEW.precio_unitario_usd=s.precio)))
  AND ABS(NEW.monto_servicio-ROUND(NEW.precio_unitario_usd*NEW.cantidad_servicio,2))<0.005
  AND ABS(NEW.monto_servicio_bs-ROUND(NEW.monto_servicio*d.tasa_bcv,2))<0.005
  AND ABS(NEW.monto_descuento_usd-ROUND(NEW.monto_servicio*d.descuento_porcentaje/100.0,2))<0.005
  AND ABS(NEW.monto_descuento_bs-(NEW.monto_servicio_bs-ROUND((NEW.monto_servicio-NEW.monto_descuento_usd)*d.tasa_bcv,2)))<0.005
  AND ABS(NEW.monto_impuesto-ROUND((NEW.monto_servicio_bs-NEW.monto_descuento_bs)*d.impuesto/100.0,2))<0.005)
 OR
 (d.tipo_documento='RE' AND EXISTS (
  SELECT 1 FROM ventas_detalleventa o WHERE o.id=NEW.linea_original_id AND o.id_documento=d.documento_original_id
  AND o.id_servicio=NEW.id_servicio AND o.barbero_id IS NEW.barbero_id AND o.descripcion_barbero=NEW.descripcion_barbero
  AND o.codigo_servicio=NEW.codigo_servicio AND o.descripcion_servicio=NEW.descripcion_servicio
  AND o.cantidad_servicio=NEW.cantidad_servicio AND o.precio_manual=NEW.precio_manual
  AND o.precio_unitario_usd=-NEW.precio_unitario_usd AND o.monto_servicio=-NEW.monto_servicio
  AND o.monto_servicio_bs=-NEW.monto_servicio_bs AND o.monto_impuesto=-NEW.monto_impuesto
  AND o.monto_descuento_usd=-NEW.monto_descuento_usd AND o.monto_descuento_bs=-NEW.monto_descuento_bs
 ))
 ))
BEGIN SELECT RAISE(ABORT,'Precio, descuento, impuesto o reverso de detalle invalido'); END"""


def instalar(apps, schema_editor):
    anteriores = importlib.import_module('ventas.migrations.0002_proteger_documentos')
    anteriores.retirar(apps, schema_editor)
    for sql in sentencias():
        schema_editor.execute(sql)


def retirar(apps, schema_editor):
    from django.db.migrations.exceptions import IrreversibleError
    with schema_editor.connection.cursor() as c:
        c.execute('SELECT EXISTS(SELECT 1 FROM ventas_documentoventa WHERE descuento_porcentaje!=0) OR EXISTS(SELECT 1 FROM ventas_detalleventa WHERE precio_manual=1)')
        if c.fetchone()[0]:
            raise IrreversibleError('Ya hay documentos con descuento o precio manual; no se puede retirar su estructura.')
    anteriores = importlib.import_module('ventas.migrations.0002_proteger_documentos')
    anteriores.retirar(apps, schema_editor)
    pagos = importlib.import_module('ventas.migrations.0004_pagos_venta')
    previos = importlib.import_module('ventas.migrations.0003_barbero_detalle')
    for sql in previos.sentencias_nuevas():
        if 'CREATE TRIGGER ventas_doc_sellar ' not in sql:
            schema_editor.execute(sql)
    sellar = pagos.sello_anterior().replace('\n)\nBEGIN', pagos.CONDICION_PAGOS+'\n)\nBEGIN')
    schema_editor.execute(sellar)
