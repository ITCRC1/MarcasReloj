"""Borra todos los datos de operacion para arrancar con los reales.

    python manage.py empezar_de_cero

Borra marcas, resultados, periodos, ajustes, empleados, horarios, feriados,
justificaciones, departamentos, sucursales y claves de API. **No** borra usuarios
ni grupos: sus cuentas de acceso se conservan.

Pide confirmacion escrita, porque no tiene vuelta atras.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

CONFIRMACION = "BORRAR TODO"


class Command(BaseCommand):
    help = "Borra los datos de operacion (incluidos los de demostracion)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--si", action="store_true",
            help="no preguntar (para usar dentro de un script)",
        )

    def handle(self, *args, **opciones):
        from apps.api.models import ClienteAPI
        from apps.core.models import Departamento, Empleado, Sucursal
        from apps.horarios.models import (
            AsignacionHorario, BloqueHorario, Feriado, Horario, Justificacion,
        )
        from apps.marcas.models import MarcaManual, MarcaReloj
        from apps.motor.models import ResultadoDiario
        from apps.periodos.models import Ajuste, Periodo

        # El orden importa: primero lo que apunta a otras cosas.
        modelos = [
            ("resultados diarios", ResultadoDiario),
            ("ajustes", Ajuste),
            ("periodos", Periodo),
            ("marcas manuales", MarcaManual),
            ("marcas del reloj", MarcaReloj),
            ("justificaciones", Justificacion),
            ("asignaciones de horario", AsignacionHorario),
            ("empleados", Empleado),
            ("bloques de horario", BloqueHorario),
            ("horarios", Horario),
            ("feriados", Feriado),
            ("departamentos", Departamento),
            ("sucursales", Sucursal),
            ("clientes de API", ClienteAPI),
        ]

        self.stdout.write("Se va a borrar:")
        total = 0
        for etiqueta, modelo in modelos:
            n = modelo.objects.count()
            total += n
            if n:
                self.stdout.write(f"  {n:>6}  {etiqueta}")
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No hay nada que borrar."))
            return

        self.stdout.write("")
        self.stdout.write("Los usuarios y los grupos NO se tocan.")
        self.stdout.write(self.style.WARNING("Esto no tiene vuelta atras."))

        if not opciones["si"]:
            self.stdout.write("")
            respuesta = input(f'Escriba "{CONFIRMACION}" para continuar: ')
            if respuesta.strip() != CONFIRMACION:
                self.stdout.write(self.style.ERROR("Cancelado. No se borro nada."))
                return

        with transaction.atomic():
            for etiqueta, modelo in modelos:
                borrados, _ = modelo.objects.all().delete()
                if borrados:
                    self.stdout.write(f"  borrados {borrados:>6}  {etiqueta}")
            # La bitacora de simple-history se borra aparte: son tablas propias.
            for _, modelo in modelos:
                historial = getattr(modelo, "history", None)
                if historial is not None:
                    historial.all().delete()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Base limpia. Siguientes pasos:"))
        self.stdout.write("  1. manage.py crear_sucursal --nombre \"Oficina Central\" --codigo-agente oficina-central")
        self.stdout.write("  2. manage.py importar_empleados empleados.csv")
        self.stdout.write("  3. Crear los horarios reales en la pantalla de Horarios")
        self.stdout.write("  4. Cargar los feriados del ano en la pantalla de Feriados")
