from django.db import models


class Empleado(models.Model):
    """Quien es cada PersonID del reloj.

    El departamento es un campo de texto y no una tabla aparte: solo sirve para
    agrupar en el reporte, y una tabla para eso seria una pantalla mas que
    mantener a cambio de nada.
    """

    codigo_planilla = models.CharField(
        "codigo de planilla", max_length=30, unique=True,
        help_text="El identificador que usa planillas. Nunca cambia.",
    )
    nombre = models.CharField("nombre", max_length=120)
    identificacion = models.CharField("identificacion", max_length=30, blank=True)
    person_id_smartpss = models.CharField(
        "PersonID en SmartPSS", max_length=30, unique=True, null=True, blank=True,
        help_text="El numero con que el reloj identifica a esta persona.",
    )
    departamento = models.CharField("departamento", max_length=60, blank=True)
    horario = models.ForeignKey(
        "horarios.Horario", on_delete=models.PROTECT, related_name="empleados",
        null=True, blank=True, verbose_name="horario",
    )
    fecha_ingreso = models.DateField("fecha de ingreso")
    fecha_salida = models.DateField("fecha de salida", null=True, blank=True)
    activo = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "empleado"
        verbose_name_plural = "empleados"
        ordering = ["nombre"]
        indexes = [models.Index(fields=["person_id_smartpss"])]

    def __str__(self):
        return f"{self.codigo_planilla} - {self.nombre}"

    def trabajaba_en(self, fecha) -> bool:
        """Si la fecha cae dentro de su relacion laboral."""
        if fecha < self.fecha_ingreso:
            return False
        return self.fecha_salida is None or fecha <= self.fecha_salida
