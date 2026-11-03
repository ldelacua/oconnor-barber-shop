"""Verificaciones de infraestructura para la evaluación local sin triggers."""
from django.apps import apps
from django.core.management.base import CommandError
from .instalacion import INDICES
from .preparar_programas_local import BASE


def comprobar(conexion):
    if (conexion.vendor != 'mysql' or conexion.settings_dict['NAME'] != BASE
        or conexion.settings_dict['HOST'] not in {'localhost', '127.0.0.1', '::1'}):
        raise CommandError('Se requiere la base experimental local.')
    if conexion.mysql_is_mariadb or conexion.mysql_version[:2] != (8,4):
        raise CommandError('Se requiere MySQL 8.4.')
    with conexion.cursor() as c:
        c.execute('SELECT DATABASE(), @@SESSION.transaction_isolation, @@SESSION.sql_mode')
        actual, aislamiento, modo = c.fetchone()
        if actual != BASE or aislamiento.upper().replace('_','-') != 'READ-COMMITTED':
            raise CommandError('La conexión o el aislamiento no coinciden con el perfil experimental.')
        if 'STRICT_TRANS_TABLES' not in modo and 'STRICT_ALL_TABLES' not in modo:
            raise CommandError('Falta el modo estricto de MySQL.')
        c.execute("SELECT table_name,engine FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'")
        tablas = c.fetchall()
        if not tablas or any(engine != 'InnoDB' for _, engine in tablas):
            raise CommandError('Faltan tablas o alguna tabla no utiliza InnoDB.')
        encontradas = {tabla for tabla, _ in tablas}
        esperadas = {m._meta.db_table for m in apps.get_models(include_auto_created=True)
                     if m._meta.managed and not m._meta.proxy and not m._meta.swapped}
        if esperadas - encontradas:
            raise CommandError('Faltan tablas de la aplicación: ' + ', '.join(sorted(esperadas - encontradas)))
        columnas = {'ci_un_conteo_abierto_mysql': ['ci_abierto_mysql'],
                    'cita_horario_activo_mysql': ['barbero_id', 'fecha', 'hora', 'cita_activa_mysql']}
        for indice, (tabla, _) in INDICES.items():
            c.execute('SELECT non_unique, column_name FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=%s AND index_name=%s ORDER BY seq_in_index', [tabla, indice])
            filas = c.fetchall()
            if any(fila[0] != 0 for fila in filas) or [fila[1] for fila in filas] != columnas[indice]:
                raise CommandError('Falta el índice único ' + indice)
        c.execute("SELECT security_type FROM information_schema.views WHERE table_schema=DATABASE() AND table_name='ci_movimientos'")
        fila = c.fetchone()
        if not fila or fila[0] != 'INVOKER':
            raise CommandError('Falta la vista de existencias.')
        c.execute('SELECT id FROM mysql_candado_operaciones WHERE id=1')
        if c.fetchone() is None:
            raise CommandError('Falta el candado de operaciones.')
        c.execute("SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE()")
        if c.fetchone()[0] != 0:
            raise CommandError('La base experimental contiene disparadores inesperados.')
        c.execute("SELECT COUNT(*) FROM django_migrations WHERE app='mysql_nuevo' AND name='0002_protecciones'")
        if c.fetchone()[0] != 1:
            raise CommandError('La inicialización experimental está incompleta.')
    return len(tablas)
