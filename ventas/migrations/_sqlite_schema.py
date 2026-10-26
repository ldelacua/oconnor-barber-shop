"""Operación congelada para conservar disparadores en reconstrucciones SQLite."""
from django.db import migrations


class EsquemaConDisparadores(migrations.SeparateDatabaseAndState):
    def _ejecutar(self, funcion, schema_editor, *args):
        conexion = schema_editor.connection
        if conexion.vendor != 'sqlite' or schema_editor.collect_sql:
            return funcion(*args)
        if not conexion.in_atomic_block:
            raise RuntimeError('Se requiere una migración atómica para conservar los disparadores.')
        with conexion.cursor() as cursor:
            cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL ORDER BY name")
            disparadores = cursor.fetchall()
        for nombre, sql in disparadores:
            schema_editor.execute('DROP TRIGGER "' + nombre.replace('"', '""') + '"')
        resultado = funcion(*args)
        for nombre, sql in disparadores:
            schema_editor.execute(sql)
        return resultado

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        return self._ejecutar(super().database_forwards, schema_editor, app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        return self._ejecutar(super().database_backwards, schema_editor, app_label, schema_editor, from_state, to_state)
