"""Listado y detalle de auditoría: solo administrador de app o superusuario Django."""

from __future__ import annotations

import json

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import DetailView, ListView

from usuarios.roles import es_superusuario_o_admin_app

from .models import AuditLog


class SoloAdministradorAuditoriaMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = reverse_lazy("login")

    def test_func(self) -> bool:
        return es_superusuario_o_admin_app(self.request.user)


class AuditLogListView(SoloAdministradorAuditoriaMixin, ListView):
    model = AuditLog
    template_name = "app/audit_log_list.html"
    context_object_name = "items"
    paginate_by = 50

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor").all()
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(object_pk__icontains=q)
                | Q(model_name__icontains=q)
                | Q(app_label__icontains=q)
                | Q(actor__username__icontains=q)
            )
        actor_id = (self.request.GET.get("actor_id") or "").strip()
        if actor_id.isdigit():
            qs = qs.filter(actor_id=int(actor_id))
        act = (self.request.GET.get("action") or "").strip().upper()
        if act in {a for a, _ in AuditLog.Action.choices}:
            qs = qs.filter(action=act)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qd = self.request.GET.copy()
        qd.pop("page", None)
        ctx["pagination_query"] = qd.urlencode()
        return ctx


class AuditLogDetailView(SoloAdministradorAuditoriaMixin, DetailView):
    model = AuditLog
    template_name = "app/audit_log_detail.html"
    context_object_name = "log"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        log: AuditLog = ctx["log"]
        for key in ("before", "after"):
            raw = getattr(log, key)
            ctx[f"{key}_json"] = (
                json.dumps(raw, indent=2, ensure_ascii=False, default=str) if raw is not None else ""
            )
        return ctx
