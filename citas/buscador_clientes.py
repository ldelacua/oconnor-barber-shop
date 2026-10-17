from django import forms
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from clientes.models import Cliente


@login_required
@require_GET
def buscar_clientes(request):
    texto = request.GET.get("q", "").strip()[:80]
    if len(texto) < 2:
        return JsonResponse({"resultados": []})
    clientes = Cliente.objects.filter(activo=True)
    for palabra in texto.split()[:5]:
        clientes = clientes.filter(
            Q(nombre__icontains=palabra)
            | Q(apellido__icontains=palabra)
            | Q(telefono__icontains=palabra)
        )
    clientes = clientes.order_by("nombre", "apellido", "pk").values(
        "pk", "nombre", "apellido", "telefono"
    )[:20]
    return JsonResponse({"resultados": [
        {"id": c["pk"], "texto": f'{c["nombre"]} {c["apellido"]} · {c["telefono"]}'}
        for c in clientes
    ]})


class BuscadorClienteWidget(forms.HiddenInput):
    template_name = "citas/widgets/buscador_cliente.html"
    # Se representa un buscador visible además del identificador oculto.
    is_hidden = False

    def id_for_label(self, id_):
        return f"{id_}_buscar" if id_ else id_

    def get_context(self, name, value, attrs):
        contexto = super().get_context(name, value, attrs)
        etiqueta = ""
        if value not in (None, ""):
            try:
                cliente = Cliente.objects.filter(pk=int(value)).first()
            except (TypeError, ValueError, OverflowError):
                cliente = None
            if cliente:
                etiqueta = f"{cliente.nombre} {cliente.apellido} · {cliente.telefono}"
        contexto["widget"]["etiqueta_cliente"] = etiqueta
        return contexto
