import uuid
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from ventas.models import Inmutable
from ventas.calculos import dinero
from decimal import Decimal


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
    total_propinas_bs = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_bs = models.DecimalField(max_digits=18, decimal_places=2)
    registrado_por = models.CharField(max_length=150)
    creado_en = models.DateTimeField(auto_now_add=True)
    clave = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sellado = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["-fecha_cancelacion", "-id_cancelacion"]
        verbose_name = "Liquidación"
        verbose_name_plural = "Liquidaciones"

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.sellado:
                raise ValidationError("La liquidación debe validarse antes de finalizarla.")
            if (self.tasa_bcv <= 0 or self.total_bs <= 0
                or self.periodo_desde > self.periodo_hasta or self.periodo_hasta > self.fecha_cancelacion):
                raise ValidationError("Datos de liquidación inválidos.")
        return super().save(*args, **kwargs)

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
        from mysql_nuevo.bloqueos import serializar_operacion
        from ventas.models import DocumentoVenta
        with transaction.atomic():
            serializar_operacion()
            liquidacion = Liquidacion.objects.select_for_update().get(pk=self.liquidacion_id)
            if liquidacion.sellado:
                raise ValidationError("No puedes añadir servicios a una liquidación guardada.")
            if self._state.adding:
                venta = self.detalle_venta
                documento = venta.documento
                if (not documento.sellado or venta.barbero_id != liquidacion.prestador_id
                    or not Decimal('0') <= self.porcentaje <= Decimal('100')):
                    raise IntegrityError("Servicio no pendiente o descuento inválido.")
                if documento.tipo_documento == 'FA':
                    if (self.ajuste_de_id is not None
                        or not liquidacion.periodo_desde <= documento.fecha <= liquidacion.periodo_hasta
                        or DocumentoVenta.objects.filter(documento_original=documento).exists()
                        or self.monto_servicio_usd != venta.monto_servicio
                        or self.porcentaje != liquidacion.prestador.porcentaje
                        or self.comision_usd != dinero(self.monto_servicio_usd * self.porcentaje / Decimal('100'))):
                        raise IntegrityError("Servicio no pendiente o descuento inválido.")
                elif documento.tipo_documento == 'RE':
                    previo = self.ajuste_de
                    original = previo.detalle_venta if previo else None
                    if (not previo or not previo.liquidacion.sellado
                        or previo.liquidacion.prestador_id != liquidacion.prestador_id
                        or documento.fecha > liquidacion.fecha_cancelacion
                        or original.documento_id != documento.documento_original_id
                        or original.servicio_id != venta.servicio_id or original.barbero_id != venta.barbero_id
                        or original.cantidad_servicio != venta.cantidad_servicio
                        or self.porcentaje != previo.porcentaje
                        or self.comision_usd != -previo.comision_usd
                        or self.monto_servicio_usd != -previo.monto_servicio_usd
                        or self.monto_servicio_usd != venta.monto_servicio):
                        raise IntegrityError("Servicio no pendiente o descuento inválido.")
                else:
                    raise IntegrityError("Servicio no pendiente o descuento inválido.")
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
        from mysql_nuevo.bloqueos import serializar_operacion
        with transaction.atomic():
            serializar_operacion()
            liquidacion = Liquidacion.objects.select_for_update().get(pk=self.liquidacion_id)
            if liquidacion.sellado:
                raise ValidationError("No puedes añadir pagos a una liquidación guardada.")
            if self._state.adding:
                if (self.tipo_pago <= 0 or self.moneda not in ('USD', 'BS')
                    or self.monto <= 0 or self.equivalente_bs < 0):
                    raise IntegrityError("Pago de liquidación inválido.")
                equivalente = dinero(Decimal(str(self.monto)) * Decimal(str(liquidacion.tasa_bcv))) if self.moneda == 'USD' else self.monto
                if self.equivalente_bs != equivalente:
                    raise IntegrityError("El equivalente del pago no coincide con la tasa.")
            return super().save(*args, **kwargs)


class PeriodoComisionProductos(Inmutable):
    """Instantánea de la escala aplicada al cerrar un período de productos."""
    liquidacion = models.OneToOneField(Liquidacion, on_delete=models.PROTECT, related_name='periodo_productos')
    prestador = models.ForeignKey('barberos.Barbero', on_delete=models.PROTECT, related_name='periodos_comision_productos')
    desde = models.DateField()
    hasta = models.DateField()
    unidades = models.DecimalField(max_digits=18, decimal_places=2)
    base_usd = models.DecimalField(max_digits=18, decimal_places=2)
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2)
    comision_usd = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ['-hasta', '-pk']
        constraints = [
            models.CheckConstraint(condition=models.Q(desde__lte=models.F('hasta')), name='lcp_fechas_validas'),
            models.CheckConstraint(condition=models.Q(unidades__gt=0), name='lcp_unidades_positivas'),
            models.CheckConstraint(condition=models.Q(base_usd__gte=0), name='lcp_base_valida'),
            models.CheckConstraint(condition=models.Q(porcentaje__gte=0, porcentaje__lte=100), name='lcp_tasa_valida'),
        ]

    def save(self, *args, **kwargs):
        from mysql_nuevo.bloqueos import serializar_operacion
        with transaction.atomic():
            serializar_operacion()
            liquidacion = Liquidacion.objects.select_for_update().get(pk=self.liquidacion_id)
            if (liquidacion.sellado or liquidacion.prestador_id != self.prestador_id
                    or liquidacion.periodo_desde != self.desde or liquidacion.periodo_hasta != self.hasta):
                raise IntegrityError('El período debe corresponder al prestador de una liquidación abierta.')
            if self.desde > self.hasta or self.unidades <= 0 or self.base_usd < 0 or not 0 <= self.porcentaje <= 100:
                raise IntegrityError('Período o escala de comisión inválidos.')
            if self.comision_usd != dinero(self.base_usd * self.porcentaje / Decimal('100')):
                raise IntegrityError('La comisión no coincide con la base y el porcentaje.')
            if PeriodoComisionProductos.objects.filter(prestador_id=self.prestador_id,
                    liquidacion__sellado=True, desde__lte=self.hasta, hasta__gte=self.desde).exists():
                raise IntegrityError('El período se cruza con una comisión de productos ya liquidada.')
            return super().save(*args, **kwargs)


class ComisionVentaProducto(Inmutable):
    periodo = models.ForeignKey(PeriodoComisionProductos, on_delete=models.PROTECT, related_name='ventas')
    venta = models.OneToOneField('ventas_productos.DocumentoProducto', on_delete=models.PROTECT, related_name='comision_productos')
    unidades = models.DecimalField(max_digits=18, decimal_places=2)
    base_usd = models.DecimalField(max_digits=18, decimal_places=2)
    comision_usd = models.DecimalField(max_digits=18, decimal_places=2)

    def save(self, *args, **kwargs):
        from mysql_nuevo.bloqueos import serializar_operacion
        with transaction.atomic():
            serializar_operacion()
            periodo = PeriodoComisionProductos.objects.select_related('liquidacion').get(pk=self.periodo_id)
            venta = self.venta
            unidades, base = venta.importes_comision()
            if (periodo.liquidacion.sellado or not venta.sellado or venta.tipo != 'VP'
                    or venta.prestador_id != periodo.prestador_id or not periodo.desde <= venta.fecha <= periodo.hasta
                    or unidades <= 0 or unidades != self.unidades or base != self.base_usd
                    or self.comision_usd < 0):
                raise IntegrityError('La venta no corresponde al período de comisión.')
            from ventas_productos.models import DocumentoProducto
            if DocumentoProducto.objects.filter(documento_original_id=venta.pk, sellado=True,
                    fecha__lte=periodo.liquidacion.fecha_cancelacion).exists():
                raise IntegrityError('No se liquida una venta de productos que ya fue reversada.')
            anteriores = list(ComisionVentaProducto.objects.filter(periodo=periodo).select_related('venta'))
            if any((v.venta.fecha, v.venta_id) >= (venta.fecha, venta.pk) for v in anteriores):
                raise IntegrityError('Las ventas deben registrarse en orden cronológico.')
            base_previa = sum((v.base_usd for v in anteriores), Decimal('0.00'))
            esperado = (dinero((base_previa + self.base_usd) * periodo.porcentaje / Decimal('100'))
                        - dinero(base_previa * periodo.porcentaje / Decimal('100')))
            if self.comision_usd != esperado:
                raise IntegrityError('La comisión de la venta no coincide con la escala del período.')
            return super().save(*args, **kwargs)


class ReintegroComisionProducto(Inmutable):
    liquidacion = models.ForeignKey(Liquidacion, on_delete=models.PROTECT, related_name='reintegros_productos')
    comision = models.OneToOneField(ComisionVentaProducto, on_delete=models.PROTECT, related_name='reintegro')
    reverso = models.OneToOneField('ventas_productos.DocumentoProducto', on_delete=models.PROTECT, related_name='reintegro_comision')
    monto_usd = models.DecimalField(max_digits=18, decimal_places=2)

    def save(self, *args, **kwargs):
        from mysql_nuevo.bloqueos import serializar_operacion
        with transaction.atomic():
            serializar_operacion()
            liquidacion = Liquidacion.objects.select_for_update().get(pk=self.liquidacion_id)
            comision = self.comision
            reverso = self.reverso
            if (liquidacion.sellado or not comision.periodo.liquidacion.sellado
                    or comision.periodo.prestador_id != liquidacion.prestador_id
                    or not reverso.sellado or reverso.tipo != 'RP'
                    or reverso.documento_original_id != comision.venta_id
                    or reverso.fecha > liquidacion.fecha_cancelacion
                    or self.monto_usd != -comision.comision_usd):
                raise IntegrityError('El descuento de comisión no corresponde a un reverso pagado.')
            return super().save(*args, **kwargs)
