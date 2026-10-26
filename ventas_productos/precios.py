from decimal import Decimal, localcontext
from django.core.exceptions import ValidationError
from control_inventario.saldos import costo_producto
from ventas.calculos import dinero
from .models import PorcentajeProducto, EscalaDescuento

def precio_producto(producto,fecha):
    regla=PorcentajeProducto.objects.filter(producto=producto,activo=True).first()
    if not regla:
        raise ValidationError(f"Configura el porcentaje de venta de {producto.codigo_producto}.")
    costo,sin_previo=costo_producto(producto.pk,fecha)
    costo=dinero(costo)
    if costo<=0:
        raise ValidationError(f"{producto.codigo_producto} no tiene un último costo positivo en USD. Registra su costo antes de vender.")
    with localcontext() as contexto:
        contexto.prec=60
        precio=dinero(costo*(Decimal("1")+regla.porcentaje/Decimal("100")))
    if precio<=0 or precio>=Decimal("10000000000000000"):
        raise ValidationError("El precio calculado está fuera del límite permitido.")
    return {"costo_unitario_usd":costo,"porcentaje_venta":regla.porcentaje,"precio_unitario_usd":precio}

def descuento_para(unidades):
    return EscalaDescuento.objects.filter(activo=True,unidades_mayor_que__lte=unidades).order_by("-unidades_mayor_que","-nivel").first()
