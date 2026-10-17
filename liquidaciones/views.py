import uuid
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from tasas_bcv.models import TasaBCV
from ventas.forms import PagosFormSet
from ventas.pagos_calculos import leer_tipos_pago
from .forms import CabeceraForm, FiltrosLista
from .models import Liquidacion
from .servicios import pendientes, registrar


@login_required
def crear(request):
    datos_get = request.GET.copy()
    if datos_get:
        hoy = timezone.localdate()
        for campo, valor in {"desde": hoy.replace(day=1), "hasta": hoy, "fecha_cancelacion": hoy}.items():
            if not datos_get.get(campo): datos_get[campo] = valor.isoformat()
    cabecera = CabeceraForm(request.POST if request.method == "POST" else (datos_get or None))
    errores = []
    try:
        catalogo = leer_tipos_pago()
    except (OSError, ValueError, KeyError, TypeError):
        catalogo = {}
        errores.append("No se pudo leer el catálogo de formas de pago de Ventas.")
    pagos = PagosFormSet(request.POST if request.method == "POST" else None, prefix="pagos", form_kwargs={"catalogo": catalogo})
    servicios, descuentos, tasa = [], [], None
    seleccion = request.POST.getlist("servicios") if request.method == "POST" else []
    try:
        clave = uuid.UUID(request.POST.get("clave", "")) if request.method == "POST" else uuid.uuid4()
    except ValueError:
        clave = uuid.uuid4()
        errores.append("La clave de la operación no es válida. Vuelve a consultar los servicios.")
    valido = cabecera.is_valid() if cabecera.is_bound else False
    if valido:
        datos = cabecera.cleaned_data
        if request.method != "POST":
            pagos = PagosFormSet(None, prefix="pagos", form_kwargs={"catalogo": catalogo}, initial=[{"fecha":datos["fecha_cancelacion"]}])
        try:
            servicios, descuentos = pendientes(datos["prestador"], datos["desde"], datos["hasta"], datos["fecha_cancelacion"])
        except ValidationError as error:
            errores.extend(error.messages)
        tasa = TasaBCV.objects.filter(fecha=datos["fecha_cancelacion"]).first()
        if not tasa:
            errores.append("No hay tasa BCV para la fecha de cancelación. Regístrala y vuelve a consultar.")
    if request.method == "POST":
        pagos_validos = pagos.is_valid()
        if valido and pagos_validos and not errores:
            try:
                if any(not s.isdigit() for s in seleccion):
                    raise ValidationError("La selección de servicios no es válida.")
                liquidacion = registrar(
                    prestador_id=datos["prestador"].pk, desde=datos["desde"], hasta=datos["hasta"],
                    fecha=datos["fecha_cancelacion"], seleccion=[int(s) for s in seleccion],
                    pagos=[p.cleaned_data for p in pagos if p.cleaned_data and not p.cleaned_data.get("DELETE")],
                    clave=clave, usuario=request.user,
                )
            except ValidationError as error:
                errores.extend(error.messages)
            except ObjectDoesNotExist:
                errores.append("Un dato ha cambiado. Vuelve a consultar los pendientes.")
            except IntegrityError:
                existente=Liquidacion.objects.filter(clave=clave,sellado=True).first()
                if existente:
                    return redirect("liquidaciones:ver",pk=existente.pk)
                errores.append("Algún servicio ya fue liquidado o ajustado. Vuelve a consultar los pendientes.")
            except OperationalError as error:
                if "locked" not in str(error).lower():
                    raise
                errores.append("Otra operación está guardando datos. Espera unos segundos y vuelve a consultar.")
            else:
                messages.success(request, f"Cancelación {liquidacion} registrada.")
                return redirect("liquidaciones:ver",pk=liquidacion.pk)
    for s in servicios:
        s["seleccionada"] = str(s["linea"].pk) in seleccion
    return render(request,"liquidaciones/formulario.html",{
        "cabecera":cabecera,"pagos":pagos,"catalogo":catalogo,"servicios":servicios,
        "descuentos":descuentos,"tasa":tasa,"clave":clave,"errores":errores,"consultado":valido,
        "descuento_usd":sum((s["comision"] for s in descuentos),Decimal("0.00")),
        "datos":cabecera.cleaned_data if valido else {},
        "estado":{"tasa":str(tasa.tasa_bcv) if tasa else "0", "descuento":str(sum((s["comision"] for s in descuentos),Decimal("0.00")))},
    })


@login_required
def lista(request):
    filtros=FiltrosLista(request.GET)
    documentos=Liquidacion.objects.filter(sellado=True)
    if filtros.is_valid():
        d=filtros.cleaned_data
        if d.get("numero"):documentos=documentos.filter(pk=d["numero"])
        if d.get("prestador"):documentos=documentos.filter(prestador=d["prestador"])
        if d.get("desde"):documentos=documentos.filter(fecha_cancelacion__gte=d["desde"])
        if d.get("hasta"):documentos=documentos.filter(fecha_cancelacion__lte=d["hasta"])
    else:documentos=documentos.none()
    pagina=Paginator(documentos,30).get_page(request.GET.get("page"))
    parametros=request.GET.copy();parametros.pop("page",None)
    return render(request,"liquidaciones/lista.html",{"pagina":pagina,"filtros":filtros,"parametros":parametros.urlencode()})


@login_required
def ver(request,pk):
    documento=get_object_or_404(Liquidacion.objects.prefetch_related("detalles__detalle_venta__documento","detalles__ajuste_de__liquidacion","pagos"),pk=pk,sellado=True)
    return render(request,"liquidaciones/documento.html",{"documento":documento})
