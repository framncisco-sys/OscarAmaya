"""
Acciones sensibles en /app/: quien no sea superusuario de Django ni tenga rol
Administrador / Gerencia (perfil `usuarios.PerfilUsuario`) debe reautenticarse
(contraseña) para editar o eliminar.

La sesión de confirmación dura PBR_SENSITIVE_REAUTH_TTL segundos (por defecto 15 min)
y se renueva al guardar correctamente un formulario de edición.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib import messages
from django.forms import ValidationError
from django.db.models import ProtectedError
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

SESSION_KEY = "app_sensitive_ok_until"


def ttl_seconds() -> int:
    return int(getattr(settings, "PBR_SENSITIVE_REAUTH_TTL", 900))


def skips_sensitive_reauth(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        from usuarios.roles import salta_reautenticacion_sensible

        return salta_reautenticacion_sensible(user)
    except Exception:
        return False


def session_valid(request: HttpRequest) -> bool:
    until = request.session.get(SESSION_KEY)
    if until is None:
        return False
    try:
        return float(until) > time.time()
    except (TypeError, ValueError):
        return False


def grant(request: HttpRequest) -> None:
    request.session[SESSION_KEY] = time.time() + ttl_seconds()
    request.session.modified = True


def clear(request: HttpRequest) -> None:
    request.session.pop(SESSION_KEY, None)


def safe_next_url(request: HttpRequest, nxt: str | None) -> str:
    if not nxt:
        return reverse("app:index")
    if url_has_allowed_host_and_scheme(
        nxt,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return nxt
    return reverse("app:index")


def redirect_reauth(request: HttpRequest, next_url: str) -> HttpResponseRedirect:
    from urllib.parse import urlencode

    q = urlencode({"next": next_url})
    return HttpResponseRedirect(f"{reverse('app:sensitive_reauth')}?{q}")


def check_sensitive_write(request: HttpRequest) -> bool:
    """True si puede aplicar un guardado o borrado (superusuario, sesión o contraseña en POST)."""
    if not request.user.is_authenticated:
        return False
    if skips_sensitive_reauth(request.user):
        return True
    if session_valid(request):
        return True
    pwd = (request.POST.get("sensitive_password") or "").strip()
    if pwd and request.user.check_password(pwd):
        grant(request)
        return True
    return False


class SensitiveEditSessionMixin:
    """GET: redirige a confirmar contraseña. Contexto para mostrar campo si la sesión expiró. Renueva sesión al guardar."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.method == "GET":
            if not skips_sensitive_reauth(request.user) and not session_valid(request):
                return redirect_reauth(request, request.get_full_path())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        u = self.request.user
        ctx["sensitive_password_required"] = bool(
            u.is_authenticated and not skips_sensitive_reauth(u) and not session_valid(self.request)
        )
        return ctx

    def form_valid(self, form):
        resp = super().form_valid(form)
        if self.request.user.is_authenticated and not skips_sensitive_reauth(self.request.user):
            grant(self.request)
        return resp


class SensitiveEditMixin(SensitiveEditSessionMixin):
    """UpdateView estándar: valida contraseña en POST si la sesión de edición expiró."""

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().post(request, *args, **kwargs)
        self.object = self.get_object()
        form = self.get_form()
        if not form.is_valid():
            return self.form_invalid(form)
        if not check_sensitive_write(request):
            form.add_error(
                None,
                ValidationError(
                    "Debe ingresar su contraseña en «Confirmar contraseña» para guardar los cambios.",
                ),
            )
            return self.form_invalid(form)
        return self.form_valid(form)


class SensitiveDeleteMixin:
    """POST de eliminación: superusuario, sesión válida o contraseña en confirm_password."""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        u = self.request.user
        ctx["sensitive_delete_password"] = bool(
            u.is_authenticated and not skips_sensitive_reauth(u) and not session_valid(self.request)
        )
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if skips_sensitive_reauth(request.user) or session_valid(request):
            return self._delete_and_redirect()
        pwd = (request.POST.get("confirm_password") or "").strip()
        if pwd and request.user.check_password(pwd):
            grant(request)
            return self._delete_and_redirect()
        messages.error(
            request,
            "Contraseña incorrecta o falta indicarla para eliminar el registro.",
        )
        return self.render_to_response(self.get_context_data(object=self.object))

    def _delete_and_redirect(self):
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(
                self.request,
                "No se puede eliminar: existen registros vinculados (contratos, lotes, etc.).",
            )
            return HttpResponseRedirect(self.get_success_url())
        messages.success(self.request, "Registro eliminado.")
        return HttpResponseRedirect(self.get_success_url())
