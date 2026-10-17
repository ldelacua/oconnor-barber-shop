from django.contrib import admin
from .models import Liquidacion,DetalleLiquidacion,PagoLiquidacion

class DetalleInline(admin.TabularInline):
    model=DetalleLiquidacion
    fk_name="liquidacion"
    extra=0
    can_delete=False
    readonly_fields=[f.name for f in DetalleLiquidacion._meta.fields]
    def has_add_permission(self,request,obj=None):return False
    def has_change_permission(self,request,obj=None):return False

class PagoInline(admin.TabularInline):
    model=PagoLiquidacion
    extra=0
    can_delete=False
    readonly_fields=[f.name for f in PagoLiquidacion._meta.fields]
    def has_add_permission(self,request,obj=None):return False
    def has_change_permission(self,request,obj=None):return False

@admin.register(Liquidacion)
class LiquidacionAdmin(admin.ModelAdmin):
    list_display=("id_cancelacion","fecha_cancelacion","nombre_prestador","total_comision_usd","total_bs")
    readonly_fields=[f.name for f in Liquidacion._meta.fields]
    inlines=[DetalleInline,PagoInline]
    actions=None
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False
