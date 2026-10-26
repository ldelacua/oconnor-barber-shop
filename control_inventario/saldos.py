from calendar import monthrange
from datetime import date
from decimal import Decimal
from django.db.models import Q,Sum,Value,DecimalField,Subquery,OuterRef,F
from django.db.models.functions import Coalesce
from inventario.models import Producto
from .models import MovimientoStock

def siguiente_mes(periodo):
    return date(periodo.year+1,1,1) if periodo.month==12 else date(periodo.year,periodo.month+1,1)
def fin_mes(periodo):return date(periodo.year,periodo.month,monthrange(periodo.year,periodo.month)[1])
def unidad(valor):return Decimal(valor or 0).quantize(Decimal(".001"))

def costo_producto(producto_id,fecha):
    dato=MovimientoStock.objects.filter(producto_id=producto_id,fecha__lte=fecha,
        costo_unitario_usd__isnull=False).order_by("-registrado_en","-id").values_list("costo_unitario_usd",flat=True).first()
    from ventas.calculos import dinero
    return (dinero(dato) if dato is not None else Decimal("0.00"),dato is None)

def reporte_stock(periodo):
    campo=DecimalField(max_digits=28,decimal_places=3)
    relacion="kardex_inventario__"
    mes=Q(kardex_inventario__fecha__gte=periodo,kardex_inventario__fecha__lt=siguiente_mes(periodo))
    def suma(filtro):
        return Coalesce(Sum(relacion+"delta",filter=filtro),Value(0),output_field=campo)
    ultimos=MovimientoStock.objects.filter(producto_id=OuterRef("pk"),fecha__lt=siguiente_mes(periodo),
        costo_unitario_usd__isnull=False).order_by("-registrado_en","-id").values("costo_unitario_usd")[:1]
    return Producto.objects.select_related('unidad_medida').annotate(
        inicial=suma(Q(kardex_inventario__fecha__lt=periodo)),
        compras=suma(mes&Q(kardex_inventario__clase="COMPRA")),
        ventas=-suma(mes&Q(kardex_inventario__clase__in=["VENTA","REVERSO"])),
        otros=suma(mes&Q(kardex_inventario__clase="OTRO")),
        costo=Coalesce(Subquery(ultimos),Value(0),output_field=DecimalField(max_digits=24,decimal_places=8)),
    ).annotate(disponible=F("inicial")+F("compras")-F("ventas")+F("otros")).order_by("codigo_producto","pk")
