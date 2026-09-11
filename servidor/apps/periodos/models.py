from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import Empleado

CONCEPTOS_AJUSTE = [
    ("ordinarios", "ordinarios"),
    ("extra", "extra"),
    ("feriado", "feriado"),
    ("descanso_trabajado", "descanso trabajado"),
    ("tardia", "tardia"),
    ("no_laborados", "no laborados"),
]


class Periodo(models.Model):
    ESTADOS = [
        ("abierto", "abierto"),
        ("en_revision", "en revision"),
        ("cerrado", "cerrado"),
    ]

    nombre = models.CharField("nombre", max_length=100)
    desde = models.DateField("desde")
    hasta = models.DateField("hasta")
    estado = models.CharField("estado", max_length=12, choices=ESTADOS, default="abierto")
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="periodos_cerrados", verbose_name="cerrado por",
    )
    cerrado_en = models.DateTimeField("cerrado en", null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "periodo"
        verbose_name_plural = "periodos"
        ordering = ["-desde"]

    def __str__(self):
        return self.nombre

    @property
    def cerrado(self) -> bool:
        return self.estado == "cerrado"

    @property
    def admite_cambios(self) -> bool:
        """Si se pueden crear marcas manuales, anular marcas o aceptar advertencias."""
        return self.estado != "cerrado"

    def clean(self):
        if self.hasta < self.desde:
            raise ValidationError({"hasta": "La fecha final es anterior a la inicial."})
        traslape = Periodo.objects.exclude(pk=self.pk).filter(
            desde__lte=self.hasta, hasta__gte=self.desde
        )
        if traslape.exists():
            raise ValidationError(
                f"Se traslapa con el periodo '{traslape.first().nombre}'."
            )


class Ajuste(models.Model):
    """Correccion que no se puede hacer en el dia porque su periodo ya cerro.

    Se aplica en el periodo donde aparece, aunque su fecha original sea anterior.
    """

    empleado = models.ForeignKey(
        Empleado, on_delete=models.PROTECT, related_name="ajustes", verbose_name="empleado"
    )
    periodo_destino = models.ForeignKey(
        Periodo, on_delete=models.PROTECT, related_name="ajustes", verbose_name="periodo destino"
    )
    fecha_original = models.DateField("fecha original")
    concepto = models.CharField("concepto", max_length=20, choices=CONCEPTOS_AJUSTE)
    minutos = models.IntegerField("minutos", help_text="Puede ser negativo.")
    motivo = models.TextField("motivo")
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="creado por"
    )
    creado_en = models.DateTimeField("creado en", auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "ajuste"
        verbose_name_plural = "ajustes"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.empleado.codigo_planilla} {self.concepto} {self.minutos:+d} min"

    def clean(self):
        if self.periodo_destino_id and self.periodo_destino.estado == "cerrado":
            raise ValidationError(
                {"periodo_destino": "No se pueden registrar ajustes en un periodo cerrado."}
            )
        if self.minutos == 0:
            raise ValidationError({"minutos": "Un ajuste de cero minutos no tiene efecto."})
