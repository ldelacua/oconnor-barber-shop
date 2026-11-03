"""Protecciones MySQL adicionales para comisiones de productos.

Se instalan después de las tablas de liquidación, solo en instalaciones que
ya usan disparadores. La configuración sin disparadores no las ejecuta.
"""
from .instalacion import definiciones


def sentencias():
    originales = definiciones()['triggers']
    sellar = originales['liq_sellar']
    requisito = 'NOT EXISTS(SELECT 1 FROM liquidaciones_detalleliquidacion WHERE liquidacion_id=NEW.id_cancelacion AND ajuste_de_id IS NULL)'
    suma = '(SELECT COALESCE(SUM(comision_usd),0) FROM liquidaciones_detalleliquidacion WHERE liquidacion_id=NEW.id_cancelacion)'
    if requisito not in sellar or suma not in sellar:
        raise RuntimeError('La definición original de la liquidación no coincide.')
    sellar = sellar.replace(requisito, '(' + requisito + ' AND NOT EXISTS(SELECT 1 FROM liquidaciones_periodocomisionproductos p JOIN liquidaciones_comisionventaproducto v ON v.periodo_id=p.id WHERE p.liquidacion_id=NEW.id_cancelacion))')
    sellar = sellar.replace(suma, '(' + suma + ' + (SELECT COALESCE(SUM(comision_usd),0) FROM liquidaciones_periodocomisionproductos WHERE liquidacion_id=NEW.id_cancelacion) + (SELECT COALESCE(SUM(monto_usd),0) FROM liquidaciones_reintegrocomisionproducto WHERE liquidacion_id=NEW.id_cancelacion))')
    marcador = ' OR EXISTS(\n SELECT 1 FROM liquidaciones_detalleliquidacion p'
    if marcador not in sellar:
        raise RuntimeError('No se encontró la comprobación de reversos.')
    control = ''' OR EXISTS(SELECT 1 FROM liquidaciones_periodocomisionproductos p WHERE p.liquidacion_id=NEW.id_cancelacion AND (
      ABS(p.unidades-(SELECT COALESCE(SUM(unidades),0) FROM liquidaciones_comisionventaproducto WHERE periodo_id=p.id))>0.005 OR
      ABS(p.base_usd-(SELECT COALESCE(SUM(base_usd),0) FROM liquidaciones_comisionventaproducto WHERE periodo_id=p.id))>0.005 OR
      ABS(p.comision_usd-(SELECT COALESCE(SUM(comision_usd),0) FROM liquidaciones_comisionventaproducto WHERE periodo_id=p.id))>0.005))
 OR EXISTS(SELECT 1 FROM liquidaciones_periodocomisionproductos p
      JOIN ventas_productos_documentoproducto v ON v.prestador_id=p.prestador_id
      WHERE p.liquidacion_id=NEW.id_cancelacion AND v.tipo='VP' AND v.sellado=1 AND v.fecha BETWEEN p.desde AND p.hasta
      AND NOT EXISTS(SELECT 1 FROM ventas_productos_documentoproducto r WHERE r.documento_original_id=v.id AND r.sellado=1 AND r.fecha<=NEW.fecha_cancelacion)
      AND NOT EXISTS(SELECT 1 FROM liquidaciones_comisionventaproducto c WHERE c.periodo_id=p.id AND c.venta_id=v.id))
 OR EXISTS(SELECT 1 FROM liquidaciones_periodocomisionproductos p
      JOIN liquidaciones_comisionventaproducto c ON c.periodo_id=p.id
      JOIN ventas_productos_documentoproducto v ON v.id=c.venta_id
      WHERE p.liquidacion_id=NEW.id_cancelacion AND ABS(c.comision_usd-(
       ROUND((SELECT COALESCE(SUM(x.base_usd),0) FROM liquidaciones_comisionventaproducto x JOIN ventas_productos_documentoproducto a ON a.id=x.venta_id
         WHERE x.periodo_id=p.id AND (a.fecha<v.fecha OR (a.fecha=v.fecha AND a.id<=v.id)))*p.porcentaje/100,2)
       - ROUND((SELECT COALESCE(SUM(x.base_usd),0) FROM liquidaciones_comisionventaproducto x JOIN ventas_productos_documentoproducto a ON a.id=x.venta_id
         WHERE x.periodo_id=p.id AND (a.fecha<v.fecha OR (a.fecha=v.fecha AND a.id<v.id)))*p.porcentaje/100,2)))>0.005)
 OR EXISTS(SELECT 1 FROM liquidaciones_comisionventaproducto c
      JOIN liquidaciones_periodocomisionproductos p ON p.id=c.periodo_id
      JOIN liquidaciones_liquidacion l ON l.id_cancelacion=p.liquidacion_id
      JOIN ventas_productos_documentoproducto r ON r.documento_original_id=c.venta_id
      WHERE p.prestador_id=NEW.prestador_id AND l.sellado=1 AND r.sellado=1 AND r.fecha<=NEW.fecha_cancelacion
      AND NOT EXISTS(SELECT 1 FROM liquidaciones_reintegrocomisionproducto a WHERE a.comision_id=c.id))
'''
    sellar = sellar.replace(marcador, control + marcador)
    periodo = originales['ci_venta_periodo']
    cierre = '''IF (OLD.sellado=0 AND NEW.sellado=1 AND NEW.tipo='VP' AND NEW.prestador_id IS NOT NULL AND EXISTS(
 SELECT 1 FROM liquidaciones_periodocomisionproductos p JOIN liquidaciones_liquidacion l ON l.id_cancelacion=p.liquidacion_id
 WHERE p.prestador_id=NEW.prestador_id AND l.sellado=1 AND NEW.fecha BETWEEN p.desde AND p.hasta)) THEN
 SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Periodo de comisiones ya liquidado';
END IF;
'''
    periodo = periodo.rsplit('END', 1)[0] + cierre + 'END'
    reverso = originales['vp_validar_sello'].replace('AND o.tipo=\'VP\' AND o.sellado=1 AND NEW.cliente_id=o.cliente_id',
        "AND o.tipo='VP' AND o.sellado=1 AND (NEW.prestador_id <=> o.prestador_id) AND NEW.cliente_id=o.cliente_id")
    if reverso == originales['vp_validar_sello']:
        raise RuntimeError('No se encontró la validación del reverso.')
    resultado = {'liq_sellar': sellar, 'ci_venta_periodo': periodo, 'vp_validar_sello': reverso}
    candado = "DECLARE candado_id SMALLINT DEFAULT NULL; SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE; IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta candado'; END IF;"
    tablas = {'lcp_periodo': 'liquidaciones_periodocomisionproductos',
              'lcp_venta': 'liquidaciones_comisionventaproducto',
              'lcp_reintegro': 'liquidaciones_reintegrocomisionproducto'}
    for prefijo, tabla in tablas.items():
        for evento in ('UPDATE', 'DELETE'):
            nombre = prefijo + '_' + evento.lower()
            resultado[nombre] = f"CREATE TRIGGER `{nombre}` BEFORE {evento} ON `{tabla}` FOR EACH ROW BEGIN {candado} SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Registro de comision inmutable'; END"
    validaciones = {
      'lcp_periodo_insert': ('liquidaciones_periodocomisionproductos', """NEW.desde>NEW.hasta OR NEW.unidades<=0 OR NEW.base_usd<0 OR NEW.porcentaje<0 OR NEW.porcentaje>100 OR ABS(NEW.comision_usd-ROUND(NEW.base_usd*NEW.porcentaje/100,2))>0.005 OR NOT EXISTS(SELECT 1 FROM liquidaciones_liquidacion l WHERE l.id_cancelacion=NEW.liquidacion_id AND l.sellado=0 AND l.prestador_id=NEW.prestador_id AND l.periodo_desde=NEW.desde AND l.periodo_hasta=NEW.hasta) OR EXISTS(SELECT 1 FROM liquidaciones_periodocomisionproductos p JOIN liquidaciones_liquidacion l ON l.id_cancelacion=p.liquidacion_id WHERE l.sellado=1 AND p.prestador_id=NEW.prestador_id AND p.desde<=NEW.hasta AND p.hasta>=NEW.desde)"""),
      'lcp_venta_insert': ('liquidaciones_comisionventaproducto', """NOT EXISTS(SELECT 1 FROM liquidaciones_periodocomisionproductos p JOIN liquidaciones_liquidacion l ON l.id_cancelacion=p.liquidacion_id JOIN ventas_productos_documentoproducto v ON v.id=NEW.venta_id WHERE p.id=NEW.periodo_id AND l.sellado=0 AND v.sellado=1 AND v.tipo='VP' AND v.prestador_id=p.prestador_id AND v.fecha BETWEEN p.desde AND p.hasta AND NEW.unidades=v.unidades_total AND NEW.base_usd=v.subtotal_usd-v.descuento_usd AND NEW.comision_usd>=0 AND NOT EXISTS(SELECT 1 FROM ventas_productos_documentoproducto r WHERE r.documento_original_id=v.id AND r.sellado=1 AND r.fecha<=l.fecha_cancelacion))"""),
      'lcp_reintegro_insert': ('liquidaciones_reintegrocomisionproducto', """NOT EXISTS(SELECT 1 FROM liquidaciones_liquidacion l JOIN liquidaciones_comisionventaproducto c ON c.id=NEW.comision_id JOIN liquidaciones_periodocomisionproductos p ON p.id=c.periodo_id JOIN liquidaciones_liquidacion anterior ON anterior.id_cancelacion=p.liquidacion_id JOIN ventas_productos_documentoproducto r ON r.id=NEW.reverso_id WHERE l.id_cancelacion=NEW.liquidacion_id AND l.sellado=0 AND anterior.sellado=1 AND l.prestador_id=p.prestador_id AND r.sellado=1 AND r.tipo='RP' AND r.documento_original_id=c.venta_id AND r.fecha<=l.fecha_cancelacion AND NEW.monto_usd=-c.comision_usd)"""),
    }
    for nombre, (tabla, condicion) in validaciones.items():
        resultado[nombre] = f"CREATE TRIGGER `{nombre}` BEFORE INSERT ON `{tabla}` FOR EACH ROW BEGIN {candado} IF ({condicion}) THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Comision de productos invalida'; END IF; END"
    return resultado
