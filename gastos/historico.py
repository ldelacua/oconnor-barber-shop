from collections import defaultdict
from decimal import Decimal

from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from ventas.pagos_calculos import total_en_usd

from .forms import FiltrosForm
from .models import DetalleRegistroGasto, GrupoGasto, RegistroGasto, TipoGasto

CERO = Decimal("0.00")


def filtrar_gastos(filtros):
    gastos = RegistroGasto.objects.all()
    if not filtros.is_valid():
        return gastos.none()
    for campo, lookup in (
        ("desde", "fecha_gasto__gte"), ("hasta", "fecha_gasto__lte"),
        ("grupo", "gasto__grupo"), ("gasto", "gasto"), ("proveedor", "proveedor"),
        ("moneda", "moneda"), ("factura", "numero_factura__icontains"),
    ):
        valor = filtros.cleaned_data.get(campo)
        if valor:
            gastos = gastos.filter(**{lookup: valor})
    return gastos


def _por_producto(gastos):
    productos = defaultdict(dict)
    desglosado = defaultdict(lambda: defaultdict(lambda: CERO))
    detalles = DetalleRegistroGasto.objects.filter(registro_gasto__in=gastos).select_related(
        "registro_gasto__proveedor", "producto",
    ).order_by("producto__descripcion", "producto_id", "-registro_gasto__fecha_gasto", "-registro_gasto_id", "pk")
    for linea in detalles.iterator():
        gasto = linea.registro_gasto
        moneda = gasto.moneda.lower()
        tipo_id = gasto.gasto_id
        fila = productos[tipo_id].setdefault(linea.producto_id, {
            "nombre": linea.producto.descripcion, "unidad": linea.producto.get_unidad_medida_display(),
            "cantidad": CERO, "sin_importe": 0, "id": f"{tipo_id}-{linea.producto_id}", "facturas": {},
        })
        fila["cantidad"] += linea.cantidad
        factura = fila["facturas"].setdefault(gasto.pk, {
            "gasto": gasto, "cantidad": CERO, "monto": None, "sin_importe": False,
        })
        factura["cantidad"] += linea.cantidad
        subtotal = linea.subtotal
        if subtotal is None:
            fila["sin_importe"] += 1
            factura["sin_importe"] = True
            continue
        factura["monto"] = (factura["monto"] or CERO) + subtotal
        fila[moneda] = fila.get(moneda, CERO) + subtotal
        desglosado[tipo_id][moneda] += subtotal
    for por_tipo in productos.values():
        for producto in por_tipo.values():
            for factura in producto["facturas"].values():
                gasto, monto = factura["gasto"], factura["monto"]
                if monto is not None:
                    if gasto.moneda == "USD":
                        factura["usd"] = monto
                    elif gasto.tasa_bcv and gasto.tasa_bcv > 0:
                        factura["usd"] = total_en_usd(monto, gasto.tasa_bcv)
    return productos, desglosado


def _por_tipo_y_grupo(gastos):
    productos, desglosado = _por_producto(gastos)
    tipos, totales = {}, {}
    campos = ("gasto_id", "gasto__descripcion", "gasto__grupo_id", "gasto__grupo__descripcion")
    filas = gastos.values(*campos, "moneda").annotate(monto=Sum("monto_gasto"))
    for fila in filas.order_by(campos[1], campos[0], campos[3], campos[2], "moneda"):
        tipo_id = fila["gasto_id"]
        tipo = tipos.setdefault(tipo_id, {"nombre": fila["gasto__descripcion"], "grupos": {}, "totales": {}})
        grupo = tipo["grupos"].setdefault(fila["gasto__grupo_id"], {
            "nombre": fila["gasto__grupo__descripcion"], "totales": {}, "diferencias": {},
            "productos": list(productos[tipo_id].values()),
        })
        moneda, monto = fila["moneda"].lower(), fila["monto"]
        grupo["totales"][moneda] = monto
        for destino in (tipo["totales"], totales):
            destino[moneda] = destino.get(moneda, CERO) + monto
        diferencia = monto - desglosado[tipo_id][moneda]
        if diferencia:
            grupo["diferencias"][moneda] = diferencia
    return list(tipos.values()), totales


@login_required
@permission_required("gastos.view_registrogasto", raise_exception=True)
@require_GET
def historico(request, grupo_id=None, tipo_id=None):
    filtros = FiltrosForm(request.GET)
    gastos = filtrar_gastos(filtros)
    grupo = get_object_or_404(GrupoGasto, pk=grupo_id) if grupo_id is not None else None
    tipo = get_object_or_404(TipoGasto, pk=tipo_id, grupo=grupo) if tipo_id is not None else None
    if grupo is not None:
        gastos = gastos.filter(gasto__grupo=grupo)
    if tipo is not None:
        gastos = gastos.filter(gasto=tipo)

    tipos, totales = _por_tipo_y_grupo(gastos)
    return render(request, "gastos/historico.html", {
        "filtros": filtros, "tipos": tipos, "totales": totales, "seccion": "historico",
    })
