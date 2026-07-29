"""Formularios del catálogo de asesores — módulo de alquileres (independiente de ventas)."""

from django import forms

from .phone_sv import aplicar_attrs_telefono, limpiar_telefono_formulario
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
        aplicar_attrs_telefono(self.fields.get("telefono"))

    def clean_telefono(self):
        return limpiar_telefono_formulario(self.cleaned_data.get("telefono"))
