"""Vistas SQL de la seccion 13.3.

Para sistemas de planillas que prefieren leer la base con un usuario de solo
lectura en lugar de consumir la API. Entregan lo mismo que
`/api/v1/periodos/{id}/resumen` y `/api/v1/periodos/{id}/detalle`.

El SQL se mantiene portable a proposito (sin FILTER, sin tipos propios de un
motor) para que funcione igual en SQLite, MySQL y PostgreSQL. Se usa
`SUM(CASE WHEN ... THEN 1 ELSE 0 END)` en vez de `COUNT(*) FILTER (...)`, que
MySQL no soporta.

El periodo se asocia por rango de fechas y no por `periodo_id`, porque ese campo
se puebla al calcular y podria estar en nulo si el periodo se creo despues. Los
periodos no se traslapan, asi que el rango da exactamente una fila.
"""

from django.db import migrations

MINUTOS = [
    "minutos_esperados",
    "minutos_trabajados",
    "minutos_ordinarios",
    "minutos_extra",
    "minutos_tardia",
    "minutos_salida_anticipada",
    "minutos_no_laborados",
    "minutos_fuera_horario",
    "minutos_feriado",
    "minutos_descanso_trabajado",
]

DETALLE = f"""
CREATE VIEW v_detalle_diario AS
SELECT
    r.id                        AS resultado_id,
    e.codigo_planilla           AS codigo_empleado,
    e.nombre                    AS empleado,
    d.nombre                    AS departamento,
    s.nombre                    AS sucursal,
    p.id                        AS periodo_id,
    p.nombre                    AS periodo,
    p.estado                    AS periodo_estado,
    r.fecha                     AS fecha,
    r.estado                    AS estado,
    {", ".join("r." + c for c in MINUTOS)},
    r.aceptado_en               AS aceptado_en,
    r.calculado_en              AS calculado_en
FROM motor_resultadodiario r
JOIN core_empleado e      ON e.id = r.empleado_id
JOIN core_departamento d  ON d.id = e.departamento_id
JOIN core_sucursal s      ON s.id = d.sucursal_id
LEFT JOIN periodos_periodo p ON r.fecha >= p.desde AND r.fecha <= p.hasta
"""

RESUMEN = f"""
CREATE VIEW v_resumen_periodo AS
SELECT
    p.id                AS periodo_id,
    p.nombre            AS periodo,
    p.estado            AS periodo_estado,
    p.desde             AS desde,
    p.hasta             AS hasta,
    e.codigo_planilla   AS codigo_empleado,
    e.nombre            AS empleado,
    d.nombre            AS departamento,
    SUM(CASE WHEN r.minutos_trabajados > 0 THEN 1 ELSE 0 END)   AS dias_laborados,
    SUM(CASE WHEN r.estado = 'AUSENTE' THEN 1 ELSE 0 END)       AS dias_ausente,
    SUM(CASE WHEN r.estado = 'JUSTIFICADO' THEN 1 ELSE 0 END)   AS dias_justificados,
    SUM(CASE WHEN r.estado = 'FERIADO' OR r.minutos_feriado > 0
             THEN 1 ELSE 0 END)                                 AS dias_feriado,
    SUM(CASE WHEN r.estado = 'INCONSISTENTE'
              OR (r.estado = 'ADVERTENCIA' AND r.aceptado_en IS NULL)
             THEN 1 ELSE 0 END)                                 AS dias_pendientes,
    {", ".join(f"SUM(r.{c}) AS {c}" for c in MINUTOS)},
    (SELECT COALESCE(SUM(a.minutos), 0)
       FROM periodos_ajuste a
      WHERE a.periodo_destino_id = p.id
        AND a.empleado_id = e.id)                               AS ajustes_minutos
FROM periodos_periodo p
JOIN motor_resultadodiario r ON r.fecha >= p.desde AND r.fecha <= p.hasta
JOIN core_empleado e         ON e.id = r.empleado_id
JOIN core_departamento d     ON d.id = e.departamento_id
GROUP BY p.id, p.nombre, p.estado, p.desde, p.hasta,
         e.id, e.codigo_planilla, e.nombre, d.nombre
"""


class Migration(migrations.Migration):
    dependencies = [
        ("periodos", "0001_initial"),
        ("motor", "0001_initial"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=DETALLE,
            reverse_sql="DROP VIEW IF EXISTS v_detalle_diario",
        ),
        migrations.RunSQL(
            sql=RESUMEN,
            reverse_sql="DROP VIEW IF EXISTS v_resumen_periodo",
        ),
    ]
