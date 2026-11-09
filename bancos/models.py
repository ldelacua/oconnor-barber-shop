from django.db import models


class Banco(models.Model):
    id_banco = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=120, unique=True)
    formato_estado = models.JSONField(default=dict, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class CuentaBancaria(models.Model):
    id_cuenta = models.BigAutoField(primary_key=True)
    banco = models.ForeignKey(Banco, on_delete=models.PROTECT, related_name='cuentas')
    nro_cuenta = models.CharField(max_length=60, verbose_name='Número de cuenta')
    moneda = models.CharField(max_length=3, choices=[('BS', 'Bs.'), ('USD', 'USD')])
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['banco__nombre', 'nro_cuenta']
        constraints = [
            models.UniqueConstraint(fields=['banco', 'nro_cuenta'], name='bancos_cuenta_unica'),
            models.CheckConstraint(condition=models.Q(moneda__in=['BS', 'USD']), name='bancos_moneda_valida'),
        ]

    def __str__(self):
        return f'{self.banco} · {self.nro_cuenta} ({self.get_moneda_display()})'


class MovimientoBanco(models.Model):
    cuenta = models.ForeignKey(CuentaBancaria, on_delete=models.PROTECT)
    fecha = models.DateField()
    nro_transaccion = models.CharField(max_length=120)
    descripcion = models.CharField(max_length=500)
    monto = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ['-fecha', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['cuenta', 'nro_transaccion'], name='bancos_transaccion_unica'),
            models.CheckConstraint(condition=~models.Q(monto=0), name='bancos_movimiento_no_cero'),
        ]


class MovimientoInterno(models.Model):
    cuenta = models.ForeignKey(CuentaBancaria, on_delete=models.PROTECT)
    origen = models.CharField(max_length=24)
    pago_id = models.PositiveBigIntegerField()
    fecha = models.DateField()
    referencia = models.CharField(max_length=100, blank=True)
    monto = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['origen', 'pago_id'], name='bancos_pago_vinculado_unico')]


class Conciliacion(models.Model):
    metodo = models.CharField(max_length=10, default='', blank=True, choices=[
        ('AUTO', 'Automática'), ('MONTO', 'Por importe confirmado'), ('MANUAL', 'Manual'),
    ])
    cuenta = models.ForeignKey(CuentaBancaria, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.CharField(max_length=150)
    monto = models.DecimalField(max_digits=18, decimal_places=2)


class ReversoConciliacion(models.Model):
    conciliacion = models.OneToOneField(Conciliacion, on_delete=models.PROTECT, related_name='reverso')
    usuario = models.CharField(max_length=150)
    fecha = models.DateTimeField(auto_now_add=True)
    movimientos = models.JSONField()


class PartidaBanco(models.Model):
    conciliacion = models.ForeignKey(Conciliacion, on_delete=models.PROTECT, related_name='partidas_banco')
    movimiento = models.OneToOneField(MovimientoBanco, on_delete=models.PROTECT, related_name='partida')


class PartidaInterna(models.Model):
    conciliacion = models.ForeignKey(Conciliacion, on_delete=models.PROTECT, related_name='partidas_internas')
    movimiento = models.OneToOneField(MovimientoInterno, on_delete=models.PROTECT, related_name='partida')


class CierreBancario(models.Model):
    cuenta = models.ForeignKey(CuentaBancaria, on_delete=models.PROTECT)
    fecha_cierre = models.DateField()
    saldo = models.DecimalField(max_digits=18, decimal_places=2)
    resumen = models.JSONField()
    usuario = models.CharField(max_length=150)
    registrado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_cierre']
        constraints = [models.UniqueConstraint(fields=['cuenta', 'fecha_cierre'], name='bancos_cierre_unico')]


class CargoBancario(models.Model):
    movimiento_banco = models.OneToOneField(MovimientoBanco, on_delete=models.PROTECT, related_name='cargo_registrado')
    movimiento_interno = models.OneToOneField(MovimientoInterno, on_delete=models.PROTECT, related_name='cargo_bancario')
    concepto = models.CharField(max_length=200)
    usuario = models.CharField(max_length=150)
    registrado_en = models.DateTimeField(auto_now_add=True)


class AnulacionCargoBancario(models.Model):
    cuenta = models.ForeignKey(CuentaBancaria, on_delete=models.PROTECT)
    datos_cargo = models.JSONField()
    motivo = models.CharField(max_length=250)
    usuario = models.CharField(max_length=150)
    registrado_en = models.DateTimeField(auto_now_add=True)
