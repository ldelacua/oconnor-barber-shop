from django.contrib import admin

from .models import Cita


@admin.register(Cita)
class CitaAdmin(admin.ModelAdmin):
    list_display = (
        "cliente",
        "barbero",
        "servicio",
        "fecha",
        "hora",
        "estado",
    )

    list_filter = (
        "estado",
        "fecha",
        "barbero",
    )

    search_fields = (
        "cliente__nombre",
        "cliente__apellido",
        "barbero__nombre",
    )

    ordering = (
        "fecha",
        "hora",
    )