import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError
from django.shortcuts import get_object_or_404, redirect, render
from ventas.forms import PagoForm
from ventas.pagos_calculos import leer_tipos_pago
from .models import Compra, PagoProveedor
from .pagos_proveedor import corregir_pago, motivo_bloqueo_correccion, movimiento_proveedor, registrar_pago, saldo_compra


class PagoProveedorForm(PagoForm):
    clave = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)


@login_required(login_url='iniciar_sesion')
def pagar_proveedor(request, compra_id):
    compra = get_object_or_404(Compra.objects.select_related('proveedor'), pk=compra_id, estado=Compra.ACTUALIZADA)
    error = ''
    try:
        catalogo = leer_tipos_pago()
    except (OSError, ValueError, KeyError, TypeError):
        catalogo = {}
        error = 'No se pudo leer la configuración de formas de pago.'
    form = PagoProveedorForm(request.POST if request.method == 'POST' else None, catalogo=catalogo)
    if request.user.has_perms(('bancos.add_movimientointerno', 'bancos.view_cuentabancaria')):
        from bancos.models import CuentaBancaria
        form.fields['cuenta_bancaria'] = forms.ModelChoiceField(
            queryset=CuentaBancaria.objects.filter(activa=True, banco__activo=True).select_related('banco'),
            required=False, label='Banco y cuenta', empty_label='Sin banco ni cuenta',
            widget=forms.Select(attrs={'class': 'form-select'}))
    if request.method == 'POST' and form.is_valid() and not error:
        try:
            registrar_pago(compra_id=compra.pk, usuario=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        except (IntegrityError, OperationalError):
            form.add_error(None, 'No se registró el pago. Recarga y comprueba el saldo antes de intentar de nuevo.')
        else:
            messages.success(request, 'Abono al proveedor registrado.')
            return redirect('pagos:proveedor', compra_id=compra.pk)
    saldo = saldo_compra(compra)
    pagos = list(compra.pagos_proveedor.select_related("reverso"))
    if request.user.is_superuser:
        from bancos.models import CierreBancario, MovimientoInterno
        movimientos = {m.pago_id: m for m in MovimientoInterno.objects.filter(
            origen="PROVEEDOR", pago_id__in=[p.pk for p in pagos],
        ).select_related("partida")}
        cierres = {}
        for cuenta_id, fecha in CierreBancario.objects.filter(
            cuenta_id__in={m.cuenta_id for m in movimientos.values()},
        ).values_list("cuenta_id", "fecha_cierre"):
            if cuenta_id not in cierres or fecha > cierres[cuenta_id]:
                cierres[cuenta_id] = fecha
        for pago in pagos:
            movimiento = movimientos.get(pago.pk)
            cierre = cierres.get(movimiento.cuenta_id) if movimiento else None
            pago.puede_corregir = not hasattr(pago, "reverso") and (
                movimiento is None or (not hasattr(movimiento, "partida") and (cierre is None or movimiento.fecha > cierre))
            )
    return render(request, 'inventario/pago_proveedor.html', {'compra': compra, 'form': form,
        'saldo': saldo, 'conversion': {'total': str(saldo['total']), 'saldo': str(saldo['saldo']), 'divisa': compra.divisa}, 'pagos': pagos, 'error': error, 'catalogo': catalogo})


@login_required(login_url='iniciar_sesion')
def proveedores(request):
    from decimal import Decimal
    from django.core.paginator import Paginator
    from django.db.models import Q
    from ventas.calculos import dinero
    texto = request.GET.get('q', '').strip()
    compras = Compra.objects.filter(estado=Compra.ACTUALIZADA).select_related('proveedor').prefetch_related('detalles', 'pagos_proveedor__reverso').order_by('-fecha_compra', '-pk')
    if texto:
        compras = compras.filter(Q(numero_factura__icontains=texto) | Q(proveedor__nombre__icontains=texto))
    pagina = Paginator(compras, 25).get_page(request.GET.get('page'))
    cuentas = {}
    if request.user.has_perm('bancos.view_cuentabancaria'):
        from bancos.models import MovimientoInterno
        ids = [p.pk for compra in pagina for p in compra.pagos_proveedor.all() if not hasattr(p, 'reverso')]
        cuentas = {m.pago_id: m.cuenta for m in MovimientoInterno.objects.filter(
            origen='PROVEEDOR', pago_id__in=ids).select_related('cuenta__banco')}
    for compra in pagina:
        vigentes = [p for p in compra.pagos_proveedor.all() if not hasattr(p, 'reverso')]
        compra.pagado_mostrar = sum((p.aplicado_factura for p in vigentes), Decimal('0.00'))
        compra.saldo_mostrar = dinero(compra.total - compra.pagado_mostrar)
        compra.cuentas_pago = list(dict.fromkeys(cuentas[p.pk] for p in vigentes if p.pk in cuentas))
    return render(request, 'inventario/proveedores_pagos.html', {'pagina': pagina, 'q': texto})


@login_required(login_url='iniciar_sesion')
def tasa_proveedor(request):
    from datetime import date
    from django.http import JsonResponse
    from tasas_bcv.models import TasaBCV
    try:
        fecha = date.fromisoformat(request.GET.get('fecha', ''))
    except ValueError:
        return JsonResponse({'error': 'Fecha inválida.'}, status=400)
    tasa = TasaBCV.objects.filter(fecha=fecha).first()
    if not tasa:
        return JsonResponse({'error': 'No hay tasa Bs para la fecha del pago.'}, status=404)
    return JsonResponse({'tasa': format(tasa.tasa_bcv, '.2f')})


class ReversoProveedorForm(forms.Form):
    motivo = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}))


@login_required(login_url='iniciar_sesion')
def reverso_proveedor(request, pago_id):
    from .pagos_proveedor import reversar_pago
    pago = get_object_or_404(PagoProveedor.objects.select_related('compra__proveedor', 'reverso'), pk=pago_id)
    form = ReversoProveedorForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            reversar_pago(pago_id=pago.pk, motivo=form.cleaned_data['motivo'], usuario=request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        except (IntegrityError, OperationalError):
            form.add_error(None, 'No se registró el reverso. Recarga para comprobar el estado del pago.')
        else:
            messages.success(request, 'Pago reversado. El importe volvió al saldo pendiente de la factura.')
            return redirect('pagos:proveedor', compra_id=pago.compra_id)
    return render(request, 'inventario/reverso_pago_proveedor.html', {'pago': pago, 'form': form})


class RetiroProveedorForm(forms.Form):
    motivo = forms.CharField(label="Motivo de la eliminación", max_length=980,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))


class CorreccionProveedorForm(PagoProveedorForm):
    motivo = forms.CharField(label="Motivo de la corrección", max_length=980,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))


@login_required(login_url="iniciar_sesion")
def corregir_proveedor(request, pago_id, eliminar=False):
    if not request.user.is_superuser:
        raise PermissionDenied
    pago = get_object_or_404(PagoProveedor.objects.select_related("compra__proveedor", "reverso"), pk=pago_id)
    movimiento = movimiento_proveedor(pago.pk).first()
    bloqueo = motivo_bloqueo_correccion(pago, movimiento)
    if bloqueo:
        messages.warning(request, bloqueo)
        return redirect("pagos:proveedor", compra_id=pago.compra_id)

    datos = request.POST if request.method == "POST" else None
    if eliminar:
        form = RetiroProveedorForm(datos)
    else:
        inicial = {campo: getattr(pago, campo) for campo in ("tipo_pago", "fecha", "referencia", "observacion", "monto")}
        inicial["cuenta_bancaria"] = movimiento.cuenta_id if movimiento else None
        form = CorreccionProveedorForm(datos, initial=inicial, catalogo=leer_tipos_pago(),
                                       usuario=request.user, exigir_cuenta=True)
    if request.method == "POST" and form.is_valid():
        campos = form.cleaned_data.copy()
        motivo = campos.pop("motivo")
        try:
            corregir_pago(pago_id=pago.pk, motivo=motivo, usuario=request.user, reemplazo=None if eliminar else campos)
        except ValidationError as exc:
            form.add_error(None, exc)
        except (IntegrityError, OperationalError):
            form.add_error(None, "No se aplicó el cambio. Recarga y revisa el estado del pago.")
        else:
            messages.success(request, "Pago retirado y saldo actualizado." if eliminar else "Pago corregido y saldo actualizado.")
            return redirect("pagos:proveedor", compra_id=pago.compra_id)
    return render(request, "inventario/corregir_pago_proveedor.html", {
        "pago": pago, "form": form, "eliminar": eliminar,
    })
