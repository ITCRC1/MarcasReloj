from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import Empleado
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

# Limite semanal por tipo de jornada, en minutos. Solo genera advertencia.
LIMITE_JORNADA_MIN = {"diurna": 48 * 60, "mixta": 42 * 60, "nocturna": 36 * 60}


class Horario(models.Model):
    TIPOS = [("diurna", "diurna"), ("mixta", "mixta"), ("nocturna", "nocturna")]

    nombre = models.CharField("nombre", max_length=100, unique=True)
    tipo_jornada = models.CharField(
        "tipo de jornada", max_length=10, choices=TIPOS, default="diurna"
    )
    tolerancia_entrada_min = models.PositiveIntegerField("tolerancia de entrada", default=5)
    minimo_extra_min = models.PositiveIntegerField("minimo para extra", default=15)
    # No esta en la seccion 6, pero la seccion 20 lo lista como parametro del
    # sistema y el motor lo necesita. Vive aqui para que todos los parametros de
    # calculo esten en un solo lugar.
    ventana_duplicado_min = models.PositiveIntegerField("ventana de duplicados", default=5)
    contar_llegada_temprana = models.BooleanField("contar llegada temprana", default=False)
    activo = models.BooleanField("activo", default=True)

    history = HistoricalRecords()

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

    def excede_limite(self) -> bool:
        return self.minutos_semanales() > LIMITE_JORNADA_MIN[self.tipo_jornada]

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
    horario = models.ForeignKey(
        Horario, on_delete=models.CASCADE, related_name="bloques", verbose_name="horario"
    )
    dia_semana = models.IntegerField("dia de la semana", choices=DIAS_SEMANA)
    orden = models.PositiveSmallIntegerField(
        "orden", choices=[(1, "bloque 1"), (2, "bloque 2")]
    )
    hora_entrada = models.TimeField("hora de entrada")
    hora_salida = models.TimeField("hora de salida")

    history = HistoricalRecords()

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
        return f"{self.get_dia_semana_display()} {self.hora_entrada:%H:%M}-{self.hora_salida:%H:%M}"

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
                raise ValidationError({"orden": "No se puede crear el bloque 2 sin el bloque 1."})
            if self.hora_entrada <= primero.hora_salida:
                raise ValidationError(
                    {"hora_entrada": "El bloque 2 debe empezar despues de que termina el bloque 1."}
                )
            intermedio = (self.hora_entrada.hour * 60 + self.hora_entrada.minute) - (
                primero.hora_salida.hour * 60 + primero.hora_salida.minute
            )
            ventana = self.horario.ventana_duplicado_min
            if intermedio <= ventana:
                # Ver docs/decisiones-abiertas.md, punto 2: con un intermedio tan
                # corto la entrada del bloque 2 se descartaria por duplicado.
                raise ValidationError(
                    {"hora_entrada": f"El intermedio debe ser mayor que la ventana de "
                                     f"duplicados ({ventana} min); de lo contrario la entrada "
                                     f"del bloque 2 se descartaria como marca repetida."}
                )


class AsignacionHorario(models.Model):
    empleado = models.ForeignKey(
        Empleado, on_delete=models.CASCADE, related_name="asignaciones",
        verbose_name="empleado",
    )
    horario = models.ForeignKey(
        Horario, on_delete=models.PROTECT, related_name="asignaciones", verbose_name="horario"
    )
    vigente_desde = models.DateField("vigente desde")
    vigente_hasta = models.DateField("vigente hasta", null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "asignacion de horario"
        verbose_name_plural = "asignaciones de horario"
        ordering = ["empleado__nombre", "-vigente_desde"]

    def __str__(self):
        hasta = self.vigente_hasta or "indefinido"
        return f"{self.empleado.nombre}: {self.horario.nombre} ({self.vigente_desde} a {hasta})"

    def clean(self):
        if self.vigente_hasta and self.vigente_hasta < self.vigente_desde:
            raise ValidationError({"vigente_hasta": "No puede ser anterior al inicio."})
        if not self.empleado_id:
            return
        otras = AsignacionHorario.objects.filter(empleado=self.empleado).exclude(pk=self.pk)
        for otra in otras:
            fin_propio = self.vigente_hasta or None
            fin_otra = otra.vigente_hasta or None
            empieza_despues = fin_otra is not None and self.vigente_desde > fin_otra
            termina_antes = fin_propio is not None and fin_propio < otra.vigente_desde
            if not (empieza_despues or termina_antes):
                raise ValidationError(
                    f"Se traslapa con la asignacion vigente desde {otra.vigente_desde}."
                )


class Feriado(models.Model):
    fecha = models.DateField("fecha", unique=True)
    nombre = models.CharField("nombre", max_length=100)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "feriado"
        verbose_name_plural = "feriados"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.fecha} {self.nombre}"


class Justificacion(models.Model):
    TIPOS = [
        ("vacaciones", "vacaciones"),
        ("incapacidad", "incapacidad"),
        ("permiso_con_goce", "permiso con goce"),
        ("permiso_sin_goce", "permiso sin goce"),
        ("otro", "otro"),
    ]

    empleado = models.ForeignKey(
        Empleado, on_delete=models.CASCADE, related_name="justificaciones",
        verbose_name="empleado",
    )
    tipo = models.CharField("tipo", max_length=20, choices=TIPOS)
    desde = models.DateField("desde")
    hasta = models.DateField("hasta")
    detalle = models.TextField("detalle", blank=True)
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        verbose_name="registrada por",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "justificacion"
        verbose_name_plural = "justificaciones"
        ordering = ["-desde"]

    def __str__(self):
        return f"{self.empleado.nombre}: {self.tipo} {self.desde} a {self.hasta}"

    def clean(self):
        if self.hasta < self.desde:
            raise ValidationError({"hasta": "No puede ser anterior al inicio."})
