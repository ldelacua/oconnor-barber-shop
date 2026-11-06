from django.urls import path
from . import views, vistas_regalo
from .reportes import reporte_servicios
from .consulta_pagos import consulta_pagos
from .tasa_bcv import registrar_tasa_bcv

app_name = "ventas"
urlpatterns = [
    path("venta-tarjetas/", vistas_regalo.vender, name="venta_tarjetas"),
    path("regalos/", vistas_regalo.tarjetas, name="tarjetas_regalo"),
    path("regalos/pdf/<uuid:lote>/", vistas_regalo.imprimir, name="regalo_pdf"),
    path("regalos/consultar/", vistas_regalo.consultar, name="regalo_consultar"),
    path("", views.lista_documentos, name="lista"),
    path("ofertas/<int:pk>/", views.consultar_ofertas, name="consultar_ofertas"),
    path("tarjeta/<int:pk>/", views.tarjeta_cliente, name="tarjeta_cliente"),
    path("nueva/", views.nueva_venta, name="crear"),
    path("cotizacion/", views.cotizacion, name="cotizacion"),
    path("reporte-servicios/", reporte_servicios, name="reporte_servicios"),
    path("pagos/", consulta_pagos, name="consulta_pagos"),
    path("<int:pk>/", views.ver_documento, name="ver"),
    path("<int:pk>/reversar/", views.reversar_documento, name="reversar"),
    path("tasa-bcv/", registrar_tasa_bcv, name="registrar_tasa_bcv"),
]
