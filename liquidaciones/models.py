import uuid
from django.core.exceptions import ValidationError
from django.db import models
from ventas.models import Inmutable


class Liquidacion(Inmutable):
    id_cancelacion = models.BigAutoField(primary_key=True)
    fecha_cancelacion = models.DateField()
    prestador = models.ForeignKey("barberos.Barbero", on_delete=models.PROTECT, related_name="liquidaciones")
    nombre_prestador = models.CharField(max_length=220)
    periodo_desde = models.DateField()
    periodo_hasta = models.DateField()
    tasa_bcv = models.DecimalField(max_digits=18, decimal_places=2)
    total_servicios_usd = models.DecimalField(max_digits=18, decimal_places=2)
    total_comision_usd = models.DecimalField(max_digits=18, decimal_places=2)
    total_bs = models.DecimalField(max_digits=18, decimal_places=2)
    registrado_por = models.CharField(max_length=150)
    creado_en = models.DateTimeField(auto_now_add=True)
    clave = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sellado = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["-fecha_cancelacion", "-id_cancelacion"]
        verbose_name = "Liquidación"
        verbose_name_plural = "Liquidaciones"

    def __str__(self):
        return f"LIQ-{self.pk:06d}"


class DetalleLiquidacion(Inmutable):
    liquidacion = models.ForeignKey(Liquidacion, on_delete=models.PROTECT, related_name="detalles")
    detalle_venta = models.OneToOneField("ventas.DetalleVenta", on_delete=models.PROTECT, related_name="comision_liquidada")
    ajuste_de = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="descuento")
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2)
    monto_servicio_usd = models.DecimalField(max_digits=18, decimal_places=2)
    comision_usd = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["pk"]

    def save(self, *args, **kwargs):
        if Liquidacion.objects.filter(pk=self.liquidacion_id, sellado=True).exists():
            raise ValidationError("No puedes añadir servicios a una liquidación guardada.")
        return super().save(*args, **kwargs)


class PagoLiquidacion(Inmutable):
    liquidacion = models.ForeignKey(Liquidacion, on_delete=models.PROTECT, related_name="pagos")
    tipo_pago = models.PositiveIntegerField()
    nombre_tipo_pago = models.CharField(max_length=100)
    moneda = models.CharField(max_length=3, choices=[("USD", "USD"), ("BS", "Bs.")])
    fecha = models.DateField()
    referencia = models.CharField(max_length=100, blank=True)
    observacion = models.TextField(blank=True)
    monto = models.DecimalField(max_digits=18, decimal_places=2)
    equivalente_bs = models.DecimalField(max_digits=18, decimal_places=2)
    ajuste_redondeo_bs = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ["pk"]

    def save(self, *args, **kwargs):
        if Liquidacion.objects.filter(pk=self.liquidacion_id, sellado=True).exists():
            raise ValidationError("No puedes añadir pagos a una liquidación guardada.")
        return super().save(*args, **kwargs)
