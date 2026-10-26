from datetime import date
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError,OperationalError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.http import require_GET,require_POST
from django.utils import timezone
from inventario.models import Producto
from inventario.views import paginar
from inventario.existencias import productos_con_existencia
from inventario.precision import disponible_visible
from .models import DocumentoAjuste,CierreMensual,MovimientoStock
from .forms import AjusteForm,LineasAjuste,PeriodoForm,InicioCierreForm,ConteoFormSet
from .saldos import costo_producto,reporte_stock,fin_mes
from .servicios import registrar_ajuste,iniciar_cierre,guardar_conteo,confirmar_cierre,cancelar_conteo

@login_required(login_url="iniciar_sesion")
def stock(request):
    datos=request.GET.copy()
    if not datos.get("periodo"):datos["periodo"]=timezone.localdate().strftime("%Y-%m")
    filtro=PeriodoForm(datos)
    consulta=Producto.objects.none()
    cierre=None
    if filtro.is_valid():
        consulta=reporte_stock(filtro.cleaned_data["periodo"])
        texto=filtro.cleaned_data.get("q","").upper()
        if texto:consulta=consulta.filter(Q(codigo_producto__icontains=texto)|Q(nombre_producto__icontains=texto))
        cierre=CierreMensual.objects.filter(periodo=filtro.cleaned_data["periodo"],estado="C").first()
    pagina,query=paginar(request,consulta)
    parametros=datos.copy();parametros.pop("page",None);query=parametros.urlencode()
    return render(request,"control_inventario/stock.html",{"filtro":filtro,"pagina":pagina,"query":query,"cierre":cierre})

@login_required(login_url="iniciar_sesion")
def documentos(request):
    consulta=DocumentoAjuste.objects.filter(sellado=True)
    texto=request.GET.get("q","").strip().upper()
    tipo=request.GET.get("tipo","")
    if tipo in ["EN","SA"]:consulta=consulta.filter(tipo=tipo)
    if texto:consulta=consulta.filter(Q(observacion__icontains=texto)|Q(detalles__descripcion__icontains=texto)|Q(detalles__producto__codigo_producto__icontains=texto)).distinct()
    error=""
    for clave,operador in [("desde","fecha__gte"),("hasta","fecha__lte")]:
        if request.GET.get(clave):
            try:fecha=date.fromisoformat(request.GET[clave]);consulta=consulta.filter(**{operador:fecha})
            except ValueError:error="Fecha inválida.";consulta=consulta.none()
    if request.GET.get("numero"):
        try:consulta=consulta.filter(pk=int(request.GET["numero"]))
        except ValueError:error="Número inválido.";consulta=consulta.none()
    pagina,query=paginar(request,consulta)
    return render(request,"control_inventario/documentos.html",{"pagina":pagina,"query":query,"error":error})

@login_required(login_url="iniciar_sesion")
def nuevo(request):
    datos=request.POST if request.method=="POST" else None
    form=AjusteForm(datos);lineas=LineasAjuste(datos,prefix="lineas")
    if request.method=="POST":
        validos=[form.is_valid(),lineas.is_valid()]
        if all(validos):
            try:
                doc=registrar_ajuste(tipo=form.cleaned_data["tipo"],fecha=form.cleaned_data["fecha"],
                    observacion=form.cleaned_data["observacion"],clave=form.cleaned_data["clave"],
                    lineas=[f.cleaned_data for f in lineas if f.cleaned_data and not f.cleaned_data.get("DELETE")],
                    usuario=request.user.get_username())
            except ValidationError as exc:form.add_error(None,exc)
            except (IntegrityError,OperationalError):
                doc=DocumentoAjuste.objects.filter(clave=form.cleaned_data["clave"],sellado=True).first()
                if doc:return redirect("control_inventario:ver",pk=doc.pk)
                form.add_error(None,"No se registró el documento. Recarga y verifica el período y las existencias.")
            else:return redirect("control_inventario:ver",pk=doc.pk)
    return render(request,"control_inventario/nuevo.html",{"form":form,"lineas":lineas})

@login_required(login_url="iniciar_sesion")
def ver(request,pk):
    doc=get_object_or_404(DocumentoAjuste.objects.prefetch_related("detalles"),pk=pk,sellado=True)
    pagina,query=paginar(request,doc.detalles.all().order_by("pk"))
    return render(request,"control_inventario/documento.html",{"documento":doc,"pagina":pagina,"query":query})

@login_required(login_url="iniciar_sesion")
@require_GET
def buscar(request):
    texto=request.GET.get("q","").strip().upper()[:100]
    if not texto:return JsonResponse({"resultados":[],"hay_mas":False})
    consulta=productos_con_existencia(Producto.objects.select_related("unidad_medida"))
    for palabra in texto.split()[:5]:
        consulta=consulta.filter(Q(codigo_producto__icontains=palabra)|Q(nombre_producto__icontains=palabra))
    productos=list(consulta.order_by("codigo_producto","pk")[:21])
    return JsonResponse({"resultados":[{"id":p.pk,"texto":str(p),"existencia":format(disponible_visible(p.existencia),".2f")} for p in productos[:20]],"hay_mas":len(productos)>20})

@login_required(login_url="iniciar_sesion")
@require_GET
def costo(request):
    try:fecha=date.fromisoformat(request.GET.get("fecha",""));pk=int(request.GET.get("producto",""))
    except (ValueError,TypeError):return JsonResponse({"error":"Selecciona producto y fecha."},status=400)
    get_object_or_404(Producto,pk=pk)
    valor,sin_previo=costo_producto(pk,fecha)
    return JsonResponse({"costo":str(valor),"sin_previo":sin_previo})

@login_required(login_url="iniciar_sesion")
def cierres(request):
    form=InicioCierreForm(request.POST if request.method=="POST" else None)
    if request.method=="POST" and form.is_valid():
        try:cierre=iniciar_cierre(periodo=form.cleaned_data["periodo"],observacion=form.cleaned_data["observacion"],usuario=request.user.get_username())
        except ValidationError as exc:form.add_error(None,exc)
        except (IntegrityError,OperationalError):form.add_error(None,"No se inició el cierre. Recarga y comprueba si hay otro conteo.")
        else:return redirect("control_inventario:conteo",pk=cierre.pk)
    pagina,query=paginar(request,CierreMensual.objects.all())
    return render(request,"control_inventario/cierres.html",{"form":form,"pagina":pagina,"query":query})

@login_required(login_url="iniciar_sesion")
def conteo(request,pk):
    cierre=get_object_or_404(CierreMensual,pk=pk)
    consulta=cierre.detalles.all()
    q=request.GET.get("q","").strip().upper()
    if q:consulta=consulta.filter(Q(codigo__icontains=q)|Q(descripcion__icontains=q))
    pagina,query=paginar(request,consulta)
    filas=list(pagina)
    inicial=[{"renglon":d.pk,"fisico":d.fisico} for d in filas]
    datos=request.POST if request.method=="POST" else None
    formset=ConteoFormSet(datos,initial=inicial,prefix="conteo")
    error=""
    if request.method=="POST":
        if cierre.estado=="C":error="El cierre ya está confirmado."
        elif formset.is_valid():
            try:
                guardar_conteo(cierre_id=pk,revision=int(request.POST.get("revision","-1")),
                    filas=[f.cleaned_data for f in formset],ids_pagina=[d.pk for d in filas])
            except (ValidationError,ValueError) as exc:error=" ".join(exc.messages) if isinstance(exc,ValidationError) else "Versión inválida."
            except (IntegrityError,OperationalError):error="No se guardó el conteo. Recarga y verifica."
            else:
                messages.success(request,"Conteo de esta página guardado.")
                return redirect(request.get_full_path())
    return render(request,"control_inventario/conteo.html",{"cierre":cierre,"pagina":pagina,"query":query,
        "filas":zip(filas,formset),"formset":formset,"error":error,
        "pendientes":cierre.detalles.filter(fisico__isnull=True).count(),
        "posteriores":cierre.estado=="B" and MovimientoStock.objects.filter(fecha__gt=fin_mes(cierre.periodo)).exists()})

@login_required(login_url="iniciar_sesion")
@require_POST
def cerrar(request,pk):
    get_object_or_404(CierreMensual,pk=pk)
    try:confirmar_cierre(cierre_id=pk,revision=int(request.POST.get("revision","-1")),usuario=request.user.get_username())
    except (ValidationError,ValueError) as exc:messages.error(request," ".join(exc.messages) if isinstance(exc,ValidationError) else "Versión inválida.")
    except (IntegrityError,OperationalError):messages.error(request,"No se cerró el mes. Recarga y revisa los conteos y movimientos posteriores.")
    else:messages.success(request,"Mes cerrado. Los ajustes quedaron registrados y el físico es el saldo inicial del mes siguiente.")
    return redirect("control_inventario:conteo",pk=pk)

@login_required(login_url="iniciar_sesion")
@require_POST
def cancelar(request,pk):
    get_object_or_404(CierreMensual,pk=pk)
    try:cancelar_conteo(cierre_id=pk,revision=int(request.POST.get("revision","-1")))
    except (ValidationError,ValueError,IntegrityError,OperationalError):
        messages.error(request,"No se canceló el conteo. Comprueba si ya fue cerrado.")
        return redirect("control_inventario:conteo",pk=pk)
    return redirect("control_inventario:cierres")
