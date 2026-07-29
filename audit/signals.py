from __future__ import annotations

import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.forms.models import model_to_dict

from .context import get_request_context
from .helpers import actor_app_role
from .models import AuditLog

EXCLUDED_APP_LABELS = {"admin", "auth", "contenttypes", "sessions"}
# Evita duplicar líneas al guardar usuario + perfil en el mismo formulario (auth.user se audita a mano).
EXCLUDED_MODEL_NAMES = frozenset({"perfilusuario"})


def _serialize_instance(instance: Any) -> dict[str, Any]:
    data = model_to_dict(instance)
    # Intenta incluir PK si no viene en model_to_dict
    pk_name = getattr(instance._meta, "pk", None)
    if pk_name and pk_name.name not in data:
        data[pk_name.name] = instance.pk
    # Asegura JSON serializable (datetime/date/Decimal/UUID/etc.)
    try:
        return json.loads(json.dumps(data, cls=DjangoJSONEncoder))
    except TypeError:
        # Fallback ultra defensivo para que auditoría no rompa flujo principal.
        return json.loads(json.dumps(data, default=str))


@receiver(pre_save)
def audit_pre_save(sender, instance, **kwargs):
    if sender is AuditLog:
        return
    if getattr(sender._meta, "model_name", "") in EXCLUDED_MODEL_NAMES:
        return
    if getattr(sender._meta, "app_label", "") in EXCLUDED_APP_LABELS:
        return
    # Evitar ruido de migraciones/sesiones si no hay request
    ctx = get_request_context()
    if ctx is None:
        return
    if not instance.pk:
        return
    try:
        old = sender.objects.filter(pk=instance.pk).first()
        if old is not None:
            instance.__audit_before__ = _serialize_instance(old)  # type: ignore[attr-defined]
    except Exception:
        return


@receiver(post_save)
def audit_post_save(sender, instance, created: bool, **kwargs):
    if sender is AuditLog:
        return
    if getattr(sender._meta, "model_name", "") in EXCLUDED_MODEL_NAMES:
        return
    if getattr(sender._meta, "app_label", "") in EXCLUDED_APP_LABELS:
        return
    ctx = get_request_context()
    if ctx is None:
        return

    actor = None
    try:
        from django.contrib.auth import get_user_model

        if ctx.user_id:
            actor = get_user_model().objects.filter(id=ctx.user_id).first()
    except Exception:
        actor = None

    before = getattr(instance, "__audit_before__", None)
    after = _serialize_instance(instance)

    try:
        AuditLog.objects.create(
            action=AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
            actor=actor,
            actor_role=actor_app_role(actor),
            app_label=instance._meta.app_label,
            model_name=instance._meta.model_name,
            object_pk=str(instance.pk),
            before=before if not created else None,
            after=after,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent or "",
            request_id=ctx.request_id or "",
            marca_slug=getattr(ctx, "marca_slug", "") or "",
        )
    except Exception:
        # Nunca bloquear la operación principal por fallo de auditoría.
        return


@receiver(post_delete)
def audit_post_delete(sender, instance, **kwargs):
    if sender is AuditLog:
        return
    if getattr(sender._meta, "model_name", "") in EXCLUDED_MODEL_NAMES:
        return
    if getattr(sender._meta, "app_label", "") in EXCLUDED_APP_LABELS:
        return
    ctx = get_request_context()
    if ctx is None:
        return

    actor = None
    try:
        from django.contrib.auth import get_user_model

        if ctx.user_id:
            actor = get_user_model().objects.filter(id=ctx.user_id).first()
    except Exception:
        actor = None

    before = None
    try:
        before = _serialize_instance(instance)
    except Exception:
        before = None

    try:
        AuditLog.objects.create(
            action=AuditLog.Action.DELETE,
            actor=actor,
            actor_role=actor_app_role(actor),
            app_label=instance._meta.app_label,
            model_name=instance._meta.model_name,
            object_pk=str(instance.pk),
            before=before,
            after=None,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent or "",
            request_id=ctx.request_id or "",
            marca_slug=getattr(ctx, "marca_slug", "") or "",
        )
    except Exception:
        return

