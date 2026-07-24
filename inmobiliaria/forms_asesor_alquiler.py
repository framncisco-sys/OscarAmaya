"""Formularios del catálogo de asesores — módulo de alquileres (independiente de ventas)."""

from django import forms

from .phone_sv import normalizar_guardado_telefono_sv
from .models import AsesorAlquiler


class AsesorAlquilerForm(forms.ModelForm):
    class Meta:
        model = AsesorAlquiler
        fields = [
            "nombres",
            "apellidos",
            "dui",
            "telefono",
            "email",
            "comision_arrendamiento_pct",
            "activo",
            "notas",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["comision_arrendamiento_pct"].widget.attrs.setdefault("step", "0.01")
        self.fields["comision_arrendamiento_pct"].widget.attrs.setdefault("min", "0")
        self.fields["comision_arrendamiento_pct"].widget.attrs.setdefault("max", "100")
        vt = self.fields.get("telefono")
        if vt:
            vt.widget.attrs.setdefault("maxlength", "40")
            vt.widget.attrs.setdefault("placeholder", "+503 7012 3456")
            vt.widget.attrs.setdefault("inputmode", "tel")
            vt.widget.attrs.setdefault("autocomplete", "tel")

    def clean_telefono(self):
        v = self.cleaned_data.get("telefono")
        if not v or not str(v).strip():
            return ""
        return normalizar_guardado_telefono_sv(v)
