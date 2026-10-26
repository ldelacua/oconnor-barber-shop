from django import forms
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from .models import Producto
from .existencias import productos_con_existencia
from .precision import disponible_visible

@login_required(login_url="iniciar_sesion")
@require_GET
def buscar_productos(request):
    texto = request.GET.get("q", "").strip().upper()[:100]
    if not texto:
        return JsonResponse({"resultados": [], "hay_mas": False})
    productos = productos_con_existencia(Producto.objects.filter(activo=True).select_related("unidad_medida"))
    for palabra in texto.split()[:5]:
        productos = productos.filter(Q(codigo_producto__icontains=palabra) | Q(nombre_producto__icontains=palabra))
    encontrados = list(productos.order_by("codigo_producto", "pk")[:21])
    return JsonResponse({"resultados": [{"id": p.pk, "texto": str(p), "existencia": format(disponible_visible(p.existencia),".2f")} for p in encontrados[:20]],
                         "hay_mas": len(encontrados) > 20})

class BuscadorProductoWidget(forms.HiddenInput):
    template_name = "inventario/widgets/buscador_producto.html"
    is_hidden = False

    def id_for_label(self, id_):
        return f"{id_}_buscar" if id_ else id_

    def get_context(self, name, value, attrs):
        contexto = super().get_context(name, value, attrs)
        etiqueta = ""
        if value not in (None, ""):
            try:
                producto = Producto.objects.select_related("unidad_medida").filter(pk=int(value)).first()
            except (TypeError, ValueError, OverflowError):
                producto = None
            if producto:
                etiqueta = str(producto)
        contexto["widget"]["etiqueta_producto"] = etiqueta
        return contexto
