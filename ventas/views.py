from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET
from tasas_bcv.models import TasaBCV
from .calculos import leer_impuesto
from .pagos_calculos import leer_tipos_pago
from .forms import VentaForm, LineasFormSet, ReversoForm, FiltrosForm, PagosVentaFormSet
from .models import DocumentoVenta
from .servicios import registrar_venta, registrar_reverso


@login_required
def lista_documentos(request):
    filtros = FiltrosForm(request.GET)
    documentos = DocumentoVenta.objects.filter(sellado=True).select_related("cliente", "documento_original", "reverso")
    if filtros.is_valid():
        datos = filtros.cleaned_data
        if datos.get("numero"):
            documentos = documentos.filter(pk=datos["numero"])
        if datos.get("tipo"):
            documentos = documentos.filter(tipo_documento=datos["tipo"])
        if datos.get("desde"):
            documentos = documentos.filter(fecha__gte=datos["desde"])
        if datos.get("hasta"):
            documentos = documentos.filter(fecha__lte=datos["hasta"])
        for palabra in datos.get("cliente", "").split():
            documentos = documentos.filter(Q(cliente__nombre__icontains=palabra) | Q(cliente__apellido__icontains=palabra))
    else:
        documentos = documentos.none()
    pagina = Paginator(documentos, 25).get_page(request.GET.get("page"))
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "ventas/lista.html", {"pagina": pagina, "filtros": filtros, "parametros": parametros.urlencode(), "paginas": pagina.paginator.get_elided_page_range(pagina.number, on_each_side=2, on_ends=1)})


@login_required
def nueva_venta(request):
    datos = request.POST if request.method == "POST" else None
    form = VentaForm(datos)
    lineas = LineasFormSet(datos, prefix="lineas")
    try:
        catalogo = leer_tipos_pago()
        error_pagos = ""
    except (ValueError, KeyError, OSError, TypeError):
        catalogo = {}
        error_pagos = "Revisa ventas/config/tipos_pago.json: cada tipo debe tener id, nombre y moneda USD o BS."
    pagos = PagosVentaFormSet(datos, prefix="pagos", form_kwargs={"catalogo": catalogo})
    try:
        porcentaje = leer_impuesto()
        error_config = ""
    except (ValueError, OSError, KeyError, ArithmeticError):
        porcentaje = None
        error_config = "No se pudo leer ventas/config/impuesto.json. Corrige el porcentaje antes de vender."
    if error_pagos:
        error_config = (error_config + " " + error_pagos).strip()
    if request.method == "POST":
        cabecera_valida = form.is_valid()
        detalle_valido = lineas.is_valid()
        pagos_validos = pagos.is_valid()
        if cabecera_valida and detalle_valido and pagos_validos and not error_config:
            filas = [f.cleaned_data for f in lineas if f.cleaned_data and not f.cleaned_data.get("DELETE")]
            try:
                documento = registrar_venta(
                    fecha=form.cleaned_data["fecha"], cliente=form.cleaned_data["cliente"],
                    aplicar_descuento=form.cleaned_data["aplicar_descuento"], descuento_porcentaje=form.cleaned_data["descuento_porcentaje"],
                    lineas=filas, pagos=[p.cleaned_data for p in pagos if p.cleaned_data and not p.cleaned_data.get("DELETE")], clave=form.cleaned_data["clave"], usuario=request.user,
                )
            except ValidationError as error:
                form.add_error(None, error)
            except ObjectDoesNotExist:
                form.add_error(None, "Un cliente, servicio o prestador de servicio ya no está activo. Revisa la selección.")
            except IntegrityError:
                existente = DocumentoVenta.objects.filter(clave_operacion=form.cleaned_data["clave"], sellado=True).first()
                if existente:
                    return redirect("ventas:ver", pk=existente.pk)
                form.add_error(None, "No se pudo registrar el documento. Revisa los datos e inténtalo de nuevo.")
            except OperationalError as error:
                if "locked" not in str(error).lower():
                    raise
                form.add_error(None, "Otra operación está guardando datos. Espera unos segundos y vuelve a guardar.")
            else:
                messages.success(request, f"Documento {documento} registrado.")
                return redirect("ventas:ver", pk=documento.pk)
    precios = {str(s.pk): str(s.precio) for s in lineas.empty_form.fields["servicio"].queryset}
    retenciones = {str(s.pk): s.retencion_impuesto for s in lineas.empty_form.fields["servicio"].queryset}
    modos_precio = {str(s.pk): s.modo_precio for s in lineas.empty_form.fields["servicio"].queryset}
    return render(request, "ventas/formulario.html", {"retenciones": retenciones, "modos_precio": modos_precio, "form": form, "lineas": lineas, "pagos": pagos, "catalogo_pagos": catalogo, "porcentaje": porcentaje, "error_config": error_config, "precios": precios})


@login_required
def ver_documento(request, pk):
    documento = get_object_or_404(DocumentoVenta.objects.select_related("cliente", "documento_original", "reverso").prefetch_related("detalles", "pagos"), pk=pk, sellado=True)
    from decimal import Decimal
    pagos = list(documento.pagos.all())
    resumen_pagos = {
        "usd": sum((p.monto for p in pagos if p.moneda == "USD"), Decimal("0.00")),
        "bs": sum((p.monto for p in pagos if p.moneda == "BS"), Decimal("0.00")),
        "ajuste_bs": sum((p.ajuste_redondeo_bs for p in pagos), Decimal("0.00")),
    }
    return render(request, "ventas/documento.html", {"documento": documento, "pagos": pagos, "resumen_pagos": resumen_pagos})


@login_required
def reversar_documento(request, pk):
    documento = get_object_or_404(DocumentoVenta.objects.select_related("cliente", "reverso"), pk=pk, sellado=True)
    if documento.tipo_documento != "FA" or hasattr(documento, "reverso"):
        messages.warning(request, "Solo puedes reversar una FA que todavía no tenga RE.")
        return redirect("ventas:ver", pk=documento.pk)
    form = ReversoForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            reverso = registrar_reverso(documento_id=documento.pk, motivo=form.cleaned_data["motivo"], usuario=request.user)
        except ValidationError as error:
            form.add_error(None, error)
        except IntegrityError:
            form.add_error(None, "No se registró el reverso. Comprueba si otra operación ya reversó esta FA.")
        except OperationalError as error:
            if "locked" not in str(error).lower():
                raise
            form.add_error(None, "La base de datos está ocupada. Vuelve a intentarlo en unos segundos.")
        else:
            messages.success(request, f"Reverso {reverso} registrado para {documento}.")
            return redirect("ventas:ver", pk=reverso.pk)
    return render(request, "ventas/reverso.html", {"documento": documento, "form": form})


@login_required
@require_GET
def cotizacion(request):
    from datetime import date
    try:
        fecha = date.fromisoformat(request.GET.get("fecha", ""))
    except ValueError:
        return JsonResponse({"error": "Fecha no válida."}, status=400)
    tasa = TasaBCV.objects.filter(fecha=fecha).first()
    if not tasa:
        return JsonResponse({"error": "No hay tasa BCV para esta fecha. Regístrala antes de vender."}, status=404)
    return JsonResponse({"tasa": str(tasa.tasa_bcv)})
