import csv

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.core import permisos
from apps.core.models import Empleado
from apps.core.tiempo import formato_hm
from apps.horarios.servicio import horario_vigente
from apps.motor.models import ResultadoDiario
from apps.periodos.models import Periodo
from apps.periodos.servicio import resumen_periodo
from apps.reportes import exportar

COLUMNAS_RESUMEN = [
    "Codigo", "Empleado", "Departamento", "Dias laborados", "Ausentes",
    "Justificados", "Feriados", "Esperado", "Ordinario", "Extra", "Feriado",
    "Descanso trab.", "Tardia", "Salida ant.", "No laborado", "Fuera de horario",
    "Ajustes (min)", "Pendientes",
]


@login_required
def indice(request):
    return render(
        request,
        "reportes/indice.html",
        {
            "periodos": Periodo.objects.all(),
            "empleados": permisos.empleados_visibles(request.user),
        },
    )


def _periodo_y_empleados(request, periodo_id):
    periodo = get_object_or_404(Periodo, pk=periodo_id)
    empleados = permisos.empleados_visibles(request.user)
    departamento = request.GET.get("departamento")
    if departamento:
        empleados = empleados.filter(departamento_id=departamento)
    return periodo, empleados


@login_required
def resumen(request, periodo_id):
    """Reporte 12.2: una fila por empleado con todos los totales del periodo."""
    periodo, empleados = _periodo_y_empleados(request, periodo_id)
    filas = resumen_periodo(periodo, empleados)
    for fila in filas:
        fila["ajustes_minutos"] = sum(a.minutos for a in fila["ajustes"])

    formato = request.GET.get("formato")
    if formato == "excel":
        return _resumen_excel(periodo, filas)
    if formato == "csv":
        return _resumen_csv(periodo, filas)

    totales = {
        campo: sum(f[campo] for f in filas)
        for campo in (
            "minutos_esperados", "minutos_ordinarios", "minutos_extra",
            "minutos_feriado", "minutos_descanso_trabajado", "minutos_tardia",
            "minutos_salida_anticipada", "minutos_no_laborados", "minutos_fuera_horario",
        )
    }
    return render(
        request,
        "reportes/resumen.html",
        {"periodo": periodo, "filas": filas, "totales": totales},
    )


def _fila_resumen(fila) -> list:
    return [
        fila["codigo_empleado"], fila["nombre"], fila["departamento"],
        fila["dias_laborados"], fila["dias_ausente"], fila["dias_justificados"],
        fila["dias_feriado"],
    ]


def _resumen_excel(periodo, filas):
    libro, hoja = exportar.hoja_nueva(f"Resumen {periodo.nombre}")
    hoja["A1"] = f"Resumen del periodo {periodo.nombre} ({periodo.desde} a {periodo.hasta})"
    hoja["A1"].font = exportar.Font(bold=True, size=13)
    exportar.escribir_encabezado(hoja, COLUMNAS_RESUMEN, fila=3)

    campos_tiempo = [
        "minutos_esperados", "minutos_ordinarios", "minutos_extra", "minutos_feriado",
        "minutos_descanso_trabajado", "minutos_tardia", "minutos_salida_anticipada",
        "minutos_no_laborados", "minutos_fuera_horario",
    ]
    numero = 4
    for fila in filas:
        for i, valor in enumerate(_fila_resumen(fila), start=1):
            hoja.cell(row=numero, column=i, value=valor)
        for j, campo in enumerate(campos_tiempo, start=8):
            exportar.escribir_tiempo(hoja, numero, j, fila[campo])
        hoja.cell(row=numero, column=17, value=fila["ajustes_minutos"])
        hoja.cell(row=numero, column=18, value=fila["dias_pendientes"])
        numero += 1

    exportar.ajustar_anchos(hoja, [12, 28, 18] + [12] * 15)
    return exportar.respuesta_excel(libro, f"resumen-{periodo.desde}-{periodo.hasta}")


def _resumen_csv(periodo, filas):
    respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = (
        f'attachment; filename="resumen-{periodo.desde}-{periodo.hasta}.csv"'
    )
    escritor = csv.writer(respuesta)
    escritor.writerow(
        [
            "codigo_empleado", "nombre", "departamento", "dias_laborados", "dias_ausente",
            "dias_justificados", "dias_feriado", "minutos_esperados", "minutos_ordinarios",
            "minutos_extra", "minutos_feriado", "minutos_descanso_trabajado",
            "minutos_tardia", "minutos_salida_anticipada", "minutos_no_laborados",
            "minutos_fuera_horario", "ajustes_minutos",
        ]
    )
    for fila in filas:
        escritor.writerow(
            _fila_resumen(fila)
            + [
                fila["minutos_esperados"], fila["minutos_ordinarios"], fila["minutos_extra"],
                fila["minutos_feriado"], fila["minutos_descanso_trabajado"],
                fila["minutos_tardia"], fila["minutos_salida_anticipada"],
                fila["minutos_no_laborados"], fila["minutos_fuera_horario"],
                fila["ajustes_minutos"],
            ]
        )
    return respuesta


@login_required
def detalle_empleado(request, periodo_id, codigo):
    """Reporte 12.1: una fila por dia, para revisar y para que el empleado firme."""
    periodo = get_object_or_404(Periodo, pk=periodo_id)
    empleado = get_object_or_404(Empleado, codigo_planilla=codigo)
    permisos.exigir_empleado_visible(request.user, empleado)

    resultados = ResultadoDiario.objects.filter(
        empleado=empleado, fecha__range=(periodo.desde, periodo.hasta)
    ).order_by("fecha")

    dias = []
    for r in resultados:
        e1, s1, e2, s2 = r.marcas_por_posicion()
        manuales = {
            m["hora"] for m in r.marcas_usadas if m.get("origen") == "manual"
        }
        dias.append({"r": r, "e1": e1, "s1": s1, "e2": e2, "s2": s2, "manuales": manuales})

    totales = resultados.aggregate(
        ordinarios=Sum("minutos_ordinarios"),
        extra=Sum("minutos_extra"),
        tardia=Sum("minutos_tardia"),
        no_laborados=Sum("minutos_no_laborados"),
        feriado=Sum("minutos_feriado"),
        descanso=Sum("minutos_descanso_trabajado"),
        fuera=Sum("minutos_fuera_horario"),
    )
    pendientes = sum(1 for r in resultados if r.es_pendiente)

    contexto = {
        "periodo": periodo,
        "empleado": empleado,
        "horario": horario_vigente(empleado, periodo.hasta),
        "dias": dias,
        "totales": {k: v or 0 for k, v in totales.items()},
        "pendientes": pendientes,
        "ajustes": periodo.ajustes.filter(empleado=empleado),
    }

    formato = request.GET.get("formato")
    if formato == "pdf":
        return exportar.respuesta_pdf(
            "reportes/detalle_empleado_pdf.html",
            contexto,
            f"detalle-{empleado.codigo_planilla}-{periodo.desde}",
        )
    if formato == "excel":
        return _detalle_excel(periodo, empleado, dias, contexto["totales"])
    return render(request, "reportes/detalle_empleado.html", contexto)


def _detalle_excel(periodo, empleado, dias, totales):
    libro, hoja = exportar.hoja_nueva(empleado.codigo_planilla)
    hoja["A1"] = f"{empleado.codigo_planilla} - {empleado.nombre}"
    hoja["A1"].font = exportar.Font(bold=True, size=13)
    hoja["A2"] = f"Periodo {periodo.nombre} ({periodo.desde} a {periodo.hasta})"
    exportar.escribir_encabezado(
        hoja,
        ["Fecha", "E1", "S1", "E2", "S2", "Ordinario", "Extra", "Tardia",
         "No laborado", "Fuera de horario", "Estado", "Observaciones"],
        fila=4,
    )
    numero = 5
    for d in dias:
        r = d["r"]
        hoja.cell(row=numero, column=1, value=r.fecha)
        hoja.cell(row=numero, column=1).number_format = "dd/mm/yyyy"
        for i, valor in enumerate([d["e1"], d["s1"], d["e2"], d["s2"]], start=2):
            hoja.cell(row=numero, column=i, value=valor or "")
        for j, campo in enumerate(
            ["minutos_ordinarios", "minutos_extra", "minutos_tardia",
             "minutos_no_laborados", "minutos_fuera_horario"],
            start=6,
        ):
            exportar.escribir_tiempo(hoja, numero, j, getattr(r, campo))
        hoja.cell(row=numero, column=11, value=r.estado)
        hoja.cell(row=numero, column=12, value=" | ".join(r.observaciones))
        numero += 1

    hoja.cell(row=numero, column=1, value="Totales").font = exportar.Font(bold=True)
    for j, campo in enumerate(
        ["ordinarios", "extra", "tardia", "no_laborados", "fuera"], start=6
    ):
        exportar.escribir_tiempo(hoja, numero, j, totales[campo])
    exportar.ajustar_anchos(hoja, [12, 8, 8, 8, 8, 12, 10, 10, 12, 14, 14, 60])
    return exportar.respuesta_excel(
        libro, f"detalle-{empleado.codigo_planilla}-{periodo.desde}"
    )


@login_required
def tardias(request, periodo_id):
    """Reporte 12.4: tardias y ausencias por empleado y departamento."""
    periodo, empleados = _periodo_y_empleados(request, periodo_id)
    filas = (
        ResultadoDiario.objects.filter(
            fecha__range=(periodo.desde, periodo.hasta), empleado__in=empleados
        )
        .values(
            "empleado__codigo_planilla",
            "empleado__nombre",
            "empleado__departamento__nombre",
        )
        .annotate(
            eventos_tardia=Count("pk", filter=Q(minutos_tardia__gt=0)),
            minutos_tardia=Sum("minutos_tardia"),
            eventos_ausencia=Count("pk", filter=Q(estado="AUSENTE")),
            minutos_no_laborados=Sum("minutos_no_laborados"),
            eventos_salida_anticipada=Count("pk", filter=Q(minutos_salida_anticipada__gt=0)),
        )
        .filter(Q(eventos_tardia__gt=0) | Q(eventos_ausencia__gt=0))
        .order_by("-minutos_tardia")
    )
    return render(
        request, "reportes/tardias.html", {"periodo": periodo, "filas": filas}
    )
