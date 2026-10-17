from decimal import Decimal


def agrupar_detalles(detalles):
    """Agrupa por identidad del prestador, sin modificar los documentos."""
    grupos = {}
    total = {"cantidad": 0, "usd": Decimal("0.00"), "bs": Decimal("0.00")}
    for detalle in detalles:
        clave = detalle.barbero_id
        if clave not in grupos:
            nombre = (
                f"{detalle.barbero.nombre} {detalle.barbero.apellido}"
                if clave is not None else "Sin prestador registrado (ventas anteriores)"
            )
            grupos[clave] = {
                "id": clave, "nombre": nombre, "filas": [],
                "cantidad": 0, "usd": Decimal("0.00"), "bs": Decimal("0.00"),
            }
        grupo = grupos[clave]
        cantidad = detalle.cantidad_servicio * (-1 if detalle.documento.tipo_documento == "RE" else 1)
        fila = {
            "fecha": detalle.documento.fecha,
            "documento_id": detalle.documento_id,
            "tipo": detalle.documento.tipo_documento,
            "servicio": detalle.descripcion_servicio,
            "cantidad": cantidad,
            "usd": detalle.monto_servicio,
            "bs": detalle.monto_servicio_bs,
        }
        grupo["filas"].append(fila)
        for destino in (grupo, total):
            destino["cantidad"] += cantidad
            destino["usd"] += detalle.monto_servicio
            destino["bs"] += detalle.monto_servicio_bs
    return sorted(grupos.values(), key=lambda g: (g["nombre"].casefold(), g["id"] or 0)), total
