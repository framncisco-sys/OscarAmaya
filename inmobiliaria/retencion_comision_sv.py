"""
Liquidación de comisión al vendedor según tipo de persona (El Salvador).

- Natural: retención de renta 10 % sobre la comisión (práctica habitual
  en pagos por servicios / intermediación a persona natural).
- Contribuyente (NIT/NRC): base + IVA 13 %; retención de renta 10 % sobre
  la base; retención de IVA 1 % sobre la base si el monto base es ≥ umbral
  (típica de agentes de retención / grandes contribuyentes, Cód. Tributario).

Los porcentajes son configurables en settings; no sustituyen asesoría fiscal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from inmobiliaria.models import Vendedor

_CERO = Decimal("0.00")
_CIEN = Decimal("100")


def _q(value: Decimal | int | float | str) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.01"))


def _pct_setting(name: str, default: str) -> Decimal:
    raw = getattr(settings, name, None)
    if raw is None or raw == "":
        return Decimal(default)
    return Decimal(str(raw))


@dataclass(frozen=True)
class LiquidacionComisionVendedor:
    tipo_persona: str
    tipo_persona_label: str
    bruto: Decimal
    iva: Decimal
    retencion_renta: Decimal
    retencion_iva: Decimal
    total_con_iva: Decimal
    neto: Decimal
    pct_renta: Decimal
    pct_iva: Decimal
    pct_retencion_iva: Decimal
    notas: tuple[str, ...]

    @property
    def es_contribuyente(self) -> bool:
        return self.tipo_persona == Vendedor.TipoPersona.CONTRIBUYENTE


def liquidar_comision_vendedor(
    bruto: Decimal,
    *,
    tipo_persona: str | None = None,
    vendedor: Vendedor | None = None,
) -> LiquidacionComisionVendedor:
    """
    Calcula IVA y retenciones sobre el monto bruto de comisión.
    `bruto` = comisión pactada (sin IVA).
    """
    monto = _q(bruto)
    if monto < 0:
        monto = _CERO

    tipo = (tipo_persona or "").strip().upper()
    if not tipo and vendedor is not None:
        tipo = (vendedor.tipo_persona or Vendedor.TipoPersona.NATURAL).strip().upper()
    if tipo not in {
        Vendedor.TipoPersona.NATURAL,
        Vendedor.TipoPersona.CONTRIBUYENTE,
    }:
        tipo = Vendedor.TipoPersona.NATURAL

    pct_renta = _pct_setting("COMISION_SV_RENTA_PCT", "10")
    pct_iva = _pct_setting("COMISION_SV_IVA_PCT", "13")
    pct_ret_iva = _pct_setting("COMISION_SV_IVA_RETENCION_PCT", "1")
    umbral_ret_iva = _q(_pct_setting("COMISION_SV_IVA_RETENCION_MIN", "100"))
    aplicar_ret_iva = bool(
        getattr(settings, "COMISION_SV_RETENER_IVA_1PCT", True)
    )

    notas: list[str] = []

    if tipo == Vendedor.TipoPersona.CONTRIBUYENTE:
        iva = _q(monto * pct_iva / _CIEN)
        ret_renta = _q(monto * pct_renta / _CIEN)
        ret_iva = _CERO
        if aplicar_ret_iva and monto >= umbral_ret_iva:
            ret_iva = _q(monto * pct_ret_iva / _CIEN)
            notas.append(
                f"Retención IVA {pct_ret_iva}% sobre la base "
                f"(agente de retención; base ≥ ${umbral_ret_iva})."
            )
        elif aplicar_ret_iva:
            notas.append(
                f"Sin retención IVA {pct_ret_iva}%: la base es menor a ${umbral_ret_iva}."
            )
        total = _q(monto + iva)
        neto = _q(total - ret_renta - ret_iva)
        notas.insert(
            0,
            f"Contribuyente: IVA {pct_iva}% + retención renta {pct_renta}% sobre la base.",
        )
        label = "Contribuyente"
    else:
        iva = _CERO
        ret_iva = _CERO
        ret_renta = _q(monto * pct_renta / _CIEN)
        total = monto
        neto = _q(monto - ret_renta)
        notas.append(
            f"Persona natural: retención de renta {pct_renta}% sobre la comisión."
        )
        label = "Natural"

    return LiquidacionComisionVendedor(
        tipo_persona=tipo,
        tipo_persona_label=label,
        bruto=monto,
        iva=iva,
        retencion_renta=ret_renta,
        retencion_iva=ret_iva,
        total_con_iva=total,
        neto=neto,
        pct_renta=pct_renta,
        pct_iva=pct_iva,
        pct_retencion_iva=pct_ret_iva,
        notas=tuple(notas),
    )
