from django.urls import path
from . import views
from .historico import historico
from .consulta_precios import consulta_precios
from .historico_comisiones import historico_comisiones

app_name="ventas_productos"
urlpatterns=[
    path("precios/consulta/pdf/", consulta_precios, {"descargar_pdf": True}, name="consulta_precios_pdf"),
    path("precios/consulta/", consulta_precios, name="consulta_precios"),
    path("precios/", views.precios, name="precios"),
    path("precio/",views.precio,name="precio"),
    path("porcentajes/",views.configuracion,{"tipo":"porcentajes"},name="porcentajes"),
    path("porcentajes/nuevo/",views.configurar,{"tipo":"porcentajes"},name="nuevo_porcentaje"),
    path("porcentajes/<int:pk>/",views.configurar,{"tipo":"porcentajes"},name="editar_porcentaje"),
    path("descuentos/",views.configuracion,{"tipo":"descuentos"},name="descuentos"),
    path("descuentos/nuevo/",views.configurar,{"tipo":"descuentos"},name="nuevo_descuento"),
    path("descuentos/<int:pk>/",views.configurar,{"tipo":"descuentos"},name="editar_descuento"),
    path("comisiones/", views.escalas_comision, name="escalas_comision"),
    path("comisiones/historico/por-producto/", historico_comisiones, {"por_producto": True}, name="historico_comisiones_por_producto"),
    path("comisiones/historico/", historico_comisiones, name="historico_comisiones"),
    path("comisiones/nueva/", views.editar_escala_comision, name="nueva_escala_comision"),
    path("comisiones/<int:pk>/", views.editar_escala_comision, name="editar_escala_comision"),
    path("reporte-prestador/", views.reporte_prestador, name="reporte_prestador"),
    path("historico-prestadores/", historico, {"por_prestador": True}, name="historico_prestadores"),
    path("historico-prestadores/<int:vendedor_id>/", historico, {"por_prestador": True}, name="historico_prestador_detalle"),
    path("historico/", historico, name="historico"),
    path("historico/<int:producto_id>/", historico, name="historico_detalle"),
    path("",views.lista,name="lista"),
    path("nueva/",views.nueva,name="nueva"),
    path("condiciones/",views.condiciones,name="condiciones"),
    path("<int:pk>/",views.ver,name="ver"),
    path("<int:pk>/reversar/",views.reversar,name="reversar"),
]
