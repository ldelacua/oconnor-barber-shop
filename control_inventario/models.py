import uuid
from decimal import Decimal,localcontext,ROUND_HALF_UP
from django.db import models
from django.core.exceptions import ValidationError

class CierreMensual(models.Model):
    periodo=models.DateField(unique=True)
    estado=models.CharField(max_length=1,choices=[("B","En conteo"),("C","Cerrado")],default="B")
    revision=models.PositiveIntegerField(default=0)
    observacion=models.TextField(blank=True)
    iniciado_por=models.CharField(max_length=150)
    creado_en=models.DateTimeField(auto_now_add=True)
    cerrado_por=models.CharField(max_length=150,blank=True)
    cerrado_en=models.DateTimeField(null=True)

    class Meta:
        ordering=["-periodo"]
        constraints=[models.UniqueConstraint(fields=["estado"],condition=models.Q(estado="B"),name="ci_un_conteo_abierto")]

    def save(self,*args,**kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk,estado="C").exists():
            raise ValidationError("El cierre histórico no se modifica.")
        return super().save(*args,**kwargs)

class DocumentoAjuste(models.Model):
    tipo=models.CharField(max_length=2,choices=[("EN","Entrada (+)"),("SA","Salida (-)")])
    fecha=models.DateField()
    observacion=models.TextField()
    clave=models.UUIDField(default=uuid.uuid4,unique=True)
    sellado=models.BooleanField(default=False)
    registrado_por=models.CharField(max_length=150)
    creado_en=models.DateTimeField(auto_now_add=True)
    cierre=models.ForeignKey(CierreMensual,null=True,blank=True,on_delete=models.PROTECT,related_name="ajustes")

    class Meta:
        ordering=["-fecha","-pk"]
        constraints=[
            models.CheckConstraint(condition=models.Q(tipo__in=["EN","SA"]),name="ci_tipo_valido"),
            models.UniqueConstraint(fields=["cierre","tipo"],name="ci_ajuste_por_tipo_cierre"),
        ]

    def __str__(self):return f"{self.tipo}-{self.pk:06d}"
    def save(self,*args,**kwargs):
        if not self._state.adding:raise ValidationError("El documento registrado no se modifica.")
        self.observacion=self.observacion.upper()
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValidationError("El documento no se elimina.")

class DetalleAjuste(models.Model):
    documento=models.ForeignKey(DocumentoAjuste,on_delete=models.PROTECT,related_name="detalles")
    producto=models.ForeignKey("inventario.Producto",on_delete=models.PROTECT)
    descripcion=models.CharField(max_length=300)
    cantidad=models.DecimalField(max_digits=14,decimal_places=3)
    costo_unitario_usd=models.DecimalField(max_digits=24,decimal_places=8)
    sin_costo_previo=models.BooleanField(default=False)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["documento","producto"],name="ci_producto_unico_ajuste"),
            models.CheckConstraint(condition=models.Q(cantidad__gt=0),name="ci_cantidad_positiva"),
            models.CheckConstraint(condition=models.Q(costo_unitario_usd__gte=0),name="ci_costo_no_negativo"),
        ]
    @property
    def total_usd(self):
        with localcontext() as contexto:
            contexto.prec=60
            return (self.cantidad*self.costo_unitario_usd).quantize(Decimal(".01"),rounding=ROUND_HALF_UP)
    def save(self,*args,**kwargs):
        if not self._state.adding or DocumentoAjuste.objects.filter(pk=self.documento_id,sellado=True).exists():
            raise ValidationError("El detalle del documento está bloqueado.")
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValidationError("El detalle no se elimina.")

class DetalleCierre(models.Model):
    cierre=models.ForeignKey(CierreMensual,on_delete=models.CASCADE,related_name="detalles")
    producto=models.ForeignKey("inventario.Producto",on_delete=models.PROTECT)
    codigo=models.CharField(max_length=50)
    descripcion=models.CharField(max_length=300)
    inicial=models.DecimalField(max_digits=28,decimal_places=3)
    compras=models.DecimalField(max_digits=28,decimal_places=3)
    ventas=models.DecimalField(max_digits=28,decimal_places=3)
    otros=models.DecimalField(max_digits=28,decimal_places=3)
    teorico=models.DecimalField(max_digits=28,decimal_places=3)
    costo_unitario_usd=models.DecimalField(max_digits=24,decimal_places=8)
    fisico=models.DecimalField(max_digits=14,decimal_places=3,null=True)

    class Meta:
        ordering=["codigo","pk"]
        constraints=[
            models.UniqueConstraint(fields=["cierre","producto"],name="ci_producto_por_cierre"),
            models.CheckConstraint(condition=models.Q(fisico__isnull=True)|models.Q(fisico__gte=0),name="ci_fisico_no_negativo"),
        ]
    @property
    def diferencia(self):return None if self.fisico is None else self.fisico-self.teorico

class MovimientoStock(models.Model):
    id=models.CharField(primary_key=True,max_length=80)
    producto=models.ForeignKey("inventario.Producto",db_constraint=False,on_delete=models.DO_NOTHING,related_name="kardex_inventario")
    fecha=models.DateField()
    clase=models.CharField(max_length=12)
    delta=models.DecimalField(max_digits=28,decimal_places=3)
    costo_unitario_usd=models.DecimalField(max_digits=24,decimal_places=8,null=True)
    registrado_en=models.DateTimeField()

    class Meta:
        managed=False
        db_table="ci_movimientos"
