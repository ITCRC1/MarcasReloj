from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.models import Empleado
from apps.core.tiempo import datetime_local
from apps.marcas.forms import MarcaManualForm, MotivoForm
from apps.marcas.models import MarcaManual, MarcaReloj
from apps.marcas.servicio import (
    anular_marca,
    anular_marca_manual,
    crear_marca_manual,
    restaurar_marca,
)
from apps.motor.models import ResultadoDiario
from apps.motor.servicio import contexto_del_dia, recalcular


@login_required
def dia(request, codigo: str, fecha: str):
    """La pantalla de trabajo: todo lo que pasa un dia y que se puede hacer."""
    empleado = get_object_or_404(Empleado, codigo_planilla=codigo)
    dia_ = date.fromisoformat(fecha)

    resultado = ResultadoDiario.objects.filter(empleado=empleado, fecha=dia_).first()
    if resultado is None:
        resultado = recalcular(empleado, dia_)

    ctx, parametros, horario = contexto_del_dia(empleado, dia_)
    descartadas = {
        m["id"] for m in (resultado.marcas_usadas if resultado else [])
        if m.get("descartada_por_duplicado")
    }

    return render(
        request,
        "marcas/dia.html",
        {
            "empleado": empleado,
            "fecha": dia_,
            "anterior": dia_ - timedelta(days=1),
            "siguiente": dia_ + timedelta(days=1),
            "resultado": resultado,
            "horario": horario,
            "bloques": ctx.bloques,
            "es_feriado": ctx.es_feriado,
            "parametros": parametros,
            "marcas_reloj": MarcaReloj.objects.filter(
                empleado=empleado, fecha_local=dia_
            ).order_by("fecha_hora"),
            "marcas_manuales": MarcaManual.objects.filter(
                empleado=empleado, fecha_local=dia_
            ).select_related("creada_por").order_by("fecha_hora"),
            "descartadas": descartadas,
            "form_manual": MarcaManualForm(),
            "form_motivo": MotivoForm(),
        },
    )


@login_required
def dia_de_hoy(request, codigo: str):
    return redirect("marcas:dia", codigo=codigo, fecha=timezone.localdate().isoformat())


@login_required
def crudas(request):
    """Marcas tal como llegaron, incluidas duplicadas y anuladas. Para auditoria."""
    qs = MarcaReloj.objects.select_related("empleado").order_by("-fecha_hora")
    desde = request.GET.get("desde")
    hasta = request.GET.get("hasta")
    if desde:
        qs = qs.filter(fecha_local__gte=desde)
    if hasta:
        qs = qs.filter(fecha_local__lte=hasta)
    if request.GET.get("sin_empleado"):
        qs = qs.filter(empleado__isnull=True)
    return render(
        request,
        "marcas/crudas.html",
        {"marcas": qs[:500], "total": qs.count(), "desde": desde or "", "hasta": hasta or ""},
    )


# --------------------------------------------------------------------------
# Acciones
# --------------------------------------------------------------------------


def _volver_al_dia(empleado, fecha):
    return redirect("marcas:dia", codigo=empleado.codigo_planilla, fecha=fecha.isoformat())


@login_required
def marca_manual_crear(request, codigo: str, fecha: str):
    empleado = get_object_or_404(Empleado, codigo_planilla=codigo)
    dia_ = date.fromisoformat(fecha)
    form = MarcaManualForm(request.POST)
    if form.is_valid():
        try:
            crear_marca_manual(
                empleado=empleado,
                fecha_hora=datetime_local(dia_, form.cleaned_data["hora"]),
                motivo=form.cleaned_data["motivo"],
                detalle=form.cleaned_data["detalle"],
                usuario=request.user,
            )
            messages.success(request, "Marca manual agregada. El dia se recalculo.")
        except ValueError as error:
            messages.error(request, str(error))
    else:
        messages.error(request, "Revise el formulario: " + form.errors.as_text())
    return _volver_al_dia(empleado, dia_)


@login_required
def marca_anular(request, pk: int):
    marca = get_object_or_404(MarcaReloj, pk=pk)
    form = MotivoForm(request.POST)
    if form.is_valid():
        try:
            if marca.anulada:
                restaurar_marca(marca, request.user, form.cleaned_data["motivo"])
                messages.success(request, "Marca restaurada.")
            else:
                anular_marca(marca, request.user, form.cleaned_data["motivo"])
                messages.success(request, "Marca anulada. Sigue visible en el detalle.")
        except ValueError as error:
            messages.error(request, str(error))
    else:
        messages.error(request, "El motivo es obligatorio.")
    if marca.empleado_id:
        return _volver_al_dia(marca.empleado, marca.fecha_local)
    return redirect("marcas:crudas")


@login_required
def manual_anular(request, pk: int):
    manual = get_object_or_404(MarcaManual, pk=pk)
    form = MotivoForm(request.POST)
    if form.is_valid():
        try:
            anular_marca_manual(manual, form.cleaned_data["motivo"])
            messages.success(request, "Marca manual anulada. El dia se recalculo.")
        except ValueError as error:
            messages.error(request, str(error))
    else:
        messages.error(request, "El motivo es obligatorio.")
    return _volver_al_dia(manual.empleado, manual.fecha_local)


@login_required
def recalcular_dia(request, codigo: str, fecha: str):
    empleado = get_object_or_404(Empleado, codigo_planilla=codigo)
    dia_ = date.fromisoformat(fecha)
    if recalcular(empleado, dia_) is None:
        messages.warning(
            request,
            "No se guardo nada: el empleado no estaba contratado ese dia, "
            "o seria una ausencia de hoy.",
        )
    else:
        messages.success(request, "Dia recalculado.")
    return _volver_al_dia(empleado, dia_)
