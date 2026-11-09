from io import BytesIO
from xml.sax.saxutils import escape

from django.contrib.staticfiles import finders
from django.utils import timezone
from ventas.templatetags.ventas_formato import monto_venta


def generar_lista_precios(productos, escalas):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Image, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    archivo = BytesIO()
    doc = SimpleDocTemplate(archivo, pagesize=A4, leftMargin=42, rightMargin=42,
                            topMargin=42, bottomMargin=45, title="Lista de precios")
    estilos = getSampleStyleSheet()
    base = ParagraphStyle("Celda", parent=estilos["Normal"], fontSize=9, leading=12, splitLongWords=True)
    derecha = ParagraphStyle("Monto", parent=base, alignment=TA_RIGHT)
    blanca = ParagraphStyle("Encabezado", parent=base, textColor=colors.white, fontName="Helvetica-Bold")
    blanca_derecha = ParagraphStyle("Encabezado monto", parent=blanca, alignment=TA_RIGHT)
    azul = colors.HexColor("#183049")

    def celda(texto, estilo=base):
        return Paragraph(escape(str(texto)), estilo)

    def tabla(filas, anchos, adicionales=()):
        resultado = LongTable(filas, colWidths=anchos, repeatRows=1)
        resultado.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), azul),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#E1E7ED")),
            *adicionales,
        ]))
        return resultado

    historia = []
    logo_path = finders.find("seguridad/logo_oconnor.png")
    if logo_path:
        logo = Image(logo_path, width=120, height=72, kind="proportional", mask="auto")
        logo.hAlign = "CENTER"
        historia.extend([logo, Spacer(1, 6)])
    historia.extend([
        celda("Lista de precios", estilos["Title"]),
        celda(f"O'Connor Barber Shop  |  {timezone.localdate():%d/%m/%Y}  |  Precios en USD"),
        Spacer(1, 15),
    ])
    filas = [[celda("Código", blanca), celda("Producto", blanca), celda("Precio de venta USD", blanca_derecha)]]
    reglas = []
    grupo_anterior = object()
    for producto in productos:
        if grupo_anterior != producto.grupo_id:
            indice = len(filas)
            filas.append([celda(f"Grupo: {producto.grupo or 'Sin grupo'}"), "", ""])
            reglas.extend([
                ("SPAN", (0, indice), (-1, indice)),
                ("BACKGROUND", (0, indice), (-1, indice), colors.HexColor("#E8EFF5")),
                ("NOSPLIT", (0, indice), (-1, indice + 1)),
            ])
            grupo_anterior = producto.grupo_id
        precio = producto.precio_consulta
        filas.append([celda(producto.codigo_producto), celda(producto.nombre_producto),
                      celda(monto_venta(precio) if precio is not None else "Sin precio", derecha)])
    if len(filas) == 1:
        filas.append([celda("No hay productos con estos filtros."), "", ""])
        reglas.append(("SPAN", (0, 1), (-1, 1)))
    historia.append(tabla(filas, [doc.width * .20, doc.width * .54, doc.width * .26], reglas))

    if escalas is not None:
        historia.extend([Spacer(1, 18), celda("% Descuento Venta al Mayor", estilos["Heading2"])])
        if escalas:
            filas_escalas = [[celda("Desde unidades", blanca), celda("Porcentaje configurado", blanca_derecha)]]
            filas_escalas.extend([celda(monto_venta(e.unidades)), celda(f"{monto_venta(e.porcentaje)} %", derecha)]
                                 for e in escalas)
            historia.append(tabla(filas_escalas, [doc.width / 2] * 2))
        else:
            historia.append(celda("No hay escalas activas de venta al mayor."))

    def pie(canvas, documento):
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(azul)
        canvas.drawRightString(A4[0] - 42, 26, f"Página {documento.page}")

    doc.build(historia, onFirstPage=pie, onLaterPages=pie)
    return archivo.getvalue()
