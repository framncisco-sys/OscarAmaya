"""Expediente de documentos PDF por cliente (listado + detalle)."""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from inmobiliaria.contratos_acceso import (
    aplica_restriccion_contratos_por_vendedor,
    filtrar_documentos_queryset_por_vendedor,
    vendedor_catalogo_activo_vinculado,
)
from inmobiliaria.formato_aceptacion_db import formato_aceptacion_defer_missing_columns
from inmobiliaria.models import FormatoAceptacion, Pago

from .models import DocumentoEmitido, DocumentoTipo

ORDEN_CAT = [
    ("formato", "Formato de aceptación"),
    ("promesa", "Promesa de venta"),
    ("reserva", "Recibo de reserva"),
    ("prima", "Recibo de prima"),
    ("contado", "Recibo de contado"),
    ("cuota", "Recibo de cuota"),
    ("abono", "Recibo de abono a capital"),
    ("comision_vendedor", "Recibo de comisión (asesor de ventas)"),
    ("comision_alquiler", "Recibo de comisión (arrendamiento)"),
    ("otro", "Otros documentos"),
]
CAT_RANK = {k: i for i, (k, _) in enumerate(ORDEN_CAT)}
CAT_LABEL = dict(ORDEN_CAT)


def _norm_cliente(nombre: str) -> str:
    return " ".join((nombre or "").strip().upper().split()) or "SIN CLIENTE"


def _display_cliente(key: str) -> str:
    if key == "SIN CLIENTE":
        return "Sin cliente"
    return key.title()


def _cat_pago(concepto: str) -> str:
    c = (concepto or "").upper()
    if c == Pago.Concepto.RESERVA:
        return "reserva"
    if c == Pago.Concepto.PRIMA:
        return "prima"
    if c == Pago.Concepto.CONTADO:
        return "contado"
    if c == Pago.Concepto.CUOTA:
        return "cuota"
    if c == Pago.Concepto.ABONO_CAPITAL:
        return "abono"
    return "otro"


def _cat_doc(d: DocumentoEmitido) -> str:
    if d.tipo == DocumentoTipo.PROMESA_VENTA:
        return "promesa"
    if d.tipo == DocumentoTipo.RECIBO_COMISION_VENDEDOR:
        return "comision_vendedor"
    if d.tipo == DocumentoTipo.RECIBO_COMISION_ARRENDAMIENTO:
        return "comision_alquiler"
    if d.tipo == DocumentoTipo.RECIBO_INGRESO and d.pago_id:
        return _cat_pago(getattr(d.pago, "concepto", "") or "")
    return "otro"


def _cliente_de_doc(d: DocumentoEmitido) -> str:
    fmt = getattr(d, "formato_relacionado", None)
    if fmt and (fmt.nombre_cliente or "").strip():
        return _norm_cliente(fmt.nombre_cliente)
    pago = getattr(d, "pago", None)
    if pago is not None:
        c = getattr(getattr(pago, "contrato", None), "cliente", None)
        if c is not None:
            return _norm_cliente(f"{c.nombres} {c.apellidos}")
    contrato = getattr(d, "contrato", None)
    if contrato is not None:
        c = getattr(contrato, "cliente", None)
        if c is not None:
            return _norm_cliente(f"{c.nombres} {c.apellidos}")
    if d.vendedor_id:
        return _norm_cliente(f"COMISION — {d.vendedor.nombre_completo}")
    return "SIN CLIENTE"


def _fila(
    *,
    categoria: str,
    titulo: str,
    numero: str,
    monto,
    emitido,
    extra: str,
    url: str | None,
    badge: str = "",
) -> dict:
    return {
        "categoria": categoria,
        "categoria_label": CAT_LABEL.get(categoria, "Otros documentos"),
        "titulo": titulo,
        "numero": numero,
        "monto": monto,
        "emitido": emitido,
        "extra": extra,
        "url": url,
        "badge": badge,
    }


def construir_expedientes(user) -> dict[str, list[dict]]:
    """Devuelve {cliente_key: [filas documento]}."""
    filas_por_cliente: dict[str, list[dict]] = defaultdict(list)
    solo_mios = aplica_restriccion_contratos_por_vendedor(user)

    items = (
        DocumentoEmitido.objects.select_related(
            "contrato",
            "contrato__cliente",
            "pago",
            "pago__contrato",
            "pago__contrato__cliente",
            "pago__formato_aceptacion",
            "vendedor",
            "emitido_por",
        )
        .prefetch_related("contrato__formatos_aceptacion")
        .order_by("-emitido_en", "-id")
    )
    if solo_mios:
        items = filtrar_documentos_queryset_por_vendedor(items, user)
    items = list(items[:500])

    for d in items:
        fmt = getattr(getattr(d, "pago", None), "formato_aceptacion", None)
        if fmt is None and getattr(d, "contrato_id", None):
            relacionados = list(d.contrato.formatos_aceptacion.all())
            if relacionados:
                fmt = max(relacionados, key=lambda f: f.numero_formulario)
        d.formato_relacionado = fmt

        cat = _cat_doc(d)
        if d.pago_id:
            titulo = d.pago.get_concepto_display()
            monto = d.pago.monto
            badge = ""
            if d.pago.validacion_abono == "VALIDADO":
                badge = "autorizado"
            elif d.pago.validacion_abono == "PENDIENTE":
                badge = "pendiente"
        elif d.tipo == DocumentoTipo.RECIBO_COMISION_VENDEDOR:
            titulo = "Comisión vendedor"
            monto = d.comision_neto_usd or d.monto_comision_usd
            badge = ""
        elif d.tipo == DocumentoTipo.PROMESA_VENTA:
            titulo = "Promesa de venta"
            monto = None
            badge = ""
        else:
            titulo = d.get_tipo_display()
            monto = d.monto_comision_usd
            badge = ""

        extra_parts = []
        if fmt:
            extra_parts.append(
                f"Formato Nº {fmt.numero_formulario:04d}"
                + (f" — {fmt.nombre_cliente}" if fmt.nombre_cliente else "")
            )
        elif d.contrato_id:
            extra_parts.append(f"Contrato {d.contrato.numero}")
        if d.vendedor_id:
            extra_parts.append(f"Asesor de ventas {d.vendedor.nombre_completo}")

        url = reverse("app:doc_download", args=[d.id]) if d.pdf_file else None
        cliente_key = _cliente_de_doc(d)
        filas_por_cliente[cliente_key].append(
            _fila(
                categoria=cat,
                titulo=titulo,
                numero=d.numero,
                monto=monto,
                emitido=d.emitido_en,
                extra=" · ".join(extra_parts),
                url=url,
                badge=badge,
            )
        )

    fmt_qs = formato_aceptacion_defer_missing_columns(
        FormatoAceptacion.objects.select_related(
            "contrato", "contrato__cliente", "creado_por"
        ).order_by("-id")
    )
    if solo_mios:
        v = vendedor_catalogo_activo_vinculado(user)
        fq = Q(creado_por_id=user.pk)
        if v is not None:
            fq |= Q(contrato__vendedor_perfil_id=v.pk) | Q(contrato__vendedor_id=user.pk)
        else:
            fq |= Q(contrato__vendedor_id=user.pk)
        fmt_qs = fmt_qs.filter(fq).distinct()

    for fmt in fmt_qs[:300]:
        cliente_key = _norm_cliente(fmt.nombre_cliente)
        if fmt.contrato_id and getattr(fmt.contrato, "cliente", None):
            c = fmt.contrato.cliente
            cliente_key = _norm_cliente(f"{c.nombres} {c.apellidos}") or cliente_key
        filas_por_cliente[cliente_key].append(
            _fila(
                categoria="formato",
                titulo="Formato de aceptación",
                numero=f"Nº {fmt.numero_formulario:04d}",
                monto=None,
                emitido=getattr(fmt, "creado_en", None),
                extra=(
                    f"Contrato {fmt.contrato.numero}"
                    if fmt.contrato_id
                    else (fmt.nombre_proyecto or "")
                ),
                url=reverse("app:formato_aceptacion_pdf", args=[fmt.pk]),
            )
        )
        promesa = getattr(fmt, "promesa_venta_escaneada", None)
        if promesa and getattr(promesa, "name", ""):
            filas_por_cliente[cliente_key].append(
                _fila(
                    categoria="promesa",
                    titulo="Promesa de venta (escaneada)",
                    numero=f"Formato {fmt.numero_formulario:04d}",
                    monto=None,
                    emitido=None,
                    extra="Adjunto del formato",
                    url=reverse("app:formato_aceptacion_promesa_descargar", args=[fmt.pk]),
                )
            )

    return filas_por_cliente


def agrupar_cliente(filas: list[dict]) -> list[dict]:
    filas = list(filas)
    filas.sort(
        key=lambda f: (
            CAT_RANK.get(f["categoria"], 99),
            -(
                f["emitido"].timestamp()
                if f["emitido"] is not None and hasattr(f["emitido"], "timestamp")
                else 0
            ),
            f["numero"] or "",
        )
    )
    por_cat: dict[str, list] = defaultdict(list)
    for f in filas:
        por_cat[f["categoria"]].append(f)
    categorias = []
    for key, label in ORDEN_CAT:
        if key in por_cat:
            categorias.append({"key": key, "label": label, "docs": por_cat[key]})
    for key, docs in por_cat.items():
        if key not in CAT_LABEL:
            categorias.append({"key": key, "label": "Otros documentos", "docs": docs})
    return categorias


@login_required
def docs_list(request: HttpRequest) -> HttpResponse:
    """Listado de clientes: clic abre el expediente de PDFs del cliente."""
    q = (request.GET.get("q") or "").strip()
    expedientes = construir_expedientes(request.user)
    if q:
        q_up = q.upper()
        expedientes = {k: v for k, v in expedientes.items() if q_up in k}

    clientes = []
    for key in sorted(expedientes.keys()):
        filas = expedientes[key]
        clientes.append(
            {
                "cliente": _display_cliente(key),
                "cliente_key": key,
                "url": f"{reverse('app:docs_cliente')}?cliente={quote(key)}",
                "total": len(filas),
            }
        )

    solo_mios = aplica_restriccion_contratos_por_vendedor(request.user)
    return render(
        request,
        "app/docs_list.html",
        {
            "clientes": clientes,
            "docs_solo_mios": solo_mios,
            "q": q,
            "total_clientes": len(clientes),
            "total_docs": sum(c["total"] for c in clientes),
        },
    )


@login_required
def docs_cliente(request: HttpRequest, cliente_key: str | None = None) -> HttpResponse:
    """Pantalla de documentos PDF de un cliente (categorías + descargas)."""
    raw = (cliente_key or request.GET.get("cliente") or "").strip()
    if not raw:
        raise Http404("Indique el cliente.")
    key = _norm_cliente(raw)
    expedientes = construir_expedientes(request.user)
    filas = expedientes.get(key)
    if filas is None:
        raise Http404("No hay documentos para ese cliente.")

    categorias = agrupar_cliente(filas)
    solo_mios = aplica_restriccion_contratos_por_vendedor(request.user)
    return render(
        request,
        "app/docs_cliente_detalle.html",
        {
            "cliente": _display_cliente(key),
            "cliente_key": key,
            "categorias": categorias,
            "total_docs": len(filas),
            "docs_solo_mios": solo_mios,
            "volver_url": reverse("app:docs_list"),
        },
    )
