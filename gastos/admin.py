from django.contrib import admin
from .models import GrupoGasto,TipoGasto,Proveedor,RegistroGasto
from .forms import GrupoForm,TipoForm,ProveedorForm

@admin.register(GrupoGasto)
class GrupoAdmin(admin.ModelAdmin):
    form=GrupoForm
    list_display=("id_grupo_gasto","descripcion","activo")
    list_filter=("activo",)
    search_fields=("descripcion",)

@admin.register(TipoGasto)
class TipoAdmin(admin.ModelAdmin):
    form=TipoForm
    list_display=("id_gasto","descripcion","grupo","activo")
    list_filter=("activo","grupo")
    search_fields=("descripcion",)

@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    form=ProveedorForm
    list_display=("id_proveedor","rif","descripcion","activo")
    list_filter=("activo",)
    search_fields=("rif","descripcion")

@admin.register(RegistroGasto)
class RegistroAdmin(admin.ModelAdmin):
    list_display=("id_registro_gasto","fecha_gasto","proveedor","numero_factura","moneda","monto_gasto","monto_impuesto")
    list_filter=("moneda","fecha_gasto")
    search_fields=("numero_factura","proveedor__descripcion")
    def get_form(self,request,obj=None,**kwargs):
        from .forms import RegistroForm
        kwargs["form"]=RegistroForm
        return super().get_form(request,obj,**kwargs)
