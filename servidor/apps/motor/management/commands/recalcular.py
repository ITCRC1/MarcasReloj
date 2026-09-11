"""Recalculo masivo.

    python manage.py recalcular --desde 2026-09-01 --hasta 2026-09-15
    python manage.py recalcular --desde 2026-09-01 --hasta 2026-09-15 --empleado E-0042
    python manage.py recalcular --ayer

La opcion --ayer es la que corre la tarea diaria de las 00:30. Existe porque un
empleado sin marcas no dispara ningun evento y, sin ella, nunca apareceria AUSENTE.
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import Empleado
from apps.motor.servicio import recalcular_rango


class Command(BaseCommand):
    help = "Recalcula los resultados diarios de un rango de fechas."

    def add_arguments(self, parser):
        parser.add_argument("--desde", help="AAAA-MM-DD")
        parser.add_argument("--hasta", help="AAAA-MM-DD")
        parser.add_argument("--empleado", help="codigo de planilla")
        parser.add_argument(
            "--ayer", action="store_true", help="recalcula solo el dia de ayer"
        )

    def handle(self, *args, **opciones):
        if opciones["ayer"]:
            desde = hasta = timezone.localdate() - timedelta(days=1)
        else:
            if not opciones["desde"] or not opciones["hasta"]:
                raise CommandError("Indique --desde y --hasta, o use --ayer.")
            desde = date.fromisoformat(opciones["desde"])
            hasta = date.fromisoformat(opciones["hasta"])
        if hasta < desde:
            raise CommandError("La fecha final es anterior a la inicial.")

        empleados = Empleado.objects.filter(activo=True)
        if opciones["empleado"]:
            empleados = empleados.filter(codigo_planilla=opciones["empleado"])
            if not empleados.exists():
                raise CommandError(f"No existe el empleado {opciones['empleado']}.")

        guardados = recalcular_rango(desde, hasta, empleados)
        self.stdout.write(
            self.style.SUCCESS(
                f"Recalculado {desde} a {hasta} para {empleados.count()} empleado(s): "
                f"{guardados} dia(s) guardado(s)."
            )
        )
