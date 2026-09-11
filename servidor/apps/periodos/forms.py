from django import forms

from apps.core.forms import ControlesBootstrap
from apps.periodos.models import Ajuste, Periodo


class PeriodoForm(ControlesBootstrap):
    class Meta:
        model = Periodo
        fields = ["nombre", "desde", "hasta"]


class AjusteForm(ControlesBootstrap):
    class Meta:
        model = Ajuste
        fields = ["empleado", "fecha_original", "concepto", "minutos", "motivo"]
        widgets = {"motivo": forms.Textarea(attrs={"rows": 2})}
        help_texts = {
            "fecha_original": "Dia al que corresponde la correccion, aunque su periodo ya haya cerrado.",
            "minutos": "Positivo suma, negativo resta.",
        }
