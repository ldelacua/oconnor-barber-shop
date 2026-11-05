from django import forms
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
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
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco', 'bancos.add_movimientobanco'), raise_exception=True)
def importar_estado(request):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from .importacion import leer_csv, importar

    class EstadoForm(forms.Form):
        cuenta = forms.ModelChoiceField(queryset=CuentaBancaria.objects.filter(activa=True, banco__activo=True))
        archivo = forms.FileField(label='Archivo CSV')

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
            nuevos, repetidos, actualizados, retirados = importar(cuenta, leer_csv(form.cleaned_data['archivo'], cuenta))
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
    return render(request, 'bancos/formulario.html', {'form': form, 'titulo': 'Asignar cuenta al pago' if desde_proveedores else 'Vincular pago existente', 'desde_proveedores': desde_proveedores})


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
        'banco_pendiente': form.fields['banco'].queryset,
        'sistema_pendiente': form.fields['internos'].queryset,
        'grupos': cuenta.conciliacion_set.filter(reverso__isnull=True).order_by('-pk').prefetch_related(
            'partidas_banco__movimiento', 'partidas_internas__movimiento'),
        'seleccion_banco': datos.getlist('banco') if datos else [],
        'seleccion_sistema': datos.getlist('internos') if datos else []})


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco',
                      'bancos.view_movimientointerno', 'bancos.view_conciliacion', 'bancos.view_cierrebancario'), raise_exception=True)
def reporte_cuenta(request, pk):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.utils import timezone
    from .cierres import cerrar, reporte, presentar_mes
    from .models import CierreBancario
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)

    class CierreForm(forms.Form):
        fecha = forms.DateField(label='Fin de mes', widget=forms.DateInput(attrs={'type': 'date'}))
        saldo = forms.DecimalField(label='Saldo final del banco', max_digits=18, decimal_places=2)

    form = CierreForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            cerrar(request.user, cuenta, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Cierre registrado. Los pendientes siguen disponibles para conciliar.')
            return redirect('bancos:reporte_cuenta', pk=pk)
    cierres = CierreBancario.objects.filter(cuenta=cuenta)
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
    resumen = seleccionado.resumen if seleccionado else reporte(cuenta, hasta, desde=desde)
    if seleccionado:
        desde = seleccionado.fecha_cierre.replace(day=1)
    resumen = presentar_mes(resumen, desde)
    if filtro_mes.errors and not seleccionado:
        resumen = {'conciliaciones': [], 'banco': [], 'sistema': []}
    if request.method == 'GET' and request.GET.get('excel') == '1' and not filtro_mes.errors:
        from .excel import exportar
        return exportar(cuenta, desde, resumen)
    return render(request, 'bancos/reporte.html', {'cuenta': cuenta, 'form': form, 'cierres': cierres,
        'cierre': seleccionado, 'resumen': resumen, 'filtro_mes': filtro_mes, 'periodo': desde})


 
@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco'), raise_exception=True)
def estado_cuenta(request, pk):
    from django.core.paginator import Paginator
    from django.db.models import Q, Sum
    from .models import MovimientoBanco
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
    filas = MovimientoBanco.objects.filter(cuenta=cuenta).select_related('partida')
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
    return render(request, 'bancos/estado.html', {'cuenta': cuenta, 'filtro': filtro,
        'pagina': Paginator(filas, 30).get_page(request.GET.get('page')), 'query': query.urlencode(), 'totales': totales})


@login_required
@permission_required(('bancos.view_banco', 'bancos.view_cuentabancaria', 'bancos.view_movimientobanco', 'bancos.add_movimientobanco'), raise_exception=True)
def cargar_movimiento(request):
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.urls import reverse
    from .importacion import agregar_movimiento

    class MovimientoForm(forms.Form):
        cuenta = forms.ModelChoiceField(queryset=CuentaBancaria.objects.filter(activa=True, banco__activo=True))
        fecha = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
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
    from .models import MovimientoBanco

    cuenta_id = str(form['cuenta'].value() or '')
    cuentas = form.fields['cuenta'].queryset
    cuenta = cuentas.filter(pk=int(cuenta_id)).first() if (
        cuenta_id.isascii() and cuenta_id.isdigit() and len(cuenta_id) <= 18
    ) else None
    movimientos = MovimientoBanco.objects.filter(cuenta=cuenta).select_related('partida') if cuenta else MovimientoBanco.objects.none()
    pagina = Paginator(movimientos, 30).get_page(request.GET.get('pagina'))
    return render(request, 'bancos/carga_manual.html', {
        'form': form, 'cuentas': cuentas.select_related('banco'), 'cuenta': cuenta, 'pagina': pagina,
    })
