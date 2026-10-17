
import importlib
from django.db import migrations, models


def sello_anterior():
    previo = importlib.import_module("ventas.migrations.0003_barbero_detalle")
    return next(s for s in previo.sentencias_nuevas() if "CREATE TRIGGER ventas_doc_sellar " in s)


PAGO_SQL = [
"""CREATE TRIGGER ventas_pago_no_update BEFORE UPDATE ON ventas_pagoventa
BEGIN SELECT RAISE(ABORT, 'El pago no se puede modificar'); END""",
"""CREATE TRIGGER ventas_pago_no_delete BEFORE DELETE ON ventas_pagoventa
BEGIN SELECT RAISE(ABORT, 'El pago no se puede eliminar'); END""",
"""CREATE TRIGGER ventas_pago_validar BEFORE INSERT ON ventas_pagoventa
WHEN NEW.tipo_pago <= 0 OR NEW.moneda NOT IN ('USD','BS') OR NEW.nombre_tipo_pago = ''
OR NOT EXISTS(
 SELECT 1 FROM ventas_documentoventa d WHERE d.id_documento=NEW.documento_id AND d.sellado=0
 AND ((d.tipo_documento='FA' AND NEW.monto>0 AND NEW.equivalente_bs>=0 AND NEW.pago_original_id IS NULL)
 OR (d.tipo_documento='RE' AND NEW.monto<0 AND NEW.equivalente_bs<=0 AND EXISTS(
  SELECT 1 FROM ventas_pagoventa p WHERE p.id=NEW.pago_original_id
  AND p.documento_id=d.documento_original_id AND p.tipo_pago=NEW.tipo_pago
  AND p.moneda=NEW.moneda AND p.nombre_tipo_pago=NEW.nombre_tipo_pago
  AND p.fecha=NEW.fecha AND p.referencia=NEW.referencia AND p.observacion=NEW.observacion
  AND p.monto=-NEW.monto AND p.equivalente_bs=-NEW.equivalente_bs
  AND p.ajuste_redondeo_bs=-NEW.ajuste_redondeo_bs
 )))
 AND ABS(NEW.equivalente_bs - CASE WHEN NEW.moneda='BS' THEN NEW.monto ELSE ROUND(NEW.monto*d.tasa_bcv,2) END)<0.005
)
BEGIN SELECT RAISE(ABORT, 'Pago invalido o documento ya guardado'); END"""
]

CONDICION_PAGOS = """
 OR (NEW.tipo_documento='FA' AND NOT EXISTS(SELECT 1 FROM ventas_pagoventa WHERE documento_id=NEW.id_documento))
 OR (NEW.tipo_documento='RE' AND
  (SELECT COUNT(*) FROM ventas_pagoventa WHERE documento_id=NEW.id_documento) !=
  (SELECT COUNT(*) FROM ventas_pagoventa WHERE documento_id=NEW.documento_original_id))
 OR (EXISTS(SELECT 1 FROM ventas_pagoventa WHERE documento_id=NEW.id_documento) AND
  ABS(NEW.total_bs - (SELECT SUM(equivalente_bs+ajuste_redondeo_bs) FROM ventas_pagoventa WHERE documento_id=NEW.id_documento))>0.005)
 OR (NEW.tipo_documento='FA' AND NOT EXISTS(SELECT 1 FROM ventas_pagoventa WHERE documento_id=NEW.id_documento AND moneda='BS')
  AND ABS(ROUND(NEW.total_bs*1.0/NEW.tasa_bcv,2) - (SELECT COALESCE(SUM(monto),0) FROM ventas_pagoventa WHERE documento_id=NEW.id_documento AND moneda='USD'))>0.005)
 OR (NEW.tipo_documento='FA' AND EXISTS(SELECT 1 FROM ventas_pagoventa WHERE documento_id=NEW.id_documento AND moneda='BS')
  AND ABS(NEW.total_bs - ROUND((SELECT COALESCE(SUM(monto),0) FROM ventas_pagoventa WHERE documento_id=NEW.id_documento AND moneda='USD')*NEW.tasa_bcv,2)
   - (SELECT COALESCE(SUM(monto),0) FROM ventas_pagoventa WHERE documento_id=NEW.id_documento AND moneda='BS'))>0.005)
"""


def instalar(apps,schema_editor):
    if schema_editor.connection.vendor!='sqlite':
        raise RuntimeError("La protección de pagos requiere SQLite.")
    schema_editor.execute('DROP TRIGGER IF EXISTS ventas_doc_sellar')
    anterior=sello_anterior()
    nuevo=anterior.replace('\n)\nBEGIN',CONDICION_PAGOS+'\n)\nBEGIN')
    if nuevo==anterior:
        raise RuntimeError("No se encontró la protección anterior de documentos.")
    schema_editor.execute(nuevo)
    for sentencia in PAGO_SQL:
        schema_editor.execute(sentencia)


def retirar(apps,schema_editor):
    for nombre in ['ventas_pago_no_update','ventas_pago_no_delete','ventas_pago_validar','ventas_doc_sellar']:
        schema_editor.execute(f'DROP TRIGGER IF EXISTS {nombre}')
    schema_editor.execute(sello_anterior())

class Migration(migrations.Migration):
    dependencies=[("ventas","0003_barbero_detalle")]
    operations=[
        migrations.CreateModel(name="PagoVenta",fields=[
('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
('documento', models.ForeignKey("ventas.documentoventa", on_delete=models.PROTECT, related_name="pagos")),
('tipo_pago', models.PositiveIntegerField()),
('nombre_tipo_pago', models.CharField(max_length=100)),
('moneda', models.CharField(max_length=3, choices=[("USD", "USD"), ("BS", "Bs.")])),
('fecha', models.DateField()),
('referencia', models.CharField(max_length=100, blank=True)),
('observacion', models.TextField(blank=True)),
('monto', models.DecimalField(max_digits=18, decimal_places=2)),
('equivalente_bs', models.DecimalField(max_digits=18, decimal_places=2)),
('ajuste_redondeo_bs', models.DecimalField(max_digits=18, decimal_places=2, default=0)),
('pago_original', models.OneToOneField("ventas.pagoventa", null=True, blank=True, on_delete=models.PROTECT, related_name="reverso"))
        ],options={"ordering":["pk"],"verbose_name":"Pago de venta","verbose_name_plural":"Pagos de venta"}),
        migrations.RunPython(instalar,retirar),
    ]
