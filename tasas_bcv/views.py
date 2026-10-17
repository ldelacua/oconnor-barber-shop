from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render

from .forms import TasaBCVForm
from .models import TasaBCV


@login_required
def lista_tasas(request):
    pagina = Paginator(TasaBCV.objects.all(), 30).get_page(request.GET.get("page"))
    return render(request, "tasas_bcv/lista.html", {"pagina": pagina})


def _guardar_tasa(request, instance=None):
    form = TasaBCVForm(
        request.POST if request.method == "POST" else None,
        instance=instance,
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            # Otra petición puede haber registrado la misma fecha después de validar.
            if TasaBCV.objects.filter(fecha=form.cleaned_data["fecha"]).exclude(
                pk=instance.pk if instance else None
            ).exists():
                form.add_error("fecha", "Ya existe una tasa para esta fecha. Edita ese registro.")
            else:
                raise
        else:
            messages.success(request, "La tasa BCV fue guardada correctamente.")
            return redirect("tasas_bcv:lista")
    return render(request, "tasas_bcv/formulario.html", {
        "form": form,
        "titulo": "Editar tasa BCV" if instance else "Nueva tasa BCV",
    })


@login_required
def crear_tasa(request):
    return _guardar_tasa(request)


@login_required
def editar_tasa(request, pk):
    return _guardar_tasa(request, get_object_or_404(TasaBCV, pk=pk))
