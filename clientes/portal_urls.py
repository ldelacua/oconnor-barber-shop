from django.urls import path
from . import portal

urlpatterns = [
    path("", portal.acceso, name="portal_acceso"),
    path("registro/", portal.acceso, {"registro": True}, name="portal_registro"),
    path("confirmar/<str:token>/", portal.confirmar, name="portal_confirmar"),
    path("citas/", portal.citas, name="portal_citas"),
]
