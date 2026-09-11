from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.core import permisos
from apps.motor.models import ResultadoDiario
from apps.motor.servicio import recalcular_rango
from apps.periodos.forms import AjusteForm, PeriodoForm
from apps.periodos.models import Periodo
from apps.periodos.servicio import (
    advertencias_sin_aceptar,
    cerrar,
    marcas_despues_del_cierre,
    puede_cerrarse,
    validaciones_de_cierre,
)


@login_required
def periodos(request):
    form = PeriodoForm(request.POST or None)
    if request.method == "POST":
        if not permisos.es_rrhh(request.user):
            messages.error(request, "Solo RRHH puede crear periodos.")
        elif form.is_valid():
            periodo = form.save()
            messages.success(request, f"Periodo '{periodo.nombre}' creado.")
            return redirect("periodos:detalle", pk=periodo.pk)
    return render(
        request, "periodos/lista.html", {"form": form, "periodos": Periodo.objects.all()}
    )


@login_required
def periodo_detalle(request, pk):
    periodo = get_object_or_404(Periodo, pk=pk)
    validar = request.GET.get("validar") == "1"
    validaciones = (
        validaciones_de_cierre(periodo, recalcular_antes=True) if validar else []
    )
    return render(
        request,
        "periodos/detalle.html",
        {
            "periodo": periodo,
            "validaciones": validaciones,
            "validado": validar,
            "puede_cerrar": validar and puede_cerrarse(periodo, validaciones),
            "advertencias": advertencias_sin_aceptar(periodo),
            "despues_del_cierre": marcas_despues_del_cierre(periodo),
            "dias": ResultadoDiario.objects.filter(
                fecha__range=(periodo.desde, periodo.hasta)
            ).count(),
            "form_ajuste": AjusteForm(),
            "ajustes": periodo.ajustes.select_related("empleado", "creado_por"),
        },
    )


@login_required
@permisos.requiere_rrhh
def periodo_estado(request, pk, estado):
    periodo = get_object_or_404(Periodo, pk=pk)
    if periodo.cerrado:
        messages.error(request, "Un periodo cerrado no se reabre.")
    elif estado in ("abierto", "en_revision"):
        periodo.estado = estado
        periodo.save()
        messages.success(request, f"Periodo marcado como {periodo.get_estado_display()}.")
    return redirect("periodos:detalle", pk=pk)


@login_required
@permisos.requiere_rrhh
def periodo_cerrar(request, pk):
    periodo = get_object_or_404(Periodo, pk=pk)
    try:
        cerrar(periodo, request.user)
        messages.success(
            request,
            "Periodo cerrado. Los resultados quedan congelados; "
            "las correcciones posteriores se registran como ajustes.",
        )
    except ValueError as error:
        messages.error(request, str(error))
    return redirect("periodos:detalle", pk=pk)


@login_required
@permisos.requiere_rrhh
def periodo_recalcular(request, pk):
    periodo = get_object_or_404(Periodo, pk=pk)
    if periodo.cerrado:
        messages.error(request, "Los dias de un periodo cerrado no se recalculan.")
    else:
        guardados = recalcular_rango(periodo.desde, periodo.hasta)
        messages.success(request, f"{guardados} dia(s) recalculado(s).")
    return redirect("periodos:detalle", pk=pk)


@login_required
@permisos.requiere_rrhh
def ajuste_crear(request, pk):
    periodo = get_object_or_404(Periodo, pk=pk)
    form = AjusteForm(request.POST)
    form.instance.periodo_destino = periodo
    form.instance.creado_por = request.user
    if form.is_valid():
        form.save()
        messages.success(request, "Ajuste registrado.")
    else:
        messages.error(request, form.errors.as_text())
    return redirect("periodos:detalle", pk=pk)
