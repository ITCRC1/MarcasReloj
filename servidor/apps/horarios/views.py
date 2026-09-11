from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.models import Empleado
from apps.horarios.forms import BloqueForm, FeriadoForm, HorarioForm
from apps.horarios.models import BloqueHorario, Feriado, Horario
from apps.motor.servicio import recalcular_rango

# Cuanto hacia atras se recalcula cuando cambia una regla del horario.
DIAS_DE_RECALCULO = 45


def _recalcular_por_horario(horario: Horario) -> int:
    """Un cambio de horario cambia lo esperado, asi que hay que rehacer los dias."""
    empleados = Empleado.objects.filter(horario=horario, activo=True)
    if not empleados.exists():
        return 0
    hoy = timezone.localdate()
    return recalcular_rango(hoy - timedelta(days=DIAS_DE_RECALCULO), hoy, empleados)


@login_required
def horarios(request):
    return render(
        request, "horarios/lista.html", {"horarios": Horario.objects.prefetch_related("bloques")}
    )


@login_required
def horario_form(request, pk=None):
    horario = get_object_or_404(Horario, pk=pk) if pk else None
    form = HorarioForm(request.POST or None, instance=horario)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        if horario:
            n = _recalcular_por_horario(obj)
            messages.success(request, f"Horario guardado. {n} dia(s) recalculado(s).")
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
            "form_bloque": BloqueForm(),
            "empleados": horario.empleados.filter(activo=True),
        },
    )


@login_required
def bloque_crear(request, pk):
    horario = get_object_or_404(Horario, pk=pk)
    form = BloqueForm(request.POST)
    form.instance.horario = horario
    if form.is_valid():
        form.save()
        n = _recalcular_por_horario(horario)
        messages.success(request, f"Bloque agregado. {n} dia(s) recalculado(s).")
    else:
        messages.error(request, form.errors.as_text())
    return redirect("horarios:detalle", pk=pk)


@login_required
def bloque_borrar(request, pk):
    bloque = get_object_or_404(BloqueHorario, pk=pk)
    horario = bloque.horario
    bloque.delete()
    n = _recalcular_por_horario(horario)
    messages.success(request, f"Bloque eliminado. {n} dia(s) recalculado(s).")
    return redirect("horarios:detalle", pk=horario.pk)


@login_required
def feriados(request):
    form = FeriadoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        feriado = form.save()
        recalcular_rango(feriado.fecha, feriado.fecha)
        messages.success(request, "Feriado guardado y dias recalculados.")
        return redirect("horarios:feriados")
    return render(
        request, "horarios/feriados.html", {"form": form, "feriados": Feriado.objects.all()}
    )


@login_required
def feriado_borrar(request, pk):
    feriado = get_object_or_404(Feriado, pk=pk)
    fecha = feriado.fecha
    feriado.delete()
    recalcular_rango(fecha, fecha)
    messages.success(request, "Feriado eliminado y dias recalculados.")
    return redirect("horarios:feriados")
