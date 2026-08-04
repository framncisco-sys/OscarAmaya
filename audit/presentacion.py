"""Textos legibles del historial de actividad (para usuarios no técnicos)."""

from __future__ import annotations

from typing import Any

from django.apps import apps

# Etiquetas amigables cuando el modelo no tiene verbose_name útil o no carga.
_ETIQUETAS_MODELO: dict[tuple[str, str], str] = {
    ("inmobiliaria", "pago"): "Pago / recibo de abono",
    ("inmobiliaria", "formatoaceptacion"): "Formato de aceptación",
    ("inmobiliaria", "contrato"): "Plan de pagos / contrato",
    ("inmobiliaria", "cliente"): "Cliente",
    ("inmobiliaria", "inmueble"): "Lote / inmueble",
    ("inmobiliaria", "proyecto"): "Proyecto",
    ("inmobiliaria", "poligono"): "Polígono",
    ("inmobiliaria", "historialprecioinmueble"): "Cambio de precio de lote",
    ("inmobiliaria", "cuotaprogramada"): "Cuota programada",
    ("inmobiliaria", "vendedor"): "Asesor de ventas",
    ("inmobiliaria", "asesoralquiler"): "Asesor de alquiler",
    ("inmobiliaria", "recordatoriopago"): "Recordatorio de pago",
    ("inmobiliaria", "documentocliente"): "Documento del cliente",
    ("inmobiliaria", "imageninmueble"): "Foto de inmueble",
    ("inmobiliaria", "detallecasaventa"): "Detalle de casa en venta",
    ("inmobiliaria", "detallelocalalquiler"): "Detalle de local en alquiler",
    ("inmobiliaria", "detallecasaalquiler"): "Detalle de casa en alquiler",
    ("docs", "documentoemitido"): "Documento PDF emitido",
    ("docs", "correlativodocumento"): "Numeración de documentos",
    ("usuarios", "perfilusuario"): "Perfil de usuario",
    ("auth", "user"): "Usuario del sistema",
    ("crm", "lead"): "Prospecto / lead",
    ("crm", "hojavisita"): "Hoja de visita",
    ("audit", "auditlog"): "Registro de auditoría",
}

_ACCION_VERBO = {
    "CREATE": "Registró",
    "UPDATE": "Modificó",
    "DELETE": "Eliminó",
}

_ACCION_BADGE = {
    "CREATE": "Nuevo registro",
    "UPDATE": "Cambio",
    "DELETE": "Eliminación",
}

# Campos técnicos que no aportan al usuario final en el detalle.
_CAMPOS_OCULTOS = {
    "id",
    "pk",
    "password",
    "hash_sha256",
    "creado_en",
    "actualizado_en",
    "emitido_en",
}


def etiqueta_modelo(app_label: str, model_name: str) -> str:
    """Nombre del tipo de registro en español."""
    key = ((app_label or "").strip().lower(), (model_name or "").strip().lower())
    if key in _ETIQUETAS_MODELO:
        return _ETIQUETAS_MODELO[key]
    try:
        model = apps.get_model(app_label, model_name)
        label = str(model._meta.verbose_name or "").strip()
        if label:
            return label[:1].upper() + label[1:]
    except Exception:
        pass
    # Último recurso: separar camel/snake del nombre técnico.
    raw = (model_name or "registro").replace("_", " ")
    return raw[:1].upper() + raw[1:] if raw else "Registro"


def etiqueta_empresa(marca_slug: str | None) -> str:
    if not marca_slug:
        return "—"
    if marca_slug == "bienes-raices":
        return "Paredes Bienes Raíces"
    if marca_slug == "desarrollos":
        return "Paredes Desarrollos"
    return str(marca_slug)


def nombre_mostrar_actor(user) -> str:
    """
    Quién aparece en el historial:
    - Admin / superusuario → Oscar Rene Paredes
    - Gerente u otros → nombre registrado (nombre + apellido)
    """
    if not user:
        return "Sistema"
    try:
        from usuarios.roles import es_superusuario_o_admin_app

        if es_superusuario_o_admin_app(user):
            return "Oscar Rene Paredes"
    except Exception:
        if getattr(user, "is_superuser", False):
            return "Oscar Rene Paredes"
    nombre = (user.get_full_name() or "").strip()
    if not nombre:
        nombre = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
    if nombre:
        return nombre
    return user.get_username() or "Usuario"


def rol_mostrar_actor(user, actor_role_guardado: str = "") -> str:
    if actor_role_guardado:
        # Homogeneizar etiqueta de administrador.
        if "administrador" in actor_role_guardado.lower():
            return "Administrador"
        return actor_role_guardado
    if not user:
        return ""
    try:
        from usuarios.roles import obtener_perfil, es_superusuario_o_admin_app

        if es_superusuario_o_admin_app(user):
            return "Administrador"
        p = obtener_perfil(user)
        if p:
            return p.get_rol_display()
    except Exception:
        pass
    return ""


def accion_badge(action: str) -> str:
    return _ACCION_BADGE.get(action, action or "—")


def resumen_evento(*, action: str, app_label: str, model_name: str, object_pk: str) -> str:
    """Frase corta: «Registró un pago / recibo de abono (#1)»."""
    verbo = _ACCION_VERBO.get(action, "Registró actividad en")
    tipo = etiqueta_modelo(app_label, model_name)
    art = "una " if tipo[:1].lower() in "aeiouáéíóú" else "un "
    # Ajustes de género simples para etiquetas conocidas.
    if tipo.lower().startswith(("formato", "cuota", "foto", "hoja", "numeración", "eliminación")):
        art = "una "
    elif tipo.lower().startswith(("pago", "plan", "lote", "proyecto", "cliente", "contrato", "documento", "cambio", "perfil", "usuario", "prospecto", "recordatorio", "asesor", "detalle", "polígono")):
        art = "un "
    pk = (object_pk or "").strip()
    if pk:
        return f"{verbo} {art}{tipo} (n.º {pk})"
    return f"{verbo} {art}{tipo}"


def _etiqueta_campo(app_label: str, model_name: str, field_name: str) -> str:
    try:
        model = apps.get_model(app_label, model_name)
        field = model._meta.get_field(field_name)
        label = str(getattr(field, "verbose_name", "") or field_name).strip()
        return label[:1].upper() + label[1:] if label else field_name
    except Exception:
        return field_name.replace("_", " ").capitalize()


def _fmt_valor(val: Any) -> str:
    if val is None or val == "":
        return "— (vacío)"
    if isinstance(val, bool):
        return "Sí" if val else "No"
    if isinstance(val, (dict, list)):
        return str(val)[:200]
    s = str(val).strip()
    return s if s else "— (vacío)"


def cambios_legibles(
    *,
    action: str,
    app_label: str,
    model_name: str,
    before: Any,
    after: Any,
    max_items: int = 40,
) -> list[dict[str, str]]:
    """
    Lista de cambios {campo, antes, despues} en lenguaje claro.
    CREATE: solo valores nuevos; DELETE: solo valores anteriores; UPDATE: diferencias.
    """
    before_d = before if isinstance(before, dict) else {}
    after_d = after if isinstance(after, dict) else {}
    out: list[dict[str, str]] = []

    if action == "CREATE":
        keys = [k for k in after_d.keys() if k not in _CAMPOS_OCULTOS]
        for k in keys[:max_items]:
            out.append(
                {
                    "campo": _etiqueta_campo(app_label, model_name, k),
                    "antes": "—",
                    "despues": _fmt_valor(after_d.get(k)),
                }
            )
        return out

    if action == "DELETE":
        keys = [k for k in before_d.keys() if k not in _CAMPOS_OCULTOS]
        for k in keys[:max_items]:
            out.append(
                {
                    "campo": _etiqueta_campo(app_label, model_name, k),
                    "antes": _fmt_valor(before_d.get(k)),
                    "despues": "(eliminado)",
                }
            )
        return out

    # UPDATE
    keys = sorted(set(before_d) | set(after_d))
    for k in keys:
        if k in _CAMPOS_OCULTOS:
            continue
        a = before_d.get(k)
        b = after_d.get(k)
        if a == b:
            continue
        out.append(
            {
                "campo": _etiqueta_campo(app_label, model_name, k),
                "antes": _fmt_valor(a),
                "despues": _fmt_valor(b),
            }
        )
        if len(out) >= max_items:
            break
    return out


def enriquecer_log(log) -> dict[str, Any]:
    """Dict listo para plantillas a partir de un AuditLog."""
    actor = getattr(log, "actor", None)
    return {
        "quien": nombre_mostrar_actor(actor),
        "rol": rol_mostrar_actor(actor, getattr(log, "actor_role", "") or ""),
        "accion": accion_badge(log.action),
        "accion_codigo": log.action,
        "tipo": etiqueta_modelo(log.app_label, log.model_name),
        "empresa": etiqueta_empresa(getattr(log, "marca_slug", None)),
        "resumen": resumen_evento(
            action=log.action,
            app_label=log.app_label,
            model_name=log.model_name,
            object_pk=log.object_pk,
        ),
        "registro_id": log.object_pk,
    }
