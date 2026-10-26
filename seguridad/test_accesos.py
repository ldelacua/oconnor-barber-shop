from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, SimpleTestCase, override_settings, RequestFactory
from django.urls import reverse, URLPattern, URLResolver, get_resolver
from django.contrib.auth.models import AnonymousUser
from clientes.models import Cliente
from .accesos import reglas, permitido, PROTEGIDOS
from .middleware import PermisosModulosMiddleware
from .checks import comprobar_permisos

MW=[m for m in settings.MIDDLEWARE if m!='seguridad.middleware.PermisosModulosMiddleware']+['seguridad.middleware.PermisosModulosMiddleware']


@override_settings(MIDDLEWARE=MW,SILENCED_SYSTEM_CHECKS=[])
class AccesosTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user(username='operador',password='prueba')
        self.client.force_login(self.user)

    def grant(self,*codigos,usuario=None):
        u=usuario or self.user
        for codigo in codigos:
            app,codename=codigo.split('.')
            u.user_permissions.add(Permission.objects.get(content_type__app_label=app,codename=codename))

    def test_sin_permisos_niega_modulos_get_y_post(self):
        rutas=['clientes:lista_clientes','barberos:lista_barberos','servicios:lista','horarios:listar_horarios','citas:listar_citas',
               'tasas_bcv:lista','ventas:lista','liquidaciones:lista','gastos:inicio','inventario:compras','ventas_productos:lista','control_inventario:stock']
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(reverse(ruta)).status_code,403)
        n=Cliente.objects.count()
        self.assertEqual(self.client.post(reverse('clientes:crear_cliente'),{'nombre':'NO AUTORIZADO'}).status_code,403)
        self.assertEqual(Cliente.objects.count(),n)

    def test_consulta_no_permita_crear_ni_editar(self):
        self.grant('clientes.view_cliente')
        c=Cliente.objects.create(nombre='ORIGINAL',apellido='CLIENTE',telefono='123')
        self.assertEqual(self.client.get(reverse('clientes:lista_clientes')).status_code,200)
        self.assertEqual(self.client.get(reverse('clientes:crear_cliente')).status_code,403)
        self.assertEqual(self.client.post(reverse('clientes:editar_cliente',args=[c.pk]),{'nombre':'ALTERADO'}).status_code,403)
        c.refresh_from_db();self.assertEqual(c.nombre,'ORIGINAL')

    def test_creacion_requiere_consulta_y_agregar(self):
        self.grant('clientes.add_cliente')
        self.assertEqual(self.client.get(reverse('clientes:crear_cliente')).status_code,403)
        self.grant('clientes.view_cliente')
        self.assertEqual(self.client.get(reverse('clientes:crear_cliente')).status_code,200)

    def test_grupos_conceden_y_revocan_acceso(self):
        g=Group.objects.create(name='Consulta de clientes')
        g.permissions.add(Permission.objects.get(content_type__app_label='clientes',codename='view_cliente'))
        self.user.groups.add(g)
        self.assertEqual(self.client.get(reverse('clientes:lista_clientes')).status_code,200)
        g.permissions.clear()
        self.assertEqual(self.client.get(reverse('clientes:lista_clientes')).status_code,403)

    def test_dashboard_y_menu_no_exponen_datos_ni_opciones(self):
        r=self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code,200)
        self.assertNotContains(r,'Ventas del día')
        self.assertNotContains(r,'href="'+reverse('clientes:lista_clientes')+'"')
        self.assertNotContains(r,'href="'+reverse('admin:index')+'"')
        self.grant('clientes.view_cliente')
        r=self.client.get(reverse('dashboard'))
        self.assertContains(r,'href="'+reverse('clientes:lista_clientes')+'"')
        self.assertNotContains(r,'href="'+reverse('ventas:lista')+'"')

    def test_dashboard_estadistica_solo_con_permiso_correspondiente(self):
        self.grant('ventas.view_documentoventa')
        r=self.client.get(reverse('dashboard'))
        self.assertContains(r,'Ventas del día')
        self.assertNotContains(r,'dashboard-icon text-success')

    def test_anonimo_redirige_login_y_usuario_inactivo_no_accede(self):
        self.client.logout()
        r=self.client.get(reverse('inventario:compras'))
        self.assertEqual(r.status_code,302)
        self.assertIn('next=',r['Location'])
        self.user.is_active=False;self.user.save();self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('inventario:compras')).status_code,302)

    def test_ajax_no_autorizado_responde_json_403(self):
        r=self.client.get(reverse('ventas:cotizacion'),HTTP_ACCEPT='application/json')
        self.assertEqual(r.status_code,403)
        self.assertIn('error',r.json())

    def test_vendedor_busca_clientes_sin_abrir_modulo_clientes(self):
        self.grant('ventas.view_documentoventa','ventas.add_documentoventa')
        self.assertEqual(self.client.get(reverse('citas:buscar_clientes'),{'q':'PR'}).status_code,200)
        self.assertEqual(self.client.get(reverse('clientes:lista_clientes')).status_code,403)
        self.assertEqual(self.client.get(reverse('ventas:crear')).status_code,200)

    def test_vendedor_productos_busca_sin_abrir_compras(self):
        self.grant('ventas_productos.view_documentoproducto','ventas_productos.add_documentoproducto')
        self.assertEqual(self.client.get(reverse('inventario:buscar_productos'),{'q':'PR'}).status_code,200)
        self.assertEqual(self.client.get(reverse('ventas_productos:nueva')).status_code,200)
        self.assertEqual(self.client.get(reverse('inventario:compras')).status_code,403)

    def test_reverso_y_actualizacion_requieren_permisos_de_accion(self):
        self.grant('ventas.view_documentoventa','ventas_productos.view_documentoproducto','inventario.view_compra')
        for ruta in ['ventas:reversar','ventas_productos:reversar','inventario:actualizar']:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.post(reverse(ruta,args=[999])).status_code,403)

    def test_consulta_ventas_productos_no_revela_costo_por_api_de_precio(self):
        self.grant('ventas_productos.view_documentoproducto')
        r=self.client.get(reverse('ventas_productos:precio'),HTTP_ACCEPT='application/json')
        self.assertEqual(r.status_code,403)

    def test_catalogos_gastos_separados(self):
        self.grant('gastos.view_proveedor')
        self.assertEqual(self.client.get(reverse('gastos:catalogo',kwargs={'catalogo':'proveedores'})).status_code,200)
        self.assertEqual(self.client.get(reverse('gastos:catalogo',kwargs={'catalogo':'tipos'})).status_code,403)

    def test_consulta_horarios_no_permite_post_en_misma_ruta(self):
        self.grant('horarios.view_horario','horarios.change_horario')
        self.assertEqual(self.client.get(reverse('horarios:listar_horarios')).status_code,200)
        self.assertEqual(self.client.post(reverse('horarios:listar_horarios'),{}).status_code,403)
        self.grant('horarios.add_horario')
        self.assertEqual(self.client.post(reverse('horarios:listar_horarios'),{}).status_code,200)

    def test_consulta_cierres_no_permite_iniciar_ni_guardar_conteo(self):
        self.grant('control_inventario.view_cierremensual')
        self.assertEqual(self.client.get(reverse('control_inventario:cierres')).status_code,200)
        self.assertEqual(self.client.post(reverse('control_inventario:cierres'),{}).status_code,403)
        self.assertEqual(self.client.post(reverse('control_inventario:conteo',args=[999]),{}).status_code,403)

    def test_menu_cierres_sin_stock_y_productos_sin_compras(self):
        self.grant('control_inventario.view_cierremensual','inventario.view_producto')
        r=self.client.get(reverse('dashboard'))
        self.assertContains(r,'href="'+reverse('control_inventario:cierres')+'"')
        self.assertContains(r,'href="'+reverse('inventario:productos')+'"')
        self.assertNotContains(r,'href="'+reverse('control_inventario:stock')+'"')
        self.assertNotContains(r,'href="'+reverse('inventario:compras')+'"')

    def test_consulta_stock_tiene_permiso_independiente(self):
        self.grant('control_inventario.view_movimientostock')
        self.assertEqual(self.client.get(reverse('control_inventario:stock')).status_code,200)
        self.assertEqual(self.client.get(reverse('control_inventario:documentos')).status_code,403)
        self.assertEqual(self.client.get(reverse('inventario:compras')).status_code,403)

    def test_superusuario_conserva_acceso(self):
        self.user.is_superuser=True;self.user.is_staff=True;self.user.save()
        for ruta in ['inventario:compras','ventas:lista','control_inventario:stock','admin:index']:
            with self.subTest(ruta=ruta):self.assertEqual(self.client.get(reverse(ruta)).status_code,200)

    def test_admin_solo_auth_y_seguridad_incluso_en_rutas_directas(self):
        self.user.is_superuser=True;self.user.is_staff=True;self.user.save()
        r=self.client.get(reverse('admin:index'))
        self.assertEqual({a['app_label'] for a in r.context['app_list']},{'auth','seguridad'})
        self.assertEqual({m._meta.app_label for m in admin.site._registry},{'auth','seguridad'})
        self.assertEqual(self.client.get('/admin/inventario/producto/').status_code,404)
        self.assertEqual(self.client.get('/admin/ventas/documentoventa/').status_code,404)

    def test_selected_permissions_ampliado_en_usuarios_y_grupos(self):
        self.user.is_superuser=True;self.user.is_staff=True;self.user.save()
        for ruta,pk in [('admin:seguridad_usuario_change',self.user.pk),('admin:auth_group_add',None)]:
            r=self.client.get(reverse(ruta,args=[pk] if pk else None))
            self.assertEqual(r.status_code,200)
            self.assertContains(r,'seguridad/permisos.css?v=1')
            self.assertContains(r,'selectfilter')

    def test_staff_no_se_eleva_privilegios_ni_administra_grupos(self):
        self.user.is_staff=True;self.user.save()
        self.grant('seguridad.view_usuario','seguridad.change_usuario','auth.view_group','auth.change_group','auth.add_group')
        g=Group.objects.create(name='NO MODIFICAR')
        r=self.client.post(reverse('admin:seguridad_usuario_change',args=[self.user.pk]),{'is_superuser':'on'})
        self.assertEqual(r.status_code,403)
        self.user.refresh_from_db();self.assertFalse(self.user.is_superuser)
        self.assertEqual(self.client.post(reverse('admin:auth_group_change',args=[g.pk]),{'name':'ALTERADO'}).status_code,403)
        self.assertEqual(self.client.post(reverse('admin:auth_group_add'),{'name':'NO CREAR'}).status_code,403)
        g.refresh_from_db();self.assertEqual(g.name,'NO MODIFICAR')

    def test_administrador_puede_crear_grupo_con_permiso(self):
        self.user.is_superuser=True;self.user.is_staff=True;self.user.save()
        permiso=Permission.objects.get(content_type__app_label='clientes',codename='view_cliente')
        r=self.client.post(reverse('admin:auth_group_add'),{'name':'LECTORES','permissions':[permiso.pk],'_save':'Save'})
        self.assertEqual(r.status_code,302)
        self.assertTrue(Group.objects.get(name='LECTORES').permissions.filter(pk=permiso.pk).exists())

    def test_superusuario_asigna_permiso_desde_formulario_usuario(self):
        from django.utils import timezone
        self.user.is_superuser=True;self.user.is_staff=True;self.user.save()
        destino=get_user_model().objects.create_user(username='lector',password='prueba')
        fecha=timezone.localtime(destino.date_joined)
        permiso=Permission.objects.get(content_type__app_label='clientes',codename='view_cliente')
        r=self.client.post(reverse('admin:seguridad_usuario_change',args=[destino.pk]),{
            'username':'lector','first_name':'','last_name':'','email':'','telefono':'','is_active':'on',
            'date_joined_0':fecha.strftime('%Y-%m-%d'),'date_joined_1':fecha.strftime('%H:%M:%S'),
            'last_login_0':'','last_login_1':'','user_permissions':[permiso.pk],'_save':'Save'})
        self.assertEqual(r.status_code,302)
        destino.refresh_from_db();self.assertFalse(destino.is_superuser)
        self.client.force_login(destino)
        self.assertEqual(self.client.get(reverse('clientes:lista_clientes')).status_code,200)
        self.assertEqual(self.client.get(reverse('clientes:crear_cliente')).status_code,403)


class PoliticaTests(SimpleTestCase):
    def test_ruta_nueva_protegida_se_deniega(self):
        self.assertEqual(reglas('ventas:exportacion_nueva'),[])
        self.assertIsNone(reglas('iniciar_sesion'))
        self.assertFalse(permitido(AnonymousUser(),'ventas:lista'))

    def test_todas_las_rutas_actuales_tienen_politica(self):
        def visitar(patrones,ns=''):
            for p in patrones:
                if isinstance(p,URLResolver):
                    visitar(p.url_patterns,p.namespace or ns)
                elif isinstance(p,URLPattern) and ns in PROTEGIDOS:
                    datos=dict(p.default_args)
                    if ns=='gastos' and p.name.startswith('catalogo'):datos['catalogo']='proveedores'
                    for metodo in ['GET','POST']:
                        self.assertTrue(reglas(ns+':'+p.name,metodo,datos),ns+':'+str(p.name))
        visitar(get_resolver().url_patterns)

    def test_comprobacion_exige_instalacion_correcta(self):
        with override_settings(MIDDLEWARE=[]):self.assertEqual(comprobar_permisos(None)[0].id,'seguridad.E001')
        with override_settings(MIDDLEWARE=MW):self.assertEqual(comprobar_permisos(None),[])

    def test_instalador_es_idempotente_y_preserva_configuracion(self):
        from instalar_seguridad_modulos import instalar
        with TemporaryDirectory() as d:
            p=Path(d)/'config';p.mkdir()
            original="SECRET_KEY = 'solo-prueba'\nMIDDLEWARE = ['django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware']\n"
            archivo=p/'settings.py';archivo.write_text(original)
            self.assertTrue(instalar(d));primero=archivo.read_text()
            self.assertFalse(instalar(d));self.assertEqual(archivo.read_text(),primero)
            self.assertEqual(primero.count('seguridad.middleware.PermisosModulosMiddleware'),1)
            self.assertIn("SECRET_KEY = 'solo-prueba'",primero)
            respaldo=list(Path(d).glob('respaldo_seguridad_*/settings.py'))
            self.assertEqual(len(respaldo),1);self.assertEqual(respaldo[0].read_text(),original)
