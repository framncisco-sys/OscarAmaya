"""Desglose de un pago de cuota: calendario + recargo + excedente a capital."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from inmobiliaria.models import CuotaProgramada, Pago


@dataclass(frozen=True)
class DesglosePagoRecibo:
    lineas: tuple[tuple[str, Decimal], ...]
    monto_cuotas: Decimal
    monto_recargo: Decimal
    monto_abono_capital: Decimal
    total: Decimal


def _suma_cuotas(cuotas) -> Decimal:
    return sum((c.monto for c in cuotas), Decimal("0")).quantize(Decimal("0.01"))


def cuotas_del_pago(pago: Pago) -> list[CuotaProgramada]:
    """Cuotas ya vinculadas o, si aún no, las N pendientes que liquida el pago."""
    if pago.concepto != Pago.Concepto.CUOTA or not pago.contrato_id:
        return []
    vinculadas = list(
        pago.cuotas_aplicadas.order_by("vence_en", "numero", "id")
    )
    if vinculadas:
        return vinculadas
    n = max(1, min(int(pago.cuotas_incluidas or 1), 200))
    return list(
        CuotaProgramada.objects.filter(
            contrato_id=pago.contrato_id,
            estado__in=[
                CuotaProgramada.Estado.PENDIENTE,
                CuotaProgramada.Estado.VENCIDA,
            ],
            pago__isnull=True,
        ).order_by("vence_en", "numero", "id")[:n]
    )


def desglose_para_recibo(pago: Pago) -> DesglosePagoRecibo:
    """
    Un solo recibo: cuotas + recargo administrativo (si aplica) + abono a capital.
    El recargo no forma parte del abono a capital.
    """
    total = Decimal(pago.monto).quantize(Decimal("0.01"))

    if pago.concepto == Pago.Concepto.ABONO_CAPITAL:
        return DesglosePagoRecibo(
            lineas=(("Abono a capital (reducción de saldo)", total),),
            monto_cuotas=Decimal("0.00"),
            monto_recargo=Decimal("0.00"),
            monto_abono_capital=total,
            total=total,
        )

    if pago.concepto == Pago.Concepto.MORA:
        return DesglosePagoRecibo(
            lineas=(("Recargo administrativo", total),),
            monto_cuotas=Decimal("0.00"),
            monto_recargo=total,
            monto_abono_capital=Decimal("0.00"),
            total=total,
        )

    if pago.concepto != Pago.Concepto.CUOTA:
        return DesglosePagoRecibo(
            lineas=((pago.get_concepto_display(), total),),
            monto_cuotas=Decimal("0.00"),
            monto_recargo=Decimal("0.00"),
            monto_abono_capital=Decimal("0.00"),
            total=total,
        )

    cuotas = cuotas_del_pago(pago)
    monto_cuotas = _suma_cuotas(cuotas) if cuotas else Decimal("0.00")
    monto_recargo = Decimal(pago.monto_recargo_incluido or 0).quantize(Decimal("0.01"))
    if monto_recargo < 0:
        monto_recargo = Decimal("0.00")

    base = (monto_cuotas + monto_recargo).quantize(Decimal("0.01"))
    if base > total:
        # Datos inconsistentes: priorizar cuotas, luego recargo, sin capital negativo.
        if monto_cuotas > total:
            monto_cuotas = total
            monto_recargo = Decimal("0.00")
        else:
            monto_recargo = (total - monto_cuotas).quantize(Decimal("0.01"))
        base = total

    capital = (total - base).quantize(Decimal("0.01"))

    lineas: list[tuple[str, Decimal]] = []
    if cuotas:
        if len(cuotas) == 1:
            c0 = cuotas[0]
            lineas.append(
                (
                    f"Cuota de financiamiento n.º {c0.numero} "
                    f"(vence {c0.vence_en.strftime('%d/%m/%Y')})",
                    c0.monto.quantize(Decimal("0.01")),
                )
            )
        else:
            nums = f"{cuotas[0].numero}–{cuotas[-1].numero}"
            lineas.append(
                (f"Cuotas de financiamiento n.º {nums}", monto_cuotas)
            )
    else:
        lineas.append(
            (
                "Cuota de financiamiento",
                total if capital <= 0 and monto_recargo <= 0 else monto_cuotas or total,
            )
        )

    if monto_recargo > 0:
        lineas.append(
            (
                "Recargo administrativo (no reduce capital)",
                monto_recargo,
            )
        )

    if capital > 0:
        lineas.append(("Abono a capital (reducción de saldo)", capital))

    if len(lineas) == 1 and lineas[0][1] != total and capital <= 0 and monto_recargo <= 0:
        lineas = [("Cuota de financiamiento", total)]

    return DesglosePagoRecibo(
        lineas=tuple(lineas),
        monto_cuotas=monto_cuotas,
        monto_recargo=monto_recargo,
        monto_abono_capital=capital,
        total=total,
    )
