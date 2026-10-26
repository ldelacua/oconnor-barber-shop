from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render

from tasas_bcv.models import TasaBCV


class TasaVentaForm(forms.ModelForm):
    class Meta:
        model = TasaBCV
        fields = ['fecha', 'tasa_bcv']
        labels = {'fecha': 'Fecha', 'tasa_bcv': 'Tasa BCV'}
        widgets = {
            'fecha': forms.DateInput(format='%Y-%m-%d', attrs={
                'type': 'date', 'class': 'form-control',
            }),
            'tasa_bcv': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0.01',
            }),
        }
        error_messages = {
            'fecha': {'unique': 'Ya existe una tasa BCV para esta fecha.'},
        }

    def clean_tasa_bcv(self):
        tasa = self.cleaned_data['tasa_bcv']
        if tasa <= 0:
            raise forms.ValidationError('La tasa debe ser mayor que cero.')
        if tasa != tasa.quantize(Decimal('0.01')):
            raise forms.ValidationError('Introduce un máximo de dos decimales.')
        return tasa


@login_required
def registrar_tasa_bcv(request):
    form = TasaVentaForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            form.add_error(None, 'No fue posible guardar la tasa. Comprueba si ya existe una para esta fecha.')
        else:
            messages.success(request, 'La tasa BCV fue registrada correctamente.')
            return redirect('ventas:lista')
    return render(request, 'ventas/tasa_bcv.html', {'form': form})
