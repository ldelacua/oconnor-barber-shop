from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import TarjetaRegalo
from .tarjetas_regalo import buscar_tarjeta_activa, cobrar_tarjeta, generar_lote, normalizar


class LoteForm(forms.Form):
    cantidad = forms.IntegerField(min_value=1, max_value=500, initial=1)
    monto = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01)
    moneda = forms.ChoiceField(choices=[("USD", "USD"), ("BS", "Bs.")])


@login_required
@permission_required("ventas.view_tarjetaregalo", raise_exception=True)
@never_cache
def tarjetas(request, ambiente_admin=False):
    accion = request.POST.get("accion")
    lote = LoteForm(request.POST if accion == "generar" else None)
    if request.method == "POST":
        from django.core.exceptions import PermissionDenied
        if accion == "generar":
            if not request.user.has_perm("ventas.add_tarjetaregalo"):
                raise PermissionDenied
            if lote.is_valid():
                id_lote = generar_lote(**lote.cleaned_data)
                return redirect("ventas:regalo_pdf", lote=id_lote)
    estados = [("", "Todas"), *TarjetaRegalo.Estado.choices]
    estado = request.GET.get("estado", "")
    if estado not in dict(estados):
        estado = ""
    lista = TarjetaRegalo.objects.order_by("-creada", "-pk")
    if estado:
        lista = lista.filter(estado=estado)
    pagina = Paginator(lista, 30).get_page(request.GET.get("pagina"))
    from django.contrib import admin
    contexto = admin.site.each_context(request) if ambiente_admin else {}
    return render(request, "ventas/regalos.html", {
        **contexto, "base_regalos": "admin/base_site.html" if ambiente_admin else "base.html",
        "ambiente_admin": ambiente_admin, "title": "Tarjetas de regalo",
        "lote": lote, "pagina": pagina, "estados": estados, "estado": estado,
    })


@login_required
@permission_required(("ventas.view_tarjetaregalo", "ventas.change_tarjetaregalo"), raise_exception=True)
@never_cache
def vender(request):
    from django.utils import timezone
    from .forms import PagoForm
    from .pagos_calculos import leer_tipos_pago, total_en_usd
    from .calculos import dinero
    from tasas_bcv.models import TasaBCV

    codigo = (request.POST if request.method == "POST" else request.GET).get("codigo", "")[:24]
    tarjeta = TarjetaRegalo.objects.filter(codigo=normalizar(codigo), estado=TarjetaRegalo.Estado.PENDIENTE).first()
    tasa = TasaBCV.objects.filter(fecha=timezone.localdate()).values_list("tasa_bcv", flat=True).first()
    total_bs = (dinero(tarjeta.monto * tasa) if tarjeta.moneda == "USD" else tarjeta.monto) if tarjeta and tasa else None
    total_usd = (tarjeta.monto if tarjeta.moneda == "USD" else total_en_usd(total_bs, tasa)) if tarjeta and tasa else None
    pago = PagoForm(request.POST if request.method == "POST" else None,
                    catalogo=leer_tipos_pago(), usuario=request.user, exigir_cuenta=True,
                    initial={"fecha": timezone.localdate(), "monto": tarjeta.monto if tarjeta else None})
    pago.fields["fecha"].disabled = True
    if request.method == "POST" and tarjeta and pago.is_valid():
        try:
            cobro = cobrar_tarjeta(codigo, request.user, pago.cleaned_data)
        except ValidationError as error:
            pago.add_error(None, error)
        else:
            messages.success(request, f"Cobro #{cobro.pk} registrado. La tarjeta ya está activa.")
            return redirect("ventas:venta_tarjetas")
    pendientes = TarjetaRegalo.objects.filter(estado=TarjetaRegalo.Estado.PENDIENTE).order_by("-pk")
    pagina = Paginator(pendientes, 30).get_page(request.GET.get("pagina"))
    return render(request, "ventas/venta_tarjetas.html", {
        "codigo": codigo, "tarjeta": tarjeta, "total_bs": total_bs, "total_usd": total_usd, "pago": pago, "pagina": pagina,
    })


@login_required
@permission_required("ventas.view_tarjetaregalo", raise_exception=True)
@never_cache
def imprimir(request, lote):
    from django.http import Http404
    from .pdf_regalo import generar_pdf
    filas = list(TarjetaRegalo.objects.filter(lote=lote).order_by("pk"))
    if not filas:
        raise Http404
    respuesta = HttpResponse(generar_pdf(filas), content_type="application/pdf")
    respuesta["Content-Disposition"] = f'attachment; filename="tarjetas-{lote}.pdf"'
    return respuesta


@login_required
@permission_required("ventas.add_documentoventa", raise_exception=True)
@require_POST
@never_cache
def consultar(request):
    try:
        tarjeta = buscar_tarjeta_activa(request.POST.get("codigo", "")[:25])
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)
    return JsonResponse({"monto": str(tarjeta.monto), "moneda": tarjeta.moneda})
