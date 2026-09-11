"""Carga la lista real de empleados desde un CSV.

    python manage.py importar_empleados empleados.csv --simular
    python manage.py importar_empleados empleados.csv

Columnas del archivo (la primera fila son los nombres, en cualquier orden):

    codigo_planilla   obligatorio, es el identificador que usa planillas
    nombre            obligatorio
    departamento      obligatorio, se crea si no existe
    person_id         opcional, el PersonID de SmartPSS; se puede mapear despues
    identificacion    opcional, la cedula
    fecha_ingreso     opcional, AAAA-MM-DD; por defecto hoy
    horario           opcional, nombre exacto de un horario ya creado

El archivo se puede guardar desde Excel como "CSV UTF-8 (delimitado por comas)".
Correr primero con --simular: revisa todo y no escribe nada.
"""

import csv
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.models import Departamento, Empleado, Sucursal
from apps.horarios.models import AsignacionHorario, Horario

OBLIGATORIAS = ["codigo_planilla", "nombre", "departamento"]


class Command(BaseCommand):
    help = "Importa empleados desde un archivo CSV."

    def add_arguments(self, parser):
        parser.add_argument("archivo")
        parser.add_argument(
            "--simular", action="store_true",
            help="revisar el archivo sin escribir nada",
        )
        parser.add_argument(
            "--sucursal",
            help="codigo de agente de la sucursal; obligatorio si hay mas de una",
        )

    def handle(self, *args, **opciones):
        ruta = Path(opciones["archivo"])
        if not ruta.exists():
            raise CommandError(f"No existe el archivo {ruta}")

        sucursal = self._sucursal(opciones.get("sucursal"))
        filas = self._leer(ruta)
        self.stdout.write(f"{len(filas)} fila(s) en {ruta.name}, sucursal '{sucursal.nombre}'.")
        self.stdout.write("")

        problemas = []
        acciones = []
        vistos = set()
        horarios = {h.nombre.lower(): h for h in Horario.objects.all()}

        for numero, fila in enumerate(filas, start=2):
            codigo = (fila.get("codigo_planilla") or "").strip()
            nombre = (fila.get("nombre") or "").strip()
            departamento = (fila.get("departamento") or "").strip()

            if not codigo or not nombre or not departamento:
                problemas.append(f"  fila {numero}: falta codigo_planilla, nombre o departamento")
                continue
            if codigo in vistos:
                problemas.append(f"  fila {numero}: el codigo {codigo} esta repetido en el archivo")
                continue
            vistos.add(codigo)

            person_id = (fila.get("person_id") or "").strip() or None
            if person_id:
                ocupado = Empleado.objects.filter(person_id_smartpss=person_id).exclude(
                    codigo_planilla=codigo
                ).first()
                if ocupado:
                    problemas.append(
                        f"  fila {numero}: el PersonID {person_id} ya es de {ocupado.nombre}"
                    )
                    continue

            ingreso = (fila.get("fecha_ingreso") or "").strip()
            try:
                fecha_ingreso = date.fromisoformat(ingreso) if ingreso else timezone.localdate()
            except ValueError:
                problemas.append(f"  fila {numero}: fecha_ingreso '{ingreso}' no es AAAA-MM-DD")
                continue

            nombre_horario = (fila.get("horario") or "").strip()
            horario = horarios.get(nombre_horario.lower()) if nombre_horario else None
            if nombre_horario and horario is None:
                problemas.append(
                    f"  fila {numero}: no existe el horario '{nombre_horario}'. "
                    f"Disponibles: {', '.join(h.nombre for h in horarios.values()) or 'ninguno'}"
                )
                continue

            acciones.append({
                "codigo": codigo, "nombre": nombre, "departamento": departamento,
                "person_id": person_id,
                "identificacion": (fila.get("identificacion") or "").strip(),
                "fecha_ingreso": fecha_ingreso, "horario": horario,
                "existe": Empleado.objects.filter(codigo_planilla=codigo).exists(),
            })

        if problemas:
            self.stdout.write(self.style.ERROR(f"{len(problemas)} problema(s):"))
            for p in problemas:
                self.stdout.write(self.style.ERROR(p))
            self.stdout.write("")

        nuevos = [a for a in acciones if not a["existe"]]
        actualizados = [a for a in acciones if a["existe"]]
        sin_mapear = [a for a in acciones if not a["person_id"]]

        self.stdout.write(f"Se crearian    : {len(nuevos)}")
        self.stdout.write(f"Se actualizarian: {len(actualizados)}")
        if sin_mapear:
            self.stdout.write(self.style.WARNING(
                f"Sin PersonID    : {len(sin_mapear)} "
                "(se pueden mapear despues desde la ficha del empleado)"
            ))

        if problemas and not opciones["simular"]:
            raise CommandError("No se importo nada. Corrija el archivo y vuelva a intentar.")

        if opciones["simular"]:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(
                "Simulacion: no se escribio nada. Quite --simular para aplicar."
            ))
            return

        with transaction.atomic():
            departamentos = {}
            for accion in acciones:
                clave = accion["departamento"].lower()
                if clave not in departamentos:
                    departamentos[clave], _ = Departamento.objects.get_or_create(
                        nombre=accion["departamento"], sucursal=sucursal
                    )
                empleado, _ = Empleado.objects.update_or_create(
                    codigo_planilla=accion["codigo"],
                    defaults={
                        "nombre": accion["nombre"],
                        "identificacion": accion["identificacion"],
                        "person_id_smartpss": accion["person_id"],
                        "departamento": departamentos[clave],
                        "fecha_ingreso": accion["fecha_ingreso"],
                        "activo": True,
                    },
                )
                if accion["horario"] and not empleado.asignaciones.exists():
                    AsignacionHorario.objects.create(
                        empleado=empleado, horario=accion["horario"],
                        vigente_desde=accion["fecha_ingreso"],
                    )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Listo: {len(nuevos)} creado(s), {len(actualizados)} actualizado(s)."
        ))
        if sin_mapear:
            self.stdout.write(
                "Los que quedaron sin PersonID aparecen en rojo en el tablero hasta "
                "que se mapeen."
            )

    def _sucursal(self, codigo) -> Sucursal:
        if codigo:
            try:
                return Sucursal.objects.get(codigo_agente=codigo)
            except Sucursal.DoesNotExist:
                raise CommandError(f"No existe una sucursal con codigo de agente '{codigo}'.")
        sucursales = list(Sucursal.objects.all())
        if not sucursales:
            raise CommandError(
                "No hay ninguna sucursal. Cree una primero:\n"
                '  manage.py crear_sucursal --nombre "Oficina Central" '
                "--codigo-agente oficina-central"
            )
        if len(sucursales) > 1:
            raise CommandError(
                "Hay mas de una sucursal. Indique cual con --sucursal CODIGO. "
                f"Disponibles: {', '.join(s.codigo_agente for s in sucursales)}"
            )
        return sucursales[0]

    def _leer(self, ruta: Path) -> list[dict]:
        # Excel en Windows suele guardar con BOM; utf-8-sig se lo come sin quejarse.
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            lector = csv.DictReader(archivo)
            if lector.fieldnames is None:
                raise CommandError("El archivo esta vacio.")
            encabezados = {(c or "").strip().lower() for c in lector.fieldnames}
            faltantes = [c for c in OBLIGATORIAS if c not in encabezados]
            if faltantes:
                raise CommandError(
                    f"Al archivo le faltan columnas obligatorias: {', '.join(faltantes)}.\n"
                    f"Tiene: {', '.join(lector.fieldnames)}"
                )
            return [
                {(k or "").strip().lower(): v for k, v in fila.items()}
                for fila in lector
            ]
