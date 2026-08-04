"""Listado y detalle de auditoría: administradores (todo) y gerencia (su empresa)."""

from __future__ import annotations

import json

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import DetailView, ListView

from core.marcas import MARCAS
from usuarios.roles import puede_ver_historial_auditoria, slug_filtro_auditoria

from .models import AuditLog
from .presentacion import cambios_legibles, enriquecer_log, etiqueta_empresa


class SoloAdministradorAuditoriaMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = reverse_lazy("login")

    def test_func(self) -> bool:
        return puede_ver_historial_auditoria(self.request.user)


class AuditLogListView(SoloAdministradorAuditoriaMixin, ListView):
    model = AuditLog
    template_name = "app/audit_log_list.html"
    context_object_name = "items"
    paginate_by = 50

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor").all()
        filtro_marca = slug_filtro_auditoria(self.request.user)
        if filtro_marca:
            qs = qs.filter(marca_slug=filtro_marca)
        else:
            marca_q = (self.request.GET.get("marca") or "").strip()
            if marca_q in MARCAS:
                qs = qs.filter(marca_slug=marca_q)
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(object_pk__icontains=q)
                | Q(model_name__icontains=q)
                | Q(app_label__icontains=q)
                | Q(actor__username__icontains=q)
                | Q(actor__first_name__icontains=q)
                | Q(actor__last_name__icontains=q)
                | Q(actor_role__icontains=q)
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
        ctx["filtro_marca_fijo"] = slug_filtro_auditoria(self.request.user)
        ctx["marcas_filtro"] = list(MARCAS.values())
        filas = []
        for row in ctx["items"]:
            info = enriquecer_log(row)
            info["row"] = row
            filas.append(info)
        ctx["filas"] = filas
        return ctx


class AuditLogDetailView(SoloAdministradorAuditoriaMixin, DetailView):
    model = AuditLog
    template_name = "app/audit_log_detail.html"
    context_object_name = "log"

    def get_queryset(self):
        qs = super().get_queryset().select_related("actor")
        filtro_marca = slug_filtro_auditoria(self.request.user)
        if filtro_marca:
            qs = qs.filter(marca_slug=filtro_marca)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        log: AuditLog = ctx["log"]
        info = enriquecer_log(log)
        ctx["info"] = info
        ctx["cambios"] = cambios_legibles(
            action=log.action,
            app_label=log.app_label,
            model_name=log.model_name,
            before=log.before,
            after=log.after,
        )
        ctx["marca_nombre"] = etiqueta_empresa(log.marca_slug)
        # JSON crudo solo como respaldo técnico (colapsado en plantilla).
        for key in ("before", "after"):
            raw = getattr(log, key)
            ctx[f"{key}_json"] = (
                json.dumps(raw, indent=2, ensure_ascii=False, default=str)
                if raw is not None
                else ""
            )
        return ctx
