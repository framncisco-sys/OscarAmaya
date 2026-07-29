"""Escritura de registros de auditoría y metadatos del actor (rol en la app)."""

from __future__ import annotations

import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder

from .context import get_request_context


def actor_app_role(user) -> str:
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    try:
        from usuarios.roles import obtener_perfil

        p = obtener_perfil(user)
        if p:
            return p.get_rol_display()
    except Exception:
        pass
    return ""


def _json_safe(data: Any) -> Any:
    if data is None:
        return None
    try:
        return json.loads(json.dumps(data, cls=DjangoJSONEncoder))
    except TypeError:
        return json.loads(json.dumps(data, default=str))


def snapshot_auth_user(user) -> dict:
    """Estado auditable del usuario Django + perfil de app (sin contraseña)."""
    out: dict = {
        "username": user.username,
        "email": user.email or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }
    p = getattr(user, "perfil_app", None)
    if p is not None:
        out["perfil_rol"] = p.rol
        out["perfil_empresa"] = getattr(p, "empresa", "") or ""
        out["perfil_telefono"] = p.telefono or ""
        out["perfil_activo_en_app"] = p.activo_en_app
        notas = p.notas or ""
        out["perfil_notas"] = notas[:500] + ("…" if len(notas) > 500 else "")
    return out


def write_audit_log(
    *,
    action: str,
    actor,
    app_label: str,
    model_name: str,
    object_pk: str,
    before: Any = None,
    after: Any = None,
) -> None:
    """Registra un evento (p. ej. usuario Django, que no dispara señales por exclusión de auth)."""
    try:
        from .models import AuditLog

        ctx = get_request_context()
        ip = getattr(ctx, "ip_address", None) if ctx else None
        ua = (getattr(ctx, "user_agent", None) or "") if ctx else ""
        rid = (getattr(ctx, "request_id", None) or "") if ctx else ""
        marca = (getattr(ctx, "marca_slug", None) or "") if ctx else ""
        act = actor if actor and getattr(actor, "is_authenticated", False) else None
        AuditLog.objects.create(
            action=action,
            actor=act,
            actor_role=actor_app_role(act) if act else "",
            app_label=app_label,
            model_name=model_name,
            object_pk=str(object_pk),
            before=_json_safe(before),
            after=_json_safe(after),
            ip_address=ip,
            user_agent=ua,
            request_id=rid,
            marca_slug=marca,
        )
    except Exception:
        return
