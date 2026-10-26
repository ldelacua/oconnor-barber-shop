"""Una misma fórmula para consultas, buscador y validación de las ventas."""
from decimal import Decimal
from django.apps import apps
from django.db.models import Sum, Subquery, OuterRef, DecimalField, Value, F, Case, When
from django.db.models.functions import Coalesce
from .models import Producto, MovimientoInventario

def productos_con_existencia(queryset=None):
    datos = queryset if queryset is not None else Producto.objects.all()
    campo = DecimalField(max_digits=28, decimal_places=3)
    if apps.is_installed("control_inventario"):
        Movimiento = apps.get_model("control_inventario", "MovimientoStock")
        movimientos = Movimiento.objects.filter(producto_id=OuterRef("pk")).order_by().values("producto_id").annotate(
            suma=Sum("delta")).values("suma")
        return datos.annotate(existencia=Coalesce(Subquery(movimientos,output_field=campo),Value(0),output_field=campo))
    entradas = MovimientoInventario.objects.filter(
        detalle__producto_id=OuterRef("pk"), detalle__compra__estado="A"
    ).order_by().values("detalle__producto_id").annotate(suma=Sum("cantidad")).values("suma")
    datos = datos.annotate(entradas_stock=Coalesce(Subquery(entradas, output_field=campo), Value(0), output_field=campo))
    if apps.is_installed("ventas_productos"):
        Linea = apps.get_model("ventas_productos", "LineaProducto")
        salidas = Linea.objects.filter(producto_id=OuterRef("pk"), documento__sellado=True).order_by().values(
            "producto_id").annotate(suma=Sum(Case(
                When(documento__tipo="RP", then=-F("cantidad")), default=F("cantidad"), output_field=campo))).values("suma")
        datos = datos.annotate(salidas_stock=Coalesce(Subquery(salidas, output_field=campo), Value(0), output_field=campo))
        return datos.annotate(existencia=F("entradas_stock") - F("salidas_stock"))
    return datos.annotate(existencia=F("entradas_stock"))

def existencia_producto(pk):
    valor = productos_con_existencia(Producto.objects.filter(pk=pk)).values_list("existencia", flat=True).first()
    return valor.quantize(Decimal("0.001")) if valor is not None else Decimal("0")
