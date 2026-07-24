from django.urls import path

from . import views

app_name = "barberos"

urlpatterns = [
    path("", views.lista_barberos, name="lista_barberos"),
    path("nuevo/", views.crear_barbero, name="crear_barbero"),
    path("<int:pk>/", views.detalle_barbero, name="detalle_barbero"),
    path("<int:pk>/editar/", views.editar_barbero, name="editar_barbero"),
]