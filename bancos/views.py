from django import forms
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from .models import Banco, CuentaBancaria


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria'), raise_exception=True)
def lista(request):
    return render(request, 'bancos/lista.html', {
        'bancos': Banco.objects.all(), 'cuentas': CuentaBancaria.objects.select_related('banco')})


@login_required
def editar(request, tipo, pk=None):
    accion = 'add' if pk is None else 'change'
    if not request.user.has_perms(('bancos.view_banco', 'bancos.view_cuentabancaria', f'bancos.{accion}_{tipo}')):
        raise PermissionDenied
    modelo = Banco if tipo == 'banco' else CuentaBancaria
    campos = ('nombre', 'activo') if modelo is Banco else ('banco', 'nro_cuenta', 'moneda', 'activa')
    instancia = get_object_or_404(modelo, pk=pk) if pk is not None else None
    clase = forms.modelform_factory(modelo, fields=campos)
    form = clase(request.POST if request.method == 'POST' else None, instance=instancia)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('bancos:lista')
    return render(request, 'bancos/formulario.html', {'form': form, 'titulo': modelo._meta.verbose_name.capitalize()})


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.change_banco'), raise_exception=True)
def formato_estado(request, pk):
    from django.contrib import messages
    from .formatos import FormatoEstadoForm

    banco = get_object_or_404(Banco, pk=pk)
    form = FormatoEstadoForm(request.POST if request.method == 'POST' else None,
                             initial=FormatoEstadoForm.inicial(banco.formato_estado))
    if request.method == 'POST' and form.is_valid():
        banco.formato_estado = form.formato
        banco.save(update_fields=['formato_estado'])
        messages.success(request, 'Formato de estado de cuenta guardado.' if form.formato
                         else 'El banco usará el CSV estándar del sistema.')
        return redirect('bancos:formato_estado', pk=pk)
    modo_guardado = banco.formato_estado.get('modo', 'estandar')
    formatos = dict(form.fields['modo'].choices)
    return render(request, 'bancos/formato_estado.html', {
        'banco': banco, 'form': form, 'formato_guardado': formatos[modo_guardado],
    })


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco', 'bancos.add_movimientobanco'), raise_exception=True)
def importar_estado(request):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from .importacion import leer_csv, importar
    from .formatos import leer_personalizado

    class EstadoForm(forms.Form):
        cuenta = forms.ModelChoiceField(queryset=CuentaBancaria.objects.filter(activa=True, banco__activo=True))
        archivo = forms.FileField(label='Archivo del estado de cuenta')
        modo = forms.ChoiceField(label='Modo de importación', required=False, initial='agregar', choices=[
            ('agregar', 'Agregar movimientos'),
            ('reemplazar', 'Reemplazar con el extracto completo del mes'),
        ])

    from django.urls import reverse
    from .models import MovimientoBanco

    cuenta = EstadoForm.base_fields['cuenta'].queryset.filter(
        pk=request.GET['cuenta']).first() if request.GET.get('cuenta', '').isdigit() else None
    form = EstadoForm(request.POST if request.method == 'POST' else None,
                      request.FILES if request.method == 'POST' else None,
                      initial={'cuenta': cuenta})
    if request.method == 'POST' and form.is_valid():
        cuenta = form.cleaned_data['cuenta']
        try:
            archivo = form.cleaned_data['archivo']
            formato = cuenta.banco.formato_estado
            filas = leer_personalizado(archivo, cuenta, formato) if formato else leer_csv(archivo, cuenta)
            nuevos, repetidos, actualizados, retirados = importar(
                cuenta, filas, reemplazar=form.cleaned_data['modo'] == 'reemplazar')
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f'Archivo procesado correctamente. Movimientos nuevos: {nuevos}. Ya importados: {repetidos}. Actualizados: {actualizados}. Retirados: {retirados}.')
            return redirect(reverse('bancos:importar_estado') + f'?cuenta={cuenta.pk}')
    movimientos = MovimientoBanco.objects.filter(cuenta=cuenta).select_related('partida') if cuenta else MovimientoBanco.objects.none()
    return render(request, 'bancos/importar.html', {'form': form, 'cuenta': cuenta,
        'movimientos': movimientos[:30], 'cantidad': movimientos.count()})


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.add_movimientointerno'), raise_exception=True)
def vincular_pago(request):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from .vinculacion import fuentes, vincular

    class VincularForm(forms.Form):
        origen = forms.ChoiceField(choices=[(k, k.capitalize()) for k in fuentes()])
        pago_id = forms.IntegerField(min_value=1, label='ID del pago')
        cuenta = forms.ModelChoiceField(queryset=CuentaBancaria.objects.filter(activa=True, banco__activo=True))

    desde_proveedores = request.GET.get('origen') == 'PROVEEDOR' and request.GET.get('pago_id', '').isdigit()
    form = VincularForm(request.POST if request.method == 'POST' else None,
        initial={'origen': request.GET.get('origen'), 'pago_id': request.GET.get('pago_id')})
    if desde_proveedores:
        for campo in ('origen', 'pago_id'):
            form.fields[campo].disabled = True

    if request.method == 'POST' and form.is_valid():
        try:
            vincular(request.user, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Pago vinculado a la cuenta bancaria.')
            if desde_proveedores:
                from django.urls import reverse
                return redirect(reverse('pagos:consulta') + '?origen=PROVEEDOR')
            return redirect('bancos:lista')
    return render(request, 'bancos/formulario.html', {'form': form, 'titulo': 'Asignar cuenta al pago' if desde_proveedores else 'Vincular pago existente', 'desde_proveedores': desde_proveedores, 'seccion_pagos': desde_proveedores})


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco',
                      'bancos.view_movimientointerno', 'bancos.add_conciliacion'), raise_exception=True)
def conciliar_cuenta(request, pk):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from .conciliacion import conciliar, conciliar_automaticamente, sugerencias_por_monto
    from .models import MovimientoBanco, MovimientoInterno
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)

    class MovimientoChoice(forms.ModelMultipleChoiceField):
        def label_from_instance(self, obj):
            ref = getattr(obj, 'nro_transaccion', None) or obj.referencia
            return f'{obj.fecha:%d/%m/%Y} · {ref} · {obj.monto:,.2f}'

    class ConciliarForm(forms.Form):
        banco = MovimientoChoice(MovimientoBanco.objects.filter(cuenta=cuenta, partida__isnull=True), label='Movimientos del banco')
        internos = MovimientoChoice(MovimientoInterno.objects.filter(cuenta=cuenta, partida__isnull=True).order_by('-fecha','-pk'), label='Movimientos del sistema')

    if request.method == 'POST' and 'reversar_grupo' in request.POST:
        from .conciliacion import reversar
        try:
            reversar(request.user, cuenta, request.POST['reversar_grupo'])
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, 'Conciliación reversada. Los movimientos volvieron a pendientes.')
        return redirect('bancos:conciliar_cuenta', pk=cuenta.pk)
    if request.method == 'POST' and 'automatico' in request.POST:
        cantidad = conciliar_automaticamente(request.user, cuenta)
        messages.success(request, f'Grupos conciliados automáticamente: {cantidad}.')
        return redirect('bancos:conciliar_cuenta', pk=cuenta.pk)

    datos = request.POST if request.method == 'POST' else None
    if datos is not None and 'confirmar_par' in datos:
        datos = datos.copy()
        par = datos['confirmar_par'].split(':')
        if len(par) == 2:
            datos.setlist('banco', [par[0]])
            datos.setlist('internos', [par[1]])
    form = ConciliarForm(datos)
    if request.method == 'POST' and form.is_valid():
        try:
            grupo = conciliar(request.user, cuenta, [m.pk for m in form.cleaned_data['banco']],
                              [m.pk for m in form.cleaned_data['internos']], manual='confirmar_par' not in request.POST, por_monto='confirmar_par' in request.POST)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f'Conciliación {grupo.pk} registrada.')
            return redirect('bancos:conciliar_cuenta', pk=cuenta.pk)
    return render(request, 'bancos/conciliar.html', {'form': form, 'titulo': f'Conciliar {cuenta}', 'cuenta': cuenta, 'sugerencias': sugerencias_por_monto(cuenta),
        'banco_pendiente': form.fields['banco'].queryset.select_related('cargo_registrado'),
        'sistema_pendiente': form.fields['internos'].queryset.select_related('cargo_bancario'),
        'grupos': cuenta.conciliacion_set.filter(reverso__isnull=True).order_by('-pk').prefetch_related(
            'partidas_banco__movimiento', 'partidas_internas__movimiento__cargo_bancario'),
        'seleccion_banco': datos.getlist('banco') if datos else [],
        'seleccion_sistema': datos.getlist('internos') if datos else []})


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco',
                      'bancos.view_movimientointerno', 'bancos.add_conciliacion',
                      'bancos.add_movimientointerno'), raise_exception=True)
def registrar_cargo_bancario(request, pk, movimiento_id):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from .cargos import registrar_cargo
    from .models import MovimientoBanco

    movimiento = get_object_or_404(MovimientoBanco.objects.select_related('cuenta__banco'),
                                   pk=movimiento_id, cuenta_id=pk, monto__lt=0)

    class CargoForm(forms.Form):
        concepto = forms.CharField(label='Concepto', max_length=200,
                                   widget=forms.TextInput(attrs={'class': 'form-control'}))

    form = CargoForm(request.POST if request.method == 'POST' else None,
                     initial={'concepto': movimiento.descripcion[:200]})
    if request.method == 'POST' and form.is_valid():
        try:
            registrar_cargo(request.user, pk, movimiento_id, form.cleaned_data['concepto'])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Cargo bancario registrado y conciliado.')
            return redirect('bancos:conciliar_cuenta', pk=pk)
    return render(request, 'bancos/registrar_cargo.html', {'form': form, 'movimiento': movimiento})


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco',
                      'bancos.view_movimientointerno', 'bancos.add_conciliacion',
                      'bancos.delete_movimientointerno', 'bancos.add_reversoconciliacion'), raise_exception=True)
def anular_cargo_bancario(request, pk, movimiento_id):
    from django.contrib import messages
    from .cargos import anular_cargo
    from .models import CargoBancario

    cargo = get_object_or_404(CargoBancario.objects.select_related('movimiento_banco__cuenta__banco'),
                              movimiento_banco_id=movimiento_id, movimiento_banco__cuenta_id=pk)

    class AnularCargoForm(forms.Form):
        motivo = forms.CharField(label='Motivo de anulación', max_length=250,
                                 widget=forms.TextInput(attrs={'class': 'form-control'}))

    form = AnularCargoForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            anular_cargo(request.user, pk, movimiento_id, form.cleaned_data['motivo'])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Cargo anulado. El movimiento del banco permanece pendiente.')
            return redirect('bancos:conciliar_cuenta', pk=pk)
    return render(request, 'bancos/anular_cargo.html', {'form': form, 'cargo': cargo})


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco',
                      'bancos.view_movimientointerno', 'bancos.view_conciliacion', 'bancos.view_cierrebancario'), raise_exception=True)
def reporte_cuenta(request, pk):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.utils import timezone
    from .cierres import calcular_saldos, cerrar, errores_cuadre, reporte, presentar_mes, saldos_apertura
    from .models import CierreBancario
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)

    from django.urls import reverse

    cierres = CierreBancario.objects.filter(cuenta=cuenta)
    apertura_banco, apertura_sistema = saldos_apertura(cierres.first())

    class CierreForm(forms.Form):
        fecha = forms.DateField(label='Fin de mes', widget=forms.DateInput(attrs={'type': 'date'}))
        saldo_inicial_banco = forms.DecimalField(label='Saldo inicial del extracto', max_digits=18, decimal_places=2)
        saldo_inicial_sistema = forms.DecimalField(label='Saldo inicial del sistema', max_digits=18, decimal_places=2)
        saldo = forms.DecimalField(label='Saldo final del extracto', max_digits=18, decimal_places=2)

    form = CierreForm(request.POST if request.method == 'POST' else None)
    for campo, apertura in [('saldo_inicial_banco', apertura_banco), ('saldo_inicial_sistema', apertura_sistema)]:
        if apertura is not None:
            form.initial[campo] = apertura
            form.fields[campo].disabled = True
            form.fields[campo].help_text = 'Tomado del cierre anterior.'
    vista_previa = None
    errores_saldos = []
    if request.method == 'POST' and form.is_valid():
        try:
            if 'previsualizar' in request.POST:
                vista_previa = calcular_saldos(cuenta, **form.cleaned_data)
                errores_saldos = errores_cuadre(vista_previa)
            else:
                cierre = cerrar(request.user, cuenta, **form.cleaned_data)
                messages.success(request, 'Cierre registrado. Las partidas en tránsito siguen disponibles para conciliar.')
                return redirect(reverse('bancos:reporte_cuenta', args=[pk]) + f'?cierre={cierre.pk}')
        except ValidationError as error:
            form.add_error(None, error)
            if 'previsualizar' not in request.POST:
                try:
                    vista_previa = calcular_saldos(cuenta, **form.cleaned_data)
                except ValidationError:
                    pass
    from calendar import monthrange
    from datetime import date

    class MesForm(forms.Form):
        mes = forms.DateField(required=False, input_formats=['%Y-%m'],
            widget=forms.DateInput(format='%Y-%m', attrs={'type': 'month', 'class': 'form-control'}))

    filtro_mes = MesForm(request.GET)
    hoy = timezone.localdate()
    hasta = hoy
    seleccionado = get_object_or_404(cierres, pk=request.GET['cierre']) if request.GET.get('cierre', '').isdigit() else None
    mes = filtro_mes.cleaned_data.get('mes') if filtro_mes.is_valid() else None
    desde = hoy.replace(day=1)
    if mes and not seleccionado:
        desde = mes.replace(day=1)
        fin = date(mes.year, mes.month, monthrange(mes.year, mes.month)[1])
        seleccionado = cierres.filter(fecha_cierre=fin).first()
        hasta = min(fin, hoy)
    if vista_previa is not None:
        seleccionado = None
        desde = form.cleaned_data['fecha'].replace(day=1)
        datos_reporte = vista_previa
    elif seleccionado:
        desde = seleccionado.fecha_cierre.replace(day=1)
        datos_reporte = seleccionado.resumen
    else:
        datos_reporte = reporte(cuenta, hasta, desde=desde)
    saldos = datos_reporte.get('saldos')
    resumen = presentar_mes(datos_reporte, desde)
    if filtro_mes.errors and not seleccionado:
        resumen = {'conciliaciones': [], 'banco': [], 'sistema': []}
    if request.method == 'GET' and request.GET.get('excel') == '1' and not filtro_mes.errors:
        from .excel import exportar
        return exportar(cuenta, desde, resumen, saldos=saldos)
    return render(request, 'bancos/reporte.html', {'cuenta': cuenta, 'form': form, 'cierres': cierres,
        'cierre': seleccionado, 'resumen': resumen, 'filtro_mes': filtro_mes, 'periodo': desde,
        'saldos': saldos, 'errores_saldos': errores_saldos, 'vista_previa': vista_previa is not None})


 
@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco'), raise_exception=True)
def estado_cuenta(request, pk):
    from django.core.paginator import Paginator
    from django.db.models import Q, Sum
    from .importacion import motivo_bloqueo_movimiento
    from .models import CierreBancario, MovimientoBanco
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)

    class Filtros(forms.Form):
        desde = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
        hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
        buscar = forms.CharField(required=False, max_length=120)

        def clean(self):
            datos = super().clean()
            if datos.get('desde') and datos.get('hasta') and datos['desde'] > datos['hasta']:
                raise forms.ValidationError('La fecha inicial no puede ser posterior a la final.')
            return datos

    filtro = Filtros(request.GET)
    filas = MovimientoBanco.objects.filter(cuenta=cuenta).select_related('partida', 'cargo_registrado')
    if filtro.is_valid():
        d = filtro.cleaned_data
        if d.get('desde'): filas = filas.filter(fecha__gte=d['desde'])
        if d.get('hasta'): filas = filas.filter(fecha__lte=d['hasta'])
        if d.get('buscar'):
            filas = filas.filter(Q(nro_transaccion__icontains=d['buscar']) | Q(descripcion__icontains=d['buscar']))
    else:
        filas = filas.none()
    totales = filas.aggregate(abonos=Sum('monto', filter=Q(monto__gt=0), default=0),
        debitos=Sum('monto', filter=Q(monto__lt=0), default=0), neto=Sum('monto', default=0))
    query = request.GET.copy()
    query.pop('page', None)
    pagina = Paginator(filas, 30).get_page(request.GET.get('page'))
    ultimo = CierreBancario.objects.filter(cuenta=cuenta).values_list('fecha_cierre', flat=True).first()
    for movimiento in pagina:
        movimiento.bloqueo = motivo_bloqueo_movimiento(movimiento, ultimo)
    return render(request, 'bancos/estado.html', {'cuenta': cuenta, 'filtro': filtro,
        'pagina': pagina, 'query': query.urlencode(), 'totales': totales})


class DatosMovimientoForm(forms.Form):
    fecha = forms.DateField(widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    nro_transaccion = forms.CharField(label='Número de transacción', max_length=120)
    descripcion = forms.CharField(label='Descripción', max_length=500)
    monto = forms.DecimalField(max_digits=18, decimal_places=2,
                             help_text='Usa signo negativo para débitos y positivo para créditos.')

    def clean_nro_transaccion(self):
        referencia = self.cleaned_data['nro_transaccion'].upper()
        if len(referencia) > 120:
            raise ValidationError('La referencia admite hasta 120 caracteres.')
        return referencia

    def clean_monto(self):
        monto = self.cleaned_data['monto']
        if not monto:
            raise ValidationError('El monto debe ser distinto de cero.')
        return monto


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco', 'bancos.add_movimientobanco'), raise_exception=True)
def cargar_movimiento(request):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.urls import reverse
    from .importacion import agregar_movimiento, motivo_bloqueo_movimiento

    class MovimientoForm(DatosMovimientoForm):
        cuenta = forms.ModelChoiceField(queryset=CuentaBancaria.objects.filter(activa=True, banco__activo=True))

    inicial = request.GET.get('cuenta', '')
    form = MovimientoForm(request.POST if request.method == 'POST' else None,
                          initial={'cuenta': inicial if inicial.isascii() and inicial.isdigit() else None})
    if request.method == 'POST' and form.is_valid():
        try:
            movimiento = agregar_movimiento(**form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Movimiento bancario guardado. Ya está disponible para conciliar.')
            return redirect(reverse('bancos:cargar_movimiento') + f'?cuenta={movimiento.cuenta_id}')
    from django.core.paginator import Paginator
    from .models import CierreBancario, MovimientoBanco

    cuenta_id = str(form['cuenta'].value() or '')
    cuentas = form.fields['cuenta'].queryset
    cuenta = cuentas.filter(pk=int(cuenta_id)).first() if (
        cuenta_id.isascii() and cuenta_id.isdigit() and len(cuenta_id) <= 18
    ) else None
    movimientos = MovimientoBanco.objects.filter(cuenta=cuenta).select_related('partida', 'cargo_registrado') if cuenta else MovimientoBanco.objects.none()
    pagina = Paginator(movimientos, 30).get_page(request.GET.get('pagina'))
    ultimo = CierreBancario.objects.filter(cuenta=cuenta).values_list('fecha_cierre', flat=True).first() if cuenta else None
    for movimiento in pagina:
        movimiento.bloqueo = motivo_bloqueo_movimiento(movimiento, ultimo)
    return render(request, 'bancos/carga_manual.html', {
        'form': form, 'cuentas': cuentas.select_related('banco'), 'cuenta': cuenta, 'pagina': pagina,
    })

 
@login_required
def corregir_movimiento_banco(request, pk, eliminar=False):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.urls import reverse
    from .importacion import corregir_movimiento, motivo_bloqueo_movimiento
    from .models import CierreBancario, MovimientoBanco

    permiso = 'bancos.delete_movimientobanco' if eliminar else 'bancos.change_movimientobanco'
    if not request.user.has_perms(('bancos.view_banco', 'bancos.view_cuentabancaria',
                                   'bancos.view_movimientobanco', permiso)):
        raise PermissionDenied
    movimiento = get_object_or_404(MovimientoBanco.objects.select_related('cuenta__banco', 'partida', 'cargo_registrado'), pk=pk)
    cuenta_id = movimiento.cuenta_id
    if request.GET.get('desde') == 'estado' or not request.user.has_perm('bancos.add_movimientobanco'):
        volver = reverse('bancos:estado_cuenta', args=[cuenta_id])
    else:
        volver = reverse('bancos:cargar_movimiento') + f'?cuenta={cuenta_id}'
    ultimo = CierreBancario.objects.filter(cuenta_id=cuenta_id).values_list('fecha_cierre', flat=True).first()
    motivo = motivo_bloqueo_movimiento(movimiento, ultimo)
    if motivo:
        messages.error(request, f'El movimiento está protegido: {motivo.lower()}.')
        return redirect(volver)

    campos = ('fecha', 'nro_transaccion', 'descripcion', 'monto')
    clase = forms.Form if eliminar else DatosMovimientoForm
    form = clase(request.POST if request.method == 'POST' else None,
                 initial={campo: getattr(movimiento, campo) for campo in campos})
    if request.method == 'POST' and form.is_valid():
        try:
            corregir_movimiento(cuenta_id, pk, None if eliminar else form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Movimiento eliminado.' if eliminar else 'Movimiento actualizado.')
            return redirect(volver)
    return render(request, 'bancos/corregir_movimiento.html', {
        'movimiento': movimiento, 'form': form, 'eliminar': eliminar, 'volver': volver,
    })
