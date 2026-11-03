from unittest.mock import MagicMock, patch
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from .preparar_programas_local import BASE, preparar

class PreparacionLocalTests(SimpleTestCase):
    def conexion(self, host='localhost', nombre=BASE):
        conexion = MagicMock()
        conexion.vendor = 'mysql'
        conexion.settings_dict = {'NAME': nombre, 'HOST': host}
        conexion.ops.quote_name.return_value = '`' + BASE + '`'
        cursor = conexion._nodb_cursor.return_value.__enter__.return_value
        return conexion, cursor

    def test_crea_base_nueva_sin_tocar_la_original(self):
        conexion, cursor = self.conexion()
        cursor.fetchone.return_value = None
        with patch('mysql_nuevo.preparar_programas_local.connections', {'default': conexion}):
            self.assertTrue(preparar())
        sentencias = [c.args[0] for c in cursor.execute.call_args_list]
        self.assertEqual(len(sentencias), 2)
        self.assertIn('CREATE DATABASE `barberia_validacion_programas`', sentencias[1])
        self.assertFalse(any('DROP' in sql.upper() for sql in sentencias))

    def test_permite_base_existente_vacia_sin_crear_nada(self):
        conexion, cursor = self.conexion()
        cursor.fetchone.side_effect = [(BASE,), (0,)]
        with patch('mysql_nuevo.preparar_programas_local.connections', {'default': conexion}):
            self.assertFalse(preparar())
        self.assertFalse(any('CREATE' in c.args[0].upper() for c in cursor.execute.call_args_list))

    def test_rechaza_una_base_existente_con_tablas(self):
        conexion, cursor = self.conexion()
        cursor.fetchone.side_effect = [(BASE,), (1,)]
        with patch('mysql_nuevo.preparar_programas_local.connections', {'default': conexion}):
            with self.assertRaises(ImproperlyConfigured):
                preparar()
        self.assertFalse(any('CREATE' in c.args[0].upper() for c in cursor.execute.call_args_list))

    def test_rechaza_servidor_remoto_o_nombre_diferente(self):
        for host, nombre in [('servidor-remoto', BASE), ('localhost', 'barberia')]:
            conexion, _ = self.conexion(host, nombre)
            with self.subTest(host=host, nombre=nombre), patch('mysql_nuevo.preparar_programas_local.connections', {'default': conexion}):
                with self.assertRaises(ImproperlyConfigured):
                    preparar()
            conexion._nodb_cursor.assert_not_called()
