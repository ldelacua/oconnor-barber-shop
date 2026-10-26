import json

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from barberos.models import Barbero
from .models import Horario
from .services.semana import (
    configurar_rejilla, guardar_semana, seleccion_actual, texto,
    validar_seleccion, version_semana,
)

SALT = 'horarios.matriz_semanal.v1'


class SeleccionPrestador(forms.Form):
    barbero = forms.ModelChoiceField(
        queryset=Barbero.objects.none(), label='Prestador de Servicio',
        empty_label='Selecciona un Prestador de Servicio',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_barbero'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['barbero'].queryset = Barbero.objects.select_related('silla').order_by('nombre', 'apellido')
        self.fields['barbero'].label_from_instance = lambda p: f'{p.nombre} {p.apellido}'


class SemanaForm(forms.Form):
    bloques = forms.CharField(widget=forms.HiddenInput(), max_length=200000)
    revision = forms.CharField(widget=forms.HiddenInput(), max_length=1000)
    observaciones = forms.CharField(required=False, max_length=150,
        label='Observaciones para los bloques nuevos',
        widget=forms.TextInput(attrs={'class': 'form-control', 'maxlength': '150'}))

    def __init__(self, *args, rejilla, **kwargs):
        self.rejilla = rejilla
        super().__init__(*args, **kwargs)

    def clean_bloques(self):
        try:
            datos = json.loads(self.cleaned_data['bloques'])
        except (TypeError, ValueError):
            raise forms.ValidationError('No se pudo leer la selección de bloques. Recarga e inténtalo de nuevo.')
        return validar_seleccion(datos, self.rejilla)


def _direccion(prestador):
    return reverse('horarios:listar_horarios') + f'?barbero={prestador.pk}'


@login_required
def pantalla_horarios(request):
    es_post = request.method == 'POST'
    datos = request.POST if es_post else request.GET
    selector = SeleccionPrestador(datos if datos.get('barbero') or es_post else None)
    prestador = None
    if selector.is_bound and selector.is_valid():
        prestador = selector.cleaned_data['barbero']
    contexto = {'selector': selector, 'prestador': prestador, 'titulo': 'Horarios'}
    if not prestador:
        return render(request, 'horarios/semana.html', contexto)
    horarios = list(Horario.objects.select_related("silla").filter(barbero=prestador).order_by('pk'))
    try:
        rejilla = configurar_rejilla(horarios)
    except ValidationError as error:
        contexto['error_rejilla'] = error.messages
        return render(request, 'horarios/semana.html', contexto)
    seleccion = seleccion_actual(horarios, rejilla)
    seleccion_guardada = seleccion
    revision = signing.dumps({'usuario': request.user.pk, 'prestador': prestador.pk,
                               'version': version_semana(prestador, horarios)}, salt=SALT)
    formulario = SemanaForm(request.POST if es_post else None, rejilla=rejilla, initial={
        'bloques': json.dumps(seleccion), 'revision': revision,
    })
    if es_post and formulario.is_valid():
        seleccion = formulario.cleaned_data['bloques']
        try:
            firmado = signing.loads(formulario.cleaned_data['revision'], salt=SALT, max_age=28800)
            if firmado['usuario'] != request.user.pk or firmado['prestador'] != prestador.pk:
                raise signing.BadSignature()
        except (signing.BadSignature, KeyError, TypeError, ValueError):
            formulario.add_error(None, 'La selección ha caducado o no corresponde a este prestador. Pulsa Recargar.')
        else:
            try:
                cambios = guardar_semana(prestador_id=prestador.pk, seleccion=seleccion,
                    version=firmado['version'], observaciones=formulario.cleaned_data['observaciones'])
            except ValidationError as error:
                for mensaje in error.messages:
                    formulario.add_error(None, mensaje)
            except (IntegrityError, OperationalError):
                formulario.add_error(None, 'No se pudo guardar por un conflicto de datos. Recarga la pantalla y vuelve a intentarlo.')
            else:
                mensaje = 'El horario semanal fue guardado correctamente.'
                if not cambios['agregados'] and not cambios['desactivados']:
                    mensaje = 'El horario ya estaba actualizado. No había cambios por guardar.'
                messages.success(request, mensaje)
                return redirect(_direccion(prestador))
    elif es_post and 'bloques' in formulario.cleaned_data:
        seleccion = formulario.cleaned_data['bloques']
    filas = []
    for m in range(rejilla['inicio'], rejilla['fin'], rejilla['paso']):
        hora = texto(m)
        filas.append({'hora': hora, 'celdas': [
            {'dia': d, 'seleccionada': hora in seleccion.get(str(d), [])}
            for d in range(1, 8)
        ]})
    contexto.update({
        'formulario': formulario, 'filas': filas, 'dias': Horario.DIAS_SEMANA,
        'paso': rejilla['paso'], 'recargar': _direccion(prestador),
        'seleccion_inicial': seleccion, 'seleccion_guardada': seleccion_guardada, 'puede_guardar': bool(prestador.silla_id and prestador.silla.activa),
        'sillas_anteriores': sorted({h.silla.nombre for h in horarios if h.activo and h.silla_id != prestador.silla_id}),
    })
    return render(request, 'horarios/semana.html', contexto)


@login_required
def abrir_horario(request, horario_id):
    horario = get_object_or_404(Horario.objects.select_related('barbero'), pk=horario_id)
    if request.method == 'POST':
        messages.info(request, 'Los horarios se modifican ahora desde la matriz semanal. Revisa los bloques y pulsa Guardar cambios.')
    return redirect(_direccion(horario.barbero))
