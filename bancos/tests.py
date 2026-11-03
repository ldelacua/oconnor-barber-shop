from io import BytesIO

from django.core.exceptions import ValidationError
from django.test import TestCase

from .importacion import importar, leer_csv
from .models import Banco, CuentaBancaria, MovimientoBanco


class ImportacionTests(TestCase):
    def test_importacion_repetida_y_reemplazo(self):
        cuenta = CuentaBancaria.objects.create(banco=Banco.objects.create(nombre='BANCO PRUEBA'),
                                              nro_cuenta='0102-1234', moneda='BS')
        encabezado = b'fecha,nro_cuenta,nro_transaccion,descripcion,monto\n'
        fila = b'2026-10-31,0102-1234,TRF-9921,Pago proveedor,-350.00\n'
        datos = leer_csv(BytesIO(encabezado + fila), cuenta)
        self.assertEqual(importar(cuenta, datos), (1, 0, 0, 0))
        self.assertEqual(importar(cuenta, datos), (0, 1, 0, 0))
        conflicto = encabezado + b'2026-10-31,0102-1234,DEP-8301,Deposito cliente,350.00\n' + fila.replace(b'-350.00', b'-351.00')
        self.assertEqual(importar(cuenta, leer_csv(BytesIO(conflicto), cuenta)), (1, 0, 1, 0))
        self.assertEqual(importar(cuenta, datos), (0, 0, 1, 1))
        self.assertEqual(MovimientoBanco.objects.count(), 1)
        with self.assertRaises(ValidationError):
            leer_csv(BytesIO(encabezado + fila.replace(b'0102-1234', b'otra')), cuenta)


class ConciliacionTests(TestCase):
    def test_sugerencia_y_conciliacion_agrupada(self):
        from datetime import date
        from decimal import Decimal
        from django.contrib.auth import get_user_model
        from .conciliacion import conciliar, sugerencias
        from .models import MovimientoInterno
        usuario = get_user_model().objects.create_superuser(username='conciliador')
        cuenta = CuentaBancaria.objects.create(banco=Banco.objects.create(nombre='PRUEBA'),
                                              nro_cuenta='001', moneda='BS')
        dia = date(2026, 10, 31)
        banco = MovimientoBanco.objects.create(cuenta=cuenta, fecha=dia, nro_transaccion='REF', monto=100)
        primero = MovimientoInterno.objects.create(cuenta=cuenta, origen='SERVICIOS', pago_id=1,
                                                    fecha=dia, referencia='REF', monto=100)
        self.assertEqual(sugerencias(cuenta), [(banco, primero)])
        segundo = MovimientoInterno.objects.create(cuenta=cuenta, origen='SERVICIOS', pago_id=2,
                                                    fecha=dia, referencia='ref', monto=100)
        self.assertEqual(sugerencias(cuenta), [])
        otro = MovimientoBanco.objects.create(cuenta=cuenta, fecha=dia, nro_transaccion='OTRO', monto=100)
        with self.assertRaises(ValidationError):
            conciliar(usuario, cuenta, [banco.pk], [primero.pk, segundo.pk])
        grupo = conciliar(usuario, cuenta, [banco.pk, otro.pk], [primero.pk, segundo.pk])
        self.assertEqual(grupo.monto, Decimal('200'))
        with self.assertRaises(ValidationError):
            conciliar(usuario, cuenta, [banco.pk], [primero.pk])


class CierreTests(TestCase):
    def test_pago_fin_de_mes_se_concilia_despues_sin_alterar_cierre(self):
        from datetime import date
        from decimal import Decimal
        from unittest.mock import patch
        from django.contrib.auth import get_user_model
        from .cierres import cerrar, reporte
        from .conciliacion import conciliar
        from .models import MovimientoInterno
        usuario = get_user_model().objects.create_superuser(username='cierre')
        cuenta = CuentaBancaria.objects.create(banco=Banco.objects.create(nombre='PRUEBA'), nro_cuenta='001', moneda='BS')
        octubre, noviembre = date(2026, 10, 31), date(2026, 11, 2)
        interno = MovimientoInterno.objects.create(cuenta=cuenta, origen='PROVEEDOR', pago_id=1,
                                                     fecha=octubre, referencia='P1', monto=-100)
        with patch('bancos.cierres.timezone.localdate', return_value=noviembre):
            cierre = cerrar(usuario, cuenta, octubre, Decimal('500.00'))
            with self.assertRaises(ValidationError):
                cerrar(usuario, cuenta, octubre, Decimal('500.00'))
        banco = MovimientoBanco.objects.create(cuenta=cuenta, fecha=noviembre, nro_transaccion='P1', monto=-100)
        grupo = conciliar(usuario, cuenta, [banco.pk], [interno.pk])
        cierre.refresh_from_db()
        self.assertEqual(cierre.resumen['sistema'][0]['id'], interno.pk)
        self.assertEqual(cierre.resumen['conciliaciones'], [])
        actual = reporte(cuenta, noviembre)
        self.assertEqual(actual['sistema'], [])
        self.assertEqual(actual['conciliaciones'][0]['id'], grupo.pk)
        self.assertEqual(MovimientoInterno.objects.count(), 1)


class ConsultaYFlujoTests(TestCase):
    def test_estado_y_tres_etapas(self):
        from datetime import date
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        from .models import Conciliacion, MovimientoInterno
        self.client.force_login(get_user_model().objects.create_superuser(username='flujo'))
        cuenta = CuentaBancaria.objects.create(banco=Banco.objects.create(nombre='PRUEBA'), nro_cuenta='001', moneda='BS')
        fecha = date(2026, 10, 31)
        for i, monto, ref in [(1, 100, 'R1'), (2, 200, 'DIF'), (3, 30, 'PARCIAL'), (4, 20, 'PARCIAL2')]:
            MovimientoInterno.objects.create(cuenta=cuenta, origen='SERVICIOS', pago_id=i, fecha=fecha, referencia=ref, monto=monto)
        for ref, monto in [('R1', 100), ('R2', 200), ('R3', 50)]:
            MovimientoBanco.objects.create(cuenta=cuenta, fecha=fecha, nro_transaccion=ref, descripcion='Importado', monto=monto)
        estado = self.client.get(reverse('bancos:estado_cuenta', args=[cuenta.pk]), {'buscar':'R2'})
        self.assertContains(estado, 'Importado')
        self.assertEqual(estado.context['totales']['neto'], 200)
        url = reverse('bancos:conciliar_cuenta', args=[cuenta.pk])
        self.assertEqual(self.client.post(url, {'automatico':'1'}).status_code, 302)
        self.assertEqual(Conciliacion.objects.count(), 1)
        r = self.client.get(url)
        self.assertContains(r, 'Movimientos conciliados')
        self.assertContains(r, 'type="checkbox" name="banco"')
        self.assertEqual(r.context['grupos'].count(), 1)
        self.assertFalse(r.context['banco_pendiente'].filter(nro_transaccion='R1').exists())
        [(banco, interno)] = r.context['sugerencias']
        self.assertEqual(banco.nro_transaccion, 'R2')
        self.assertEqual(self.client.post(url, {'confirmar_par': f'{banco.pk}:{interno.pk}'}).status_code, 302)
        banco = MovimientoBanco.objects.get(nro_transaccion='R3')
        internos = list(MovimientoInterno.objects.filter(partida__isnull=True).values_list('pk', flat=True))
        self.assertEqual(self.client.post(url, {'banco':[banco.pk], 'internos':internos}).status_code, 302)
        self.assertEqual(Conciliacion.objects.count(), 3)
        self.assertEqual(list(Conciliacion.objects.order_by("pk").values_list("metodo", flat=True)), ["AUTO", "MONTO", "MANUAL"])
        self.assertFalse(MovimientoBanco.objects.filter(partida__isnull=True).exists())
        grupo = Conciliacion.objects.order_by('pk').first()
        self.assertEqual(self.client.post(url, {'reversar_grupo': grupo.pk}).status_code, 302)
        self.assertEqual(grupo.reverso.movimientos['banco'][0]['referencia'], 'R1')
        self.assertEqual(MovimientoBanco.objects.filter(partida__isnull=True).count(), 1)
        self.assertEqual(MovimientoInterno.objects.filter(partida__isnull=True).count(), 1)
        self.assertEqual(self.client.get(url).context['grupos'].count(), 2)
        self.assertEqual(self.client.post(url, {'automatico':'1'}).status_code, 302)
        self.assertFalse(MovimientoBanco.objects.filter(partida__isnull=True).exists())



class PantallaImportacionTests(TestCase):
    def test_confirma_carga_y_muestra_filas_sin_mezclar_cuentas(self):
        from django.contrib.auth import get_user_model
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse
        self.client.force_login(get_user_model().objects.create_superuser(username='importador'))
        cuenta = CuentaBancaria.objects.create(banco=Banco.objects.create(nombre='BANCO PRUEBA'), nro_cuenta='001', moneda='BS')
        url = reverse('bancos:importar_estado')
        def cargar(numero):
            texto = f'fecha,nro_cuenta,nro_transaccion,descripcion,monto\n2026-10-31,{numero},REF1,Depósito de prueba,350.00\n'
            return self.client.post(url, {'cuenta': cuenta.pk, 'archivo': SimpleUploadedFile('estado.csv', texto.encode())}, follow=True)
        self.assertContains(cargar('002'), 'el número de cuenta del CSV no coincide')
        self.assertFalse(MovimientoBanco.objects.exists())
        respuesta = cargar('001')
        self.assertContains(respuesta, 'Archivo procesado correctamente')
        self.assertContains(respuesta, 'Depósito de prueba')
        self.assertContains(cargar('001'), 'Movimientos nuevos: 0. Ya importados: 1.')


class ArrastreMensualTests(TestCase):
    def test_octubre_pendiente_en_noviembre_y_conciliado_en_diciembre(self):
        from datetime import date
        from django.contrib.auth import get_user_model
        from .cierres import reporte, presentar_mes
        from .conciliacion import conciliar
        from .models import MovimientoInterno
        usuario = get_user_model().objects.create_superuser(username='arrastre')
        cuenta = CuentaBancaria.objects.create(banco=Banco.objects.create(nombre='ARRASTRE'), nro_cuenta='001', moneda='BS')
        pago = MovimientoInterno.objects.create(cuenta=cuenta, origen='PROVEEDOR', pago_id=1,
            fecha=date(2026,10,31), referencia='PAGO', monto=-100)
        banco = MovimientoBanco.objects.create(cuenta=cuenta, fecha=date(2026,12,2),
            nro_transaccion='PAGO', monto=-100)
        grupo = conciliar(usuario, cuenta, [banco.pk], [pago.pk])
        noviembre = presentar_mes(reporte(cuenta, date(2026,11,30)), date(2026,11,1))
        self.assertTrue(noviembre['sistema'][0]['arrastrado'])
        self.assertEqual(noviembre['conciliaciones'], [])
        diciembre = presentar_mes(reporte(cuenta, date(2026,12,31)), date(2026,12,1))
        self.assertEqual(diciembre['sistema'], [])
        self.assertEqual(diciembre['conciliaciones'][0]['id'], grupo.pk)
        from io import BytesIO
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        from django.urls import reverse
        from unittest.mock import patch
        self.client.force_login(usuario)
        with patch('django.utils.timezone.localdate', return_value=date(2026,12,5)):
            r = self.client.get(reverse('bancos:reporte_cuenta', args=[cuenta.pk]),
                                {'mes':'2026-11', 'excel':'1'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('2026-11.xlsx', r['Content-Disposition'])
        with ZipFile(BytesIO(r.content)) as z:
            for archivo in z.namelist():
                ET.fromstring(z.read(archivo))
            self.assertIn('Pendientes del sistema', z.read('xl/workbook.xml').decode())
            self.assertIn('PAGO', z.read('xl/worksheets/sheet3.xml').decode())
            self.assertIn('<v>-100.00</v>', z.read('xl/worksheets/sheet3.xml').decode())
