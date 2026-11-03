from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from barberos.models import Barbero
from . import tests as base
from .servicios import registrar_reverso


class PrestadorVentaTests(TestCase):
    setUpTestData = classmethod(base.VentaProductosTests.setUpTestData.__func__)
    setUp = base.VentaProductosTests.setUp
    venta = base.VentaProductosTests.venta
    def prestador(self, activo=True):
        return Barbero.objects.create(codigo='PR', nombre='PRESTADOR', apellido='UNO', direccion='A',
                                      telefono='1', fecha_ingreso=timezone.localdate(), porcentaje=50, activo=activo)

    def test_venta_y_reverso_conservan_prestador(self):
        prestador = self.prestador()
        venta = self.venta(prestador=prestador)
        reverso = registrar_reverso(documento_id=venta.pk, motivo='PRUEBA', usuario=self.usuario)
        self.assertEqual(venta.prestador_id, prestador.pk)
        self.assertEqual(reverso.prestador_id, prestador.pk)

    def test_prestador_inactivo_no_puede_vender(self):
        prestador = self.prestador(activo=False)
        with self.assertRaises(ValidationError):
            self.venta(prestador=prestador)

    def test_reporte_aplica_escala_del_periodo_y_excluye_reverso(self):
        from django.urls import reverse
        from .models import EscalaComisionProducto
        prestador = self.prestador()
        venta = self.venta(prestador=prestador)
        EscalaComisionProducto.objects.create(unidades=2, porcentaje=10)
        datos = {'prestador': prestador.pk, 'desde': '2026-10-20', 'hasta': '2026-10-20'}
        respuesta = self.client.get(reverse('ventas_productos:reporte_prestador'), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['resumen']['comision_usd'], 2)
        self.assertContains(respuesta, str(venta))
        from datetime import date
        from unittest.mock import patch
        with patch('ventas_productos.servicios.timezone.localdate', return_value=date(2026, 10, 20)):
            registrar_reverso(documento_id=venta.pk, motivo='PRUEBA', usuario=self.usuario)
        respuesta = self.client.get(reverse('ventas_productos:reporte_prestador'), datos)
        self.assertIsNone(respuesta.context['resumen'])
        self.assertNotContains(respuesta, str(venta))

    def test_reporte_sin_escala_indica_configuracion(self):
        from django.urls import reverse
        prestador = self.prestador()
        self.venta(prestador=prestador)
        r = self.client.get(reverse('ventas_productos:reporte_prestador'),
                            {'prestador': prestador.pk, 'desde': '2026-10-20', 'hasta': '2026-10-20'})
        self.assertContains(r, 'No hay una escala de comisión')

    def test_prepara_comision_del_periodo_con_distribucion_exacta(self):
        from datetime import date
        from decimal import Decimal
        from liquidaciones.comisiones_productos import pendientes_productos
        from .models import EscalaComisionProducto
        prestador = self.prestador()
        self.venta(prestador=prestador)
        EscalaComisionProducto.objects.create(unidades=2, porcentaje=10)
        datos = pendientes_productos(prestador, date(2026, 10, 20), date(2026, 10, 20), date(2026, 10, 20))
        self.assertEqual(datos['resumen']['unidades'], Decimal('2.00'))
        self.assertEqual(datos['resumen']['comision_usd'], Decimal('2.00'))
        self.assertEqual(sum(v['comision_usd'] for v in datos['ventas']), datos['resumen']['comision_usd'])
        self.assertEqual(datos['total_reintegros_usd'], Decimal('0.00'))

    def test_prepara_comision_sin_escala_falla(self):
        from datetime import date
        from liquidaciones.comisiones_productos import pendientes_productos
        prestador = self.prestador()
        self.venta(prestador=prestador)
        with self.assertRaises(ValidationError):
            pendientes_productos(prestador, date(2026, 10, 20), date(2026, 10, 20), date(2026, 10, 20))

    def test_liquida_productos_y_descuenta_reverso_una_sola_vez(self):
        from datetime import date
        from decimal import Decimal
        from unittest.mock import patch
        import uuid
        from liquidaciones.servicios import registrar
        from liquidaciones.models import ReintegroComisionProducto
        from tasas_bcv.models import TasaBCV
        from .models import EscalaComisionProducto
        dia1, dia2 = date(2026, 10, 20), date(2026, 10, 21)
        prestador = self.prestador()
        escala = EscalaComisionProducto.objects.create(unidades=1, porcentaje=10)
        venta = self.venta(prestador=prestador)
        pago = lambda monto, fecha: [{'tipo_pago': '5', 'monto': Decimal(monto), 'fecha': fecha}]
        primero = registrar(prestador_id=prestador.pk, desde=dia1, hasta=dia1, fecha=dia1,
                            seleccion=[], pagos=pago('2.00', dia1), clave=uuid.uuid4(),
                            usuario=self.usuario, incluir_productos=True)
        self.assertEqual(primero.total_comision_usd, Decimal('2.00'))
        self.assertEqual(primero.periodo_productos.ventas.get().venta_id, venta.pk)
        with self.assertRaises(ValidationError):
            self.venta(prestador=prestador)
        with self.assertRaises(ValidationError):
            registrar(prestador_id=prestador.pk, desde=dia1, hasta=dia1, fecha=dia1,
                      seleccion=[], pagos=pago('2.00', dia1), clave=uuid.uuid4(),
                      usuario=self.usuario, incluir_productos=True)
        escala.porcentaje = 20
        escala.save()
        TasaBCV.objects.get_or_create(fecha=dia2, defaults={'tasa_bcv': 40})
        with patch('ventas_productos.servicios.timezone.localdate', return_value=dia2):
            registrar_reverso(documento_id=venta.pk, motivo='PRUEBA', usuario=self.usuario)
        self.venta(prestador=prestador, fecha=dia2,
                   lineas=[dict(producto=self.producto, cantidad=Decimal('3'), precio_unitario_usd=Decimal('10'))],
                   pagos=[dict(tipo_pago='5', monto=Decimal('34.80'), fecha=dia2)])
        segundo = registrar(prestador_id=prestador.pk, desde=dia2, hasta=dia2, fecha=dia2,
                           seleccion=[], pagos=pago('4.00', dia2), clave=uuid.uuid4(),
                           usuario=self.usuario, incluir_productos=True)
        self.assertEqual(segundo.total_comision_usd, Decimal('4.00'))
        self.assertEqual(ReintegroComisionProducto.objects.get(liquidacion=segundo).monto_usd, Decimal('-2.00'))

    def test_formulario_liquida_solo_productos_y_conserva_historico(self):
        from datetime import date
        import uuid
        from django.urls import reverse
        from .models import EscalaComisionProducto
        from liquidaciones.models import Liquidacion
        from bancos.models import Banco, CuentaBancaria, MovimientoInterno
        cuenta = CuentaBancaria.objects.create(banco=Banco.objects.create(nombre='BANCO LIQ'), nro_cuenta='001', moneda='USD')
        prestador = self.prestador()
        venta = self.venta(prestador=prestador)
        escala = EscalaComisionProducto.objects.create(unidades=1, porcentaje=10)
        datos = {'prestador': prestador.pk, 'desde': '2026-10-20', 'hasta': '2026-10-20',
                 'fecha_cancelacion': '2026-10-20', 'incluir_productos': 'on'}
        respuesta = self.client.get(reverse('liquidaciones:crear'), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Comisión por ventas de productos')
        datos.update({'clave': str(uuid.uuid4()), 'pagos-TOTAL_FORMS': '1', 'pagos-INITIAL_FORMS': '0',
                      'pagos-0-cuenta_bancaria': cuenta.pk, 'pagos-0-tipo_pago': '4', 'pagos-0-monto': '2.00', 'pagos-0-fecha': '2026-10-20'})
        respuesta = self.client.post(reverse('liquidaciones:crear'), datos)
        self.assertEqual(respuesta.status_code, 302, respuesta.content[:1000])
        liq = Liquidacion.objects.get(periodo_productos__prestador=prestador)
        self.assertEqual(liq.periodo_productos.ventas.get().venta_id, venta.pk)
        self.assertEqual(MovimientoInterno.objects.get(cuenta=cuenta, origen='PRESTADOR').monto, -2)
        detalle = self.client.get(reverse('liquidaciones:ver', args=[liq.pk]))
        self.assertContains(detalle, 'Fecha de factura')
        self.assertContains(detalle, 'Total unidades')
        self.assertContains(detalle, 'Monto factura Bs.')
        self.assertContains(detalle, venta.descripcion_cliente)
        self.assertContains(detalle, reverse('ventas_productos:ver', args=[venta.pk]))
        escala.porcentaje = 50
        escala.save()
        r = self.client.get(reverse('ventas_productos:reporte_prestador'),
                            {'prestador': prestador.pk, 'desde': '2026-10-20', 'hasta': '2026-10-20'})
        self.assertTrue(r.context['cerrado'])
        self.assertEqual(r.context['resumen']['porcentaje'], 10)
        self.assertContains(r, 'liquidada')

    def test_periodos_solapados_y_venta_en_periodo_cerrado_se_rechazan(self):
        from datetime import date
        from decimal import Decimal
        import uuid
        from liquidaciones.servicios import registrar
        from .models import EscalaComisionProducto
        prestador = self.prestador()
        self.venta(prestador=prestador)
        EscalaComisionProducto.objects.create(unidades=1, porcentaje=10)
        datos = dict(prestador_id=prestador.pk, desde=date(2026, 10, 20), hasta=date(2026, 10, 20),
                     fecha=date(2026, 10, 20), seleccion=[],
                     pagos=[dict(tipo_pago='5', monto=Decimal('2'), fecha=date(2026, 10, 20))],
                     usuario=self.usuario, incluir_productos=True)
        registrar(**datos, clave=uuid.uuid4())
        with self.assertRaises(ValidationError):
            registrar(**datos, clave=uuid.uuid4())
        with self.assertRaises(ValidationError):
            self.venta(prestador=prestador)

    def test_proteccion_sql_impide_alterar_comision_liquidada(self):
        from datetime import date
        from decimal import Decimal
        from django.db import connection, transaction, IntegrityError
        import uuid
        from liquidaciones.servicios import registrar
        from .models import EscalaComisionProducto
        with connection.cursor() as c:
            if connection.vendor == 'mysql':
                c.execute("SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND trigger_name='lcp_venta_update'")
            else:
                c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='inmutable_liquidaciones_comisionventaproducto_update'")
            if not c.fetchone()[0]:
                self.skipTest('La prueba requiere disparadores de protección SQL.')
        prestador = self.prestador()
        self.venta(prestador=prestador)
        EscalaComisionProducto.objects.create(unidades=1, porcentaje=10)
        d = date(2026, 10, 20)
        liquidacion = registrar(prestador_id=prestador.pk, desde=d, hasta=d, fecha=d, seleccion=[],
            pagos=[dict(tipo_pago='5', monto=Decimal('2'), fecha=d)], clave=uuid.uuid4(),
            usuario=self.usuario, incluir_productos=True)
        comision = liquidacion.periodo_productos.ventas.get()
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as c:
            c.execute('UPDATE liquidaciones_comisionventaproducto SET comision_usd=%s WHERE id=%s', [999, comision.pk])

    def test_liquidacion_combina_servicios_y_productos(self):
        from datetime import date
        from decimal import Decimal
        import uuid
        from servicios.models import Servicio
        from ventas.servicios import registrar_venta as vender_servicio
        from liquidaciones.servicios import registrar
        from .models import EscalaComisionProducto
        d = date(2026, 10, 20)
        prestador = self.prestador()
        self.venta(prestador=prestador)
        EscalaComisionProducto.objects.create(unidades=1, porcentaje=10)
        servicio = Servicio.objects.create(codigo='COM', nombre='CORTE', precio=116, duracion=30, retencion_impuesto=True)
        factura = vender_servicio(fecha=d, cliente=self.cliente, clave=uuid.uuid4(), usuario=self.usuario,
            lineas=[dict(servicio=servicio, barbero=prestador, cantidad_servicio=1)],
            pagos=[dict(tipo_pago='5', fecha=d, monto=Decimal('116'))])
        liquidacion = registrar(prestador_id=prestador.pk, desde=d, hasta=d, fecha=d,
            seleccion=[factura.detalles.get().pk], pagos=[dict(tipo_pago='5', fecha=d, monto=Decimal('60'))],
            clave=uuid.uuid4(), usuario=self.usuario, incluir_productos=True)
        self.assertEqual(liquidacion.total_comision_usd, Decimal('60.00'))
        self.assertEqual(liquidacion.periodo_productos.comision_usd, Decimal('2.00'))
        self.assertEqual(liquidacion.detalles.get().comision_usd, Decimal('58.00'))

    def test_consulta_porcentajes_muestra_costo_recargo_y_precio(self):
        from django.urls import reverse
        from decimal import Decimal
        r = self.client.get(reverse('ventas_productos:porcentajes'))
        self.assertEqual(r.status_code, 200)
        regla = next(x for x in r.context['pagina'] if x.producto_id == self.producto.pk)
        self.assertEqual(regla.ultimo_costo_usd, Decimal('4.00'))
        self.assertEqual(regla.recargo_usd, Decimal('6.00'))
        self.assertEqual(regla.precio_venta_usd, Decimal('10.00'))
        self.assertContains(r, 'Precio de venta USD')
        self.assertNotContains(r, 'ID producto')
        self.assertContains(r, 'type="checkbox" disabled aria-label="Activo"')


    def test_liquida_servicios_con_casilla_productos_ya_liquidados(self):
        from datetime import date
        from decimal import Decimal
        import uuid
        from django.urls import reverse
        from servicios.models import Servicio
        from ventas.servicios import registrar_venta
        from liquidaciones.servicios import registrar
        from liquidaciones.models import ComisionVentaProducto, PeriodoComisionProductos
        from .models import EscalaComisionProducto
        dia = date(2026, 10, 20)
        prestador = self.prestador()
        self.venta(prestador=prestador)
        EscalaComisionProducto.objects.create(unidades=1, porcentaje=10)
        registrar(prestador_id=prestador.pk, desde=dia, hasta=dia, fecha=dia,
            seleccion=[], pagos=[dict(tipo_pago='5', monto=Decimal('2.00'), fecha=dia)],
            clave=uuid.uuid4(), usuario=self.usuario, incluir_productos=True)
        servicio = Servicio.objects.create(codigo='POST-PROD', nombre='SERVICIO', precio=10, duracion=30)
        factura = registrar_venta(fecha=dia, cliente=self.cliente,
            lineas=[dict(barbero=prestador, servicio=servicio, cantidad_servicio=1)],
            pagos=[dict(tipo_pago='5', fecha=dia, monto=Decimal('11.60'))],
            clave=uuid.uuid4(), usuario=self.usuario)
        r = self.client.get(reverse('liquidaciones:crear'), dict(prestador=prestador.pk,
            desde='2026-10-20', hasta='2026-10-20', fecha_cancelacion='2026-10-20', incluir_productos='on'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['errores'])
        self.assertEqual(r.context['productos']['ventas'], [])
        self.assertContains(r, 'Puedes continuar con los servicios seleccionados.')
        liquidacion = registrar(prestador_id=prestador.pk, desde=dia, hasta=dia, fecha=dia,
            seleccion=[factura.detalles.get().pk], pagos=[dict(tipo_pago='5', monto=Decimal('5.00'), fecha=dia)],
            clave=uuid.uuid4(), usuario=self.usuario, incluir_productos=True)
        self.assertTrue(liquidacion.sellado)
        self.assertEqual(liquidacion.total_comision_usd, Decimal('5.00'))
        self.assertEqual(ComisionVentaProducto.objects.count(), 1)
        self.assertEqual(PeriodoComisionProductos.objects.count(), 1)
        with self.assertRaises(ValidationError):
            registrar(prestador_id=prestador.pk, desde=dia, hasta=dia, fecha=dia,
                seleccion=[], pagos=[dict(tipo_pago='5', monto=Decimal('2.00'), fecha=dia)],
                clave=uuid.uuid4(), usuario=self.usuario, incluir_productos=True)
