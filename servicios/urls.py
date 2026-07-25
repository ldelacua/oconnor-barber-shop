from django.urls import path

from . import views

app_name = "servicios"

urlpatterns = [
    path("", views.lista_servicios, name="lista"),
    path("nuevo/", views.crear_servicio, name="crear"),
    path("editar/<int:pk>/", views.editar_servicio, name="editar"),
    path("eliminar/<int:pk>/", views.eliminar_servicio, name="eliminar"),
]