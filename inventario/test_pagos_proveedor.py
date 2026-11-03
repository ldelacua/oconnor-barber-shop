import uuid
from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.urls import reverse
from . import tests as base
from .models import PagoProveedor
from .services import actualizar_compra
from .pagos_proveedor import registrar_pago, saldo_compra
from .existencias import existencia_producto


class PagosProveedorTests(TestCase):
    setUpTestData = classmethod(base.InventarioTests.setUpTestData.__func__)
    setUp = base.InventarioTests.setUp
    compra = base.InventarioTests.compra

    def preparar(self, divisa='USD'):
        compra = self.compra(divisa=divisa)
        actualizar_compra(compra.pk, 'PRUEBA', 0)
        return compra

    def pagar(self, compra, monto='10', tipo=5, clave=None):
        return registrar_pago(compra_id=compra.pk, fecha=date(2026, 10, 20), tipo_pago=tipo,
            monto=Decimal(monto), referencia='ref', observacion='abono', clave=clave or uuid.uuid4(), usuario=self.usuario)

    def test_abonos_mixtos_completan_saldo_sin_cambiar_stock(self):
        compra = self.preparar()
        self.pagar(compra)
        self.assertEqual(saldo_compra(compra)['saldo'], Decimal('24.80'))
        self.pagar(compra, monto='992', tipo=6)
        self.assertEqual(saldo_compra(compra)['saldo'], 0)
        self.assertEqual(existencia_producto(self.producto.pk), 3)
        with self.assertRaises(ValidationError): self.pagar(compra, monto='0.01')

    def test_pago_usd_aplicado_en_factura_bs(self):
        compra = self.preparar('BS')
        self.pagar(compra, monto='0.87')
        self.assertEqual(saldo_compra(compra)['saldo'], 0)

    def test_doble_envio_no_duplica_y_no_se_modifica(self):
        compra = self.preparar()
        clave = uuid.uuid4()
        primero = self.pagar(compra, clave=clave)
        self.assertEqual(self.pagar(compra, clave=clave).pk, primero.pk)
        with self.assertRaises(ValidationError): self.pagar(compra, monto='11', clave=clave)
        primero.monto = Decimal('9')
        with self.assertRaises(ValidationError): primero.save()
        with self.assertRaises(ValidationError): PagoProveedor(pk=primero.pk).save(force_update=True)
        with self.assertRaises(ValidationError): PagoProveedor.objects.all().update(monto=1)
        self.assertEqual(PagoProveedor.objects.count(), 1)

    def test_borrador_y_exceso_se_rechazan(self):
        compra = self.compra()
        with self.assertRaises(ValidationError): self.pagar(compra)
        actualizar_compra(compra.pk, 'PRUEBA', 0)
        with self.assertRaises(ValidationError): self.pagar(compra, monto='35')
        self.assertFalse(PagoProveedor.objects.exists())

    def test_formulario_y_reporte_filtrado_por_permisos(self):
        compra = self.preparar()
        self.pagar(compra)
        self.assertEqual(self.client.get(reverse('pagos:proveedor', args=[compra.pk])).status_code, 200)
        r = self.client.get(reverse('pagos:consulta'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ABONO')
        self.assertEqual(r.context['totales']['salida_usd'], 10)
        self.assertEqual(r.context['totales']['entrada_usd'], 0)
        self.assertEqual(self.client.get(reverse('pagos:consulta'), {'sentido': 'E'}).context['pagina'].paginator.count, 0)
        usuario = get_user_model().objects.create_user(username='solo_cobros', password='prueba')
        usuario.user_permissions.add(Permission.objects.get(content_type__app_label='ventas', codename='view_pagoventa'))
        self.client.force_login(usuario)
        r = self.client.get(reverse('pagos:consulta'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'ABONO')
        self.assertEqual(self.client.get(reverse('pagos:proveedor', args=[compra.pk])).status_code, 403)

    def test_tasa_regresa_a_compra_y_rechaza_destino_externo(self):
        url = reverse('ventas:registrar_tasa_bcv')
        destino = reverse('inventario:nueva_compra')
        r = self.client.post(url, {'fecha': '2026-01-01', 'tasa_bcv': '40', 'next': destino})
        self.assertRedirects(r, destino, fetch_redirect_response=False)
        r = self.client.post(url, {'fecha': '2026-01-02', 'tasa_bcv': '40', 'next': 'https://externo.invalid/'})
        self.assertRedirects(r, reverse('ventas:lista'), fetch_redirect_response=False)

    def test_reporte_reune_cobros_y_liquidaciones_sin_sumar_monedas(self):
        from clientes.models import Cliente
        from barberos.models import Barbero
        from servicios.models import Servicio
        from ventas_productos.models import PorcentajeProducto
        from ventas_productos.servicios import registrar_venta as vender_producto
        from ventas.servicios import registrar_venta as vender_servicio, registrar_reverso
        from liquidaciones.servicios import registrar as liquidar
        from bancos.models import Banco, CuentaBancaria, MovimientoInterno
        cuenta = CuentaBancaria.objects.create(banco=Banco.objects.create(nombre='BANCO FLUJO'), nro_cuenta='001', moneda='USD')
        compra = self.preparar()
        self.pagar(compra)
        d = date(2026, 10, 20)
        cliente = Cliente.objects.create(nombre='CLIENTE', apellido='PAGOS', telefono='123')
        prestador = Barbero.objects.create(codigo='PAGOS', nombre='P', apellido='UNO', direccion='A', telefono='1', fecha_ingreso=d, porcentaje=50)
        servicio = Servicio.objects.create(codigo='PAGOS', nombre='SERVICIO', precio=10, duracion=30)
        PorcentajeProducto.objects.create(producto=self.producto, porcentaje=100)
        vender_producto(fecha=d, cliente=cliente, lineas=[dict(producto=self.producto, cantidad=Decimal('1'))],
            pagos=[dict(tipo_pago='4', fecha=d, cuenta_bancaria=cuenta, monto=Decimal('23.20'))], clave=uuid.uuid4(), usuario=self.usuario)
        factura = vender_servicio(fecha=d, cliente=cliente, lineas=[dict(barbero=prestador, servicio=servicio, cantidad_servicio=1)],
            pagos=[dict(tipo_pago='4', fecha=d, cuenta_bancaria=cuenta, monto=Decimal('11.60'))], clave=uuid.uuid4(), usuario=self.usuario)
        liquidar(prestador_id=prestador.pk, desde=d, hasta=d, fecha=d, seleccion=[factura.detalles.get().pk],
            pagos=[dict(tipo_pago='4', fecha=d, cuenta_bancaria=cuenta, monto=Decimal('5'))], clave=uuid.uuid4(), usuario=self.usuario)
        r = self.client.get(reverse('pagos:consulta'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['pagina'].paginator.count, 4)
        self.assertEqual(r.context['totales']['entrada_usd'], Decimal('34.80'))
        self.assertEqual(r.context['totales']['salida_usd'], Decimal('15.00'))
        registrar_reverso(documento_id=factura.pk, motivo='PRUEBA', usuario=self.usuario)
        r = self.client.get(reverse('pagos:consulta'))
        self.assertEqual(r.context['totales']['salida_usd'], Decimal('26.60'))

        self.assertEqual(set(MovimientoInterno.objects.filter(cuenta=cuenta).values_list('origen','monto')),
            {('PRODUCTOS', Decimal('23.20')), ('SERVICIOS', Decimal('11.60')),
             ('SERVICIOS', Decimal('-11.60')), ('PRESTADOR', Decimal('-5.00'))})

    def test_sql_no_modifica_pago_registrado(self):
        from django.db import connection, transaction, IntegrityError
        with connection.cursor() as c:
            if connection.vendor == 'mysql':
                c.execute("SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND trigger_name='pp_no_update'")
            else:
                c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='pp_no_update'")
            if not c.fetchone()[0]: self.skipTest('Requiere disparadores de protección SQL.')
        pago = self.pagar(self.preparar())
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as c:
            c.execute('UPDATE inventario_pagoproveedor SET monto=%s WHERE id=%s', [1, pago.pk])
        from .pagos_proveedor import reversar_pago
        reverso = reversar_pago(pago_id=pago.pk, motivo='ERROR SQL', usuario=self.usuario)
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as c:
            c.execute('DELETE FROM inventario_reversopagoproveedor WHERE id=%s', [reverso.pk])

    def test_conversion_usa_tasa_del_pago_y_no_la_de_compra(self):
        from tasas_bcv.models import TasaBCV
        compra = self.preparar()
        d = date(2026, 10, 21)
        TasaBCV.objects.create(fecha=d, tasa_bcv=80)
        pago = registrar_pago(compra_id=compra.pk, fecha=d, tipo_pago=6, monto=Decimal('800'),
            referencia='TASA', observacion='', clave=uuid.uuid4(), usuario=self.usuario)
        self.assertEqual(pago.tasa_cambio, Decimal('80'))
        self.assertEqual(pago.aplicado_factura, Decimal('10.00'))
        self.assertEqual(saldo_compra(compra)['saldo'], Decimal('24.80'))

    def test_pantallas_de_compra_y_producto_tienen_acceso_a_tasa(self):
        destino = reverse('ventas:registrar_tasa_bcv')
        for url in (reverse('inventario:nueva_compra'), reverse('ventas_productos:nueva')):
            respuesta = self.client.get(url)
            self.assertEqual(respuesta.status_code, 200)
            self.assertContains(respuesta, destino + '?next=')
            self.assertContains(respuesta, 'Cargar tasa Bs')

    def test_reporte_normaliza_textos_del_union_mysql(self):
        from unittest.mock import patch
        from django.db import connection
        with patch.object(connection, 'vendor', 'mysql'), \
             patch('django.db.models.query.QuerySet.aggregate', return_value={'entrada': None, 'salida': None}), \
             patch('ventas.pagos_general.Paginator') as paginador:
            paginador.return_value.get_page.return_value = []
            r = self.client.get(reverse('pagos:consulta'))
            self.assertEqual(r.status_code, 200)
            consulta = paginador.call_args.args[0]
            sql = str(consulta.query)
            self.assertIn('utf8mb4_0900_ai_ci', sql)
            self.assertIn('UNION ALL', sql)
            self.assertGreaterEqual(sql.count('USING utf8mb4'), 30)
            self.assertGreaterEqual(sql.count('CONVERT('), 30)

    def test_inicio_pagos_separa_prestadores_y_proveedores(self):
        r = self.client.get(reverse('pagos:lista'))
        self.assertContains(r, 'Pagos a prestadores de servicio')
        self.assertContains(r, 'Pagos a proveedores')
        self.assertNotContains(r, 'Compras / Pagar')
        compra = self.preparar()
        self.pagar(compra)
        r = self.client.get(reverse('pagos:proveedores'))
        self.assertContains(r, compra.numero_factura)
        self.assertContains(r, reverse('pagos:proveedor', args=[compra.pk]))

    def test_tasa_y_equivalente_bs_en_pago_proveedor(self):
        compra = self.preparar()
        pago = self.pagar(compra)
        self.assertEqual(pago.equivalente_bs, Decimal('400.00'))
        r = self.client.get(reverse('pagos:proveedor', args=[compra.pk]))
        self.assertContains(r, 'Equivalente Bs.')
        self.assertContains(r, '400.00')
        r = self.client.get(reverse('pagos:tasa_proveedor'), {'fecha': '2026-10-20'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['tasa'], '40.00')
        self.assertEqual(self.client.get(reverse('pagos:tasa_proveedor'), {'fecha': '1999-01-01'}).status_code, 404)


    def test_reverso_reabre_saldo_conserva_historial_y_no_duplica(self):
        from .pagos_proveedor import reversar_pago
        from .models import ReversoPagoProveedor
        compra = self.preparar()
        pago = self.pagar(compra, monto='34.80')
        self.assertEqual(saldo_compra(compra)['saldo'], 0)
        antes = existencia_producto(self.producto.pk)
        reverso = reversar_pago(pago_id=pago.pk, motivo='ERROR DE MONTO', usuario=self.usuario)
        self.assertEqual(saldo_compra(compra)['saldo'], Decimal('34.80'))
        self.assertEqual(existencia_producto(self.producto.pk), antes)
        with self.assertRaises(ValidationError):
            reversar_pago(pago_id=pago.pk, motivo='OTRO', usuario=self.usuario)
        with self.assertRaises(ValidationError):
            reverso.motivo = 'CAMBIO'
            reverso.save()
        with self.assertRaises(ValidationError):
            ReversoPagoProveedor.objects.all().delete()
        self.pagar(compra, monto='34.80')
        self.assertEqual(saldo_compra(compra)['saldo'], 0)
        self.assertEqual(PagoProveedor.objects.count(), 2)
        r = self.client.get(reverse('pagos:proveedor', args=[compra.pk]))
        self.assertContains(r, 'REVERSADO')
        self.assertContains(r, 'ERROR DE MONTO')
        reporte = self.client.get(reverse('pagos:consulta'))
        self.assertEqual(reporte.context['totales']['salida_usd'], Decimal('69.60'))
        self.assertEqual(reporte.context['totales']['entrada_usd'], Decimal('34.80'))

    def test_reverso_requiere_motivo_permiso_y_confirmacion_post(self):
        compra = self.preparar()
        pago = self.pagar(compra)
        url = reverse('pagos:reverso_proveedor', args=[pago.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(saldo_compra(compra)['pagado'], Decimal('10'))
        from django.utils.translation import override
        from .models import ReversoPagoProveedor
        for idioma in ('es', 'en'):
            with self.subTest(idioma=idioma), override(idioma):
                respuesta = self.client.post(url, {'motivo': ''})
                self.assertEqual(respuesta.status_code, 200)
                errores = respuesta.context['form'].errors.as_data()
                self.assertIn('motivo', errores)
                self.assertEqual(errores['motivo'][0].code, 'required')
                self.assertFalse(ReversoPagoProveedor.objects.filter(pago=pago).exists())
                self.assertEqual(saldo_compra(compra)['pagado'], Decimal('10'))
        usuario = get_user_model().objects.create_user(username='lector_pagos')
        usuario.user_permissions.add(*Permission.objects.filter(codename__in=['view_compra','view_pagoproveedor']))
        self.client.force_login(usuario)
        self.assertEqual(self.client.post(url, {'motivo': 'ERROR'}).status_code, 403)
        self.client.force_login(self.usuario)
        self.assertRedirects(self.client.post(url, {'motivo': 'ERROR'}), reverse('pagos:proveedor', args=[compra.pk]), fetch_redirect_response=False)
        self.assertEqual(saldo_compra(compra)['pagado'], 0)

    def test_excel_separa_monedas_respeta_filtros_y_permisos(self):
        from io import BytesIO
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        from .pagos_proveedor import reversar_pago
        compra = self.preparar()
        pago = self.pagar(compra)
        self.pagar(compra, monto='40', tipo=6)
        reversar_pago(pago_id=pago.pk, motivo='ERROR', usuario=self.usuario)
        r = self.client.get(reverse('pagos:consulta'), {'excel': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(BytesIO(r.content)) as z:
            for nombre in z.namelist():
                ET.fromstring(z.read(nombre))
            bs = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            usd = ET.fromstring(z.read('xl/worksheets/sheet2.xml'))
            self.assertIn('40.00', [v.text for v in bs.findall('.//s:v', ns)])
            self.assertIn('REVERSO DE PAGO A PROVEEDOR', ''.join(usd.itertext()))
            self.assertIn('SUM(I5:I6)', ''.join(usd.itertext()))
        usuario = get_user_model().objects.create_user(username='solo_excel_cobros')
        usuario.user_permissions.add(Permission.objects.get(content_type__app_label='ventas', codename='view_pagoventa'))
        self.client.force_login(usuario)
        r = self.client.get(reverse('pagos:consulta'), {'excel': '1'})
        with ZipFile(BytesIO(r.content)) as z:
            self.assertNotIn('PAGO A PROVEEDOR', z.read('xl/worksheets/sheet2.xml').decode())


    def test_excel_exporta_todas_las_paginas_y_filtra_moneda(self):
        from io import BytesIO
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        compra = self.preparar()
        for _ in range(31):
            self.pagar(compra, monto='0.01')
        r = self.client.get(reverse('pagos:consulta'), {'excel': '1', 'moneda': 'USD'})
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(BytesIO(r.content)) as z:
            usd = ET.fromstring(z.read('xl/worksheets/sheet2.xml'))
            bs = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            self.assertEqual(len(usd.findall('s:sheetData/s:row', ns)), 37)
            self.assertEqual(len(bs.findall('s:sheetData/s:row', ns)), 6)
            self.assertIn('SUM(I5:I35)', ''.join(usd.itertext()))
            self.assertIn('0.31', [v.text for v in usd.findall('.//s:v', ns)])


    def test_consulta_proveedores_incluye_reversos_y_excel(self):
        from .pagos_proveedor import reversar_pago
        from io import BytesIO
        from zipfile import ZipFile
        compra = self.preparar()
        pago = self.pagar(compra)
        reversar_pago(pago_id=pago.pk, motivo='ERROR LISTADO', usuario=self.usuario)
        filtros = {'origen': 'PROVEEDOR'}
        r = self.client.get(reverse('pagos:consulta'), filtros)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['pagina'].paginator.count, 2)
        self.assertContains(r, 'REVERSO_PROVEEDOR')
        self.assertContains(r, 'ERROR LISTADO')
        self.assertEqual(r.context['totales']['entrada_usd'], Decimal('10.00'))
        self.assertEqual(r.context['totales']['salida_usd'], Decimal('10.00'))
        self.assertEqual(r.context['totales']['neto_usd'], Decimal('0.00'))
        r = self.client.get(reverse('pagos:consulta'), dict(filtros, excel='1'))
        with ZipFile(BytesIO(r.content)) as z:
            self.assertIn('REVERSO DE PAGO A PROVEEDOR', z.read('xl/worksheets/sheet2.xml').decode())
        solo_reversos = self.client.get(reverse('pagos:consulta'), {'origen': 'REVERSO_PROVEEDOR'})
        self.assertEqual(solo_reversos.context['pagina'].paginator.count, 1)
        solo_salidas = self.client.get(reverse('pagos:consulta'), dict(filtros, sentido='S'))
        self.assertEqual(solo_salidas.context['pagina'].paginator.count, 1)


    def test_exceso_abono_muestra_error_y_no_registra_pago(self):
        compra = self.preparar()
        self.pagar(compra, monto='10')
        url = reverse('pagos:proveedor', args=[compra.pk])
        for tipo, monto in [('5', '25.00'), ('6', '992.01')]:
            with self.subTest(tipo=tipo):
                r = self.client.post(url, {'fecha': '2026-10-20', 'tipo_pago': tipo, 'monto': monto,
                    'referencia': 'EXCESO', 'observacion': '', 'clave': str(uuid.uuid4())})
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, 'No se registró el abono.')
                self.assertContains(r, 'El abono supera el saldo pendiente de la factura (24.80 USD)')
                self.assertContains(r, 'Cambia el monto o cancela el pago.')
                self.assertEqual(PagoProveedor.objects.filter(compra=compra).count(), 1)
                self.assertEqual(saldo_compra(compra)['saldo'], Decimal('24.80'))
        self.pagar(compra, monto='992', tipo=6)
        self.assertEqual(saldo_compra(compra)['saldo'], 0)


    def test_detalle_compra_muestra_abonos_y_reversos_con_saldo(self):
        from .pagos_proveedor import reversar_pago
        compra = self.preparar()
        pago = self.pagar(compra)
        self.pagar(compra, monto='40', tipo=6)
        reversar_pago(pago_id=pago.pk, motivo='ERROR HISTORIAL COMPRA', usuario=self.usuario)
        r = self.client.get(reverse('inventario:detalle', args=[compra.pk]))
        self.assertContains(r, 'Pagos de esta compra')
        self.assertContains(r, 'REVERSADO')
        self.assertContains(r, 'VIGENTE')
        self.assertContains(r, 'ERROR HISTORIAL COMPRA')
        self.assertEqual(len(r.context['pagos_compra']), 2)
        self.assertEqual(r.context['saldo_pagos']['pagado'], Decimal('1.00'))
        self.assertEqual(r.context['saldo_pagos']['saldo'], Decimal('33.80'))
        usuario = get_user_model().objects.create_user(username='solo_consulta_compra')
        usuario.user_permissions.add(Permission.objects.get(content_type__app_label='inventario', codename='view_compra'))
        self.client.force_login(usuario)
        r = self.client.get(reverse('inventario:detalle', args=[compra.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Pagos de esta compra')
        self.assertNotContains(r, 'ERROR HISTORIAL COMPRA')

    def test_detalle_compra_sin_pagos_indica_saldo_total(self):
        compra = self.preparar()
        r = self.client.get(reverse('inventario:detalle', args=[compra.pk]))
        self.assertContains(r, 'Esta compra no tiene pagos registrados.')
        self.assertEqual(r.context['saldo_pagos']['pagado'], 0)
        self.assertEqual(r.context['saldo_pagos']['saldo'], compra.total)


    def test_abono_con_cuenta_bancaria_y_reverso(self):
        from bancos.models import Banco, CuentaBancaria, MovimientoInterno
        from .pagos_proveedor import reversar_pago
        compra = self.preparar()
        banco = Banco.objects.create(nombre='BANCO PRUEBA')
        usd = CuentaBancaria.objects.create(banco=banco, nro_cuenta='001', moneda='USD')
        bs = CuentaBancaria.objects.create(banco=banco, nro_cuenta='002', moneda='BS')
        url = reverse('pagos:proveedor', args=[compra.pk])
        datos = {'fecha': '2026-10-20', 'tipo_pago': '4', 'monto': '10.00',
                 'referencia': 'BANCO', 'observacion': '', 'clave': str(uuid.uuid4()),
                 'cuenta_bancaria': bs.pk}
        respuesta = self.client.post(url, datos)
        self.assertContains(respuesta, 'corresponder a la moneda')
        self.assertFalse(PagoProveedor.objects.filter(compra=compra).exists())
        datos['cuenta_bancaria'] = usd.pk
        self.assertContains(self.client.post(url, dict(datos, tipo_pago='5')), 'no afecta al banco')
        self.assertFalse(PagoProveedor.objects.filter(compra=compra).exists())
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        pago = PagoProveedor.objects.get(compra=compra)
        vinculo = MovimientoInterno.objects.get(origen='PROVEEDOR', pago_id=pago.pk)
        self.assertEqual(vinculo.cuenta_id, usd.pk)
        self.assertEqual(vinculo.monto, Decimal('-10.00'))
        self.assertContains(self.client.get(reverse('pagos:proveedores')), str(usd))
        self.assertContains(self.client.get(reverse('pagos:consulta'), {'origen': 'PROVEEDOR'}), str(usd))
        self.assertContains(self.client.get(url), str(usd))
        reverso = reversar_pago(pago_id=pago.pk, motivo='PRUEBA', usuario=self.usuario)
        compensacion = MovimientoInterno.objects.get(origen='REVERSO_PROVEEDOR', pago_id=reverso.pk)
        self.assertEqual(compensacion.cuenta_id, usd.pk)
        self.assertEqual(compensacion.monto, Decimal('10.00'))


    def test_asignar_cuenta_desde_consulta_a_pago_existente(self):
        from bancos.models import Banco, CuentaBancaria, MovimientoInterno
        compra = self.preparar()
        pago = self.pagar(compra, tipo=4)
        cuenta = CuentaBancaria.objects.create(banco=Banco.objects.create(nombre='BANCO HISTÓRICO'),
            nro_cuenta='001', moneda='USD')
        consulta = reverse('pagos:consulta') + '?origen=PROVEEDOR'
        asignar = reverse('bancos:vincular_pago') + f'?origen=PROVEEDOR&pago_id={pago.pk}'
        self.assertContains(self.client.get(consulta), 'Asignar cuenta')
        respuesta = self.client.post(asignar, {'cuenta': cuenta.pk}, follow=True)
        self.assertContains(respuesta, str(cuenta))
        self.assertEqual(PagoProveedor.objects.filter(compra=compra).count(), 1)
        self.assertEqual(MovimientoInterno.objects.get(origen='PROVEEDOR', pago_id=pago.pk).monto, -pago.monto)
        otro = Banco.objects.create(nombre='OTRO BANCO')
        r = self.client.get(consulta, {'banco': cuenta.banco_id})
        self.assertEqual(r.context['pagina'].paginator.count, 1)
        self.assertEqual(r.context['totales']['salida_usd'], pago.monto)
        r = self.client.get(consulta, {'banco': otro.pk})
        self.assertEqual(r.context['pagina'].paginator.count, 0)
        self.assertEqual(r.context['totales']['salida_usd'], 0)
