import uuid
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SoloLecturaQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Los documentos guardados no se modifican.")
    def delete(self):
        raise ValidationError("Los documentos guardados no se eliminan.")
    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Los documentos guardados no se modifican.")
    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Utiliza el registro de Ventas para crear documentos.")


class Inmutable(models.Model):
    objects = SoloLecturaQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El registro ya está guardado. Emite un RE para corregir la venta.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los documentos guardados no se eliminan.")


class DocumentoVenta(Inmutable):
    id_documento = models.BigAutoField(primary_key=True)
    tipo_documento = models.CharField(max_length=2, choices=[("FA", "Venta"), ("RE", "Reverso")])
    fecha = models.DateField(default=timezone.localdate)
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.PROTECT, related_name="documentos_venta")
    tasa_bcv = models.DecimalField(max_digits=18, decimal_places=2)
    iva_incluido = models.BooleanField(default=True, editable=False)
    impuesto = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Impuesto (%)")
    documento_original = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reverso"
    )
    motivo_reverso = models.TextField(blank=True)
    subtotal_usd = models.DecimalField(max_digits=18, decimal_places=2)
    subtotal_bs = models.DecimalField(max_digits=18, decimal_places=2)
    total_impuesto_bs = models.DecimalField(max_digits=18, decimal_places=2)
    total_bs = models.DecimalField(max_digits=18, decimal_places=2)
    descuento_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    descuento_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    descuento_bs = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    clave_operacion = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    creado_en = models.DateTimeField(auto_now_add=True)
    registrado_por = models.CharField(max_length=150, editable=False)
    sellado = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["-fecha", "-id_documento"]
        verbose_name = "Documento de venta"
        verbose_name_plural = "Documentos de venta"

    def save(self, *args, **kwargs):
        from decimal import Decimal, InvalidOperation
        from django.db import IntegrityError, transaction
        from mysql_nuevo.bloqueos import serializar_operacion
        with transaction.atomic():
            serializar_operacion()
            if self._state.adding:
                if self.sellado:
                    raise ValidationError("Una factura debe validarse antes de finalizarla.")
                try:
                    tasa = Decimal(str(self.tasa_bcv))
                    impuesto = Decimal(str(self.impuesto))
                    descuento = Decimal(str(self.descuento_porcentaje))
                    importes = [Decimal(str(getattr(self, campo))) for campo in
                                ('subtotal_usd','subtotal_bs','total_impuesto_bs','total_bs','descuento_usd','descuento_bs')]
                    if (not all(x.is_finite() for x in [tasa, impuesto, descuento, *importes])
                        or tasa <= 0 or not 0 <= impuesto <= 100 or not 0 <= descuento <= 100):
                        raise ValueError()
                    if self.tipo_documento == 'FA':
                        if not self.iva_incluido or self.documento_original_id is not None or any(x < 0 for x in importes):
                            raise ValueError()
                    elif self.tipo_documento == 'RE':
                        original = self.documento_original
                        iguales = ('cliente_id','tasa_bcv','impuesto','iva_incluido','descuento_porcentaje')
                        negativos = ('subtotal_usd','subtotal_bs','total_impuesto_bs','total_bs','descuento_usd','descuento_bs')
                        if (not original or not original.sellado or original.tipo_documento != 'FA'
                            or any(x > 0 for x in importes)
                            or any(getattr(self,c) != getattr(original,c) for c in iguales)
                            or any(getattr(self,c) != -getattr(original,c) for c in negativos)):
                            raise ValueError()
                    else:
                        raise ValueError()
                except (InvalidOperation, ValueError, TypeError) as error:
                    raise IntegrityError("Datos de factura o reverso inválidos.") from error
            return super().save(*args, **kwargs)

    @property
    def subtotal_bruto_usd(self):
        if self.iva_incluido:
            return sum((l.monto_servicio for l in self.detalles.all()), 0)
        return self.subtotal_usd + self.descuento_usd

    @property
    def subtotal_bruto_bs(self):
        if self.iva_incluido:
            return sum((l.monto_servicio_bs for l in self.detalles.all()), 0)
        return self.subtotal_bs + self.descuento_bs

    @property
    def total_usd(self):
        from .pagos_calculos import total_en_usd
        return total_en_usd(self.total_bs, self.tasa_bcv)

    def __str__(self):
        return f"{self.tipo_documento}-{self.pk:06d}"


class DetalleVenta(Inmutable):
    documento = models.ForeignKey(DocumentoVenta, on_delete=models.PROTECT, related_name="detalles", db_column="id_documento")
    servicio = models.ForeignKey("servicios.Servicio", on_delete=models.PROTECT, related_name="detalles_venta", db_column="id_servicio")
    barbero = models.ForeignKey(
        "barberos.Barbero", null=True, blank=True,
        on_delete=models.PROTECT, related_name="detalles_venta",
    )
    descripcion_barbero = models.CharField(max_length=220, blank=True, default="")
    codigo_servicio = models.CharField(max_length=10)
    descripcion_servicio = models.CharField(max_length=100)
    cantidad_servicio = models.PositiveIntegerField()
    precio_unitario_usd = models.DecimalField(max_digits=18, decimal_places=2)
    monto_servicio = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Subtotal USD")
    monto_servicio_bs = models.DecimalField(max_digits=18, decimal_places=2)
    monto_impuesto = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Impuesto Bs.")

    retencion_impuesto = models.BooleanField(null=True, editable=False)
    impuesto_normal = models.BooleanField(default=False, editable=False)

    # Nullable únicamente para documentos históricos que sumaban IVA al precio.
    base_imponible_usd = models.DecimalField(max_digits=18, decimal_places=2, null=True, editable=False)
    base_imponible_bs = models.DecimalField(max_digits=18, decimal_places=2, null=True, editable=False)

    precio_manual = models.BooleanField(default=False)
    monto_descuento_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    monto_descuento_bs = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    linea_original = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="linea_reverso",
    )

    @property
    def monto_neto_usd(self):
        return self.monto_servicio - self.monto_descuento_usd

    @property
    def monto_neto_bs(self):
        return self.monto_servicio_bs - self.monto_descuento_bs

    class Meta:
        ordering = ["pk"]

    def save(self, *args, **kwargs):
        from django.db import IntegrityError, transaction
        from mysql_nuevo.bloqueos import serializar_operacion
        from .servicios import _validar_linea_factura, _validar_linea_reverso
        with transaction.atomic():
            serializar_operacion()
            documento = DocumentoVenta.objects.select_for_update().get(pk=self.documento_id)
            if documento.sellado:
                raise ValidationError("No puedes añadir líneas a un documento guardado.")
            if self._state.adding:
                try:
                    if documento.tipo_documento == 'FA':
                        _validar_linea_factura(documento, self)
                    elif documento.tipo_documento == 'RE':
                        _validar_linea_reverso(documento, self)
                    else:
                        raise ValidationError("Tipo de documento inválido.")
                except (ValidationError, ValueError, TypeError, ArithmeticError) as error:
                    raise IntegrityError("Precio, descuento, impuesto o reverso inválido.") from error
            return super().save(*args, **kwargs)


class PagoVenta(Inmutable):
    documento = models.ForeignKey(DocumentoVenta, on_delete=models.PROTECT, related_name="pagos")
    tipo_pago = models.PositiveIntegerField()
    nombre_tipo_pago = models.CharField(max_length=100)
    moneda = models.CharField(max_length=3, choices=[("USD", "USD"), ("BS", "Bs.")])
    fecha = models.DateField()
    referencia = models.CharField(max_length=100, blank=True)
    observacion = models.TextField(blank=True)
    monto = models.DecimalField(max_digits=18, decimal_places=2)
    equivalente_bs = models.DecimalField(max_digits=18, decimal_places=2)
    ajuste_redondeo_bs = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    pago_original = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reverso")

    class Meta:
        ordering = ["pk"]
        verbose_name = "Pago de venta"
        verbose_name_plural = "Pagos de venta"

    def save(self, *args, **kwargs):
        from django.db import IntegrityError, transaction
        from mysql_nuevo.bloqueos import serializar_operacion
        from .servicios import _validar_pago_venta
        with transaction.atomic():
            serializar_operacion()
            documento = DocumentoVenta.objects.select_for_update().get(pk=self.documento_id)
            if documento.sellado:
                raise ValidationError("No puedes añadir pagos a un documento guardado.")
            if self._state.adding:
                try:
                    _validar_pago_venta(documento, self)
                except (ValidationError, ValueError, TypeError, ArithmeticError) as error:
                    raise IntegrityError("Pago de factura inválido.") from error
            return super().save(*args, **kwargs)
