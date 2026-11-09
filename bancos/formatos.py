import csv
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from django import forms
from django.core.exceptions import ValidationError

CAMPOS = {
    'nro_cuenta': 'Número de cuenta',
    'nro_transaccion': 'Referencia',
    'fecha': 'Fecha',
    'monto': 'Monto',
    'descripcion': 'Descripción (opcional)',
}
REQUERIDOS = set(CAMPOS) - {'descripcion'}
SEPARADORES = {',': ',', ';': ';', '|': '|', 'tab': '\t'}
FECHAS = (
    ('%Y-%m-%d', 'AAAA-MM-DD'), ('%d/%m/%Y', 'DD/MM/AAAA'),
    ('%d-%m-%Y', 'DD-MM-AAAA'), ('%Y%m%d', 'AAAAMMDD'),
    ('%d%m%Y', 'DDMMAAAA'), ('%m/%d/%Y', 'MM/DD/AAAA'),
    ('%Y/%m/%d', 'AAAA/MM/DD'), ('%d/%m/%y', 'DD/MM/AA'),
)


class FormatoEstadoForm(forms.Form):
    modo = forms.ChoiceField(label='Tipo de archivo', choices=[
        ('', 'Selecciona un tipo de archivo'), ('estandar', 'CSV estándar del sistema'), ('separado', 'Campos separados'),
        ('fijo', 'Texto de ancho fijo'),
    ])
    separador = forms.ChoiceField(required=False, choices=[(v, 'Tabulación' if v == 'tab' else v)
                                                             for v in SEPARADORES])
    fecha = forms.ChoiceField(label='Formato de fecha', required=False, choices=FECHAS)
    decimal = forms.ChoiceField(label='Separador decimal', required=False, choices=[('.', 'Punto'), (',', 'Coma')])
    codificacion = forms.ChoiceField(label='Codificación', required=False, choices=[
        ('utf-8-sig', 'UTF-8'), ('cp1252', 'Windows-1252'),
    ])
    omitir = forms.IntegerField(label='Filas iniciales a omitir', min_value=0, max_value=1000, required=False,
                               help_text='Por ejemplo, 1 si el archivo tiene un encabezado.')
    campos = forms.CharField(label='Ubicación de los campos', required=False, max_length=4096,
                            widget=forms.Textarea(attrs={'rows': 6, 'class': 'form-control'}))

    @classmethod
    def inicial(cls, formato):
        inicial = {'modo': '', 'separador': ';', 'fecha': '%d/%m/%Y',
                   'decimal': '.', 'codificacion': 'utf-8-sig', 'omitir': 0}
        if formato:
            inicial.update(formato)
            inicial['campos'] = '\n'.join(
                f'{campo}: {pos}' if isinstance(pos, int) else f'{campo}: {pos[0]}-{pos[1]}'
                for campo, pos in formato['campos'].items())
        return inicial

    def clean(self):
        datos = super().clean()
        modo = datos.get('modo')
        self.formato = {}
        if modo == 'estandar' and datos.get('campos'):
            self.add_error('modo', 'Selecciona Campos separados o Texto de ancho fijo para guardar las posiciones. Para volver al CSV estándar, borra primero las posiciones.')
        if modo not in {'separado', 'fijo'}:
            return datos
        for campo in ('fecha', 'decimal', 'codificacion') + (('separador',) if modo == 'separado' else ()):
            if not datos.get(campo) and campo not in self.errors:
                self.add_error(campo, 'Selecciona una opción.')
        campos = {}
        usados = []
        for numero, linea in enumerate(datos.get('campos', '').splitlines(), 1):
            if not linea.strip():
                continue
            nombre, _, ubicacion = linea.partition(':')
            nombre = nombre.strip().lower()
            patron = r'([0-9]{1,5})' if modo == 'separado' else r'([0-9]{1,5})\s*-\s*([0-9]{1,5})'
            coincidencia = re.fullmatch(patron, ubicacion.strip())
            if nombre not in CAMPOS or nombre in campos or not coincidencia:
                self.add_error('campos', f'Línea {numero}: campo desconocido, repetido o posición inválida.')
                continue
            inicio = int(coincidencia[1])
            fin = int(coincidencia[2]) if modo == 'fijo' else inicio
            if not 1 <= inicio <= fin or any(inicio <= b and a <= fin for a, b in usados):
                self.add_error('campos', f'Línea {numero}: usa posiciones desde 1 y sin superponer campos.')
                continue
            usados.append((inicio, fin))
            campos[nombre] = [inicio, fin] if modo == 'fijo' else inicio
        faltan = REQUERIDOS - campos.keys()
        if faltan:
            self.add_error('campos', 'Faltan: ' + ', '.join(sorted(faltan)) + '.')
        if not self.errors:
            self.formato = {k: datos[k] for k in ('modo', 'fecha', 'decimal', 'codificacion', 'separador')}
            self.formato.update(campos=campos, omitir=datos.get('omitir') or 0)
        return datos


def leer_personalizado(archivo, cuenta, formato):
    try:
        bruto = archivo.read(2_000_001)
        if len(bruto) > 2_000_000:
            raise ValidationError('El archivo supera el límite de 2 MB.')
        texto = bruto.decode(formato['codificacion'])
        lineas = StringIO(texto, newline='')
        omitidas = formato['omitir']
        for _ in range(omitidas):
            next(lineas, None)
        separado = formato['modo'] == 'separado'
        lector = csv.reader(lineas, delimiter=SEPARADORES[formato['separador']], strict=True) if separado else lineas
        resultado = {}
        decimal = formato['decimal']
        patron_monto = r'[+-]?[0-9]+(?:' + re.escape(decimal) + r'[0-9]{1,2})?'
        for numero, fila in enumerate(lector, omitidas + 1):
            if separado:
                numero = omitidas + lector.line_num
                if not fila or all(not valor.strip() for valor in fila):
                    continue
            else:
                fila = fila.rstrip('\r\n')
                if not fila.strip():
                    continue
            valores = {}
            for campo, posicion in formato['campos'].items():
                fin = posicion if separado else posicion[1]
                if len(fila) < fin:
                    raise ValidationError(f'Fila {numero}: el archivo no llega hasta la posición configurada para {CAMPOS[campo]}.')
                valores[campo] = (fila[posicion - 1] if separado else fila[posicion[0] - 1:fin]).strip()
            if valores['nro_cuenta'] != cuenta.nro_cuenta:
                raise ValidationError(f'Fila {numero}: el número de cuenta no coincide con la cuenta seleccionada.')
            try:
                fecha = datetime.strptime(valores['fecha'], formato['fecha']).date()
                if fecha.strftime(formato['fecha']) != valores['fecha']:
                    raise ValueError()
            except ValueError:
                raise ValidationError(f'Fila {numero}: la fecha no coincide con el formato del banco.')
            referencia = valores['nro_transaccion'].upper()
            descripcion = valores.get('descripcion', '')
            importe = valores['monto']
            if not referencia or len(referencia) > 120 or len(descripcion) > 500:
                raise ValidationError(f'Fila {numero}: revisa la referencia o la descripción.')
            if not re.fullmatch(patron_monto, importe):
                raise ValidationError(f'Fila {numero}: monto inválido. Usa el separador decimal configurado, sin separador de miles.')
            try:
                monto = Decimal(importe.replace(decimal, '.'))
            except InvalidOperation:
                raise ValidationError(f'Fila {numero}: monto inválido.')
            if not monto or abs(monto) >= 10**16:
                raise ValidationError(f'Fila {numero}: el monto debe ser distinto de cero y caber en el sistema.')
            datos = {'fecha': fecha, 'descripcion': descripcion, 'monto': monto}
            if referencia in resultado and resultado[referencia] != datos:
                raise ValidationError(f'Fila {numero}: la referencia {referencia} está repetida con datos distintos.')
            resultado[referencia] = datos
        if not resultado:
            raise ValidationError('El archivo no contiene movimientos.')
        return resultado
    except UnicodeError:
        raise ValidationError('El archivo no usa la codificación configurada para el banco.')
    except csv.Error:
        raise ValidationError('El archivo no coincide con el formato delimitado configurado.')
