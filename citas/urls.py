from django.urls import path

from . import views


app_name = "citas"

urlpatterns = [
    path(
        "",
        views.listar_citas,
        name="listar_citas",
    ),
    path(
        "nueva/",
        views.crear_cita,
        name="crear_cita",
    ),
    path(
        "disponibilidad/",
        views.consultar_disponibilidad,
        name="consultar_disponibilidad",
    ),
    path(
        "<int:cita_id>/editar/",
        views.editar_cita,
        name="editar_cita",
    ),
    path(
        "<int:cita_id>/eliminar/",
        views.eliminar_cita,
        name="eliminar_cita",
    ),
    path(
        "<int:cita_id>/estado/",
        views.cambiar_estado_cita,
        name="cambiar_estado_cita",
    ),
]