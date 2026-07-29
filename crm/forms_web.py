from django import forms

from inmobiliaria.phone_sv import aplicar_attrs_telefono, limpiar_telefono_formulario

from .models import HojaVisita, Lead, LeadActividad


class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplicar_attrs_telefono(self.fields.get("telefono"))

    def clean_telefono(self):
        return limpiar_telefono_formulario(self.cleaned_data.get("telefono"))


class LeadActividadForm(forms.ModelForm):
    class Meta:
        model = LeadActividad
        fields = ["tipo", "fecha", "resumen"]


class HojaVisitaForm(forms.ModelForm):
    class Meta:
        model = HojaVisita
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplicar_attrs_telefono(self.fields.get("telefono_interesado"))

    def clean_telefono_interesado(self):
        return limpiar_telefono_formulario(self.cleaned_data.get("telefono_interesado"))
