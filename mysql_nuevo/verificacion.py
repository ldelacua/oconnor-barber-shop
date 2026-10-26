"""Inspección de instalación; no inserta ni modifica datos de negocio."""
import re
from django.core.management.base import CommandError
from .instalacion import definiciones,INDICES


def comprobar(conexion):
    if conexion.vendor!='mysql':raise CommandError('La conexión activa no es MySQL.')
    if conexion.mysql_is_mariadb or conexion.mysql_version[:2]!=(8,4):raise CommandError('Se requiere MySQL 8.4 LTS.')
    reglas=definiciones()
    def normalizar(texto):return re.sub(r'\s+',' ',texto).strip()
    with conexion.cursor() as c:
        c.execute('SELECT @@SESSION.transaction_isolation, @@SESSION.sql_mode')
        aislamiento,modo=c.fetchone()
        if aislamiento.upper().replace('_','-')!='READ-COMMITTED':raise CommandError('La conexión debe usar READ COMMITTED.')
        if 'STRICT_TRANS_TABLES' not in modo and 'STRICT_ALL_TABLES' not in modo:raise CommandError('Falta modo estricto de MySQL.')
        c.execute("SELECT table_name,engine FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'")
        tablas=c.fetchall()
        if not tablas:raise CommandError('La base está vacía. Ejecuta manage_mysql.py migrate.')
        if any(engine!='InnoDB' for _,engine in tablas):raise CommandError('Todas las tablas deben usar InnoDB.')
        c.execute("SELECT trigger_name,action_statement FROM information_schema.triggers WHERE trigger_schema=DATABASE()")
        actuales=dict(c.fetchall())
        for nombre,sql in reglas['triggers'].items():
            if nombre not in actuales:raise CommandError('Falta el disparador '+nombre+'. Verifica migraciones y permiso TRIGGER del usuario MySQL.')
            cuerpo=sql.split('FOR EACH ROW',1)[1].strip()
            if normalizar(actuales[nombre])!=normalizar(cuerpo):raise CommandError('La definición del disparador '+nombre+' no coincide con esta versión.')
        for indice,(tabla,_) in INDICES.items():
            c.execute('SELECT non_unique FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=%s AND index_name=%s',[tabla,indice])
            filas=c.fetchall()
            if not filas or any(f[0]!=0 for f in filas):raise CommandError('Falta la restricción única '+indice)
        c.execute("SELECT security_type FROM information_schema.views WHERE table_schema=DATABASE() AND table_name='ci_movimientos'")
        vista=c.fetchone()
        if not vista or vista[0]!='INVOKER':raise CommandError('Falta la vista de existencias MySQL.')
        c.execute('SELECT id FROM mysql_candado_operaciones WHERE id=1')
        if c.fetchone() is None:raise CommandError('Falta inicializar el candado de transacciones.')
        c.execute("SELECT COUNT(*) FROM django_migrations WHERE app='mysql_nuevo' AND name='0002_protecciones'")
        if c.fetchone()[0]!=1:raise CommandError('La inicialización de MySQL no está completa.')
    return {'tablas':len(tablas),'disparadores':len(reglas['triggers']),'indices_especiales':len(INDICES)}
