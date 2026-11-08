from django import forms
from django.contrib import admin
from datetime import time
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


from .models import TarjetaFidelidad

@admin.register(TarjetaFidelidad)
class TarjetaFidelidadAdmin(admin.ModelAdmin):
    list_display = ("servicio", "cortes", "porcentaje", "desde", "activa")


from .models import EntidadConvenio, PromocionServicio


class NombreMayusculas(forms.CharField):
    def to_python(self, value):
        return super().to_python(value).upper()


def campo_nombre():
    return NombreMayusculas(label="Nombre", max_length=120,
        widget=forms.TextInput(attrs={"style": "text-transform: uppercase"}))


class EntidadConvenioForm(forms.ModelForm):
    nombre = campo_nombre()

    class Meta:
        model = EntidadConvenio
        fields = ("nombre", "activa")


@admin.register(EntidadConvenio)
class EntidadConvenioAdmin(admin.ModelAdmin):
    form = EntidadConvenioForm
    list_display = ("nombre", "activa")
    fields = ("nombre", "activa")
    search_fields = ("nombre",)


class FechaConCalendario(forms.DateInput):
    template_name = "ventas/widgets/fecha.html"


def campo_fecha(etiqueta):
    return forms.DateField(label=etiqueta, input_formats=["%d/%m/%Y", "%Y-%m-%d"],
        widget=FechaConCalendario(format="%d/%m/%Y", attrs={
            "placeholder": "DD/MM/AAAA", "size": "12", "style": "width: 9rem; max-width: 100%",
        }))


class PromocionServicioForm(forms.ModelForm):
    nombre = campo_nombre()
    desde = campo_fecha("Desde")
    hasta = campo_fecha("Hasta")
    dias = forms.TypedMultipleChoiceField(
        choices=PromocionServicio._meta.get_field("dia").choices, coerce=int,
        required=False, widget=forms.CheckboxSelectMultiple, label="Días de la semana",
    )

    class Meta:
        model = PromocionServicio
        fields = ("nombre", "servicio", "desde", "hasta", "porcentaje", "activa",
                  "entidad", "dias", "hora_desde", "hora_hasta")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["dias"] = self.instance.dias or ([self.instance.dia] if self.instance.dia else [])
        for nombre in ("hora_desde", "hora_hasta"):
            opciones = [(f"{h:02d}:00", str(h)) for h in range(8, 24)]
            anterior = getattr(self.instance, nombre)
            if anterior and anterior.strftime("%H:%M") not in dict(opciones):
                opciones.append((anterior.isoformat(), f"{anterior.isoformat()} (hora guardada)"))
            elif anterior and anterior.second:
                opciones.append((anterior.isoformat(), f"{anterior.isoformat()} (hora guardada)"))
            campo = forms.TypedChoiceField(label=self.fields[nombre].label, required=False,
                choices=[("", "—")] + opciones, coerce=time.fromisoformat, empty_value=None,
                widget=forms.Select(attrs={"style": "width: auto; min-width: 5rem"}))
            self.fields[nombre] = campo
            if anterior:
                valor = anterior.isoformat()
                self.initial[nombre] = valor if valor in dict(opciones) else anterior.strftime("%H:%M")

    def clean(self):
        datos = super().clean()
        dias = datos.get("dias") or []
        inicio, fin = datos.get("hora_desde"), datos.get("hora_hasta")
        self.instance.dia = dias[0] if dias else None
        if (dias or inicio or fin) and (not dias or inicio is None or fin is None or inicio >= fin):
            raise forms.ValidationError("Marca al menos un día y elige una hora final posterior a la inicial.")
        return datos


@admin.register(PromocionServicio)
class PromocionServicioAdmin(admin.ModelAdmin):
    form = PromocionServicioForm
    fields = ("nombre", "servicio", ("desde", "hasta"), "porcentaje", "activa",
              "entidad", "dias", ("hora_desde", "hora_hasta"))
    list_display = ("nombre", "servicio", "porcentaje", "entidad", "desde_visible", "hasta_visible", "dias_visibles", "activa")
    list_filter = ("activa", "entidad")

    @admin.display(description="Desde", ordering="desde")
    def desde_visible(self, obj):
        return obj.desde.strftime("%d/%m/%Y")

    @admin.display(description="Hasta", ordering="hasta")
    def hasta_visible(self, obj):
        return obj.hasta.strftime("%d/%m/%Y")

    @admin.display(description="Días")
    def dias_visibles(self, obj):
        nombres = dict(PromocionServicio._meta.get_field("dia").choices)
        return ", ".join(nombres[d] for d in (obj.dias or ([obj.dia] if obj.dia else []))) or "—"


from .models import TarjetaRegalo


@admin.register(TarjetaRegalo)
class TarjetaRegaloAdmin(admin.ModelAdmin):
    def changelist_view(self, request, extra_context=None):
        from .vistas_regalo import tarjetas
        return tarjetas(request, ambiente_admin=True)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return obj is None and request.user.has_perm("ventas.view_tarjetaregalo")
