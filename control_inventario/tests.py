import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase,Client
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction,connection,IntegrityError
from django.urls import reverse
from inventario.models import Producto,Proveedor,Compra,DetalleCompra
from inventario.services import actualizar_compra
from inventario.existencias import existencia_producto
from tasas_bcv.models import TasaBCV
from clientes.models import Cliente
from ventas_productos.servicios import registrar_venta,registrar_reverso
from ventas_productos.models import PorcentajeProducto
from .models import DocumentoAjuste,DetalleAjuste,CierreMensual,DetalleCierre,MovimientoStock
from .servicios import registrar_ajuste,iniciar_cierre,guardar_conteo,confirmar_cierre,cancelar_conteo,validar_fecha
from .saldos import reporte_stock,costo_producto

class ControlInventarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario=get_user_model().objects.create_superuser(username="control",password="prueba")
        cls.cliente=Cliente.objects.create(nombre="CLIENTE",apellido="CONTROL",telefono="04121234567")
        TasaBCV.objects.create(fecha=date(2026,10,10),tasa_bcv=40)
        cls.proveedor=Proveedor.objects.create(nombre="PROVEEDOR",rif="J-CONTROL")
        cls.producto=Producto.objects.create(codigo_producto="623",nombre_producto="CHAMPÚ")
        cls.otro=Producto.objects.create(codigo_producto="624",nombre_producto="PROMOCIÓN")
        for numero,fecha,cantidad,precio,divisa in [
            ("SEP",date(2026,9,15),10,2,"USD"),("OCT",date(2026,10,5),20,120,"BS")]:
            compra=Compra.objects.create(proveedor=cls.proveedor,numero_factura=numero,fecha_compra=fecha,
                divisa=divisa,tasa_cambio=40,registrada_por="control")
            DetalleCompra.objects.create(compra=compra,producto=cls.producto,cantidad=cantidad,precio_unitario=precio)
            actualizar_compra(compra.pk,"control",0)
        PorcentajeProducto.objects.create(producto=cls.producto,porcentaje=Decimal("233.33"))

    def setUp(self):self.client.force_login(self.usuario)
    def ajuste(self,tipo="SA",cantidad=2,producto=None,fecha=date(2026,10,12),clave=None):
        return registrar_ajuste(tipo=tipo,fecha=fecha,observacion="producto dañado" if tipo=="SA" else "promoción",
            lineas=[dict(producto=producto or self.producto,cantidad=Decimal(str(cantidad)))],
            usuario="control",clave=clave or uuid.uuid4())
    def venta(self,cantidad=5):
        return registrar_venta(fecha=date(2026,10,10),cliente=self.cliente,
            lineas=[dict(producto=self.producto,cantidad=Decimal(cantidad),precio_unitario_usd=Decimal(10))],
            pagos=[dict(tipo_pago="5",fecha=date(2026,10,10),monto=Decimal(cantidad)*Decimal("11.60"))],
            clave=uuid.uuid4(),usuario=self.usuario)
    def iniciar(self):
        with patch("control_inventario.servicios.timezone.localdate",return_value=date(2026,11,1)):
            return iniciar_cierre(periodo=date(2026,10,1),observacion="conteo",usuario="control")
    def contar(self,cierre,a,b):
        filas=list(cierre.detalles.all())
        guardar_conteo(cierre_id=cierre.pk,revision=cierre.revision,
            filas=[{"renglon":d.pk,"fisico":Decimal(str(a if d.producto_id==self.producto.pk else b))} for d in filas],
            ids_pagina=[d.pk for d in filas])
        cierre.refresh_from_db()
    def cerrar(self,a=24,b=4):
        cierre=self.iniciar();self.contar(cierre,a,b)
        return confirmar_cierre(cierre_id=cierre.pk,revision=cierre.revision,usuario="control")

    def test_entrada_y_salida_signos_y_costo_automatico(self):
        salida=self.ajuste("SA",2)
        self.assertEqual(existencia_producto(self.producto.pk),28)
        self.assertEqual(salida.detalles.get().costo_unitario_usd,Decimal("3"))
        entrada=self.ajuste("EN",4)
        self.assertEqual(existencia_producto(self.producto.pk),32)
        self.assertEqual(entrada.detalles.get().costo_unitario_usd,Decimal("3"))

    def test_costo_por_fecha_y_producto_sin_costo(self):
        self.assertEqual(costo_producto(self.producto.pk,date(2026,9,20))[0],2)
        self.assertEqual(costo_producto(self.producto.pk,date(2026,10,20))[0],3)
        doc=self.ajuste("EN",4,self.otro)
        self.assertEqual(doc.detalles.get().costo_unitario_usd,0)
        self.assertTrue(doc.detalles.get().sin_costo_previo)
        self.assertEqual(existencia_producto(self.otro.pk),4)

    def test_entrada_inicial_sin_costo_no_oculta_compra(self):
        # Se registra después de la compra, pero con fecha anterior a ella.
        doc=self.ajuste("EN",12,fecha=date(2026,9,1))
        self.assertEqual(doc.detalles.get().costo_unitario_usd,0)
        self.assertEqual(costo_producto(self.producto.pk,date(2026,9,1)),(Decimal("0.00"),True))
        self.assertEqual(costo_producto(self.producto.pk,date(2026,9,20))[0],2)
        self.assertEqual(costo_producto(self.producto.pk,date(2026,10,26))[0],3)
        fila=reporte_stock(date(2026,10,1)).get(pk=self.producto.pk)
        self.assertEqual(fila.costo,3)
        self.assertEqual(fila.disponible,42)
        from ventas_productos.precios import precio_producto
        self.assertEqual(precio_producto(self.producto,date(2026,10,26))["precio_unitario_usd"],Decimal("10.00"))

    def test_salida_sin_stock_no_registra_nada(self):
        with self.assertRaises(ValidationError):self.ajuste("SA",31)
        self.assertFalse(DocumentoAjuste.objects.exists())
        self.assertEqual(existencia_producto(self.producto.pk),30)

    def test_ajuste_idempotente(self):
        clave=uuid.uuid4()
        a=self.ajuste(clave=clave);b=self.ajuste(clave=clave)
        self.assertEqual(a.pk,b.pk)
        self.assertEqual(existencia_producto(self.producto.pk),28)

    def test_documento_y_detalle_inmutables_sql(self):
        doc=self.ajuste()
        for tabla in ["documentoajuste","detalleajuste"]:
            for operacion in ["UPDATE","DELETE"]:
                with self.subTest(tabla=tabla,operacion=operacion),self.assertRaises(IntegrityError),transaction.atomic(),connection.cursor() as c:
                    c.execute(f"UPDATE control_inventario_{tabla} SET id=id" if operacion=="UPDATE" else f"DELETE FROM control_inventario_{tabla}")

    def test_stock_mensual_con_inicial_compras_ventas_y_otros(self):
        self.venta();self.ajuste("SA",2);self.ajuste("EN",3)
        p=reporte_stock(date(2026,10,1)).get(pk=self.producto.pk)
        self.assertEqual((p.inicial,p.compras,p.ventas,p.otros,p.disponible),(10,20,5,1,26))
        self.assertEqual(existencia_producto(self.producto.pk),26)

    def test_reverso_suma_stock_y_resta_ventas_netas(self):
        original=self.venta()
        registrar_reverso(documento_id=original.pk,motivo="CORRECCIÓN",usuario=self.usuario)
        p=reporte_stock(date(2026,10,1)).get(pk=self.producto.pk)
        self.assertEqual((p.ventas,p.disponible),(0,30))

    def test_venta_usa_entradas_adicionales_y_bloquea_salidas(self):
        self.ajuste("EN",5)
        self.venta(32)
        self.assertEqual(existencia_producto(self.producto.pk),3)
        with self.assertRaises(ValidationError):self.venta(4)

    def test_venta_descuenta_salidas_adicionales(self):
        self.ajuste("SA",29)
        with self.assertRaises(ValidationError):self.venta(2)
        self.assertEqual(existencia_producto(self.producto.pk),1)

    def test_cierre_generados_entrada_salida_e_inicial_noviembre(self):
        self.venta();self.ajuste("SA",2);self.ajuste("EN",3)
        cierre=self.cerrar(24,4)
        self.assertEqual(cierre.estado,"C")
        self.assertEqual(cierre.ajustes.count(),2)
        d=cierre.detalles.get(producto=self.producto)
        self.assertEqual((d.inicial,d.compras,d.ventas,d.otros,d.teorico,d.fisico,d.diferencia),(10,20,5,1,26,24,-2))
        noviembre=reporte_stock(date(2026,11,1)).get(pk=self.producto.pk)
        self.assertEqual((noviembre.inicial,noviembre.disponible),(24,24))
        self.assertEqual(existencia_producto(self.producto.pk),24)
        self.assertEqual(existencia_producto(self.otro.pk),4)
        octubre=reporte_stock(date(2026,10,1)).get(pk=self.producto.pk)
        self.assertEqual(octubre.otros,-1)
        self.assertEqual(octubre.disponible,24)

    def test_cierre_sin_diferencias_no_crea_documentos(self):
        cierre=self.cerrar(30,0)
        self.assertEqual(cierre.ajustes.count(),0)
        self.assertEqual(existencia_producto(self.producto.pk),30)

    def test_cerrar_dos_veces_no_duplica(self):
        cierre=self.cerrar(28,4)
        cantidad=DocumentoAjuste.objects.count()
        confirmar_cierre(cierre_id=cierre.pk,revision=0,usuario="control")
        self.assertEqual(DocumentoAjuste.objects.count(),cantidad)
        self.assertEqual(existencia_producto(self.producto.pk),28)

    def test_cierre_requiere_todos_los_fisicos(self):
        cierre=self.iniciar()
        with self.assertRaises(ValidationError):confirmar_cierre(cierre_id=cierre.pk,revision=0,usuario="control")
        self.assertEqual(DocumentoAjuste.objects.count(),0)
        cierre.refresh_from_db()
        self.assertEqual((cierre.estado,cierre.revision),("B",0))

    def test_conteo_revision_obsoleta_y_cambio_ids(self):
        cierre=self.iniciar();self.contar(cierre,29,0)
        with self.assertRaises(ValidationError):
            guardar_conteo(cierre_id=cierre.pk,revision=0,filas=[],ids_pagina=[])
        with self.assertRaises(ValidationError):
            guardar_conteo(cierre_id=cierre.pk,revision=cierre.revision,
                filas=[{"renglon":999,"fisico":1}],ids_pagina=[cierre.detalles.first().pk])

    def test_conteo_congela_periodo_pero_no_mes_siguiente(self):
        cierre=self.iniciar()
        with self.assertRaises(ValidationError):self.ajuste()
        with self.assertRaises(ValidationError):self.venta()
        validar_fecha(date(2026,11,2))
        with self.assertRaises(ValidationError):validar_fecha(date(2026,9,1))
        cancelar_conteo(cierre_id=cierre.pk,revision=0)
        self.ajuste()
        self.assertEqual(existencia_producto(self.producto.pk),28)

    def test_cierre_bloquea_mes_y_meses_anteriores(self):
        self.cerrar(30,0)
        for fecha in [date(2026,9,1),date(2026,10,31)]:
            with self.subTest(fecha=fecha),self.assertRaises(ValidationError):validar_fecha(fecha)
        validar_fecha(date(2026,11,1))
        compra=Compra.objects.create(proveedor=self.proveedor,numero_factura="TARDIA",fecha_compra=date(2026,10,20),tasa_cambio=40,registrada_por="control")
        DetalleCompra.objects.create(compra=compra,producto=self.producto,cantidad=1,precio_unitario=1)
        with self.assertRaises(ValidationError):actualizar_compra(compra.pk,"control",0)
        self.assertEqual(existencia_producto(self.producto.pk),30)

    def test_cierres_consecutivos_y_mes_no_terminado(self):
        with patch("control_inventario.servicios.timezone.localdate",return_value=date(2026,10,25)):
            with self.assertRaises(ValidationError):iniciar_cierre(periodo=date(2026,10,1),observacion="",usuario="control")
        self.cerrar(30,0)
        with patch("control_inventario.servicios.timezone.localdate",return_value=date(2027,1,1)):
            with self.assertRaises(ValidationError):iniciar_cierre(periodo=date(2026,12,1),observacion="",usuario="control")
            noviembre=iniciar_cierre(periodo=date(2026,11,1),observacion="",usuario="control")
        self.assertEqual(noviembre.detalles.get(producto=self.producto).inicial,30)

    def test_historico_no_cambia_ante_movimientos_del_mes_siguiente(self):
        cierre=self.cerrar(28,0)
        self.ajuste("EN",5,fecha=date(2026,11,2))
        self.assertEqual(cierre.detalles.get(producto=self.producto).fisico,28)
        p=reporte_stock(date(2026,11,1)).get(pk=self.producto.pk)
        self.assertEqual((p.inicial,p.otros,p.disponible),(28,5,33))
        self.assertEqual(existencia_producto(self.producto.pk),33)

    def test_historico_sql_inmutable(self):
        cierre=self.cerrar(30,0)
        with self.assertRaises(IntegrityError),transaction.atomic():
            DetalleCierre.objects.filter(cierre=cierre).update(fisico=1)
        with self.assertRaises(IntegrityError),transaction.atomic():
            CierreMensual.objects.filter(pk=cierre.pk).update(observacion="CAMBIO")
        with self.assertRaises(IntegrityError),transaction.atomic():
            CierreMensual.objects.filter(pk=cierre.pk).delete()

    def test_snapshot_teorico_inmutable_antes_de_cerrar(self):
        cierre=self.iniciar()
        with self.assertRaises(IntegrityError),transaction.atomic():
            cierre.detalles.update(teorico=999)

    def test_cierre_con_ajuste_negativo_imposible_revierte_todo(self):
        self.venta(29)
        cierre=self.iniciar();self.contar(cierre,0,4)
        # Movimiento posterior permitido: consume el remanente actual de otro mes.
        self.ajuste("SA",1,fecha=date(2026,11,2))
        with self.assertRaises(ValidationError):
            confirmar_cierre(cierre_id=cierre.pk,revision=cierre.revision,usuario="control")
        cierre.refresh_from_db()
        self.assertEqual(cierre.estado,"B")
        self.assertFalse(DocumentoAjuste.objects.filter(cierre=cierre).exists())
        self.assertEqual(existencia_producto(self.otro.pk),0)

    def test_modal_rojo_de_stock_con_acciones(self):
        datos={"fecha":"2026-10-10","cliente":self.cliente.pk,"clave":str(uuid.uuid4()),
            "lineas-TOTAL_FORMS":"1","lineas-INITIAL_FORMS":"0","lineas-0-producto":self.producto.pk,
            "lineas-0-cantidad":"31","lineas-0-precio_unitario_usd":"10",
            "pagos-TOTAL_FORMS":"1","pagos-INITIAL_FORMS":"0","pagos-0-tipo_pago":"5",
            "pagos-0-fecha":"2026-10-10","pagos-0-monto":"359.60"}
        r=self.client.post(reverse("ventas_productos:nueva"),datos)
        self.assertEqual(r.status_code,200)
        self.assertContains(r,'id="aviso-existencias"')
        self.assertContains(r,"EXISTENCIAS INSUFICIENTES")
        self.assertContains(r,"Cambiar cantidad")
        self.assertContains(r,"Cancelar venta")
        self.assertContains(r,"#dc3545")
        self.assertEqual(existencia_producto(self.producto.pk),30)

    def test_web_registrar_y_buscar_costo(self):
        datos={"tipo":"SA","fecha":"2026-10-12","observacion":"roto","clave":str(uuid.uuid4()),
            "lineas-TOTAL_FORMS":"1","lineas-INITIAL_FORMS":"0",
            "lineas-0-producto":self.producto.pk,"lineas-0-cantidad":"2","lineas-0-costo_unitario_usd":"999"}
        r=self.client.post(reverse("control_inventario:nuevo"),datos)
        self.assertEqual(r.status_code,302)
        self.assertEqual(DetalleAjuste.objects.get().costo_unitario_usd,3)
        r=self.client.get(reverse("control_inventario:costo"),{"producto":self.producto.pk,"fecha":"2026-10-12"})
        self.assertEqual(Decimal(r.json()["costo"]),3)

    def test_web_pantallas_y_filtros(self):
        doc=self.ajuste()
        for ruta in ["stock","documentos","nuevo","cierres"]:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(reverse("control_inventario:"+ruta)).status_code,200)
        self.assertEqual(self.client.get(reverse("control_inventario:ver",args=[doc.pk])).status_code,200)
        self.assertEqual(len(self.client.get(reverse("control_inventario:documentos"),{"q":"623"}).context["pagina"]),1)
        r=self.client.get(reverse("control_inventario:stock"),{"periodo":"2026-10","q":"CHAMPÚ"})
        self.assertEqual(len(r.context["pagina"]),1)
        cierre=self.iniciar()
        self.assertEqual(self.client.get(reverse("control_inventario:conteo",args=[cierre.pk])).status_code,200)

    def test_web_captura_fisico_conserva_cero(self):
        cierre=self.iniciar();filas=list(cierre.detalles.all())
        datos={"revision":0,"conteo-TOTAL_FORMS":len(filas),"conteo-INITIAL_FORMS":len(filas)}
        for i,d in enumerate(filas):
            datos[f"conteo-{i}-renglon"]=d.pk;datos[f"conteo-{i}-fisico"]="0"
        r=self.client.post(reverse("control_inventario:conteo",args=[cierre.pk]),datos)
        self.assertEqual(r.status_code,302)
        self.assertEqual(cierre.detalles.filter(fisico=0).count(),2)

    def test_autenticacion_csrf_y_cierre_solo_post(self):
        c=Client()
        self.assertEqual(c.get(reverse("control_inventario:stock")).status_code,302)
        c=Client(enforce_csrf_checks=True);c.force_login(self.usuario)
        self.assertEqual(c.post(reverse("control_inventario:nuevo"),{}).status_code,403)
        cierre=self.iniciar()
        self.assertEqual(self.client.get(reverse("control_inventario:cerrar",args=[cierre.pk])).status_code,405)

    def test_conteo_paginado_y_busqueda_no_omite_pendientes(self):
        Producto.objects.bulk_create([Producto(codigo_producto=f"PAG-{i:03}",nombre_producto="PAGINADO") for i in range(30)])
        cierre=self.iniciar()
        r=self.client.get(reverse("control_inventario:conteo",args=[cierre.pk]),{"page":2})
        self.assertEqual(len(r.context["pagina"]),7)
        self.assertEqual(r.context["pendientes"],32)
        r=self.client.get(reverse("control_inventario:conteo",args=[cierre.pk]),{"q":"623"})
        self.assertEqual(len(r.context["pagina"]),1)
        self.assertEqual(r.context["pendientes"],32)

    def test_no_se_puede_mover_el_periodo_de_un_conteo(self):
        cierre=self.iniciar()
        with self.assertRaises(IntegrityError),transaction.atomic():
            CierreMensual.objects.filter(pk=cierre.pk).update(periodo=date(2026,11,1))

    def test_cierre_noviembre_arrastra_octubre_y_genera_historico_nuevo(self):
        octubre=self.cerrar(28,0)
        self.ajuste("EN",5,fecha=date(2026,11,2))
        with patch("control_inventario.servicios.timezone.localdate",return_value=date(2026,12,1)):
            noviembre=iniciar_cierre(periodo=date(2026,11,1),observacion="NOVIEMBRE",usuario="control")
        self.assertEqual(noviembre.detalles.get(producto=self.producto).inicial,28)
        self.contar(noviembre,32,0)
        confirmar_cierre(cierre_id=noviembre.pk,revision=noviembre.revision,usuario="control")
        self.assertEqual(CierreMensual.objects.filter(estado="C").count(),2)
        self.assertEqual(octubre.detalles.get(producto=self.producto).fisico,28)
        diciembre=reporte_stock(date(2026,12,1)).get(pk=self.producto.pk)
        self.assertEqual(diciembre.inicial,32)
        self.assertEqual(existencia_producto(self.producto.pk),32)
