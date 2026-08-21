"""Aprobación / rechazo de cambio de precio en formato de aceptación."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.contrib.auth.models import AbstractUser
from django.utils import timezone

from audit.helpers import write_audit_log
from audit.models import AuditLog
from inmobiliaria.models import Contrato, FormatoAceptacion, Proyecto


def _decimal_str(v: Decimal | None) -> str | None:
    if v is None:
        return None
    return str(v.quantize(Decimal("0.01")))


def snapshot_precio_formato(fmt: FormatoAceptacion) -> dict[str, Any]:
    return {
        "numero_formulario": fmt.numero_formulario,
        "validacion_precio": fmt.validacion_precio,
        "valor_inmueble": _decimal_str(fmt.valor_inmueble),
        "valor_inmueble_sistema": _decimal_str(fmt.valor_inmueble_sistema),
        "valor_inmueble_solicitado": _decimal_str(fmt.valor_inmueble_solicitado),
        "precio_solicitud_motivo": fmt.precio_solicitud_motivo or "",
        "prima_1": _decimal_str(fmt.prima_1),
        "prima_2": _decimal_str(fmt.prima_2),
        "valor_financiamiento": _decimal_str(fmt.valor_financiamiento),
        "precio_validacion_nota": fmt.precio_validacion_nota or "",
    }


def _proyecto_desde_formato(fmt: FormatoAceptacion) -> Proyecto | None:
    nombre = (fmt.nombre_proyecto or "").strip()
    if not nombre:
        return None
    return (
        Proyecto.objects.filter(nombre__iexact=nombre, activo=True).first()
        or Proyecto.objects.filter(nombre__icontains=nombre, activo=True).first()
    )


def recalcular_montos_formato_por_valor(
    fmt: FormatoAceptacion, valor: Decimal
) -> list[str]:
    """Recalcula reserva, prima y financiamiento según % del proyecto."""
    campos: list[str] = []
    proy = _proyecto_desde_formato(fmt)
    valor_d = Decimal(valor).quantize(Decimal("0.01"))

    if proy is not None and proy.porcentaje_reserva is not None:
        fmt.prima_1 = (valor_d * Decimal(proy.porcentaje_reserva) / Decimal("100")).quantize(
            Decimal("0.01")
        )
        campos.append("prima_1")

    if (
        proy is not None
        and proy.porcentaje_prima is not None
        and fmt.prima_1 is not None
    ):
        prima_total = (valor_d * Decimal(proy.porcentaje_prima) / Decimal("100")).quantize(
            Decimal("0.01")
        )
        restante = (prima_total - fmt.prima_1).quantize(Decimal("0.01"))
        fmt.prima_2 = max(Decimal("0"), restante).quantize(Decimal("0.01"))
        campos.append("prima_2")

    p1 = fmt.prima_1 or Decimal("0")
    p2 = fmt.prima_2 or Decimal("0")
    if fmt.tipo_financiamiento != fmt.TipoFinanciamiento.CONTADO:
        fin = (valor_d - p1 - p2).quantize(Decimal("0.01"))
        fmt.valor_financiamiento = max(Decimal("0"), fin)
        campos.append("valor_financiamiento")
    return campos


def sincronizar_financiamiento_formato(fmt: FormatoAceptacion, *, persistir: bool = False) -> bool:
    """valor_financiamiento = valor_inmueble − reserva − prima (coherente con el formulario)."""
    from inmobiliaria.etapa_venta import decimales_iguales

    if fmt.valor_inmueble is None:
        return False
    if getattr(fmt, "tipo_financiamiento", None) == fmt.TipoFinanciamiento.CONTADO:
        return False
    p1 = fmt.prima_1 or Decimal("0")
    p2 = fmt.prima_2 or Decimal("0")
    esperado = (Decimal(fmt.valor_inmueble) - p1 - p2).quantize(Decimal("0.01"))
    if esperado < 0:
        esperado = Decimal("0")
    if fmt.valor_financiamiento is not None and decimales_iguales(fmt.valor_financiamiento, esperado):
        return False
    fmt.valor_financiamiento = esperado
    if persistir:
        fmt.save(update_fields=["valor_financiamiento", "actualizado_en"])
    return True


def asegurar_precio_vigente_formato(fmt: FormatoAceptacion, *, persistir: bool = False) -> bool:
    """
    Si el cambio ya está APROBADO pero valor_inmueble no coincide con lo solicitado, corrige.
    Devuelve True si hubo corrección en memoria o en BD.
    """
    from inmobiliaria.etapa_venta import decimales_iguales

    if fmt.validacion_precio != FormatoAceptacion.ValidacionPrecio.APROBADO:
        return False
    if fmt.valor_inmueble_solicitado is None:
        return False
    esperado = Decimal(fmt.valor_inmueble_solicitado).quantize(Decimal("0.01"))
    actual = fmt.valor_inmueble
    if actual is not None and decimales_iguales(actual, esperado):
        return False
    fmt.valor_inmueble = esperado
    extra = recalcular_montos_formato_por_valor(fmt, esperado)
    if persistir:
        fmt.save(update_fields=["valor_inmueble", *extra, "actualizado_en"])
        _sync_contrato_precio(fmt)
    return True


def precio_vigente_formato(fmt: FormatoAceptacion) -> Decimal | None:
    """Precio que debe usarse en cálculos, PDF y pantalla."""
    if fmt.validacion_precio == FormatoAceptacion.ValidacionPrecio.APROBADO:
        if fmt.valor_inmueble is not None:
            return Decimal(fmt.valor_inmueble).quantize(Decimal("0.01"))
        if fmt.valor_inmueble_solicitado is not None:
            return Decimal(fmt.valor_inmueble_solicitado).quantize(Decimal("0.01"))
    if fmt.pendiente_validacion_precio and fmt.valor_inmueble_sistema is not None:
        return Decimal(fmt.valor_inmueble_sistema).quantize(Decimal("0.01"))
    if fmt.valor_inmueble is not None:
        return Decimal(fmt.valor_inmueble).quantize(Decimal("0.01"))
    if fmt.valor_inmueble_sistema is not None:
        return Decimal(fmt.valor_inmueble_sistema).quantize(Decimal("0.01"))
    return None


def _sync_contrato_precio(fmt: FormatoAceptacion) -> None:
    if not fmt.contrato_id or fmt.valor_inmueble is None:
        return
    Contrato.objects.filter(pk=fmt.contrato_id).update(
        precio_final=fmt.valor_inmueble,
    )


def _audit_precio(
    *,
    fmt: FormatoAceptacion,
    user: AbstractUser,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    write_audit_log(
        action=AuditLog.Action.UPDATE,
        actor=user,
        app_label="inmobiliaria",
        model_name="formatoaceptacion",
        object_pk=str(fmt.pk),
        before=before,
        after=after,
    )


def aplicar_aprobacion_precio_formato(
    fmt: FormatoAceptacion,
    user: AbstractUser,
    *,
    nota: str,
) -> FormatoAceptacion:
    if not fmt.pendiente_validacion_precio:
        raise ValueError("El formato no tiene cambio de precio pendiente.")
    if fmt.valor_inmueble_solicitado is None:
        raise ValueError("No hay precio solicitado para aprobar.")

    before = snapshot_precio_formato(fmt)
    precio_aprobado = Decimal(fmt.valor_inmueble_solicitado).quantize(Decimal("0.01"))

    fmt.valor_inmueble = precio_aprobado
    fmt.validacion_precio = FormatoAceptacion.ValidacionPrecio.APROBADO
    fmt.precio_validado_por = user
    fmt.precio_validado_en = timezone.localtime()
    fmt.precio_validacion_nota = (nota or "Precio aprobado").strip()[:255]

    extra = recalcular_montos_formato_por_valor(fmt, precio_aprobado)
    update_fields = [
        "valor_inmueble",
        "validacion_precio",
        "precio_validado_por",
        "precio_validado_en",
        "precio_validacion_nota",
        *extra,
        "actualizado_en",
    ]
    fmt.save(update_fields=update_fields)
    _sync_contrato_precio(fmt)
    sincronizar_financiamiento_formato(fmt, persistir=True)
    _audit_precio(fmt=fmt, user=user, before=before, after=snapshot_precio_formato(fmt))
    return fmt


def aplicar_rechazo_precio_formato(
    fmt: FormatoAceptacion,
    user: AbstractUser,
    *,
    nota: str,
) -> FormatoAceptacion:
    if not fmt.pendiente_validacion_precio:
        raise ValueError("El formato no tiene cambio de precio pendiente.")
    if not (nota or "").strip():
        raise ValueError("Indique el motivo del rechazo.")

    before = snapshot_precio_formato(fmt)
    if fmt.valor_inmueble_sistema is not None:
        fmt.valor_inmueble = fmt.valor_inmueble_sistema
    fmt.validacion_precio = FormatoAceptacion.ValidacionPrecio.RECHAZADO
    fmt.precio_validado_por = user
    fmt.precio_validado_en = timezone.localtime()
    fmt.precio_validacion_nota = nota.strip()[:255]

    extra = []
    if fmt.valor_inmueble is not None:
        extra = recalcular_montos_formato_por_valor(fmt, fmt.valor_inmueble)

    fmt.save(
        update_fields=[
            "valor_inmueble",
            "validacion_precio",
            "precio_validado_por",
            "precio_validado_en",
            "precio_validacion_nota",
            *extra,
            "actualizado_en",
        ]
    )
    _sync_contrato_precio(fmt)
    _audit_precio(fmt=fmt, user=user, before=before, after=snapshot_precio_formato(fmt))
    return fmt
