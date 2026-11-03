from django.urls import path
from . import views

app_name="ventas_productos"
urlpatterns=[
    path("precio/",views.precio,name="precio"),
    path("porcentajes/",views.configuracion,{"tipo":"porcentajes"},name="porcentajes"),
    path("porcentajes/nuevo/",views.configurar,{"tipo":"porcentajes"},name="nuevo_porcentaje"),
    path("porcentajes/<int:pk>/",views.configurar,{"tipo":"porcentajes"},name="editar_porcentaje"),
    path("descuentos/",views.configuracion,{"tipo":"descuentos"},name="descuentos"),
    path("descuentos/nuevo/",views.configurar,{"tipo":"descuentos"},name="nuevo_descuento"),
    path("descuentos/<int:pk>/",views.configurar,{"tipo":"descuentos"},name="editar_descuento"),
    path("comisiones/", views.escalas_comision, name="escalas_comision"),
    path("comisiones/nueva/", views.editar_escala_comision, name="nueva_escala_comision"),
    path("comisiones/<int:pk>/", views.editar_escala_comision, name="editar_escala_comision"),
    path("reporte-prestador/", views.reporte_prestador, name="reporte_prestador"),
    path("",views.lista,name="lista"),
    path("nueva/",views.nueva,name="nueva"),
    path("condiciones/",views.condiciones,name="condiciones"),
    path("<int:pk>/",views.ver,name="ver"),
    path("<int:pk>/reversar/",views.reversar,name="reversar"),
]
