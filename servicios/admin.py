from django.contrib import admin
from .models import Servicio
from .forms import ServicioForm


@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    form = ServicioForm
    list_display = (
        "codigo",
        "nombre",
        "modo_precio",
        "precio",
        "duracion",
        "retencion_impuesto",
        "activo",
    )

    search_fields = (
        "codigo",
        "nombre",
    )

    list_filter = (
        "modo_precio",
        "retencion_impuesto",
        "activo",
    )