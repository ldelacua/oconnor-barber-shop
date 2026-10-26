from django.db import migrations

SQL = {
"vp_cabecera_no_insertar_sellada": """
BEFORE INSERT ON ventas_productos_documentoproducto WHEN NEW.sellado <> 0
BEGIN SELECT RAISE(ABORT, 'El documento debe sellarse al terminar'); END""",
"vp_cabecera_no_editar": """
BEFORE UPDATE ON ventas_productos_documentoproducto WHEN OLD.sellado = 1
BEGIN SELECT RAISE(ABORT, 'El documento guardado no se modifica'); END""",
"vp_cabecera_no_eliminar": """
BEFORE DELETE ON ventas_productos_documentoproducto
BEGIN SELECT RAISE(ABORT, 'Los documentos no se eliminan'); END""",
"vp_validar_sello": """
BEFORE UPDATE OF sellado ON ventas_productos_documentoproducto WHEN NEW.sellado = 1 AND OLD.sellado = 0
BEGIN
 SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id)
 THEN RAISE(ABORT, 'La venta necesita productos') END;
 SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM ventas_productos_pagoproducto WHERE documento_id=OLD.id)
 THEN RAISE(ABORT, 'La venta necesita pagos') END;
 SELECT CASE WHEN ABS(ROUND(COALESCE((SELECT SUM(subtotal_usd) FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id),0),2)-NEW.subtotal_usd)>0.005
 OR ABS(ROUND(COALESCE((SELECT SUM(subtotal_bs) FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id),0),2)-NEW.subtotal_bs)>0.005
 OR ABS(ROUND(COALESCE((SELECT SUM(impuesto_bs) FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id),0),2)-NEW.impuesto_bs)>0.005
 OR ABS(NEW.total_bs-ROUND(NEW.subtotal_bs+NEW.impuesto_bs,2))>0.005
 THEN RAISE(ABORT, 'Los importes no coinciden con los detalles') END;
 SELECT CASE WHEN ABS(ROUND(COALESCE((SELECT SUM(equivalente_bs+ajuste_redondeo_bs) FROM ventas_productos_pagoproducto WHERE documento_id=OLD.id),0),2)-NEW.total_bs)>0.005
 THEN RAISE(ABORT, 'Los pagos no cubren el documento') END;
 SELECT CASE WHEN NEW.tipo='VP' AND (
 NEW.documento_original_id IS NOT NULL OR NEW.total_bs<=0
 OR EXISTS(SELECT 1 FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id AND (linea_original_id IS NOT NULL OR subtotal_usd<=0 OR subtotal_bs<0 OR impuesto_bs<0))
 OR EXISTS(SELECT 1 FROM ventas_productos_pagoproducto WHERE documento_id=OLD.id AND (pago_original_id IS NOT NULL OR monto<=0))
 ) THEN RAISE(ABORT, 'La venta de productos es invalida') END;
 SELECT CASE WHEN NEW.tipo='VP' AND EXISTS(
 SELECT 1 FROM ventas_productos_lineaproducto n WHERE n.documento_id=OLD.id
 AND ROUND(n.cantidad,3)>ROUND(
  COALESCE((SELECT SUM(m.cantidad) FROM inventario_movimientoinventario m
  JOIN inventario_detallecompra dc ON dc.id=m.detalle_id JOIN inventario_compra c ON c.id_compra=dc.compra_id
  WHERE dc.producto_id=n.producto_id AND c.estado='A'),0)
  -COALESCE((SELECT SUM(CASE WHEN v.tipo='RP' THEN -l.cantidad ELSE l.cantidad END)
   FROM ventas_productos_lineaproducto l JOIN ventas_productos_documentoproducto v ON v.id=l.documento_id
   WHERE l.producto_id=n.producto_id AND v.sellado=1),0),3)
 ) THEN RAISE(ABORT, 'Existencias insuficientes') END;
 SELECT CASE WHEN NEW.tipo='RP' AND NOT EXISTS(
 SELECT 1 FROM ventas_productos_documentoproducto o WHERE o.id=NEW.documento_original_id
 AND o.tipo='VP' AND o.sellado=1 AND NEW.cliente_id=o.cliente_id AND NEW.tasa_bcv=o.tasa_bcv
 AND NEW.iva=o.iva AND NEW.subtotal_usd=-o.subtotal_usd AND NEW.subtotal_bs=-o.subtotal_bs
 AND NEW.impuesto_bs=-o.impuesto_bs AND NEW.total_bs=-o.total_bs AND LENGTH(TRIM(NEW.motivo))>0
 ) THEN RAISE(ABORT, 'El reverso no corresponde con la venta original') END;
 SELECT CASE WHEN NEW.tipo='RP' AND (
 (SELECT COUNT(*) FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id)
 <> (SELECT COUNT(*) FROM ventas_productos_lineaproducto WHERE documento_id=NEW.documento_original_id)
 OR EXISTS(SELECT 1 FROM ventas_productos_lineaproducto l LEFT JOIN ventas_productos_lineaproducto o ON o.id=l.linea_original_id
 WHERE l.documento_id=OLD.id AND (o.id IS NULL OR o.documento_id<>NEW.documento_original_id
 OR l.producto_id<>o.producto_id OR l.cantidad<>o.cantidad OR l.precio_unitario_usd<>o.precio_unitario_usd
 OR l.subtotal_usd<>-o.subtotal_usd OR l.subtotal_bs<>-o.subtotal_bs OR l.impuesto_bs<>-o.impuesto_bs))
 ) THEN RAISE(ABORT, 'El reverso debe reponer los productos originales completos') END;
 SELECT CASE WHEN NEW.tipo='RP' AND (
 (SELECT COUNT(*) FROM ventas_productos_pagoproducto WHERE documento_id=OLD.id)
 <> (SELECT COUNT(*) FROM ventas_productos_pagoproducto WHERE documento_id=NEW.documento_original_id)
 OR EXISTS(SELECT 1 FROM ventas_productos_pagoproducto p LEFT JOIN ventas_productos_pagoproducto o ON o.id=p.pago_original_id
 WHERE p.documento_id=OLD.id AND (o.id IS NULL OR o.documento_id<>NEW.documento_original_id
 OR p.tipo_pago<>o.tipo_pago OR p.moneda<>o.moneda OR p.monto<>-o.monto
 OR p.equivalente_bs<>-o.equivalente_bs OR p.ajuste_redondeo_bs<>-o.ajuste_redondeo_bs))
 ) THEN RAISE(ABORT, 'El reverso debe devolver los pagos originales completos') END;
END""",
}

for tabla in ("lineaproducto", "pagoproducto"):
    SQL["vp_"+tabla+"_no_agregar"] = f"""
    BEFORE INSERT ON ventas_productos_{tabla}
    WHEN EXISTS(SELECT 1 FROM ventas_productos_documentoproducto WHERE id=NEW.documento_id AND sellado=1)
    BEGIN SELECT RAISE(ABORT, 'El documento guardado no admite registros'); END"""
    for accion in ("UPDATE", "DELETE"):
        SQL["vp_"+tabla+"_"+accion.lower()] = f"""
        BEFORE {accion} ON ventas_productos_{tabla}
        BEGIN SELECT RAISE(ABORT, 'El registro no puede modificarse ni eliminarse'); END"""

def instalar(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        raise RuntimeError("Las protecciones de Venta de productos requieren SQLite.")
    for nombre, sql in SQL.items():
        schema_editor.execute(f"CREATE TRIGGER {nombre} {sql}")

def quitar(apps, schema_editor):
    for nombre in reversed(SQL):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {nombre}")

class Migration(migrations.Migration):
    dependencies = [("ventas_productos","0001_initial")]
    operations = [migrations.RunPython(instalar,quitar)]
