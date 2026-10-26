import importlib
from django.db import migrations

VISTA="""
CREATE VIEW ci_movimientos AS
SELECT 'C-'||m.id AS id, dc.producto_id AS producto_id, c.fecha_compra AS fecha,
 'COMPRA' AS clase, m.cantidad AS delta, m.costo_unitario_usd AS costo_unitario_usd, m.creado_en AS registrado_en
 FROM inventario_movimientoinventario m JOIN inventario_detallecompra dc ON dc.id=m.detalle_id
 JOIN inventario_compra c ON c.id_compra=dc.compra_id WHERE c.estado='A'
UNION ALL
SELECT 'V-'||l.id,l.producto_id,v.fecha,CASE WHEN v.tipo='VP' THEN 'VENTA' ELSE 'REVERSO' END,
 CASE WHEN v.tipo='VP' THEN -l.cantidad ELSE l.cantidad END,NULL,v.creado_en
 FROM ventas_productos_lineaproducto l JOIN ventas_productos_documentoproducto v ON v.id=l.documento_id WHERE v.sellado=1
UNION ALL
SELECT 'A-'||d.id,d.producto_id,a.fecha,'OTRO',CASE WHEN a.tipo='EN' THEN d.cantidad ELSE -d.cantidad END,
 d.costo_unitario_usd,a.creado_en FROM control_inventario_detalleajuste d
 JOIN control_inventario_documentoajuste a ON a.id=d.documento_id WHERE a.sellado=1
"""

def periodo_bloqueado(fecha,cierre="NULL"):
    return f"""EXISTS(SELECT 1 FROM control_inventario_cierremensual c
    WHERE {fecha}<=date(c.periodo,'+1 month','-1 day')
    AND (c.estado='C' OR (c.estado='B' AND c.id<>COALESCE({cierre},-1))))"""

SQL={
"ci_compra_periodo":f"""
BEFORE UPDATE OF estado ON inventario_compra WHEN OLD.estado='B' AND NEW.estado='A'
AND {periodo_bloqueado('NEW.fecha_compra')}
BEGIN SELECT RAISE(ABORT,'Periodo cerrado o con conteo fisico'); END""",
"ci_venta_periodo":f"""
BEFORE UPDATE OF sellado ON ventas_productos_documentoproducto WHEN OLD.sellado=0 AND NEW.sellado=1
AND {periodo_bloqueado('NEW.fecha')}
BEGIN SELECT RAISE(ABORT,'Periodo cerrado o con conteo fisico'); END""",
"ci_ajuste_no_insertar_sellado":"""
BEFORE INSERT ON control_inventario_documentoajuste WHEN NEW.sellado<>0
BEGIN SELECT RAISE(ABORT,'El ajuste debe sellarse al terminar'); END""",
"ci_ajuste_no_editar":"""
BEFORE UPDATE ON control_inventario_documentoajuste WHEN OLD.sellado=1
BEGIN SELECT RAISE(ABORT,'El ajuste registrado no se modifica'); END""",
"ci_ajuste_no_eliminar":"""
BEFORE DELETE ON control_inventario_documentoajuste
BEGIN SELECT RAISE(ABORT,'El ajuste no se elimina'); END""",
"ci_ajuste_sellar":f"""
BEFORE UPDATE OF sellado ON control_inventario_documentoajuste WHEN OLD.sellado=0 AND NEW.sellado=1
BEGIN
 SELECT CASE WHEN {periodo_bloqueado('NEW.fecha','NEW.cierre_id')}
 THEN RAISE(ABORT,'Periodo cerrado o con conteo fisico') END;
 SELECT CASE WHEN LENGTH(TRIM(NEW.observacion))=0 OR NOT EXISTS(
 SELECT 1 FROM control_inventario_detalleajuste WHERE documento_id=NEW.id)
 THEN RAISE(ABORT,'El ajuste requiere motivo y productos') END;
 SELECT CASE WHEN NEW.cierre_id IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM control_inventario_cierremensual c WHERE c.id=NEW.cierre_id AND c.estado='B'
 AND NEW.fecha=date(c.periodo,'+1 month','-1 day'))
 THEN RAISE(ABORT,'El ajuste no corresponde al cierre abierto') END;
 SELECT CASE WHEN NEW.tipo='SA' AND EXISTS(
 SELECT 1 FROM control_inventario_detalleajuste d WHERE d.documento_id=NEW.id
 AND ROUND(d.cantidad,3)>ROUND(COALESCE((SELECT SUM(delta) FROM ci_movimientos WHERE producto_id=d.producto_id),0),3))
 THEN RAISE(ABORT,'Existencias insuficientes para la salida') END;
END""",
"ci_detalle_no_agregar":"""
BEFORE INSERT ON control_inventario_detalleajuste WHEN EXISTS(
SELECT 1 FROM control_inventario_documentoajuste WHERE id=NEW.documento_id AND sellado=1)
BEGIN SELECT RAISE(ABORT,'El ajuste esta bloqueado'); END""",
"ci_detalle_no_editar":"""
BEFORE UPDATE ON control_inventario_detalleajuste
BEGIN SELECT RAISE(ABORT,'El detalle no se modifica'); END""",
"ci_detalle_no_eliminar":"""
BEFORE DELETE ON control_inventario_detalleajuste
BEGIN SELECT RAISE(ABORT,'El detalle no se elimina'); END""",
"ci_cierre_crear":"""
BEFORE INSERT ON control_inventario_cierremensual
BEGIN
 SELECT CASE WHEN NEW.estado<>'B' OR strftime('%d',NEW.periodo)<>'01'
 THEN RAISE(ABORT,'Periodo de cierre invalido') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM control_inventario_cierremensual WHERE estado='C')
 AND NEW.periodo<>date((SELECT MAX(periodo) FROM control_inventario_cierremensual WHERE estado='C'),'+1 month')
 THEN RAISE(ABORT,'Los cierres deben ser consecutivos') END;
END""",
"ci_cierre_periodo_fijo":"""
BEFORE UPDATE ON control_inventario_cierremensual
WHEN NEW.periodo<>OLD.periodo OR NEW.iniciado_por<>OLD.iniciado_por OR NEW.creado_en<>OLD.creado_en
OR NEW.estado NOT IN ('B','C')
BEGIN SELECT RAISE(ABORT,'El periodo y origen del conteo no se modifican'); END""",
"ci_cierre_inmutable":"""
BEFORE UPDATE ON control_inventario_cierremensual WHEN OLD.estado='C'
BEGIN SELECT RAISE(ABORT,'El cierre historico no se modifica'); END""",
"ci_cierre_no_eliminar":"""
BEFORE DELETE ON control_inventario_cierremensual WHEN OLD.estado='C'
BEGIN SELECT RAISE(ABORT,'El cierre historico no se elimina'); END""",
"ci_cierre_confirmar":"""
BEFORE UPDATE OF estado ON control_inventario_cierremensual WHEN OLD.estado='B' AND NEW.estado='C'
BEGIN
 SELECT CASE WHEN NEW.cerrado_en IS NULL OR NEW.cerrado_por='' OR
 NOT EXISTS(SELECT 1 FROM control_inventario_detallecierre WHERE cierre_id=NEW.id) OR EXISTS(
 SELECT 1 FROM control_inventario_detallecierre WHERE cierre_id=NEW.id AND fisico IS NULL)
 THEN RAISE(ABORT,'Falta completar el conteo fisico') END;
 SELECT CASE WHEN EXISTS(
 SELECT 1 FROM control_inventario_detallecierre d WHERE d.cierre_id=NEW.id AND
 ABS(ROUND(d.fisico-d.teorico,3)-ROUND(COALESCE((
 SELECT SUM(CASE WHEN a.tipo='EN' THEN l.cantidad ELSE -l.cantidad END)
 FROM control_inventario_detalleajuste l JOIN control_inventario_documentoajuste a ON a.id=l.documento_id
 WHERE a.cierre_id=NEW.id AND a.sellado=1 AND l.producto_id=d.producto_id),0),3))>0.0005)
 THEN RAISE(ABORT,'Los ajustes no coinciden con el conteo fisico') END;
END""",
"ci_snapshot_no_agregar":"""
BEFORE INSERT ON control_inventario_detallecierre WHEN EXISTS(
SELECT 1 FROM control_inventario_cierremensual WHERE id=NEW.cierre_id AND estado='C')
BEGIN SELECT RAISE(ABORT,'El cierre historico no admite productos'); END""",
"ci_snapshot_actualizar":"""
BEFORE UPDATE ON control_inventario_detallecierre
WHEN EXISTS(SELECT 1 FROM control_inventario_cierremensual WHERE id=OLD.cierre_id AND estado='C')
OR NEW.cierre_id<>OLD.cierre_id OR NEW.producto_id<>OLD.producto_id OR NEW.codigo<>OLD.codigo
OR NEW.descripcion<>OLD.descripcion OR NEW.inicial<>OLD.inicial OR NEW.compras<>OLD.compras
OR NEW.ventas<>OLD.ventas OR NEW.otros<>OLD.otros OR NEW.teorico<>OLD.teorico
OR NEW.costo_unitario_usd<>OLD.costo_unitario_usd
BEGIN SELECT RAISE(ABORT,'La fotografia del cierre esta bloqueada'); END""",
"ci_snapshot_no_eliminar":"""
BEFORE DELETE ON control_inventario_detallecierre WHEN EXISTS(
SELECT 1 FROM control_inventario_cierremensual WHERE id=OLD.cierre_id AND estado='C')
BEGIN SELECT RAISE(ABORT,'El cierre historico no se elimina'); END""",
}

def stock_sello_original():
    return importlib.import_module("ventas_productos.migrations.0002_protecciones").SQL["vp_validar_sello"]

def instalar(apps,schema_editor):
    if schema_editor.connection.vendor!="sqlite":raise RuntimeError("Control de inventario requiere SQLite.")
    schema_editor.execute(VISTA)
    original=stock_sello_original()
    comienzo=original.index(" AND ROUND(n.cantidad,3)>ROUND(")
    fin=original.index(" ) THEN RAISE(ABORT, 'Existencias insuficientes')",comienzo)
    nuevo=original[:comienzo]+""" AND ROUND(n.cantidad,3)>ROUND(
 COALESCE((SELECT SUM(delta) FROM ci_movimientos WHERE producto_id=n.producto_id),0),3)
"""+original[fin:]
    schema_editor.execute("DROP TRIGGER vp_validar_sello")
    schema_editor.execute("CREATE TRIGGER vp_validar_sello "+nuevo)
    for nombre,sql in SQL.items():schema_editor.execute(f"CREATE TRIGGER {nombre} {sql}")

def quitar(apps,schema_editor):
    for nombre in reversed(SQL):schema_editor.execute(f"DROP TRIGGER IF EXISTS {nombre}")
    schema_editor.execute("DROP TRIGGER vp_validar_sello")
    schema_editor.execute("CREATE TRIGGER vp_validar_sello "+stock_sello_original())
    schema_editor.execute("DROP VIEW ci_movimientos")

class Migration(migrations.Migration):
    dependencies=[("control_inventario","0001_initial"),("ventas_productos","0002_protecciones")]
    operations=[migrations.RunPython(instalar,quitar)]
