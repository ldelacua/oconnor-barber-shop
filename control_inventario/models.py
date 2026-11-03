import uuid
from decimal import Decimal,localcontext,ROUND_HALF_UP
from django.db import IntegrityError, models
from django.core.exceptions import ValidationError
from mysql_nuevo.guardias import BloquearFinalizadosQuerySet, mutacion_serializada, guardar_serializado
from ventas.models import SoloLecturaQuerySet

class CierresQuerySet(BloquearFinalizadosQuerySet):
    criterio_finalizado = {'estado': 'C'}
    mensaje = 'El cierre histórico no se modifica ni elimina.'

    def update(self, **kwargs):
        if 'estado' in kwargs and kwargs['estado'] not in ('B', 'C'):
            raise IntegrityError('El estado del cierre no es válido.')
        if {'periodo', 'iniciado_por', 'creado_en'} & set(kwargs) and self.exists():
            raise IntegrityError('No se puede cambiar el período ni el origen de un cierre.')
        if kwargs.get('estado') == 'C':
            if set(kwargs) != {'estado', 'cerrado_por', 'cerrado_en'} or not kwargs.get('cerrado_en') or not str(kwargs.get('cerrado_por', '')).strip():
                raise IntegrityError('El cierre requiere fecha y usuario responsable.')
            with mutacion_serializada(self):
                self.comprobar_no_finalizado()
                for cierre in self:
                    detalles = list(cierre.detalles.all())
                    if not detalles or any(d.fisico is None for d in detalles):
                        raise IntegrityError('Falta completar el conteo físico.')
                    from django.db.models import Sum
                    totales = {}
                    ajustes = (DetalleAjuste.objects.filter(documento__cierre=cierre, documento__sellado=True)
                               .values('producto_id', 'documento__tipo').annotate(total=Sum('cantidad')))
                    for ajuste in ajustes:
                        signo = 1 if ajuste['documento__tipo'] == 'EN' else -1
                        producto_id = ajuste['producto_id']
                        totales[producto_id] = totales.get(producto_id, Decimal('0')) + signo * ajuste['total']
                    if set(totales) - {detalle.producto_id for detalle in detalles}:
                        raise IntegrityError('Hay ajustes de productos que no pertenecen al conteo.')
                    for detalle in detalles:
                        if totales.get(detalle.producto_id, Decimal('0')) != detalle.fisico - detalle.teorico:
                            raise IntegrityError('Los ajustes no coinciden con el conteo físico.')
                return super().update(**kwargs)
        return super().update(**kwargs)

class AjustesQuerySet(BloquearFinalizadosQuerySet):
    criterio_finalizado = {'sellado': True}
    mensaje = 'El documento de inventario registrado no se modifica.'

    def update(self, **kwargs):
        if 'sellado' in kwargs and type(kwargs['sellado']) is not bool:
            raise IntegrityError('El estado del documento debe ser verdadero o falso.')
        if kwargs.get('sellado') is True:
            if set(kwargs) != {'sellado'}:
                raise IntegrityError('El ajuste debe validarse antes de finalizarlo.')
            with mutacion_serializada(self):
                self.comprobar_no_finalizado()
                from inventario.existencias import existencia_producto
                from .servicios import validar_fecha
                from .saldos import fin_mes
                for documento in self:
                    validar_fecha(documento.fecha, documento.cierre_id)
                    if not documento.observacion.strip() or not documento.registrado_por.strip():
                        raise IntegrityError('El ajuste requiere motivo y usuario responsable.')
                    detalles = list(documento.detalles.all())
                    if not detalles:
                        raise IntegrityError('El ajuste requiere productos.')
                    if documento.cierre_id and (documento.cierre.estado != 'B' or documento.fecha != fin_mes(documento.cierre.periodo)):
                        raise IntegrityError('El ajuste no corresponde al cierre abierto.')
                    if documento.tipo == 'SA' and any(d.cantidad > existencia_producto(d.producto_id) for d in detalles):
                        raise IntegrityError('Existencias insuficientes para la salida.')
                return super().update(**kwargs)
        return super().update(**kwargs)

    def delete(self):
        raise ValidationError('El documento no se elimina.')

class DetallesCierreQuerySet(BloquearFinalizadosQuerySet):
    criterio_finalizado = {'cierre__estado': 'C'}
    mensaje = 'El inventario físico de un cierre histórico no se modifica.'

    def update(self, **kwargs):
        if set(kwargs) - {'fisico'}:
            raise IntegrityError('El inventario teórico del conteo no se modifica.')
        return super().update(**kwargs)

    def delete(self):
        raise ValidationError('Los renglones de un cierre no se eliminan individualmente.')

    def bulk_create(self, objs, **kwargs):
        with mutacion_serializada(self):
            ids = {o.cierre_id for o in objs}
            if None in ids or CierreMensual.objects.filter(pk__in=ids, estado='C').exists():
                raise ValidationError('No se agregan renglones a un cierre cerrado.')
            return models.QuerySet.bulk_create(self, objs, **kwargs)


class CierreMensual(models.Model):
    objects = CierresQuerySet.as_manager()
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

    @guardar_serializado
    def save(self,*args,**kwargs):
        if self._state.adding:
            if self.estado != "B" or not self.periodo or self.periodo.day != 1:
                raise ValidationError("El cierre debe iniciarse con un mes válido y conteo abierto.")
            from .saldos import siguiente_mes
            ultimo = type(self).objects.filter(estado='C').order_by('-periodo').first()
            if ultimo and self.periodo != siguiente_mes(ultimo.periodo):
                raise ValidationError("Debes cerrar el mes inmediatamente siguiente al último cierre.")
        else:
            original = type(self).objects.filter(pk=self.pk).first()
            if original and (original.estado == "C" or self.estado != original.estado
                or self.periodo != original.periodo or self.iniciado_por != original.iniciado_por
                or self.creado_en != original.creado_en):
                raise ValidationError("El cierre histórico, su período y origen no se modifican.")
        return super().save(*args,**kwargs)

    @guardar_serializado
    def delete(self,*args,**kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk,estado="C").exists():
            raise ValidationError("El cierre histórico no se elimina.")
        return super().delete(*args,**kwargs)

class DocumentoAjuste(models.Model):
    objects = AjustesQuerySet.as_manager()
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
    @guardar_serializado
    def save(self,*args,**kwargs):
        if self._state.adding and self.sellado:raise ValidationError("El documento debe validarse antes de finalizarlo.")
        if not self._state.adding:raise ValidationError("El documento registrado no se modifica.")
        self.observacion=self.observacion.upper()
        return super().save(*args,**kwargs)
    @guardar_serializado
    def delete(self,*args,**kwargs):raise ValidationError("El documento no se elimina.")

class DetalleAjuste(models.Model):
    objects = SoloLecturaQuerySet.as_manager()
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
    @guardar_serializado
    def save(self,*args,**kwargs):
        if not self._state.adding or DocumentoAjuste.objects.filter(pk=self.documento_id,sellado=True).exists():
            raise ValidationError("El detalle del documento está bloqueado.")
        return super().save(*args,**kwargs)
    @guardar_serializado
    def delete(self,*args,**kwargs):raise ValidationError("El detalle no se elimina.")

class DetalleCierre(models.Model):
    objects = DetallesCierreQuerySet.as_manager()
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
    @guardar_serializado
    def save(self,*args,**kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original:
                campos = ('cierre_id','producto_id','codigo','descripcion','inicial',
                          'compras','ventas','otros','teorico','costo_unitario_usd')
                if any(getattr(self,campo) != getattr(original,campo) for campo in campos):
                    raise ValidationError('El inventario teórico del conteo no se modifica.')
        if CierreMensual.objects.filter(pk=self.cierre_id,estado='C').exists():
            raise ValidationError('El inventario físico de un cierre histórico no se modifica.')
        return super().save(*args,**kwargs)

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
