from mysql_nuevo.bloqueos import es_error_transitorio
from django.contrib import messages
from django.conf import settings
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
    pagina = Paginator(documentos, 15).get_page(request.GET.get("page"))
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "ventas/lista.html", {"pagina": pagina, "filtros": filtros, "parametros": parametros.urlencode(), "paginas": pagina.paginator.get_elided_page_range(pagina.number, on_each_side=2, on_ends=1)})


@login_required
def nueva_venta(request):
    datos = request.POST if request.method == "POST" else None
    from .vistas_cobro_compartido import LineasProductos, VendedorForm, habilitado, filas_productos
    combinada = habilitado(request.user)
    productos = LineasProductos(datos, prefix="productos") if combinada else None
    vendedor = VendedorForm(datos, prefix="vendedor") if combinada else None
    form = VentaForm(datos)
    lineas = LineasFormSet(datos, prefix="lineas")
    try:
        catalogo = leer_tipos_pago()
        error_pagos = ""
    except (ValueError, KeyError, OSError, TypeError):
        catalogo = {}
        error_pagos = "Revisa ventas/config/tipos_pago.json: cada tipo debe tener id, nombre y moneda USD o BS."
    datos_pagos = datos
    if datos is not None and datos.get("codigo_regalo", "").strip():
        datos_pagos = datos.copy()
        # Una tarjeta puede cubrir todo el importe sin una segunda forma de pago.
        for i in range(25):
            prefijo = f"pagos-{i}-"
            monto = datos.get(prefijo + "monto", "").strip()
            if monto in {"", "0", "0.0", "0.00"} and not any(
                datos.get(prefijo + campo, "").strip()
                for campo in ("referencia", "observacion", "cuenta_bancaria")
            ):
                datos_pagos[prefijo + "DELETE"] = "on"
    pagos = PagosVentaFormSet(datos_pagos, prefix="pagos", form_kwargs={"catalogo": catalogo, "exigir_cuenta": True, "usuario": request.user if request.user.has_perm("ventas.view_pagoventa") else None})
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
        productos_validos = productos is None or productos.is_valid()
        vendedor_valido = vendedor is None or vendedor.is_valid()
        if cabecera_valida and detalle_valido and pagos_validos and productos_validos and vendedor_valido and not error_config:
            filas = [f.cleaned_data for f in lineas if f.cleaned_data and not f.cleaned_data.get("DELETE")]
            for fila in filas:
                fila.pop("promocion", None)
            try:
                opciones = dict(
                    fecha=form.cleaned_data["fecha"], cliente=form.cleaned_data["cliente"],
                    aplicar_descuento=form.cleaned_data["aplicar_descuento"], descuento_porcentaje=form.cleaned_data["descuento_porcentaje"],
                    hora_atencion=form.cleaned_data["hora_atencion"], cita_id=form.cleaned_data["cita_id"],
                    entidad_id=form.cleaned_data["entidad"].pk if form.cleaned_data["entidad"] else None,
                    fidelidad_automatica=True, codigo_regalo=form.cleaned_data["codigo_regalo"],
                    clave=form.cleaned_data["clave"], usuario=request.user,
                )
                filas_pagos = [p.cleaned_data for p in pagos if p.cleaned_data and not p.cleaned_data.get("DELETE")]
                detalle_productos = filas_productos(productos) if productos is not None else []
                if detalle_productos:
                    from .cobro_compartido import registrar_venta_combinada
                    if len(filas_pagos) != 1:
                        raise ValidationError("Para una venta combinada registra una sola forma de pago.")
                    cobro = registrar_venta_combinada(servicios=filas, productos=detalle_productos,
                        pago=filas_pagos[0], prestador=vendedor.cleaned_data["prestador"], **opciones)
                    messages.success(request, f"Cobro compartido #{cobro.pk} registrado con sus dos facturas.")
                    return redirect("ventas:ver", pk=cobro.servicios_id)
                documento = registrar_venta(lineas=filas, pagos=filas_pagos, **opciones)
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
                if not es_error_transitorio(error):
                    raise
                form.add_error(None, "Otra operación está guardando datos. Espera unos segundos y vuelve a guardar.")
            else:
                messages.success(request, f"Documento {documento} registrado.")
                return redirect("ventas:ver", pk=documento.pk)
    tasa_factura = TasaBCV.objects.filter(fecha=form["fecha"].initial, tasa_bcv__gt=0).values_list("tasa_bcv", flat=True).first()
    from ventas_productos.servicios import puede_dar_promocion
    promociones = getattr(settings, "PROMOCIONES_FIDELIDAD", False) and puede_promocionar(request.user)
    precios = {str(s.pk): str(s.precio) for s in lineas.empty_form.fields["servicio"].queryset}
    retenciones = {str(s.pk): s.retencion_impuesto for s in lineas.empty_form.fields["servicio"].queryset}
    modos_precio = {str(s.pk): s.modo_precio for s in lineas.empty_form.fields["servicio"].queryset}
    return render(request, "ventas/formulario.html", {"puede_promocionar_productos": puede_dar_promocion(request.user), "tasa_factura": format(tasa_factura, ".2f") if tasa_factura is not None else "", "productos_combinados": productos, "vendedor_productos": vendedor, "ofertas_habilitadas": getattr(settings, "PROMOCIONES_FIDELIDAD", False), "promociones": promociones, "retenciones": retenciones, "modos_precio": modos_precio, "form": form, "lineas": lineas, "pagos": pagos, "catalogo_pagos": catalogo, "porcentaje": porcentaje, "error_config": error_config, "precios": precios})


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
    from inventario.views import regreso
    return render(request, "ventas/documento.html", {"documento": documento, "pagos": pagos,
                  "resumen_pagos": resumen_pagos, "regresar": regreso(request, "ventas:lista")})


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
            if not es_error_transitorio(error):
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
        return JsonResponse({"error": "No hay tasa Bs para esta fecha. Regístrala antes de vender."}, status=404)
    return JsonResponse({"tasa": format(tasa.tasa_bcv, ".2f")})

def puede_promocionar(usuario):
    return usuario.has_perm("ventas.change_tarjetafidelidad") or usuario.groups.filter(name__iexact="ENCARGADO").exists()


@login_required
@require_GET
def tarjeta_cliente(request, pk):
    from django.core.exceptions import PermissionDenied
    from clientes.models import Cliente
    from .fidelidad import tarjetas

    if not request.user.has_perm("ventas.add_documentoventa"):
        raise PermissionDenied
    cliente = get_object_or_404(Cliente, pk=pk, activo=True)
    resumen = request.GET.get("resumen") == "1"
    disponibles = tarjetas(cliente, incluir_historial=not resumen)
    if resumen:
        return JsonResponse({
            "beneficios": [{"servicio": t.servicio.nombre, "porcentaje": str(t.porcentaje)} for t in disponibles if t.disponible],
            "progreso": [{"servicio": t.servicio.nombre, "acumulados": t.acumulados, "meta": t.cortes}
                         for t in disponibles],
        })
    plantilla = "ventas/tarjeta_detalle.html" if request.GET.get("panel") == "1" else "ventas/tarjeta.html"
    return render(request, plantilla, {"cliente": cliente, "tarjetas": disponibles})

@login_required
@require_GET
def consultar_ofertas(request, pk):
    from django import forms
    from django.core.exceptions import PermissionDenied
    from django.utils import timezone
    from clientes.models import Cliente
    from .promociones import citas_del_dia, horas_atencion, ofertas
    from .fidelidad import tarjetas

    if not request.user.has_perm("ventas.add_documentoventa") or not getattr(settings, "PROMOCIONES_FIDELIDAD", False):
        raise PermissionDenied
    cliente = get_object_or_404(Cliente, pk=pk, activo=True)
    fecha = timezone.localdate()
    try:
        hora = forms.TimeField(required=False).clean(request.GET.get("hora"))
        cita = forms.IntegerField(required=False, min_value=1, max_value=9223372036854775807).clean(request.GET.get("cita"))
        entidad_id = forms.IntegerField(required=False, min_value=1, max_value=9223372036854775807).clean(request.GET.get("entidad"))
        vigentes = ofertas(cliente, fecha, hora, cita, entidad_id)
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)
    return JsonResponse({
        "fidelidad": {t.servicio_id: str(t.porcentaje) for t in tarjetas(cliente) if t.disponible and fecha >= t.desde},
        "horas": [h.isoformat(timespec="seconds" if h.second else "minutes") for h in horas_atencion(fecha, entidad_id)],
        "ofertas": {pk: {"nombre": p.nombre, "porcentaje": str(p.porcentaje)} for pk, p in vigentes.items()},
        "citas": [{"id": c.pk, "hora": c.hora.strftime("%H:%M"), "prestador": str(c.barbero)}
                  for c in citas_del_dia(cliente, fecha).select_related("barbero").order_by("hora", "pk")],
    })
