"""Carga un juego de datos completo para poder ver el sistema funcionando.

    python manage.py datos_demo

Crea sucursal, departamentos, usuarios de los cuatro roles, horarios, feriados,
empleados, marcas simuladas de varias semanas y tres periodos, uno de ellos cerrado.
Las marcas incluyen a proposito los casos interesantes: tardias, horas extra,
salidas anticipadas, un olvido de marca, una ausencia, trabajo en dia de descanso
y un PersonID sin mapear.

No usar en produccion: crea usuarios con claves conocidas.
"""

import random
from datetime import date, time, timedelta

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.api.models import ClienteAPI
from apps.core.models import Departamento, Empleado, Sucursal
from apps.core.tiempo import CR, datetime_local
from apps.horarios.models import AsignacionHorario, BloqueHorario, Feriado, Horario, Justificacion
from apps.marcas.models import MarcaManual, MarcaReloj
from apps.motor.servicio import recalcular_rango
from apps.periodos.models import Ajuste, Periodo
from apps.periodos.servicio import cerrar

CLAVE = "asistencia2026"

FERIADOS_2026 = [
    (date(2026, 1, 1), "Ano nuevo"),
    (date(2026, 4, 2), "Jueves santo"),
    (date(2026, 4, 3), "Viernes santo"),
    (date(2026, 4, 11), "Juan Santamaria"),
    (date(2026, 5, 1), "Dia del trabajador"),
    (date(2026, 7, 25), "Anexion del Partido de Nicoya"),
    (date(2026, 8, 2), "Virgen de los Angeles"),
    (date(2026, 8, 15), "Dia de la madre"),
    (date(2026, 9, 15), "Dia de la independencia"),
    (date(2026, 12, 1), "Abolicion del ejercito"),
    (date(2026, 12, 25), "Navidad"),
]

EMPLEADOS = [
    ("E-0042", "Maria Rodriguez", "1-0888-0777", "1024", "Administracion", "partido"),
    ("E-0043", "Jose Perez", "2-0555-0444", "1025", "Administracion", "partido"),
    ("E-0044", "Ana Chaves", "1-0333-0222", "1026", "Administracion", "partido"),
    ("E-0051", "Carlos Mora", "3-0111-0999", "1031", "Operaciones", "continuo"),
    ("E-0052", "Laura Vargas", "1-0777-0666", "1032", "Operaciones", "continuo"),
    ("E-0053", "Diego Solis", "2-0222-0111", None, "Operaciones", "continuo"),
]


class Command(BaseCommand):
    help = "Carga datos de demostracion completos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--borrar", action="store_true",
            help="Borra los datos anteriores antes de cargar.",
        )

    @transaction.atomic
    def handle(self, *args, **opciones):
        azar = random.Random(20260910)
        hoy = timezone.localdate()

        if opciones["borrar"]:
            self._borrar()

        sucursal = self._sucursal()
        departamentos = self._departamentos(sucursal)
        usuarios = self._usuarios(departamentos)
        horarios = self._horarios()
        self._feriados()
        empleados = self._empleados(departamentos, horarios)

        inicio = date(2026, 8, 1)
        self._marcas(sucursal, empleados, inicio, hoy, azar)
        self._casos_especiales(sucursal, empleados, usuarios, hoy)

        self.stdout.write("Recalculando...")
        guardados = recalcular_rango(inicio, hoy)
        self.stdout.write(f"  {guardados} dia(s) calculado(s).")

        self._periodos(usuarios["admin"], hoy)
        self._resumen(usuarios)

    # ----------------------------------------------------------------- datos

    def _borrar(self):
        self.stdout.write("Borrando datos anteriores...")
        from apps.motor.models import ResultadoDiario

        ResultadoDiario.objects.all().delete()
        Ajuste.objects.all().delete()
        Periodo.objects.all().delete()
        MarcaManual.objects.all().delete()
        MarcaReloj.objects.all().delete()
        Justificacion.objects.all().delete()
        AsignacionHorario.objects.all().delete()
        Empleado.objects.all().delete()
        BloqueHorario.objects.all().delete()
        Horario.objects.all().delete()
        Feriado.objects.all().delete()
        Departamento.objects.all().delete()
        Sucursal.objects.all().delete()
        ClienteAPI.objects.all().delete()

    def _sucursal(self) -> Sucursal:
        sucursal, _ = Sucursal.objects.get_or_create(
            codigo_agente="oficina-central", defaults={"nombre": "Oficina Central"}
        )
        clave = sucursal.rotar_api_key()
        sucursal.ultima_sincronizacion = timezone.now()
        sucursal.save()
        self.clave_agente = clave

        cliente, _ = ClienteAPI.objects.get_or_create(nombre="Sistema de planillas")
        self.clave_planillas = cliente.rotar_api_key()
        return sucursal

    def _departamentos(self, sucursal) -> dict:
        return {
            nombre: Departamento.objects.get_or_create(nombre=nombre, sucursal=sucursal)[0]
            for nombre in ("Administracion", "Operaciones")
        }

    def _usuarios(self, departamentos) -> dict:
        from apps.core.permisos import ADMINISTRADOR, CONSULTA, RRHH, SUPERVISOR

        for nombre in (ADMINISTRADOR, RRHH, SUPERVISOR, CONSULTA):
            Group.objects.get_or_create(name=nombre)

        def usuario(username, grupo, superusuario=False):
            u, creado = User.objects.get_or_create(
                username=username, defaults={"is_staff": superusuario, "is_superuser": superusuario}
            )
            if creado:
                u.set_password(CLAVE)
                u.is_staff = superusuario
                u.is_superuser = superusuario
                u.save()
            u.groups.set([Group.objects.get(name=grupo)])
            return u

        usuarios = {
            "admin": usuario("admin", ADMINISTRADOR, superusuario=True),
            "rrhh": usuario("rrhh", RRHH),
            "supervisor": usuario("supervisor", SUPERVISOR),
            "consulta": usuario("consulta", CONSULTA),
        }
        departamentos["Administracion"].supervisores.set([usuarios["supervisor"]])
        return usuarios

    def _horarios(self) -> dict:
        partido, creado = Horario.objects.get_or_create(
            nombre="Administrativo partido",
            defaults={"tipo_jornada": "diurna", "tolerancia_entrada_min": 5,
                      "minimo_extra_min": 15, "ventana_duplicado_min": 5},
        )
        if creado:
            for dia in range(0, 5):
                BloqueHorario.objects.create(
                    horario=partido, dia_semana=dia, orden=1,
                    hora_entrada=time(8, 0), hora_salida=time(12, 0))
                BloqueHorario.objects.create(
                    horario=partido, dia_semana=dia, orden=2,
                    hora_entrada=time(13, 0), hora_salida=time(17, 0))
            BloqueHorario.objects.create(
                horario=partido, dia_semana=5, orden=1,
                hora_entrada=time(8, 0), hora_salida=time(12, 0))

        continuo, creado = Horario.objects.get_or_create(
            nombre="Operativo continuo",
            defaults={"tipo_jornada": "diurna", "tolerancia_entrada_min": 10,
                      "minimo_extra_min": 30, "ventana_duplicado_min": 5},
        )
        if creado:
            for dia in range(0, 5):
                BloqueHorario.objects.create(
                    horario=continuo, dia_semana=dia, orden=1,
                    hora_entrada=time(6, 0), hora_salida=time(14, 0))
        return {"partido": partido, "continuo": continuo}

    def _feriados(self):
        for fecha, nombre in FERIADOS_2026:
            Feriado.objects.get_or_create(fecha=fecha, defaults={"nombre": nombre})

    def _empleados(self, departamentos, horarios) -> list:
        creados = []
        for codigo, nombre, cedula, person_id, departamento, horario in EMPLEADOS:
            empleado, _ = Empleado.objects.get_or_create(
                codigo_planilla=codigo,
                defaults={
                    "nombre": nombre,
                    "identificacion": cedula,
                    "person_id_smartpss": person_id,
                    "departamento": departamentos[departamento],
                    "fecha_ingreso": date(2024, 1, 15),
                },
            )
            AsignacionHorario.objects.get_or_create(
                empleado=empleado, horario=horarios[horario],
                defaults={"vigente_desde": date(2024, 1, 15)},
            )
            creados.append(empleado)
        return creados

    # ---------------------------------------------------------------- marcas

    def _marca(self, sucursal, empleado, momento, person_id=None, handler=""):
        utc_ms = int(momento.timestamp() * 1000)
        MarcaReloj.objects.get_or_create(
            sucursal=sucursal,
            person_id=person_id or empleado.person_id_smartpss or "",
            utc_ms=utc_ms,
            device_ip="192.168.1.201",
            defaults={
                "empleado": empleado,
                "person_name": empleado.nombre if empleado else "",
                "fecha_hora": momento,
                "fecha_local": momento.astimezone(CR).date(),
                "method": 3,
                "device_name": "Reloj Entrada",
                "handler": handler,
            },
        )

    def _marcas(self, sucursal, empleados, desde, hasta, azar):
        """Genera marcas realistas: casi siempre bien, a veces tarde o de mas."""
        self.stdout.write(f"Generando marcas del {desde} al {hasta}...")
        total = 0
        for empleado in empleados:
            if not empleado.person_id_smartpss:
                continue
            horario = empleado.asignaciones.first().horario
            dia = desde
            while dia <= hasta:
                bloques = horario.bloques_de(dia.weekday())
                if bloques and not (dia.month == 9 and dia.day == 3 and empleado.codigo_planilla == "E-0044"):
                    for bloque in bloques:
                        entrada = self._jitter(bloque.entrada, azar, -6, 14)
                        salida = self._jitter(bloque.salida, azar, -4, 12)
                        self._marca(sucursal, empleado, datetime_local(dia, entrada))
                        self._marca(sucursal, empleado, datetime_local(dia, salida))
                        total += 2
                dia += timedelta(days=1)
        self.stdout.write(f"  {total} marca(s) generadas.")

    @staticmethod
    def _jitter(hora: time, azar, minimo: int, maximo: int) -> time:
        minutos = hora.hour * 60 + hora.minute + azar.randint(minimo, maximo)
        minutos = max(0, min(minutos, 24 * 60 - 1))
        return time(minutos // 60, minutos % 60)

    def _casos_especiales(self, sucursal, empleados, usuarios, hoy):
        """Los casos que hacen interesante la pantalla de pendientes."""
        maria = Empleado.objects.get(codigo_planilla="E-0042")
        jose = Empleado.objects.get(codigo_planilla="E-0043")
        ana = Empleado.objects.get(codigo_planilla="E-0044")
        carlos = Empleado.objects.get(codigo_planilla="E-0051")

        # 1. Olvido de la salida: queda con 3 marcas, INCONSISTENTE.
        olvido = self._dia_habil_reciente(hoy, 2)
        MarcaReloj.objects.filter(empleado=maria, fecha_local=olvido).delete()
        for hora in (time(8, 1), time(12, 0), time(13, 2)):
            self._marca(sucursal, maria, datetime_local(olvido, hora))

        # 2. Marca manual pendiente de aprobacion, creada por el supervisor.
        MarcaManual.objects.get_or_create(
            empleado=maria,
            fecha_hora=datetime_local(olvido, time(17, 0)),
            defaults={
                "fecha_local": olvido,
                "motivo": "olvido",
                "detalle": "Salio a las 5:00 pm. Lo confirma el guarda de la entrada.",
                "estado": "pendiente",
                "creada_por": usuarios["supervisor"],
            },
        )

        # 3. Ausencia sin justificar.
        ausencia = self._dia_habil_reciente(hoy, 4)
        MarcaReloj.objects.filter(empleado=jose, fecha_local=ausencia).delete()

        # 4. Trabajo en domingo: todo va a descanso trabajado.
        domingo = hoy - timedelta(days=hoy.weekday() + 1)
        for hora in (time(8, 0), time(12, 0)):
            self._marca(sucursal, carlos, datetime_local(domingo, hora))

        # 5. Vacaciones de Ana: el dia queda JUSTIFICADO.
        Justificacion.objects.get_or_create(
            empleado=ana,
            desde=date(2026, 9, 3),
            hasta=date(2026, 9, 3),
            defaults={
                "tipo": "vacaciones",
                "detalle": "Un dia de vacaciones aprobado.",
                "registrada_por": usuarios["rrhh"],
            },
        )

        # 6. Marca modificada dentro de SmartPSS: genera alerta.
        modificada = self._dia_habil_reciente(hoy, 6)
        primera = MarcaReloj.objects.filter(empleado=jose, fecha_local=modificada).first()
        if primera:
            primera.handler = "operador_smartpss"
            primera.save(update_fields=["handler"])

        # 7. Un PersonID que nadie reclamo todavia.
        sin_duenio = self._dia_habil_reciente(hoy, 1)
        for hora in (time(7, 58), time(16, 5)):
            momento = datetime_local(sin_duenio, hora)
            MarcaReloj.objects.get_or_create(
                sucursal=sucursal, person_id="9999", utc_ms=int(momento.timestamp() * 1000),
                device_ip="192.168.1.201",
                defaults={
                    "empleado": None, "person_name": "Rodrigo Nunez",
                    "fecha_hora": momento, "fecha_local": sin_duenio,
                    "method": 1, "device_name": "Reloj Entrada",
                },
            )

    @staticmethod
    def _dia_habil_reciente(hoy: date, atras: int) -> date:
        """Un dia de semana `atras` dias habiles hacia atras desde ayer."""
        dia = hoy - timedelta(days=1)
        contados = 0
        while contados < atras:
            dia -= timedelta(days=1)
            if dia.weekday() < 5:
                contados += 1
        while dia.weekday() >= 5:
            dia -= timedelta(days=1)
        return dia

    # -------------------------------------------------------------- periodos

    def _periodos(self, admin, hoy):
        agosto_1, _ = Periodo.objects.get_or_create(
            nombre="Primera quincena de agosto 2026",
            defaults={"desde": date(2026, 8, 1), "hasta": date(2026, 8, 15)},
        )
        agosto_2, _ = Periodo.objects.get_or_create(
            nombre="Segunda quincena de agosto 2026",
            defaults={"desde": date(2026, 8, 16), "hasta": date(2026, 8, 31)},
        )
        Periodo.objects.get_or_create(
            nombre="Primera quincena de setiembre 2026",
            defaults={"desde": date(2026, 9, 1), "hasta": date(2026, 9, 15)},
        )

        if agosto_1.estado != "cerrado":
            try:
                cerrar(agosto_1, admin)
                self.stdout.write(self.style.SUCCESS(f"  Cerrado: {agosto_1.nombre}"))
            except ValueError as error:
                self.stdout.write(self.style.WARNING(f"  No se cerro agosto 1: {error}"))

        if agosto_2.estado == "abierto":
            agosto_2.estado = "en_revision"
            agosto_2.save()

        # Un ajuste que ilustra la correccion tardia de un periodo ya cerrado.
        Ajuste.objects.get_or_create(
            empleado=Empleado.objects.get(codigo_planilla="E-0042"),
            periodo_destino=agosto_2,
            fecha_original=date(2026, 8, 14),
            concepto="extra",
            defaults={
                "minutos": 60,
                "motivo": "Marca de salida recibida despues del cierre del periodo anterior.",
                "creado_por": admin,
            },
        )

    def _resumen(self, usuarios):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Datos de demostracion listos."))
        self.stdout.write("")
        self.stdout.write("  Usuarios (clave para todos: " + CLAVE + ")")
        for nombre in ("admin", "rrhh", "supervisor", "consulta"):
            self.stdout.write(f"    {nombre}")
        self.stdout.write("")
        self.stdout.write("  Clave de API del agente (X-API-Key):")
        self.stdout.write(f"    {self.clave_agente}")
        self.stdout.write("  Clave de API de planillas (X-API-Key):")
        self.stdout.write(f"    {self.clave_planillas}")
