from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement

from ventas.pagos_excel import NS, libro_excel, texto_seguro, xml


def hoja(cuenta, periodo, columnas, filas):
    raiz = Element('worksheet', xmlns=NS)
    columnas_xml = SubElement(raiz, 'cols')
    for i, ancho in enumerate([18, 22, 26, 27, 20, 19], 1):
        SubElement(columnas_xml, 'col', min=str(i), max=str(i), width=str(ancho), customWidth='1')
    datos = SubElement(raiz, 'sheetData')
    for numero, valores in enumerate([(str(cuenta),), (periodo.strftime('%m/%Y'),), columnas, *filas], 1):
        fila = SubElement(datos, 'row', r=str(numero))
        for i, valor in enumerate(valores):
            celda = SubElement(fila, 'c', r=f'{chr(65 + i)}{numero}', s='2' if isinstance(valor, Decimal) else '1' if numero <= 3 else '0')
            if isinstance(valor, Decimal):
                SubElement(celda, 'v').text = format(valor, '.2f')
            else:
                celda.set('t', 'inlineStr')
                SubElement(SubElement(celda, 'is'), 't').text = texto_seguro(valor)
    if filas:
        SubElement(raiz, 'autoFilter', ref=f'A3:{chr(64 + len(columnas))}{len(filas) + 3}')
    return xml(raiz)


def exportar(cuenta, periodo, resumen):
    filas = [(g['id'], lado.capitalize(), m['fecha'], m['referencia'], Decimal(m['monto']),
              g.get('metodo') or 'Sin registrar')
             for g in resumen['conciliaciones'] if isinstance(g, dict)
             for lado in ('banco', 'sistema') for m in g[lado]]
    hojas = [('Conciliados', hoja(cuenta, periodo,
              ('Grupo', 'Origen', 'Fecha original', 'Referencia', 'Importe', 'Método'), filas))]
    for lado, titulo in [('banco', 'Pendientes del banco'), ('sistema', 'Pendientes del sistema')]:
        filas = [(m['fecha'], m['referencia'], Decimal(m['monto']), 'Sí' if m['arrastrado'] else 'No')
                 for m in resumen[lado]]
        hojas.append((titulo, hoja(cuenta, periodo, ('Fecha original', 'Referencia', 'Importe', 'Arrastrado'), filas)))
    return libro_excel(hojas, f'conciliacion_{cuenta.pk}_{periodo:%Y-%m}.xlsx')
