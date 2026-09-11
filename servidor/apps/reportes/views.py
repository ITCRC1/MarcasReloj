"""El reporte: una fila por dia por empleado, con totales, en pantalla y en Excel."""

from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from apps.core.models import Empleado
from apps.motor.models import ResultadoDiario
from apps.reportes import exportar

CAMPOS_MINUTOS = [
    ("minutos_esperados", "Esperado"),
    ("minutos_ordinarios", "Ordinario"),
    ("minutos_extra", "Extra"),
    ("minutos_tardia", "Tardia"),
    ("minutos_salida_anticipada", "Salida ant."),
    ("minutos_no_laborados", "No laborado"),
    ("minutos_fuera_horario", "Fuera de horario"),
    ("minutos_feriado", "Feriado"),
    ("minutos_descanso_trabajado", "Descanso trab."),
]


def _rango(request) -> tuple[date, date]:
    """Por defecto, la quincena en curso."""
    hoy = timezone.localdate()
    inicio = date(hoy.year, hoy.month, 1) if hoy.day <= 15 else date(hoy.year, hoy.month, 16)
    desde = request.GET.get("desde") or inicio.isoformat()
    hasta = request.GET.get("hasta") or hoy.isoformat()
    try:
        return date.fromisoformat(desde), date.fromisoformat(hasta)
    except ValueError:
        return inicio, hoy


def _totales_por_empleado(desde: date, hasta: date, empleados):
    """Una fila por empleado con todos los totales del rango."""
    sumas = {f"tot_{campo}": Sum(campo) for campo, _ in CAMPOS_MINUTOS}
    agregados = {
        fila["empleado_id"]: fila
        for fila in ResultadoDiario.objects.filter(
            fecha__range=(desde, hasta), empleado__in=empleados
        )
        .values("empleado_id")
        .annotate(
            **sumas,
            dias_laborados=Count("pk", filter=Q(minutos_trabajados__gt=0)),
            dias_ausente=Count("pk", filter=Q(estado="AUSENTE")),
            dias_revisar=Count("pk", filter=Q(estado__in=("INCONSISTENTE", "ADVERTENCIA"))),
        )
    }

    filas = []
    for empleado in empleados:
        datos = agregados.get(empleado.pk)
        if datos is None:
            continue
        fila = {
            "empleado": empleado,
            "codigo": empleado.codigo_planilla,
            "nombre": empleado.nombre,
            "departamento": empleado.departamento,
            "dias_laborados": datos["dias_laborados"],
            "dias_ausente": datos["dias_ausente"],
            "dias_revisar": datos["dias_revisar"],
        }
        for campo, _ in CAMPOS_MINUTOS:
            fila[campo] = datos[f"tot_{campo}"] or 0
        filas.append(fila)
    return filas


@login_required
def reporte(request):
    """Resumen del rango: una fila por empleado."""
    desde, hasta = _rango(request)
    empleados = Empleado.objects.all()
    departamento = request.GET.get("departamento", "").strip()
    if departamento:
        empleados = empleados.filter(departamento=departamento)

    filas = _totales_por_empleado(desde, hasta, empleados)
    totales = {
        campo: sum(f[campo] for f in filas) for campo, _ in CAMPOS_MINUTOS
    }

    if request.GET.get("formato") == "excel":
        return _resumen_excel(desde, hasta, filas, totales)

    return render(
        request,
        "reportes/reporte.html",
        {
            "desde": desde,
            "hasta": hasta,
            "filas": filas,
            "totales": totales,
            "campos": CAMPOS_MINUTOS,
            "departamentos": (
                Empleado.objects.exclude(departamento="")
                .values_list("departamento", flat=True)
                .distinct()
            ),
            "departamento": departamento,
        },
    )


@login_required
def detalle_empleado(request, codigo: str):
    """Una fila por dia, para revisar y para que el empleado lo firme."""
    from django.shortcuts import get_object_or_404

    desde, hasta = _rango(request)
    empleado = get_object_or_404(Empleado, codigo_planilla=codigo)

    resultados = ResultadoDiario.objects.filter(
        empleado=empleado, fecha__range=(desde, hasta)
    ).order_by("fecha")

    dias = []
    for r in resultados:
        e1, s1, e2, s2 = r.marcas_por_posicion()
        manuales = {m["hora"] for m in r.marcas_usadas if m.get("origen") == "manual"}
        dias.append({"r": r, "e1": e1, "s1": s1, "e2": e2, "s2": s2, "manuales": manuales})

    totales = {
        campo: sum(getattr(r, campo) for r in resultados) for campo, _ in CAMPOS_MINUTOS
    }

    if request.GET.get("formato") == "excel":
        return _detalle_excel(empleado, desde, hasta, dias, totales)

    return render(
        request,
        "reportes/detalle_empleado.html",
        {
            "empleado": empleado,
            "desde": desde,
            "hasta": hasta,
            "dias": dias,
            "totales": totales,
            "por_revisar": sum(1 for r in resultados if r.necesita_revision),
        },
    )


# --------------------------------------------------------------------------
# Excel
# --------------------------------------------------------------------------


def _resumen_excel(desde, hasta, filas, totales):
    columnas = ["Codigo", "Empleado", "Departamento", "Dias lab.", "Ausentes", "Por revisar"]
    columnas += [etiqueta for _, etiqueta in CAMPOS_MINUTOS]

    libro, hoja = exportar.hoja_nueva("Resumen")
    hoja["A1"] = f"Reporte de asistencia del {desde} al {hasta}"
    hoja["A1"].font = exportar.Font(bold=True, size=13)
    exportar.escribir_encabezado(hoja, columnas, fila=3)

    numero = 4
    for f in filas:
        for i, valor in enumerate(
            [f["codigo"], f["nombre"], f["departamento"],
             f["dias_laborados"], f["dias_ausente"], f["dias_revisar"]], start=1
        ):
            hoja.cell(row=numero, column=i, value=valor)
        for j, (campo, _) in enumerate(CAMPOS_MINUTOS, start=7):
            exportar.escribir_tiempo(hoja, numero, j, f[campo])
        numero += 1

    hoja.cell(row=numero, column=1, value="Totales").font = exportar.Font(bold=True)
    for j, (campo, _) in enumerate(CAMPOS_MINUTOS, start=7):
        exportar.escribir_tiempo(hoja, numero, j, totales[campo])

    exportar.ajustar_anchos(hoja, [12, 28, 18, 10, 10, 12] + [13] * len(CAMPOS_MINUTOS))
    return exportar.respuesta_excel(libro, f"asistencia-{desde}-{hasta}")


def _detalle_excel(empleado, desde, hasta, dias, totales):
    libro, hoja = exportar.hoja_nueva(empleado.codigo_planilla)
    hoja["A1"] = f"{empleado.codigo_planilla} - {empleado.nombre}"
    hoja["A1"].font = exportar.Font(bold=True, size=13)
    hoja["A2"] = f"Del {desde} al {hasta}"

    columnas = ["Fecha", "E1", "S1", "E2", "S2"]
    columnas += [etiqueta for _, etiqueta in CAMPOS_MINUTOS]
    columnas += ["Estado", "Observaciones"]
    exportar.escribir_encabezado(hoja, columnas, fila=4)

    numero = 5
    for d in dias:
        r = d["r"]
        celda = hoja.cell(row=numero, column=1, value=r.fecha)
        celda.number_format = "dd/mm/yyyy"
        for i, valor in enumerate([d["e1"], d["s1"], d["e2"], d["s2"]], start=2):
            hoja.cell(row=numero, column=i, value=valor or "")
        for j, (campo, _) in enumerate(CAMPOS_MINUTOS, start=6):
            exportar.escribir_tiempo(hoja, numero, j, getattr(r, campo))
        fin = 6 + len(CAMPOS_MINUTOS)
        hoja.cell(row=numero, column=fin, value=r.get_estado_display())
        hoja.cell(row=numero, column=fin + 1, value=" | ".join(r.observaciones))
        numero += 1

    hoja.cell(row=numero, column=1, value="Totales").font = exportar.Font(bold=True)
    for j, (campo, _) in enumerate(CAMPOS_MINUTOS, start=6):
        exportar.escribir_tiempo(hoja, numero, j, totales[campo])

    exportar.ajustar_anchos(
        hoja, [12, 8, 8, 8, 8] + [13] * len(CAMPOS_MINUTOS) + [14, 60]
    )
    return exportar.respuesta_excel(
        libro, f"detalle-{empleado.codigo_planilla}-{desde}"
    )
