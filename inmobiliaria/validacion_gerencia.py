"""Validación de gerencia/admin sobre el flujo de venta (formato, plan, pagos)."""

from __future__ import annotations

from django.utils import timezone

from inmobiliaria.models import Contrato, FormatoAceptacion, Pago
from usuarios.roles import (
    puede_validar_flujo_venta,
    requiere_validacion_formato_y_plan,
    requiere_validacion_gerencia,
)


def marcar_sin_cola_formato_o_plan(obj) -> None:
    """Formato/plan sin cola (asesor u otros roles que no son Proyectos)."""
    if hasattr(obj, "validacion_gerencia"):
        obj.validacion_gerencia = obj.ValidacionGerencia.NO_APLICA
        obj.validado_gerencia_por = None
        obj.validado_gerencia_en = None
        obj.validacion_gerencia_nota = ""


def aplicar_validacion_formato_o_plan(obj, user) -> bool:
    """
    Rol Proyectos, lotes y mapa: formato y plan quedan PENDIENTE.
    Admin/gerencia: VALIDADO. Asesor y demás: NO_APLICA (sin cola).
    Devuelve True si quedó pendiente.
    """
    if not hasattr(obj, "validacion_gerencia"):
        return False
    if puede_validar_flujo_venta(user):
        obj.validacion_gerencia = obj.ValidacionGerencia.VALIDADO
        obj.validado_gerencia_por = user
        obj.validado_gerencia_en = timezone.now()
        if not (getattr(obj, "validacion_gerencia_nota", None) or "").strip():
            obj.validacion_gerencia_nota = "Registrado por admin/gerencia"
        return False
    if requiere_validacion_formato_y_plan(user):
        obj.validacion_gerencia = obj.ValidacionGerencia.PENDIENTE
        obj.validado_gerencia_por = None
        obj.validado_gerencia_en = None
        if isinstance(obj, Contrato):
            obj.estado = Contrato.Estado.BORRADOR
        return True
    marcar_sin_cola_formato_o_plan(obj)
    return False


def marcar_pendiente_si_operador(obj, user) -> bool:
    """Compat: en formato/contrato usa aplicar_validacion_formato_o_plan."""
    from inmobiliaria.models import Contrato, FormatoAceptacion

    if isinstance(obj, (FormatoAceptacion, Contrato)):
        return aplicar_validacion_formato_o_plan(obj, user)
    if not requiere_validacion_gerencia(user):
        obj.validacion_gerencia = obj.ValidacionGerencia.VALIDADO
        obj.validado_gerencia_por = user
        obj.validado_gerencia_en = timezone.now()
        if not (getattr(obj, "validacion_gerencia_nota", None) or "").strip():
            obj.validacion_gerencia_nota = "Registrado por admin/gerencia"
        return False
    obj.validacion_gerencia = obj.ValidacionGerencia.PENDIENTE
    obj.validado_gerencia_por = None
    obj.validado_gerencia_en = None
    return True


def aplicar_validacion_pago_al_guardar(pago: Pago, user) -> bool:
    """
    Al crear/editar abono del flujo: admin/gerencia deja VALIDADO;
    operador deja PENDIENTE. Devuelve True si quedó pendiente.
    """
    if pago.concepto not in Pago.CONCEPTOS_CON_VALIDACION:
        return False
    if puede_validar_flujo_venta(user):
        pago.validacion_abono = Pago.ValidacionAbono.VALIDADO
        pago.validado_por = user
        pago.validado_en = timezone.now()
        pago.validacion_nota = (
            (pago.validacion_nota or "").strip()
            or "Validado al registrar (admin/gerencia)."
        )[:255]
        return False
    pago.validacion_abono = Pago.ValidacionAbono.PENDIENTE
    pago.validado_por = None
    pago.validado_en = None
    return True


def auto_validar_pago_si_autoridad(pago: Pago, user) -> None:
    """Compat: misma lógica que aplicar_validacion_pago_al_guardar."""
    aplicar_validacion_pago_al_guardar(pago, user)


def validar_contrato(contrato: Contrato, user, *, nota: str = "") -> None:
    contrato.validacion_gerencia = Contrato.ValidacionGerencia.VALIDADO
    contrato.validado_gerencia_por = user
    contrato.validado_gerencia_en = timezone.now()
    contrato.validacion_gerencia_nota = (nota or "").strip()[:255]
    if contrato.estado == Contrato.Estado.BORRADOR:
        contrato.estado = Contrato.Estado.ACTIVO
    contrato.save(
        update_fields=[
            "validacion_gerencia",
            "validado_gerencia_por",
            "validado_gerencia_en",
            "validacion_gerencia_nota",
            "estado",
        ]
    )


def rechazar_contrato(contrato: Contrato, user, *, nota: str = "") -> None:
    contrato.validacion_gerencia = Contrato.ValidacionGerencia.RECHAZADO
    contrato.validado_gerencia_por = user
    contrato.validado_gerencia_en = timezone.now()
    contrato.validacion_gerencia_nota = (nota or "").strip()[:255]
    contrato.estado = Contrato.Estado.BORRADOR
    contrato.save(
        update_fields=[
            "validacion_gerencia",
            "validado_gerencia_por",
            "validado_gerencia_en",
            "validacion_gerencia_nota",
            "estado",
        ]
    )


def validar_formato(formato: FormatoAceptacion, user, *, nota: str = "") -> None:
    formato.validacion_gerencia = FormatoAceptacion.ValidacionGerencia.VALIDADO
    formato.validado_gerencia_por = user
    formato.validado_gerencia_en = timezone.now()
    formato.validacion_gerencia_nota = (nota or "").strip()[:255]
    formato.save(
        update_fields=[
            "validacion_gerencia",
            "validado_gerencia_por",
            "validado_gerencia_en",
            "validacion_gerencia_nota",
            "actualizado_en",
        ]
    )


def rechazar_formato(formato: FormatoAceptacion, user, *, nota: str = "") -> None:
    formato.validacion_gerencia = FormatoAceptacion.ValidacionGerencia.RECHAZADO
    formato.validado_gerencia_por = user
    formato.validado_gerencia_en = timezone.now()
    formato.validacion_gerencia_nota = (nota or "").strip()[:255]
    formato.save(
        update_fields=[
            "validacion_gerencia",
            "validado_gerencia_por",
            "validado_gerencia_en",
            "validacion_gerencia_nota",
            "actualizado_en",
        ]
    )


def conteos_pendientes_flujo() -> dict[str, int]:
    return {
        "formatos": FormatoAceptacion.objects.filter(
            validacion_gerencia=FormatoAceptacion.ValidacionGerencia.PENDIENTE
        ).count(),
        "contratos": Contrato.objects.filter(
            validacion_gerencia=Contrato.ValidacionGerencia.PENDIENTE
        ).count(),
        "pagos": Pago.objects.filter(validacion_abono=Pago.ValidacionAbono.PENDIENTE).count(),
    }
