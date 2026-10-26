"""Política central: rutas conocidas, permisos explícitos y denegación por defecto."""
from django.urls import resolve, Resolver404

PROTEGIDOS = {'clientes','barberos','servicios','horarios','citas','tasas_bcv','ventas','liquidaciones','gastos','inventario','ventas_productos','control_inventario'}


def permisos(modelo, accion='view'):
    app, nombre = modelo.split('.')
    return (f'{app}.view_{nombre}',) if accion=='view' else (f'{app}.view_{nombre}', f'{app}.{accion}_{nombre}')


def reglas(nombre, metodo='GET', datos=None):
    """Lista OR de tuplas AND. None: ruta ajena; []: ruta protegida desconocida."""
    datos=datos or {}
    ns, _, ruta=nombre.partition(':')
    if ns not in PROTEGIDOS:
        return None
    escribir=metodo not in {'GET','HEAD','OPTIONS'}
    def p(modelo,accion='view'):return [permisos(modelo,accion)]
    simples={
      'clientes':('clientes.cliente',{'lista_clientes':'view','detalle_cliente':'view','crear_cliente':'add','editar_cliente':'change'}),
      'barberos':('barberos.barbero',{'lista_barberos':'view','detalle_barbero':'view','crear_barbero':'add','editar_barbero':'change'}),
      'servicios':('servicios.servicio',{'lista':'view','crear':'add','editar':'change','eliminar':'delete'}),
      'tasas_bcv':('tasas_bcv.tasabcv',{'lista':'view','crear':'add','editar':'change'}),
      'liquidaciones':('liquidaciones.liquidacion',{'lista':'view','ver':'view','crear':'add'}),
    }
    if ns in simples:
        modelo,acciones=simples[ns]
        return p(modelo,acciones[ruta]) if ruta in acciones else []
    if ns=='horarios':
        if 'silla' in ruta:
            acciones={'listar_sillas':'view','crear_silla':'add','editar_silla':'change','eliminar_silla':'delete','cambiar_estado_silla':'change'}
            return p('horarios.silla',acciones[ruta]) if ruta in acciones else []
        if ruta in {'listar_horarios','crear_horario'} and escribir:
            return [('horarios.view_horario','horarios.add_horario','horarios.change_horario')]
        acciones={'listar_horarios':'view','crear_horario':'add','editar_horario':'change','eliminar_horario':'delete','cambiar_estado_horario':'change'}
        return p('horarios.horario',acciones[ruta]) if ruta in acciones else []
    if ns=='citas':
        if ruta=='buscar_clientes':
            return [permisos(m,a) for m,a in [('citas.cita','add'),('citas.cita','change'),('clientes.cliente','view'),('ventas.documentoventa','add'),('ventas_productos.documentoproducto','add')]]
        acciones={'listar_citas':'view','agenda_citas':'view','crear_cita':'add','editar_cita':'change','eliminar_cita':'delete','cambiar_estado_cita':'change','consultar_disponibilidad':'view'}
        return p('citas.cita',acciones[ruta]) if ruta in acciones else []
    if ns=='ventas':
        if ruta=='registrar_tasa_bcv':return p('tasas_bcv.tasabcv','add')
        if ruta=='consulta_pagos':return p('ventas.pagoventa')
        acciones={'lista':'view','ver':'view','crear':'add','cotizacion':'view','reporte_servicios':'view','reversar':'delete'}
        return p('ventas.documentoventa',acciones[ruta]) if ruta in acciones else []
    if ns=='gastos':
        if ruta.startswith('catalogo'):
            modelos={'grupos':'grupogasto','tipos':'tipogasto','productos':'producto','proveedores':'proveedor'}
            modelo=modelos.get(datos.get('catalogo'))
            acciones={'catalogo':'view','catalogo_crear':'add','catalogo_editar':'change','catalogo_estado':'change','catalogo_eliminar':'delete'}
            return p('gastos.'+modelo,acciones[ruta]) if modelo and ruta in acciones else []
        acciones={'inicio':'view','ver':'view','crear':'add','editar':'change','eliminar':'delete'}
        return p('gastos.registrogasto',acciones[ruta]) if ruta in acciones else []
    if ns=='inventario':
        if ruta=='buscar_productos':
            return [permisos(m,a) for m,a in [('inventario.producto','view'),('inventario.compra','add'),('inventario.compra','change'),('ventas_productos.documentoproducto','add'),('control_inventario.documentoajuste','add')]]
        maestros={'productos':('producto','view'),'nuevo_producto':('producto','add'),'editar_producto':('producto','change'),
                  'proveedores':('proveedor','view'),'nuevo_proveedor':('proveedor','add'),'editar_proveedor':('proveedor','change'),
                  'unidades':('unidadmedida','view'),'nueva_unidad':('unidadmedida','add'),'editar_unidad':('unidadmedida','change')}
        if ruta in maestros:
            modelo,accion=maestros[ruta];return p('inventario.'+modelo,accion)
        acciones={'compras':'view','detalle':'view','nueva_compra':'add','editar_compra':'change','actualizar':'change','eliminar':'delete','condiciones':'view'}
        return p('inventario.compra',acciones[ruta]) if ruta in acciones else []
    if ns=='ventas_productos':
        configuracion={'porcentajes':('porcentajeproducto','view'),'nuevo_porcentaje':('porcentajeproducto','add'),'editar_porcentaje':('porcentajeproducto','change'),
                       'descuentos':('escaladescuento','view'),'nuevo_descuento':('escaladescuento','add'),'editar_descuento':('escaladescuento','change')}
        if ruta in configuracion:
            modelo,accion=configuracion[ruta];return p('ventas_productos.'+modelo,accion)
        acciones={'lista':'view','ver':'view','nueva':'add','condiciones':'view','precio':'add','reversar':'delete'}
        return p('ventas_productos.documentoproducto',acciones[ruta]) if ruta in acciones else []
    if ns=='control_inventario':
        if ruta=='stock':return p('control_inventario.movimientostock')
        if ruta in {'documentos','ver'}:return p('control_inventario.documentoajuste')
        if ruta in {'nuevo','buscar','costo'}:return p('control_inventario.documentoajuste','add')
        if ruta=='cierres':return p('control_inventario.cierremensual','add' if escribir else 'view')
        if ruta=='conteo':return p('control_inventario.cierremensual','change' if escribir else 'view')
        if ruta=='cerrar':return p('control_inventario.cierremensual','change')
        if ruta=='cancelar':return p('control_inventario.cierremensual','delete')
    return []


def permitido(usuario, nombre, metodo='GET', datos=None):
    if not usuario.is_authenticated or not usuario.is_active:return False
    if usuario.is_superuser:return True
    opciones=reglas(nombre,metodo,datos)
    return opciones is not None and any(usuario.has_perms(opcion) for opcion in opciones)


def enlace_permitido(usuario,url):
    try:
        match=resolve(url.split('?',1)[0])
    except (Resolver404,ValueError):return False
    if match.namespace=='admin':return usuario.is_authenticated and usuario.is_active and usuario.is_staff
    if match.url_name=='dashboard':return usuario.is_authenticated and usuario.is_active
    return permitido(usuario,match.view_name,datos=match.kwargs)


def entrada_modulo(usuario,modulo):
    """Entra por la primera consulta autorizada, sin conceder la consulta general."""
    from django.urls import reverse
    entradas={
      'inventario':[('inventario:compras',{}),('inventario:productos',{}),('inventario:proveedores',{}),('inventario:unidades',{})],
      'control_inventario':[('control_inventario:stock',{}),('control_inventario:documentos',{}),('control_inventario:cierres',{})],
      'ventas':[('ventas:lista',{}),('ventas:consulta_pagos',{})],
      'ventas_productos':[('ventas_productos:lista',{}),('ventas_productos:porcentajes',{}),('ventas_productos:descuentos',{})],
      'barberos':[('barberos:lista_barberos',{}),('horarios:listar_sillas',{})],
      'gastos':[('gastos:inicio',{})]+[('gastos:catalogo',{'catalogo':c}) for c in ['grupos','tipos','proveedores','productos']],
    }
    for nombre,kwargs in entradas.get(modulo,[]):
        url=reverse(nombre,kwargs=kwargs)
        if enlace_permitido(usuario,url):return url
    return ''
