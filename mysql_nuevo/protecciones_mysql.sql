-- Solo para revisión; instalar mediante manage_mysql.py migrate.
CREATE OR REPLACE SQL SECURITY INVOKER VIEW ci_movimientos AS
SELECT CONCAT('C-',m.id) AS id, dc.producto_id AS producto_id, c.fecha_compra AS fecha,
 'COMPRA' AS clase, m.cantidad AS delta, m.costo_unitario_usd AS costo_unitario_usd, m.creado_en AS registrado_en
 FROM inventario_movimientoinventario m JOIN inventario_detallecompra dc ON dc.id=m.detalle_id
 JOIN inventario_compra c ON c.id_compra=dc.compra_id WHERE c.estado='A'
UNION ALL
SELECT CONCAT('V-',l.id),l.producto_id,v.fecha,CASE WHEN v.tipo='VP' THEN 'VENTA' ELSE 'REVERSO' END,
 CASE WHEN v.tipo='VP' THEN -l.cantidad ELSE l.cantidad END,NULL,v.creado_en
 FROM ventas_productos_lineaproducto l JOIN ventas_productos_documentoproducto v ON v.id=l.documento_id WHERE v.sellado=1
UNION ALL
SELECT CONCAT('A-',d.id),d.producto_id,a.fecha,'OTRO',CASE WHEN a.tipo='EN' THEN d.cantidad ELSE -d.cantidad END,
 d.costo_unitario_usd,a.creado_en FROM control_inventario_detalleajuste d
 JOIN control_inventario_documentoajuste a ON a.id=d.documento_id WHERE a.sellado=1;
DELIMITER $$
CREATE TRIGGER `ci_ajuste_no_editar` BEFORE UPDATE ON `control_inventario_documentoajuste` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (OLD.sellado=1) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El ajuste registrado no se modifica';
END IF;
END$$
CREATE TRIGGER `ci_ajuste_no_eliminar` BEFORE DELETE ON `control_inventario_documentoajuste` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El ajuste no se elimina';
END$$
CREATE TRIGGER `ci_ajuste_no_insertar_sellado` BEFORE INSERT ON `control_inventario_documentoajuste` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.sellado<>0) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El ajuste debe sellarse al terminar';
END IF;
END$$
CREATE TRIGGER `ci_ajuste_sellar` BEFORE UPDATE ON `control_inventario_documentoajuste` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (OLD.sellado=0 AND NEW.sellado=1) THEN
IF (EXISTS(SELECT 1 FROM control_inventario_cierremensual c
    WHERE NEW.fecha<=LAST_DAY(c.periodo)
    AND (c.estado='C' OR (c.estado='B' AND c.id<>COALESCE(NEW.cierre_id,-1))))) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Periodo cerrado o con conteo fisico';
END IF;
 IF (LENGTH(TRIM(NEW.observacion))=0 OR NOT EXISTS(
 SELECT 1 FROM control_inventario_detalleajuste WHERE documento_id=NEW.id)) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El ajuste requiere motivo y productos';
END IF;
 IF (NEW.cierre_id IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM control_inventario_cierremensual c WHERE c.id=NEW.cierre_id AND c.estado='B'
 AND NEW.fecha=LAST_DAY(c.periodo))) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El ajuste no corresponde al cierre abierto';
END IF;
 IF (NEW.tipo='SA' AND EXISTS(
 SELECT 1 FROM control_inventario_detalleajuste d WHERE d.documento_id=NEW.id
 AND ROUND(d.cantidad,3)>ROUND(COALESCE((SELECT SUM(delta) FROM ci_movimientos WHERE producto_id=d.producto_id),0),3))) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Existencias insuficientes para la salida';
END IF;
END IF;
END$$
CREATE TRIGGER `ci_cierre_confirmar` BEFORE UPDATE ON `control_inventario_cierremensual` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (OLD.estado='B' AND NEW.estado='C') THEN
IF (NEW.cerrado_en IS NULL OR NEW.cerrado_por='' OR
 NOT EXISTS(SELECT 1 FROM control_inventario_detallecierre WHERE cierre_id=NEW.id) OR EXISTS(
 SELECT 1 FROM control_inventario_detallecierre WHERE cierre_id=NEW.id AND fisico IS NULL)) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta completar el conteo fisico';
END IF;
 IF (EXISTS(
 SELECT 1 FROM control_inventario_detallecierre d WHERE d.cierre_id=NEW.id AND
 ABS(ROUND(d.fisico-d.teorico,3)-ROUND(COALESCE((
 SELECT SUM(CASE WHEN a.tipo='EN' THEN l.cantidad ELSE -l.cantidad END)
 FROM control_inventario_detalleajuste l JOIN control_inventario_documentoajuste a ON a.id=l.documento_id
 WHERE a.cierre_id=NEW.id AND a.sellado=1 AND l.producto_id=d.producto_id),0),3))>0.0005)) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Los ajustes no coinciden con el conteo fisico';
END IF;
END IF;
END$$
CREATE TRIGGER `ci_cierre_crear` BEFORE INSERT ON `control_inventario_cierremensual` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.estado<>'B' OR DAY(NEW.periodo)<>1) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Periodo de cierre invalido';
END IF;
 IF (EXISTS(SELECT 1 FROM control_inventario_cierremensual WHERE estado='C')
 AND NEW.periodo<>DATE_ADD((SELECT MAX(periodo) FROM control_inventario_cierremensual WHERE estado='C'), INTERVAL 1 MONTH)) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Los cierres deben ser consecutivos';
END IF;
END$$
CREATE TRIGGER `ci_cierre_inmutable` BEFORE UPDATE ON `control_inventario_cierremensual` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (OLD.estado='C') THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El cierre historico no se modifica';
END IF;
END$$
CREATE TRIGGER `ci_cierre_no_eliminar` BEFORE DELETE ON `control_inventario_cierremensual` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (OLD.estado='C') THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El cierre historico no se elimina';
END IF;
END$$
CREATE TRIGGER `ci_cierre_periodo_fijo` BEFORE UPDATE ON `control_inventario_cierremensual` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.periodo<>OLD.periodo OR (CAST(NEW.iniciado_por AS BINARY) <> CAST(OLD.iniciado_por AS BINARY)) OR NEW.creado_en<>OLD.creado_en
OR NEW.estado NOT IN ('B','C')) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El periodo y origen del conteo no se modifican';
END IF;
END$$
CREATE TRIGGER `ci_compra_periodo` BEFORE UPDATE ON `inventario_compra` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (OLD.estado='B' AND NEW.estado='A'
AND EXISTS(SELECT 1 FROM control_inventario_cierremensual c
    WHERE NEW.fecha_compra<=LAST_DAY(c.periodo)
    AND (c.estado='C' OR (c.estado='B' AND c.id<>COALESCE(NULL,-1))))) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Periodo cerrado o con conteo fisico';
END IF;
END$$
CREATE TRIGGER `ci_detalle_no_agregar` BEFORE INSERT ON `control_inventario_detalleajuste` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (EXISTS(
SELECT 1 FROM control_inventario_documentoajuste WHERE id=NEW.documento_id AND sellado=1)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El ajuste esta bloqueado';
END IF;
END$$
CREATE TRIGGER `ci_detalle_no_editar` BEFORE UPDATE ON `control_inventario_detalleajuste` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El detalle no se modifica';
END$$
CREATE TRIGGER `ci_detalle_no_eliminar` BEFORE DELETE ON `control_inventario_detalleajuste` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El detalle no se elimina';
END$$
CREATE TRIGGER `ci_snapshot_actualizar` BEFORE UPDATE ON `control_inventario_detallecierre` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (EXISTS(SELECT 1 FROM control_inventario_cierremensual WHERE id=OLD.cierre_id AND estado='C')
OR NEW.cierre_id<>OLD.cierre_id OR NEW.producto_id<>OLD.producto_id OR (CAST(NEW.codigo AS BINARY) <> CAST(OLD.codigo AS BINARY))
OR (CAST(NEW.descripcion AS BINARY) <> CAST(OLD.descripcion AS BINARY)) OR NEW.inicial<>OLD.inicial OR NEW.compras<>OLD.compras
OR NEW.ventas<>OLD.ventas OR NEW.otros<>OLD.otros OR NEW.teorico<>OLD.teorico
OR NEW.costo_unitario_usd<>OLD.costo_unitario_usd) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La fotografia del cierre esta bloqueada';
END IF;
END$$
CREATE TRIGGER `ci_snapshot_no_agregar` BEFORE INSERT ON `control_inventario_detallecierre` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (EXISTS(
SELECT 1 FROM control_inventario_cierremensual WHERE id=NEW.cierre_id AND estado='C')) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El cierre historico no admite productos';
END IF;
END$$
CREATE TRIGGER `ci_snapshot_no_eliminar` BEFORE DELETE ON `control_inventario_detallecierre` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (EXISTS(
SELECT 1 FROM control_inventario_cierremensual WHERE id=OLD.cierre_id AND estado='C')) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El cierre historico no se elimina';
END IF;
END$$
CREATE TRIGGER `ci_venta_periodo` BEFORE UPDATE ON `ventas_productos_documentoproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (OLD.sellado=0 AND NEW.sellado=1
AND EXISTS(SELECT 1 FROM control_inventario_cierremensual c
    WHERE NEW.fecha<=LAST_DAY(c.periodo)
    AND (c.estado='C' OR (c.estado='B' AND c.id<>COALESCE(NULL,-1))))) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Periodo cerrado o con conteo fisico';
END IF;
END$$
CREATE TRIGGER `inv_compra_no_editar` BEFORE UPDATE ON `inventario_compra` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (OLD.estado = 'A') THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La compra actualizada no se modifica';
END IF;
END$$
CREATE TRIGGER `inv_compra_no_eliminar` BEFORE DELETE ON `inventario_compra` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (OLD.estado = 'A') THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La compra actualizada no se elimina';
END IF;
END$$
CREATE TRIGGER `inv_compra_no_insertar_actualizada` BEFORE INSERT ON `inventario_compra` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.estado <> 'B') THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La compra debe comenzar como borrador';
END IF;
END$$
CREATE TRIGGER `inv_compra_validar_actualizacion` BEFORE UPDATE ON `inventario_compra` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.estado = 'A') THEN
IF (NEW.actualizada_en IS NULL OR NEW.actualizada_por = '') THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta auditoria de actualizacion';
END IF;
 IF (NOT EXISTS (SELECT 1 FROM inventario_detallecompra WHERE compra_id = OLD.id_compra)) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La compra requiere productos';
END IF;
 IF (EXISTS (
 SELECT 1 FROM inventario_detallecompra d
 LEFT JOIN inventario_movimientoinventario m ON m.detalle_id = d.id
 WHERE d.compra_id = OLD.id_compra AND (m.id IS NULL OR m.cantidad <> d.cantidad))) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Las entradas de inventario no coinciden con la compra';
END IF;
END IF;
END$$
CREATE TRIGGER `inv_detalle_no_editar` BEFORE UPDATE ON `inventario_detallecompra` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (EXISTS (SELECT 1 FROM inventario_compra WHERE id_compra IN (OLD.compra_id, NEW.compra_id) AND estado = 'A')
 OR EXISTS (SELECT 1 FROM inventario_movimientoinventario WHERE detalle_id = OLD.id)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El detalle de inventario esta bloqueado';
END IF;
END$$
CREATE TRIGGER `inv_detalle_no_eliminar` BEFORE DELETE ON `inventario_detallecompra` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (EXISTS (SELECT 1 FROM inventario_compra WHERE id_compra = OLD.compra_id AND estado = 'A')
 OR EXISTS (SELECT 1 FROM inventario_movimientoinventario WHERE detalle_id = OLD.id)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El detalle de inventario esta bloqueado';
END IF;
END$$
CREATE TRIGGER `inv_detalle_no_insertar` BEFORE INSERT ON `inventario_detallecompra` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (EXISTS (SELECT 1 FROM inventario_compra WHERE id_compra = NEW.compra_id AND estado = 'A')) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La compra actualizada no admite detalles';
END IF;
END$$
CREATE TRIGGER `inv_movimiento_no_editar` BEFORE UPDATE ON `inventario_movimientoinventario` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Los movimientos no se modifican';
END$$
CREATE TRIGGER `inv_movimiento_no_eliminar` BEFORE DELETE ON `inventario_movimientoinventario` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Los movimientos no se eliminan';
END$$
CREATE TRIGGER `inv_movimiento_validar` BEFORE INSERT ON `inventario_movimientoinventario` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NOT EXISTS (
 SELECT 1 FROM inventario_detallecompra d JOIN inventario_compra c ON c.id_compra = d.compra_id
 WHERE d.id = NEW.detalle_id AND c.estado = 'B' AND d.cantidad = NEW.cantidad)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Entrada de inventario invalida';
END IF;
END$$
CREATE TRIGGER `liq_detalle_validar` BEFORE INSERT ON `liquidaciones_detalleliquidacion` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.porcentaje<0 OR NEW.porcentaje>100 OR NOT EXISTS(
 SELECT 1 FROM liquidaciones_liquidacion l
 JOIN ventas_detalleventa v ON v.id=NEW.detalle_venta_id
 JOIN ventas_documentoventa d ON d.id_documento=v.id_documento
 WHERE l.id_cancelacion=NEW.liquidacion_id AND l.sellado=0 AND d.sellado=1
 AND v.barbero_id=l.prestador_id
 AND ((d.tipo_documento='FA' AND NEW.ajuste_de_id IS NULL
 AND d.fecha BETWEEN l.periodo_desde AND l.periodo_hasta
 AND NOT EXISTS(SELECT 1 FROM ventas_documentoventa r WHERE r.documento_original_id=d.id_documento)
 AND NEW.monto_servicio_usd=v.monto_servicio
 AND NEW.porcentaje=(SELECT porcentaje FROM barberos_barbero WHERE id=l.prestador_id)
 AND ABS(NEW.comision_usd-ROUND(NEW.monto_servicio_usd*NEW.porcentaje/100.0,2))<0.005)
 OR (d.tipo_documento='RE' AND d.fecha<=l.fecha_cancelacion AND EXISTS(
 SELECT 1 FROM liquidaciones_detalleliquidacion p
 JOIN liquidaciones_liquidacion lp ON lp.id_cancelacion=p.liquidacion_id
 JOIN ventas_detalleventa vf ON vf.id=p.detalle_venta_id
 WHERE p.id=NEW.ajuste_de_id AND lp.sellado=1 AND lp.prestador_id=l.prestador_id
 AND vf.id_documento=d.documento_original_id AND vf.id_servicio=v.id_servicio
 AND vf.barbero_id=v.barbero_id AND vf.cantidad_servicio=v.cantidad_servicio
 AND p.porcentaje=NEW.porcentaje AND p.comision_usd=-NEW.comision_usd
 AND p.monto_servicio_usd=-NEW.monto_servicio_usd AND v.monto_servicio=NEW.monto_servicio_usd
 )))
)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Servicio no pendiente o descuento invalido';
END IF;
END$$
CREATE TRIGGER `liq_detalleliquidacion_delete` BEFORE DELETE ON `liquidaciones_detalleliquidacion` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El registro liquidado no se modifica ni elimina';
END$$
CREATE TRIGGER `liq_detalleliquidacion_update` BEFORE UPDATE ON `liquidaciones_detalleliquidacion` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El registro liquidado no se modifica ni elimina';
END$$
CREATE TRIGGER `liq_no_delete` BEFORE DELETE ON `liquidaciones_liquidacion` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La cancelacion no se elimina';
END$$
CREATE TRIGGER `liq_no_update` BEFORE UPDATE ON `liquidaciones_liquidacion` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NOT (OLD.sellado=0 AND NEW.sellado=1 AND (NEW.id_cancelacion <=> OLD.id_cancelacion) AND (NEW.fecha_cancelacion <=> OLD.fecha_cancelacion) AND (NEW.prestador_id <=> OLD.prestador_id) AND (CAST(NEW.nombre_prestador AS BINARY) <=> CAST(OLD.nombre_prestador AS BINARY)) AND (NEW.periodo_desde <=> OLD.periodo_desde) AND (NEW.periodo_hasta <=> OLD.periodo_hasta) AND (NEW.tasa_bcv <=> OLD.tasa_bcv) AND (NEW.total_servicios_usd <=> OLD.total_servicios_usd) AND (NEW.total_comision_usd <=> OLD.total_comision_usd) AND (NEW.total_bs <=> OLD.total_bs) AND (CAST(NEW.registrado_por AS BINARY) <=> CAST(OLD.registrado_por AS BINARY)) AND (NEW.creado_en <=> OLD.creado_en) AND (NEW.clave <=> OLD.clave))) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La cancelacion no se modifica';
END IF;
END$$
CREATE TRIGGER `liq_pago_validar` BEFORE INSERT ON `liquidaciones_pagoliquidacion` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.monto<=0 OR NEW.equivalente_bs<0 OR NEW.tipo_pago<=0 OR NEW.moneda NOT IN ('USD','BS') OR NOT EXISTS(
 SELECT 1 FROM liquidaciones_liquidacion l WHERE l.id_cancelacion=NEW.liquidacion_id AND l.sellado=0
 AND ABS(NEW.equivalente_bs-CASE WHEN NEW.moneda='BS' THEN NEW.monto ELSE ROUND(NEW.monto*l.tasa_bcv,2) END)<0.005
)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Pago de cancelacion invalido';
END IF;
END$$
CREATE TRIGGER `liq_pagoliquidacion_delete` BEFORE DELETE ON `liquidaciones_pagoliquidacion` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El registro liquidado no se modifica ni elimina';
END$$
CREATE TRIGGER `liq_pagoliquidacion_update` BEFORE UPDATE ON `liquidaciones_pagoliquidacion` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El registro liquidado no se modifica ni elimina';
END$$
CREATE TRIGGER `liq_sellar` BEFORE UPDATE ON `liquidaciones_liquidacion` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.sellado=1 AND (
 NOT EXISTS(SELECT 1 FROM liquidaciones_detalleliquidacion WHERE liquidacion_id=NEW.id_cancelacion AND ajuste_de_id IS NULL)
 OR NOT EXISTS(SELECT 1 FROM liquidaciones_pagoliquidacion WHERE liquidacion_id=NEW.id_cancelacion)
 OR ABS(NEW.total_comision_usd-(SELECT COALESCE(SUM(comision_usd),0) FROM liquidaciones_detalleliquidacion WHERE liquidacion_id=NEW.id_cancelacion))>0.005
 OR ABS(NEW.total_servicios_usd-(SELECT COALESCE(SUM(monto_servicio_usd),0) FROM liquidaciones_detalleliquidacion WHERE liquidacion_id=NEW.id_cancelacion))>0.005
 OR ABS(NEW.total_bs-ROUND(NEW.total_comision_usd*NEW.tasa_bcv,2))>0.005
 OR ABS(NEW.total_bs-(SELECT COALESCE(SUM(equivalente_bs+ajuste_redondeo_bs),0) FROM liquidaciones_pagoliquidacion WHERE liquidacion_id=NEW.id_cancelacion))>0.005
 OR (NOT EXISTS(SELECT 1 FROM liquidaciones_pagoliquidacion WHERE liquidacion_id=NEW.id_cancelacion AND moneda='BS')
 AND ABS(NEW.total_comision_usd-(SELECT COALESCE(SUM(monto),0) FROM liquidaciones_pagoliquidacion WHERE liquidacion_id=NEW.id_cancelacion AND moneda='USD'))>0.005)
 OR (EXISTS(SELECT 1 FROM liquidaciones_pagoliquidacion WHERE liquidacion_id=NEW.id_cancelacion AND moneda='BS')
 AND ABS(NEW.total_bs-ROUND((SELECT COALESCE(SUM(monto),0) FROM liquidaciones_pagoliquidacion WHERE liquidacion_id=NEW.id_cancelacion AND moneda='USD')*NEW.tasa_bcv,2)
 -(SELECT COALESCE(SUM(monto),0) FROM liquidaciones_pagoliquidacion WHERE liquidacion_id=NEW.id_cancelacion AND moneda='BS'))>0.005)
 OR EXISTS(
 SELECT 1 FROM liquidaciones_detalleliquidacion p
 JOIN liquidaciones_liquidacion lp ON lp.id_cancelacion=p.liquidacion_id
 JOIN ventas_detalleventa vf ON vf.id=p.detalle_venta_id
 JOIN ventas_documentoventa f ON f.id_documento=vf.id_documento
 JOIN ventas_documentoventa r ON r.documento_original_id=f.id_documento
 WHERE lp.prestador_id=NEW.prestador_id AND lp.sellado=1 AND f.tipo_documento='FA'
 AND r.sellado=1 AND r.fecha<=NEW.fecha_cancelacion
 AND NOT EXISTS(SELECT 1 FROM liquidaciones_detalleliquidacion a WHERE a.ajuste_de_id=p.id)
 )
)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Saldo, pagos o descuentos de la cancelacion incompletos';
END IF;
END$$
CREATE TRIGGER `liq_validar` BEFORE INSERT ON `liquidaciones_liquidacion` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.sellado!=0 OR NEW.tasa_bcv<=0 OR NEW.total_comision_usd<=0 OR NEW.total_bs<=0
OR NEW.periodo_desde>NEW.periodo_hasta OR NEW.periodo_hasta>NEW.fecha_cancelacion) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Datos de cancelacion invalidos';
END IF;
END$$
CREATE TRIGGER `ventas_detalle_no_delete` BEFORE DELETE ON `ventas_detalleventa` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El detalle no se modifica ni elimina';
END$$
CREATE TRIGGER `ventas_detalle_no_update` BEFORE UPDATE ON `ventas_detalleventa` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El detalle no se modifica ni elimina';
END$$
CREATE TRIGGER `ventas_detalle_validar` BEFORE INSERT ON `ventas_detalleventa` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.cantidad_servicio<=0 OR NEW.precio_manual NOT IN (0,1) OR NOT EXISTS (
 SELECT 1 FROM ventas_documentoventa d WHERE d.id_documento=NEW.id_documento AND d.sellado=0 AND (
 (d.tipo_documento='FA' AND NEW.linea_original_id IS NULL
  AND NEW.impuesto_normal IN (0,1) AND NEW.impuesto_normal=1-NEW.retencion_impuesto
  AND NEW.retencion_impuesto IS NOT NULL AND NEW.retencion_impuesto IN (0,1)
  AND NEW.retencion_impuesto=(SELECT retencion_impuesto FROM servicios_servicio WHERE id=NEW.id_servicio)
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
  AND (
   (d.iva_incluido=0 AND NEW.base_imponible_usd IS NULL AND NEW.base_imponible_bs IS NULL
    AND ABS(NEW.monto_impuesto-ROUND((NEW.monto_servicio_bs-NEW.monto_descuento_bs)*d.impuesto/100.0,2))<0.005)
   OR (d.iva_incluido=1 AND NEW.base_imponible_usd IS NOT NULL AND NEW.base_imponible_bs IS NOT NULL
    AND NEW.base_imponible_usd>=0 AND NEW.base_imponible_bs>=0
    AND ABS(NEW.base_imponible_usd-ROUND((NEW.monto_servicio-NEW.monto_descuento_usd)/(1.0+CASE WHEN NEW.retencion_impuesto=1 THEN d.impuesto ELSE 0 END/100.0),2))<0.005
    AND ABS(NEW.base_imponible_bs-ROUND((NEW.monto_servicio_bs-NEW.monto_descuento_bs)/(1.0+CASE WHEN NEW.retencion_impuesto=1 THEN d.impuesto ELSE 0 END/100.0),2))<0.005
    AND ABS(NEW.monto_impuesto-CASE WHEN NEW.impuesto_normal=1
     THEN ROUND((NEW.monto_servicio_bs-NEW.monto_descuento_bs)*d.impuesto/100.0,2)
     ELSE NEW.monto_servicio_bs-NEW.monto_descuento_bs-NEW.base_imponible_bs END)<0.005)
  ))
 OR
 (d.tipo_documento='RE' AND EXISTS (
  SELECT 1 FROM ventas_detalleventa o WHERE o.id=NEW.linea_original_id AND o.id_documento=d.documento_original_id
  AND o.id_servicio=NEW.id_servicio AND (o.barbero_id <=> NEW.barbero_id) AND (CAST(o.descripcion_barbero AS BINARY) = CAST(NEW.descripcion_barbero AS BINARY))
  AND (CAST(o.codigo_servicio AS BINARY) = CAST(NEW.codigo_servicio AS BINARY)) AND (CAST(o.descripcion_servicio AS BINARY) = CAST(NEW.descripcion_servicio AS BINARY))
  AND o.cantidad_servicio=NEW.cantidad_servicio AND o.precio_manual=NEW.precio_manual
  AND o.precio_unitario_usd=-NEW.precio_unitario_usd AND o.monto_servicio=-NEW.monto_servicio
  AND o.monto_servicio_bs=-NEW.monto_servicio_bs AND o.monto_impuesto=-NEW.monto_impuesto
  AND NEW.impuesto_normal=o.impuesto_normal
  AND (NEW.retencion_impuesto <=> o.retencion_impuesto)
  AND (NEW.base_imponible_usd <=> -o.base_imponible_usd)
  AND (NEW.base_imponible_bs <=> -o.base_imponible_bs)
  AND o.monto_descuento_usd=-NEW.monto_descuento_usd AND o.monto_descuento_bs=-NEW.monto_descuento_bs
 ))
 ))) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Precio, descuento, impuesto o reverso de detalle invalido';
END IF;
END$$
CREATE TRIGGER `ventas_doc_no_borrar` BEFORE DELETE ON `ventas_documentoventa` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El documento no se puede eliminar';
END$$
CREATE TRIGGER `ventas_doc_no_editar` BEFORE UPDATE ON `ventas_documentoventa` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NOT (OLD.sellado = 0 AND NEW.sellado = 1 AND (NEW.id_documento <=> OLD.id_documento) AND (CAST(NEW.tipo_documento AS BINARY) <=> CAST(OLD.tipo_documento AS BINARY)) AND (NEW.fecha <=> OLD.fecha) AND (NEW.cliente_id <=> OLD.cliente_id) AND (NEW.tasa_bcv <=> OLD.tasa_bcv) AND (NEW.impuesto <=> OLD.impuesto) AND (NEW.documento_original_id <=> OLD.documento_original_id) AND (CAST(NEW.motivo_reverso AS BINARY) <=> CAST(OLD.motivo_reverso AS BINARY)) AND (NEW.subtotal_usd <=> OLD.subtotal_usd) AND (NEW.subtotal_bs <=> OLD.subtotal_bs) AND (NEW.total_impuesto_bs <=> OLD.total_impuesto_bs) AND (NEW.total_bs <=> OLD.total_bs) AND (NEW.clave_operacion <=> OLD.clave_operacion) AND (NEW.creado_en <=> OLD.creado_en) AND (NEW.iva_incluido <=> OLD.iva_incluido) AND (CAST(NEW.registrado_por AS BINARY) <=> CAST(OLD.registrado_por AS BINARY)) AND (NEW.descuento_porcentaje <=> OLD.descuento_porcentaje) AND (NEW.descuento_usd <=> OLD.descuento_usd) AND (NEW.descuento_bs <=> OLD.descuento_bs))) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El documento no se puede modificar';
END IF;
END$$
CREATE TRIGGER `ventas_doc_sellar` BEFORE UPDATE ON `ventas_documentoventa` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.sellado = 1 AND (
 NOT EXISTS(SELECT 1 FROM ventas_detalleventa WHERE id_documento = NEW.id_documento)
 OR ABS(NEW.subtotal_usd - (SELECT COALESCE(SUM(CASE WHEN NEW.iva_incluido=1 THEN base_imponible_usd ELSE monto_servicio-monto_descuento_usd END), 0) FROM ventas_detalleventa WHERE id_documento = NEW.id_documento)) > 0.005
 OR ABS(NEW.subtotal_bs - (SELECT COALESCE(SUM(CASE WHEN NEW.iva_incluido=1 THEN base_imponible_bs ELSE monto_servicio_bs-monto_descuento_bs END), 0) FROM ventas_detalleventa WHERE id_documento = NEW.id_documento)) > 0.005
 OR ABS(NEW.total_impuesto_bs - (SELECT COALESCE(SUM(monto_impuesto), 0) FROM ventas_detalleventa WHERE id_documento = NEW.id_documento)) > 0.005
 OR ABS(NEW.total_bs - NEW.subtotal_bs - NEW.total_impuesto_bs) > 0.005
 OR (NEW.tipo_documento='FA' AND NEW.total_bs>0 AND NOT EXISTS(SELECT 1 FROM ventas_pagoventa WHERE documento_id=NEW.id_documento))
 OR (NEW.tipo_documento='RE' AND
  (SELECT COUNT(*) FROM ventas_pagoventa WHERE documento_id=NEW.id_documento) !=
  (SELECT COUNT(*) FROM ventas_pagoventa WHERE documento_id=NEW.documento_original_id))
 OR (EXISTS(SELECT 1 FROM ventas_pagoventa WHERE documento_id=NEW.id_documento) AND
  ABS(NEW.total_bs - (SELECT SUM(equivalente_bs+ajuste_redondeo_bs) FROM ventas_pagoventa WHERE documento_id=NEW.id_documento))>0.005)
 OR (NEW.tipo_documento='FA' AND NOT EXISTS(SELECT 1 FROM ventas_pagoventa WHERE documento_id=NEW.id_documento AND moneda='BS')
  AND ABS(ROUND(NEW.total_bs*1.0/NEW.tasa_bcv,2) - (SELECT COALESCE(SUM(monto),0) FROM ventas_pagoventa WHERE documento_id=NEW.id_documento AND moneda='USD'))>0.005)
 OR (NEW.tipo_documento='FA' AND EXISTS(SELECT 1 FROM ventas_pagoventa WHERE documento_id=NEW.id_documento AND moneda='BS')
  AND ABS(NEW.total_bs - ROUND((SELECT COALESCE(SUM(monto),0) FROM ventas_pagoventa WHERE documento_id=NEW.id_documento AND moneda='USD')*NEW.tasa_bcv,2)
   - (SELECT COALESCE(SUM(monto),0) FROM ventas_pagoventa WHERE documento_id=NEW.id_documento AND moneda='BS'))>0.005)

 OR ABS(NEW.descuento_usd-(SELECT COALESCE(SUM(monto_descuento_usd),0) FROM ventas_detalleventa WHERE id_documento=NEW.id_documento))>0.005
 OR ABS(NEW.descuento_bs-(SELECT COALESCE(SUM(monto_descuento_bs),0) FROM ventas_detalleventa WHERE id_documento=NEW.id_documento))>0.005
 OR (NEW.tipo_documento='RE' AND (SELECT COUNT(*) FROM ventas_detalleventa WHERE id_documento=NEW.id_documento)!=(SELECT COUNT(*) FROM ventas_detalleventa WHERE id_documento=NEW.documento_original_id))

)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Documento sin detalles o totales inconsistentes';
END IF;
END$$
CREATE TRIGGER `ventas_doc_validar` BEFORE INSERT ON `ventas_documentoventa` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.iva_incluido NOT IN (0,1) OR NEW.descuento_porcentaje<0 OR NEW.descuento_porcentaje>100 OR NEW.sellado != 0 OR NEW.tasa_bcv <= 0 OR NEW.impuesto < 0 OR NEW.impuesto > 100
OR NOT (
 (NEW.tipo_documento = 'FA' AND NEW.iva_incluido=1 AND NEW.descuento_usd>=0 AND NEW.descuento_bs>=0 AND NEW.documento_original_id IS NULL AND NEW.subtotal_usd >= 0 AND NEW.subtotal_bs >= 0 AND NEW.total_impuesto_bs >= 0 AND NEW.total_bs >= 0)
 OR
 (NEW.tipo_documento = 'RE' AND NEW.descuento_usd<=0 AND NEW.descuento_bs<=0 AND NEW.documento_original_id IS NOT NULL AND NEW.subtotal_usd <= 0 AND NEW.subtotal_bs <= 0 AND NEW.total_impuesto_bs <= 0 AND NEW.total_bs <= 0
 AND EXISTS(SELECT 1 FROM ventas_documentoventa o WHERE o.id_documento = NEW.documento_original_id AND o.tipo_documento = 'FA' AND o.sellado = 1
 AND o.iva_incluido=NEW.iva_incluido AND o.cliente_id = NEW.cliente_id AND o.tasa_bcv = NEW.tasa_bcv AND o.impuesto = NEW.impuesto
 AND o.subtotal_usd = -NEW.subtotal_usd AND o.subtotal_bs = -NEW.subtotal_bs AND o.total_impuesto_bs = -NEW.total_impuesto_bs AND o.total_bs = -NEW.total_bs AND o.descuento_porcentaje=NEW.descuento_porcentaje AND o.descuento_usd=-NEW.descuento_usd AND o.descuento_bs=-NEW.descuento_bs))
)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Datos de documento o reverso no validos';
END IF;
END$$
CREATE TRIGGER `ventas_pago_no_delete` BEFORE DELETE ON `ventas_pagoventa` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El pago no se puede eliminar';
END$$
CREATE TRIGGER `ventas_pago_no_update` BEFORE UPDATE ON `ventas_pagoventa` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El pago no se puede modificar';
END$$
CREATE TRIGGER `ventas_pago_validar` BEFORE INSERT ON `ventas_pagoventa` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.tipo_pago <= 0 OR NEW.moneda NOT IN ('USD','BS') OR NEW.nombre_tipo_pago = ''
OR NOT EXISTS(
 SELECT 1 FROM ventas_documentoventa d WHERE d.id_documento=NEW.documento_id AND d.sellado=0
 AND ((d.tipo_documento='FA' AND NEW.monto>0 AND NEW.equivalente_bs>=0 AND NEW.pago_original_id IS NULL)
 OR (d.tipo_documento='RE' AND NEW.monto<0 AND NEW.equivalente_bs<=0 AND EXISTS(
  SELECT 1 FROM ventas_pagoventa p WHERE p.id=NEW.pago_original_id
  AND p.documento_id=d.documento_original_id AND p.tipo_pago=NEW.tipo_pago
  AND (CAST(p.moneda AS BINARY) = CAST(NEW.moneda AS BINARY)) AND (CAST(p.nombre_tipo_pago AS BINARY) = CAST(NEW.nombre_tipo_pago AS BINARY))
  AND p.fecha=NEW.fecha AND (CAST(p.referencia AS BINARY) = CAST(NEW.referencia AS BINARY)) AND (CAST(p.observacion AS BINARY) = CAST(NEW.observacion AS BINARY))
  AND p.monto=-NEW.monto AND p.equivalente_bs=-NEW.equivalente_bs
  AND p.ajuste_redondeo_bs=-NEW.ajuste_redondeo_bs
 )))
 AND ABS(NEW.equivalente_bs - CASE WHEN NEW.moneda='BS' THEN NEW.monto ELSE ROUND(NEW.monto*d.tasa_bcv,2) END)<0.005
)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Pago invalido o documento ya guardado';
END IF;
END$$
CREATE TRIGGER `vp_cabecera_no_editar` BEFORE UPDATE ON `ventas_productos_documentoproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (OLD.sellado = 1) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El documento guardado no se modifica';
END IF;
END$$
CREATE TRIGGER `vp_cabecera_no_eliminar` BEFORE DELETE ON `ventas_productos_documentoproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Los documentos no se eliminan';
END$$
CREATE TRIGGER `vp_cabecera_no_insertar_sellada` BEFORE INSERT ON `ventas_productos_documentoproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.sellado <> 0) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El documento debe sellarse al terminar';
END IF;
END$$
CREATE TRIGGER `vp_lineaproducto_delete` BEFORE DELETE ON `ventas_productos_lineaproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El registro no puede modificarse ni eliminarse';
END$$
CREATE TRIGGER `vp_lineaproducto_no_agregar` BEFORE INSERT ON `ventas_productos_lineaproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (EXISTS(SELECT 1 FROM ventas_productos_documentoproducto WHERE id=NEW.documento_id AND sellado=1)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El documento guardado no admite registros';
END IF;
END$$
CREATE TRIGGER `vp_lineaproducto_update` BEFORE UPDATE ON `ventas_productos_lineaproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El registro no puede modificarse ni eliminarse';
END$$
CREATE TRIGGER `vp_pagoproducto_delete` BEFORE DELETE ON `ventas_productos_pagoproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El registro no puede modificarse ni eliminarse';
END$$
CREATE TRIGGER `vp_pagoproducto_no_agregar` BEFORE INSERT ON `ventas_productos_pagoproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (EXISTS(SELECT 1 FROM ventas_productos_documentoproducto WHERE id=NEW.documento_id AND sellado=1)) THEN
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El documento guardado no admite registros';
END IF;
END$$
CREATE TRIGGER `vp_pagoproducto_update` BEFORE UPDATE ON `ventas_productos_pagoproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El registro no puede modificarse ni eliminarse';
END$$
CREATE TRIGGER `vp_validar_sello` BEFORE UPDATE ON `ventas_productos_documentoproducto` FOR EACH ROW
BEGIN
DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
IF (NEW.sellado = 1 AND OLD.sellado = 0) THEN
IF (NOT EXISTS (SELECT 1 FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id)) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La venta necesita productos';
END IF;
 IF (NEW.total_bs<>0 AND NOT EXISTS (SELECT 1 FROM ventas_productos_pagoproducto WHERE documento_id=OLD.id)) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La venta necesita pagos';
END IF;
 IF (ABS(ROUND(COALESCE((SELECT SUM(subtotal_usd) FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id),0),2)-NEW.subtotal_usd)>0.005
 OR ABS(ROUND(COALESCE((SELECT SUM(subtotal_bs) FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id),0),2)-NEW.subtotal_bs)>0.005
 OR ABS(ROUND(COALESCE((SELECT SUM(impuesto_bs) FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id),0),2)-NEW.impuesto_bs)>0.005
 OR ABS(NEW.total_bs-ROUND(NEW.subtotal_bs-NEW.descuento_bs+NEW.impuesto_bs,2))>0.005) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Los importes no coinciden con los detalles';
END IF;
 IF (ABS(ROUND(COALESCE((SELECT SUM(equivalente_bs+ajuste_redondeo_bs) FROM ventas_productos_pagoproducto WHERE documento_id=OLD.id),0),2)-NEW.total_bs)>0.005) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Los pagos no cubren el documento';
END IF;
 IF (NEW.tipo='VP' AND (
 NEW.documento_original_id IS NOT NULL OR NEW.total_bs<0
 OR EXISTS(SELECT 1 FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id AND (linea_original_id IS NOT NULL OR subtotal_usd<=0 OR subtotal_bs<0 OR impuesto_bs<0))
 OR EXISTS(SELECT 1 FROM ventas_productos_pagoproducto WHERE documento_id=OLD.id AND (pago_original_id IS NOT NULL OR monto<=0))
 )) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La venta de productos es invalida';
END IF;
 IF (NEW.tipo='VP' AND EXISTS(
 SELECT 1 FROM ventas_productos_lineaproducto n WHERE n.documento_id=OLD.id
 AND ROUND(n.cantidad,3)>ROUND(
 COALESCE((SELECT SUM(delta) FROM ci_movimientos WHERE producto_id=n.producto_id),0),3)
 )) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Existencias insuficientes';
END IF;
 IF (NEW.tipo='RP' AND NOT EXISTS(
 SELECT 1 FROM ventas_productos_documentoproducto o WHERE o.id=NEW.documento_original_id
 AND o.tipo='VP' AND o.sellado=1 AND NEW.cliente_id=o.cliente_id AND NEW.tasa_bcv=o.tasa_bcv
 AND NEW.iva=o.iva AND NEW.subtotal_usd=-o.subtotal_usd AND NEW.subtotal_bs=-o.subtotal_bs
 AND NEW.impuesto_bs=-o.impuesto_bs AND NEW.total_bs=-o.total_bs AND LENGTH(TRIM(NEW.motivo))>0
 )) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El reverso no corresponde con la venta original';
END IF;
 IF (NEW.tipo='RP' AND (
 (SELECT COUNT(*) FROM ventas_productos_lineaproducto WHERE documento_id=OLD.id)
 <> (SELECT COUNT(*) FROM ventas_productos_lineaproducto WHERE documento_id=NEW.documento_original_id)
 OR EXISTS(SELECT 1 FROM ventas_productos_lineaproducto l LEFT JOIN ventas_productos_lineaproducto o ON o.id=l.linea_original_id
 WHERE l.documento_id=OLD.id AND (o.id IS NULL OR o.documento_id<>NEW.documento_original_id
 OR l.producto_id<>o.producto_id OR l.cantidad<>o.cantidad OR l.precio_unitario_usd<>o.precio_unitario_usd
 OR l.subtotal_usd<>-o.subtotal_usd OR l.subtotal_bs<>-o.subtotal_bs OR l.impuesto_bs<>-o.impuesto_bs))
 )) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El reverso debe reponer los productos originales completos';
END IF;
 IF (NEW.tipo='RP' AND (
 (SELECT COUNT(*) FROM ventas_productos_pagoproducto WHERE documento_id=OLD.id)
 <> (SELECT COUNT(*) FROM ventas_productos_pagoproducto WHERE documento_id=NEW.documento_original_id)
 OR EXISTS(SELECT 1 FROM ventas_productos_pagoproducto p LEFT JOIN ventas_productos_pagoproducto o ON o.id=p.pago_original_id
 WHERE p.documento_id=OLD.id AND (o.id IS NULL OR o.documento_id<>NEW.documento_original_id
 OR p.tipo_pago<>o.tipo_pago OR (CAST(p.moneda AS BINARY) <> CAST(o.moneda AS BINARY)) OR p.monto<>-o.monto
 OR p.equivalente_bs<>-o.equivalente_bs OR p.ajuste_redondeo_bs<>-o.ajuste_redondeo_bs))
 )) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El reverso debe devolver los pagos originales completos';
END IF;

 IF (NEW.total_bs=0 AND EXISTS(SELECT 1 FROM ventas_productos_pagoproducto WHERE documento_id=NEW.id)) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Un total cero no admite pagos';
END IF;
 IF (ABS(NEW.descuento_usd-ROUND(COALESCE((SELECT SUM(descuento_usd) FROM ventas_productos_lineaproducto WHERE documento_id=NEW.id),0),2))>0.005
 OR ABS(NEW.descuento_bs-ROUND(COALESCE((SELECT SUM(descuento_bs) FROM ventas_productos_lineaproducto WHERE documento_id=NEW.id),0),2))>0.005) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El descuento no coincide con sus renglones';
END IF;
 IF (NEW.tipo='VP' AND (NEW.precio_automatico<>1 OR EXISTS(
 SELECT 1 FROM ventas_productos_lineaproducto WHERE documento_id=NEW.id AND
 (costo_unitario_usd IS NULL OR porcentaje_venta IS NULL OR costo_unitario_usd<=0 OR porcentaje_venta<0)))) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='La venta requiere precios automaticos y su costo historico';
END IF;
 IF (NEW.tipo='VP' AND ABS(NEW.unidades_total-ROUND(COALESCE((SELECT SUM(cantidad)
 FROM ventas_productos_lineaproducto WHERE documento_id=NEW.id),0),2))>0.005) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El total de unidades no coincide';
END IF;
 IF (NEW.tipo='VP' AND (
 NEW.descuento_porcentaje<0 OR NEW.descuento_porcentaje>100 OR NEW.descuento_usd<0 OR NEW.descuento_usd>NEW.subtotal_usd
 OR NEW.descuento_bs<0 OR NEW.descuento_bs>NEW.subtotal_bs
 OR EXISTS(SELECT 1 FROM ventas_productos_lineaproducto WHERE documento_id=NEW.id AND
 (descuento_usd<0 OR descuento_usd>subtotal_usd OR descuento_bs<0 OR descuento_bs>subtotal_bs)))) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El descuento de la venta no es valido';
END IF;
 IF (NEW.tipo='RP' AND NOT EXISTS(
 SELECT 1 FROM ventas_productos_documentoproducto o WHERE o.id=NEW.documento_original_id
 AND NEW.descuento_porcentaje=o.descuento_porcentaje AND NEW.descuento_usd=-o.descuento_usd
 AND NEW.descuento_bs=-o.descuento_bs AND NEW.unidades_total=o.unidades_total
 AND (NEW.descuento_nivel <=> o.descuento_nivel) AND (NEW.umbral_descuento <=> o.umbral_descuento))) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El reverso debe conservar los descuentos originales';
END IF;
 IF (NEW.tipo='RP' AND EXISTS(
 SELECT 1 FROM ventas_productos_lineaproducto l JOIN ventas_productos_lineaproducto o ON o.id=l.linea_original_id
 WHERE l.documento_id=NEW.id AND (l.descuento_usd<>-o.descuento_usd OR l.descuento_bs<>-o.descuento_bs
 OR (NOT (l.costo_unitario_usd <=> o.costo_unitario_usd)) OR (NOT (l.porcentaje_venta <=> o.porcentaje_venta))))) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='El reverso no conserva sus precios originales';
END IF;
END IF;
END$$
DELIMITER ;
