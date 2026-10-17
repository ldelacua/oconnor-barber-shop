from datetime import datetime, timedelta


def construir_matrices(horarios, dias):
    """Representación de lectura; cada bloque conserva su horario original."""
    grupos = {}
    for horario in horarios:
        grupo = grupos.setdefault(horario.barbero_id, {
            "barbero": horario.barbero,
            "horarios": [],
        })
        grupo["horarios"].append(horario)

    matrices = []
    for grupo in grupos.values():
        registros = grupo["horarios"]
        # Misma ventana que la creación, ampliada si hay horarios fuera de ella.
        inicio = min([480] + [h.hora_inicio.hour * 60 + h.hora_inicio.minute for h in registros])
        fin = max([1380] + [h.hora_fin.hour * 60 + h.hora_fin.minute + bool(h.hora_fin.second) for h in registros])
        inicio = (inicio // 30) * 30
        fin = ((fin + 29) // 30) * 30
        filas = []
        for minuto in range(inicio, fin, 30):
            comienzo = (datetime.min + timedelta(minutes=minuto)).time()
            celdas = []
            for numero, nombre in dias:
                coincidentes = [h for h in registros if (
                    h.dia_semana == numero
                    and (h.hora_inicio.hour * 3600 + h.hora_inicio.minute * 60 + h.hora_inicio.second) < (minuto + 30) * 60
                    and (h.hora_fin.hour * 3600 + h.hora_fin.minute * 60 + h.hora_fin.second) > minuto * 60
                )]
                celdas.append({"horarios": coincidentes, "dia": nombre})
            filas.append({"hora": comienzo.strftime("%H:%M"), "celdas": celdas})
        matrices.append({**grupo, "filas": filas})
    return matrices
