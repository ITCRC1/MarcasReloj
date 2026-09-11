from django import forms

from apps.core.forms import ControlesBootstrap
from apps.horarios.models import (
    AsignacionHorario,
    BloqueHorario,
    Feriado,
    Horario,
    Justificacion,
)


class HorarioForm(ControlesBootstrap):
    class Meta:
        model = Horario
        fields = [
            "nombre", "tipo_jornada", "tolerancia_entrada_min", "minimo_extra_min",
            "ventana_duplicado_min", "contar_llegada_temprana", "activo",
        ]


class BloqueForm(ControlesBootstrap):
    class Meta:
        model = BloqueHorario
        fields = ["dia_semana", "orden", "hora_entrada", "hora_salida"]


class AsignacionForm(ControlesBootstrap):
    class Meta:
        model = AsignacionHorario
        fields = ["empleado", "horario", "vigente_desde", "vigente_hasta"]


class FeriadoForm(ControlesBootstrap):
    class Meta:
        model = Feriado
        fields = ["fecha", "nombre"]


class JustificacionForm(ControlesBootstrap):
    class Meta:
        model = Justificacion
        fields = ["empleado", "tipo", "desde", "hasta", "detalle"]
        widgets = {"detalle": forms.Textarea(attrs={"rows": 2})}
