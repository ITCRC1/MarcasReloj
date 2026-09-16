"""Arma el dia de cada persona directamente de sus marcas, sin horario.

Es lo que pide el reporte: una fila por dia con las marcas en columnas (E1, S1,
E2, S2...), las horas trabajadas y lo que haya que revisar. No hace falta tener
empleados ni horarios creados; eso se suma despues para tardias y extras.

El reloj no distingue entrada de salida (su propio informe dice "Entrada/salida"
en todas), asi que las marcas se emparejan por orden: 1a entrada, 2a salida, 3a
entrada, 4a salida. Las repetidas se descartan con la misma regla del motor.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from apps.motor import calculo

VENTANA_DUPLICADO_MIN = calculo.Parametros().ventana_duplicado_min


@dataclass
class Dia:
    fecha: date
    pares: list[tuple[calculo.Marca, calculo.Marca | None]]
    minutos: int
    repetidas: int

    @property
    def completo(self) -> bool:
        return all(salida is not None for _, salida in self.pares)

    @property
    def observacion(self) -> str:
        partes = []
        if not self.completo:
            entrada = self.pares[-1][0].hora.astimezone(calculo.CR)
            partes.append(f"Falta la salida de las {entrada:%H:%M}")
        manuales = sum(
            1 for par in self.pares for m in par
            if m is not None and m.origen == calculo.MANUAL
        )
        if manuales:
            partes.append(f"{manuales} marca(s) manual(es)")
        if self.repetidas:
            partes.append(f"{self.repetidas} marca(s) repetida(s) no cuentan")
        return ". ".join(partes)


@dataclass
class Persona:
    clave: str
    person_id: str
    nombre: str
    codigo: str = ""
    dias: list[Dia] = field(default_factory=list)

    @property
    def minutos(self) -> int:
        return sum(d.minutos for d in self.dias)

    @property
    def incompletos(self) -> int:
        return sum(1 for d in self.dias if not d.completo)


def armar_dia(fecha: date, marcas: list[calculo.Marca]) -> Dia:
    """Ordena, quita repetidas, empareja por posicion y suma lo trabajado."""
    ordenadas = sorted(marcas, key=lambda m: m.hora)
    # La regla de repetidas es la del motor, para que el reporte y el calculo
    # nunca cuenten distinto el mismo dia.
    usadas, repetidas = calculo._quitar_duplicados(ordenadas, VENTANA_DUPLICADO_MIN)
    pares = [
        (usadas[i], usadas[i + 1] if i + 1 < len(usadas) else None)
        for i in range(0, len(usadas), 2)
    ]
    minutos = sum(
        max(0, calculo._minutos_de_marca(salida) - calculo._minutos_de_marca(entrada))
        for entrada, salida in pares
        if salida is not None
    )
    return Dia(fecha=fecha, pares=pares, minutos=minutos, repetidas=len(repetidas))


def armar_personas(marcas_reloj, marcas_manuales) -> list[Persona]:
    """Agrupa por persona y por dia. Recibe querysets ya filtrados por fecha."""
    personas: dict[str, Persona] = {}
    por_dia: dict[str, dict[date, list[calculo.Marca]]] = defaultdict(lambda: defaultdict(list))

    for m in marcas_reloj:
        clave = m.person_id
        if clave not in personas:
            empleado = m.empleado
            personas[clave] = Persona(
                clave=clave,
                person_id=m.person_id,
                nombre=empleado.nombre if empleado else m.person_name,
                codigo=empleado.codigo_planilla if empleado else "",
            )
        por_dia[clave][m.fecha_local].append(
            calculo.Marca(hora=m.fecha_hora, origen=calculo.RELOJ, ref_id=m.pk)
        )

    for m in marcas_manuales:
        empleado = m.empleado
        clave = empleado.person_id_smartpss or f"empleado-{empleado.pk}"
        if clave not in personas:
            personas[clave] = Persona(
                clave=clave,
                person_id=empleado.person_id_smartpss or "",
                nombre=empleado.nombre,
                codigo=empleado.codigo_planilla,
            )
        por_dia[clave][m.fecha_local].append(
            calculo.Marca(
                hora=m.fecha_hora, origen=calculo.MANUAL, ref_id=m.pk,
                motivo=m.get_motivo_display(),
            )
        )

    for clave, dias in por_dia.items():
        personas[clave].dias = [armar_dia(f, dias[f]) for f in sorted(dias)]

    return sorted(personas.values(), key=lambda p: p.nombre.upper())


def columnas_de_marcas(personas: list[Persona]) -> int:
    """Cuantos pares de columnas hacen falta. Minimo dos: E1 S1 E2 S2."""
    return max([2] + [len(d.pares) for p in personas for d in p.dias])
