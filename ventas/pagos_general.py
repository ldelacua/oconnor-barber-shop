from decimal import Decimal
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Value, CharField, DecimalField, ExpressionWrapper, Sum, Q, Func, TextField
from django.db.models.functions import Concat
from django.db.models.functions import Collate
from django.db import connection
from django.shortcuts import render
from .models import PagoVenta
from .pagos_calculos import leer_tipos_pago
from ventas_productos.models import PagoProducto
from liquidaciones.models import PagoLiquidacion
from inventario.models import PagoProveedor, ReversoPagoProveedor


class TextoUTF8MB4(Func):
    """Convierte también las columnas antiguas antes de asignar la colación."""
    template = 'CONVERT(%(expressions)s USING utf8mb4)'
    output_field = TextField()


class Filtros(forms.Form):
    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    origen = forms.ChoiceField(required=False, label='Origen')
    forma_pago = forms.ChoiceField(required=False, label='Forma de pago')
    moneda = forms.ChoiceField(required=False, choices=[('', 'Todas'), ('USD', 'USD'), ('BS', 'Bs.')])
    sentido = forms.ChoiceField(required=False, choices=[('', 'Todos'), ('E', 'Entradas'), ('S', 'Salidas')])
    referencia = forms.CharField(required=False, max_length=100)
    observacion = forms.CharField(required=False, max_length=500, label='Observación')

    def __init__(self, *args, origenes=(), formas=(), ver_bancos=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['origen'].choices = [('', 'Todos')] + list(origenes)
        if ver_bancos:
            from bancos.models import Banco
            self.fields['banco'] = forms.ModelChoiceField(
                queryset=Banco.objects.all(), required=False, empty_label='Todos', label='Banco')
        self.fields['forma_pago'].choices = [('', 'Todas')] + list(formas)
        for campo in self.fields.values():
            campo.widget.attrs['class'] = 'form-control'

    def clean(self):
        datos = super().clean()
        if datos.get('desde') and datos.get('hasta') and datos['desde'] > datos['hasta']:
            raise forms.ValidationError('La fecha inicial no puede ser posterior a la final.')
        return datos


@login_required(login_url='iniciar_sesion')
def consulta_general(request):
    fuentes = []
    reversos = ReversoPagoProveedor.objects.annotate(**{n: F('pago__'+n) for n in ['tipo_pago','nombre_tipo_pago','referencia','moneda']}, monto=-F('pago__monto'), observacion=F('motivo'))
    definiciones = [
        ('SERVICIOS', 'Cobros de servicios', 'ventas.view_pagoventa', PagoVenta.objects.filter(documento__sellado=True), 'documento_id', Concat(F('documento__cliente__nombre'), Value(' '), F('documento__cliente__apellido')), 1, 'ventas.view_documentoventa'),
        ('PRODUCTOS', 'Cobros de productos', 'ventas_productos.view_pagoproducto', PagoProducto.objects.filter(documento__sellado=True), 'documento_id', F('documento__descripcion_cliente'), 1, 'ventas_productos.view_documentoproducto'),
        ('REVERSO_PROVEEDOR', 'Reversos de pagos a proveedores', 'inventario.view_pagoproveedor', reversos, 'pago__compra_id', F('pago__compra__proveedor__nombre'), -1, 'inventario.view_compra'),
        ('PROVEEDOR', 'Pagos a proveedores', 'inventario.view_pagoproveedor', PagoProveedor.objects.all(), 'compra_id', F('compra__proveedor__nombre'), -1, 'inventario.view_compra'),
        ('LIQUIDACION', 'Liquidaciones', 'liquidaciones.view_pagoliquidacion', PagoLiquidacion.objects.filter(liquidacion__sellado=True), 'liquidacion_id', F('liquidacion__nombre_prestador'), -1, 'liquidaciones.view_liquidacion'),
    ]
    formas = {}
    catalogo = {}
    try:
        catalogo = leer_tipos_pago()
        formas.update({str(k): v['nombre'] for k, v in catalogo.items()})
    except (OSError, ValueError, TypeError, KeyError):
        pass
    for codigo, nombre, permiso, consulta, numero, tercero, signo, permiso_documento in definiciones:
        if request.user.has_perm(permiso):
            fuentes.append((codigo, nombre, consulta, numero, tercero, signo, permiso_documento))
            for k, n in consulta.order_by().values_list('tipo_pago', 'nombre_tipo_pago').distinct():
                formas.setdefault(str(k), n)
    filtro = Filtros(request.GET, origenes=[(f[0], f[1]) for f in fuentes], formas=sorted(formas.items()), ver_bancos=request.user.has_perm('bancos.view_cuentabancaria'))
    consultas = []
    totales = {k: Decimal('0.00') for k in ['entrada_usd', 'entrada_bs', 'salida_usd', 'salida_bs']}
    validos = filtro.is_valid()
    campos = ('id', 'fecha', 'nombre_tipo_pago', 'referencia', 'observacion', 'moneda', 'monto', 'numero', 'origen', 'tercero', 'flujo')
    enlaces = {}
    if validos:
        d = filtro.cleaned_data
        for codigo, nombre, consulta, numero, tercero, signo, permiso_documento in fuentes:
            origen = d.get('origen')
            if origen and codigo != origen and not (origen == 'PROVEEDOR' and codigo == 'REVERSO_PROVEEDOR'):
                continue
            consulta = consulta.order_by().annotate(numero=F(numero), origen=Value(codigo, output_field=CharField()),
                tercero=tercero, flujo=ExpressionWrapper(F('monto') * Value(signo), output_field=DecimalField(max_digits=20, decimal_places=2)))
            if d.get('banco'):
                from bancos.models import MovimientoInterno
                origen_banco = 'PRESTADOR' if codigo == 'LIQUIDACION' else codigo
                ids = MovimientoInterno.objects.filter(origen=origen_banco,
                    cuenta__banco=d['banco']).values('pago_id')
                consulta = consulta.filter(pk__in=ids)
            if d.get('desde'): consulta = consulta.filter(fecha__gte=d['desde'])
            if d.get('hasta'): consulta = consulta.filter(fecha__lte=d['hasta'])
            if d.get('forma_pago'): consulta = consulta.filter(tipo_pago=int(d['forma_pago']))
            if d.get('moneda'): consulta = consulta.filter(moneda=d['moneda'])
            if d.get('referencia'): consulta = consulta.filter(referencia__icontains=d['referencia'])
            if d.get('observacion'): consulta = consulta.filter(observacion__icontains=d['observacion'])
            if d.get('sentido') == 'E': consulta = consulta.filter(flujo__gt=0)
            if d.get('sentido') == 'S': consulta = consulta.filter(flujo__lt=0)
            for moneda, sufijo in [('USD', 'usd'), ('BS', 'bs')]:
                valores = consulta.filter(moneda=moneda).aggregate(entrada=Sum('flujo', filter=Q(flujo__gt=0)), salida=Sum('flujo', filter=Q(flujo__lt=0)))
                totales['entrada_' + sufijo] += valores['entrada'] or Decimal('0.00')
                totales['salida_' + sufijo] -= valores['salida'] or Decimal('0.00')
            if connection.vendor == 'mysql':
                # Las columnas antiguas pueden ser utf8mb3: COLLATE por sí solo
                # no cambia su charset. Primero convertir, después unificar.
                consulta = consulta.values('id', 'fecha', 'monto', 'numero', 'flujo').annotate(**{
                    nombre: Collate(TextoUTF8MB4(F(nombre)), 'utf8mb4_0900_ai_ci') for nombre in
                    ('nombre_tipo_pago', 'referencia', 'observacion', 'moneda', 'origen', 'tercero')})
            consultas.append(consulta.values(*campos))
            enlaces[codigo] = request.user.has_perm(permiso_documento)
    if validos and request.GET.get('excel') == '1':
        from .pagos_excel import descargar_excel
        filas_excel = consultas[0].union(*consultas[1:], all=True).order_by('fecha', 'origen', 'id') if consultas else []
        return descargar_excel(filas_excel, filtro.cleaned_data)
    if consultas:
        filas = consultas[0].union(*consultas[1:], all=True).order_by('-fecha', 'origen', '-id')
        pagina = Paginator(filas, 30).get_page(request.GET.get('page'))
    else:
        pagina = Paginator([], 30).get_page(request.GET.get('page'))
    cuentas = {}
    if request.user.has_perm('bancos.view_cuentabancaria'):
        from bancos.models import MovimientoInterno
        from collections import defaultdict
        por_origen = defaultdict(set)
        for fila in pagina:
            por_origen[fila['origen']].add(fila['id'])
        criterios = Q(pk__in=[])
        for origen, ids in por_origen.items():
            criterios |= Q(origen='PRESTADOR' if origen == 'LIQUIDACION' else origen, pago_id__in=ids)
        cuentas = {(m.origen, m.pago_id): m.cuenta for m in
                   MovimientoInterno.objects.filter(criterios).select_related('cuenta__banco')}
    proveedores_bancarios = set(PagoProveedor.objects.filter(
        pk__in=[fila['id'] for fila in pagina if fila['origen'] == 'PROVEEDOR'],
        tipo_pago__in=[k for k, v in catalogo.items() if v.get('afecta_banco')]
    ).values_list('pk', flat=True))
    for fila in pagina:
        fila['admite_cuenta'] = fila['origen'] == 'PROVEEDOR' and fila['id'] in proveedores_bancarios
        fila['cuenta_pago'] = cuentas.get(('PRESTADOR' if fila['origen'] == 'LIQUIDACION' else fila['origen'], fila['id']))
        fila['monto_mostrar'] = abs(fila['monto'])
        fila['enlace'] = enlaces.get(fila['origen'], False)
    totales['neto_bs'] = totales['entrada_bs'] - totales['salida_bs']
    totales['neto_usd'] = totales['entrada_usd'] - totales['salida_usd']
    query = request.GET.copy()
    query.pop('page', None)
    query.pop('excel', None)
    return render(request, 'ventas/pagos_general.html', {'filtro': filtro, 'pagina': pagina, 'totales': totales, 'query': query.urlencode()})
