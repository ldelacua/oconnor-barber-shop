from io import BytesIO


def generar_pdf(filas):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    salida = BytesIO()
    pdf = canvas.Canvas(salida, pagesize=A4)
    pdf.setTitle("O’Connor Barber Shop - Tarjetas de regalo")
    for indice, tarjeta in enumerate(filas):
        if indice and indice % 8 == 0:
            pdf.showPage()
        x = 32 + (indice % 2) * 270
        y = A4[1] - 44 - (indice % 8 // 2) * 187 - 170
        pdf.setStrokeColor(HexColor("#AD823D"))
        pdf.roundRect(x, y, 260, 170, 10, fill=0)
        pdf.setFillColor(HexColor("#201B15"))
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawCentredString(x + 130, y + 139, "O’CONNOR BARBER SHOP")
        pdf.setFont("Helvetica", 11)
        pdf.drawCentredString(x + 130, y + 119, "TARJETA DE REGALO")
        pdf.setFont("Helvetica-Bold", 23)
        pdf.drawCentredString(x + 130, y + 83, f"{tarjeta.monto:,.2f} {'Bs.' if tarjeta.moneda == 'BS' else 'USD'}")
        pdf.setFont("Courier-Bold", 13)
        codigo = "-".join(tarjeta.codigo[i:i + 4] for i in range(0, 16, 4))
        pdf.drawCentredString(x + 130, y + 56, codigo)
        pdf.setFont("Helvetica", 9)
        pdf.drawCentredString(x + 130, y + 32, "Uso único. Requiere activación al comprarla.")
        pdf.drawCentredString(x + 130, y + 19, "La factura debe cubrir el valor completo.")
    pdf.save()
    return salida.getvalue()
