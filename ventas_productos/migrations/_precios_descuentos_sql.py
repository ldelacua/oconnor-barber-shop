import importlib

COLUMNAS={
 "documentoproducto":{
  "descuento_bs":"decimal NOT NULL DEFAULT 0","descuento_nivel":"smallint NULL",
  "descuento_porcentaje":"decimal NOT NULL DEFAULT 0","descuento_usd":"decimal NOT NULL DEFAULT 0",
  "precio_automatico":"bool NOT NULL DEFAULT 0","umbral_descuento":"decimal NULL",
  "unidades_total":"decimal NOT NULL DEFAULT 0",
 },
 "lineaproducto":{
  "costo_unitario_usd":"decimal NULL","descuento_bs":"decimal NOT NULL DEFAULT 0",
  "descuento_usd":"decimal NOT NULL DEFAULT 0","porcentaje_venta":"decimal NULL",
 },
}
def agregar_columnas(apps,schema_editor):
    if schema_editor.connection.vendor!="sqlite":raise RuntimeError("Esta migración requiere SQLite.")
    for tabla,columnas in COLUMNAS.items():
        nombre="ventas_productos_"+tabla
        with schema_editor.connection.cursor() as c:
            existentes={r[1] for r in c.execute(f"PRAGMA table_info({nombre})").fetchall()}
        for columna,tipo in columnas.items():
            if columna not in existentes:schema_editor.execute(f"ALTER TABLE {nombre} ADD COLUMN {columna} {tipo}")

def base_ledger():
    modulo=importlib.import_module("control_inventario.migrations.0002_ledger_y_protecciones")
    sql=modulo.stock_sello_original()
    inicio=sql.index(" AND ROUND(n.cantidad,3)>ROUND(")
    fin=sql.index(" ) THEN RAISE(ABORT, 'Existencias insuficientes')",inicio)
    return sql[:inicio]+""" AND ROUND(n.cantidad,3)>ROUND(
 COALESCE((SELECT SUM(delta) FROM ci_movimientos WHERE producto_id=n.producto_id),0),3)
"""+sql[fin:]

def proteger(apps,schema_editor):
    sql=base_ledger()
    sql=sql.replace(
      "SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM ventas_productos_pagoproducto WHERE documento_id=OLD.id)",
      "SELECT CASE WHEN NEW.total_bs<>0 AND NOT EXISTS (SELECT 1 FROM ventas_productos_pagoproducto WHERE documento_id=OLD.id)")
    sql=sql.replace("NEW.subtotal_bs+NEW.impuesto_bs","NEW.subtotal_bs-NEW.descuento_bs+NEW.impuesto_bs")
    sql=sql.replace("NEW.total_bs<=0","NEW.total_bs<0")
    extra="""
 SELECT CASE WHEN NEW.total_bs=0 AND EXISTS(SELECT 1 FROM ventas_productos_pagoproducto WHERE documento_id=NEW.id)
 THEN RAISE(ABORT,'Un total cero no admite pagos') END;
 SELECT CASE WHEN ABS(NEW.descuento_usd-ROUND(COALESCE((SELECT SUM(descuento_usd) FROM ventas_productos_lineaproducto WHERE documento_id=NEW.id),0),2))>0.005
 OR ABS(NEW.descuento_bs-ROUND(COALESCE((SELECT SUM(descuento_bs) FROM ventas_productos_lineaproducto WHERE documento_id=NEW.id),0),2))>0.005
 THEN RAISE(ABORT,'El descuento no coincide con sus renglones') END;
 SELECT CASE WHEN NEW.tipo='VP' AND (NEW.precio_automatico<>1 OR EXISTS(
 SELECT 1 FROM ventas_productos_lineaproducto WHERE documento_id=NEW.id AND
 (costo_unitario_usd IS NULL OR porcentaje_venta IS NULL OR costo_unitario_usd<=0 OR porcentaje_venta<0)))
 THEN RAISE(ABORT,'La venta requiere precios automaticos y su costo historico') END;
 SELECT CASE WHEN NEW.tipo='VP' AND ABS(NEW.unidades_total-ROUND(COALESCE((SELECT SUM(cantidad)
 FROM ventas_productos_lineaproducto WHERE documento_id=NEW.id),0),2))>0.005
 THEN RAISE(ABORT,'El total de unidades no coincide') END;
 SELECT CASE WHEN NEW.tipo='VP' AND (
 NEW.descuento_porcentaje<0 OR NEW.descuento_porcentaje>100 OR NEW.descuento_usd<0 OR NEW.descuento_usd>NEW.subtotal_usd
 OR NEW.descuento_bs<0 OR NEW.descuento_bs>NEW.subtotal_bs
 OR EXISTS(SELECT 1 FROM ventas_productos_lineaproducto WHERE documento_id=NEW.id AND
 (descuento_usd<0 OR descuento_usd>subtotal_usd OR descuento_bs<0 OR descuento_bs>subtotal_bs)))
 THEN RAISE(ABORT,'El descuento de la venta no es valido') END;
 SELECT CASE WHEN NEW.tipo='RP' AND NOT EXISTS(
 SELECT 1 FROM ventas_productos_documentoproducto o WHERE o.id=NEW.documento_original_id
 AND NEW.descuento_porcentaje=o.descuento_porcentaje AND NEW.descuento_usd=-o.descuento_usd
 AND NEW.descuento_bs=-o.descuento_bs AND NEW.unidades_total=o.unidades_total
 AND NEW.descuento_nivel IS o.descuento_nivel AND NEW.umbral_descuento IS o.umbral_descuento)
 THEN RAISE(ABORT,'El reverso debe conservar los descuentos originales') END;
 SELECT CASE WHEN NEW.tipo='RP' AND EXISTS(
 SELECT 1 FROM ventas_productos_lineaproducto l JOIN ventas_productos_lineaproducto o ON o.id=l.linea_original_id
 WHERE l.documento_id=NEW.id AND (l.descuento_usd<>-o.descuento_usd OR l.descuento_bs<>-o.descuento_bs
 OR l.costo_unitario_usd IS NOT o.costo_unitario_usd OR l.porcentaje_venta IS NOT o.porcentaje_venta))
 THEN RAISE(ABORT,'El reverso no conserva sus precios originales') END;
"""
    sql=sql[:sql.rfind("END")]+extra+sql[sql.rfind("END"):]
    schema_editor.execute("DROP TRIGGER vp_validar_sello")
    schema_editor.execute("CREATE TRIGGER vp_validar_sello "+sql)

def restaurar(apps,schema_editor):
    schema_editor.execute("DROP TRIGGER vp_validar_sello")
    schema_editor.execute("CREATE TRIGGER vp_validar_sello "+base_ledger())
