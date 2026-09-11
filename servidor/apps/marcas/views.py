from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core import permisos
from apps.core.models import Empleado
from apps.core.tiempo import datetime_local
from apps.marcas.forms import MarcaManualForm, MotivoForm
from apps.marcas.models import MarcaManual, MarcaReloj
from apps.marcas.servicio import (
    PeriodoCerrado,
    aceptar_advertencia,
    anular_marca,
    crear_marca_manual,
    resolver_marca_manual,
    restaurar_marca,
)
from apps.motor.models import ResultadoDiario
from apps.motor.servicio import contexto_del_dia, esta_cerrado, periodo_de, recalcular


def _empleado_visible(request, codigo: str) -> Empleado:
    empleado = get_object_or_404(Empleado, codigo_planilla=codigo)
    permisos.exigir_empleado_visible(request.user, empleado)
    return empleado


@login_required
def dia(request, codigo: str, fecha: str):
    """Pantalla principal de trabajo: todo lo que pasa un dia y que se puede hacer."""
    empleado = _empleado_visible(request, codigo)
    dia_ = date.fromisoformat(fecha)

    resultado = ResultadoDiario.objects.filter(empleado=empleado, fecha=dia_).first()
    if resultado is None and not esta_cerrado(dia_):
        resultado = recalcular(empleado, dia_)

    ctx, parametros, horario = contexto_del_dia(empleado, dia_)
    descartadas = {
        m["id"] for m in (resultado.marcas_usadas if resultado else [])
        if m.get("descartada_por_duplicado")
    }

    periodo = periodo_de(dia_)
    contexto = {
        "empleado": empleado,
        "fecha": dia_,
        "anterior": dia_ - timedelta(days=1),
        "siguiente": dia_ + timedelta(days=1),
        "resultado": resultado,
        "horario": horario,
        "bloques": ctx.bloques,
        "es_feriado": ctx.es_feriado,
        "justificacion": ctx.justificacion,
        "parametros": parametros,
        "marcas_reloj": MarcaReloj.objects.filter(
            empleado=empleado, fecha_local=dia_
        ).order_by("fecha_hora"),
        "marcas_manuales": MarcaManual.objects.filter(
            empleado=empleado, fecha_local=dia_
        ).order_by("fecha_hora"),
        "descartadas": descartadas,
        "periodo": periodo,
        "cerrado": esta_cerrado(dia_),
        "form_manual": MarcaManualForm(),
        "form_motivo": MotivoForm(),
        "puede_corregir": permisos.puede_crear_marca_manual(request.user),
        "aprueba_directo": permisos.es_rrhh(request.user),
        "historial": ResultadoDiario.objects.filter(empleado=empleado, fecha=dia_).first(),
    }
    return render(request, "marcas/dia.html", contexto)


@login_required
def dia_de_hoy(request, codigo: str):
    return redirect("marcas:dia", codigo=codigo, fecha=timezone.localdate().isoformat())


@login_required
def pendientes(request):
    """Todo lo que hay que resolver antes del cierre, agrupado por tipo (reporte 12.3)."""
    empleados = permisos.empleados_visibles(request.user)
    resultados = ResultadoDiario.objects.filter(empleado__in=empleados).select_related(
        "empleado"
    )
    contexto = {
        "inconsistentes": resultados.filter(estado="INCONSISTENTE").order_by("-fecha")[:100],
        "advertencias": resultados.filter(
            estado="ADVERTENCIA", aceptado_en__isnull=True
        ).order_by("-fecha")[:100],
        "manuales": MarcaManual.objects.filter(
            empleado__in=empleados, estado="pendiente"
        ).select_related("empleado", "creada_por").order_by("-fecha_local")[:100],
        "sin_empleado": (
            MarcaReloj.objects.filter(empleado__isnull=True)
            .values("person_id", "person_name", "sucursal__nombre")
            .distinct()[:100]
            if not permisos.es_supervisor(request.user)
            else []
        ),
    }
    return render(request, "marcas/pendientes.html", contexto)


@login_required
def crudas(request):
    """Marcas tal como llegaron, incluidas duplicadas y anuladas (reporte 12.6)."""
    qs = MarcaReloj.objects.select_related("empleado", "sucursal").order_by("-fecha_hora")
    if permisos.es_supervisor(request.user):
        qs = qs.filter(empleado__in=permisos.empleados_visibles(request.user))
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
    empleado = _empleado_visible(request, codigo)
    dia_ = date.fromisoformat(fecha)
    if not permisos.puede_crear_marca_manual(request.user):
        raise PermissionDenied("Su rol no puede crear marcas manuales.")

    periodo = periodo_de(dia_)
    if periodo and periodo.estado == "en_revision" and permisos.es_supervisor(request.user):
        messages.error(
            request, "El periodo esta en revision: solo RRHH puede hacer cambios."
        )
        return _volver_al_dia(empleado, dia_)

    form = MarcaManualForm(request.POST)
    if form.is_valid():
        try:
            crear_marca_manual(
                empleado=empleado,
                fecha_hora=datetime_local(dia_, form.cleaned_data["hora"]),
                motivo=form.cleaned_data["motivo"],
                detalle=form.cleaned_data["detalle"],
                usuario=request.user,
                aprobada_directamente=permisos.es_rrhh(request.user),
            )
            messages.success(
                request,
                "Marca manual aprobada y aplicada."
                if permisos.es_rrhh(request.user)
                else "Marca manual creada. Queda pendiente de aprobacion por RRHH.",
            )
        except (PeriodoCerrado, ValueError) as error:
            messages.error(request, str(error))
    else:
        messages.error(request, "Revise el formulario: " + form.errors.as_text())
    return _volver_al_dia(empleado, dia_)


@login_required
@permisos.requiere_rrhh
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
        except (PeriodoCerrado, ValueError) as error:
            messages.error(request, str(error))
    else:
        messages.error(request, "El motivo es obligatorio.")
    if marca.empleado_id:
        return _volver_al_dia(marca.empleado, marca.fecha_local)
    return redirect("marcas:pendientes")


@login_required
@permisos.requiere_rrhh
def manual_resolver(request, pk: int, accion: str):
    manual = get_object_or_404(MarcaManual, pk=pk)
    comentario = request.POST.get("motivo", "").strip()
    try:
        resolver_marca_manual(manual, request.user, accion, comentario)
        messages.success(request, f"Marca manual {accion}.")
    except (PeriodoCerrado, ValueError) as error:
        messages.error(request, str(error))
    destino = request.POST.get("volver")
    if destino == "pendientes":
        return redirect("marcas:pendientes")
    return _volver_al_dia(manual.empleado, manual.fecha_local)


@login_required
@permisos.requiere_rrhh
def advertencia_aceptar(request, pk: int):
    resultado = get_object_or_404(ResultadoDiario, pk=pk)
    form = MotivoForm(request.POST)
    if form.is_valid():
        try:
            aceptar_advertencia(resultado, request.user, form.cleaned_data["motivo"])
            messages.success(request, "Advertencia aceptada. Los minutos no cambian.")
        except (PeriodoCerrado, ValueError) as error:
            messages.error(request, str(error))
    else:
        messages.error(request, "El motivo es obligatorio.")
    if request.POST.get("volver") == "pendientes":
        return redirect("marcas:pendientes")
    return _volver_al_dia(resultado.empleado, resultado.fecha)


@login_required
def recalcular_dia(request, codigo: str, fecha: str):
    empleado = _empleado_visible(request, codigo)
    dia_ = date.fromisoformat(fecha)
    if recalcular(empleado, dia_) is None:
        messages.warning(
            request,
            "No se guardo nada: el dia pertenece a un periodo cerrado, "
            "el empleado no estaba contratado, o seria una ausencia de hoy.",
        )
    else:
        messages.success(request, "Dia recalculado.")
    return _volver_al_dia(empleado, dia_)
