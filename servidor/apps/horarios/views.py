from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core import permisos
from apps.core.models import Empleado
from apps.horarios.forms import (
    AsignacionForm,
    BloqueForm,
    FeriadoForm,
    HorarioForm,
    JustificacionForm,
)
from apps.horarios.models import (
    LIMITE_JORNADA_MIN,
    AsignacionHorario,
    BloqueHorario,
    Feriado,
    Horario,
    Justificacion,
)
from apps.motor.servicio import recalcular, recalcular_rango

# Cuanto hacia atras se recalcula cuando cambia una regla del horario.
DIAS_DE_RECALCULO = 45


def _recalcular_por_horario(horario: Horario) -> int:
    """Un cambio de horario cambia lo esperado, asi que hay que rehacer los dias."""
    empleados = Empleado.objects.filter(
        asignaciones__horario=horario, activo=True
    ).distinct()
    if not empleados.exists():
        return 0
    hoy = timezone.localdate()
    return recalcular_rango(hoy - timedelta(days=DIAS_DE_RECALCULO), hoy, empleados)


@login_required
def horarios(request):
    return render(
        request,
        "horarios/lista.html",
        {
            "horarios": Horario.objects.prefetch_related("bloques"),
            "limites": LIMITE_JORNADA_MIN,
        },
    )


@login_required
@permisos.requiere_rrhh
def horario_form(request, pk=None):
    horario = get_object_or_404(Horario, pk=pk) if pk else None
    form = HorarioForm(request.POST or None, instance=horario)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        if horario:
            recalculados = _recalcular_por_horario(obj)
            messages.success(request, f"Horario guardado. {recalculados} dia(s) recalculado(s).")
        else:
            messages.success(request, "Horario creado. Agregue los bloques de cada dia.")
        return redirect("horarios:detalle", pk=obj.pk)
    return render(request, "horarios/form.html", {"form": form, "horario": horario})


@login_required
def horario_detalle(request, pk):
    horario = get_object_or_404(Horario, pk=pk)
    return render(
        request,
        "horarios/detalle.html",
        {
            "horario": horario,
            "semana": horario.resumen_semanal(),
            "minutos_semanales": horario.minutos_semanales(),
            "limite": LIMITE_JORNADA_MIN[horario.tipo_jornada],
            "excede": horario.excede_limite(),
            "form_bloque": BloqueForm(),
        },
    )


@login_required
@permisos.requiere_rrhh
def bloque_crear(request, pk):
    horario = get_object_or_404(Horario, pk=pk)
    form = BloqueForm(request.POST)
    form.instance.horario = horario
    if form.is_valid():
        form.save()
        recalculados = _recalcular_por_horario(horario)
        messages.success(request, f"Bloque agregado. {recalculados} dia(s) recalculado(s).")
    else:
        messages.error(request, form.errors.as_text())
    return redirect("horarios:detalle", pk=pk)


@login_required
@permisos.requiere_rrhh
def bloque_borrar(request, pk):
    bloque = get_object_or_404(BloqueHorario, pk=pk)
    horario_id = bloque.horario_id
    horario = bloque.horario
    bloque.delete()
    recalculados = _recalcular_por_horario(horario)
    messages.success(request, f"Bloque eliminado. {recalculados} dia(s) recalculado(s).")
    return redirect("horarios:detalle", pk=horario_id)


@login_required
@permisos.requiere_rrhh
def asignaciones(request):
    form = AsignacionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        asignacion = form.save()
        hoy = timezone.localdate()
        desde = max(asignacion.vigente_desde, hoy - timedelta(days=DIAS_DE_RECALCULO))
        hasta = min(asignacion.vigente_hasta or hoy, hoy)
        if desde <= hasta:
            recalcular_rango(desde, hasta, [asignacion.empleado])
        messages.success(request, "Asignacion guardada y dias recalculados.")
        return redirect("horarios:asignaciones")
    return render(
        request,
        "horarios/asignaciones.html",
        {
            "form": form,
            "asignaciones": AsignacionHorario.objects.select_related("empleado", "horario"),
        },
    )


@login_required
def feriados(request):
    form = FeriadoForm(request.POST or None)
    if request.method == "POST":
        if not permisos.es_rrhh(request.user):
            messages.error(request, "Solo RRHH puede registrar feriados.")
        elif form.is_valid():
            feriado = form.save()
            recalcular_rango(feriado.fecha, feriado.fecha)
            messages.success(request, "Feriado guardado y dias recalculados.")
            return redirect("horarios:feriados")
    return render(
        request, "horarios/feriados.html", {"form": form, "feriados": Feriado.objects.all()}
    )


@login_required
def justificaciones(request):
    form = JustificacionForm(request.POST or None)
    if request.method == "POST":
        if not permisos.es_rrhh(request.user):
            messages.error(request, "Solo RRHH puede registrar justificaciones.")
        elif form.is_valid():
            justificacion = form.save(commit=False)
            justificacion.registrada_por = request.user
            justificacion.save()
            recalcular_rango(
                justificacion.desde, justificacion.hasta, [justificacion.empleado]
            )
            messages.success(request, "Justificacion guardada y dias recalculados.")
            return redirect("horarios:justificaciones")
    qs = Justificacion.objects.select_related("empleado", "registrada_por")
    if permisos.es_supervisor(request.user):
        qs = qs.filter(empleado__in=permisos.empleados_visibles(request.user))
    return render(
        request, "horarios/justificaciones.html", {"form": form, "justificaciones": qs[:100]}
    )
