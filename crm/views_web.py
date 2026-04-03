from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from . import forms_web as forms
from .models import HojaVisita, Lead, LeadActividad


class AppLoginRequiredMixin(LoginRequiredMixin):
    login_url = reverse_lazy("login")


class LeadListView(AppLoginRequiredMixin, ListView):
    model = Lead
    template_name = "app/crm_lead_list.html"
    context_object_name = "items"
    paginate_by = 30

    def get_queryset(self):
        qs = super().get_queryset().select_related("asignado_a", "proyecto_interes", "poligono_interes", "inmueble_interes")
        estado = self.request.GET.get("estado")
        if estado:
            qs = qs.filter(estado_embudo=estado)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["estado"] = self.request.GET.get("estado", "")
        ctx["estados"] = Lead.EstadoEmbudo.choices
        return ctx


class LeadCreateView(AppLoginRequiredMixin, CreateView):
    model = Lead
    form_class = forms.LeadForm
    template_name = "app/object_form.html"
    success_url = reverse_lazy("app:crm_lead_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo lead"
        ctx["cancel_url"] = reverse_lazy("app:crm_lead_list")
        return ctx


class LeadUpdateView(AppLoginRequiredMixin, UpdateView):
    model = Lead
    form_class = forms.LeadForm
    template_name = "app/object_form.html"
    success_url = reverse_lazy("app:crm_lead_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar lead"
        ctx["cancel_url"] = reverse_lazy("app:crm_lead_list")
        return ctx


class LeadDetailView(AppLoginRequiredMixin, DetailView):
    model = Lead
    template_name = "app/crm_lead_detail.html"
    context_object_name = "lead"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["actividad_form"] = forms.LeadActividadForm(initial={"fecha": timezone.now()})
        ctx["visita_form"] = forms.HojaVisitaForm(initial={"fecha": timezone.now(), "lead": self.object})
        ctx["actividades"] = self.object.actividades.all()
        ctx["visitas"] = self.object.visitas.select_related("inmueble").all()
        return ctx


def lead_add_actividad(request, pk: int):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")
    lead = get_object_or_404(Lead, pk=pk)
    form = forms.LeadActividadForm(request.POST)
    if form.is_valid():
        obj: LeadActividad = form.save(commit=False)
        obj.lead = lead
        obj.creado_por = request.user
        obj.save()
    return redirect("app:crm_lead_detail", pk=lead.pk)


def lead_add_visita(request, pk: int):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")
    lead = get_object_or_404(Lead, pk=pk)
    form = forms.HojaVisitaForm(request.POST)
    if form.is_valid():
        obj: HojaVisita = form.save(commit=False)
        obj.lead = lead
        obj.creado_por = request.user
        obj.save()
    return redirect("app:crm_lead_detail", pk=lead.pk)

