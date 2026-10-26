from datetime import date
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET
from inventario.condiciones import tasa_para_fecha, iva_vigente
from inventario.views import regreso
from ventas.pagos_calculos import leer_tipos_pago
from .models import DocumentoProducto
from .forms import CabeceraForm, LineasFormSet, PagosFormSet, FiltroForm, ReversoForm
from .servicios import registrar_venta, registrar_reverso

@login_required(login_url="iniciar_sesion")
def lista(request):
    filtros=FiltroForm(request.GET)
    datos=DocumentoProducto.objects.filter(sellado=True).select_related("cliente","documento_original","reverso")
    if filtros.is_valid():
        f=filtros.cleaned_data
        if f.get("numero"): datos=datos.filter(pk=f["numero"])
        if f.get("tipo"): datos=datos.filter(tipo=f["tipo"])
        if f.get("desde"): datos=datos.filter(fecha__gte=f["desde"])
        if f.get("hasta"): datos=datos.filter(fecha__lte=f["hasta"])
        for palabra in f.get("cliente","").upper().split():
            datos=datos.filter(descripcion_cliente__icontains=palabra)
        if f.get("producto"):
            texto=f["producto"].upper()
            datos=datos.filter(Q(detalles__codigo__icontains=texto)|Q(detalles__descripcion__icontains=texto)).distinct()
    else: datos=datos.none()
    pagina=Paginator(datos,25).get_page(request.GET.get("page"))
    query=request.GET.copy();query.pop("page",None)
    return render(request,"ventas_productos/lista.html",{"filtros":filtros,"pagina":pagina,"query":query.urlencode()})

@login_required(login_url="iniciar_sesion")
def nueva(request):
    datos=request.POST if request.method=="POST" else None
    aviso_existencias=[]
    aviso_producto=None
    form=CabeceraForm(datos)
    lineas=LineasFormSet(datos,prefix="lineas")
    try:
        catalogo=leer_tipos_pago()
        iva=iva_vigente()
        error_config=""
    except (ValueError,KeyError,OSError,TypeError,ArithmeticError,ValidationError):
        catalogo={};iva=None
        error_config="Revisa la configuración compartida de IVA y formas de pago de Ventas."
    pagos=PagosFormSet(datos,prefix="pagos",form_kwargs={"catalogo":catalogo})
    if request.method=="POST":
        validos=[form.is_valid(),lineas.is_valid(),pagos.is_valid()]
        if all(validos) and not error_config:
            try:
                doc=registrar_venta(fecha=form.cleaned_data["fecha"],cliente=form.cleaned_data["cliente"],
                    lineas=[f.cleaned_data for f in lineas if f.cleaned_data and not f.cleaned_data.get("DELETE")],
                    pagos=[f.cleaned_data for f in pagos if f.cleaned_data and not f.cleaned_data.get("DELETE")],
                    clave=form.cleaned_data["clave"],usuario=request.user,observacion=form.cleaned_data["observacion"])
            except ValidationError as exc:
                form.add_error(None,exc)
                if getattr(exc,"code",None)=="stock_insuficiente":
                    aviso_existencias=exc.messages
                    aviso_producto=(exc.params or {}).get("producto_id")
            except (IntegrityError,OperationalError):
                doc=DocumentoProducto.objects.filter(clave=form.cleaned_data["clave"],sellado=True).first()
                if doc:return redirect("ventas_productos:ver",pk=doc.pk)
                form.add_error(None,"No se registró la venta. Recarga y verifica las existencias antes de intentar nuevamente.")
            else:
                messages.success(request,"Venta registrada. Las existencias se descontaron una sola vez.")
                return redirect("ventas_productos:ver",pk=doc.pk)
    return render(request,"ventas_productos/formulario.html",{
        "form":form,"lineas":lineas,"pagos":pagos,"catalogo":catalogo,"iva":iva,"error_config":error_config,"aviso_existencias":aviso_existencias,"aviso_producto":aviso_producto})

@login_required(login_url="iniciar_sesion")
@require_GET
def condiciones(request):
    try: fecha=date.fromisoformat(request.GET.get("fecha",""))
    except ValueError:return JsonResponse({"error":"Fecha inválida."},status=400)
    try: tasa,iva=tasa_para_fecha(fecha),iva_vigente()
    except ValidationError as exc:return JsonResponse({"error":" ".join(exc.messages)},status=422)
    from .models import EscalaDescuento
    return JsonResponse({"tasa":format(tasa,".2f"),"iva":format(iva,".2f"),
        "escalas":[{"nivel":r.nivel,"unidades":format(r.unidades_mayor_que,".2f"),"porcentaje":format(r.porcentaje,".2f")}
                    for r in EscalaDescuento.objects.filter(activo=True)]})

@login_required(login_url="iniciar_sesion")
def ver(request,pk):
    doc=get_object_or_404(DocumentoProducto.objects.select_related("documento_original","reverso").prefetch_related("detalles","pagos"),
                         pk=pk,sellado=True)
    return render(request,"ventas_productos/documento.html",{"documento":doc,"regresar":regreso(request,"ventas_productos:lista")})

@login_required(login_url="iniciar_sesion")
def reversar(request,pk):
    original=get_object_or_404(DocumentoProducto,pk=pk,sellado=True)
    if original.tipo!="VP" or hasattr(original,"reverso"):
        messages.warning(request,"La venta ya fue reversada o no admite reverso.")
        return redirect("ventas_productos:ver",pk=pk)
    form=ReversoForm(request.POST if request.method=="POST" else None)
    if request.method=="POST" and form.is_valid():
        try: doc=registrar_reverso(documento_id=pk,motivo=form.cleaned_data["motivo"],usuario=request.user)
        except ValidationError as exc:form.add_error(None,exc)
        except (IntegrityError,OperationalError):
            form.add_error(None,"No se registró el reverso. Comprueba si otro usuario ya lo registró.")
        else:
            messages.success(request,"Reverso registrado. Los productos regresaron al inventario.")
            return redirect("ventas_productos:ver",pk=doc.pk)
    return render(request,"ventas_productos/reverso.html",{"form":form,"documento":original})

@login_required(login_url="iniciar_sesion")
@require_GET
def precio(request):
    from inventario.models import Producto
    from .precios import precio_producto
    try:
        pk=int(request.GET.get("producto",""))
        fecha=date.fromisoformat(request.GET.get("fecha",""))
    except (TypeError,ValueError):
        return JsonResponse({"error":"Selecciona producto y fecha."},status=400)
    producto=get_object_or_404(Producto,pk=pk,activo=True)
    try:datos=precio_producto(producto,fecha)
    except ValidationError as exc:return JsonResponse({"error":" ".join(exc.messages)},status=422)
    return JsonResponse({k:format(v,".2f") for k,v in datos.items()})

@login_required(login_url="iniciar_sesion")
def configuracion(request,tipo):
    from .models import PorcentajeProducto,EscalaDescuento
    consulta=PorcentajeProducto.objects.select_related("producto","producto__unidad_medida") if tipo=="porcentajes" else EscalaDescuento.objects.all()
    q=request.GET.get("q","").strip().upper()
    if tipo=="porcentajes" and q:consulta=consulta.filter(Q(producto__codigo_producto__icontains=q)|Q(producto__nombre_producto__icontains=q))
    pagina=Paginator(consulta,25).get_page(request.GET.get("page"))
    params=request.GET.copy();params.pop("page",None)
    return render(request,"ventas_productos/configuracion.html",{"tipo":tipo,"pagina":pagina,"query":params.urlencode(),
        "regresar":regreso(request,"ventas_productos:lista"),"ruta_actual":request.get_full_path(),
        "puede_agregar":tipo=="porcentajes" or EscalaDescuento.objects.count()<4})

@login_required(login_url="iniciar_sesion")
def configurar(request,tipo,pk=None):
    from .models import PorcentajeProducto,EscalaDescuento
    from .forms import PorcentajeForm,EscalaForm
    modelo,clase=(PorcentajeProducto,PorcentajeForm) if tipo=="porcentajes" else (EscalaDescuento,EscalaForm)
    instancia=get_object_or_404(modelo,pk=pk) if pk is not None else None
    form=clase(request.POST if request.method=="POST" else None,instance=instancia)
    destino=regreso(request,"ventas_productos:"+tipo)
    if request.method=="POST" and form.is_valid():
        try:
            regla=form.save(commit=False)
            regla.save(force_insert=instancia is None)
        except IntegrityError:form.add_error(None,"Ese producto, nivel o umbral ya está registrado.")
        else:return redirect(destino)
    return render(request,"ventas_productos/configurar.html",{"form":form,"tipo":tipo,"regresar":destino})
