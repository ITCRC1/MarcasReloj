from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core import permisos
from apps.core.forms import EmpleadoForm, MapeoForm
from apps.core.models import Empleado, Sucursal
from apps.marcas.models import MarcaManual, MarcaReloj
from apps.marcas.servicio import mapear_person_id, sugerencias_de_mapeo
from apps.motor.models import ResultadoDiario
from apps.periodos.models import Periodo


def contar_pendientes(user) -> dict:
    """Lo que hay que resolver antes de poder cerrar. Alimenta el tablero y el menu."""
    empleados = permisos.empleados_visibles(user)
    resultados = ResultadoDiario.objects.filter(empleado__in=empleados)
    return {
        "inconsistentes": resultados.filter(estado="INCONSISTENTE").count(),
        "advertencias": resultados.filter(
            estado="ADVERTENCIA", aceptado_en__isnull=True
        ).count(),
        "manuales": MarcaManual.objects.filter(
            empleado__in=empleados, estado="pendiente"
        ).count(),
        "sin_empleado": (
            MarcaReloj.objects.filter(empleado__isnull=True).count()
            if not permisos.es_supervisor(user)
            else 0
        ),
    }


def marcas_despues_de_cierres():
    """Marcas que llegaron para dias ya pagados. Necesitan un ajuste, no un recalculo."""
    filas = []
    for periodo in Periodo.objects.filter(estado="cerrado").exclude(cerrado_en=None):
        qs = MarcaReloj.objects.filter(
            fecha_local__range=(periodo.desde, periodo.hasta),
            recibida_en__gt=periodo.cerrado_en,
        ).select_related("empleado")
        if qs.exists():
            filas.append({"periodo": periodo, "marcas": qs[:20], "total": qs.count()})
    return filas


@login_required
def tablero(request):
    hoy = timezone.localdate()
    empleados = permisos.empleados_visibles(request.user)

    marcas_hoy = (
        MarcaReloj.objects.filter(fecha_local=hoy)
        .select_related("empleado")
        .order_by("-fecha_hora")
    )
    if permisos.es_supervisor(request.user):
        marcas_hoy = marcas_hoy.filter(empleado__in=empleados)

    limite = timezone.now() - timedelta(minutes=settings.ALERTA_AGENTE_MINUTOS)
    agentes = []
    for sucursal in Sucursal.objects.filter(activa=True):
        ultima = sucursal.ultima_sincronizacion
        agentes.append(
            {
                "sucursal": sucursal,
                "ultima": ultima,
                "caido": ultima is None or ultima < limite,
                "minutos": (
                    int((timezone.now() - ultima).total_seconds() // 60) if ultima else None
                ),
            }
        )

    # Un empleado activo sin PersonID nunca recibe marcas, asi que acumula
    # ausencias en silencio. Conviene verlo antes de cerrar la quincena.
    sin_mapear = empleados.filter(activo=True, person_id_smartpss__isnull=True)

    contexto = {
        "hoy": hoy,
        "sin_mapear": sin_mapear,
        "marcas_hoy": marcas_hoy[:25],
        "total_marcas_hoy": marcas_hoy.count(),
        "pendientes": contar_pendientes(request.user),
        "agentes": agentes,
        "alerta_minutos": settings.ALERTA_AGENTE_MINUTOS,
        "despues_de_cierre": marcas_despues_de_cierres(),
        "periodo_actual": Periodo.objects.filter(desde__lte=hoy, hasta__gte=hoy).first(),
        "resumen_hoy": ResultadoDiario.objects.filter(
            fecha=hoy, empleado__in=empleados
        ).values("estado").annotate(total=Count("pk")).order_by("-total"),
    }
    return render(request, "core/tablero.html", contexto)


@login_required
def empleados(request):
    qs = permisos.empleados_visibles(request.user).select_related(
        "departamento", "departamento__sucursal"
    )
    busqueda = request.GET.get("q", "").strip()
    if busqueda:
        qs = qs.filter(
            Q(nombre__icontains=busqueda)
            | Q(codigo_planilla__icontains=busqueda)
            | Q(person_id_smartpss__icontains=busqueda)
        )
    if request.GET.get("sin_mapear"):
        qs = qs.filter(person_id_smartpss__isnull=True)
    return render(
        request,
        "core/empleados.html",
        {"empleados": qs, "q": busqueda, "hoy": timezone.localdate()},
    )


@login_required
@permisos.requiere_rrhh
def empleado_form(request, pk=None):
    empleado = get_object_or_404(Empleado, pk=pk) if pk else None
    form = EmpleadoForm(request.POST or None, instance=empleado)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"Empleado {obj.codigo_planilla} guardado.")
        return redirect("core:empleado_detalle", pk=obj.pk)
    return render(request, "core/empleado_form.html", {"form": form, "empleado": empleado})


@login_required
def empleado_detalle(request, pk):
    empleado = get_object_or_404(
        Empleado.objects.select_related("departamento"), pk=pk
    )
    permisos.exigir_empleado_visible(request.user, empleado)
    hoy = timezone.localdate()
    return render(
        request,
        "core/empleado_detalle.html",
        {
            "empleado": empleado,
            "asignaciones": empleado.asignaciones.select_related("horario"),
            "justificaciones": empleado.justificaciones.all()[:10],
            "ultimos_dias": empleado.resultados.order_by("-fecha")[:15],
            "sugerencias": (
                sugerencias_de_mapeo(empleado)
                if empleado.person_id_smartpss is None and permisos.es_rrhh(request.user)
                else []
            ),
            "form_mapeo": MapeoForm(),
            "hoy": hoy,
        },
    )


@login_required
@permisos.requiere_rrhh
def empleado_mapear(request, pk):
    empleado = get_object_or_404(Empleado, pk=pk)
    form = MapeoForm(request.POST)
    if form.is_valid():
        person_id = form.cleaned_data["person_id"]
        ocupado = Empleado.objects.filter(person_id_smartpss=person_id).exclude(pk=pk).first()
        if ocupado:
            messages.error(request, f"El PersonID {person_id} ya es de {ocupado.nombre}.")
        else:
            adoptadas = mapear_person_id(empleado, person_id)
            messages.success(
                request,
                f"PersonID {person_id} asignado. Se adoptaron {adoptadas} marca(s) "
                "y se recalcularon sus dias.",
            )
    return redirect("core:empleado_detalle", pk=pk)


@login_required
def bitacora(request):
    """Quien cambio que, cuando y por que (reporte 12.5)."""
    from apps.horarios.models import Feriado, Horario, Justificacion
    from apps.periodos.models import Ajuste, Periodo as P

    modelos = {
        "empleados": Empleado,
        "marcas": MarcaReloj,
        "marcas_manuales": MarcaManual,
        "horarios": Horario,
        "feriados": Feriado,
        "justificaciones": Justificacion,
        "periodos": P,
        "ajustes": Ajuste,
    }
    clave = request.GET.get("tipo", "marcas_manuales")
    modelo = modelos.get(clave, MarcaManual)
    registros = modelo.history.select_related("history_user").all()[:200]
    return render(
        request,
        "core/bitacora.html",
        {"registros": registros, "tipos": modelos.keys(), "tipo": clave},
    )
