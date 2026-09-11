from django.db import models

from apps.core.models import Empleado

ESTADOS = [
    ("OK", "OK"),
    ("ADVERTENCIA", "advertencia"),
    ("INCONSISTENTE", "inconsistente"),
    ("AUSENTE", "ausente"),
    ("FERIADO", "feriado"),
    ("LIBRE", "libre"),
]


class ResultadoDiario(models.Model):
    """El calculo de un dia. Es la fila del reporte.

    Se regenera entera cada vez que algo del dia cambia, asi que nunca se edita
    a mano: lo que se corrige son las marcas, y el resultado se rehace solo.
    """

    empleado = models.ForeignKey(
        Empleado, on_delete=models.CASCADE, related_name="resultados",
        verbose_name="empleado",
    )
    fecha = models.DateField("fecha", db_index=True)
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
        indexes = [models.Index(fields=["empleado", "fecha"])]

    def __str__(self):
        return f"{self.empleado.codigo_planilla} {self.fecha} {self.estado}"

    @property
    def necesita_revision(self) -> bool:
        return self.estado in ("INCONSISTENTE", "ADVERTENCIA")

    def marcas_por_posicion(self) -> list[str]:
        """Las marcas usadas como E1, S1, E2, S2, para el reporte."""
        horas = [
            m["hora"] for m in self.marcas_usadas
            if not m.get("descartada_por_duplicado")
        ]
        return (horas + ["", "", "", ""])[:4]
