from django.contrib import admin

from .models import Barbero


#@admin.register(Barbero)
class BarberoAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nombre",
        "apellido",
        "telefono",
        "fecha_ingreso",
        "porcentaje",
        "codigo_silla",
        "activo",
    )

    search_fields = (
        "codigo",
        "nombre",
        "apellido",
        "telefono",
        "correo",
        "codigo_silla",
    )

    list_filter = (
        "activo",
        "fecha_ingreso",
    )
