from apps.core.forms import ControlesBootstrap
from apps.horarios.models import BloqueHorario, Feriado, Horario


class HorarioForm(ControlesBootstrap):
    class Meta:
        model = Horario
        fields = [
            "nombre", "tolerancia_entrada_min", "minimo_extra_min",
            "ventana_duplicado_min", "contar_llegada_temprana", "activo",
        ]


class BloqueForm(ControlesBootstrap):
    class Meta:
        model = BloqueHorario
        fields = ["dia_semana", "orden", "hora_entrada", "hora_salida"]


class FeriadoForm(ControlesBootstrap):
    class Meta:
        model = Feriado
        fields = ["fecha", "nombre"]
