"""Consultas del dashboard: inventario de venta vs alquiler, sin contenedores técnicos."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from inmobiliaria.forms_web import PROYECTO_CONTENEDOR_CASA_VENTA
from inmobiliaria.models import Contrato, Inmueble, Pago, Poligono, Proyecto, Vendedor

_LOTE = Inmueble.Tipo.LOTE
_EST = Inmueble.Estado


def _qs_inventario_venta():
    """Inmuebles de venta/lotes (excluye módulo de alquiler)."""
    return Inmueble.objects.filter(en_alquiler=False)


def _qs_proyectos_lotificacion():
    return Proyecto.objects.filter(activo=True).exclude(nombre=PROYECTO_CONTENEDOR_CASA_VENTA)


def _filtro_lote_venta(prefix: str = "lotes") -> Q:
    p = f"{prefix}__"
    return Q(**{f"{p}tipo": _LOTE, f"{p}en_alquiler": False})


def build_dashboard_bienes_raices_context(
    *,
    user,
    incluir_vendedores: bool,
    contratos_restringidos: bool,
) -> dict:
    """Dashboard del sistema Paredes Bienes Raíces (sin lotificación/proyectos)."""
    ahora = timezone.localtime()

    from inmobiliaria.models import AsesorAlquiler, Cliente

    alquiler_locales = Inmueble.objects.filter(en_alquiler=True, tipo=Inmueble.Tipo.LOCAL).count()
    alquiler_casas = Inmueble.objects.filter(
        en_alquiler=True,
        tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA),
    ).count()
    inventario_venta = _qs_inventario_venta()
    casas_venta = inventario_venta.filter(
        tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA)
    ).count()
    lotes_venta = inventario_venta.exclude(
        tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA)
    ).count()
    disponibles_venta = inventario_venta.filter(estado=_EST.DISPONIBLE).count()

    contratos_qs = Contrato.objects.all()
    if contratos_restringidos:
        from inmobiliaria.contratos_acceso import filtrar_contratos_queryset_por_vendedor

        contratos_qs = filtrar_contratos_queryset_por_vendedor(contratos_qs, user)

    ctx: dict = {
        "dashboard_actualizado": ahora,
        "br_clientes": Cliente.objects.count(),
        "br_alquiler_total": alquiler_locales + alquiler_casas,
        "br_alquiler_locales": alquiler_locales,
        "br_alquiler_casas": alquiler_casas,
        "br_venta_total": casas_venta + lotes_venta,
        "br_casas_venta": casas_venta,
        "br_lotes_venta": lotes_venta,
        "br_disponibles_venta": disponibles_venta,
        "br_contratos_activos": contratos_qs.filter(estado=Contrato.Estado.ACTIVO).count(),
        "br_ultimos_alquiler": (
            Inmueble.objects.filter(en_alquiler=True)
            .select_related("proyecto")
            .order_by("-id")[:6]
        ),
        "br_ultimos_clientes": Cliente.objects.order_by("-id")[:6],
    }

    if incluir_vendedores:
        ctx["br_vendedores"] = Vendedor.objects.filter(activo=True).count()
        ctx["br_asesores_alquiler"] = AsesorAlquiler.objects.filter(activo=True).count()

    return ctx


def _qs_inventario_lotes_desarrollos():
    """Solo lotes de lotificación (sistema Desarrollos)."""
    return _qs_inventario_venta().filter(tipo=_LOTE)


def build_dashboard_context(*, user, incluir_vendedores: bool, contratos_restringidos: bool) -> dict:
    hoy = timezone.localdate()
    limite = hoy + timedelta(days=7)
    ahora = timezone.localtime()

    inventario = _qs_inventario_lotes_desarrollos()
    total_inventario = inventario.count()

    estado_map = {
        row["estado"]: row["n"]
        for row in inventario.values("estado").annotate(n=Count("id"))
    }
    disponibles = estado_map.get(_EST.DISPONIBLE, 0)
    reservados = estado_map.get(_EST.RESERVADO, 0)
    vendidos = estado_map.get(_EST.VENDIDO, 0)
    bloqueados = estado_map.get(_EST.BLOQUEADO, 0)

    valor_disponible = inventario.filter(estado=_EST.DISPONIBLE).aggregate(
        s=Sum("precio_lista")
    )["s"] or Decimal("0")

    estado_breakdown = []
    for est in _EST:
        n = estado_map.get(est.value, 0)
        if total_inventario and n == 0:
            continue
        estado_breakdown.append(
            {
                "key": est.value,
                "label": est.label,
                "count": n,
                "pct": round(n * 100 / total_inventario, 1) if total_inventario else 0,
            }
        )

    lote_q = _filtro_lote_venta()
    poligonos = (
        Poligono.objects.select_related("proyecto")
        .exclude(proyecto__nombre=PROYECTO_CONTENEDOR_CASA_VENTA)
        .annotate(
            total_lotes=Count("lotes", filter=lote_q, distinct=True),
            vendidos=Count(
                "lotes",
                filter=lote_q & Q(lotes__estado=_EST.VENDIDO),
                distinct=True,
            ),
            reservados=Count(
                "lotes",
                filter=lote_q & Q(lotes__estado=_EST.RESERVADO),
                distinct=True,
            ),
            disponibles=Count(
                "lotes",
                filter=lote_q & Q(lotes__estado=_EST.DISPONIBLE),
                distinct=True,
            ),
        )
        .filter(total_lotes__gt=0)
        .order_by("-vendidos", "-reservados", "proyecto__nombre", "orden", "nombre")[:15]
    )

    poligono_rows = []
    for p in poligonos:
        total = p.total_lotes or 0
        v = p.vendidos or 0
        r = p.reservados or 0
        d = p.disponibles or 0
        ocupacion = round((v + r) * 100 / total, 1) if total else 0
        poligono_rows.append(
            {
                "obj": p,
                "total": total,
                "vendidos": v,
                "reservados": r,
                "disponibles": d,
                "ocupacion_pct": ocupacion,
                "vendidos_pct": round(v * 100 / total, 1) if total else 0,
                "reservados_pct": round(r * 100 / total, 1) if total else 0,
                "disponibles_pct": round(d * 100 / total, 1) if total else 0,
            }
        )

    reservas_por_vencer = (
        inventario.filter(
            estado=_EST.RESERVADO,
            reserva_hasta__gte=hoy,
            reserva_hasta__lte=limite,
        )
        .select_related("proyecto", "cliente_reserva")
        .order_by("reserva_hasta")[:12]
    )
    reservas_vencidas_ct = inventario.filter(
        estado=_EST.RESERVADO,
        reserva_hasta__isnull=False,
        reserva_hasta__lt=hoy,
    ).count()

    ultimos_inmuebles = (
        inventario.select_related("proyecto", "poligono")
        .order_by("-id")[:8]
    )

    contratos_activos = Contrato.objects.filter(estado=Contrato.Estado.ACTIVO).count()
    total_alquiler = Inmueble.objects.filter(en_alquiler=True).count()

    ctx: dict = {
        "dashboard_actualizado": ahora,
        "total_proyectos": _qs_proyectos_lotificacion().count(),
        "total_inventario_venta": total_inventario,
        "total_alquiler": total_alquiler,
        "disponibles": disponibles,
        "reservados": reservados,
        "vendidos": vendidos,
        "bloqueados": bloqueados,
        "valor_inventario_disponible": valor_disponible,
        "estado_breakdown": estado_breakdown,
        "total_contratos_activos": contratos_activos,
        "ultimos_inmuebles": ultimos_inmuebles,
        "poligono_rows": poligono_rows,
        "reservas_por_vencer": reservas_por_vencer,
        "reservas_vencidas_ct": reservas_vencidas_ct,
        # Compatibilidad con plantilla antigua
        "total_inmuebles": total_inventario,
        "poligono_stats": [r["obj"] for r in poligono_rows],
    }

    if incluir_vendedores:
        ctx["total_vendedores"] = Vendedor.objects.filter(activo=True).count()

    if contratos_restringidos:
        from inmobiliaria.contratos_acceso import (
            filtrar_contratos_queryset_por_vendedor,
            totales_comision_contratos,
        )

        resumen_qs = filtrar_contratos_queryset_por_vendedor(
            Contrato.objects.only(
                "id", "comision_monto", "comision_porcentaje", "precio_final"
            ),
            user,
        )
        total_com, con_m, n_ct = totales_comision_contratos(resumen_qs)
        ctx["dashboard_mis_contratos"] = {
            "count": n_ct,
            "comision_total": total_com,
            "con_comision": con_m,
        }

    return ctx


def build_gestion_hub_context(
    *,
    user,
    incluir_vendedores: bool,
    contratos_restringidos: bool,
) -> dict:
    """Resumen para la página de Gestión (/app/): conteos confiables por módulo."""
    ahora = timezone.localtime()
    hoy = timezone.localdate()
    mes_inicio = hoy.replace(day=1)

    inventario = _qs_inventario_venta()
    casas_venta = inventario.filter(
        tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA)
    )
    # Desarrollos / KPIs de lotificación: solo tipo LOTE.
    lotes_locales = inventario.filter(tipo=_LOTE)

    alquiler_locales = Inmueble.objects.filter(
        en_alquiler=True, tipo=Inmueble.Tipo.LOCAL
    )
    alquiler_casas = Inmueble.objects.filter(
        en_alquiler=True,
        tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA),
    )

    contratos_qs = Contrato.objects.all()
    if contratos_restringidos:
        from inmobiliaria.contratos_acceso import filtrar_contratos_queryset_por_vendedor

        contratos_qs = filtrar_contratos_queryset_por_vendedor(contratos_qs, user)

    pagos_qs = Pago.objects.all()
    if contratos_restringidos:
        pagos_qs = pagos_qs.filter(contrato__in=contratos_qs)

    pagos_mes = pagos_qs.filter(fecha__gte=mes_inicio).count()
    monto_mes = pagos_qs.filter(fecha__gte=mes_inicio).aggregate(s=Sum("monto"))["s"] or Decimal(
        "0"
    )

    reservas_vencidas = inventario.filter(
        tipo=_LOTE,
        estado=_EST.RESERVADO,
        reserva_hasta__isnull=False,
        reserva_hasta__lt=hoy,
    ).count()

    from docs.models import DocumentoEmitido
    from inmobiliaria.models import FormatoAceptacion

    docs_total = DocumentoEmitido.objects.count()
    formatos_total = FormatoAceptacion.objects.count()

    poligonos_ct = Poligono.objects.exclude(
        proyecto__nombre=PROYECTO_CONTENEDOR_CASA_VENTA
    ).count()

    return {
        "gestion_actualizado": ahora,
        "gestion_resumen": {
            "proyectos": _qs_proyectos_lotificacion().count(),
            "poligonos": poligonos_ct,
            "lotes_locales": lotes_locales.count(),
            "casas_venta": casas_venta.count(),
            "alquiler_locales": alquiler_locales.count(),
            "alquiler_casas": alquiler_casas.count(),
            "contratos_activos": contratos_qs.filter(estado=Contrato.Estado.ACTIVO).count(),
            "contratos_total": contratos_qs.count(),
            "pagos_mes": pagos_mes,
            "monto_mes": monto_mes,
            "documentos": docs_total,
            "formatos": formatos_total,
            "reservas_vencidas": reservas_vencidas,
        },
        "gestion_alertas": _gestion_alertas(reservas_vencidas),
    }


def _gestion_alertas(reservas_vencidas: int) -> list[dict]:
    alertas = []
    if reservas_vencidas:
        alertas.append(
            {
                "tipo": "warn",
                "texto": (
                    f"Hay {reservas_vencidas} reserva(s) vencida(s). "
                    "Revise el inventario o ejecute expirar_reservas."
                ),
                "url_name": "app:inmueble_list",
                "url_label": "Ver lotes",
            }
        )
    return alertas


def build_sidebar_stats(
    *,
    user,
    contratos_restringidos: bool,
    incluir_admin: bool = False,
    incluir_usuarios: bool = False,
    incluir_vendedores: bool = False,
) -> dict:
    """Conteos en vivo para el menú lateral (misma lógica que Gestión / dashboard)."""
    resumen = build_gestion_hub_context(
        user=user,
        incluir_vendedores=False,
        contratos_restringidos=contratos_restringidos,
    )["gestion_resumen"]

    from django.contrib.auth import get_user_model

    from audit.models import AuditLog
    from inmobiliaria.models import AsesorAlquiler, Cliente, ParametroMora, Vendedor

    stats = {
        "clientes": Cliente.objects.count(),
        "alquiler_locales": resumen["alquiler_locales"],
        "alquiler_casas": resumen["alquiler_casas"],
        "casas_venta": resumen["casas_venta"],
        "lotes_locales": resumen["lotes_locales"],
        "proyectos": resumen["proyectos"],
        "poligonos": resumen["poligonos"],
        "contratos_activos": resumen["contratos_activos"],
        "contratos_total": resumen["contratos_total"],
        "pagos_mes": resumen["pagos_mes"],
        "documentos": resumen["documentos"],
        "formatos": resumen["formatos"],
        "parametros_mora": ParametroMora.objects.count(),
    }

    if incluir_usuarios:
        User = get_user_model()
        stats["usuarios"] = User.objects.filter(is_active=True).count()

    if incluir_admin:
        stats["auditoria"] = AuditLog.objects.count()

    if incluir_vendedores:
        stats["vendedores"] = Vendedor.objects.filter(activo=True).count()
        stats["asesores_alquiler"] = AsesorAlquiler.objects.filter(activo=True).count()

    return stats
