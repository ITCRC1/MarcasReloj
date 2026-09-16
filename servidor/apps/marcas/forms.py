from django import forms

from apps.marcas.models import MOTIVOS_MANUAL


class MarcaManualForm(forms.Form):
    hora = forms.TimeField(
        label="Hora (formato 24 horas: 2 de la tarde es 14:00)",
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
    )
    motivo = forms.ChoiceField(
        label="Motivo", choices=MOTIVOS_MANUAL,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    detalle = forms.CharField(
        label="Detalle",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 2,
                   "placeholder": "Que paso y como se comprobo"}
        ),
    )

    def clean_detalle(self):
        detalle = self.cleaned_data["detalle"].strip()
        if not detalle:
            raise forms.ValidationError("El detalle es obligatorio.")
        return detalle


class MotivoForm(forms.Form):
    """Motivo obligatorio para anular, restaurar, rechazar o aceptar."""

    motivo = forms.CharField(
        label="Motivo",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )

    def clean_motivo(self):
        motivo = self.cleaned_data["motivo"].strip()
        if not motivo:
            raise forms.ValidationError("El motivo es obligatorio.")
        return motivo
