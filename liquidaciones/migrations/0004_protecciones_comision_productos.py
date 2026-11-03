from importlib import import_module
from django.db import migrations

BASE = import_module('liquidaciones.migrations.0002_proteccion')
ORIGINAL = next(s for s in BASE.SQL if s.startswith('CREATE TRIGGER liq_sellar '))
SERVICIO = 'NOT EXISTS(SELECT 1 FROM liquidaciones_detalleliquidacion WHERE liquidacion_id=NEW.id_cancelacion AND ajuste_de_id IS NULL)'
SUMA = '(SELECT COALESCE(SUM(comision_usd),0) FROM liquidaciones_detalleliquidacion WHERE liquidacion_id=NEW.id_cancelacion)'
assert SERVICIO in ORIGINAL and SUMA in ORIGINAL
ACTUAL = ORIGINAL.replace(SERVICIO, '(' + SERVICIO + ' AND NOT EXISTS(SELECT 1 FROM liquidaciones_periodocomisionproductos p JOIN liquidaciones_comisionventaproducto v ON v.periodo_id=p.id WHERE p.liquidacion_id=NEW.id_cancelacion))')
ACTUAL = ACTUAL.replace(SUMA, '(' + SUMA + ' + (SELECT COALESCE(SUM(comision_usd),0) FROM liquidaciones_periodocomisionproductos WHERE liquidacion_id=NEW.id_cancelacion) + (SELECT COALESCE(SUM(monto_usd),0) FROM liquidaciones_reintegrocomisionproducto WHERE liquidacion_id=NEW.id_cancelacion))')
ACTUAL = ACTUAL.replace(' OR EXISTS(\n SELECT 1 FROM liquidaciones_detalleliquidacion p', ''' OR EXISTS(
 SELECT 1 FROM liquidaciones_periodocomisionproductos p WHERE p.liquidacion_id=NEW.id_cancelacion AND (
  ABS(p.unidades-(SELECT COALESCE(SUM(unidades),0) FROM liquidaciones_comisionventaproducto WHERE periodo_id=p.id))>0.005 OR
  ABS(p.base_usd-(SELECT COALESCE(SUM(base_usd),0) FROM liquidaciones_comisionventaproducto WHERE periodo_id=p.id))>0.005 OR
  ABS(p.comision_usd-(SELECT COALESCE(SUM(comision_usd),0) FROM liquidaciones_comisionventaproducto WHERE periodo_id=p.id))>0.005))
 OR EXISTS(
 SELECT 1 FROM liquidaciones_detalleliquidacion p''')
MARCADOR = ' OR EXISTS(\n SELECT 1 FROM liquidaciones_detalleliquidacion p'
ACTUAL = ACTUAL.replace(MARCADOR, ''' OR EXISTS(
 SELECT 1 FROM liquidaciones_comisionventaproducto c
 JOIN liquidaciones_periodocomisionproductos p ON p.id=c.periodo_id
 JOIN liquidaciones_liquidacion l ON l.id_cancelacion=p.liquidacion_id
 JOIN ventas_productos_documentoproducto r ON r.documento_original_id=c.venta_id
 WHERE p.prestador_id=NEW.prestador_id AND l.sellado=1 AND r.sellado=1 AND r.fecha<=NEW.fecha_cancelacion
 AND NOT EXISTS(SELECT 1 FROM liquidaciones_reintegrocomisionproducto a WHERE a.comision_id=c.id))
''' + MARCADOR)
ACTUAL = ACTUAL.replace(MARCADOR, ''' OR EXISTS(
 SELECT 1 FROM liquidaciones_periodocomisionproductos p JOIN ventas_productos_documentoproducto v ON v.prestador_id=p.prestador_id
 WHERE p.liquidacion_id=NEW.id_cancelacion AND v.tipo='VP' AND v.sellado=1 AND v.fecha BETWEEN p.desde AND p.hasta
 AND NOT EXISTS(SELECT 1 FROM ventas_productos_documentoproducto r WHERE r.documento_original_id=v.id AND r.sellado=1 AND r.fecha<=NEW.fecha_cancelacion)
 AND NOT EXISTS(SELECT 1 FROM liquidaciones_comisionventaproducto c WHERE c.periodo_id=p.id AND c.venta_id=v.id))
 OR EXISTS(SELECT 1 FROM liquidaciones_periodocomisionproductos p JOIN liquidaciones_comisionventaproducto c ON c.periodo_id=p.id
 JOIN ventas_productos_documentoproducto v ON v.id=c.venta_id WHERE p.liquidacion_id=NEW.id_cancelacion AND ABS(c.comision_usd-(
 ROUND((SELECT COALESCE(SUM(x.base_usd),0) FROM liquidaciones_comisionventaproducto x JOIN ventas_productos_documentoproducto a ON a.id=x.venta_id
 WHERE x.periodo_id=p.id AND (a.fecha<v.fecha OR (a.fecha=v.fecha AND a.id<=v.id)))*p.porcentaje/100,2)
 - ROUND((SELECT COALESCE(SUM(x.base_usd),0) FROM liquidaciones_comisionventaproducto x JOIN ventas_productos_documentoproducto a ON a.id=x.venta_id
 WHERE x.periodo_id=p.id AND (a.fecha<v.fecha OR (a.fecha=v.fecha AND a.id<v.id)))*p.porcentaje/100,2)))>0.005)
''' + MARCADOR)

INMUTABLES = [
 'liquidaciones_periodocomisionproductos', 'liquidaciones_comisionventaproducto',
 'liquidaciones_reintegrocomisionproducto',
]

VALIDACIONES = [
    """CREATE TRIGGER lcp_periodo_insert BEFORE INSERT ON liquidaciones_periodocomisionproductos
    WHEN NEW.desde>NEW.hasta OR NEW.unidades<=0 OR NEW.base_usd<0 OR NEW.porcentaje<0 OR NEW.porcentaje>100
    OR ABS(NEW.comision_usd-ROUND(NEW.base_usd*NEW.porcentaje/100,2))>0.005
    OR NOT EXISTS(SELECT 1 FROM liquidaciones_liquidacion l WHERE l.id_cancelacion=NEW.liquidacion_id AND l.sellado=0
    AND l.prestador_id=NEW.prestador_id AND l.periodo_desde=NEW.desde AND l.periodo_hasta=NEW.hasta)
    OR EXISTS(SELECT 1 FROM liquidaciones_periodocomisionproductos p JOIN liquidaciones_liquidacion l ON l.id_cancelacion=p.liquidacion_id
    WHERE l.sellado=1 AND p.prestador_id=NEW.prestador_id AND p.desde<=NEW.hasta AND p.hasta>=NEW.desde)
    BEGIN SELECT RAISE(ABORT,'Período de comisión inválido'); END""",
    """CREATE TRIGGER lcp_venta_insert BEFORE INSERT ON liquidaciones_comisionventaproducto
    WHEN NOT EXISTS(SELECT 1 FROM liquidaciones_periodocomisionproductos p JOIN liquidaciones_liquidacion l ON l.id_cancelacion=p.liquidacion_id
    JOIN ventas_productos_documentoproducto v ON v.id=NEW.venta_id WHERE p.id=NEW.periodo_id AND l.sellado=0 AND v.sellado=1
    AND v.tipo='VP' AND v.prestador_id=p.prestador_id AND v.fecha BETWEEN p.desde AND p.hasta AND NEW.unidades=v.unidades_total
    AND ABS(NEW.base_usd-(v.subtotal_usd-v.descuento_usd))<0.005 AND NEW.comision_usd>=0 AND NOT EXISTS(
    SELECT 1 FROM ventas_productos_documentoproducto r WHERE r.documento_original_id=v.id AND r.sellado=1 AND r.fecha<=l.fecha_cancelacion))
    BEGIN SELECT RAISE(ABORT,'Venta de comisión inválida'); END""",
    """CREATE TRIGGER lcp_reintegro_insert BEFORE INSERT ON liquidaciones_reintegrocomisionproducto
    WHEN NOT EXISTS(SELECT 1 FROM liquidaciones_liquidacion l JOIN liquidaciones_comisionventaproducto c ON c.id=NEW.comision_id
    JOIN liquidaciones_periodocomisionproductos p ON p.id=c.periodo_id JOIN liquidaciones_liquidacion anterior ON anterior.id_cancelacion=p.liquidacion_id
    JOIN ventas_productos_documentoproducto r ON r.id=NEW.reverso_id WHERE l.id_cancelacion=NEW.liquidacion_id AND l.sellado=0
    AND anterior.sellado=1 AND l.prestador_id=p.prestador_id AND r.sellado=1 AND r.tipo='RP'
    AND r.documento_original_id=c.venta_id AND r.fecha<=l.fecha_cancelacion AND ABS(NEW.monto_usd+c.comision_usd)<0.005)
    BEGIN SELECT RAISE(ABORT,'Reintegro de comisión inválido'); END""",
    """CREATE TRIGGER lcp_venta_periodo BEFORE UPDATE OF sellado ON ventas_productos_documentoproducto
    WHEN OLD.sellado=0 AND NEW.sellado=1 AND NEW.tipo='VP' AND NEW.prestador_id IS NOT NULL AND EXISTS(
    SELECT 1 FROM liquidaciones_periodocomisionproductos p JOIN liquidaciones_liquidacion l ON l.id_cancelacion=p.liquidacion_id
    WHERE p.prestador_id=NEW.prestador_id AND l.sellado=1 AND NEW.fecha BETWEEN p.desde AND p.hasta)
    BEGIN SELECT RAISE(ABORT,'Período de comisión ya liquidado'); END""",
    """CREATE TRIGGER lcp_reverso_prestador BEFORE UPDATE OF sellado ON ventas_productos_documentoproducto
    WHEN OLD.sellado=0 AND NEW.sellado=1 AND NEW.tipo='RP' AND NOT EXISTS(
    SELECT 1 FROM ventas_productos_documentoproducto o WHERE o.id=NEW.documento_original_id AND NEW.prestador_id IS o.prestador_id)
    BEGIN SELECT RAISE(ABORT,'Prestador del reverso inválido'); END""",
]

def instalar(apps, schema_editor):
    if schema_editor.connection.vendor != 'sqlite':
        return
    schema_editor.execute('DROP TRIGGER IF EXISTS liq_sellar')
    schema_editor.execute(ACTUAL)
    for sentencia in VALIDACIONES:
        schema_editor.execute(sentencia)
    for tabla in INMUTABLES:
        for accion in ('UPDATE', 'DELETE'):
            nombre = 'inmutable_' + tabla + '_' + accion.lower()
            schema_editor.execute(f"CREATE TRIGGER {nombre} BEFORE {accion} ON {tabla} BEGIN SELECT RAISE(ABORT,'Registro de comisión inmutable'); END")

def retirar(apps, schema_editor):
    if schema_editor.connection.vendor != 'sqlite':
        return
    for sentencia in VALIDACIONES:
        schema_editor.execute('DROP TRIGGER IF EXISTS ' + sentencia.split()[2])
    for tabla in INMUTABLES:
        for accion in ('UPDATE', 'DELETE'):
            schema_editor.execute('DROP TRIGGER IF EXISTS inmutable_' + tabla + '_' + accion.lower())
    schema_editor.execute('DROP TRIGGER IF EXISTS liq_sellar')
    schema_editor.execute(ORIGINAL)

class Migration(migrations.Migration):
    dependencies = [('liquidaciones', '0003_alter_liquidacion_id_cancelacion_and_more')]
    operations = [migrations.RunPython(instalar, retirar)]
