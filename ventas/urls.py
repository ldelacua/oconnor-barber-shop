from django.urls import path
from . import views
from .reportes import reporte_servicios
from .consulta_pagos import consulta_pagos
from .tasa_bcv import registrar_tasa_bcv

app_name = "ventas"
urlpatterns = [
    path("", views.lista_documentos, name="lista"),
    path("nueva/", views.nueva_venta, name="crear"),
    path("cotizacion/", views.cotizacion, name="cotizacion"),
    path("reporte-servicios/", reporte_servicios, name="reporte_servicios"),
    path("pagos/", consulta_pagos, name="consulta_pagos"),
    path("<int:pk>/", views.ver_documento, name="ver"),
    path("<int:pk>/reversar/", views.reversar_documento, name="reversar"),
    path("tasa-bcv/", registrar_tasa_bcv, name="registrar_tasa_bcv"),
]
