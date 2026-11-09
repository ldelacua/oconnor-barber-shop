import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import CuentaBancaria, MovimientoBanco, CierreBancario

CAMPOS = {'fecha', 'nro_cuenta', 'nro_transaccion', 'descripcion', 'monto'}


def leer_csv(archivo, cuenta):
    try:
        texto = archivo.read(2_000_001)
        if len(texto) > 2_000_000:
            raise ValidationError('El archivo supera el límite de 2 MB.')
        lector = csv.DictReader(StringIO(texto.decode('utf-8-sig'), newline=''), strict=True)
        if len(lector.fieldnames or []) != len(CAMPOS) or set(lector.fieldnames) != CAMPOS:
            raise ValidationError('Encabezados esperados: fecha, nro_cuenta, nro_transaccion, descripcion, monto.')
        filas = {}
        for fila in lector:
            try:
                if None in fila or None in fila.values():
                    raise ValidationError(f'Fila {lector.line_num}: la cantidad de columnas no coincide con el encabezado.')
                if fila['nro_cuenta'].strip() != cuenta.nro_cuenta:
                    raise ValidationError(f'Fila {lector.line_num}: el número de cuenta del CSV no coincide con la cuenta seleccionada.')

                try:
                    fecha = date.fromisoformat(fila['fecha'].strip())
                except ValueError:
                    raise ValidationError(f'Fila {lector.line_num}: fecha inválida; usa AAAA-MM-DD.')

                referencia = fila['nro_transaccion'].strip().upper()
                descripcion = fila['descripcion'].strip()
                monto = Decimal(fila['monto'].strip())
                if not referencia or len(referencia) > 120 or len(descripcion) > 500:
                    raise ValueError()
                if not monto.is_finite() or not monto or abs(monto) >= 10**16 or monto != monto.quantize(Decimal('0.01')):
                    raise ValueError()
                datos = {'fecha': fecha, 'descripcion': descripcion, 'monto': monto}
                if referencia in filas and filas[referencia] != datos:
                    raise ValueError()
                filas[referencia] = datos
            except (ValueError, InvalidOperation):
                raise ValidationError(f'Fila {lector.line_num}: revisa la referencia, descripción o importe. Usa punto decimal y signo negativo para débitos.')
        if not filas:
            raise ValidationError('El archivo no contiene movimientos.')
        return filas
    except (UnicodeError, csv.Error):
        raise ValidationError('El archivo debe ser CSV válido en UTF-8.')


@transaction.atomic
def importar(cuenta, filas, *, reemplazar=True):
    cuenta = CuentaBancaria.objects.select_for_update().select_related('banco').get(pk=cuenta.pk)
    if not cuenta.activa or not cuenta.banco.activo:
        raise ValidationError('Selecciona una cuenta y un banco activos.')
    meses = {(d['fecha'].year, d['fecha'].month) for d in filas.values()}
    if len(meses) != 1:
        raise ValidationError('Importa un archivo de un solo mes por cuenta.')
    anio, mes = meses.pop()
    if CierreBancario.objects.filter(cuenta=cuenta, fecha_cierre__gte=date(anio, mes, 1)).exists():
        raise ValidationError('El mes está cerrado. No se pueden importar movimientos en ese período.')
    existentes = MovimientoBanco.objects.filter(cuenta=cuenta, fecha__year=anio, fecha__month=mes)
    anteriores = {m.nro_transaccion: m for m in existentes.select_related('partida', 'cargo_registrado')}
    for ref, m in anteriores.items():
        datos = filas.get(ref)
        if not reemplazar:
            if datos is not None and (m.fecha != datos['fecha'] or m.monto != datos['monto']):
                raise ValidationError(f'La transacción {ref} ya existe con otra fecha o importe. Revisa la referencia antes de importar.')
            continue
        iguales = datos and all(getattr(m, campo) == valor for campo, valor in datos.items())
        if not iguales and hasattr(m, 'cargo_registrado'):
            raise ValidationError(f'La transacción {ref} tiene un cargo bancario registrado y no puede cambiarse ni eliminarse.')
        if not iguales and hasattr(m, 'partida'):
            raise ValidationError(f'La transacción {ref} ya está conciliada y no puede cambiarse ni eliminarse.')
    if MovimientoBanco.objects.filter(cuenta=cuenta, nro_transaccion__in=filas).exclude(pk__in=existentes.values('pk')).exists():
        raise ValidationError('Una referencia del archivo ya pertenece a otro mes.')
    nuevos = repetidos = actualizados = retirados = 0
    for ref, m in anteriores.items():
        if reemplazar and ref not in filas:
            m.delete()
            retirados += 1
    for ref, datos in filas.items():
        m = anteriores.get(ref)
        if m is None:
            MovimientoBanco.objects.create(cuenta=cuenta, nro_transaccion=ref, **datos)
            nuevos += 1
        elif not reemplazar or all(getattr(m, campo) == valor for campo, valor in datos.items()):
            repetidos += 1
        else:
            for campo, valor in datos.items():
                setattr(m, campo, valor)
            m.save(update_fields=datos.keys())
            actualizados += 1
    return nuevos, repetidos, actualizados, retirados


@transaction.atomic
def agregar_movimiento(cuenta, fecha, nro_transaccion, descripcion, monto):
    cuenta = CuentaBancaria.objects.select_for_update().select_related('banco').get(pk=cuenta.pk)
    if not cuenta.activa or not cuenta.banco.activo:
        raise ValidationError('Selecciona una cuenta y un banco activos.')
    if CierreBancario.objects.filter(cuenta=cuenta, fecha_cierre__gte=fecha.replace(day=1)).exists():
        raise ValidationError('El mes está cerrado. No se puede agregar el movimiento.')
    if MovimientoBanco.objects.filter(cuenta=cuenta, nro_transaccion__iexact=nro_transaccion).exists():
        raise ValidationError('Esa referencia ya existe en la cuenta seleccionada.')
    return MovimientoBanco.objects.create(cuenta=cuenta, fecha=fecha, nro_transaccion=nro_transaccion,
                                          descripcion=descripcion, monto=monto)


def motivo_bloqueo_movimiento(movimiento, ultimo_cierre):
    if ultimo_cierre is not None and movimiento.fecha <= ultimo_cierre:
        return 'Mes cerrado'
    if hasattr(movimiento, 'cargo_registrado'):
        return 'Cargo bancario registrado'
    if hasattr(movimiento, 'partida'):
        return 'Conciliado'
    return ''


@transaction.atomic
def corregir_movimiento(cuenta_id, movimiento_id, datos=None):
    cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta_id)
    movimiento = MovimientoBanco.objects.filter(cuenta=cuenta, pk=movimiento_id).first()
    if movimiento is None:
        raise ValidationError('El movimiento ya no existe.')
    ultimo = CierreBancario.objects.filter(cuenta=cuenta).values_list('fecha_cierre', flat=True).first()
    motivo = motivo_bloqueo_movimiento(movimiento, ultimo)
    if motivo:
        raise ValidationError(f'No se puede modificar ni eliminar el movimiento: {motivo.lower()}.')
    if datos is None:
        movimiento.delete()
        return
    if ultimo is not None and datos['fecha'] <= ultimo:
        raise ValidationError('La nueva fecha corresponde a un mes cerrado.')
    if MovimientoBanco.objects.filter(cuenta=cuenta, nro_transaccion__iexact=datos['nro_transaccion']).exclude(pk=movimiento.pk).exists():
        raise ValidationError('Esa referencia ya existe en la cuenta seleccionada.')
    for campo in ('fecha', 'nro_transaccion', 'descripcion', 'monto'):
        setattr(movimiento, campo, datos[campo])
    movimiento.save(update_fields=['fecha', 'nro_transaccion', 'descripcion', 'monto'])
