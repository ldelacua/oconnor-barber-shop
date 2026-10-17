from django.contrib import admin
from .models import DocumentoVenta, DetalleVenta, PagoVenta


class DetalleInline(admin.TabularInline):
    model = DetalleVenta
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in DetalleVenta._meta.fields]
    def has_add_permission(self, request, obj=None):
        return False
    def has_change_permission(self, request, obj=None):
        return False


class PagoInline(admin.TabularInline):
    model = PagoVenta
    fk_name = "documento"
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in PagoVenta._meta.fields]
    def has_add_permission(self, request, obj=None):
        return False
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DocumentoVenta)
class DocumentoVentaAdmin(admin.ModelAdmin):
    list_display = ("id_documento", "tipo_documento", "fecha", "cliente", "total_bs")
    list_filter = ("tipo_documento", "fecha")
    readonly_fields = [f.name for f in DocumentoVenta._meta.fields]
    inlines = [DetalleInline, PagoInline]
    actions = None
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
