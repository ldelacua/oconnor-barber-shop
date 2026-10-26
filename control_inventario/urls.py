from django.urls import path
from . import views
app_name="control_inventario"
urlpatterns=[
    path("",views.stock,name="stock"),
    path("documentos/",views.documentos,name="documentos"),
    path("documentos/nuevo/",views.nuevo,name="nuevo"),
    path("documentos/<int:pk>/",views.ver,name="ver"),
    path("productos/buscar/",views.buscar,name="buscar"),
    path("costo/",views.costo,name="costo"),
    path("cierres/",views.cierres,name="cierres"),
    path("cierres/<int:pk>/",views.conteo,name="conteo"),
    path("cierres/<int:pk>/confirmar/",views.cerrar,name="cerrar"),
    path("cierres/<int:pk>/cancelar/",views.cancelar,name="cancelar"),
]
