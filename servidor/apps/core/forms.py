from django import forms

from apps.core.models import Empleado


class ControlesBootstrap(forms.ModelForm):
    """Aplica las clases de Bootstrap a todos los campos, sin repetirlas en cada uno."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")
            if isinstance(widget, forms.DateInput):
                widget.input_type = "date"
            if isinstance(widget, forms.TimeInput):
                widget.input_type = "time"


class EmpleadoForm(ControlesBootstrap):
    class Meta:
        model = Empleado
        fields = [
            "codigo_planilla", "nombre", "identificacion", "departamento",
            "fecha_ingreso", "fecha_salida", "activo",
        ]


class MapeoForm(forms.Form):
    person_id = forms.CharField(
        label="PersonID en SmartPSS",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "1024"}),
    )
