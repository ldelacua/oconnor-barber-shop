import json
from pathlib import Path

INDICES={
 'ci_un_conteo_abierto_mysql':('control_inventario_cierremensual',
  "ALTER TABLE control_inventario_cierremensual ADD COLUMN ci_abierto_mysql TINYINT GENERATED ALWAYS AS (CASE WHEN estado='B' THEN 1 ELSE NULL END) STORED, ADD UNIQUE INDEX ci_un_conteo_abierto_mysql(ci_abierto_mysql)"),
 'cita_horario_activo_mysql':('citas_cita',
  "ALTER TABLE citas_cita ADD COLUMN cita_activa_mysql TINYINT GENERATED ALWAYS AS (CASE WHEN estado<>'cancelada' THEN 1 ELSE NULL END) STORED, ADD UNIQUE INDEX cita_horario_activo_mysql(barbero_id,fecha,hora,cita_activa_mysql)"),
}


def definiciones():
    return json.loads((Path(__file__).parent/'protecciones_mysql.json').read_text(encoding='utf-8'))


def instalar(apps,schema_editor):
    if schema_editor.connection.vendor!='mysql':
        raise RuntimeError('Esta inicialización requiere MySQL. El historial SQLite se mantiene separado.')
    with schema_editor.connection.cursor() as c:
        c.execute('SELECT id FROM mysql_candado_operaciones WHERE id=1')
        if c.fetchone() is None:c.execute('INSERT INTO mysql_candado_operaciones(id) VALUES (1)')
    # Los estados/tipos deben distinguir mayúsculas incluso cuando el resto de
    # las columnas use una colación apropiada para búsquedas sin distinguir caso.
    from django.db import models
    for modelo in apps.get_models():
        if not modelo._meta.managed:continue
        for campo in modelo._meta.local_fields:
            if isinstance(campo,models.CharField) and campo.choices:
                tabla=schema_editor.quote_name(modelo._meta.db_table)
                columna=schema_editor.quote_name(campo.column)
                nulidad='NULL' if campo.null else 'NOT NULL'
                tipo=campo.db_type(schema_editor.connection)
                schema_editor.execute(f'ALTER TABLE {tabla} MODIFY COLUMN {columna} {tipo} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs {nulidad}')
    # DDL de MySQL no es transaccional: todas las instrucciones son reintentables.
    for nombre,(tabla,sql) in INDICES.items():
        with schema_editor.connection.cursor() as c:
            c.execute('SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=%s AND index_name=%s',[tabla,nombre])
            existe=c.fetchone()[0]
        if not existe:schema_editor.execute(sql)
    reglas=definiciones()
    schema_editor.execute(reglas['view'])
    for nombre,sql in reglas['triggers'].items():
        schema_editor.execute('DROP TRIGGER IF EXISTS `'+nombre+'`')
        schema_editor.execute(sql)
    Unidad=apps.get_model('inventario','UnidadMedida')
    for codigo,nombre in [('GR','GRAMOS'),('LT','LITROS'),('KG','KILOGRAMOS'),('ML','MILILITROS')]:
        Unidad.objects.get_or_create(codigo=codigo,defaults={'nombre':nombre,'activo':True})
