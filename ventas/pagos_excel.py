"""Exportación XLSX sin dependencias externas, con importes numéricos."""
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree.ElementTree import Element, SubElement, tostring
from django.http import HttpResponse

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ORIGENES = {'SERVICIOS': 'COBRO DE SERVICIOS', 'PRODUCTOS': 'COBRO DE PRODUCTOS',
    'PROVEEDOR': 'PAGO A PROVEEDOR', 'REVERSO_PROVEEDOR': 'REVERSO DE PAGO A PROVEEDOR', 'LIQUIDACION': 'PAGO A PRESTADOR'}


def xml(root):
    return tostring(root, encoding='utf-8', xml_declaration=True)


def texto_seguro(value):
    # XML 1.0 no admite controles; inlineStr evita ejecutar fórmulas de referencias/observaciones.
    return ''.join(c for c in str(value) if c in '\t\n\r' or ord(c) >= 32)[:32767]


def hoja(filas, moneda, filtros):
    root = Element('worksheet', xmlns=NS)
    views = SubElement(root, 'sheetViews')
    SubElement(SubElement(views, 'sheetView', workbookViewId='0'), 'pane', ySplit='4', topLeftCell='A5', activePane='bottomLeft', state='frozen')
    cols = SubElement(root, 'cols')
    for i, ancho in enumerate([31, 36, 14, 24, 23, 45, 12, 18, 18], 1):
        SubElement(cols, 'col', min=str(i), max=str(i), width=str(ancho), customWidth='1')
    data = SubElement(root, 'sheetData')
    def row(values, style=0):
        n = len(data) + 1
        rr = SubElement(data, 'row', r=str(n))
        for i, v in enumerate(values):
            cell = SubElement(rr, 'c', r=chr(65+i)+str(n), s=str(2 if isinstance(v, Decimal) else style))
            if isinstance(v, Decimal):
                SubElement(cell, 'v').text = format(v, '.2f')
            else:
                cell.set('t', 'inlineStr')
                SubElement(SubElement(cell, 'is'), 't').text = texto_seguro(v)
    row(['REPORTE DE PAGOS — '+moneda], 1)
    row(['Desde: '+str(filtros.get('desde') or 'INICIO')+' · Hasta: '+str(filtros.get('hasta') or 'HOY')])
    row(['Los reversos conservan el pago original y figuran como movimiento contrario.'])
    row(['Origen','Cliente / Proveedor / Prestador','Fecha pago','Forma de pago','Referencia','Observación','Moneda','Entradas','Salidas'], 1)
    entradas = salidas = Decimal('0.00')
    for f in filas:
        entrada = max(f['flujo'], Decimal('0.00'))
        salida = max(-f['flujo'], Decimal('0.00'))
        entradas += entrada
        salidas += salida
        row([ORIGENES.get(f['origen'], f['origen']), f['tercero'], f['fecha'].strftime('%d/%m/%Y'),
            f['nombre_tipo_pago'], f['referencia'], f['observacion'], moneda, entrada, salida])
    fin = len(data)
    row(['TOTALES','','','','','',moneda,entradas,salidas],1)
    # Totales editables y conciliados con los importes exportados.
    for celda, letra, valor in [(data[-1][-2], 'H', entradas), (data[-1][-1], 'I', salidas)]:
        SubElement(celda, 'f').text = f'SUM({letra}5:{letra}{fin})' if fin >= 5 else '0'
        celda.find('v').text = format(valor,'.2f')
        celda[:] = sorted(celda, key=lambda c: 0 if c.tag == 'f' else 1)
    row(['NETO (ENTRADAS − SALIDAS)','','','','','',moneda, entradas-salidas],1)
    if fin >= 5:
        SubElement(root, 'autoFilter', ref=f'A4:I{fin}')
    return xml(root)


def descargar_excel(filas, filtros):
    grupos = {'BS': [], 'USD': []}
    for f in filas:
        grupos[f['moneda']].append(f)
    return libro_excel([(f'Pagos {nombre}', hoja(grupos[moneda], moneda, filtros))
                        for moneda, nombre in [('BS', 'Bs'), ('USD', 'USD')]], 'reporte_pagos.xlsx')


def libro_excel(hojas, nombre_archivo):
    from xml.sax.saxutils import quoteattr
    hojas = list(hojas)
    partes = list(enumerate(hojas, 1))
    tipos = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i, _ in partes)
    nombres = ''.join(f'<sheet name={quoteattr(nombre)} sheetId="{i}" r:id="rId{i}"/>' for i, (nombre, _) in partes)
    enlaces = ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i, _ in partes)
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', f'''<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{tipos}</Types>''')
        z.writestr('_rels/.rels', '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        z.writestr('xl/workbook.xml', f'''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{nombres}</sheets></workbook>''')
        z.writestr('xl/_rels/workbook.xml.rels', f'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{enlaces}<Relationship Id="rIdEstilos" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''')
        z.writestr('xl/styles.xml', '''<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="3"><xf fontId="0"/><xf fontId="1" applyFont="1"/><xf fontId="0" numFmtId="4" applyNumberFormat="1"><alignment horizontal="right"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>''')
        for i, (_, contenido) in partes:
            z.writestr(f'xl/worksheets/sheet{i}.xml', contenido)
    response = HttpResponse(output.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response
