from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import Empleado, Sucursal
from apps.core.tiempo import a_local

MOTIVOS_MANUAL = [
    ("olvido", "olvido"),
    ("reloj_fuera_servicio", "reloj fuera de servicio"),
    ("trabajo_externo", "trabajo externo"),
    ("error_marca", "error de marca"),
    ("otro", "otro"),
]


class MarcaReloj(models.Model):
    """Una marca tal como llego de SmartPSS. Nunca se edita ni se borra: se anula."""

    sucursal = models.ForeignKey(
        Sucursal, on_delete=models.PROTECT, related_name="marcas", verbose_name="sucursal"
    )
    empleado = models.ForeignKey(
        Empleado, on_delete=models.PROTECT, related_name="marcas",
        null=True, blank=True, verbose_name="empleado",
    )
    person_id = models.CharField("PersonID", max_length=30, db_index=True)
    person_name = models.CharField("nombre en el reloj", max_length=60, blank=True)
    card_no = models.CharField("tarjeta", max_length=30, blank=True)

    utc_ms = models.BigIntegerField("hora UTC en milisegundos")
    fecha_hora = models.DateTimeField("fecha y hora")
    fecha_local = models.DateField("fecha local", db_index=True)

    state = models.IntegerField("AttendanceState", default=0)
    method = models.IntegerField("metodo", default=0)
    device_ip = models.CharField("IP del dispositivo", max_length=20, blank=True, default="")
    device_name = models.CharField("dispositivo", max_length=50, blank=True)
    snapshot_path = models.CharField("ruta de la foto", max_length=200, blank=True)
    handler = models.CharField("modificada en SmartPSS por", max_length=50, blank=True)
    remarks = models.CharField("observaciones del reloj", max_length=256, blank=True)

    recibida_en = models.DateTimeField("recibida en", auto_now_add=True)

    anulada = models.BooleanField("anulada", default=False)
    anulada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="marcas_anuladas", verbose_name="anulada por",
    )
    anulada_en = models.DateTimeField("anulada en", null=True, blank=True)
    motivo_anulacion = models.TextField("motivo de anulacion", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "marca del reloj"
        verbose_name_plural = "marcas del reloj"
        ordering = ["fecha_hora"]
        constraints = [
            models.UniqueConstraint(
                fields=["sucursal", "person_id", "utc_ms", "device_ip"],
                name="marca_unica_por_sucursal",
            )
        ]
        indexes = [
            models.Index(fields=["empleado", "fecha_local"]),
            models.Index(fields=["fecha_local"]),
        ]

    def __str__(self):
        return f"{self.person_id} {a_local(self.fecha_hora):%Y-%m-%d %H:%M}"

    @property
    def hora_local(self):
        return a_local(self.fecha_hora)

    @property
    def metodo_legible(self) -> str:
        return {0: "desconocido", 1: "tarjeta", 2: "huella", 3: "rostro", 4: "clave"}.get(
            self.method, str(self.method)
        )


class MarcaManual(models.Model):
    """Correccion explicita, con responsable y bitacora. No sustituye a la del reloj."""

    ESTADOS = [
        ("pendiente", "pendiente"),
        ("aprobada", "aprobada"),
        ("rechazada", "rechazada"),
        ("anulada", "anulada"),
    ]

    empleado = models.ForeignKey(
        Empleado, on_delete=models.PROTECT, related_name="marcas_manuales",
        verbose_name="empleado",
    )
    fecha_hora = models.DateTimeField("fecha y hora")
    fecha_local = models.DateField("fecha local", db_index=True)
    motivo = models.CharField("motivo", max_length=30, choices=MOTIVOS_MANUAL)
    detalle = models.TextField("detalle")
    estado = models.CharField("estado", max_length=12, choices=ESTADOS, default="pendiente")

    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="marcas_manuales_creadas", verbose_name="creada por",
    )
    creada_en = models.DateTimeField("creada en", auto_now_add=True)
    resuelta_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="marcas_manuales_resueltas", verbose_name="resuelta por",
    )
    resuelta_en = models.DateTimeField("resuelta en", null=True, blank=True)
    comentario_resolucion = models.TextField("comentario de resolucion", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "marca manual"
        verbose_name_plural = "marcas manuales"
        ordering = ["fecha_hora"]
        indexes = [models.Index(fields=["empleado", "fecha_local"])]

    def __str__(self):
        return f"{self.empleado.nombre} {a_local(self.fecha_hora):%Y-%m-%d %H:%M} ({self.estado})"

    @property
    def hora_local(self):
        return a_local(self.fecha_hora)
