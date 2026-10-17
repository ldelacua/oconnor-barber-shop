from django.urls import path
from . import views

app_name = "tasas_bcv"

urlpatterns = [
    path("", views.lista_tasas, name="lista"),
    path("nueva/", views.crear_tasa, name="crear"),
    path("<int:pk>/editar/", views.editar_tasa, name="editar"),
]
