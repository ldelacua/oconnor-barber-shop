from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render

from barberos.models import Barbero

from .forms import HorarioForm, MatrizHorarioForm, SillaForm
from .models import Horario, Silla
from .matriz_visual import construir_matrices
from .services.matriz_horarios import crear_horarios_desde_matriz


# ==========================================================
# SILLAS
# ==========================================================


@login_required
def listar_sillas(request):
    sillas = Silla.objects.all().order_by("nombre")

    contexto = {
        "sillas": sillas,
        "titulo": "Sillas",
        "descripcion": (
            "Administra las sillas disponibles en la barbería."
        ),
    }

    return render(
        request,
        "horarios/sillas/lista.html",
        contexto,
    )


@login_required
def crear_silla(request):
    if request.method == "POST":
        formulario = SillaForm(request.POST)

        if formulario.is_valid():
            silla = formulario.save()

            messages.success(
                request,
                f'La silla "{silla.nombre}" fue creada correctamente.',
            )

            return redirect("horarios:listar_sillas")
    else:
        formulario = SillaForm()

    contexto = {
        "formulario": formulario,
        "titulo": "Nueva silla",
        "descripcion": (
            "Registra una nueva silla disponible en la barbería."
        ),
        "texto_boton": "Guardar silla",
    }

    return render(
        request,
        "horarios/sillas/formulario.html",
        contexto,
    )


@login_required
def editar_silla(request, silla_id):
    silla = get_object_or_404(Silla, pk=silla_id)

    if request.method == "POST":
        formulario = SillaForm(
            request.POST,
            instance=silla,
        )

        if formulario.is_valid():
            silla = formulario.save()

            messages.success(
                request,
                f'La silla "{silla.nombre}" fue actualizada correctamente.',
            )

            return redirect("horarios:listar_sillas")
    else:
        formulario = SillaForm(instance=silla)

    contexto = {
        "formulario": formulario,
        "silla": silla,
        "titulo": "Editar silla",
        "descripcion": (
            "Modifica la información de la silla seleccionada."
        ),
        "texto_boton": "Guardar cambios",
    }

    return render(
        request,
        "horarios/sillas/formulario.html",
        contexto,
    )


@login_required
def eliminar_silla(request, silla_id):
    silla = get_object_or_404(Silla, pk=silla_id)

    if request.method == "POST":
        nombre = silla.nombre

        try:
            silla.delete()

            messages.success(
                request,
                f'La silla "{nombre}" fue eliminada correctamente.',
            )
        except ProtectedError:
            messages.error(
                request,
                (
                    f'No se puede eliminar la silla "{nombre}" porque '
                    "tiene horarios asociados. Puedes desactivarla "
                    "en lugar de eliminarla."
                ),
            )

        return redirect("horarios:listar_sillas")

    contexto = {
        "silla": silla,
        "titulo": "Eliminar silla",
        "descripcion": "Confirma si deseas eliminar esta silla.",
    }

    return render(
        request,
        "horarios/sillas/eliminar.html",
        contexto,
    )


@login_required
def cambiar_estado_silla(request, silla_id):
    silla = get_object_or_404(Silla, pk=silla_id)

    if request.method == "POST":
        silla.activa = not silla.activa
        silla.save()

        estado = "activada" if silla.activa else "desactivada"

        messages.success(
            request,
            f'La silla "{silla.nombre}" fue {estado} correctamente.',
        )

    return redirect("horarios:listar_sillas")


# ==========================================================
# HORARIOS
# ==========================================================


@login_required
def listar_horarios(request):
    horarios = Horario.objects.select_related(
        "barbero",
        "silla",
    )

    barbero_id = request.GET.get("barbero")
    silla_id = request.GET.get("silla")
    dia = request.GET.get("dia")
    estado = request.GET.get("estado")

    if barbero_id:
        horarios = horarios.filter(barbero_id=barbero_id)

    if silla_id:
        horarios = horarios.filter(silla_id=silla_id)

    if dia:
        horarios = horarios.filter(dia_semana=dia)

    if estado == "activos":
        horarios = horarios.filter(activo=True)
    elif estado == "inactivos":
        horarios = horarios.filter(activo=False)

    horarios = list(horarios.order_by(
        "barbero__nombre", "barbero__apellido", "barbero_id",
        "dia_semana", "hora_inicio", "pk",
    ))
    dias_matriz = [
        (numero, nombre) for numero, nombre in Horario.DIAS_SEMANA
        if not dia or str(numero) == str(dia)
    ]

    contexto = {
        "matrices": construir_matrices(horarios, dias_matriz),
        "dias_matriz": dias_matriz,
        "horarios": horarios,
        "barberos": Barbero.objects.all().order_by(
            "nombre",
            "apellido",
        ),
        "sillas": Silla.objects.all().order_by("nombre"),
        "dias": Horario.DIAS_SEMANA,
        "filtros": {
            "barbero": barbero_id or "",
            "silla": silla_id or "",
            "dia": dia or "",
            "estado": estado or "",
        },
        "titulo": "Horarios",
        "descripcion": (
            "Consulta, filtra y administra los horarios registrados."
        ),
    }

    return render(
        request,
        "horarios/horarios/lista.html",
        contexto,
    )


@login_required
def crear_horario(request):
    if request.method == "POST":
        formulario = MatrizHorarioForm(request.POST)

        if formulario.is_valid():
            horarios, errores = crear_horarios_desde_matriz(
                barbero=formulario.cleaned_data["barbero"],
                silla=formulario.cleaned_data["silla"],
                seleccion=formulario.cleaned_data["bloques"],
                activo=formulario.cleaned_data["activo"],
                observaciones=formulario.cleaned_data[
                    "observaciones"
                ],
            )

            if errores:
                for error in errores:
                    messages.error(request, error)
            else:
                messages.success(
                    request,
                    (
                        "Se registraron correctamente "
                        f"{len(horarios)} bloques de horario."
                    ),
                )

                return redirect("horarios:listar_horarios")
    else:
        formulario = MatrizHorarioForm()

    contexto = {
        "formulario": formulario,
        "titulo": "Nuevo horario",
        "descripcion": (
            "Selecciona el barbero, la silla y los bloques "
            "de trabajo en la matriz semanal."
        ),
        "texto_boton": "Guardar horarios",
        "dias": Horario.DIAS_SEMANA,
        "horas": generar_intervalos_matriz(),
    }

    return render(
        request,
        "horarios/formulario_matriz.html",
        contexto,
    )


@login_required
def editar_horario(request, horario_id):
    horario = get_object_or_404(
        Horario.objects.select_related("barbero", "silla"),
        pk=horario_id,
    )

    if request.method == "POST":
        formulario = HorarioForm(
            request.POST,
            instance=horario,
        )

        if formulario.is_valid():
            formulario.save()

            messages.success(
                request,
                "El horario fue actualizado correctamente.",
            )

            return redirect("horarios:listar_horarios")
    else:
        formulario = HorarioForm(instance=horario)

    contexto = {
        "formulario": formulario,
        "horario": horario,
        "titulo": "Editar horario",
        "descripcion": (
            "Modifica el día, las horas, el barbero o la silla."
        ),
        "texto_boton": "Guardar cambios",
    }

    return render(
        request,
        "horarios/horarios/formulario.html",
        contexto,
    )


@login_required
def eliminar_horario(request, horario_id):
    horario = get_object_or_404(
        Horario.objects.select_related("barbero", "silla"),
        pk=horario_id,
    )

    if request.method == "POST":
        horario.delete()

        messages.success(
            request,
            "El horario fue eliminado correctamente.",
        )

        return redirect("horarios:listar_horarios")

    contexto = {
        "horario": horario,
        "titulo": "Eliminar horario",
        "descripcion": (
            "Confirma si deseas eliminar este bloque de horario."
        ),
    }

    return render(
        request,
        "horarios/horarios/eliminar.html",
        contexto,
    )


@login_required
def cambiar_estado_horario(request, horario_id):
    horario = get_object_or_404(Horario, pk=horario_id)

    if request.method == "POST":
        horario.activo = not horario.activo
        horario.save()

        estado = "activado" if horario.activo else "desactivado"

        messages.success(
            request,
            f"El horario fue {estado} correctamente.",
        )

    return redirect("horarios:listar_horarios")


def generar_intervalos_matriz():
    """
    Genera intervalos de 30 minutos para la matriz semanal.

    Desde las 08:00 hasta las 22:30.
    """
    intervalos = []

    hora_actual = datetime.strptime("08:00", "%H:%M")
    ultima_hora = datetime.strptime("22:30", "%H:%M")

    while hora_actual <= ultima_hora:
        intervalos.append(hora_actual.strftime("%H:%M"))
        hora_actual += timedelta(minutes=30)

    return intervalos
