from datetime import date

from ninja import Schema


class MarcaEntrada(Schema):
    person_id: str
    person_name: str = ""
    card_no: str = ""
    utc_ms: int
    state: int = 0
    method: int = 0
    device_ip: str = ""
    device_name: str = ""
    snapshot_path: str = ""
    handler: str = ""
    remarks: str = ""


class LoteEntrada(Schema):
    agente: str
    enviado_en: str | None = None
    marcas: list[MarcaEntrada] = []


class LoteRespuesta(Schema):
    recibidas: int
    nuevas: int
    duplicadas: int
    sin_empleado: int


class SaludRespuesta(Schema):
    estado: str
    version: str
    hora_servidor: str


class EmpleadoSalida(Schema):
    codigo_empleado: str
    nombre: str
    identificacion: str = ""
    departamento: str
    sucursal: str
    activo: bool
    fecha_ingreso: date
    fecha_salida: date | None = None


class PeriodoSalida(Schema):
    id: int
    nombre: str
    desde: date
    hasta: date
    estado: str


class AjusteSalida(Schema):
    concepto: str
    minutos: int
    fecha_original: date
    motivo: str
    codigo_empleado: str | None = None


class EmpleadoResumen(Schema):
    codigo_empleado: str
    nombre: str
    tipo_jornada: str
    dias_laborados: int
    dias_ausente: int
    dias_justificados: int
    dias_feriado: int
    minutos_esperados: int
    minutos_ordinarios: int
    minutos_extra: int
    minutos_feriado: int
    minutos_descanso_trabajado: int
    minutos_tardia: int
    minutos_salida_anticipada: int
    minutos_no_laborados: int
    minutos_fuera_horario: int
    ajustes: list[AjusteSalida] = []


class ResumenSalida(Schema):
    periodo: PeriodoSalida
    empleados: list[EmpleadoResumen]


class MarcaSalida(Schema):
    hora: str
    origen: str


class DiaSalida(Schema):
    fecha: date
    estado: str
    marcas: list[MarcaSalida]
    minutos_esperados: int
    minutos_ordinarios: int
    minutos_extra: int
    minutos_tardia: int
    minutos_salida_anticipada: int
    minutos_no_laborados: int
    minutos_fuera_horario: int
    minutos_feriado: int
    minutos_descanso_trabajado: int
    observaciones: list[str] = []


class DetalleSalida(Schema):
    periodo: PeriodoSalida
    codigo_empleado: str
    nombre: str
    dias: list[DiaSalida]


class Error(Schema):
    detalle: str
