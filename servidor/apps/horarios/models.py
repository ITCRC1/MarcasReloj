from django.core.exceptions import ValidationError
from django.db import models

from apps.motor import calculo

DIAS_SEMANA = [
    (0, "lunes"),
    (1, "martes"),
    (2, "miercoles"),
    (3, "jueves"),
    (4, "viernes"),
    (5, "sabado"),
    (6, "domingo"),
]


class Horario(models.Model):
    """La jornada esperada. Sin esto no hay con que comparar las marcas.

    Los parametros de calculo viven aqui para que se puedan ajustar sin tocar
    codigo cuando RRHH confirme cuales son los suyos.
    """

    nombre = models.CharField("nombre", max_length=100, unique=True)
    tolerancia_entrada_min = models.PositiveIntegerField(
        "tolerancia de entrada", default=5,
        help_text="Minutos de atraso que se perdonan.",
    )
    minimo_extra_min = models.PositiveIntegerField(
        "minimo para extra", default=15,
        help_text="Desde cuantos minutos despues de la salida se cuenta extra.",
    )
    ventana_duplicado_min = models.PositiveIntegerField(
        "ventana de duplicados", default=5,
        help_text="Dos marcas mas juntas que esto se cuentan como una sola.",
    )
    contar_llegada_temprana = models.BooleanField(
        "contar llegada temprana", default=False,
        help_text="Si llegar antes de la hora se paga como extra.",
    )
    activo = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "horario"
        verbose_name_plural = "horarios"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    def parametros(self) -> calculo.Parametros:
        return calculo.Parametros(
            tolerancia_entrada_min=self.tolerancia_entrada_min,
            minimo_extra_min=self.minimo_extra_min,
            ventana_duplicado_min=self.ventana_duplicado_min,
            contar_llegada_temprana=self.contar_llegada_temprana,
        )

    def bloques_de(self, dia_semana: int) -> tuple[calculo.Bloque, ...]:
        return tuple(
            calculo.Bloque(entrada=b.hora_entrada, salida=b.hora_salida)
            for b in self.bloques.filter(dia_semana=dia_semana).order_by("orden")
        )

    def minutos_semanales(self) -> int:
        return sum(b.minutos() for b in self.bloques.all())

    def resumen_semanal(self):
        """[(dia, etiqueta, [bloques], minutos)] para la vista semanal."""
        por_dia = {d: [] for d, _ in DIAS_SEMANA}
        for b in self.bloques.all().order_by("dia_semana", "orden"):
            por_dia[b.dia_semana].append(b)
        return [
            (dia, etiqueta, por_dia[dia], sum(b.minutos() for b in por_dia[dia]))
            for dia, etiqueta in DIAS_SEMANA
        ]


class BloqueHorario(models.Model):
    """Un tramo de un dia. Dos bloques en un dia es horario partido; ninguno, libre."""

    horario = models.ForeignKey(
        Horario, on_delete=models.CASCADE, related_name="bloques", verbose_name="horario"
    )
    dia_semana = models.IntegerField("dia de la semana", choices=DIAS_SEMANA)
    orden = models.PositiveSmallIntegerField(
        "orden", choices=[(1, "bloque 1"), (2, "bloque 2")]
    )
    hora_entrada = models.TimeField("hora de entrada")
    hora_salida = models.TimeField("hora de salida")

    class Meta:
        verbose_name = "bloque de horario"
        verbose_name_plural = "bloques de horario"
        ordering = ["dia_semana", "orden"]
        constraints = [
            models.UniqueConstraint(
                fields=["horario", "dia_semana", "orden"], name="bloque_unico_por_dia"
            )
        ]

    def __str__(self):
        return (
            f"{self.get_dia_semana_display()} "
            f"{self.hora_entrada:%H:%M}-{self.hora_salida:%H:%M}"
        )

    def minutos(self) -> int:
        return (self.hora_salida.hour * 60 + self.hora_salida.minute) - (
            self.hora_entrada.hour * 60 + self.hora_entrada.minute
        )

    def clean(self):
        if self.hora_entrada >= self.hora_salida:
            raise ValidationError(
                {"hora_salida": "La salida debe ser posterior a la entrada. "
                                "Los turnos que cruzan la medianoche no estan soportados."}
            )
        if not self.horario_id:
            return
        hermanos = BloqueHorario.objects.filter(
            horario=self.horario, dia_semana=self.dia_semana
        ).exclude(pk=self.pk)
        if hermanos.count() >= 2:
            raise ValidationError("Un dia admite como maximo dos bloques.")
        if self.orden == 2:
            primero = hermanos.filter(orden=1).first()
            if primero is None:
                raise ValidationError(
                    {"orden": "No se puede crear el bloque 2 sin el bloque 1."}
                )
            if self.hora_entrada <= primero.hora_salida:
                raise ValidationError(
                    {"hora_entrada": "El bloque 2 debe empezar despues de que "
                                     "termina el bloque 1."}
                )
            intermedio = (self.hora_entrada.hour * 60 + self.hora_entrada.minute) - (
                primero.hora_salida.hour * 60 + primero.hora_salida.minute
            )
            ventana = self.horario.ventana_duplicado_min
            if intermedio <= ventana:
                raise ValidationError(
                    {"hora_entrada": f"El intermedio debe ser mayor que la ventana de "
                                     f"duplicados ({ventana} min); si no, la entrada del "
                                     f"bloque 2 se descartaria como marca repetida."}
                )


class Feriado(models.Model):
    """Dia de pago especial. Sin esta tabla, un feriado trabajado se paga mal.

    Se cargan a mano cada ano: algunos se trasladan por ley y no se pueden calcular.
    """

    fecha = models.DateField("fecha", unique=True)
    nombre = models.CharField("nombre", max_length=100)

    class Meta:
        verbose_name = "feriado"
        verbose_name_plural = "feriados"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.fecha} {self.nombre}"
