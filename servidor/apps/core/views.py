from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.forms import EmpleadoForm, MapeoForm
from apps.core.models import Empleado
from apps.marcas import importador
from apps.marcas.models import MarcaReloj
from apps.marcas.servicio import mapear_person_id, sugerencias_de_mapeo
from apps.motor.models import ResultadoDiario


@login_required
def tablero(request):
    hoy = timezone.localdate()

    marcas_hoy = (
        MarcaReloj.objects.filter(fecha_local=hoy)
        .select_related("empleado")
        .order_by("-fecha_hora")
    )
    revisar = ResultadoDiario.objects.filter(
        estado__in=("INCONSISTENTE", "ADVERTENCIA")
    ).select_related("empleado").order_by("-fecha")

    # Un empleado activo sin PersonID nunca recibe marcas, asi que acumula
    # ausencias en silencio. Conviene verlo antes de sacar el reporte.
    sin_mapear = Empleado.objects.filter(activo=True, person_id_smartpss__isnull=True)

    ultima = MarcaReloj.objects.order_by("-fecha_hora").first()

    # Si SmartPSS escribe y el sistema no importa, antes no se notaba: la
    # pantalla se veia igual que un dia sin marcas. Este numero lo delata.
    sin_importar = importador.pendientes(settings.SMARTPSS_TABLA)

    return render(
        request,
        "core/tablero.html",
        {
            "hoy": hoy,
            "tabla_smartpss": settings.SMARTPSS_TABLA,
            "sin_importar": sin_importar,
            "marcas_hoy": marcas_hoy[:25],
            "total_marcas_hoy": marcas_hoy.count(),
            "inconsistentes": revisar.filter(estado="INCONSISTENTE")[:20],
            "advertencias": revisar.filter(estado="ADVERTENCIA")[:20],
            "total_inconsistentes": revisar.filter(estado="INCONSISTENTE").count(),
            "total_advertencias": revisar.filter(estado="ADVERTENCIA").count(),
            "sin_empleado": MarcaReloj.objects.filter(empleado__isnull=True)
            .values("person_id", "person_name")
            .annotate(marcas=Count("pk"))
            .order_by("-marcas")[:10],
            "total_sin_empleado": MarcaReloj.objects.filter(empleado__isnull=True).count(),
            "sin_mapear": sin_mapear,
            "ultima_marca": ultima,
            "empleados_activos": Empleado.objects.filter(activo=True).count(),
        },
    )


@login_required
def empleados(request):
    qs = Empleado.objects.select_related("horario")
    busqueda = request.GET.get("q", "").strip()
    if busqueda:
        qs = qs.filter(
            Q(nombre__icontains=busqueda)
            | Q(codigo_planilla__icontains=busqueda)
            | Q(person_id_smartpss__icontains=busqueda)
        )
    if request.GET.get("sin_mapear"):
        qs = qs.filter(person_id_smartpss__isnull=True)
    return render(request, "core/empleados.html", {"empleados": qs, "q": busqueda})


@login_required
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
    empleado = get_object_or_404(Empleado.objects.select_related("horario"), pk=pk)
    return render(
        request,
        "core/empleado_detalle.html",
        {
            "empleado": empleado,
            "ultimos_dias": empleado.resultados.order_by("-fecha")[:15],
            "sugerencias": (
                sugerencias_de_mapeo(empleado)
                if empleado.person_id_smartpss is None
                else []
            ),
            "form_mapeo": MapeoForm(),
            "hoy": timezone.localdate(),
            "hace_un_mes": timezone.localdate() - timedelta(days=30),
        },
    )


@login_required
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
