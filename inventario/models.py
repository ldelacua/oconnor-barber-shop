from decimal import Decimal, ROUND_HALF_UP, localcontext
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import IntegrityError, models
from django.utils import timezone
from mysql_nuevo.guardias import BloquearFinalizadosQuerySet, mutacion_serializada, guardar_serializado
from ventas.models import SoloLecturaQuerySet

class ComprasQuerySet(BloquearFinalizadosQuerySet):
    criterio_finalizado = {'estado': 'A'}
    mensaje = 'La compra actualizada no puede modificarse ni eliminarse.'

    def update(self, **kwargs):
        if 'estado' in kwargs and kwargs['estado'] not in ('A', 'B'):
            raise IntegrityError('El estado de la compra no es válido.')
        if kwargs.get('estado') == 'A':
            if (set(kwargs) != {'estado', 'actualizada_en', 'actualizada_por'}
                or not kwargs.get('actualizada_en') or not str(kwargs.get('actualizada_por', '')).strip()):
                raise IntegrityError('La actualización requiere fecha y usuario responsable.')
            with mutacion_serializada(self):
                self.comprobar_no_finalizado()
                for compra in self:
                    detalles = list(compra.detalles.all())
                    if not detalles:
                        raise IntegrityError('La compra requiere productos.')
                    for detalle in detalles:
                        entrada = MovimientoInventario.objects.filter(detalle=detalle).first()
                        if entrada is None or entrada.cantidad != detalle.cantidad:
                            raise IntegrityError('Las entradas no coinciden con la compra.')
                    from control_inventario.servicios import validar_fecha
                    validar_fecha(compra.fecha_compra)
                return super().update(**kwargs)
        return super().update(**kwargs)

class DetallesCompraQuerySet(BloquearFinalizadosQuerySet):
    criterio_finalizado = {'compra__estado': 'A'}
    mensaje = 'No se modifican detalles de una compra actualizada.'

    def update(self, **kwargs):
        destino = kwargs.get('compra_id', kwargs.get('compra'))
        if destino is not None:
            raise IntegrityError('No se puede trasladar un detalle de compra.')
        return super().update(**kwargs)


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
    sin_comision = models.BooleanField("No aplica comisión en venta", default=False)
    promocionable = models.BooleanField("Promocionable", default=False)
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
    objects = ComprasQuerySet.as_manager()
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

    @guardar_serializado
    def save(self, *args, **kwargs):
        if self.estado == self.ACTUALIZADA:
            raise ValidationError("Actualiza la compra desde su operación de registro.")
        if self.pk and type(self).objects.filter(pk=self.pk, estado=self.ACTUALIZADA).exists():
            raise ValidationError("La compra actualizada no puede modificarse.")
        self.clean()
        return super().save(*args, **kwargs)

    @guardar_serializado
    def delete(self, *args, **kwargs):
        if type(self).objects.filter(pk=self.pk, estado=self.ACTUALIZADA).exists():
            raise ValidationError("La compra actualizada no puede eliminarse.")
        return super().delete(*args, **kwargs)

class DetalleCompra(models.Model):
    objects = DetallesCompraQuerySet.as_manager()
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

    @guardar_serializado
    def save(self, *args, **kwargs):
        ids = [self.compra_id]
        if self.pk:
            ids += list(type(self).objects.filter(pk=self.pk).values_list("compra_id", flat=True))
        if Compra.objects.filter(pk__in=ids, estado=Compra.ACTUALIZADA).exists():
            raise ValidationError("No se modifican detalles de una compra actualizada.")
        return super().save(*args, **kwargs)

    @guardar_serializado
    def delete(self, *args, **kwargs):
        if Compra.objects.filter(pk=self.compra_id, estado=Compra.ACTUALIZADA).exists():
            raise ValidationError("No se eliminan detalles de una compra actualizada.")
        return super().delete(*args, **kwargs)

class MovimientoInventario(models.Model):
    objects = SoloLecturaQuerySet.as_manager()
    detalle = models.OneToOneField(DetalleCompra, on_delete=models.PROTECT, related_name="entrada")
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    costo_unitario_usd = models.DecimalField(max_digits=24, decimal_places=8)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="inv_entrada_positiva")]

    @guardar_serializado
    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Los movimientos no pueden modificarse.")
        detalle = DetalleCompra.objects.filter(pk=self.detalle_id, compra__estado=Compra.BORRADOR).first()
        if detalle is None or detalle.cantidad != self.cantidad:
            raise IntegrityError("La entrada de inventario no coincide con la compra.")
        return super().save(*args, **kwargs)

    @guardar_serializado
    def delete(self, *args, **kwargs):
        raise ValidationError("Los movimientos no pueden eliminarse.")


class PagoProveedor(models.Model):
    """Abono inmutable aplicado en la moneda de la factura de compra."""
    objects = SoloLecturaQuerySet.as_manager()
    compra = models.ForeignKey(Compra, on_delete=models.PROTECT, related_name='pagos_proveedor')
    fecha = models.DateField()
    tipo_pago = models.PositiveIntegerField()
    nombre_tipo_pago = models.CharField(max_length=100)
    moneda = models.CharField(max_length=3, choices=[('USD', 'USD'), ('BS', 'Bs.')])
    monto = models.DecimalField(max_digits=18, decimal_places=2)
    tasa_cambio = models.DecimalField(max_digits=18, decimal_places=2)
    aplicado_factura = models.DecimalField(max_digits=18, decimal_places=2)
    referencia = models.CharField(max_length=100, blank=True)
    observacion = models.CharField(max_length=1000, blank=True)
    registrado_por = models.CharField(max_length=150)
    creado_en = models.DateTimeField(auto_now_add=True)
    clave = models.UUIDField(unique=True, editable=False)

    class Meta:
        ordering = ['-fecha', '-pk']
        constraints = [
            models.CheckConstraint(condition=models.Q(monto__gt=0), name='pp_monto_positivo'),
            models.CheckConstraint(condition=models.Q(tasa_cambio__gt=0), name='pp_tasa_positiva'),
            models.CheckConstraint(condition=models.Q(aplicado_factura__gt=0), name='pp_aplicado_positivo'),
        ]

    @property
    def equivalente_bs(self):
        from ventas.calculos import dinero
        with localcontext() as contexto:
            contexto.prec = 60
            return dinero(self.monto if self.moneda == 'BS' else self.monto * self.tasa_cambio)

    @guardar_serializado
    def save(self, *args, **kwargs):
        from django.db.models import Sum
        from ventas.calculos import dinero
        from tasas_bcv.models import TasaBCV
        from ventas.pagos_calculos import leer_tipos_pago
        if not self._state.adding or self.pk is not None or kwargs.get('force_update') or kwargs.get('update_fields') is not None:
            raise ValidationError('El pago registrado no se modifica.')
        compra = Compra.objects.select_for_update().get(pk=self.compra_id)
        if compra.estado != Compra.ACTUALIZADA:
            raise ValidationError('Solo se pagan compras actualizadas.')
        if self.fecha < compra.fecha_compra or self.fecha > timezone.localdate():
            raise ValidationError('La fecha del pago debe estar entre la fecha de compra y hoy.')
        tasa = TasaBCV.objects.filter(fecha=self.fecha).first()
        if tasa is None or tasa.tasa_bcv != self.tasa_cambio:
            raise ValidationError('Registra la tasa Bs de la fecha del pago.')
        tipo = leer_tipos_pago().get(self.tipo_pago)
        if not tipo or tipo['moneda'] != self.moneda or tipo['nombre'].upper() != self.nombre_tipo_pago:
            raise ValidationError('La forma de pago no es válida.')
        monto = Decimal(str(self.monto))
        if not monto.is_finite() or monto <= 0 or monto != dinero(monto) or monto >= Decimal('10000000000000000'):
            raise ValidationError('El monto debe ser positivo con hasta dos decimales.')
        with localcontext() as contexto:
            contexto.prec = 60
            equivalente = monto if self.moneda == compra.divisa else monto * self.tasa_cambio if self.moneda == 'USD' else monto / self.tasa_cambio
            equivalente_sin_redondear = equivalente
            equivalente = dinero(equivalente)
        if equivalente <= 0 or equivalente != self.aplicado_factura:
            raise ValidationError('El equivalente en la moneda de la factura no es válido.')
        pagado = PagoProveedor.objects.filter(compra=compra, reverso__isnull=True).aggregate(total=Sum('aplicado_factura'))['total'] or Decimal('0.00')
        saldo = dinero(compra.total - pagado)
        if equivalente_sin_redondear > saldo:
            raise ValidationError(f'El abono supera el saldo pendiente de la factura ({saldo:,.2f} {compra.get_divisa_display()}). Cambia el monto o cancela el pago.')
        if not self.registrado_por.strip():
            raise ValidationError('El pago requiere un usuario responsable.')
        self.referencia = self.referencia.strip().upper()
        self.observacion = self.observacion.strip().upper()
        kwargs['force_insert'] = True
        return super().save(*args, **kwargs)

    @guardar_serializado
    def delete(self, *args, **kwargs):
        raise ValidationError('El pago registrado no se elimina.')


class ReversoPagoProveedor(models.Model):
    objects = SoloLecturaQuerySet.as_manager()
    pago = models.OneToOneField(PagoProveedor, on_delete=models.PROTECT, related_name='reverso')
    fecha = models.DateField(default=timezone.localdate)
    motivo = models.CharField(max_length=1000)
    registrado_por = models.CharField(max_length=150)
    creado_en = models.DateTimeField(auto_now_add=True)

    @guardar_serializado
    def save(self, *args, **kwargs):
        if not self._state.adding or self.pk is not None or kwargs.get('force_update') or kwargs.get('update_fields') is not None:
            raise ValidationError('El reverso registrado no se modifica.')
        pago = PagoProveedor.objects.select_for_update().get(pk=self.pago_id)
        if self.fecha != timezone.localdate() or self.fecha < pago.fecha:
            raise ValidationError('El reverso debe registrarse con la fecha de hoy.')
        if ReversoPagoProveedor.objects.filter(pago=pago).exists():
            raise ValidationError('Este pago ya fue reversado.')
        if not self.motivo.strip() or not self.registrado_por.strip():
            raise ValidationError('Indica el motivo y el usuario responsable del reverso.')
        self.motivo = self.motivo.strip().upper()
        self.full_clean()
        kwargs['force_insert'] = True
        return super().save(*args, **kwargs)

    @guardar_serializado
    def delete(self, *args, **kwargs):
        raise ValidationError('El reverso registrado no se elimina.')
