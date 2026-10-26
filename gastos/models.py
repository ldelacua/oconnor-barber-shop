from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models.functions import Lower, Trim
from django.utils import timezone


class GrupoGasto(models.Model):
    id_grupo_gasto = models.BigAutoField(primary_key=True)
    descripcion = models.CharField(max_length=150, verbose_name="Descripción")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["descripcion"]
        verbose_name = "Grupo de gastos"
        verbose_name_plural = "Grupos de gastos"

    def __str__(self):
        return self.descripcion


class TipoGasto(models.Model):
    id_gasto = models.BigAutoField(primary_key=True)
    descripcion = models.CharField(max_length=150, verbose_name="Descripción")
    grupo = models.ForeignKey(GrupoGasto, on_delete=models.PROTECT, related_name="tipos", db_column="id_grupo_gasto")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["descripcion"]
        verbose_name = "Tipo de gasto"
        verbose_name_plural = "Tipos de gasto"

    def __str__(self):
        return self.descripcion


class Proveedor(models.Model):
    id_proveedor = models.BigAutoField(primary_key=True)
    rif = models.CharField(max_length=30, unique=True, verbose_name="RIF")
    descripcion = models.CharField(max_length=200, verbose_name="Descripción / razón social")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["descripcion"]
        verbose_name = "Proveedor"
        verbose_name_plural = "Proveedores"
        constraints = [models.UniqueConstraint(Lower(Trim("rif")), name="proveedor_rif_unico_ci")]

    def __str__(self):
        return f"{self.rif} · {self.descripcion}"


class RegistroGasto(models.Model):
    id_registro_gasto = models.BigAutoField(primary_key=True)
    gasto = models.ForeignKey(TipoGasto, on_delete=models.PROTECT, related_name="registros", db_column="id_gasto", verbose_name="Tipo de gasto")
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="gastos", db_column="id_proveedor")
    numero_factura = models.CharField(max_length=60, verbose_name="Número de factura")
    numero_control = models.CharField(max_length=60, blank=True, verbose_name="Número de control")
    fecha_gasto = models.DateField(default=timezone.localdate, verbose_name="Fecha del gasto")
    moneda = models.CharField(max_length=3, choices=[("BS", "Bs."), ("USD", "USD")], default="BS")
    monto_gasto = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))], help_text="Monto antes del impuesto, en la moneda seleccionada.")
    monto_impuesto = models.DecimalField(max_digits=18, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0.00"))], help_text="Introduce el impuesto manualmente en la misma moneda. No se calcula automáticamente.")
    porcentaje_impuesto = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))], verbose_name="Porcentaje de impuesto (%)", help_text="Informativo. No calcula ni modifica el monto del impuesto.")

    class Meta:
        ordering = ["-fecha_gasto", "-id_registro_gasto"]
        verbose_name = "Registro de gasto"
        verbose_name_plural = "Registros de gastos"
        constraints = [
            models.UniqueConstraint(Lower(Trim("numero_factura")), "proveedor", name="gasto_factura_proveedor_unica"),
            models.CheckConstraint(condition=models.Q(monto_gasto__gt=0), name="gasto_base_positiva"),
            models.CheckConstraint(condition=models.Q(monto_impuesto__gte=0), name="gasto_impuesto_no_negativo"),
            models.CheckConstraint(condition=models.Q(porcentaje_impuesto__gte=0, porcentaje_impuesto__lte=100), name="gasto_porcentaje_valido"),
            models.CheckConstraint(condition=models.Q(moneda__in=["USD", "BS"]), name="gasto_moneda_valida"),
        ]

    @property
    def total(self):
        return self.monto_gasto + self.monto_impuesto

    def __str__(self):
        return f"Gasto {self.pk} · {self.numero_factura}"


class Producto(models.Model):
    id_producto = models.BigAutoField(primary_key=True)
    descripcion = models.CharField(max_length=150, verbose_name="Descripción")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["descripcion", "id_producto"]
        verbose_name = "Producto"
        verbose_name_plural = "Productos"

    def __str__(self):
        return self.descripcion
    unidad_medida = models.CharField(
        max_length=10,
        choices=[
            ("kg", "Kg"),
            ("gr", "gr"),
            ("metro", "Metro"),
            ("unidad", "Unidad"),
        ],
        default="unidad",
        verbose_name="Unidad de medida",
    )

class DetalleRegistroGasto(models.Model):
    id_detalle_registro = models.BigAutoField(primary_key=True)
    registro_gasto = models.ForeignKey(RegistroGasto, on_delete=models.CASCADE,
        related_name="detalles", db_column="id_registro_gasto")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT,
        related_name="detalles_gasto", db_column="id_producto")
    cantidad = models.DecimalField(max_digits=12, decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))])

    class Meta:
        ordering = ["id_detalle_registro"]
        constraints = [models.CheckConstraint(condition=models.Q(cantidad__gt=0),
            name="detalle_gasto_cantidad_positiva")]

    
    def __str__(self):
        return f"{self.descripcion} ({self.get_unidad_medida_display()})"