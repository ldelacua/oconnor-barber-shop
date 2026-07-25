from django.contrib import admin
from .models import Cliente


#@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "nombre",
        "apellido",
        "telefono",
        "email",
        "activo",
    )

    search_fields = (
        "nombre",
        "apellido",
        "telefono",
        "email",
    )

    list_filter = (
        "activo",
    )

    readonly_fields = (
        "fecha_registro",
    )