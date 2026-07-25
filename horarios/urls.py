from django.urls import path

from . import views

app_name = "horarios"

urlpatterns = [
    # ===========================
    # SILLAS
    # ===========================
    path(
        "sillas/",
        views.listar_sillas,
        name="listar_sillas",
    ),
    path(
        "sillas/nueva/",
        views.crear_silla,
        name="crear_silla",
    ),
    path(
        "sillas/<int:silla_id>/editar/",
        views.editar_silla,
        name="editar_silla",
    ),
    path(
        "sillas/<int:silla_id>/eliminar/",
        views.eliminar_silla,
        name="eliminar_silla",
    ),
    path(
        "sillas/<int:silla_id>/estado/",
        views.cambiar_estado_silla,
        name="cambiar_estado_silla",
    ),

    # ===========================
    # HORARIOS
    # ===========================
    path(
        "",
        views.listar_horarios,
        name="listar_horarios",
    ),
    path(
        "nuevo/",
        views.crear_horario,
        name="crear_horario",
    ),
    path(
        "<int:horario_id>/editar/",
        views.editar_horario,
        name="editar_horario",
    ),
    path(
        "<int:horario_id>/eliminar/",
        views.eliminar_horario,
        name="eliminar_horario",
    ),
    path(
        "<int:horario_id>/estado/",
        views.cambiar_estado_horario,
        name="cambiar_estado_horario",
    ),
]
