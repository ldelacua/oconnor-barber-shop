from django.contrib import admin

from .models import Barbero


#@admin.register(Barbero)
class BarberoAdmin(admin.ModelAdmin):
    from .forms import BarberoForm
    form = BarberoForm
    list_display = (
        "codigo",
        "nombre",
        "apellido",
        "telefono",
        "fecha_ingreso",
        "porcentaje",
        "silla",
        "activo",
    )

    search_fields = (
        "codigo",
        "nombre",
        "apellido",
        "telefono",
        "correo",
        "silla__nombre",
    )

    list_filter = (
        "activo",
        "fecha_ingreso",
    )
