from django.conf import settings
from django.db import models

from apps.core.models import Empleado

ESTADOS = [
    ("OK", "OK"),
    ("ADVERTENCIA", "advertencia"),
    ("INCONSISTENTE", "inconsistente"),
    ("AUSENTE", "ausente"),
    ("JUSTIFICADO", "justificado"),
    ("FERIADO", "feriado"),
    ("LIBRE", "libre"),
]

# Campos que, si cambian en un recalculo, invalidan una aceptacion previa.
CAMPOS_DE_MINUTOS = [
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


class ResultadoDiario(models.Model):
    """Resultado calculado de un dia. Se regenera entero en cada recalculo.

    No lleva bitacora de simple-history: no tiene sentido versionar algo que se
    reconstruye desde cero. Lo que si queda registrado es su aceptacion.
    """

    empleado = models.ForeignKey(
        Empleado, on_delete=models.CASCADE, related_name="resultados", verbose_name="empleado"
    )
    fecha = models.DateField("fecha", db_index=True)
    periodo = models.ForeignKey(
        "periodos.Periodo", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="resultados", verbose_name="periodo",
    )
    estado = models.CharField("estado", max_length=14, choices=ESTADOS, db_index=True)

    horario_snapshot = models.JSONField("horario esperado", default=list, blank=True)
    marcas_usadas = models.JSONField("marcas usadas", default=list, blank=True)

    minutos_esperados = models.IntegerField("esperados", default=0)
    minutos_trabajados = models.IntegerField("trabajados", default=0)
    minutos_ordinarios = models.IntegerField("ordinarios", default=0)
    minutos_extra = models.IntegerField("extra", default=0)
    minutos_tardia = models.IntegerField("tardia", default=0)
    minutos_salida_anticipada = models.IntegerField("salida anticipada", default=0)
    minutos_no_laborados = models.IntegerField("no laborados", default=0)
    minutos_fuera_horario = models.IntegerField("fuera de horario", default=0)
    minutos_feriado = models.IntegerField("feriado", default=0)
    minutos_descanso_trabajado = models.IntegerField("descanso trabajado", default=0)

    observaciones = models.JSONField("observaciones", default=list, blank=True)

    aceptado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="dias_aceptados", verbose_name="aceptado por",
    )
    aceptado_en = models.DateTimeField("aceptado en", null=True, blank=True)
    motivo_aceptacion = models.TextField("motivo de aceptacion", blank=True)

    calculado_en = models.DateTimeField("calculado en", auto_now=True)

    class Meta:
        verbose_name = "resultado diario"
        verbose_name_plural = "resultados diarios"
        ordering = ["fecha"]
        constraints = [
            models.UniqueConstraint(
                fields=["empleado", "fecha"], name="resultado_unico_por_empleado_y_dia"
            )
        ]
        indexes = [models.Index(fields=["empleado", "fecha"]), models.Index(fields=["estado"])]

    def __str__(self):
        return f"{self.empleado.codigo_planilla} {self.fecha} {self.estado}"

    @property
    def aceptado(self) -> bool:
        return self.aceptado_en is not None

    @property
    def es_pendiente(self) -> bool:
        """Requiere que alguien haga algo antes de poder cerrar el periodo."""
        if self.estado == "INCONSISTENTE":
            return True
        return self.estado == "ADVERTENCIA" and not self.aceptado

    def marcas_por_posicion(self) -> list[str]:
        """Las marcas usadas como E1, S1, E2, S2, para el reporte por empleado."""
        horas = [m["hora"] for m in self.marcas_usadas if not m.get("descartada_por_duplicado")]
        return (horas + ["", "", "", ""])[:4]
