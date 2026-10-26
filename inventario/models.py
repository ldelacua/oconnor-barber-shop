from decimal import Decimal, ROUND_HALF_UP, localcontext
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

CENTAVO = Decimal("0.01")
def dinero(valor):
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)

def mayusculas(instancia, campos):
    for campo in campos:
        valor = getattr(instancia, campo)
        if isinstance(valor, str):
            setattr(instancia, campo, valor.upper())

class UnidadMedida(models.Model):
    codigo = models.CharField("Unidad", max_length=20, unique=True)
    nombre = models.CharField("Descripción", max_length=80)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["codigo"]
        verbose_name = "Unidad de medida"
        verbose_name_plural = "Unidades de medida"

    def clean(self):
        mayusculas(self, ["codigo", "nombre"])
        self.codigo = self.codigo.strip()

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

class Producto(models.Model):
    id_producto = models.BigAutoField(primary_key=True)
    codigo_producto = models.CharField("Código", max_length=50, unique=True)
    volumen = models.DecimalField("Volumen", max_digits=14, decimal_places=3, null=True, blank=True,
                                  validators=[MinValueValidator(Decimal("0.001"))])
    unidad_medida = models.ForeignKey(UnidadMedida, on_delete=models.PROTECT, null=True, blank=True,
                                     verbose_name="Unidad de medida")
    # Columna histórica: se conserva sin utilizarla en la captura nueva.
    modelo = models.CharField("Modelo del producto", max_length=100, blank=True)
    nombre_producto = models.CharField("Nombre", max_length=150)
    observacion = models.TextField("Observación", blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["codigo_producto"]

    def clean(self):
        mayusculas(self, ["codigo_producto", "nombre_producto", "modelo", "observacion"])
        self.codigo_producto = self.codigo_producto.strip().upper()

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        volumen = format(dinero(self.volumen), ",.2f") if self.volumen is not None else ""
        unidad = self.unidad_medida.codigo if self.unidad_medida_id else ""
        return " · ".join(p for p in [self.codigo_producto, self.nombre_producto, f"{volumen} {unidad}".strip()] if p)

class Proveedor(models.Model):
    id_proveedor = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=150)
    direccion = models.CharField("Dirección", max_length=250, blank=True)
    rif = models.CharField("RIF", max_length=25, unique=True)
    telefono = models.CharField("Teléfono", max_length=25, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def clean(self):
        mayusculas(self, ["nombre", "direccion", "rif", "telefono"])
        self.rif = self.rif.strip().upper()

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nombre} ({self.rif})"

class Compra(models.Model):
    BORRADOR, ACTUALIZADA = "B", "A"
    id_compra = models.BigAutoField(primary_key=True)
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT)
    numero_factura = models.CharField("Número de factura", max_length=60)
    numero_control = models.CharField("Número de control", max_length=60, blank=True)
    fecha_compra = models.DateField("Fecha de compra", default=timezone.localdate)
    observacion = models.TextField("Observación", blank=True)
    divisa = models.CharField("Divisa", max_length=3, choices=[("USD", "USD"), ("BS", "Bs")], default="USD")
    tasa_cambio = models.DecimalField("Tasa de cambio (Bs por 1 USD)", max_digits=18, decimal_places=6,
                                     validators=[MinValueValidator(Decimal("0.000001"))])
    estado = models.CharField(max_length=1, choices=[("B", "Borrador"), ("A", "Actualizada")], default="B", editable=False)
    revision = models.PositiveIntegerField(default=0, editable=False)
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(null=True, editable=False)
    registrada_por = models.CharField(max_length=150, editable=False)
    actualizada_por = models.CharField(max_length=150, blank=True, editable=False)

    class Meta:
        ordering = ["-fecha_compra", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["proveedor", "numero_factura"], name="inv_factura_por_proveedor"),
            models.CheckConstraint(condition=models.Q(tasa_cambio__gt=0), name="inv_tasa_positiva"),
            models.CheckConstraint(condition=models.Q(divisa__in=["USD", "BS"]), name="inv_divisa_valida"),
            models.CheckConstraint(condition=models.Q(estado__in=["B", "A"]), name="inv_estado_valido"),
        ]

    def clean(self):
        mayusculas(self, ["numero_factura", "numero_control", "observacion"])
        self.numero_factura = self.numero_factura.strip().upper()

    @property
    def subtotal(self):
        return sum((d.subtotal for d in self.detalles.all()), Decimal("0.00"))

    @property
    def impuesto(self):
        return sum((d.monto_impuesto for d in self.detalles.all()), Decimal("0.00"))

    @property
    def total(self):
        return self.subtotal + self.impuesto

    @property
    def total_usd(self):
        with localcontext() as contexto:
            contexto.prec = 60
            return dinero(self.total if self.divisa == "USD" else self.total / self.tasa_cambio)

    @property
    def total_bs(self):
        with localcontext() as contexto:
            contexto.prec = 60
            return dinero(self.total if self.divisa == "BS" else self.total * self.tasa_cambio)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk, estado=self.ACTUALIZADA).exists():
            raise ValidationError("La compra actualizada no puede modificarse.")
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if type(self).objects.filter(pk=self.pk, estado=self.ACTUALIZADA).exists():
            raise ValidationError("La compra actualizada no puede eliminarse.")
        return super().delete(*args, **kwargs)

class DetalleCompra(models.Model):
    compra = models.ForeignKey(Compra, on_delete=models.CASCADE, related_name="detalles")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    precio_unitario = models.DecimalField("Precio Unitario", max_digits=18, decimal_places=4,
                                         validators=[MinValueValidator(Decimal("0.0001"))])
    tasa_impuesto = models.DecimalField("Impuesto (%)", max_digits=5, decimal_places=2, default=0,
                                        validators=[MinValueValidator(0), MaxValueValidator(100)])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["compra", "producto"], name="inv_producto_por_compra"),
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="inv_cantidad_positiva"),
            models.CheckConstraint(condition=models.Q(precio_unitario__gt=0), name="inv_precio_positivo"),
            models.CheckConstraint(condition=models.Q(tasa_impuesto__gte=0, tasa_impuesto__lte=100), name="inv_impuesto_valido"),
        ]

    @property
    def subtotal(self):
        with localcontext() as contexto:
            contexto.prec = 60
            return dinero(self.cantidad * self.precio_unitario)

    @property
    def monto_impuesto(self):
        with localcontext() as contexto:
            contexto.prec = 60
            return dinero(self.subtotal * self.tasa_impuesto / Decimal("100"))

    @property
    def total(self):
        return self.subtotal + self.monto_impuesto

    def save(self, *args, **kwargs):
        ids = [self.compra_id]
        if self.pk:
            ids += list(type(self).objects.filter(pk=self.pk).values_list("compra_id", flat=True))
        if Compra.objects.filter(pk__in=ids, estado=Compra.ACTUALIZADA).exists():
            raise ValidationError("No se modifican detalles de una compra actualizada.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if Compra.objects.filter(pk=self.compra_id, estado=Compra.ACTUALIZADA).exists():
            raise ValidationError("No se eliminan detalles de una compra actualizada.")
        return super().delete(*args, **kwargs)

class MovimientoInventario(models.Model):
    detalle = models.OneToOneField(DetalleCompra, on_delete=models.PROTECT, related_name="entrada")
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    costo_unitario_usd = models.DecimalField(max_digits=24, decimal_places=8)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="inv_entrada_positiva")]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Los movimientos no pueden modificarse.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los movimientos no pueden eliminarse.")
