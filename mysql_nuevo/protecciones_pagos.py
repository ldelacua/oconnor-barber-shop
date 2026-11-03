"""Protecciones del registro de abonos a proveedores."""
CONDICION = """NEW.monto<=0 OR NEW.aplicado_factura<=0 OR NEW.tasa_cambio<=0 OR NEW.moneda NOT IN ('USD','BS') OR NEW.tipo_pago<=0
 OR LENGTH(TRIM(NEW.registrado_por))=0 OR NOT EXISTS(
 SELECT 1 FROM inventario_compra c JOIN tasas_bcv_tasabcv t ON t.fecha=NEW.fecha
 WHERE c.id_compra=NEW.compra_id AND c.estado='A' AND NEW.fecha>=c.fecha_compra AND t.tasa_bcv=NEW.tasa_cambio
 AND ABS(NEW.aplicado_factura-ROUND(CASE WHEN NEW.moneda=c.divisa THEN NEW.monto WHEN NEW.moneda='USD' THEN NEW.monto*NEW.tasa_cambio ELSE NEW.monto/NEW.tasa_cambio END,2))<0.005
 AND NEW.aplicado_factura <= ROUND((SELECT COALESCE(SUM(ROUND(d.cantidad*d.precio_unitario,2)+ROUND(ROUND(d.cantidad*d.precio_unitario,2)*d.tasa_impuesto/100,2)),0) FROM inventario_detallecompra d WHERE d.compra_id=c.id_compra)
 -(SELECT COALESCE(SUM(p.aplicado_factura),0) FROM inventario_pagoproveedor p WHERE p.compra_id=c.id_compra),2))"""


def sentencias():
    # La moneda de compras históricas distingue mayúsculas; una tabla nueva
    # puede heredar ai_ci. Ambas columnas deben compararse explícitamente igual.
    condicion_mysql = CONDICION.replace('NEW.moneda=c.divisa',
        '(NEW.moneda COLLATE utf8mb4_0900_as_cs)=(c.divisa COLLATE utf8mb4_0900_as_cs)')
    candado = "DECLARE candado_id SMALLINT DEFAULT NULL; SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE; IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta candado'; END IF;"
    reglas = {'pp_validar': f"CREATE TRIGGER `pp_validar` BEFORE INSERT ON `inventario_pagoproveedor` FOR EACH ROW BEGIN {candado} IF ({condicion_mysql}) THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Pago a proveedor invalido o excede saldo'; END IF; END"}
    for evento in ('UPDATE', 'DELETE'):
        nombre = 'pp_no_' + evento.lower()
        reglas[nombre] = f"CREATE TRIGGER `{nombre}` BEFORE {evento} ON `inventario_pagoproveedor` FOR EACH ROW BEGIN {candado} SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Pago a proveedor inmutable'; END"
    return reglas
