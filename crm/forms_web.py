from django import forms

from .models import HojaVisita, Lead, LeadActividad


class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = "__all__"


class LeadActividadForm(forms.ModelForm):
    class Meta:
        model = LeadActividad
        fields = ["tipo", "fecha", "resumen"]


class HojaVisitaForm(forms.ModelForm):
    class Meta:
        model = HojaVisita
        fields = "__all__"

