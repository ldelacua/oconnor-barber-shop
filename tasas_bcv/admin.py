from django.contrib import admin
from .models import TasaBCV


@admin.register(TasaBCV)
class TasaBCVAdmin(admin.ModelAdmin):
    list_display = ("fecha", "tasa_bcv")
    ordering = ("-fecha",)
    date_hierarchy = "fecha"
