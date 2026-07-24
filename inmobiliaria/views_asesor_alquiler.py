"""CRUD del catálogo de asesores — módulo de alquileres (independiente de vendedores de proyectos)."""

from django.contrib.auth.mixins import UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from core.sensitive_access import SensitiveDeleteMixin, SensitiveEditMixin
from usuarios.roles import puede_gestionar_vendedores

from .forms_asesor_alquiler import AsesorAlquilerForm
from .models import AsesorAlquiler
from .views_web import AppLoginRequiredMixin


class AsesoresAlquilerGestionMixin(AppLoginRequiredMixin, UserPassesTestMixin):
    login_url = reverse_lazy("login")

    def test_func(self) -> bool:
        return puede_gestionar_vendedores(self.request.user)


class AsesorAlquilerListView(AsesoresAlquilerGestionMixin, ListView):
    model = AsesorAlquiler
    template_name = "app/asesor_alquiler_list.html"
    context_object_name = "items"
    paginate_by = 30
    queryset = AsesorAlquiler.objects.all().order_by("apellidos", "nombres")


class AsesorAlquilerCreateView(AsesoresAlquilerGestionMixin, CreateView):
    model = AsesorAlquiler
    form_class = AsesorAlquilerForm
    template_name = "app/asesor_alquiler_form.html"
    success_url = reverse_lazy("app:asesor_alquiler_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo asesor de alquiler"
        ctx["cancel_url"] = reverse_lazy("app:asesor_alquiler_list")
        return ctx


class AsesorAlquilerUpdateView(AsesoresAlquilerGestionMixin, SensitiveEditMixin, UpdateView):
    model = AsesorAlquiler
    form_class = AsesorAlquilerForm
    template_name = "app/asesor_alquiler_form.html"
    success_url = reverse_lazy("app:asesor_alquiler_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = f"Editar asesor: {self.object.nombre_completo}"
        ctx["cancel_url"] = reverse_lazy("app:asesor_alquiler_list")
        return ctx


class AsesorAlquilerDeleteView(AsesoresAlquilerGestionMixin, SensitiveDeleteMixin, DeleteView):
    model = AsesorAlquiler
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:asesor_alquiler_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar asesor de alquiler"
        ctx["delete_blurb"] = (
            "Los recibos de comisión ya emitidos conservan el nombre guardado; "
            "no se borran documentos."
        )
        return ctx
