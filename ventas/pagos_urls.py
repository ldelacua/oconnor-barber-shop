from django.urls import path
from .pagos_general import consulta_general
from inventario.views_pagos import pagar_proveedor, proveedores, tasa_proveedor, reverso_proveedor, corregir_proveedor
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def inicio(request):
    return render(request, "ventas/pagos_inicio.html")
app_name = 'pagos'
urlpatterns = [path('', inicio, name='lista'),
               path('editar-pago-proveedor/<int:pago_id>/', corregir_proveedor, name='editar_pago_proveedor'),
               path('eliminar-pago-proveedor/<int:pago_id>/', corregir_proveedor, {'eliminar': True}, name='eliminar_pago_proveedor'),
               path('reverso-proveedor/<int:pago_id>/', reverso_proveedor, name='reverso_proveedor'),
               path('cobros-clientes/', consulta_general, {'cobros_clientes': True}, name='cobros_clientes'),
               path('consulta/', consulta_general, name='consulta'),
               path('proveedores/', proveedores, name='proveedores'),
               path('tasa/', tasa_proveedor, name='tasa_proveedor'),
               path('proveedor/<int:compra_id>/', pagar_proveedor, name='proveedor')]
