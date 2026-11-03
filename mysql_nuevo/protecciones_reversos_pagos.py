"""Protecciones adicionales; se instalan después de crear la tabla de reversos."""
from .protecciones_pagos import CONDICION, sentencias as pagos_originales


def sentencias(vendor='mysql'):
    condicion = CONDICION.replace('WHERE p.compra_id=c.id_compra', "WHERE p.compra_id=c.id_compra AND NOT EXISTS(SELECT 1 FROM inventario_reversopagoproveedor r WHERE r.pago_id=p.id)")
    reverso = "LENGTH(TRIM(NEW.motivo))=0 OR LENGTH(TRIM(NEW.registrado_por))=0 OR NOT EXISTS(SELECT 1 FROM inventario_pagoproveedor p WHERE p.id=NEW.pago_id AND NEW.fecha>=p.fecha)"
    if vendor == 'sqlite':
        condicion = condicion.replace('NEW.monto/NEW.tasa_cambio', 'NEW.monto*1.0/NEW.tasa_cambio')
        reglas = {'pp_validar': "CREATE TRIGGER pp_validar BEFORE INSERT ON inventario_pagoproveedor WHEN " + condicion + " BEGIN SELECT RAISE(ABORT,'Pago inválido o excede saldo'); END",
            'rpp_validar': "CREATE TRIGGER rpp_validar BEFORE INSERT ON inventario_reversopagoproveedor WHEN " + reverso + " BEGIN SELECT RAISE(ABORT,'Reverso inválido'); END"}
        for evento in ('UPDATE', 'DELETE'):
            reglas['rpp_no_'+evento.lower()] = f"CREATE TRIGGER rpp_no_{evento.lower()} BEFORE {evento} ON inventario_reversopagoproveedor BEGIN SELECT RAISE(ABORT,'Reverso inmutable'); END"
        return reglas
    original = pagos_originales()['pp_validar']
    viejo = CONDICION.replace('NEW.moneda=c.divisa', '(NEW.moneda COLLATE utf8mb4_0900_as_cs)=(c.divisa COLLATE utf8mb4_0900_as_cs)')
    condicion = condicion.replace('NEW.moneda=c.divisa', '(NEW.moneda COLLATE utf8mb4_0900_as_cs)=(c.divisa COLLATE utf8mb4_0900_as_cs)')
    reglas = {'pp_validar': original.replace(viejo, condicion)}
    candado = "DECLARE candado_id SMALLINT DEFAULT NULL; SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE; IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta candado'; END IF;"
    reglas['rpp_validar'] = f"CREATE TRIGGER rpp_validar BEFORE INSERT ON inventario_reversopagoproveedor FOR EACH ROW BEGIN {candado} IF ({reverso}) THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Reverso invalido'; END IF; END"
    for evento in ('UPDATE', 'DELETE'):
        reglas['rpp_no_'+evento.lower()] = f"CREATE TRIGGER rpp_no_{evento.lower()} BEFORE {evento} ON inventario_reversopagoproveedor FOR EACH ROW BEGIN {candado} SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Reverso inmutable'; END"
    return reglas


def instalar(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor not in ('mysql', 'sqlite'):
        return
    if vendor == 'mysql':
        with schema_editor.connection.cursor() as c:
            c.execute('SELECT trigger_name FROM information_schema.triggers WHERE trigger_schema=DATABASE()')
            actuales = {r[0] for r in c.fetchall()}
        if not actuales:
            return
        if 'pp_validar' not in actuales:
            raise RuntimeError('Faltan las protecciones originales de pagos.')
    for nombre, sql in sentencias(vendor).items():
        schema_editor.execute('DROP TRIGGER IF EXISTS ' + schema_editor.quote_name(nombre))
        schema_editor.execute(sql)


def permisos(apps, schema_editor):
    alias = schema_editor.connection.alias
    ct, _ = apps.get_model('contenttypes', 'ContentType').objects.using(alias).get_or_create(app_label='inventario', model='reversopagoproveedor')
    Permission = apps.get_model('auth', 'Permission')
    permisos = [Permission.objects.using(alias).get_or_create(content_type=ct, codename=a+'_reversopagoproveedor', defaults={'name': a.title()+' reverso de pago a proveedor'})[0] for a in ('add','view')]
    for grupo in apps.get_model('auth','Group').objects.using(alias).filter(name__in=['ADMINISTRADOR','ENCARGADO']):
        grupo.permissions.add(*permisos)
