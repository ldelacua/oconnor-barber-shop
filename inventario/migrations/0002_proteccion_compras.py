from django.db import migrations

DISPARADORES = {
"inv_compra_no_editar": """
BEFORE UPDATE ON inventario_compra WHEN OLD.estado = 'A'
BEGIN SELECT RAISE(ABORT, 'La compra actualizada no se modifica'); END""",
"inv_compra_no_eliminar": """
BEFORE DELETE ON inventario_compra WHEN OLD.estado = 'A'
BEGIN SELECT RAISE(ABORT, 'La compra actualizada no se elimina'); END""",
"inv_compra_validar_actualizacion": """
BEFORE UPDATE OF estado ON inventario_compra WHEN NEW.estado = 'A'
BEGIN
 SELECT CASE WHEN NEW.actualizada_en IS NULL OR NEW.actualizada_por = ''
 THEN RAISE(ABORT, 'Falta auditoria de actualizacion') END;
 SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM inventario_detallecompra WHERE compra_id = OLD.id_compra)
 THEN RAISE(ABORT, 'La compra requiere productos') END;
 SELECT CASE WHEN EXISTS (
 SELECT 1 FROM inventario_detallecompra d
 LEFT JOIN inventario_movimientoinventario m ON m.detalle_id = d.id
 WHERE d.compra_id = OLD.id_compra AND (m.id IS NULL OR m.cantidad <> d.cantidad))
 THEN RAISE(ABORT, 'Las entradas de inventario no coinciden con la compra') END;
END""",
"inv_compra_no_insertar_actualizada": """
BEFORE INSERT ON inventario_compra WHEN NEW.estado <> 'B'
BEGIN SELECT RAISE(ABORT, 'La compra debe comenzar como borrador'); END""",
"inv_detalle_no_insertar": """
BEFORE INSERT ON inventario_detallecompra
WHEN EXISTS (SELECT 1 FROM inventario_compra WHERE id_compra = NEW.compra_id AND estado = 'A')
BEGIN SELECT RAISE(ABORT, 'La compra actualizada no admite detalles'); END""",
"inv_detalle_no_editar": """
BEFORE UPDATE ON inventario_detallecompra
WHEN EXISTS (SELECT 1 FROM inventario_compra WHERE id_compra IN (OLD.compra_id, NEW.compra_id) AND estado = 'A')
 OR EXISTS (SELECT 1 FROM inventario_movimientoinventario WHERE detalle_id = OLD.id)
BEGIN SELECT RAISE(ABORT, 'El detalle de inventario esta bloqueado'); END""",
"inv_detalle_no_eliminar": """
BEFORE DELETE ON inventario_detallecompra
WHEN EXISTS (SELECT 1 FROM inventario_compra WHERE id_compra = OLD.compra_id AND estado = 'A')
 OR EXISTS (SELECT 1 FROM inventario_movimientoinventario WHERE detalle_id = OLD.id)
BEGIN SELECT RAISE(ABORT, 'El detalle de inventario esta bloqueado'); END""",
"inv_movimiento_validar": """
BEFORE INSERT ON inventario_movimientoinventario
WHEN NOT EXISTS (
 SELECT 1 FROM inventario_detallecompra d JOIN inventario_compra c ON c.id_compra = d.compra_id
 WHERE d.id = NEW.detalle_id AND c.estado = 'B' AND d.cantidad = NEW.cantidad)
BEGIN SELECT RAISE(ABORT, 'Entrada de inventario invalida'); END""",
"inv_movimiento_no_editar": """
BEFORE UPDATE ON inventario_movimientoinventario
BEGIN SELECT RAISE(ABORT, 'Los movimientos no se modifican'); END""",
"inv_movimiento_no_eliminar": """
BEFORE DELETE ON inventario_movimientoinventario
BEGIN SELECT RAISE(ABORT, 'Los movimientos no se eliminan'); END""",
}

def instalar(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        raise RuntimeError("Estas protecciones de inventario están preparadas para SQLite.")
    for nombre, sql in DISPARADORES.items():
        schema_editor.execute(f"CREATE TRIGGER {nombre} {sql}")

def quitar(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        for nombre in reversed(DISPARADORES):
            schema_editor.execute(f"DROP TRIGGER IF EXISTS {nombre}")

class Migration(migrations.Migration):
    dependencies = [("inventario", "0001_initial")]
    operations = [migrations.RunPython(instalar, quitar)]
