"""Gestión de usuarios internos bajo /app/usuarios/ (solo gerencia y administradores de app)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import DeleteView, ListView

from audit.helpers import snapshot_auth_user, write_audit_log
from audit.models import AuditLog
from core.sensitive_access import SensitiveDeleteMixin

from .forms import UsuarioAppCrearForm, UsuarioAppEditarForm
from .models import PerfilUsuario
from .roles import (
    es_superusuario_o_admin_app,
    puede_gestionar_usuarios,
    slug_unica_permitida,
)

User = get_user_model()


def _es_admin_editor(user) -> bool:
    return es_superusuario_o_admin_app(user)


def _forzar_empresa_editor(user) -> str | None:
    """Gerencia solo puede crear/editar usuarios de su misma empresa."""
    if _es_admin_editor(user):
        return None
    return slug_unica_permitida(user)


class GestionUsuariosMixin(LoginRequiredMixin):
    """Solo superusuario o rol Administrador / Gerencia."""

    login_url = reverse_lazy("login")

    def dispatch(self, request, *args, **kwargs):
        if not puede_gestionar_usuarios(request.user):
            return HttpResponseForbidden(
                "No tiene permiso para gestionar usuarios. Se requiere rol Gerencia o Administrador de sistema.",
            )
        return super().dispatch(request, *args, **kwargs)


class UsuarioListView(GestionUsuariosMixin, ListView):
    model = User
    template_name = "app/usuario_list.html"
    context_object_name = "items"
    paginate_by = 30

    def get_queryset(self):
        qs = (
            User.objects.filter(
                Q(is_staff=True) | Q(is_superuser=True) | Q(perfil_app__isnull=False)
            )
            .distinct()
            .select_related("perfil_app")
            .order_by("username")
        )
        forzar = _forzar_empresa_editor(self.request.user)
        if forzar:
            qs = qs.filter(perfil_app__empresa=forzar).exclude(is_superuser=True)
        return qs


@login_required
def usuario_create(request: HttpRequest) -> HttpResponse:
    if not puede_gestionar_usuarios(request.user):
        return HttpResponseForbidden("Sin permiso para crear usuarios.")

    mostrar_interno = request.user.is_superuser
    es_admin = _es_admin_editor(request.user)
    forzar = _forzar_empresa_editor(request.user)
    if request.method == "POST":
        form = UsuarioAppCrearForm(
            request.POST,
            mostrar_acceso_interno=mostrar_interno,
            es_admin_editor=es_admin,
            forzar_empresa=forzar,
        )
        if form.is_valid():
            cd = form.cleaned_data
            activa = bool(cd.get("cuenta_activa", True))
            empresa = forzar or cd["empresa"]
            with transaction.atomic():
                u = User.objects.create_user(
                    username=cd["username"],
                    email=cd.get("email") or "",
                    password=cd["password1"],
                    first_name=cd.get("first_name") or "",
                    last_name=cd.get("last_name") or "",
                    is_staff=bool(cd.get("acceso_interno", False)) if mostrar_interno else False,
                    is_active=activa,
                )
                perfil, _ = PerfilUsuario.objects.get_or_create(user=u)
                perfil.rol = cd["rol"]
                perfil.empresa = empresa
                perfil.telefono = cd.get("telefono") or ""
                perfil.activo_en_app = activa
                perfil.save()
            u.refresh_from_db()
            perfil.refresh_from_db()
            write_audit_log(
                action=AuditLog.Action.CREATE,
                actor=request.user,
                app_label="auth",
                model_name="user",
                object_pk=str(u.pk),
                before=None,
                after=snapshot_auth_user(u),
            )
            if cd["rol"] == PerfilUsuario.Rol.VENTAS:
                messages.success(
                    request,
                    f"Usuario «{u.username}» creado. "
                    "Para el flujo de vendedor: vaya a Vendedores y asigne este usuario en «Usuario vínculo».",
                )
            else:
                messages.success(request, f"Usuario «{u.username}» creado.")
            return redirect("app:usuario_list")
    else:
        form = UsuarioAppCrearForm(
            mostrar_acceso_interno=mostrar_interno,
            es_admin_editor=es_admin,
            forzar_empresa=forzar,
            initial={"empresa": forzar or PerfilUsuario.Empresa.DESARROLLOS},
        )

    return render(
        request,
        "app/usuario_form.html",
        {
            "form_title": "Nuevo usuario",
            "form": form,
            "cancel_url": reverse("app:usuario_list"),
            "es_crear": True,
        },
    )


@login_required
def usuario_update(request: HttpRequest, pk: int) -> HttpResponse:
    if not puede_gestionar_usuarios(request.user):
        return HttpResponseForbidden("Sin permiso para editar usuarios.")

    user = get_object_or_404(User, pk=pk)
    if user.is_superuser and not request.user.is_superuser:
        return HttpResponseForbidden("Solo un superusuario puede editar a otro superusuario.")
    perfil, _ = PerfilUsuario.objects.get_or_create(user=user)
    forzar = _forzar_empresa_editor(request.user)
    if forzar and (perfil.empresa != forzar or user.is_superuser):
        return HttpResponseForbidden("Solo puede editar usuarios de su misma empresa.")
    mostrar_interno = request.user.is_superuser
    es_admin = _es_admin_editor(request.user)

    if request.method == "POST":
        form = UsuarioAppEditarForm(
            request.POST,
            mostrar_acceso_interno=mostrar_interno,
            es_admin_editor=es_admin,
            forzar_empresa=forzar,
        )
        if form.is_valid():
            cd = form.cleaned_data
            antes = snapshot_auth_user(user)
            activa = bool(cd.get("cuenta_activa"))
            user.email = cd.get("email") or ""
            user.first_name = cd.get("first_name") or ""
            user.last_name = cd.get("last_name") or ""
            user.is_active = activa
            if mostrar_interno:
                user.is_staff = bool(cd.get("acceso_interno"))
            p1 = cd.get("password1") or ""
            if p1:
                user.set_password(p1)
            user.save()
            perfil.rol = cd["rol"]
            perfil.empresa = forzar or cd["empresa"]
            perfil.telefono = cd.get("telefono") or ""
            perfil.notas = cd.get("notas") or ""
            perfil.activo_en_app = activa
            perfil.save()
            user.refresh_from_db()
            perfil.refresh_from_db()
            despues = snapshot_auth_user(user)
            if antes != despues or cd.get("password1"):
                write_audit_log(
                    action=AuditLog.Action.UPDATE,
                    actor=request.user,
                    app_label="auth",
                    model_name="user",
                    object_pk=str(user.pk),
                    before=antes,
                    after={**despues, "password_changed": bool(cd.get("password1"))},
                )
            messages.success(request, "Usuario actualizado.")
            return redirect("app:usuario_list")
    else:
        form = UsuarioAppEditarForm(
            initial={
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "rol": perfil.rol,
                "empresa": forzar or perfil.empresa,
                "telefono": perfil.telefono,
                "notas": perfil.notas,
                "cuenta_activa": bool(user.is_active and perfil.activo_en_app),
                "acceso_interno": user.is_staff,
            },
            mostrar_acceso_interno=mostrar_interno,
            es_admin_editor=es_admin,
            forzar_empresa=forzar,
        )

    return render(
        request,
        "app/usuario_form.html",
        {
            "form_title": f"Editar usuario: {user.username}",
            "form": form,
            "cancel_url": reverse("app:usuario_list"),
            "edit_user": user,
            "es_crear": False,
        },
    )


class UsuarioDeleteView(GestionUsuariosMixin, SensitiveDeleteMixin, DeleteView):
    """Elimina cuenta de usuario (perfil en cascada). Requiere contraseña si aplica política sensible."""

    model = User
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:usuario_list")

    def get_object(self, queryset=None):
        user = get_object_or_404(User, pk=self.kwargs["pk"])
        en_app = (
            user.is_staff
            or user.is_superuser
            or PerfilUsuario.objects.filter(user=user).exists()
        )
        if not en_app:
            raise PermissionDenied(
                "Este usuario no se gestiona desde esta pantalla.",
            )
        if user.pk == self.request.user.pk:
            raise PermissionDenied("No puede eliminar su propia cuenta.")
        if user.is_superuser and not self.request.user.is_superuser:
            raise PermissionDenied(
                "Solo un superusuario puede eliminar a otro superusuario.",
            )
        if user.is_superuser and User.objects.filter(is_superuser=True).count() <= 1:
            raise PermissionDenied(
                "No se puede eliminar el único superusuario del sistema.",
            )
        forzar = _forzar_empresa_editor(self.request.user)
        if forzar:
            perfil = getattr(user, "perfil_app", None)
            if not perfil or perfil.empresa != forzar:
                raise PermissionDenied("Solo puede eliminar usuarios de su misma empresa.")
        return user

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar usuario"
        ctx["delete_blurb"] = (
            "Quitará la cuenta del sistema. Si hay datos vinculados (contratos, documentos, etc.), "
            "la operación puede fallar o dejar referencias en null según la configuración."
        )
        return ctx

    def _delete_and_redirect(self):
        from django.db.models import ProtectedError
        from django.http import HttpResponseRedirect

        username = self.object.username
        pk = self.object.pk
        antes = snapshot_auth_user(self.object)
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(
                self.request,
                "No se puede eliminar: existen registros que requieren este usuario.",
            )
            return HttpResponseRedirect(str(self.success_url))
        write_audit_log(
            action=AuditLog.Action.DELETE,
            actor=self.request.user,
            app_label="auth",
            model_name="user",
            object_pk=str(pk),
            before=antes,
            after=None,
        )
        messages.success(self.request, f"Usuario «{username}» eliminado.")
        return HttpResponseRedirect(str(self.success_url))


@login_required
def usuario_roles_manual(request: HttpRequest) -> HttpResponse:
    if not puede_gestionar_usuarios(request.user):
        return HttpResponseForbidden("Sin permiso.")
    from .roles import descripcion_roles_para_manual

    return render(
        request,
        "app/usuario_roles_manual.html",
        {"bloques": descripcion_roles_para_manual()},
    )
