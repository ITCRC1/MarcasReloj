import hashlib
import secrets

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

PREFIJO_VISIBLE = 12


def hash_api_key(clave: str) -> str:
    """SHA-256 de la clave.

    Las claves las genera el sistema con entropia alta, asi que no necesitan sal ni
    derivacion lenta. Sin sal el hash es indexable y la autenticacion es una sola
    consulta, en lugar de recorrer todas las filas ejecutando PBKDF2.
    Ver docs/decisiones-abiertas.md, punto 6.
    """
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def generar_api_key(prefijo: str) -> tuple[str, str, str]:
    """Devuelve (clave en claro, hash, prefijo visible). La clave no se vuelve a ver."""
    clave = f"{prefijo}_{secrets.token_urlsafe(32)}"
    return clave, hash_api_key(clave), clave[:PREFIJO_VISIBLE]


class Sucursal(models.Model):
    nombre = models.CharField("nombre", max_length=100)
    codigo_agente = models.CharField(
        "codigo del agente",
        max_length=50,
        unique=True,
        help_text="Debe coincidir con AGENTE_NOMBRE en el .env del agente.",
    )
    api_key_hash = models.CharField(max_length=64, unique=True, blank=True, db_index=True)
    api_key_prefijo = models.CharField(max_length=16, blank=True)
    ultima_sincronizacion = models.DateTimeField(
        "ultima sincronizacion", null=True, blank=True
    )
    activa = models.BooleanField("activa", default=True)

    class Meta:
        verbose_name = "sucursal"
        verbose_name_plural = "sucursales"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    def rotar_api_key(self) -> str:
        """Genera una clave nueva, guarda su hash y devuelve la clave en claro."""
        clave, hash_, prefijo = generar_api_key("ag")
        self.api_key_hash = hash_
        self.api_key_prefijo = prefijo
        self.save(update_fields=["api_key_hash", "api_key_prefijo"])
        return clave


class Departamento(models.Model):
    nombre = models.CharField("nombre", max_length=100)
    sucursal = models.ForeignKey(
        Sucursal, on_delete=models.PROTECT, related_name="departamentos",
        verbose_name="sucursal",
    )
    supervisores = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="departamentos_supervisados",
        verbose_name="supervisores",
    )

    class Meta:
        verbose_name = "departamento"
        verbose_name_plural = "departamentos"
        ordering = ["sucursal__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["sucursal", "nombre"], name="departamento_unico_por_sucursal"
            )
        ]

    def __str__(self):
        return f"{self.nombre} ({self.sucursal.nombre})"


class Empleado(models.Model):
    codigo_planilla = models.CharField(
        "codigo de planilla", max_length=30, unique=True,
        help_text="Identificador que usa el sistema de planillas. Nunca cambia.",
    )
    nombre = models.CharField("nombre", max_length=120)
    identificacion = models.CharField("identificacion", max_length=30, blank=True)
    person_id_smartpss = models.CharField(
        "PersonID en SmartPSS", max_length=30, unique=True, null=True, blank=True,
    )
    departamento = models.ForeignKey(
        Departamento, on_delete=models.PROTECT, related_name="empleados",
        verbose_name="departamento",
    )
    fecha_ingreso = models.DateField("fecha de ingreso")
    fecha_salida = models.DateField("fecha de salida", null=True, blank=True)
    activo = models.BooleanField("activo", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "empleado"
        verbose_name_plural = "empleados"
        ordering = ["nombre"]
        indexes = [models.Index(fields=["person_id_smartpss"])]

    def __str__(self):
        return f"{self.codigo_planilla} - {self.nombre}"

    @property
    def sucursal(self) -> Sucursal:
        return self.departamento.sucursal

    def trabajaba_en(self, fecha) -> bool:
        """Si la fecha cae dentro de su relacion laboral."""
        if fecha < self.fecha_ingreso:
            return False
        return self.fecha_salida is None or fecha <= self.fecha_salida
