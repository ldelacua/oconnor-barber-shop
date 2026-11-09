from decimal import Decimal

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import render

from .models import PagoVenta
from .pagos_calculos import leer_tipos_pago


class FiltrosPagosForm(forms.Form):
    desde = forms.DateField(required=False, label="Pago desde", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    hasta = forms.DateField(required=False, label="Pago hasta", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    numero = forms.IntegerField(required=False, min_value=1, label="N.º documento")
    tipo = forms.ChoiceField(required=False, label="Tipo de documento", choices=[("", "FA y RE"), ("FA", "FA"), ("RE", "RE")])
    cliente = forms.CharField(required=False, max_length=100, label="Cliente")
    forma_pago = forms.ChoiceField(required=False, label="Forma de pago")
    moneda = forms.ChoiceField(required=False, choices=[("", "Todas"), ("USD", "USD"), ("BS", "Bs.")])
    referencia = forms.CharField(required=False, max_length=100, label="Referencia")

    def __init__(self, *args, opciones_pago=(), ver_bancos=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["forma_pago"].choices = [("", "Todas")] + list(opciones_pago)
        if ver_bancos:
            from bancos.models import Banco
            self.fields["banco"] = forms.ModelChoiceField(queryset=Banco.objects.all(), required=False, empty_label="Todos")
        for campo in self.fields.values():
            campo.widget.attrs["class"] = "form-select" if isinstance(campo.widget, forms.Select) else "form-control"

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


def _agrupar_pagos(usuario, pagina, nombres, por_forma):
    from bancos.templatetags.bancos_pagos import filas_con_cuenta

    grupos = {}
    ver_bancos = usuario.has_perm("bancos.view_cuentabancaria")
    for pago, cuenta in filas_con_cuenta(usuario, pagina, "SERVICIOS"):
        banco = (cuenta.banco_id, cuenta.banco.nombre) if cuenta else (
            0, "Sin banco" if ver_bancos else "Banco no disponible",
        )
        forma = (pago.tipo_pago, nombres.get(pago.tipo_pago, pago.nombre_tipo_pago))
        (padre_id, padre_nombre), (hijo_id, hijo_nombre) = (forma, banco) if por_forma else (banco, forma)
        padre = grupos.setdefault(padre_id, {
            "id": padre_id, "nombre": padre_nombre, "hijos": {}, "cantidad": 0,
        })
        hijo = padre["hijos"].setdefault(hijo_id, {
            "id": hijo_id, "nombre": hijo_nombre, "origenes": {}, "cantidad": 0,
        })
        tipo = pago.documento.tipo_documento
        origen = hijo["origenes"].setdefault(tipo, {
            "id": tipo, "nombre": "Factura (FA)" if tipo == "FA" else "Reverso (RE)", "filas": [],
        })
        padre["cantidad"] += 1
        hijo["cantidad"] += 1
        origen["filas"].append((pago, cuenta))
    orden = lambda grupo: (not grupo["id"], grupo["nombre"].casefold(), grupo["id"])
    for padre in grupos.values():
        padre["hijos"] = sorted(padre["hijos"].values(), key=orden)
    return sorted(grupos.values(), key=orden)


@login_required
def consulta_pagos(request, historico=False, por_forma=False):
    # Se incluyen los tipos históricos aunque ya no estuvieran en el JSON.
    nombres = {}
    for codigo, nombre in PagoVenta.objects.filter(documento__sellado=True).order_by("tipo_pago", "nombre_tipo_pago").values_list("tipo_pago", "nombre_tipo_pago").distinct():
        nombres[codigo] = nombre
    try:
        nombres.update({codigo: tipo["nombre"] for codigo, tipo in leer_tipos_pago().items()})
    except (OSError, ValueError, KeyError, TypeError):
        pass
    opciones = [(str(codigo), nombre) for codigo, nombre in sorted(nombres.items())]
    filtros = FiltrosPagosForm(request.GET, opciones_pago=opciones, ver_bancos=request.user.has_perm("bancos.view_cuentabancaria"))
    pagos = PagoVenta.objects.filter(documento__sellado=True).select_related("documento").order_by("-fecha", "-documento_id", "-pk")
    if filtros.is_valid():
        datos = filtros.cleaned_data
        if datos.get("banco"):
            from bancos.models import MovimientoInterno
            directos = MovimientoInterno.objects.filter(origen="SERVICIOS")
            ids = directos.filter(cuenta__banco=datos["banco"]).values("pago_id")
            pagos = pagos.filter(Q(pk__in=ids) | (
                Q(documento__cobro_compartido__cuenta__banco=datos["banco"])
                & ~Q(pk__in=directos.values("pago_id"))
            ))
        if datos.get("desde"):
            pagos = pagos.filter(fecha__gte=datos["desde"])
        if datos.get("hasta"):
            pagos = pagos.filter(fecha__lte=datos["hasta"])
        if datos.get("numero"):
            pagos = pagos.filter(documento_id=datos["numero"])
        if datos.get("tipo"):
            pagos = pagos.filter(documento__tipo_documento=datos["tipo"])
        if datos.get("forma_pago"):
            pagos = pagos.filter(tipo_pago=int(datos["forma_pago"]))
        if datos.get("moneda"):
            pagos = pagos.filter(moneda=datos["moneda"])
        if datos.get("referencia"):
            pagos = pagos.filter(referencia__icontains=datos["referencia"])
        for palabra in datos.get("cliente", "").split():
            pagos = pagos.filter(Q(documento__cliente__nombre__icontains=palabra) | Q(documento__cliente__apellido__icontains=palabra))
    else:
        pagos = pagos.none()
    # Agregar ANTES de paginar: totales de todos los resultados de la consulta.
    totales = pagos.aggregate(
        cantidad=Count("pk"),
        usd=Sum("monto", filter=Q(moneda="USD")),
        bs=Sum("monto", filter=Q(moneda="BS")),
    )
    cantidad_total = totales.pop("cantidad")
    totales = {moneda: valor if valor is not None else Decimal("0.00") for moneda, valor in totales.items()}
    grupos = {}
    if historico:
        resumen = pagos.values("tipo_pago").annotate(
            cantidad=Count("pk"),
            usd=Sum("monto", filter=Q(moneda="USD"), default=0),
            bs=Sum("monto", filter=Q(moneda="BS"), default=0),
        ).order_by("tipo_pago")
        pagina = Paginator(resumen, 15).get_page(request.GET.get("page"))
        grupos = {fila["tipo_pago"]: fila for fila in pagina}
        for codigo, fila in grupos.items():
            fila["nombre"] = nombres.get(codigo, str(codigo))
            fila["pagos"] = []
        for pago in pagos.filter(tipo_pago__in=grupos).iterator():
            grupos[pago.tipo_pago]["pagos"].append(pago)
    else:
        pagina = Paginator(pagos, 15).get_page(request.GET.get("page"))
    grupos_pagina = [] if historico else _agrupar_pagos(request.user, pagina, nombres, por_forma)
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "ventas/consulta_pagos.html", {
        "seccion_pagos": True, "filtros": filtros, "pagina": pagina, "grupos_pagina": grupos_pagina, "por_forma": por_forma, "totales": totales, "cantidad_total": cantidad_total, "historico": historico,
        "paginas": pagina.paginator.get_elided_page_range(pagina.number),
        "parametros": parametros.urlencode(),
    })
