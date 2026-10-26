import json
import re
from pathlib import Path
from unittest.mock import patch,MagicMock
from django.test import SimpleTestCase
from django.core.exceptions import ImproperlyConfigured
from mysql_nuevo.compilador import convertir,convertir_vista
from mysql_nuevo.bloqueos import serializar_operacion

class ConversionTests(SimpleTestCase):
    def setUp(self):
        raiz=Path(__file__).parent
        self.origen=json.loads((raiz/'origen_sqlite.json').read_text())
        self.mysql=json.loads((raiz/'protecciones_mysql.json').read_text())

    def test_todas_las_reglas_se_conservan(self):
        self.assertEqual(len(self.origen['triggers']),57)
        self.assertEqual(set(self.origen['triggers']),set(self.mysql['triggers']))
        for nombre,sql in self.origen['triggers'].items():
            n,salida=convertir(sql)
            self.assertEqual(n,nombre);self.assertEqual(salida,self.mysql['triggers'][nombre])
            self.assertEqual(salida.count('MYSQL_ERRNO=3819'),len(re.findall(r'RAISE\(ABORT',sql))+1)
            self.assertIn('FOR EACH ROW',salida)
            self.assertIn('FOR UPDATE',salida)

    def test_no_queda_gramatica_sqlite(self):
        for sql in self.mysql['triggers'].values():
            self.assertNotRegex(sql,r'RAISE\(|strftime\(|\bdate\(|UPDATE OF|\|\|')
        self.assertEqual(convertir_vista(self.origen['view']),self.mysql['view'])
        self.assertEqual(self.mysql['view'].count('CONCAT('),3)
        self.assertIn('SQL SECURITY INVOKER',self.mysql['view'])

    def test_reglas_clave_presentes(self):
        sql='\n'.join(self.mysql['triggers'].values())
        for texto in ['impuesto_normal','retencion_impuesto','descuento_porcentaje','ci_movimientos','Existencias insuficientes','liq_detalle','fisico','teorico']:
            self.assertIn(texto,sql)
        self.assertIn('LAST_DAY(',sql);self.assertIn('DATE_ADD(',sql)
        self.assertIn('CAST(NEW.registrado_por AS BINARY)',sql)

    def test_compilador_rechaza_formato_inesperado(self):
        with self.assertRaises(ValueError):convertir('DROP TABLE clientes_cliente')

    def test_mutex_sqlite_no_hace_consultas(self):
        with patch('mysql_nuevo.bloqueos.connection') as con:
            con.vendor='sqlite';serializar_operacion();con.cursor.assert_not_called()

    def test_mutex_mysql_requiere_transaccion_y_fila(self):
        with patch('mysql_nuevo.bloqueos.connection') as con:
            con.vendor='mysql';con.in_atomic_block=False
            with self.assertRaises(ImproperlyConfigured):serializar_operacion()
            con.in_atomic_block=True
            con.cursor.return_value.__enter__.return_value.fetchone.return_value=None
            with self.assertRaises(ImproperlyConfigured):serializar_operacion()
            con.cursor.return_value.__enter__.return_value.fetchone.return_value=(1,)
            serializar_operacion()
            self.assertIn('FOR UPDATE',con.cursor.return_value.__enter__.return_value.execute.call_args[0][0])
