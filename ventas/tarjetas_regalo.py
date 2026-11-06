"""Operaciones sobre las tarjetas de regalo; el canje se confirma junto con la factura."""
from decimal import Decimal, InvalidOperation
from secrets import choice
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import TarjetaRegalo
from .pagos_calculos import total_en_usd

ALFABETO = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
TIPOS_REGALO = {
    "USD": {"id": 990001, "nombre": "Tarjeta de regalo USD", "moneda": "USD", "afecta_banco": False},
    "BS": {"id": 990002, "nombre": "Tarjeta de regalo Bs.", "moneda": "BS", "afecta_banco": False},
}


def normalizar(codigo):
    return codigo.strip().replace("-", "").upper()


@transaction.atomic
def generar_lote(cantidad, monto, moneda):
    try:
        monto = Decimal(str(monto))
        valido = monto.is_finite() and 0 < monto < 10**12 and monto == monto.quantize(Decimal(".01"))
    except (InvalidOperation, ValueError):
        valido = False
    if not valido or moneda not in TIPOS_REGALO or type(cantidad) is not int or not 1 <= cantidad <= 500:
        raise ValidationError("Indica de 1 a 500 tarjetas, un monto positivo con dos decimales y una moneda válida.")
    lote = uuid4()
    for _ in range(cantidad):
        for intento in range(5):
            codigo = "".join(choice(ALFABETO) for _ in range(16))
            try:
                with transaction.atomic():
                    TarjetaRegalo.objects.create(codigo=codigo, lote=lote, monto=monto, moneda=moneda)
                break
            except IntegrityError:
                if not TarjetaRegalo.objects.filter(codigo=codigo).exists():
                    raise
        else:
            raise ValidationError("No fue posible generar un código único. Intenta de nuevo.")
    return lote


@transaction.atomic
def activar(codigo, usuario, referencia):
    tarjeta = TarjetaRegalo.objects.select_for_update().filter(codigo=normalizar(codigo)).first()
    referencia = referencia.strip()
    if not referencia or len(referencia) > 120:
        raise ValidationError("Indica la referencia del cobro de la tarjeta.")
    if not tarjeta or tarjeta.estado != TarjetaRegalo.Estado.PENDIENTE:
        raise ValidationError("La tarjeta no está pendiente de venta.")
    tarjeta.estado = TarjetaRegalo.Estado.ACTIVA
    tarjeta.activada = timezone.now()
    tarjeta.activada_por = usuario.get_username()
    tarjeta.referencia_venta = referencia
    tarjeta.save(update_fields=["estado", "activada", "activada_por", "referencia_venta"])
    return tarjeta


def buscar_tarjeta_activa(codigo, *, bloquear=False):
    codigo = normalizar(codigo)
    if len(codigo) not in (6, 16) or any(c not in ALFABETO for c in codigo):
        raise ValidationError("Introduce el código completo o sus últimos 6 caracteres.")
    consulta = TarjetaRegalo.objects.filter(estado=TarjetaRegalo.Estado.ACTIVA)
    if bloquear:
        consulta = consulta.select_for_update()
    criterio = {"codigo": codigo} if len(codigo) == 16 else {"codigo__endswith": codigo}
    tarjetas = list(consulta.filter(**criterio).order_by("pk")[:2])
    if not tarjetas:
        raise ValidationError("La tarjeta de regalo no está activa o ya fue utilizada.")
    if len(tarjetas) > 1:
        raise ValidationError("Hay más de una tarjeta activa con esos 6 caracteres. Introduce el código completo.")
    return tarjetas[0]


def preparar_canje(codigo, total_bs, tasa, pagos):
    """Llamar dentro de la transacción que guarda la factura."""
    tarjeta = buscar_tarjeta_activa(codigo, bloquear=True)
    total = total_bs if tarjeta.moneda == "BS" else total_en_usd(total_bs, tasa)
    if tarjeta.monto > total:
        raise ValidationError("La factura debe cubrir todo el valor de la tarjeta de regalo.")
    tipo = TIPOS_REGALO[tarjeta.moneda]
    fila = {"tipo_pago": tipo["id"], "monto": tarjeta.monto,
            "fecha": timezone.localdate(), "referencia": tarjeta.codigo[-4:]}
    return tarjeta, [*pagos, fila], tipo


def confirmar_canje(tarjeta, factura):
    actualizadas = TarjetaRegalo.objects.filter(pk=tarjeta.pk, estado=TarjetaRegalo.Estado.ACTIVA).update(
        estado=TarjetaRegalo.Estado.USADA, factura=factura)
    if actualizadas != 1:
        raise ValidationError("La tarjeta ya fue utilizada.")


@transaction.atomic
def cobrar_tarjeta(codigo, usuario, datos):
    from django.core.exceptions import PermissionDenied
    from bancos.models import CuentaBancaria, MovimientoInterno, CierreBancario
    from mysql_nuevo.bloqueos import serializar_operacion
    from tasas_bcv.models import TasaBCV
    from .calculos import dinero
    from .models import CobroTarjetaRegalo
    from .pagos_calculos import leer_tipos_pago

    serializar_operacion()
    if not usuario.has_perms(("ventas.view_tarjetaregalo", "ventas.change_tarjetaregalo")):
        raise PermissionDenied
    tarjeta = TarjetaRegalo.objects.select_for_update().filter(codigo=normalizar(codigo)).first()
    if not tarjeta or tarjeta.estado != TarjetaRegalo.Estado.PENDIENTE:
        raise ValidationError("La tarjeta no está pendiente de venta.")
    fecha = timezone.localdate()
    tasa = TasaBCV.objects.filter(fecha=fecha).values_list("tasa_bcv", flat=True).first()
    if not tasa or tasa <= 0:
        raise ValidationError("Registra primero la tasa Bs de hoy.")
    catalogo = leer_tipos_pago()
    tipo = catalogo.get(int(datos["tipo_pago"]))
    cuenta = datos.get("cuenta_bancaria")
    if not tipo or tipo["afecta_banco"] != bool(cuenta):
        raise ValidationError("Revisa la forma de pago y la cuenta bancaria.")
    if cuenta:
        if not usuario.has_perms(("bancos.add_movimientointerno", "bancos.view_cuentabancaria")):
            raise PermissionDenied
        cuenta = CuentaBancaria.objects.select_for_update().select_related("banco").get(pk=cuenta.pk)
        if not cuenta.activa or not cuenta.banco.activo or cuenta.moneda != tipo["moneda"]:
            raise ValidationError("Selecciona una cuenta activa en la moneda del pago.")
        if CierreBancario.objects.filter(cuenta=cuenta, fecha_cierre__gte=fecha.replace(day=1)).exists():
            raise ValidationError("El mes está cerrado para esta cuenta.")
    total_bs = dinero(tarjeta.monto * tasa) if tarjeta.moneda == "USD" else tarjeta.monto
    esperado = (tarjeta.monto if tipo["moneda"] == tarjeta.moneda
                else total_bs if tipo["moneda"] == "BS" else total_en_usd(total_bs, tasa))
    if datos["monto"] != esperado or esperado <= 0:
        moneda = "Bs." if tipo["moneda"] == "BS" else "USD"
        raise ValidationError(f"El pago debe cubrir exactamente el valor de la tarjeta: {esperado:,.2f} {moneda}, sin impuestos.")
    equivalente = dinero(esperado * tasa) if tipo["moneda"] == "USD" else esperado
    cobro = CobroTarjetaRegalo.objects.create(
        tarjeta=tarjeta, tasa=tasa, cuenta=cuenta, usuario=usuario.get_username(), fecha=fecha,
        tipo_pago=tipo["id"], nombre_tipo_pago=tipo["nombre"], moneda=tipo["moneda"],
        monto=esperado, equivalente_bs=equivalente, ajuste_redondeo_bs=total_bs - equivalente,
        referencia=datos.get("referencia", ""), observacion=datos.get("observacion", ""),
    )
    activar(tarjeta.codigo, usuario, f"Venta de tarjeta #{cobro.pk}")
    if cuenta:
        MovimientoInterno.objects.create(origen="TARJETA_REGALO", pago_id=cobro.pk, cuenta=cuenta,
                                         fecha=fecha, referencia=cobro.referencia, monto=cobro.monto)
    return cobro
