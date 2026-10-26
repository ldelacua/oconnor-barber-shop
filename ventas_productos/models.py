import uuid
from django.db import models
from django.core.exceptions import ValidationError
from ventas.pagos_calculos import total_en_usd

class DocumentoProducto(models.Model):
    tipo = models.CharField(max_length=2, choices=[("VP", "Venta de productos"), ("RP", "Reverso de productos")])
    fecha = models.DateField()
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.PROTECT)
    descripcion_cliente = models.CharField(max_length=240)
    observacion = models.TextField(blank=True)
    tasa_bcv = models.DecimalField(max_digits=18, decimal_places=6)
    iva = models.DecimalField(max_digits=5, decimal_places=2)
    subtotal_usd = models.DecimalField(max_digits=18, decimal_places=2)
    subtotal_bs = models.DecimalField(max_digits=18, decimal_places=2)
    impuesto_bs = models.DecimalField(max_digits=18, decimal_places=2)
    total_bs = models.DecimalField(max_digits=18, decimal_places=2)
    descuento_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    descuento_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    descuento_bs = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    unidades_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    descuento_nivel = models.PositiveSmallIntegerField(null=True)
    umbral_descuento = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    precio_automatico = models.BooleanField(default=False)
    clave = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    registrado_por = models.CharField(max_length=150, editable=False)
    creado_en = models.DateTimeField(auto_now_add=True)
    sellado = models.BooleanField(default=False, editable=False)
    documento_original = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reverso")
    motivo = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(tipo__in=["VP", "RP"]), name="vp_tipo_valido"),
            models.CheckConstraint(condition=models.Q(tasa_bcv__gt=0), name="vp_tasa_positiva"),
            models.CheckConstraint(condition=models.Q(iva__gte=0, iva__lte=100), name="vp_iva_valido"),
        ]

    @property
    def total_usd(self):
        return total_en_usd(self.total_bs, self.tasa_bcv)

    @property
    def base_usd(self): return self.subtotal_usd-self.descuento_usd
    @property
    def base_bs(self): return self.subtotal_bs-self.descuento_bs
    @property
    def total_unidades(self):
        return self.unidades_total or sum((l.cantidad for l in self.detalles.all()), 0)

    def __str__(self):
        return f"{self.tipo}-{self.pk:06d}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La venta guardada no se modifica. Utiliza un reverso.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los documentos de productos no se eliminan.")

class LineaProducto(models.Model):
    documento = models.ForeignKey(DocumentoProducto, on_delete=models.PROTECT, related_name="detalles")
    producto = models.ForeignKey("inventario.Producto", on_delete=models.PROTECT, related_name="ventas_producto")
    descripcion = models.CharField(max_length=300)
    codigo = models.CharField(max_length=50)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    precio_unitario_usd = models.DecimalField(max_digits=18, decimal_places=2)
    subtotal_usd = models.DecimalField(max_digits=18, decimal_places=2)
    subtotal_bs = models.DecimalField(max_digits=18, decimal_places=2)
    impuesto_bs = models.DecimalField(max_digits=18, decimal_places=2)
    costo_unitario_usd = models.DecimalField(max_digits=24, decimal_places=2, null=True)
    porcentaje_venta = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    descuento_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    descuento_bs = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    linea_original = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reverso")

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["documento", "producto"], name="vp_producto_unico_documento"),
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="vp_cantidad_positiva"),
            models.CheckConstraint(condition=models.Q(precio_unitario_usd__gt=0), name="vp_precio_positivo"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding or DocumentoProducto.objects.filter(pk=self.documento_id, sellado=True).exists():
            raise ValidationError("El detalle del documento está bloqueado.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El detalle del documento no se elimina.")

class PagoProducto(models.Model):
    documento = models.ForeignKey(DocumentoProducto, on_delete=models.PROTECT, related_name="pagos")
    tipo_pago = models.PositiveIntegerField()
    nombre_tipo_pago = models.CharField(max_length=100)
    moneda = models.CharField(max_length=3)
    fecha = models.DateField()
    referencia = models.CharField(max_length=100, blank=True)
    observacion = models.TextField(blank=True)
    monto = models.DecimalField(max_digits=18, decimal_places=2)
    equivalente_bs = models.DecimalField(max_digits=18, decimal_places=2)
    ajuste_redondeo_bs = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    pago_original = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reverso")

    class Meta:
        ordering = ["pk"]

    @property
    def equivalente_aplicado_bs(self):
        """Importe conciliado con la factura, incluido el ajuste de conversión."""
        return self.equivalente_bs + self.ajuste_redondeo_bs

    def save(self, *args, **kwargs):
        if not self._state.adding or DocumentoProducto.objects.filter(pk=self.documento_id, sellado=True).exists():
            raise ValidationError("Los pagos del documento están bloqueados.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los pagos del documento no se eliminan.")

class PorcentajeProducto(models.Model):
    producto = models.OneToOneField("inventario.Producto", primary_key=True, on_delete=models.PROTECT,
                                    related_name="porcentaje_venta", verbose_name="Producto")
    porcentaje = models.DecimalField("Recargo sobre costo (%)", max_digits=7, decimal_places=2)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["producto__codigo_producto"]
        constraints = [models.CheckConstraint(condition=models.Q(porcentaje__gte=0), name="vp_recargo_no_negativo")]

class EscalaDescuento(models.Model):
    nivel = models.PositiveSmallIntegerField(primary_key=True, choices=[(n,str(n)) for n in range(1,5)])
    unidades_mayor_que = models.DecimalField("Más de X unidades", max_digits=14, decimal_places=2, unique=True)
    porcentaje = models.DecimalField("Descuento (%)", max_digits=5, decimal_places=2)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["unidades_mayor_que"]
        constraints = [
            models.CheckConstraint(condition=models.Q(nivel__gte=1,nivel__lte=4), name="vp_cuatro_niveles"),
            models.CheckConstraint(condition=models.Q(unidades_mayor_que__gte=0), name="vp_umbral_no_negativo"),
            models.CheckConstraint(condition=models.Q(porcentaje__gte=0,porcentaje__lte=100), name="vp_descuento_valido"),
        ]
