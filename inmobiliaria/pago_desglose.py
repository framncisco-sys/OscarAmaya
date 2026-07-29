"""Desglose de un pago de cuota: calendario + recargo + excedente a capital."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from inmobiliaria.models import CuotaProgramada, Pago

__all__ = (
    "DesglosePagoRecibo",
    "cuotas_del_pago",
    "desglose_para_recibo",
    "desglose_aplicado_por_cuota",
)


@dataclass(frozen=True)
class DesglosePagoRecibo:
    # (etiqueta, monto, cantidad) — cantidad = N cuotas en esa fila (p. ej. 2.0 si son n.º 18–19)
    lineas: tuple[tuple[str, Decimal, Decimal], ...]
    monto_cuotas: Decimal
    monto_recargo: Decimal
    monto_abono_capital: Decimal
    total: Decimal
    # Recargo que correspondía por gracia vencida (puede ser > al incluido si el pago no lo cubrió).
    monto_recargo_debido: Decimal = Decimal("0.00")


def _cant(n: int | Decimal) -> Decimal:
    return Decimal(n).quantize(Decimal("0.1"))


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
            lineas=(("Abono a capital (reducción de saldo)", total, _cant(1)),),
            monto_cuotas=Decimal("0.00"),
            monto_recargo=Decimal("0.00"),
            monto_abono_capital=total,
            total=total,
            monto_recargo_debido=Decimal("0.00"),
        )

    if pago.concepto == Pago.Concepto.MORA:
        return DesglosePagoRecibo(
            lineas=(("Recargo administrativo", total, _cant(1)),),
            monto_cuotas=Decimal("0.00"),
            monto_recargo=total,
            monto_abono_capital=Decimal("0.00"),
            total=total,
            monto_recargo_debido=total,
        )

    if pago.concepto != Pago.Concepto.CUOTA:
        return DesglosePagoRecibo(
            lineas=((pago.get_concepto_display(), total, _cant(1)),),
            monto_cuotas=Decimal("0.00"),
            monto_recargo=Decimal("0.00"),
            monto_abono_capital=Decimal("0.00"),
            total=total,
            monto_recargo_debido=Decimal("0.00"),
        )

    cuotas = cuotas_del_pago(pago)
    monto_cuotas = _suma_cuotas(cuotas) if cuotas else Decimal("0.00")
    # El recargo del recibo es el que quedó registrado en el pago
    # (se cobra en la cuota siguiente al atraso, no en la misma atrasada).
    monto_recargo = Decimal(pago.monto_recargo_incluido or 0).quantize(Decimal("0.01"))
    if monto_recargo < 0:
        monto_recargo = Decimal("0.00")
    monto_recargo_debido = monto_recargo

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

    lineas: list[tuple[str, Decimal, Decimal]] = []
    if cuotas:
        n_cuotas = len(cuotas)
        if n_cuotas == 1:
            c0 = cuotas[0]
            lineas.append(
                (
                    f"Cuota de financiamiento n.º {c0.numero} "
                    f"(vence {c0.vence_en.strftime('%d/%m/%Y')})",
                    c0.monto.quantize(Decimal("0.01")),
                    _cant(1),
                )
            )
        else:
            nums = f"{cuotas[0].numero}–{cuotas[-1].numero}"
            lineas.append(
                (f"Cuotas de financiamiento n.º {nums}", monto_cuotas, _cant(n_cuotas))
            )
    else:
        n_fallback = max(1, int(pago.cuotas_incluidas or 1))
        lineas.append(
            (
                "Cuota de financiamiento",
                total if capital <= 0 and monto_recargo <= 0 else monto_cuotas or total,
                _cant(n_fallback),
            )
        )

    if monto_recargo > 0:
        lineas.append(
            (
                "Recargo administrativo (no reduce capital)",
                monto_recargo,
                _cant(1),
            )
        )

    if capital > 0:
        lineas.append(("Abono a capital (reducción de saldo)", capital, _cant(1)))

    if len(lineas) == 1 and lineas[0][1] != total and capital <= 0 and monto_recargo <= 0:
        n_fallback = max(1, int(pago.cuotas_incluidas or 1))
        lineas = [("Cuota de financiamiento", total, _cant(n_fallback))]

    return DesglosePagoRecibo(
        lineas=tuple(lineas),
        monto_cuotas=monto_cuotas,
        monto_recargo=monto_recargo,
        monto_abono_capital=capital,
        total=total,
        monto_recargo_debido=monto_recargo_debido,
    )


def desglose_aplicado_por_cuota(cuota: CuotaProgramada) -> dict:
    """
    Cómo se desglosó el pago que liquidó esta cuota.
    Recargo y capital se muestran en la *última* cuota del mismo pago
    (un pago puede cubrir varias cuotas + recargo + abono a capital).
    """
    vacio = {
        "recargo": Decimal("0.00"),
        "capital": Decimal("0.00"),
        "total_pago": None,
        "es_ultima_del_pago": False,
        "tiene_pago": False,
    }
    if not cuota.pago_id:
        return vacio
    pago = cuota.pago
    if pago is None:
        return vacio
    vinculadas = list(
        pago.cuotas_aplicadas.order_by("vence_en", "numero", "id")
    )
    if not vinculadas:
        return vacio
    es_ultima = vinculadas[-1].pk == cuota.pk
    d = desglose_para_recibo(pago)
    return {
        "recargo": d.monto_recargo if es_ultima else Decimal("0.00"),
        "capital": d.monto_abono_capital if es_ultima else Decimal("0.00"),
        "total_pago": Decimal(pago.monto).quantize(Decimal("0.01")) if es_ultima else None,
        "es_ultima_del_pago": es_ultima,
        "tiene_pago": True,
        "pago_id": pago.pk,
    }
