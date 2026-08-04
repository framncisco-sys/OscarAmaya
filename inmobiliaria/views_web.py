"""Vistas web minimalistas (azul / blanco / gris) — gestión sin depender del admin."""

import csv
import html
import json
import logging
import mimetypes
import os
import tempfile
import time
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from django.conf import settings
from django.core.files.storage import default_storage
from django.contrib import messages
from django.forms import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import connection, transaction
from django.db.models import Max, ProtectedError, Sum
from django.db.utils import ProgrammingError
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.formats import date_format
from django.utils.html import format_html
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    ListView,
    TemplateView,
    UpdateView,
)

from usuarios.roles import puede_gestionar_vendedores

from inmobiliaria.contratos_acceso import (
    aplica_restriccion_contratos_por_vendedor,
    filtrar_contratos_queryset_por_vendedor,
    filtrar_pagos_queryset_por_vendedor,
    totales_comision_contratos,
    usuario_ve_todos_los_contratos,
    vendedor_catalogo_activo_vinculado,
)

from core.sensitive_access import (
    SensitiveDeleteMixin,
    SensitiveEditMixin,
    SensitiveEditSessionMixin,
    check_sensitive_write,
    grant,
    safe_next_url,
    session_valid,
    skips_sensitive_reauth,
    ttl_seconds,
)

from . import forms_web as forms
from .cuotas_calendario import (
    construir_cuotas_programadas,
    filas_listado_cuotas_formato_aceptacion,
    fecha_primera_cuota_desde_formato_contrato,
    monto_uniforme_por_cuota,
)
from docs.services import generar_pdf_desde_plantilla

from .formato_aceptacion_db import (
    formato_aceptacion_compraventa_column_ready as _formato_aceptacion_compraventa_column_ready,
    formato_aceptacion_credito_extra_columns_ready,
    formato_aceptacion_defer_missing_columns,
    formato_aceptacion_promesa_column_ready as _formato_aceptacion_promesa_column_ready,
)
from .models import (
    Cliente,
    ClienteDocumento,
    Contrato,
    CuotaProgramada,
    FormatoAceptacion,
    Inmueble,
    InmuebleDetalleCasa,
    InmuebleDetalleCasaAlquiler,
    InmuebleDetalleLocalAlquiler,
    InmuebleImagen,
    Pago,
    ParametroEtapaVenta,
    ParametroMora,
    Poligono,
    Proyecto,
    RecordatorioPago,
    Vendedor,
)

logger = logging.getLogger(__name__)


def _formato_aceptacion_qs_contrato_pdf():
    qs = FormatoAceptacion.objects.select_related(
        "contrato",
        "contrato__cliente",
        "contrato__inmueble",
        "contrato__inmueble__proyecto",
    )
    return formato_aceptacion_defer_missing_columns(qs)


def _formato_aceptacion_qs_pk():
    return formato_aceptacion_defer_missing_columns(FormatoAceptacion.objects.all())


def _formato_aceptacion_qs_para_usuario(user):
    """Evita IDOR: el vendedor solo ve/edita formatos que él creó."""
    from inmobiliaria.vendedor_acceso import es_vendedor_restringido

    qs = _formato_aceptacion_qs_contrato_pdf()
    if es_vendedor_restringido(user):
        qs = qs.filter(creado_por_id=user.pk)
    return qs


def _formato_aceptacion_qs_pk_para_usuario(user):
    from inmobiliaria.vendedor_acceso import es_vendedor_restringido

    qs = _formato_aceptacion_qs_pk()
    if es_vendedor_restringido(user):
        qs = qs.filter(creado_por_id=user.pk)
    return qs


# Editar/eliminar formato de aceptación: credenciales de superusuario (sesión temporal).
PBR_SESSION_FORMATO_SUPER_GATE = "PBR_FORMATO_SUPERUSER_GATE_UNTIL"


def _formato_superuser_gate_session_valid(request: HttpRequest) -> bool:
    until = request.session.get(PBR_SESSION_FORMATO_SUPER_GATE)
    if until is None:
        return False
    try:
        return float(until) > time.time()
    except (TypeError, ValueError):
        return False


def _verify_superuser_credentials(username: str, password: str) -> bool:
    User = get_user_model()
    u = User.objects.filter(
        username__iexact=(username or "").strip(),
        is_superuser=True,
        is_active=True,
    ).first()
    return bool(u and u.check_password(password))


def _inmueble_galeria_superusuario_post_ok(request: HttpRequest) -> bool:
    """Subir / editar / eliminar imágenes de galería: credenciales de superusuario en cada solicitud."""
    u = (request.POST.get("superuser_username") or "").strip()
    p = (request.POST.get("superuser_password") or "").strip()
    return _verify_superuser_credentials(u, p)


def _inmueble_galeria_subida_error_o_none(request: HttpRequest) -> str | None:
    if not request.FILES.getlist("galeria_fotos"):
        return None
    if not _inmueble_galeria_superusuario_post_ok(request):
        return (
            "Para subir fotos a la galería ingrese usuario y contraseña de un superusuario de Django "
            "(campos al final de la sección Galería)."
        )
    return None


def _inmueble_procesar_subida_galeria(request: HttpRequest, inv: Inmueble) -> None:
    files = request.FILES.getlist("galeria_fotos")
    if not files:
        return
    if not _inmueble_galeria_superusuario_post_ok(request):
        return
    raw_idx = (request.POST.get("galeria_portada_index") or "").strip()
    try:
        portada_i = int(raw_idx) if raw_idx != "" else None
    except ValueError:
        portada_i = None
    max_o = InmuebleImagen.objects.filter(inmueble=inv).aggregate(m=Max("orden"))["m"] or 0
    created_pks: list[int] = []
    for i, f in enumerate(files):
        img = InmuebleImagen.objects.create(
            inmueble=inv,
            imagen=f,
            orden=max_o + i + 1,
            url="",
            es_portada=False,
        )
        created_pks.append(img.pk)
    if portada_i is not None and 0 <= portada_i < len(created_pks):
        pk_portada = created_pks[portada_i]
        InmuebleImagen.objects.filter(inmueble=inv).update(es_portada=False)
        InmuebleImagen.objects.filter(pk=pk_portada).update(es_portada=True)


def _inmueble_imagenes_ordenadas(inv: Inmueble) -> list[InmuebleImagen]:
    imgs = list(InmuebleImagen.objects.filter(inmueble=inv))
    imgs.sort(key=lambda x: (not x.es_portada, x.orden, x.pk))
    return imgs


def _guardar_galeria_inmueble_tras_ficha(request: HttpRequest, inv: Inmueble) -> None:
    """Tras guardar una ficha: subida de fotos + portada (misma regla que Casa y fotos)."""
    gal_err = _inmueble_galeria_subida_error_o_none(request)
    if gal_err:
        messages.error(request, gal_err)
        return
    n_fotos = len(request.FILES.getlist("galeria_fotos"))
    try:
        with transaction.atomic():
            _inmueble_procesar_subida_galeria(request, inv)
    except Exception:
        logger.exception("Error al guardar fotos de galería (inmueble)")
        messages.error(
            request,
            "La ficha ya está guardada; revise las fotos (formato, tamaño) o vuelva a intentar.",
        )
    else:
        if n_fotos:
            messages.success(request, f"Se agregaron {n_fotos} foto(s) a la galería.")


def _firma_preview_flags(formato: FormatoAceptacion | None) -> dict[str, bool]:
    """Compat: ya no se usan miniaturas de firma; se mantiene vacío."""
    return {"aceptante": False, "vendedor": False, "autorizado": False}


def _formato_firmas_ausentes_en_storage(formato: FormatoAceptacion) -> list[str]:
    """
    Adjuntos con ruta en BD pero archivo inexistente en default_storage.
    Ocurre en App Platform sin S3/volumen.
    """
    faltan: list[str] = []
    for label, attr in (
        ("DUI del cliente", "dui_cliente_archivo"),
        ("formato en físico", "formato_aceptacion_fisico"),
    ):
        ff = getattr(formato, attr, None)
        if ff and ff.name and not default_storage.exists(ff.name):
            faltan.append(label)
    return faltan


def _formato_ctx_expediente_archivos(obj) -> dict:
    """URLs de subir/descargar promesa y compraventa para plantillas de formato."""
    out = {
        "formato_promesa_columna_bd": False,
        "formato_promesa_migrate_pendiente": False,
        "formato_promesa_subir_url": None,
        "formato_promesa_descargar_url": None,
        "formato_compraventa_columna_bd": False,
        "formato_compraventa_migrate_pendiente": False,
        "formato_compraventa_subir_url": None,
        "formato_compraventa_descargar_url": None,
    }
    has_pk = bool(getattr(obj, "pk", None))
    promesa_ok = _formato_aceptacion_promesa_column_ready()
    compra_ok = _formato_aceptacion_compraventa_column_ready()
    out["formato_promesa_columna_bd"] = promesa_ok
    out["formato_compraventa_columna_bd"] = compra_ok
    out["formato_promesa_migrate_pendiente"] = bool(has_pk and not promesa_ok)
    out["formato_compraventa_migrate_pendiente"] = bool(has_pk and not compra_ok)
    if not has_pk:
        return out
    if promesa_ok:
        out["formato_promesa_subir_url"] = reverse(
            "app:formato_aceptacion_promesa_subir", kwargs={"pk": obj.pk}
        )
        f = getattr(obj, "promesa_venta_escaneada", None)
        if f and f.name:
            out["formato_promesa_descargar_url"] = reverse(
                "app:formato_aceptacion_promesa_descargar", kwargs={"pk": obj.pk}
            )
    if compra_ok:
        out["formato_compraventa_subir_url"] = reverse(
            "app:formato_aceptacion_compraventa_subir", kwargs={"pk": obj.pk}
        )
        c = getattr(obj, "contrato_compraventa_escaneado", None)
        if c and c.name:
            out["formato_compraventa_descargar_url"] = reverse(
                "app:formato_aceptacion_compraventa_descargar", kwargs={"pk": obj.pk}
            )
    return out


def _formato_adjunto_urls(formato: FormatoAceptacion | None) -> dict[str, str | None]:
    empty = {"dui": None, "fisico": None, "boucher": None}
    if not formato or not getattr(formato, "pk", None):
        return empty
    mapping = (
        ("dui", "dui_cliente_archivo", "dui"),
        ("fisico", "formato_aceptacion_fisico", "fisico"),
        ("boucher", "boucher_pago_reserva", "boucher"),
    )
    out: dict[str, str | None] = {}
    for key, attr, slug in mapping:
        ff = getattr(formato, attr, None)
        if ff and ff.name:
            out[key] = reverse(
                "app:formato_aceptacion_adjunto_descargar",
                kwargs={"pk": formato.pk, "tipo": slug},
            )
        else:
            out[key] = None
    return out


def _firma_field_bytes(field_file) -> bytes | None:
    """Lee bytes de un ImageField (FieldFile o storage por nombre)."""
    if not field_file or not field_file.name:
        return None
    name = field_file.name
    raw: bytes | None = None
    try:
        with field_file.open("rb") as f:
            raw = f.read()
    except OSError:
        raw = None
    if not raw:
        try:
            with default_storage.open(name, "rb") as f:
                raw = f.read()
        except OSError:
            return None
    return raw if raw else None


def _firma_field_temp_file_uri(field_file) -> tuple[str | None, str | None]:
    """
    Copia la firma a un PNG temporal y devuelve (URI file:// para <img>, ruta para borrar).
    Evita data-URIs enormes en el HTML, que algunos motores PDF no renderizan bien.
    """
    raw = _firma_field_bytes(field_file)
    if not raw:
        return None, None
    fd, path = tempfile.mkstemp(prefix="pbr-fa-firma-", suffix=".png")
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    return Path(path).as_uri(), path


def _formato_aceptacion_direccion_impreso() -> str:
    return getattr(
        settings,
        "PBR_FORMATO_ACEPTACION_DIRECCION",
        "16a Calle Oriente, Pol. C-1 #24, Col. El Molino, Distrito de San Miguel, San Miguel Centro, 7547-0186",
    )


def _formato_editar_acceso_permitido(request: HttpRequest) -> bool:
    """Misma regla que FormatoSuperuserGateMixin (edición del formato)."""
    u = request.user
    return bool(getattr(u, "is_superuser", False)) or _formato_superuser_gate_session_valid(
        request
    )


def _formato_aceptacion_tras_guardado_notificar(
    request: HttpRequest, formato: FormatoAceptacion, prev_firmas_completas: bool
) -> None:
    try:
        from docs.formato_aceptacion_notificacion import notificar_formato_pdf_tras_guardado

        notificar_formato_pdf_tras_guardado(request, formato, prev_firmas_completas)
    except Exception:
        logger.exception("Notificación automática del formato de aceptación tras guardar")


def _generar_pdf_formato_aceptacion_bytes(formato: FormatoAceptacion) -> bytes:
    """Genera el PDF con firmas; limpia PNG temporales. Exige firmas_completas en datos."""
    tmp_firmas: list[str] = []
    try:
        uri_a, p_a = _firma_field_temp_file_uri(formato.firma_aceptante)
        uri_v, p_v = _firma_field_temp_file_uri(formato.firma_vendedor)
        uri_z, p_z = _firma_field_temp_file_uri(formato.firma_autorizado)
        for p in (p_a, p_v, p_z):
            if p:
                tmp_firmas.append(p)
        if not (uri_a and uri_v and uri_z):
            logger.warning(
                "PDF formato aceptación pk=%s: no se leyeron los 3 archivos de firma.",
                formato.pk,
            )
        from docs.services import branding_pdf_context

        proyecto = _proyecto_para_pdf_formato(formato)
        ctx = {
            "formato": formato,
            "proyecto": proyecto,
            "razon_social": getattr(
                settings,
                "PBR_PROMESA_RAZON_SOCIAL_VENDEDOR",
                "PAREDES BIENES RAÍCES",
            ),
            "direccion_empresa": _formato_aceptacion_direccion_impreso(),
            "pie_inmobiliaria": "Formato de aceptación — documento interno",
            "firma_aceptante_src": uri_a,
            "firma_vendedor_src": uri_v,
            "firma_autorizado_src": uri_z,
            "formato_pdf_credito_extra_bd": formato_aceptacion_credito_extra_columns_ready(),
            "formato_listado_cuotas": filas_listado_cuotas_formato_aceptacion(formato),
            **branding_pdf_context(proyecto),
        }
        return generar_pdf_desde_plantilla(
            template_name="docs/formato_aceptacion_pdf.html",
            context=ctx,
        )
    finally:
        for path in tmp_firmas:
            try:
                os.unlink(path)
            except OSError:
                pass


def _proyecto_para_pdf_formato(formato: FormatoAceptacion):
    """Cabecera PDF: proyecto del contrato o nombre libre del formulario."""
    c = formato.contrato
    if c is not None and c.inmueble_id:
        return c.inmueble.proyecto
    nombre = (formato.nombre_proyecto or "").strip() or "—"
    return SimpleNamespace(
        nombre=nombre,
        direccion="",
        municipio="",
        departamento="",
    )


def _proyectos_para_formato_aceptacion() -> list[dict]:
    """Catálogo para el selector que rellena nombre y dirección del terreno en el formato."""
    rows = []
    for p in Proyecto.objects.filter(activo=True).order_by("nombre"):
        rows.append(
            {
                "id": p.pk,
                "nombre": p.nombre,
                "direccion": p.direccion,
                "porcentaje_prima": (
                    str(p.porcentaje_prima) if p.porcentaje_prima is not None else ""
                ),
                "porcentaje_reserva": (
                    str(p.porcentaje_reserva) if p.porcentaje_reserva is not None else ""
                ),
            }
        )
    return rows


def _catalogo_inmuebles_formato_aceptacion() -> dict:
    """Polígonos por proyecto, lotes por polígono (o sin polígono) e índice por id de inmueble."""
    from inmobiliaria.etapa_venta import etapa_para_proyecto, precio_lote_en_etapa

    polis_por_proyecto: dict[int, list[dict]] = defaultdict(list)
    for pol in (
        Poligono.objects.filter(proyecto__activo=True)
        .select_related("proyecto")
        .order_by("proyecto_id", "orden", "nombre")
    ):
        polis_por_proyecto[pol.proyecto_id].append({"id": pol.pk, "nombre": pol.nombre})

    etapas_por_proyecto: dict[int, dict] = {}
    lotes_por_clave: dict[str, list[dict]] = defaultdict(list)
    inmueble_por_id: dict[str, dict] = {}
    for inv in (
        Inmueble.objects.filter(proyecto__activo=True)
        .select_related("poligono", "proyecto", "cliente_reserva")
        .order_by("proyecto_id", "poligono_id", "codigo")
    ):
        if inv.proyecto_id not in etapas_por_proyecto:
            etapas_por_proyecto[inv.proyecto_id] = etapa_para_proyecto(inv.proyecto_id)
        etapa = etapas_por_proyecto[inv.proyecto_id]
        precio_etapa = precio_lote_en_etapa(inv, etapa["codigo"])
        clave = str(inv.poligono_id) if inv.poligono_id else f"np:{inv.proyecto_id}"
        pol_nombre = inv.poligono.nombre if inv.poligono_id else ""
        cli = inv.cliente_reserva
        cli_txt = ""
        if cli is not None:
            cli_txt = f"{(cli.nombres or '').strip()} {(cli.apellidos or '').strip()}".strip()
        entry = {
            "id": inv.pk,
            "codigo": inv.codigo,
            "precio": str(precio_etapa if precio_etapa is not None else inv.precio_lista),
            "precio_preventa": str(inv.precio_preventa) if inv.precio_preventa is not None else "",
            "precio_promocional": str(inv.precio_promocional)
            if inv.precio_promocional is not None
            else "",
            "precio_pos_preventa": str(inv.precio_pos_preventa)
            if inv.precio_pos_preventa is not None
            else "",
            "etapa_codigo": etapa["codigo"],
            "etapa_label": etapa["label"],
            "etapa_rango": etapa["rango_label"],
            "comprometidos": etapa["comprometidos"],
            "area_m2": str(inv.area_m2) if inv.area_m2 is not None else "",
            "area_v2": str(inv.area_varas_cuadradas)
            if inv.area_varas_cuadradas is not None
            else "",
            "poligono_nombre": pol_nombre,
            "proyecto_id": inv.proyecto_id,
            "clave_poligono": clave,
            "estado": inv.estado,
            "estado_label": inv.get_estado_display(),
            "cliente_reserva": cli_txt,
            "reserva_hasta": (
                inv.reserva_hasta.isoformat() if inv.reserva_hasta else ""
            ),
            "ocupado": inv.estado
            in (
                Inmueble.Estado.RESERVADO,
                Inmueble.Estado.VENDIDO,
                Inmueble.Estado.BLOQUEADO,
            ),
        }
        lotes_por_clave[clave].append(entry)
        inmueble_por_id[str(inv.pk)] = entry

    return {
        "poligonosPorProyecto": {str(k): v for k, v in polis_por_proyecto.items()},
        "lotesPorClave": dict(lotes_por_clave),
        "inmueblePorId": inmueble_por_id,
        "etapasPorProyecto": {str(k): v for k, v in etapas_por_proyecto.items()},
    }


def _formato_aceptacion_form_sections(form: forms.FormatoAceptacionForm) -> list[dict]:
    """Agrupa campos del formato impreso (omite filas vacías si el formulario no incluye un campo)."""

    def G(name: str):
        if name not in form.fields:
            return None
        return form.__getitem__(name)

    def row(*cells):
        r = [c for c in cells if c is not None]
        return r if r else None

    def rows_compact(*row_defs):
        return [r for r in row_defs if r]

    return [
        {
            "title": "Datos personales",
            "rows": rows_compact(
                row(G("nombre_cliente")),
                row(G("lugar_nacimiento"), G("fecha_nacimiento")),
                row(G("dui_numero"), G("dui_exp_lugar"), G("dui_exp_fecha"), G("nit_numero")),
                row(G("direccion_domicilio"), G("telefono_domicilio")),
                row(G("direccion_notificacion"), G("telefono_notificacion")),
                row(G("trabaja_lo_propio"), G("nombre_empresa_trabajo")),
                row(G("direccion_trabajo"), G("telefono_trabajo")),
                row(G("cargo"), G("sueldo")),
                row(
                    G("num_familia_grupo"),
                    G("num_personas_trabajan"),
                    G("num_personas_estudian"),
                ),
            ),
        },
        {
            "title": "Referencias comerciales",
            "rows": rows_compact(
                row(G("ref_com_nombre_1"), G("ref_com_tel_1"), G("ref_com_obs_1")),
                row(G("ref_com_nombre_2"), G("ref_com_tel_2"), G("ref_com_obs_2")),
                row(G("ref_com_nombre_3"), G("ref_com_tel_3"), G("ref_com_obs_3")),
            ),
        },
        {
            "title": "Referencias personales",
            "rows": rows_compact(
                row(G("ref_per_nombre_1"), G("ref_per_tel_1"), G("ref_per_obs_1")),
                row(G("ref_per_nombre_2"), G("ref_per_tel_2"), G("ref_per_obs_2")),
                row(G("ref_per_nombre_3"), G("ref_per_tel_3"), G("ref_per_obs_3")),
            ),
        },
        {
            "title": "Datos del terreno",
            "rows": rows_compact(
                row(G("nombre_proyecto")),
                row(G("direccion_terreno")),
            ),
        },
        {
            "title": "Datos del crédito",
            "rows": rows_compact(
                row(G("area_m2_txt"), G("area_v2_txt")),
                row(G("valor_inmueble_sistema"), G("valor_inmueble")),
                row(G("valor_inmueble_solicitado"), G("precio_solicitud_motivo")),
                row(G("prima_1"), G("prima_1_fecha")),
                row(G("prima_2"), G("prima_2_fecha")),
                row(G("tipo_financiamiento")),
                row(G("valor_financiamiento"), G("letra_mensual")),
                row(G("plazo_txt"), G("num_cuota_txt"), G("interes_txt")),
                row(G("fecha_primera_cuota"), G("fecha_pago_mensual")),
                row(G("lugar_pago")),
                row(G("observaciones_financiamiento")),
            ),
        },
        {
            "title": "Beneficiarios",
            "rows": rows_compact(
                row(G("ben_nombre_1"), G("ben_parentesco_1"), G("ben_porcentaje_1")),
                row(G("ben_nombre_2"), G("ben_parentesco_2"), G("ben_porcentaje_2")),
            ),
        },
        {
            "title": "Elaborado por y cierre",
            "rows": rows_compact(
                row(G("elaborado_por"), G("lugar_y_fecha")),
            ),
        },
    ]


def _mapa_planos_proyectos():
    """Para el selector de polígono: URL y si es PDF por proyecto."""
    out = {}
    for p in Proyecto.objects.all():
        if p.plano_maestro and p.plano_maestro.name:
            out[str(p.pk)] = {
                "url": p.plano_maestro.url,
                "pdf": p.plano_maestro.name.lower().endswith(".pdf"),
            }
        else:
            out[str(p.pk)] = None
    return out


class AppLoginRequiredMixin(LoginRequiredMixin):
    login_url = reverse_lazy("login")

    def dispatch(self, request: HttpRequest, *args, **kwargs):
        if request.user.is_authenticated:
            from core.marcas import (
                SESSION_KEY,
                es_desarrollos,
                marca_from_session,
                ruta_solo_bienes_raices,
            )
            from inmobiliaria.vendedor_acceso import redirigir_vendedor_si_fuera_de_flujo
            from usuarios.roles import puede_acceder_marca, slug_unica_permitida

            marca = marca_from_session(request)
            if marca is None:
                unica = slug_unica_permitida(request.user)
                if unica:
                    from core.marcas import set_marca

                    set_marca(request, unica)
                    marca = marca_from_session(request)
                else:
                    return HttpResponseRedirect(reverse("elegir_marca"))
            elif not puede_acceder_marca(request.user, marca.get("slug")):
                request.session.pop(SESSION_KEY, None)
                unica = slug_unica_permitida(request.user)
                if unica:
                    from core.marcas import set_marca

                    set_marca(request, unica)
                else:
                    return HttpResponseRedirect(reverse("elegir_marca"))
                return HttpResponseRedirect(reverse("dashboard"))
            match = getattr(request, "resolver_match", None)
            url_name = getattr(match, "url_name", None) if match else None
            if es_desarrollos(marca) and ruta_solo_bienes_raices(url_name):
                messages.warning(
                    request,
                    "Ese módulo pertenece a Paredes Bienes Raíces (alquileres / venta de casas e inmuebles). "
                    "Cambie de empresa o use Gestión de Desarrollos (proyectos y lotes).",
                )
                return HttpResponseRedirect(reverse("dashboard"))
            blocked = redirigir_vendedor_si_fuera_de_flujo(request)
            if blocked is not None:
                return blocked
        return super().dispatch(request, *args, **kwargs)


class FormatoSuperuserGateMixin:
    """
    Editar o eliminar formato de aceptación: exige validar usuario + contraseña de un superusuario,
    salvo que quien navega ya sea superusuario. Tras validar, aplica el mismo TTL que la reauth sensible.
    """

    def dispatch(self, request: HttpRequest, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        if _formato_superuser_gate_session_valid(request):
            return super().dispatch(request, *args, **kwargs)
        nxt = request.get_full_path()
        gate = f"{reverse('app:formato_superuser_gate')}?{urlencode({'next': nxt})}"
        return HttpResponseRedirect(gate)


@login_required
def sensitive_reauth(request: HttpRequest) -> HttpResponse:
    """Pantalla para confirmar contraseña y abrir ventana de edición (no superusuarios)."""
    next_url = safe_next_url(request, request.POST.get("next") or request.GET.get("next"))
    if skips_sensitive_reauth(request.user):
        return HttpResponseRedirect(next_url)
    if request.method == "POST":
        pwd = (request.POST.get("password") or "").strip()
        if request.user.check_password(pwd):
            grant(request)
            messages.success(request, "Acceso confirmado.")
            return HttpResponseRedirect(next_url)
        messages.error(request, "Contraseña incorrecta.")
    return render(request, "app/sensitive_reauth.html", {"next": next_url})


@login_required
def formato_superuser_gate(request: HttpRequest) -> HttpResponse:
    """Pantalla para ingresar usuario y contraseña de superusuario antes de editar/eliminar formatos."""
    next_url = safe_next_url(
        request, request.POST.get("next") or request.GET.get("next")
    )
    if request.user.is_superuser:
        return HttpResponseRedirect(next_url)
    if _formato_superuser_gate_session_valid(request):
        return HttpResponseRedirect(next_url)
    if request.method == "POST":
        su_user = (request.POST.get("superuser_username") or "").strip()
        su_pass = (request.POST.get("superuser_password") or "").strip()
        if _verify_superuser_credentials(su_user, su_pass):
            request.session[PBR_SESSION_FORMATO_SUPER_GATE] = time.time() + ttl_seconds()
            request.session.modified = True
            messages.success(
                request,
                "Superusuario verificado. Puede editar o eliminar formatos de aceptación durante unos minutos.",
            )
            return HttpResponseRedirect(next_url)
        messages.error(
            request,
            "Usuario o contraseña de superusuario incorrectos.",
        )
    return render(
        request,
        "app/formato_superuser_gate.html",
        {"next": next_url},
    )


class AppIndexView(AppLoginRequiredMixin, TemplateView):
    """Hub de módulos (menú de gestión) con resumen de datos confiables."""

    template_name = "app/index.html"

    def dispatch(self, request: HttpRequest, *args, **kwargs):
        from core.marcas import es_bienes_raices, marca_from_session
        from inmobiliaria.vendedor_acceso import es_vendedor_restringido

        # Vendedor: solo su hub de flujo (también en Bienes Raíces).
        if request.user.is_authenticated and es_vendedor_restringido(request.user):
            return super().dispatch(request, *args, **kwargs)
        # Bienes Raíces es un sistema aparte: entra por su dashboard, no por Gestión.
        if request.user.is_authenticated and es_bienes_raices(marca_from_session(request)):
            return HttpResponseRedirect(reverse("dashboard"))
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        from inmobiliaria.vendedor_acceso import es_vendedor_restringido

        if es_vendedor_restringido(self.request.user):
            return ["app/index_vendedor.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        from core.dashboard_data import build_gestion_hub_context
        from inmobiliaria.contratos_acceso import (
            filtrar_contratos_queryset_por_vendedor,
            vendedor_catalogo_activo_vinculado,
        )
        from inmobiliaria.models import Contrato, Pago
        from inmobiliaria.vendedor_acceso import es_vendedor_restringido

        ctx = super().get_context_data(**kwargs)
        if es_vendedor_restringido(self.request.user):
            user = self.request.user
            vc = vendedor_catalogo_activo_vinculado(user)
            nombre = ""
            if vc is not None:
                nombre = (vc.nombre_completo or "").strip()
            if not nombre:
                nombre = (user.get_full_name() or "").strip() or user.get_username()
            contratos_qs = filtrar_contratos_queryset_por_vendedor(
                Contrato.objects.all(), user
            )
            pagos_qs = Pago.objects.filter(contrato__in=contratos_qs)
            ctx["vend_nombre"] = nombre.split()[0] if nombre else ""
            ctx["vend_contratos_activos"] = contratos_qs.filter(
                estado=Contrato.Estado.ACTIVO
            ).count()
            ctx["vend_pagos_pendientes"] = pagos_qs.filter(
                validacion_abono=Pago.ValidacionAbono.PENDIENTE
            ).count()
            from inmobiliaria.comision_vendedor import resumen_progreso_comision_vendedor

            ctx["vend_progreso_comision"] = resumen_progreso_comision_vendedor(user)
            return ctx
        ctx.update(
            build_gestion_hub_context(
                user=self.request.user,
                incluir_vendedores=puede_gestionar_vendedores(self.request.user),
                contratos_restringidos=aplica_restriccion_contratos_por_vendedor(
                    self.request.user
                ),
            )
        )
        return ctx

class MapaEditorView(AppLoginRequiredMixin, TemplateView):
    template_name = "app/mapa_editor.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["proyectos"] = Proyecto.objects.order_by("nombre")
        ctx["poligonos"] = Poligono.objects.select_related("proyecto").order_by(
            "proyecto__nombre", "orden", "nombre"
        )
        return ctx


# ——— Proyectos ———
class ProyectoListView(AppLoginRequiredMixin, ListView):
    model = Proyecto
    template_name = "app/proyecto_list.html"
    context_object_name = "items"
    paginate_by = 25


class ProyectoCreateView(AppLoginRequiredMixin, CreateView):
    model = Proyecto
    form_class = forms.ProyectoForm
    template_name = "app/proyecto_form.html"
    success_url = reverse_lazy("app:proyecto_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo proyecto"
        ctx["cancel_url"] = reverse_lazy("app:proyecto_list")
        ctx["form_multipart"] = True
        return ctx


class ProyectoUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = Proyecto
    form_class = forms.ProyectoForm
    template_name = "app/proyecto_form.html"
    success_url = reverse_lazy("app:proyecto_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar proyecto"
        ctx["cancel_url"] = reverse_lazy("app:proyecto_list")
        ctx["form_multipart"] = True
        return ctx


# ——— Polígonos ———
class PoligonoListView(AppLoginRequiredMixin, ListView):
    model = Poligono
    template_name = "app/poligono_list.html"
    context_object_name = "items"
    paginate_by = 30
    queryset = Poligono.objects.select_related("proyecto")  # plano maestro en proyecto


class PoligonoCreateView(AppLoginRequiredMixin, CreateView):
    model = Poligono
    form_class = forms.PoligonoForm
    template_name = "app/poligono_form.html"
    success_url = reverse_lazy("app:poligono_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo polígono"
        ctx["cancel_url"] = reverse_lazy("app:poligono_list")
        ctx["form_multipart"] = True
        ctx["proyecto_planos_map"] = _mapa_planos_proyectos()
        return ctx


class PoligonoUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = Poligono
    form_class = forms.PoligonoForm
    template_name = "app/poligono_form.html"
    success_url = reverse_lazy("app:poligono_list")
    queryset = Poligono.objects.select_related("proyecto")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar polígono"
        ctx["cancel_url"] = reverse_lazy("app:poligono_list")
        ctx["form_multipart"] = True
        ctx["proyecto_planos_map"] = _mapa_planos_proyectos()
        return ctx


# ——— Inmuebles ———
def _bloquear_si_desarrollos(request: HttpRequest) -> HttpResponse | None:
    """Alquileres y venta de casas/inmuebles no existen en Desarrollos."""
    from core.marcas import es_desarrollos, marca_from_session

    marca = marca_from_session(request)
    if marca is None:
        return HttpResponseRedirect(reverse("elegir_marca"))
    if es_desarrollos(marca):
        messages.warning(
            request,
            "Ese módulo pertenece a Paredes Bienes Raíces. "
            "En Desarrollos use proyectos, lotes, contratos y cartera.",
        )
        return HttpResponseRedirect(reverse("dashboard"))
    return None


@login_required
def inmuebles_alquiler_hub(request: HttpRequest) -> HttpResponse:
    """Centro de alquileres: locales, casas e inquilino por ficha."""
    bloqueo = _bloquear_si_desarrollos(request)
    if bloqueo:
        return bloqueo
    return render(
        request,
        "app/inmuebles_alquiler_hub.html",
        {
            "page_title": "Alquileres",
            "page_meta": (
                "Locales y casas en arrendamiento. Asigne al cliente como "
                "inquilino en la ficha de cada inmueble."
            ),
        },
    )


@login_required
def inmuebles_venta_hub(request: HttpRequest) -> HttpResponse:
    """Centro de venta: casas, lotes, reservas y comisión al asesor de ventas."""
    bloqueo = _bloquear_si_desarrollos(request)
    if bloqueo:
        return bloqueo
    return render(
        request,
        "app/inmuebles_venta_hub.html",
        {
            "page_title": "Venta de inmuebles",
            "page_meta": (
                "Inventario de casas y lotes. Marque apartado con cliente reserva; "
                "el contrato formal se crea en Gestión."
            ),
        },
    )


def _inmueble_url_listado_tras_tipo(tipo: str, *, en_alquiler: bool = False) -> str:
    if en_alquiler:
        if tipo == Inmueble.Tipo.LOCAL:
            return reverse("app:arrendamiento_locales_list")
        if tipo in (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA):
            return reverse("app:arrendamiento_casas_list")
    if tipo in (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA):
        return reverse("app:inmueble_casa_list")
    return reverse("app:inmueble_list")


def _inmueble_ficha_alquiler_url(inmueble: Inmueble) -> str | None:
    if not inmueble.en_alquiler:
        return None
    if inmueble.tipo == Inmueble.Tipo.LOCAL:
        return reverse("app:local_alquiler_ficha", args=[inmueble.pk])
    if inmueble.tipo in (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA):
        return reverse("app:casa_alquiler_ficha", args=[inmueble.pk])
    return None


class InmuebleLoteListView(AppLoginRequiredMixin, ListView):
    """Lotes y locales (sin casas); equivalente al inventario «inmueble lote» de antes."""

    model = Inmueble
    template_name = "app/inmueble_list.html"
    context_object_name = "items"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Inmueble.objects.select_related("proyecto", "poligono")
            .filter(en_alquiler=False)
            .exclude(
                tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA),
            )
            .order_by("proyecto__nombre", "poligono__orden", "codigo")
        )
        from core.marcas import es_desarrollos, marca_from_session

        # Desarrollos: solo lotes de lotificación (sin locales ni casas).
        if es_desarrollos(marca_from_session(self.request)):
            qs = qs.filter(tipo=Inmueble.Tipo.LOTE)
        pid = (self.request.GET.get("proyecto") or "").strip()
        if pid.isdigit():
            qs = qs.filter(proyecto_id=int(pid))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from core.marcas import es_desarrollos, marca_from_session

        if es_desarrollos(marca_from_session(self.request)):
            ctx["listado_page_title"] = "Lotes de lotificación"
            ctx["listado_meta"] = "Inventario de lotes por proyecto y polígono (sistema Desarrollos)."
            ctx["nuevo_boton_label"] = "Nuevo lote"
        else:
            ctx["listado_page_title"] = "Inmueble lote"
            ctx["listado_meta"] = "Lotes y locales comerciales por proyecto y polígono (sin casas)."
            ctx["nuevo_boton_label"] = "Nuevo lote o local"
        pid = (self.request.GET.get("proyecto") or "").strip()
        if pid.isdigit():
            proy = Proyecto.objects.filter(pk=int(pid)).first()
            if proy:
                ctx["listado_page_title"] = f"Lotes · {proy.nombre}"
                ctx["listado_meta"] = (
                    f"Inventario del proyecto activo «{proy.nombre}» "
                    "(disponibles, reserva y pagados)."
                )
        ctx["nuevo_url"] = reverse("app:inmueble_create")
        ctx["es_listado_casas"] = False
        return ctx

class InmuebleCasaListView(AppLoginRequiredMixin, ListView):
    """Solo casas nuevas o de segunda en venta (excluye módulo de alquiler)."""

    model = Inmueble
    template_name = "app/inmueble_list.html"
    context_object_name = "items"
    paginate_by = 25

    def get_queryset(self):
        return (
            Inmueble.objects.select_related("proyecto", "poligono")
            .filter(
                tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA),
                en_alquiler=False,
            )
            .order_by("proyecto__nombre", "codigo")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["listado_page_title"] = "Casa nueva o usada"
        ctx["listado_meta"] = "Inventario de viviendas; use «Casa y fotos» para la ficha ampliada y galería."
        ctx["nuevo_url"] = reverse("app:inmueble_casa_create")
        ctx["nuevo_boton_label"] = "Nueva casa"
        ctx["es_listado_casas"] = True
        return ctx


class ArrendamientoListProgrammingErrorMixin:
    """
    Si en producción no se ejecutó migrate (p. ej. falta 0030_en_alquiler),
    el filtro por en_alquiler provoca ProgrammingError: mensaje claro en lugar de página amarilla.
    """

    def get(self, request, *args, **kwargs):
        try:
            return super().get(request, *args, **kwargs)
        except ProgrammingError as exc:
            if "en_alquiler" not in str(exc):
                raise
            messages.error(
                request,
                "Faltan migraciones en la base de datos (columna «en alquiler»). "
                "Ejecute: python manage.py migrate --noinput. "
                "En DigitalOcean use como Run Command: bash scripts/run_web.sh",
            )
            return HttpResponseRedirect(reverse("app:index"))


class ArrendamientoLocalesListView(
    AppLoginRequiredMixin, ArrendamientoListProgrammingErrorMixin, ListView
):
    """Locales comerciales marcados para alquiler."""

    model = Inmueble
    template_name = "app/inmueble_list.html"
    context_object_name = "items"
    paginate_by = 25

    def get_queryset(self):
        return (
            Inmueble.objects.select_related("proyecto", "poligono")
            .filter(tipo=Inmueble.Tipo.LOCAL, en_alquiler=True)
            .order_by("proyecto__nombre", "poligono__orden", "codigo")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["listado_page_title"] = "Listado de alquileres de local"
        ctx["listado_meta"] = (
            "Listado de lo guardado en este módulo. «Nuevo alquiler de local» solo pide la ficha de arrendamiento y fotos; no usa el formulario de lotes."
        )
        ctx["nuevo_url"] = reverse("app:local_alquiler_create")
        ctx["nuevo_boton_label"] = "Nuevo alquiler de local"
        ctx["es_listado_casas"] = False
        ctx["es_listado_locales_alquiler"] = True
        return ctx


class ArrendamientoCasasListView(
    AppLoginRequiredMixin, ArrendamientoListProgrammingErrorMixin, ListView
):
    """Casas (nueva o segunda) marcadas para alquiler."""

    model = Inmueble
    template_name = "app/inmueble_list.html"
    context_object_name = "items"
    paginate_by = 25

    def get_queryset(self):
        return (
            Inmueble.objects.select_related("proyecto", "poligono")
            .filter(
                tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA),
                en_alquiler=True,
            )
            .order_by("proyecto__nombre", "codigo")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["listado_page_title"] = "Listado de casas en alquiler"
        ctx["listado_meta"] = (
            "Listado de lo guardado en este módulo. «Nuevo alquiler de casa» solo pide la ficha de arrendamiento de vivienda y fotos; no usa el formulario de «Nueva casa» (venta)."
        )
        ctx["nuevo_url"] = reverse("app:casa_alquiler_create")
        ctx["nuevo_boton_label"] = "Nuevo alquiler de casa"
        ctx["es_listado_casas"] = True
        ctx["es_listado_casas_alquiler"] = True
        return ctx


class InmuebleCreateLoteView(AppLoginRequiredMixin, CreateView):
    model = Inmueble
    form_class = forms.InmuebleForm
    template_name = "app/inmueble_form.html"
    success_url = reverse_lazy("app:inmueble_list")

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["modo_tipo"] = "lote_local"
        return kw

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo inmueble lote o local"
        ctx["cancel_url"] = reverse_lazy("app:inmueble_list")
        return ctx


class InmuebleCreateCasaView(AppLoginRequiredMixin, View):
    """Alta de casa en venta: tipo, código, precio y ficha (sin proyecto ni alquiler)."""

    template_name = "app/inmueble_casa_alta.html"

    def get(self, request, *args, **kwargs):
        form = forms.InmuebleCasaAltaForm(modo_tipo="casa")
        casa_form = forms.InmuebleDetalleCasaForm(prefix="casa")
        return render(request, self.template_name, self._ctx(form, casa_form))

    def post(self, request, *args, **kwargs):
        form = forms.InmuebleCasaAltaForm(request.POST, request.FILES, modo_tipo="casa")
        casa_form = forms.InmuebleDetalleCasaForm(
            request.POST, request.FILES, prefix="casa"
        )
        if form.is_valid() and casa_form.is_valid():
            with transaction.atomic():
                inmueble = form.save()
                detalle = casa_form.save(commit=False)
                detalle.inmueble = inmueble
                detalle.save()
            messages.success(request, "Casa registrada con su ficha de venta.")
            messages.info(
                request,
                "Puede subir o revisar fotos en «Casa y fotos» desde el listado o el menú lateral.",
            )
            return HttpResponseRedirect(
                reverse("app:inmueble_casa_galeria", kwargs={"pk": inmueble.pk})
            )
        return render(request, self.template_name, self._ctx(form, casa_form))

    def _ctx(self, form, casa_form):
        return {
            "form": form,
            "casa_form": casa_form,
            "form_title": "Nueva casa (nueva o de segunda)",
            "cancel_url": reverse("app:inmueble_casa_list"),
        }


class InmuebleUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = Inmueble
    form_class = forms.InmuebleForm
    template_name = "app/inmueble_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        ficha_url = _inmueble_ficha_alquiler_url(self.object)
        if ficha_url is not None:
            messages.info(
                request,
                "Este inmueble pertenece al módulo de alquileres. Use la ficha de arrendamiento.",
            )
            return HttpResponseRedirect(ficha_url)
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self) -> str:
        return _inmueble_url_listado_tras_tipo(
            self.object.tipo, en_alquiler=self.object.en_alquiler
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar inmueble"
        ctx["cancel_url"] = _inmueble_url_listado_tras_tipo(
            self.object.tipo, en_alquiler=self.object.en_alquiler
        )
        ctx["historial_precios"] = self.object.historial_precios.all()[:50]
        if self.object.pk:
            ctx["inmueble_imagenes"] = _inmueble_imagenes_ordenadas(self.object)
        else:
            ctx["inmueble_imagenes"] = []
        return ctx

    def form_valid(self, form):
        tipo = form.cleaned_data.get("tipo")
        resp = super().form_valid(form)
        if tipo not in (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA):
            InmuebleDetalleCasa.objects.filter(inmueble=self.object).delete()
            InmuebleDetalleCasaAlquiler.objects.filter(inmueble=self.object).delete()
        if tipo != Inmueble.Tipo.LOCAL:
            InmuebleDetalleLocalAlquiler.objects.filter(inmueble=self.object).delete()
        if self.request.user.is_authenticated and not skips_sensitive_reauth(self.request.user):
            grant(self.request)
        return resp


class InmuebleCasaGaleriaView(AppLoginRequiredMixin, SensitiveEditSessionMixin, View):
    """Ficha ampliada y galería solo para casa nueva o segunda (no mezcla con el formulario de lote)."""

    template_name = "app/inmueble_casa_galeria.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.inmueble = get_object_or_404(Inmueble, pk=self.kwargs["pk"])

    def dispatch(self, request, *args, **kwargs):
        if self.inmueble.tipo not in (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA):
            messages.warning(
                request,
                "«Casa y fotos» solo aplica a inmuebles tipo casa nueva o casa segunda.",
            )
            return HttpResponseRedirect(reverse("app:inmueble_casa_list"))
        if self.inmueble.en_alquiler:
            messages.info(
                request,
                "Esta casa está en el módulo de alquileres. Use la ficha de arrendamiento.",
            )
            return HttpResponseRedirect(
                reverse("app:casa_alquiler_ficha", args=[self.inmueble.pk])
            )
        return super().dispatch(request, *args, **kwargs)

    def _detalle_instance(self):
        try:
            return self.inmueble.detalle_casa
        except InmuebleDetalleCasa.DoesNotExist:
            return None

    def get_context_data(self, **kwargs):
        casa_form = kwargs.get("casa_form")
        if casa_form is None:
            casa_form = forms.InmuebleDetalleCasaForm(
                prefix="casa", instance=self._detalle_instance()
            )
        imgs = _inmueble_imagenes_ordenadas(self.inmueble)
        u = self.request.user
        return {
            "object": self.inmueble,
            "inmueble": self.inmueble,
            "casa_form": casa_form,
            "inmueble_imagenes": imgs,
            "form_title": f"Casa y fotos · {self.inmueble.codigo}",
            "cancel_url": reverse("app:inmueble_update", args=[self.inmueble.pk]),
            "form_multipart": True,
            "sensitive_password_required": bool(
                u.is_authenticated
                and not skips_sensitive_reauth(u)
                and not session_valid(self.request)
            ),
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.get_context_data())

    def post(self, request, *args, **kwargs):
        if not check_sensitive_write(request):
            messages.error(
                request,
                "Debe confirmar su contraseña de acceso (final del formulario) o usar «Confirmar acceso» en la app.",
            )
            casa_form = forms.InmuebleDetalleCasaForm(
                request.POST, request.FILES, prefix="casa", instance=self._detalle_instance()
            )
            return render(request, self.template_name, self.get_context_data(casa_form=casa_form))
        casa_form = forms.InmuebleDetalleCasaForm(
            request.POST, request.FILES, prefix="casa", instance=self._detalle_instance()
        )
        if not casa_form.is_valid():
            return render(request, self.template_name, self.get_context_data(casa_form=casa_form))
        # Guardar ficha y archivos del detalle en transacción aparte: si falla la galería o credenciales
        # de superusuario, no se pierden datos ni documentos ya validados.
        with transaction.atomic():
            det = casa_form.save(commit=False)
            det.inmueble = self.inmueble
            det.save()
        messages.success(
            request,
            "Ficha de casa guardada (texto y documentos adjuntos: escritura, recibos, plano, etc.).",
        )

        _guardar_galeria_inmueble_tras_ficha(request, self.inmueble)

        if request.user.is_authenticated and not skips_sensitive_reauth(request.user):
            grant(request)
        return HttpResponseRedirect(reverse("app:inmueble_casa_galeria", args=[self.inmueble.pk]))


def _crear_inmueble_local_para_ficha_alquiler() -> Inmueble | None:
    """
    Soporte técnico para el módulo independiente de alquiler de local: un Inmueble tipo LOCAL
    mínimo (código autogenerado) para enlazar InmuebleDetalleLocalAlquiler sin mostrar inventario.
    """
    proyecto = Proyecto.objects.order_by("pk").first()
    if not proyecto:
        return None
    for _ in range(80):
        codigo = f"ALQ-LOC-{uuid.uuid4().hex[:10].upper()}"
        if not Inmueble.objects.filter(proyecto=proyecto, codigo=codigo).exists():
            return Inmueble.objects.create(
                proyecto=proyecto,
                tipo=Inmueble.Tipo.LOCAL,
                estado=Inmueble.Estado.DISPONIBLE,
                codigo=codigo,
                precio_lista=Decimal("0"),
                en_alquiler=True,
            )
    return None


def _crear_inmueble_casa_para_ficha_alquiler() -> Inmueble | None:
    """
    Soporte técnico para el módulo independiente de casas en alquiler: Inmueble mínimo
    (casa de segunda por defecto, código autogenerado) para InmuebleDetalleCasaAlquiler.
    """
    proyecto = Proyecto.objects.order_by("pk").first()
    if not proyecto:
        return None
    for _ in range(80):
        codigo = f"ALQ-CAS-{uuid.uuid4().hex[:10].upper()}"
        if not Inmueble.objects.filter(proyecto=proyecto, codigo=codigo).exists():
            return Inmueble.objects.create(
                proyecto=proyecto,
                tipo=Inmueble.Tipo.CASA_SEGUNDA,
                estado=Inmueble.Estado.DISPONIBLE,
                codigo=codigo,
                precio_lista=Decimal("0"),
                en_alquiler=True,
            )
    return None


class LocalAlquilerCreateView(AppLoginRequiredMixin, SensitiveEditSessionMixin, View):
    """Alta independiente: solo ficha de arrendamiento + fotos (el inmueble se crea por detrás)."""

    template_name = "app/local_alquiler_ficha.html"

    def _ctx(self, local_form):
        u = self.request.user
        return {
            "object": None,
            "inmueble": None,
            "local_form": local_form,
            "inmueble_imagenes": [],
            "form_title": "Nuevo alquiler de local",
            "cancel_url": reverse("app:arrendamiento_locales_list"),
            "form_multipart": True,
            "es_alta_local_alquiler": True,
            "sensitive_password_required": bool(
                u.is_authenticated
                and not skips_sensitive_reauth(u)
                and not session_valid(self.request)
            ),
        }

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            self._ctx(forms.InmuebleDetalleLocalAlquilerForm()),
        )

    def post(self, request, *args, **kwargs):
        if not check_sensitive_write(request):
            messages.error(
                request,
                "Debe confirmar su contraseña de acceso (final del formulario) o usar «Confirmar acceso» en la app.",
            )
            return render(
                request,
                self.template_name,
                self._ctx(forms.InmuebleDetalleLocalAlquilerForm(request.POST)),
            )
        local_form = forms.InmuebleDetalleLocalAlquilerForm(request.POST)
        if not local_form.is_valid():
            return render(request, self.template_name, self._ctx(local_form))
        if not Proyecto.objects.exists():
            messages.error(
                request,
                "No hay ningún proyecto creado. Cree al menos un proyecto en la app y vuelva a intentar.",
            )
            return render(request, self.template_name, self._ctx(local_form))
        try:
            with transaction.atomic():
                inv = _crear_inmueble_local_para_ficha_alquiler()
                if not inv:
                    raise RuntimeError("No se pudo generar código de local.")
                det = local_form.save(commit=False)
                det.inmueble = inv
                det.save()
        except Exception:
            messages.error(request, "No se pudo guardar el alquiler de local. Intente de nuevo.")
            return render(request, self.template_name, self._ctx(local_form))
        messages.success(
            request,
            "Alquiler de local guardado. Puede seguir editando la ficha o subir fotos.",
        )
        _guardar_galeria_inmueble_tras_ficha(request, inv)
        if request.user.is_authenticated and not skips_sensitive_reauth(request.user):
            grant(request)
        return HttpResponseRedirect(reverse("app:local_alquiler_ficha", args=[inv.pk]))


class LocalAlquilerFichaView(AppLoginRequiredMixin, SensitiveEditSessionMixin, View):
    """Ficha de arrendamiento del local (módulo independiente del inventario de lotes)."""

    template_name = "app/local_alquiler_ficha.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.inmueble = get_object_or_404(Inmueble, pk=self.kwargs["pk"])

    def dispatch(self, request, *args, **kwargs):
        if self.inmueble.tipo != Inmueble.Tipo.LOCAL:
            messages.warning(
                request,
                "La ficha de alquiler solo aplica a inmuebles tipo local comercial.",
            )
            return HttpResponseRedirect(reverse("app:inmueble_list"))
        return super().dispatch(request, *args, **kwargs)

    def _detalle_instance(self):
        try:
            return self.inmueble.detalle_local_alquiler
        except InmuebleDetalleLocalAlquiler.DoesNotExist:
            return None

    def get_context_data(self, **kwargs):
        local_form = kwargs.get("local_form")
        if local_form is None:
            local_form = forms.InmuebleDetalleLocalAlquilerForm(
                instance=self._detalle_instance()
            )
        u = self.request.user
        return {
            "object": self.inmueble,
            "inmueble": self.inmueble,
            "local_form": local_form,
            "inmueble_imagenes": _inmueble_imagenes_ordenadas(self.inmueble),
            "form_title": f"Local en alquiler · {self.inmueble.codigo}",
            "cancel_url": reverse("app:arrendamiento_locales_list"),
            "form_multipart": True,
            "es_alta_local_alquiler": False,
            "sensitive_password_required": bool(
                u.is_authenticated
                and not skips_sensitive_reauth(u)
                and not session_valid(self.request)
            ),
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.get_context_data())

    def post(self, request, *args, **kwargs):
        if not check_sensitive_write(request):
            messages.error(
                request,
                "Debe confirmar su contraseña de acceso (final del formulario) o usar «Confirmar acceso» en la app.",
            )
            local_form = forms.InmuebleDetalleLocalAlquilerForm(
                request.POST, request.FILES, instance=self._detalle_instance()
            )
            return render(
                request,
                self.template_name,
                self.get_context_data(local_form=local_form),
            )
        local_form = forms.InmuebleDetalleLocalAlquilerForm(
            request.POST, request.FILES, instance=self._detalle_instance()
        )
        if not local_form.is_valid():
            return render(
                request,
                self.template_name,
                self.get_context_data(local_form=local_form),
            )
        with transaction.atomic():
            det = local_form.save(commit=False)
            det.inmueble = self.inmueble
            det.save()
        messages.success(
            request,
            "Ficha de alquiler del local guardada (fotos nuevas si las hubo).",
        )
        _guardar_galeria_inmueble_tras_ficha(request, self.inmueble)
        if request.user.is_authenticated and not skips_sensitive_reauth(request.user):
            grant(request)
        return HttpResponseRedirect(
            reverse("app:local_alquiler_ficha", args=[self.inmueble.pk])
        )


class CasaAlquilerCreateView(AppLoginRequiredMixin, SensitiveEditSessionMixin, View):
    """Alta independiente: solo ficha de arrendamiento de vivienda + fotos (formulario distinto al de local)."""

    template_name = "app/casa_alquiler_ficha.html"

    def _ctx(self, casa_alquiler_form):
        u = self.request.user
        return {
            "object": None,
            "inmueble": None,
            "casa_alquiler_form": casa_alquiler_form,
            "inmueble_imagenes": [],
            "form_title": "Nuevo alquiler de casa",
            "cancel_url": reverse("app:arrendamiento_casas_list"),
            "form_multipart": True,
            "es_alta_casa_alquiler": True,
            "sensitive_password_required": bool(
                u.is_authenticated
                and not skips_sensitive_reauth(u)
                and not session_valid(self.request)
            ),
        }

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            self._ctx(forms.InmuebleDetalleCasaAlquilerForm()),
        )

    def post(self, request, *args, **kwargs):
        if not check_sensitive_write(request):
            messages.error(
                request,
                "Debe confirmar su contraseña de acceso (final del formulario) o usar «Confirmar acceso» en la app.",
            )
            return render(
                request,
                self.template_name,
                self._ctx(forms.InmuebleDetalleCasaAlquilerForm(request.POST)),
            )
        casa_alquiler_form = forms.InmuebleDetalleCasaAlquilerForm(request.POST)
        if not casa_alquiler_form.is_valid():
            return render(request, self.template_name, self._ctx(casa_alquiler_form))
        if not Proyecto.objects.exists():
            messages.error(
                request,
                "No hay ningún proyecto creado. Cree al menos un proyecto en la app y vuelva a intentar.",
            )
            return render(request, self.template_name, self._ctx(casa_alquiler_form))
        try:
            with transaction.atomic():
                inv = _crear_inmueble_casa_para_ficha_alquiler()
                if not inv:
                    raise RuntimeError("No se pudo generar código de casa.")
                det = casa_alquiler_form.save(commit=False)
                det.inmueble = inv
                det.save()
        except Exception:
            messages.error(request, "No se pudo guardar el alquiler de casa. Intente de nuevo.")
            return render(request, self.template_name, self._ctx(casa_alquiler_form))
        messages.success(
            request,
            "Alquiler de casa guardado. Puede seguir editando la ficha o subir fotos.",
        )
        _guardar_galeria_inmueble_tras_ficha(request, inv)
        if request.user.is_authenticated and not skips_sensitive_reauth(request.user):
            grant(request)
        return HttpResponseRedirect(reverse("app:casa_alquiler_ficha", args=[inv.pk]))


class CasaAlquilerFichaView(AppLoginRequiredMixin, SensitiveEditSessionMixin, View):
    """Ficha de arrendamiento de vivienda (módulo independiente del inventario de casas en venta)."""

    template_name = "app/casa_alquiler_ficha.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.inmueble = get_object_or_404(Inmueble, pk=self.kwargs["pk"])

    def dispatch(self, request, *args, **kwargs):
        if self.inmueble.tipo not in (
            Inmueble.Tipo.CASA_NUEVA,
            Inmueble.Tipo.CASA_SEGUNDA,
        ):
            messages.warning(
                request,
                "La ficha de alquiler de casa solo aplica a viviendas (casa nueva o de segunda).",
            )
            return HttpResponseRedirect(reverse("app:inmueble_casa_list"))
        return super().dispatch(request, *args, **kwargs)

    def _detalle_instance(self):
        try:
            return self.inmueble.detalle_casa_alquiler
        except InmuebleDetalleCasaAlquiler.DoesNotExist:
            return None

    def get_context_data(self, **kwargs):
        casa_alquiler_form = kwargs.get("casa_alquiler_form")
        if casa_alquiler_form is None:
            casa_alquiler_form = forms.InmuebleDetalleCasaAlquilerForm(
                instance=self._detalle_instance()
            )
        u = self.request.user
        return {
            "object": self.inmueble,
            "inmueble": self.inmueble,
            "casa_alquiler_form": casa_alquiler_form,
            "inmueble_imagenes": _inmueble_imagenes_ordenadas(self.inmueble),
            "form_title": f"Casa en alquiler · {self.inmueble.codigo}",
            "cancel_url": reverse("app:arrendamiento_casas_list"),
            "form_multipart": True,
            "es_alta_casa_alquiler": False,
            "sensitive_password_required": bool(
                u.is_authenticated
                and not skips_sensitive_reauth(u)
                and not session_valid(self.request)
            ),
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.get_context_data())

    def post(self, request, *args, **kwargs):
        if not check_sensitive_write(request):
            messages.error(
                request,
                "Debe confirmar su contraseña de acceso (final del formulario) o usar «Confirmar acceso» en la app.",
            )
            casa_alquiler_form = forms.InmuebleDetalleCasaAlquilerForm(
                request.POST, request.FILES, instance=self._detalle_instance()
            )
            return render(
                request,
                self.template_name,
                self.get_context_data(casa_alquiler_form=casa_alquiler_form),
            )
        casa_alquiler_form = forms.InmuebleDetalleCasaAlquilerForm(
            request.POST, request.FILES, instance=self._detalle_instance()
        )
        if not casa_alquiler_form.is_valid():
            return render(
                request,
                self.template_name,
                self.get_context_data(casa_alquiler_form=casa_alquiler_form),
            )
        with transaction.atomic():
            det = casa_alquiler_form.save(commit=False)
            det.inmueble = self.inmueble
            det.save()
        messages.success(
            request,
            "Ficha de alquiler de la casa guardada (fotos nuevas si las hubo).",
        )
        _guardar_galeria_inmueble_tras_ficha(request, self.inmueble)
        if request.user.is_authenticated and not skips_sensitive_reauth(request.user):
            grant(request)
        return HttpResponseRedirect(
            reverse("app:casa_alquiler_ficha", args=[self.inmueble.pk])
        )


# ——— Clientes ———
class ClienteListView(AppLoginRequiredMixin, ListView):
    model = Cliente
    template_name = "app/cliente_list.html"
    context_object_name = "items"
    paginate_by = 30

    def get_queryset(self):
        from django.db.models import Count

        return (
            Cliente.objects.annotate(
                num_contratos=Count("contratos", distinct=True),
                num_alquileres_local=Count("alquileres_local", distinct=True),
                num_alquileres_casa=Count("alquileres_casa", distinct=True),
                num_reservas=Count("inmuebles_reservados", distinct=True),
            )
            .order_by("apellidos", "nombres")
        )


def _guardar_documentos_cliente_upload(request, cliente: Cliente) -> None:
    desc = (request.POST.get("documento_descripcion_cliente") or "").strip()[:200]
    for f in request.FILES.getlist("documentos_cliente"):
        ClienteDocumento.objects.create(cliente=cliente, archivo=f, descripcion=desc)


class ClienteCreateView(AppLoginRequiredMixin, CreateView):
    model = Cliente
    form_class = forms.ClienteForm
    template_name = "app/cliente_form.html"
    success_url = reverse_lazy("app:cliente_list")

    def form_valid(self, form):
        try:
            with transaction.atomic():
                self.object = form.save()
                _guardar_documentos_cliente_upload(self.request, self.object)
        except Exception:
            messages.error(
                self.request,
                "No se pudieron guardar el cliente ni sus documentos. Revise los archivos e intente de nuevo.",
            )
            return self.form_invalid(form)
        messages.success(self.request, "Cliente guardado correctamente.")
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo cliente"
        ctx["cancel_url"] = reverse_lazy("app:cliente_list")
        ctx["form_multipart"] = True
        ctx["form_cliente_documentos"] = True
        ctx["documentos_cliente"] = []
        ctx["cliente_pk"] = None
        return ctx


class ClienteUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = Cliente
    form_class = forms.ClienteForm
    template_name = "app/cliente_form.html"
    success_url = reverse_lazy("app:cliente_list")

    def form_valid(self, form):
        try:
            with transaction.atomic():
                self.object = form.save()
                _guardar_documentos_cliente_upload(self.request, self.object)
        except Exception:
            messages.error(
                self.request,
                "No se pudieron guardar los cambios del cliente ni los documentos nuevos.",
            )
            return self.form_invalid(form)
        messages.success(self.request, "Cliente actualizado correctamente.")
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar cliente"
        ctx["cancel_url"] = reverse_lazy("app:cliente_list")
        ctx["form_multipart"] = True
        ctx["form_cliente_documentos"] = True
        obj = ctx.get("object")
        if obj and obj.pk:
            ctx["documentos_cliente"] = obj.documentos.all()
            ctx["cliente_pk"] = obj.pk
        else:
            ctx["documentos_cliente"] = []
            ctx["cliente_pk"] = None
        ctx["pdf_report_url"] = reverse("app:cliente_reporte_pdf", args=[self.object.pk])
        ctx["estado_cuenta_pdf_url"] = reverse(
            "app:cliente_estado_cuenta_pdf", args=[self.object.pk]
        )
        from inmobiliaria.cliente_inmuebles import build_cliente_inmuebles_context

        ctx.update(build_cliente_inmuebles_context(self.object))
        return ctx


@login_required
def estado_cuenta_hub(request: HttpRequest) -> HttpResponse:
    """Pantalla visible: elegir cliente/contrato e imprimir estado de cuenta PDF."""
    from inmobiliaria.contratos_acceso import filtrar_contratos_queryset_por_vendedor

    qs = (
        Contrato.objects.select_related(
            "cliente", "inmueble", "inmueble__proyecto", "vendedor_perfil"
        )
        .order_by("cliente__apellidos", "cliente__nombres", "-fecha_firma", "-pk")
    )
    qs = filtrar_contratos_queryset_por_vendedor(qs, request.user)
    items = list(qs[:200])
    # Clientes únicos (para PDF por cliente)
    clientes_vistos: set[int] = set()
    clientes_filas: list = []
    for c in items:
        if c.cliente_id in clientes_vistos:
            continue
        clientes_vistos.add(c.cliente_id)
        n_contratos = sum(1 for x in items if x.cliente_id == c.cliente_id)
        clientes_filas.append(
            {
                "cliente": c.cliente,
                "n_contratos": n_contratos,
                "ejemplo_proyecto": (
                    c.inmueble.proyecto.nombre
                    if c.inmueble_id and c.inmueble.proyecto_id
                    else "—"
                ),
            }
        )
    return render(
        request,
        "app/estado_cuenta_hub.html",
        {
            "page_title": "Estado de cuenta",
            "page_meta": (
                "PDF imprimible con logo del proyecto y logo de Paredes Desarrollos Inmobiliarios. "
                "Elija por cliente (todos sus contratos) o por un plan de pagos."
            ),
            "contratos": items,
            "clientes_filas": clientes_filas,
        },
    )


@login_required
def cliente_reporte_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    """PDF con los datos del cliente (ficha del formulario) y contratos / documentos."""
    cliente = get_object_or_404(Cliente, pk=pk)
    contratos = (
        Contrato.objects.filter(cliente=cliente)
        .select_related("inmueble", "inmueble__proyecto")
        .order_by("-fecha_firma", "-pk")
    )
    documentos_qs = cliente.documentos.order_by("-creado_en")[:80]
    documentos_reporte = []
    for d in documentos_qs:
        nom = ""
        if d.archivo and d.archivo.name:
            nom = d.archivo.name.replace("\\", "/").rsplit("/", 1)[-1]
        documentos_reporte.append(
            {"descripcion": d.descripcion, "nombre_archivo": nom or "—", "creado_en": d.creado_en}
        )
    from docs.services import branding_pdf_context

    razon = getattr(
        settings,
        "PBR_PROMESA_RAZON_SOCIAL_VENDEDOR",
        "PAREDES BIENES RAÍCES",
    )
    proy = None
    first = contratos.first()
    if first is not None and first.inmueble_id:
        proy = first.inmueble.proyecto
    pdf_bytes = generar_pdf_desde_plantilla(
        template_name="docs/reporte_cliente.html",
        context={
            "cliente": cliente,
            "contratos": contratos,
            "documentos": documentos_reporte,
            "emitido_en": timezone.now(),
            "razon_social": razon,
            "proyecto": proy,
            **branding_pdf_context(proy),
        },
    )
    base_name = f"reporte_cliente_{cliente.pk}_{cliente.apellidos}_{cliente.nombres}"
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in base_name).strip("._") or "reporte_cliente"
    safe = safe[:100]
    return HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'},
    )


@login_required
def cliente_estado_cuenta_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    """PDF imprimible: estado de cuenta detallado del cliente (logos proyecto + Desarrollos)."""
    from inmobiliaria.contratos_acceso import filtrar_contratos_queryset_por_vendedor
    from inmobiliaria.estado_cuenta import build_estado_cuenta_cliente_context

    cliente = get_object_or_404(Cliente, pk=pk)
    base = (
        Contrato.objects.filter(cliente=cliente)
        .select_related("inmueble", "inmueble__proyecto", "vendedor_perfil")
        .order_by("-fecha_firma", "-pk")
    )
    contratos = filtrar_contratos_queryset_por_vendedor(base, request.user)
    ctx = build_estado_cuenta_cliente_context(cliente, contratos_qs=contratos)
    pdf_bytes = generar_pdf_desde_plantilla(
        template_name="docs/estado_cuenta_cliente.html",
        context=ctx,
    )
    base_name = f"estado_cuenta_{cliente.pk}_{cliente.apellidos}_{cliente.nombres}"
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in base_name).strip("._") or "estado_cuenta"
    safe = safe[:100]
    return HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe}.pdf"'},
    )


@login_required
def contrato_estado_cuenta_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    """PDF del estado de cuenta de un contrato (mismo formato detallado, un solo contrato)."""
    from inmobiliaria.contratos_acceso import filtrar_contratos_queryset_por_vendedor
    from inmobiliaria.estado_cuenta import build_estado_cuenta_cliente_context

    base = Contrato.objects.select_related(
        "cliente", "inmueble", "inmueble__proyecto", "vendedor_perfil"
    )
    contrato = get_object_or_404(
        filtrar_contratos_queryset_por_vendedor(base, request.user),
        pk=pk,
    )
    qs = Contrato.objects.filter(pk=contrato.pk).select_related(
        "inmueble", "inmueble__proyecto", "vendedor_perfil"
    )
    ctx = build_estado_cuenta_cliente_context(contrato.cliente, contratos_qs=qs)
    pdf_bytes = generar_pdf_desde_plantilla(
        template_name="docs/estado_cuenta_cliente.html",
        context=ctx,
    )
    safe = f"estado_cuenta_contrato_{contrato.numero}".replace("/", "-")[:100]
    return HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe}.pdf"'},
    )


@login_required
@require_POST
def cliente_documento_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    doc = get_object_or_404(ClienteDocumento, pk=pk)
    cliente_id = doc.cliente_id
    if not check_sensitive_write(request):
        messages.error(
            request,
            "Debe confirmar su contraseña para eliminar documentos del expediente.",
        )
        next_url = reverse("app:cliente_update", args=[cliente_id])
        return HttpResponseRedirect(
            f"{reverse('app:sensitive_reauth')}?{urlencode({'next': next_url})}"
        )
    doc.delete()
    messages.success(request, "Documento eliminado.")
    return HttpResponseRedirect(reverse("app:cliente_update", args=[cliente_id]))


# ——— Vendedores (catálogo) ———
class VendedoresGestionMixin(AppLoginRequiredMixin, UserPassesTestMixin):
    login_url = reverse_lazy("login")

    def test_func(self) -> bool:
        return puede_gestionar_vendedores(self.request.user)


class VendedorListView(VendedoresGestionMixin, ListView):
    model = Vendedor
    template_name = "app/vendedor_list.html"
    context_object_name = "items"
    paginate_by = 30
    queryset = Vendedor.objects.all().order_by("apellidos", "nombres")


class VendedorCreateView(VendedoresGestionMixin, CreateView):
    model = Vendedor
    form_class = forms.VendedorForm
    template_name = "app/vendedor_form.html"
    success_url = reverse_lazy("app:vendedor_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo asesor de ventas"
        ctx["cancel_url"] = reverse_lazy("app:vendedor_list")
        return ctx


class VendedorUpdateView(VendedoresGestionMixin, SensitiveEditMixin, UpdateView):
    model = Vendedor
    form_class = forms.VendedorForm
    template_name = "app/vendedor_form.html"
    success_url = reverse_lazy("app:vendedor_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = f"Editar asesor de ventas: {self.object.nombre_completo}"
        ctx["cancel_url"] = reverse_lazy("app:vendedor_list")
        return ctx


class VendedorDeleteView(VendedoresGestionMixin, SensitiveDeleteMixin, DeleteView):
    model = Vendedor
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:vendedor_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar asesor de ventas"
        ctx["delete_blurb"] = (
            "Los contratos vinculados quedarán sin asesor de ventas del catálogo (no se borran contratos)."
        )
        return ctx


# ——— Contratos ———
class ContratoListView(AppLoginRequiredMixin, ListView):
    model = Contrato
    template_name = "app/contrato_list.html"
    context_object_name = "items"
    paginate_by = 25

    def get_queryset(self):
        qs = Contrato.objects.select_related(
            "cliente",
            "inmueble",
            "inmueble__proyecto",
            "vendedor",
            "vendedor_perfil",
        )
        return filtrar_contratos_queryset_por_vendedor(qs, self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["contratos_modo_solo_vendedor"] = aplica_restriccion_contratos_por_vendedor(user)
        ctx["contratos_ve_todos"] = usuario_ve_todos_los_contratos(user)
        vc = vendedor_catalogo_activo_vinculado(user)
        ctx["vendedor_catalogo_ctx"] = vc
        if ctx["contratos_modo_solo_vendedor"]:
            resumen_qs = self.get_queryset().only(
                "id", "comision_monto", "comision_porcentaje", "precio_final"
            )
            total, con_m, n = totales_comision_contratos(resumen_qs)
            ctx["contratos_resumen_total"] = n
            ctx["contratos_resumen_comision_suma"] = total
            ctx["contratos_resumen_comision_con_monto"] = con_m

        return ctx


class ContratoCreateView(AppLoginRequiredMixin, CreateView):
    model = Contrato
    form_class = forms.PlanPagosForm
    template_name = "app/contrato_form.html"
    success_url = reverse_lazy("app:contrato_list")

    def get_initial(self):
        initial = super().get_initial()
        raw = self.request.GET.get("cliente")
        if raw:
            try:
                cid = int(raw)
                if Cliente.objects.filter(pk=cid).exists():
                    initial["cliente"] = cid
            except (TypeError, ValueError):
                pass
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["filtro_proyecto_id"] = self.request.GET.get("proyecto") or None
        kwargs["filtro_poligono_id"] = self.request.GET.get("poligono") or None
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Paso 5 · Nuevo plan de pagos (desde el mes 13)"
        ctx["cancel_url"] = reverse_lazy("app:contrato_list")
        ctx["form_inmueble_filters"] = False
        ctx["form_contrato_autocomplete_off"] = True
        ctx["form_contrato_credito_panel"] = True
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        from inmobiliaria.cuotas_calendario import aplicar_calendario_desde_formato_cliente

        n = aplicar_calendario_desde_formato_cliente(
            self.object,
            descuento=self.object.descuento_efectivo_monto,
            prima=form.cleaned_data.get("prima_monto"),
            forzar=True,
        )
        if n:
            messages.success(
                self.request,
                f"Plan de pagos #{self.object.numero} guardado con {n} cuotas "
                f"(deuda con interés desde el mes 13). Es el único plan de este tipo para el cliente.",
            )
        else:
            messages.success(
                self.request,
                f"Plan de pagos #{self.object.numero} guardado. "
                "Es el único plan post–mes 13 permitido para este cliente.",
            )
        return response


@login_required
def contrato_credito_cliente_json(request: HttpRequest, cliente_id: int) -> JsonResponse:
    """
    Carga el crédito a plazos del formato de aceptación del cliente y calcula
    nueva deuda tras descuento y abonos de los meses 1–12.
    """
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    desc_raw = (request.GET.get("descuento") or "").strip().replace(",", "")
    descuento = None
    if desc_raw:
        try:
            descuento = Decimal(desc_raw)
        except Exception:
            descuento = None
    prima_raw = (request.GET.get("prima") or "").strip().replace(",", "")
    prima = None
    if prima_raw:
        try:
            prima = Decimal(prima_raw)
        except Exception:
            prima = None
    from inmobiliaria.credito_contrato import credito_plazos_para_cliente

    data = credito_plazos_para_cliente(cliente, descuento=descuento, prima=prima)
    if data.get("necesita_formato") or (not data.get("ok") and not data.get("formato_id")):
        data["formato_nuevo_url"] = (
            reverse("app:formato_aceptacion") + f"?cliente={cliente.pk}"
        )
    elif data.get("formato_id"):
        data["formato_edit_url"] = reverse(
            "app:formato_aceptacion_edit", kwargs={"pk": data["formato_id"]}
        )
    # Ayuda a preseleccionar lote en el plan
    if data.get("ok") and data.get("num_lote"):
        data["num_lote"] = data.get("num_lote")
    return JsonResponse(data)


class ContratoUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = Contrato
    form_class = forms.PlanPagosForm
    template_name = "app/contrato_form.html"
    success_url = reverse_lazy("app:contrato_list")

    def get_queryset(self):
        qs = Contrato.objects.select_related(
            "inmueble",
            "inmueble__proyecto",
            "inmueble__poligono",
            "vendedor_perfil",
            "vendedor",
            "cliente",
        )
        return filtrar_contratos_queryset_por_vendedor(qs, self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["filtro_proyecto_id"] = self.request.GET.get("proyecto") or None
        kwargs["filtro_poligono_id"] = self.request.GET.get("poligono") or None
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar plan de pagos"
        ctx["cancel_url"] = reverse_lazy("app:contrato_list")
        ctx["form_inmueble_filters"] = False
        ctx["form_contrato_autocomplete_off"] = True
        ctx["form_contrato_credito_panel"] = True
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        from inmobiliaria.cuotas_calendario import aplicar_calendario_desde_formato_cliente

        n = aplicar_calendario_desde_formato_cliente(
            self.object,
            descuento=self.object.descuento_efectivo_monto,
            prima=form.cleaned_data.get("prima_monto"),
            forzar=False,
        )
        if n:
            messages.success(
                self.request,
                f"Plan de pagos actualizado y calendario regenerado ({n} cuotas).",
            )
        else:
            messages.success(self.request, "Plan de pagos actualizado.")
        return response


class FormatoAceptacionCreateStandaloneView(AppLoginRequiredMixin, CreateView):
    """Alta directa del formato, sin contrato obligatorio ni pasos previos."""

    model = FormatoAceptacion
    form_class = forms.FormatoAceptacionForm
    template_name = "app/formato_aceptacion_form.html"

    def get_initial(self):
        initial = super().get_initial()
        raw = self.request.GET.get("cliente")
        if not raw:
            return initial
        try:
            cid = int(raw)
        except (TypeError, ValueError):
            return initial
        cli = Cliente.objects.filter(pk=cid).first()
        if not cli:
            return initial
        initial["nombre_cliente"] = (
            f"{(cli.nombres or '').strip()} {(cli.apellidos or '').strip()}".strip()
        )
        if cli.dui:
            initial["dui_numero"] = cli.dui
        if cli.telefono:
            initial["telefono_domicilio"] = cli.telefono
            initial["telefono_notificacion"] = cli.telefono
        if cli.direccion:
            initial["direccion_domicilio"] = cli.direccion
            initial["direccion_notificacion"] = cli.direccion
        return initial

    def form_valid(self, form):
        from inmobiliaria.validacion_gerencia import marcar_sin_cola_formato_o_plan

        form.instance.creado_por = self.request.user
        marcar_sin_cola_formato_o_plan(form.instance)
        prev_firmas = False
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Paso 1 listo: formato de aceptación guardado. "
            "Si es Contado → paso 2 (recibo total). "
            "Si es a plazos → 3 reserva → 4 prima → 5 plan → 6 cuotas. "
            "Solo los recibos (reserva/prima/cuotas) requieren validación de gerencia.",
        )
        _formato_aceptacion_tras_guardado_notificar(self.request, self.object, prev_firmas)
        return response

    def get_success_url(self):
        return reverse("app:formato_aceptacion_edit", kwargs={"pk": self.object.pk})

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        return kw

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Formato de aceptación (nuevo)"
        ctx["cancel_url"] = reverse("app:formato_aceptacion_list")
        ctx["form_multipart"] = True
        ctx["firmas_completas"] = False
        ctx["firmas_storage_perdidas"] = []
        ctx["firma_preview"] = _firma_preview_flags(getattr(self, "object", None))
        ctx["formato_adjunto_urls"] = _formato_adjunto_urls(getattr(self, "object", None))
        ctx["formato_encabezado_direccion"] = _formato_aceptacion_direccion_impreso()
        ctx["proyectos_formato"] = _proyectos_para_formato_aceptacion()
        ctx["formato_catalogo_inmuebles"] = _catalogo_inmuebles_formato_aceptacion()
        ctx["formato_lote_estado_url_tpl"] = reverse(
            "app:api_inmueble_estado", args=[0]
        ).replace("/0/", "/__ID__/")
        form = ctx.get("form") or self.get_form()
        ctx["formato_sections"] = _formato_aceptacion_form_sections(form)
        ctx.update(_formato_ctx_expediente_archivos(getattr(self, "object", None)))
        return ctx


@method_decorator(never_cache, name="dispatch")
class FormatoAceptacionListView(AppLoginRequiredMixin, ListView):
    """Módulo aparte: todos los formatos de aceptación y acceso rápido a edición/PDF."""

    model = FormatoAceptacion
    template_name = "app/formato_aceptacion_list.html"
    context_object_name = "items"
    paginate_by = 30

    def get_queryset(self):
        from inmobiliaria.vendedor_acceso import es_vendedor_restringido

        qs = FormatoAceptacion.objects.order_by("-numero_formulario", "-id").select_related(
            "contrato",
            "contrato__inmueble",
            "contrato__inmueble__proyecto",
        )
        qs = formato_aceptacion_defer_missing_columns(qs)
        if es_vendedor_restringido(self.request.user):
            qs = qs.filter(creado_por_id=self.request.user.pk)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["formato_promesa_lista_ok"] = _formato_aceptacion_promesa_column_ready()
        ctx["formato_compraventa_lista_ok"] = _formato_aceptacion_compraventa_column_ready()
        ctx["formato_credito_extra_lista_ok"] = formato_aceptacion_credito_extra_columns_ready()
        return ctx


class FormatoAceptacionUpdateView(
    AppLoginRequiredMixin, FormatoSuperuserGateMixin, UpdateView
):
    model = FormatoAceptacion
    form_class = forms.FormatoAceptacionForm
    template_name = "app/formato_aceptacion_form.html"

    def get_queryset(self):
        return _formato_aceptacion_qs_para_usuario(self.request.user)

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        return kw

    def form_valid(self, form):
        from inmobiliaria.validacion_gerencia import marcar_sin_cola_formato_o_plan

        pk = self.object.pk
        prev_firmas = False
        if pk:
            try:
                q = formato_aceptacion_defer_missing_columns(
                    FormatoAceptacion.objects.filter(pk=pk)
                )
                prev_firmas = q.get().firmas_completas
            except FormatoAceptacion.DoesNotExist:
                prev_firmas = False
        marcar_sin_cola_formato_o_plan(form.instance)
        response = super().form_valid(form)
        messages.success(self.request, "Cambios guardados.")
        _formato_aceptacion_tras_guardado_notificar(self.request, self.object, prev_firmas)
        return response

    def get_success_url(self):
        return reverse("app:formato_aceptacion_edit", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = (
            f"Formato de aceptación Nº {self.object.numero_formulario:04d}"
        )
        ctx["cancel_url"] = reverse("app:formato_aceptacion_list")
        ctx["form_multipart"] = True
        ctx["formato_pdf_url"] = reverse(
            "app:formato_aceptacion_pdf", kwargs={"pk": self.object.pk}
        )
        ctx["firmas_completas"] = self.object.firmas_completas
        ctx["firmas_storage_perdidas"] = _formato_firmas_ausentes_en_storage(
            self.object
        )
        ctx["firma_preview"] = _firma_preview_flags(self.object)
        ctx["formato_adjunto_urls"] = _formato_adjunto_urls(self.object)
        ctx["formato_encabezado_direccion"] = _formato_aceptacion_direccion_impreso()
        ctx["proyectos_formato"] = _proyectos_para_formato_aceptacion()
        ctx["formato_catalogo_inmuebles"] = _catalogo_inmuebles_formato_aceptacion()
        ctx["formato_lote_estado_url_tpl"] = reverse(
            "app:api_inmueble_estado", args=[0]
        ).replace("/0/", "/__ID__/")
        form = ctx.get("form") or self.get_form()
        ctx["formato_sections"] = _formato_aceptacion_form_sections(form)
        ctx.update(_formato_ctx_expediente_archivos(self.object))
        return ctx


class FormatoAceptacionDeleteView(
    AppLoginRequiredMixin, FormatoSuperuserGateMixin, DeleteView
):
    model = FormatoAceptacion
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:formato_aceptacion_list")

    def get_queryset(self):
        return _formato_aceptacion_qs_pk_para_usuario(self.request.user)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(
                request,
                "No se puede eliminar: existen registros vinculados.",
            )
            return HttpResponseRedirect(self.get_success_url())
        messages.success(request, "Registro eliminado.")
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar formato de aceptación"
        ctx["delete_blurb"] = (
            "Quitará este formato y sus datos. Los archivos adjuntos en almacenamiento pueden quedar huérfanos; "
            "revise su bucket o carpeta media si aplica."
        )
        return ctx


@login_required
def formato_aceptacion_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    formato = get_object_or_404(_formato_aceptacion_qs_para_usuario(request.user), pk=pk)
    if not formato.firmas_completas:
        messages.error(
            request,
            "Guarde el formulario con el DUI del cliente (PDF) y el formato de aceptación "
            "en físico firmado (PDF) antes de generar el PDF del sistema.",
        )
        return HttpResponseRedirect(
            reverse("app:formato_aceptacion_edit", kwargs={"pk": pk})
        )
    pdf_bytes = _generar_pdf_formato_aceptacion_bytes(formato)
    filename = f"formato_aceptacion_{formato.numero_formulario:04d}.pdf"
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


_FORMATO_FIRMA_PREVIEW_ROLES = {
    "aceptante": "firma_aceptante",
    "vendedor": "firma_vendedor",
    "autorizado": "firma_autorizado",
}

_FORMATO_ADJUNTO_ROLES = {
    "dui": "dui_cliente_archivo",
    "fisico": "formato_aceptacion_fisico",
    "boucher": "boucher_pago_reserva",
}


@login_required
@never_cache
def formato_firma_preview(request: HttpRequest, pk: int, tipo: str) -> HttpResponse:
    """
    Sirve la imagen de firma bajo /app/ con sesión iniciada.
    En producción (DEBUG=False) /media/ no es público por defecto: usar .url en <img> rompe la vista previa.
    """
    if tipo not in _FORMATO_FIRMA_PREVIEW_ROLES:
        raise Http404()
    formato = get_object_or_404(_formato_aceptacion_qs_pk_para_usuario(request.user), pk=pk)
    field = getattr(formato, _FORMATO_FIRMA_PREVIEW_ROLES[tipo])
    if not field or not field.name:
        raise Http404()
    if not default_storage.exists(field.name):
        raise Http404()
    try:
        fh = field.open("rb")
    except OSError:
        raise Http404()
    content_type = mimetypes.guess_type(field.name)[0] or "image/png"
    return FileResponse(fh, content_type=content_type)


@login_required
@never_cache
def formato_aceptacion_adjunto_descargar(
    request: HttpRequest, pk: int, tipo: str
) -> HttpResponse:
    if tipo not in _FORMATO_ADJUNTO_ROLES:
        raise Http404()
    if not _formato_editar_acceso_permitido(request):
        nxt = request.get_full_path()
        gate = f"{reverse('app:formato_superuser_gate')}?{urlencode({'next': nxt})}"
        return HttpResponseRedirect(gate)
    formato = get_object_or_404(_formato_aceptacion_qs_pk_para_usuario(request.user), pk=pk)
    field = getattr(formato, _FORMATO_ADJUNTO_ROLES[tipo])
    if not field or not field.name:
        raise Http404()
    if not default_storage.exists(field.name):
        raise Http404()
    try:
        fh = field.open("rb")
    except OSError:
        raise Http404()
    ctype = mimetypes.guess_type(field.name)[0] or "application/octet-stream"
    base = field.name.split("/")[-1] or f"adjunto_{tipo}"
    return FileResponse(
        fh,
        content_type=ctype,
        as_attachment=True,
        filename=base,
    )


@login_required
@require_POST
def formato_aceptacion_promesa_subir(request: HttpRequest, pk: int) -> HttpResponse:
    if not _formato_editar_acceso_permitido(request):
        nxt = request.get_full_path()
        gate = f"{reverse('app:formato_superuser_gate')}?{urlencode({'next': nxt})}"
        return HttpResponseRedirect(gate)
    use_list = (request.POST.get("promesa_origen") or "").strip() == "lista"
    redir = (
        reverse("app:formato_aceptacion_list")
        if use_list
        else reverse("app:formato_aceptacion_edit", kwargs={"pk": pk})
    )
    if not _formato_aceptacion_promesa_column_ready():
        messages.error(
            request,
            "La base de datos aún no tiene la columna para la promesa escaneada. "
            "En el servidor ejecute: python manage.py migrate --noinput",
        )
        return HttpResponseRedirect(redir)
    formato = get_object_or_404(_formato_aceptacion_qs_pk_para_usuario(request.user), pk=pk)
    form = forms.FormatoAceptacionPromesaForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Revise el archivo (PDF, JPG o PNG).")
        return HttpResponseRedirect(redir)
    formato.promesa_venta_escaneada = form.cleaned_data["promesa_venta_escaneada"]
    formato.save()
    try:
        from docs.formato_aceptacion_notificacion import notificar_promesa_escaneada_tras_subir

        # select_related para correo/tel del cliente al notificar (evita instancia sin contrato cargado)
        formato = formato_aceptacion_defer_missing_columns(
            FormatoAceptacion.objects.select_related("contrato", "contrato__cliente")
        ).get(pk=formato.pk)
        notificar_promesa_escaneada_tras_subir(request, formato)
    except Exception:
        logger.exception("Notificación promesa escaneada formato pk=%s", pk)
        messages.warning(
            request,
            "Archivo guardado; hubo un problema al notificar al cliente.",
        )
    return HttpResponseRedirect(redir)


@login_required
@never_cache
def formato_aceptacion_promesa_descargar(request: HttpRequest, pk: int) -> HttpResponse:
    if not _formato_editar_acceso_permitido(request):
        nxt = request.get_full_path()
        gate = f"{reverse('app:formato_superuser_gate')}?{urlencode({'next': nxt})}"
        return HttpResponseRedirect(gate)
    if not _formato_aceptacion_promesa_column_ready():
        raise Http404()
    formato = get_object_or_404(_formato_aceptacion_qs_pk_para_usuario(request.user), pk=pk)
    field = formato.promesa_venta_escaneada
    if not field or not field.name:
        raise Http404()
    if not default_storage.exists(field.name):
        raise Http404()
    try:
        fh = field.open("rb")
    except OSError:
        raise Http404()
    ctype = mimetypes.guess_type(field.name)[0] or "application/octet-stream"
    base = field.name.split("/")[-1] or "promesa_venta"
    return FileResponse(
        fh,
        content_type=ctype,
        as_attachment=True,
        filename=base,
    )


@login_required
@require_POST
def formato_aceptacion_compraventa_subir(request: HttpRequest, pk: int) -> HttpResponse:
    if not _formato_editar_acceso_permitido(request):
        nxt = request.get_full_path()
        gate = f"{reverse('app:formato_superuser_gate')}?{urlencode({'next': nxt})}"
        return HttpResponseRedirect(gate)
    use_list = (request.POST.get("compraventa_origen") or "").strip() == "lista"
    redir = (
        reverse("app:formato_aceptacion_list")
        if use_list
        else reverse("app:formato_aceptacion_edit", kwargs={"pk": pk})
    )
    if not _formato_aceptacion_compraventa_column_ready():
        messages.error(
            request,
            "La base de datos aún no tiene la columna para el contrato de compraventa. "
            "En el servidor ejecute: python manage.py migrate --noinput",
        )
        return HttpResponseRedirect(redir)
    formato = get_object_or_404(_formato_aceptacion_qs_pk_para_usuario(request.user), pk=pk)
    form = forms.FormatoAceptacionCompraventaForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Revise el archivo (PDF, JPG o PNG).")
        return HttpResponseRedirect(redir)
    formato.contrato_compraventa_escaneado = form.cleaned_data["contrato_compraventa_escaneado"]
    formato.save(update_fields=["contrato_compraventa_escaneado", "actualizado_en"])
    messages.success(
        request,
        "Contrato de compraventa guardado en el expediente del formato.",
    )
    return HttpResponseRedirect(redir)


@login_required
@never_cache
def formato_aceptacion_compraventa_descargar(request: HttpRequest, pk: int) -> HttpResponse:
    if not _formato_editar_acceso_permitido(request):
        nxt = request.get_full_path()
        gate = f"{reverse('app:formato_superuser_gate')}?{urlencode({'next': nxt})}"
        return HttpResponseRedirect(gate)
    if not _formato_aceptacion_compraventa_column_ready():
        raise Http404()
    formato = get_object_or_404(_formato_aceptacion_qs_pk_para_usuario(request.user), pk=pk)
    field = formato.contrato_compraventa_escaneado
    if not field or not field.name:
        raise Http404()
    if not default_storage.exists(field.name):
        raise Http404()
    try:
        fh = field.open("rb")
    except OSError:
        raise Http404()
    ctype = mimetypes.guess_type(field.name)[0] or "application/octet-stream"
    base = field.name.split("/")[-1] or "contrato_compraventa"
    return FileResponse(
        fh,
        content_type=ctype,
        as_attachment=True,
        filename=base,
    )


@login_required
def contrato_estado_cuenta(request: HttpRequest, pk: int) -> HttpResponse:
    from inmobiliaria.recargo_administrativo import (
        detalle_recargo_por_cuota,
        parametro_recargo_activo,
        resumen_cobro_contrato,
    )

    base = Contrato.objects.select_related("cliente", "inmueble", "inmueble__proyecto")
    contrato = get_object_or_404(
        filtrar_contratos_queryset_por_vendedor(base, request.user),
        pk=pk,
    )
    pagos = contrato.pagos.all().order_by("-fecha", "-id")
    cuotas_qs = (
        contrato.cuotas_programadas.select_related("pago")
        .prefetch_related("pago__cuotas_aplicadas")
        .order_by("numero")
    )
    hoy = timezone.localdate()
    param = parametro_recargo_activo()
    dias_gracia = int(param.dias_gracia) if param else 0
    monto_unitario = (param.monto_recargo if param else None) or Decimal("0")
    cobro = resumen_cobro_contrato(contrato, hoy=hoy)

    filas_cuotas: list[dict] = []
    from inmobiliaria.pago_desglose import desglose_aplicado_por_cuota

    for c in cuotas_qs:
        liquidada = (
            c.estado == CuotaProgramada.Estado.PAGADA or c.pago_id is not None
        )
        fecha_pago = None
        if liquidada:
            fecha_pago = (c.pago.fecha if c.pago_id else None) or c.pagado_en
        dias_tarde_al_pagar: int | None = None
        dias_impago_tras_venc: int | None = None
        if fecha_pago is not None:
            dias_tarde_al_pagar = max(0, (fecha_pago - c.vence_en).days)
        elif c.estado in (
            CuotaProgramada.Estado.PENDIENTE,
            CuotaProgramada.Estado.VENCIDA,
        ) and hoy > c.vence_en:
            dias_impago_tras_venc = (hoy - c.vence_en).days
        pago_monto = c.pago.monto if c.pago_id else None
        pago_referencia = None
        if c.pago_id:
            ref = (c.pago.referencia or "").strip()
            pago_referencia = ref or None
        det = detalle_recargo_por_cuota(
            c,
            hoy=hoy,
            dias_gracia=dias_gracia,
            monto_unitario=monto_unitario,
        )
        es_proxima = cobro.cuota is not None and cobro.cuota.pk == c.pk
        dg = desglose_aplicado_por_cuota(c)
        fecha_registro = None
        if c.pago_id and getattr(c.pago, "creado_en", None):
            fecha_registro = timezone.localtime(c.pago.creado_en).date()
        filas_cuotas.append(
            {
                "cuota": c,
                "fecha_pago": fecha_pago,
                "fecha_registro": fecha_registro,
                "dias_tarde_al_pagar": dias_tarde_al_pagar,
                "dias_impago_tras_venc": dias_impago_tras_venc,
                "pago_monto": pago_monto,
                "pago_referencia": pago_referencia,
                "genera_recargo": det["genera_recargo"],
                "fecha_limite_gracia": det["fecha_limite_gracia"],
                "es_proxima": es_proxima,
                "a_cobrar_total": cobro.monto_total if es_proxima else None,
                "a_cobrar_recargo": cobro.monto_recargo if es_proxima else None,
                "recargo_cobrado": dg["recargo"] if dg["tiene_pago"] else None,
                "abono_capital": dg["capital"] if dg["tiene_pago"] else None,
                "total_pago_fila": dg["total_pago"],
                "es_ultima_del_pago": dg["es_ultima_del_pago"],
            }
        )

    qp = contrato.cuotas_programadas
    monto_plan_total = qp.aggregate(t=Sum("monto"))["t"] or Decimal("0")
    monto_cuotas_pagadas = (
        qp.filter(estado=CuotaProgramada.Estado.PAGADA).aggregate(t=Sum("monto"))["t"]
        or Decimal("0")
    )
    monto_cuotas_por_pagar = monto_plan_total - monto_cuotas_pagadas
    cuotas_resumen = {
        "total_cuotas": qp.count(),
        "pagadas": qp.filter(estado=CuotaProgramada.Estado.PAGADA).count(),
        "pendientes": qp.filter(estado=CuotaProgramada.Estado.PENDIENTE).count(),
        "vencidas": qp.filter(estado=CuotaProgramada.Estado.VENCIDA).count(),
        "monto_plan_total": monto_plan_total,
        "monto_cuotas_pagadas": monto_cuotas_pagadas,
        "monto_cuotas_por_pagar": monto_cuotas_por_pagar,
    }

    total_pagado_bruto = pagos.aggregate(t=Sum("monto"))["t"] or Decimal("0")
    total_recargos = (
        pagos.filter(concepto=Pago.Concepto.MORA).aggregate(t=Sum("monto"))["t"]
        or Decimal("0")
    ) + (
        pagos.filter(concepto=Pago.Concepto.CUOTA).aggregate(
            t=Sum("monto_recargo_incluido")
        )["t"]
        or Decimal("0")
    )
    # El recargo administrativo no reduce el capital del contrato.
    total_pagado = (total_pagado_bruto - total_recargos).quantize(Decimal("0.01"))
    saldo_estimado = contrato.precio_final - total_pagado
    context = {
        "contrato": contrato,
        "pagos": pagos,
        "filas_cuotas": filas_cuotas,
        "cuotas_resumen": cuotas_resumen,
        "hoy": hoy,
        "total_pagado": total_pagado,
        "saldo_estimado": saldo_estimado,
        "cobro_mes": cobro,
        "param_recargo": param,
    }
    return render(request, "app/contrato_estado_cuenta.html", context)


@login_required
def export_pagos_csv(request: HttpRequest) -> HttpResponse:
    qs = Pago.objects.select_related("contrato", "contrato__cliente").order_by("-fecha", "-id")
    qs = filtrar_pagos_queryset_por_vendedor(qs, request.user)
    rows = qs.iterator(chunk_size=500)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="pagos_pbr.csv"'
    response.write("\ufeff")
    w = csv.writer(response)
    w.writerow(
        [
            "fecha",
            "contrato_numero",
            "cliente",
            "concepto",
            "monto",
            "referencia",
        ]
    )
    for p in rows:
        w.writerow(
            [
                p.fecha.isoformat(),
                p.contrato.numero,
                str(p.contrato.cliente),
                p.get_concepto_display(),
                str(p.monto),
                p.referencia,
            ]
        )
    return response


# ——— Pagos ———
class PagoListView(AppLoginRequiredMixin, ListView):
    model = Pago
    template_name = "app/pago_list.html"
    context_object_name = "items"
    paginate_by = 40

    def get_queryset(self):
        qs = Pago.objects.select_related(
            "contrato",
            "contrato__cliente",
            "validado_por",
        )
        qs = filtrar_pagos_queryset_por_vendedor(qs, self.request.user)
        cid = (self.request.GET.get("contrato") or "").strip()
        if cid.isdigit():
            qs = qs.filter(contrato_id=int(cid))
        estado = (self.request.GET.get("validacion") or "").strip().upper()
        if estado == "PENDIENTE":
            qs = qs.filter(validacion_abono=Pago.ValidacionAbono.PENDIENTE)
        elif estado == "VALIDADO":
            qs = qs.filter(validacion_abono=Pago.ValidacionAbono.VALIDADO)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cid = (self.request.GET.get("contrato") or "").strip()
        ctx["contrato_filtro"] = None
        if cid.isdigit():
            ctx["contrato_filtro"] = Contrato.objects.filter(pk=int(cid)).first()
        ctx["filtro_validacion"] = (self.request.GET.get("validacion") or "").strip().lower()
        pendientes = Pago.objects.filter(
            validacion_abono=Pago.ValidacionAbono.PENDIENTE
        )
        pendientes = filtrar_pagos_queryset_por_vendedor(pendientes, self.request.user)
        ctx["pagos_pendientes_validacion_ct"] = pendientes.count()
        from inmobiliaria.vendedor_acceso import es_vendedor_restringido

        ctx["pago_list_vendedor"] = es_vendedor_restringido(self.request.user)
        return ctx

class PagoCreateView(AppLoginRequiredMixin, CreateView):
    model = Pago
    form_class = forms.PagoForm
    template_name = "app/pago_form.html"
    success_url = reverse_lazy("app:pago_list")

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["ocultar_contrato"] = True
        kw["user"] = self.request.user
        concepto = (self.request.GET.get("concepto") or "").strip().upper()
        if concepto in {c.value for c in Pago.Concepto}:
            kw["concepto_fijo"] = concepto
        return kw

    def get_initial(self):
        initial = super().get_initial()
        fid = (self.request.GET.get("formato") or "").strip()
        if fid.isdigit():
            initial["formato_aceptacion"] = int(fid)
        concepto = (self.request.GET.get("concepto") or "").strip().upper()
        if concepto in {c.value for c in Pago.Concepto}:
            initial["concepto"] = concepto
        cid = (self.request.GET.get("contrato") or "").strip()
        if cid.isdigit():
            initial["contrato"] = int(cid)
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        concepto = (self.request.GET.get("concepto") or "").strip().upper()
        titulos = {
            "CONTADO": "Paso 2 · Contado: recibo total del lote",
            "RESERVA": "Paso 3 · Reserva pagada (recibo)",
            "PRIMA": "Paso 4 · Prima pagada (recibo)",
            "CUOTA": "Paso 6 · Recibo a plazos (cuota)",
        }
        ctx["form_title"] = titulos.get(concepto, "Nuevo pago / recibo")
        ctx["cancel_url"] = reverse_lazy("app:pago_list")
        ctx["pago_contrato_panel"] = True
        ctx["pago_cuotas_checkboxes"] = concepto == "CUOTA"
        ctx["pago_ocultar_contrato"] = True
        ctx["pago_panel_debajo_formato"] = True
        ctx["pago_flujo_concepto"] = concepto
        ctx["form_multipart"] = True
        return ctx

    def form_valid(self, form):
        from inmobiliaria.validacion_gerencia import aplicar_validacion_pago_al_guardar

        pendiente = aplicar_validacion_pago_al_guardar(form.instance, self.request.user)
        response = super().form_valid(form)
        concepto = form.cleaned_data.get("concepto")
        if concepto in Pago.CONCEPTOS_CON_VALIDACION and pendiente:
            messages.success(
                self.request,
                f"{self.object.get_concepto_display()} registrado. "
                "Queda pendiente de validación de gerencia/administrador: "
                "el recibo PDF no se genera ni se puede imprimir hasta que confirmen el depósito en cuenta.",
            )
            messages.info(
                self.request,
                "Gerencia: menú → Validar flujo de venta / Validar abonos → Confirmar. "
                "Asesor: Estado de mis recibos (verá «Imprimir / PDF» solo cuando esté validado).",
            )
        elif concepto in Pago.CONCEPTOS_CON_VALIDACION:
            messages.success(
                self.request,
                f"{self.object.get_concepto_display()} registrado y validado. "
                "Puede generar el recibo PDF.",
            )
        else:
            messages.success(
                self.request,
                "Pago registrado. El recibo de ingreso se genera automáticamente al guardar.",
            )
        return response


@login_required
def pago_validar_abono(request: HttpRequest, pk: int) -> HttpResponse:
    """Gerencia confirma depósito en cuenta → genera recibo PDF y notifica (correo/WhatsApp)."""
    from usuarios.roles import puede_validar_abonos

    if not puede_validar_abonos(request.user):
        messages.error(
            request,
            "Solo gerencia o administrador puede validar abonos (reserva, prima, cuota o abono a capital).",
        )
        return HttpResponseRedirect(reverse("app:pago_list"))

    pago = get_object_or_404(
        filtrar_pagos_queryset_por_vendedor(
            Pago.objects.select_related(
                "contrato",
                "contrato__cliente",
                "contrato__inmueble",
                "contrato__inmueble__proyecto",
            ),
            request.user,
        ),
        pk=pk,
    )
    if not pago.pendiente_validacion_gerente:
        messages.warning(request, "Este pago no está pendiente de validación.")
        return HttpResponseRedirect(reverse("app:pago_list") + "?validacion=pendiente")

    if request.method != "POST":
        return render(
            request,
            "app/pago_validar_abono.html",
            {"pago": pago, "accion": "validar"},
        )

    nota = (request.POST.get("validacion_nota") or "").strip()[:255]
    if not nota:
        nota = "Abono confirmado en cuenta"
    pago.validacion_abono = Pago.ValidacionAbono.VALIDADO
    pago.validado_por = request.user
    pago.validado_en = timezone.localtime()
    pago.validacion_nota = nota
    pago.save(
        update_fields=[
            "validacion_abono",
            "validado_por",
            "validado_en",
            "validacion_nota",
        ]
    )

    from docs.recibo_notificacion import construir_url_whatsapp_recibo
    from docs.services import emitir_recibo_ingreso
    from docs.views_web import _alerta_html_recibo_emitido

    try:
        doc, notif = emitir_recibo_ingreso(pago=pago, emitido_por=request.user)
        wa = construir_url_whatsapp_recibo(pago.contrato.cliente, doc, pago)
        url_pdf = reverse("app:doc_download", args=[doc.id])
        messages.success(
            request,
            _alerta_html_recibo_emitido(
                doc_numero=doc.numero,
                url_pdf=url_pdf,
                wa_url=wa,
                notif=notif,
            ),
            extra_tags="allow_html",
        )
        enviados = []
        if notif.correo_enviado:
            enviados.append("correo")
        if notif.whatsapp_pdf_por_api:
            enviados.append("WhatsApp API")
        if enviados:
            msg_envio = " y enviado al cliente por " + " y ".join(enviados)
        elif wa:
            msg_envio = (
                ". Se abre WhatsApp en su equipo para enviarlo con su WhatsApp personal "
                "(adjunte el PDF y pulse Enviar)"
            )
        else:
            msg_envio = (
                ". Agregue teléfono/email del cliente para notificar, "
                "o use Descargar PDF"
            )
        messages.info(
            request,
            f"Validación OK ({nota}). Recibo {doc.numero} generado{msg_envio}.",
        )
        if pago.concepto in (
            Pago.Concepto.RESERVA,
            Pago.Concepto.PRIMA,
            Pago.Concepto.CONTADO,
        ):
            from inmobiliaria.comision_vendedor import (
                intentar_emitir_comision_automatica,
                requisitos_comision_venta,
                ya_existe_recibo_comision,
            )

            doc_com = intentar_emitir_comision_automatica(
                pago.contrato_id, emitido_por=request.user
            )
            if doc_com is not None:
                url_com = reverse("app:doc_download", args=[doc_com.id])
                messages.success(
                    request,
                    format_html(
                        "Recibo de comisión al asesor de ventas <strong>{}</strong> generado "
                        "(reserva y prima OK, asesor completo). "
                        '<a href="{}">Descargar PDF</a>.',
                        doc_com.numero,
                        url_com,
                    ),
                    extra_tags="allow_html",
                )
            elif not ya_existe_recibo_comision(pago.contrato_id):
                req_c = requisitos_comision_venta(pago.contrato)
                if not req_c.puede_emitir:
                    messages.info(
                        request,
                        "Comisión al asesor de ventas aún no generada: " + " ".join(req_c.motivos),
                    )
        # Sin API Meta: PDF + mensaje juntos con WhatsApp personal del asesor de ventas.
        if wa and not notif.whatsapp_pdf_por_api:
            from docs.recibo_notificacion import datos_envio_whatsapp_personal

            datos = datos_envio_whatsapp_personal(pago.contrato.cliente, doc, pago) or {}
            return render(
                request,
                "app/recibo_abrir_whatsapp.html",
                {
                    "doc_numero": doc.numero,
                    "wa_url": wa,
                    "url_pdf": url_pdf,
                    "continue_url": reverse("app:docs_list"),
                    "share_payload": {
                        "doc_numero": doc.numero,
                        "pdf_url": url_pdf,
                        "pdf_nombre": datos.get("pdf_nombre")
                        or f"{doc.numero.replace('/', '-')}.pdf",
                        "wa_url": wa,
                        "mensaje": datos.get("mensaje") or "",
                        "mensaje_con_enlace": datos.get("mensaje_con_enlace") or "",
                    },
                },
            )
        return HttpResponseRedirect(reverse("app:docs_list"))
    except Exception:
        logger.exception("Error al emitir recibo tras validar pago id=%s", pago.pk)
        messages.warning(
            request,
            "Abono validado en cuenta, pero no se pudo emitir el recibo automáticamente. "
            "Intente «Recibo PDF» desde el listado de pagos.",
        )
        return HttpResponseRedirect(reverse("app:pago_list") + "?validacion=pendiente")


@login_required
def pago_rechazar_abono(request: HttpRequest, pk: int) -> HttpResponse:
    """Gerencia rechaza el abono: no se emite recibo ni notificaciones."""
    from usuarios.roles import puede_validar_abonos

    if not puede_validar_abonos(request.user):
        messages.error(
            request,
            "Solo gerencia o administrador puede rechazar abonos (reserva, prima, cuota o abono a capital).",
        )
        return HttpResponseRedirect(reverse("app:pago_list"))

    pago = get_object_or_404(
        filtrar_pagos_queryset_por_vendedor(
            Pago.objects.select_related("contrato"),
            request.user,
        ),
        pk=pk,
    )
    if not pago.pendiente_validacion_gerente:
        messages.warning(request, "Este pago no está pendiente de validación.")
        return HttpResponseRedirect(reverse("app:pago_list") + "?validacion=pendiente")

    if request.method != "POST":
        return render(
            request,
            "app/pago_validar_abono.html",
            {"pago": pago, "accion": "rechazar"},
        )

    nota = (request.POST.get("validacion_nota") or "").strip()[:255]
    if not nota:
        messages.error(request, "Indique el motivo del rechazo.")
        return render(
            request,
            "app/pago_validar_abono.html",
            {"pago": pago, "accion": "rechazar"},
        )

    pago.validacion_abono = Pago.ValidacionAbono.RECHAZADO
    pago.validado_por = request.user
    pago.validado_en = timezone.localtime()
    pago.validacion_nota = nota
    pago.save(
        update_fields=[
            "validacion_abono",
            "validado_por",
            "validado_en",
            "validacion_nota",
        ]
    )
    messages.success(
        request,
        "Abono rechazado. No se generó recibo ni se notificó al cliente.",
    )
    return HttpResponseRedirect(reverse("app:pago_list") + "?validacion=pendiente")


@login_required
def flujo_venta_validar_list(request: HttpRequest) -> HttpResponse:
    """Cola de formatos, planes y enlace a abonos pendientes de gerencia."""
    from inmobiliaria.validacion_gerencia import conteos_pendientes_flujo
    from usuarios.roles import puede_validar_flujo_venta

    if not puede_validar_flujo_venta(request.user):
        messages.error(
            request,
            "Solo gerencia o administrador puede validar el flujo de venta.",
        )
        return HttpResponseRedirect(reverse("app:index"))

    formatos = (
        FormatoAceptacion.objects.filter(
            validacion_gerencia=FormatoAceptacion.ValidacionGerencia.PENDIENTE
        )
        .select_related("creado_por")
        .order_by("-actualizado_en", "-pk")
    )
    contratos = (
        Contrato.objects.filter(
            validacion_gerencia=Contrato.ValidacionGerencia.PENDIENTE
        )
        .select_related("cliente", "inmueble", "inmueble__proyecto")
        .order_by("-creado_en", "-pk")
    )
    conteos = conteos_pendientes_flujo()
    return render(
        request,
        "app/flujo_venta_validar_list.html",
        {
            "formatos": formatos,
            "contratos": contratos,
            "conteos": conteos,
        },
    )


@login_required
def flujo_venta_validar_formato(request: HttpRequest, pk: int) -> HttpResponse:
    from inmobiliaria.validacion_gerencia import rechazar_formato, validar_formato
    from usuarios.roles import puede_validar_flujo_venta

    if not puede_validar_flujo_venta(request.user):
        messages.error(request, "Solo gerencia o administrador puede validar formatos.")
        return HttpResponseRedirect(reverse("app:formato_aceptacion_list"))

    fmt = get_object_or_404(FormatoAceptacion, pk=pk)
    accion = (request.GET.get("accion") or request.POST.get("accion") or "validar").strip()
    if accion not in ("validar", "rechazar"):
        accion = "validar"

    if fmt.validacion_gerencia != FormatoAceptacion.ValidacionGerencia.PENDIENTE:
        messages.warning(request, "Este formato no está pendiente de validación.")
        return HttpResponseRedirect(reverse("app:flujo_venta_validar_list"))

    if request.method != "POST":
        return render(
            request,
            "app/flujo_venta_validar_item.html",
            {"tipo": "formato", "formato": fmt, "accion": accion},
        )

    nota = (request.POST.get("validacion_nota") or "").strip()[:255]
    if accion == "rechazar":
        if not nota:
            messages.error(request, "Indique el motivo del rechazo.")
            return render(
                request,
                "app/flujo_venta_validar_item.html",
                {"tipo": "formato", "formato": fmt, "accion": accion},
            )
        rechazar_formato(fmt, request.user, nota=nota)
        messages.success(request, f"Formato #{fmt.numero_formulario:04d} rechazado.")
    else:
        if not nota:
            nota = "Formato validado por gerencia"
        validar_formato(fmt, request.user, nota=nota)
        messages.success(
            request,
            f"Formato #{fmt.numero_formulario:04d} validado. Ya es oficial en el flujo.",
        )
    return HttpResponseRedirect(reverse("app:flujo_venta_validar_list"))


@login_required
def flujo_venta_validar_contrato(request: HttpRequest, pk: int) -> HttpResponse:
    from inmobiliaria.validacion_gerencia import rechazar_contrato, validar_contrato
    from usuarios.roles import puede_validar_flujo_venta

    if not puede_validar_flujo_venta(request.user):
        messages.error(request, "Solo gerencia o administrador puede validar planes.")
        return HttpResponseRedirect(reverse("app:contrato_list"))

    contrato = get_object_or_404(
        Contrato.objects.select_related("cliente", "inmueble", "inmueble__proyecto"),
        pk=pk,
    )
    accion = (request.GET.get("accion") or request.POST.get("accion") or "validar").strip()
    if accion not in ("validar", "rechazar"):
        accion = "validar"

    if contrato.validacion_gerencia != Contrato.ValidacionGerencia.PENDIENTE:
        messages.warning(request, "Este plan no está pendiente de validación.")
        return HttpResponseRedirect(reverse("app:flujo_venta_validar_list"))

    if request.method != "POST":
        return render(
            request,
            "app/flujo_venta_validar_item.html",
            {"tipo": "contrato", "contrato": contrato, "accion": accion},
        )

    nota = (request.POST.get("validacion_nota") or "").strip()[:255]
    if accion == "rechazar":
        if not nota:
            messages.error(request, "Indique el motivo del rechazo.")
            return render(
                request,
                "app/flujo_venta_validar_item.html",
                {"tipo": "contrato", "contrato": contrato, "accion": accion},
            )
        rechazar_contrato(contrato, request.user, nota=nota)
        messages.success(request, f"Plan {contrato.numero} rechazado (sigue en borrador).")
    else:
        if not nota:
            nota = "Plan de pagos validado por gerencia"
        validar_contrato(contrato, request.user, nota=nota)
        messages.success(
            request,
            f"Plan {contrato.numero} validado y activado.",
        )
    return HttpResponseRedirect(reverse("app:flujo_venta_validar_list"))


@login_required
def formato_precio_pendiente_list(request: HttpRequest) -> HttpResponse:
    from usuarios.roles import puede_aprobar_precio_formato

    if not puede_aprobar_precio_formato(request.user):
        messages.error(request, "Solo gerencia o administrador puede aprobar precios.")
        return HttpResponseRedirect(reverse("app:formato_aceptacion_list"))

    qs = (
        FormatoAceptacion.objects.filter(
            validacion_precio=FormatoAceptacion.ValidacionPrecio.PENDIENTE
        )
        .select_related("precio_solicitado_por")
        .order_by("-precio_solicitado_en", "-pk")
    )
    return render(
        request,
        "app/formato_precio_pendiente_list.html",
        {"formatos": qs},
    )


@login_required
def formato_precio_aprobar(request: HttpRequest, pk: int) -> HttpResponse:
    from usuarios.roles import puede_aprobar_precio_formato

    if not puede_aprobar_precio_formato(request.user):
        messages.error(request, "Solo gerencia o administrador puede aprobar precios.")
        return HttpResponseRedirect(reverse("app:formato_aceptacion_list"))

    fmt = get_object_or_404(FormatoAceptacion, pk=pk)
    if not fmt.pendiente_validacion_precio:
        messages.warning(request, "Este formato no tiene cambio de precio pendiente.")
        return HttpResponseRedirect(reverse("app:formato_precio_pendiente_list"))

    if request.method != "POST":
        return render(
            request,
            "app/formato_precio_validar.html",
            {"formato": fmt, "accion": "aprobar"},
        )

    nota = (request.POST.get("validacion_nota") or "").strip()[:255] or "Precio aprobado"
    if fmt.valor_inmueble_solicitado is not None:
        fmt.valor_inmueble = fmt.valor_inmueble_solicitado
    fmt.validacion_precio = FormatoAceptacion.ValidacionPrecio.APROBADO
    fmt.precio_validado_por = request.user
    fmt.precio_validado_en = timezone.localtime()
    fmt.precio_validacion_nota = nota
    fmt.save(
        update_fields=[
            "valor_inmueble",
            "validacion_precio",
            "precio_validado_por",
            "precio_validado_en",
            "precio_validacion_nota",
        ]
    )
    messages.success(
        request,
        f"Precio aprobado en formato #{fmt.numero_formulario:04d}: ${fmt.valor_inmueble}.",
    )
    return HttpResponseRedirect(reverse("app:formato_precio_pendiente_list"))


@login_required
def formato_precio_rechazar(request: HttpRequest, pk: int) -> HttpResponse:
    from usuarios.roles import puede_aprobar_precio_formato

    if not puede_aprobar_precio_formato(request.user):
        messages.error(request, "Solo gerencia o administrador puede rechazar precios.")
        return HttpResponseRedirect(reverse("app:formato_aceptacion_list"))

    fmt = get_object_or_404(FormatoAceptacion, pk=pk)
    if not fmt.pendiente_validacion_precio:
        messages.warning(request, "Este formato no tiene cambio de precio pendiente.")
        return HttpResponseRedirect(reverse("app:formato_precio_pendiente_list"))

    if request.method != "POST":
        return render(
            request,
            "app/formato_precio_validar.html",
            {"formato": fmt, "accion": "rechazar"},
        )

    nota = (request.POST.get("validacion_nota") or "").strip()[:255]
    if not nota:
        messages.error(request, "Indique el motivo del rechazo.")
        return render(
            request,
            "app/formato_precio_validar.html",
            {"formato": fmt, "accion": "rechazar"},
        )

    if fmt.valor_inmueble_sistema is not None:
        fmt.valor_inmueble = fmt.valor_inmueble_sistema
    fmt.validacion_precio = FormatoAceptacion.ValidacionPrecio.RECHAZADO
    fmt.precio_validado_por = request.user
    fmt.precio_validado_en = timezone.localtime()
    fmt.precio_validacion_nota = nota
    fmt.save(
        update_fields=[
            "valor_inmueble",
            "validacion_precio",
            "precio_validado_por",
            "precio_validado_en",
            "precio_validacion_nota",
        ]
    )
    messages.success(
        request,
        f"Cambio de precio rechazado en formato #{fmt.numero_formulario:04d}. "
        f"Se mantiene ${fmt.valor_inmueble}.",
    )
    return HttpResponseRedirect(reverse("app:formato_precio_pendiente_list"))


class ParametroEtapaVentaUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    """Editar rangos generales de etapa (una sola configuración)."""

    model = ParametroEtapaVenta
    fields = ("hasta_preventa", "hasta_promocional", "hasta_pos_preventa")
    template_name = "app/object_form.html"
    success_url = reverse_lazy("app:parametro_etapa_venta")

    def get_object(self, queryset=None):
        from inmobiliaria.etapa_venta import get_parametro_etapa

        return get_parametro_etapa()

    def dispatch(self, request, *args, **kwargs):
        from usuarios.roles import puede_aprobar_precio_formato

        if not puede_aprobar_precio_formato(request.user):
            messages.error(request, "Solo gerencia o administrador puede editar etapas.")
            return HttpResponseRedirect(reverse("app:proyecto_list"))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Etapas de venta (rangos generales)"
        ctx["form_intro"] = (
            "Preventa / Promocional / Pos preventa. El contador de lotes es por proyecto; "
            "estos rangos son los mismos para todos."
        )
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Rangos de etapa actualizados.")
        return super().form_valid(form)


class PagoUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = Pago
    form_class = forms.PagoForm
    template_name = "app/pago_form.html"
    success_url = reverse_lazy("app:pago_list")

    def get_queryset(self):
        qs = Pago.objects.select_related("contrato")
        return filtrar_pagos_queryset_por_vendedor(qs, self.request.user)

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        return kw

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar pago"
        ctx["cancel_url"] = reverse_lazy("app:pago_list")
        ctx["pago_contrato_panel"] = True
        ctx["pago_cuotas_checkboxes"] = False
        ctx["pago_ocultar_contrato"] = False
        ctx["pago_panel_debajo_formato"] = False
        ctx["form_multipart"] = True
        return ctx

    def form_valid(self, form):
        from inmobiliaria.validacion_gerencia import aplicar_validacion_pago_al_guardar

        pendiente = aplicar_validacion_pago_al_guardar(form.instance, self.request.user)
        response = super().form_valid(form)
        if pendiente:
            messages.warning(
                self.request,
                "Pago actualizado. Queda de nuevo pendiente de validación de admin/gerencia.",
            )
        else:
            messages.success(self.request, "Pago actualizado.")
        return response


@login_required
def aviso_cobro_list(request: HttpRequest) -> HttpResponse:
    """Lista avisos de cobro (5 días antes) y permite generarlos."""
    from datetime import timedelta

    from inmobiliaria.recordatorios_cobro import generar_avisos_cobro

    dias = 5
    raw_dias = (request.GET.get("dias") or request.POST.get("dias") or "5").strip()
    if raw_dias.isdigit():
        dias = max(0, min(int(raw_dias), 60))

    if request.method == "POST":
        enviar_email = request.POST.get("enviar_email") == "1"
        resultado = generar_avisos_cobro(dias=dias, enviar_email=enviar_email)
        messages.success(
            request,
            f"Avisos generados para cuotas que vencen el {resultado['objetivo']:%d/%m/%Y}: "
            f"{resultado['cuotas']} cuota(s), {resultado['creados']} recordatorio(s) nuevo(s)"
            + (f", {resultado['emails']} correo(s) enviado(s)." if enviar_email else "."),
        )
        return HttpResponseRedirect(f"{reverse('app:aviso_cobro_list')}?dias={dias}")

    hoy = timezone.localdate()
    objetivo = hoy + timedelta(days=dias)
    items = (
        RecordatorioPago.objects.select_related(
            "cuota",
            "cuota__contrato",
            "cuota__contrato__cliente",
        )
        .filter(programado_para=objetivo)
        .order_by("-id")
    )
    cuotas_proximas = (
        CuotaProgramada.objects.select_related("contrato", "contrato__cliente")
        .filter(estado=CuotaProgramada.Estado.PENDIENTE, vence_en=objetivo)
        .order_by("contrato__numero", "numero")
    )
    return render(
        request,
        "app/aviso_cobro_list.html",
        {
            "dias": dias,
            "objetivo": objetivo,
            "items": items,
            "cuotas_proximas": cuotas_proximas,
            "cuotas_proximas_ct": cuotas_proximas.count(),
        },
    )


# ——— Recargo administrativo ———
class ParametroMoraListView(AppLoginRequiredMixin, ListView):
    model = ParametroMora
    template_name = "app/parametro_mora_list.html"
    context_object_name = "items"
    paginate_by = 20


class ParametroMoraCreateView(AppLoginRequiredMixin, CreateView):
    model = ParametroMora
    form_class = forms.ParametroMoraForm
    template_name = "app/parametro_mora_form.html"
    success_url = reverse_lazy("app:parametro_mora_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo recargo administrativo"
        ctx["cancel_url"] = reverse_lazy("app:parametro_mora_list")
        return ctx


class ParametroMoraUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = ParametroMora
    form_class = forms.ParametroMoraForm
    template_name = "app/parametro_mora_form.html"
    success_url = reverse_lazy("app:parametro_mora_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar recargo administrativo"
        ctx["cancel_url"] = reverse_lazy("app:parametro_mora_list")
        return ctx


class ProyectoDeleteView(AppLoginRequiredMixin, SensitiveDeleteMixin, DeleteView):
    model = Proyecto
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:proyecto_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar proyecto"
        ctx["delete_blurb"] = (
            "Quitará el proyecto del sistema. Si existen polígonos, lotes u otros datos vinculados, "
            "la operación puede no permitirse."
        )
        return ctx


class PoligonoDeleteView(AppLoginRequiredMixin, SensitiveDeleteMixin, DeleteView):
    model = Poligono
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:poligono_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar polígono"
        ctx["delete_blurb"] = "Elimina el polígono y datos asociados si el sistema lo permite."
        return ctx


class InmuebleDeleteView(AppLoginRequiredMixin, SensitiveDeleteMixin, DeleteView):
    model = Inmueble
    template_name = "app/confirm_delete.html"

    def get_success_url(self) -> str:
        return _inmueble_url_listado_tras_tipo(
            self.object.tipo, en_alquiler=self.object.en_alquiler
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar inmueble"
        ctx["delete_blurb"] = "No se puede eliminar si hay contratos u otros registros enlazados a este lote o bien."
        return ctx


def _redirect_tras_accion_imagen(inmueble_pk: int) -> HttpResponseRedirect:
    inv = get_object_or_404(Inmueble, pk=inmueble_pk)
    ficha_url = _inmueble_ficha_alquiler_url(inv)
    if ficha_url is not None:
        return HttpResponseRedirect(ficha_url)
    if inv.tipo in (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA):
        return HttpResponseRedirect(reverse("app:inmueble_casa_galeria", args=[inmueble_pk]))
    return HttpResponseRedirect(reverse("app:inmueble_update", args=[inmueble_pk]))


@login_required
@require_POST
def inmueble_imagen_eliminar(request: HttpRequest, inmueble_pk: int, pk: int) -> HttpResponseRedirect:
    if not _inmueble_galeria_superusuario_post_ok(request):
        messages.error(
            request,
            "Credenciales de superusuario incorrectas o incompletas. No se eliminó la imagen.",
        )
        return _redirect_tras_accion_imagen(inmueble_pk)
    img = get_object_or_404(InmuebleImagen, pk=pk, inmueble_id=inmueble_pk)
    img.delete()
    messages.success(request, "Imagen eliminada.")
    return _redirect_tras_accion_imagen(inmueble_pk)


@login_required
@require_POST
def inmueble_imagen_portada(request: HttpRequest, inmueble_pk: int, pk: int) -> HttpResponseRedirect:
    if not _inmueble_galeria_superusuario_post_ok(request):
        messages.error(
            request,
            "Credenciales de superusuario incorrectas. No se cambió la portada.",
        )
        return _redirect_tras_accion_imagen(inmueble_pk)
    img = get_object_or_404(InmuebleImagen, pk=pk, inmueble_id=inmueble_pk)
    InmuebleImagen.objects.filter(inmueble_id=inmueble_pk).update(es_portada=False)
    InmuebleImagen.objects.filter(pk=img.pk).update(es_portada=True)
    messages.success(request, "Portada actualizada.")
    return _redirect_tras_accion_imagen(inmueble_pk)


@login_required
@require_POST
def inmueble_imagen_descripcion(request: HttpRequest, inmueble_pk: int, pk: int) -> HttpResponseRedirect:
    if not _inmueble_galeria_superusuario_post_ok(request):
        messages.error(
            request,
            "Credenciales de superusuario incorrectas. No se guardó la descripción.",
        )
        return _redirect_tras_accion_imagen(inmueble_pk)
    img = get_object_or_404(InmuebleImagen, pk=pk, inmueble_id=inmueble_pk)
    img.descripcion = (request.POST.get("descripcion") or "").strip()[:200]
    img.save(update_fields=["descripcion"])
    messages.success(request, "Descripción de la imagen actualizada.")
    return _redirect_tras_accion_imagen(inmueble_pk)


class ClienteDeleteView(AppLoginRequiredMixin, SensitiveDeleteMixin, DeleteView):
    model = Cliente
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:cliente_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar cliente"
        ctx["delete_blurb"] = "No se puede eliminar si el cliente tiene contratos registrados."
        return ctx


class ContratoDeleteView(AppLoginRequiredMixin, SensitiveDeleteMixin, DeleteView):
    model = Contrato
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:contrato_list")

    def get_queryset(self):
        return filtrar_contratos_queryset_por_vendedor(Contrato.objects.all(), self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar contrato"
        ctx["delete_blurb"] = "Elimina el contrato y datos vinculados permitidos. Si hay pagos u otras restricciones, fallará."
        return ctx


class PagoDeleteView(AppLoginRequiredMixin, SensitiveDeleteMixin, DeleteView):
    model = Pago
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:pago_list")

    def get_queryset(self):
        return filtrar_pagos_queryset_por_vendedor(Pago.objects.all(), self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar pago"
        ctx["delete_blurb"] = "Quita el registro de pago. Los documentos PDF emitidos no se borran automáticamente del archivo."
        return ctx


class ParametroMoraDeleteView(AppLoginRequiredMixin, SensitiveDeleteMixin, DeleteView):
    model = ParametroMora
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:parametro_mora_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar recargo administrativo"
        ctx["delete_blurb"] = "Quita esta política de recargo del sistema."
        return ctx


@login_required
def api_mapa_proyecto(request: HttpRequest, proyecto_id: int) -> JsonResponse:
    proyecto = get_object_or_404(Proyecto, pk=proyecto_id)
    lotes = (
        Inmueble.objects.select_related("poligono", "cliente_reserva", "proyecto")
        .filter(proyecto_id=proyecto_id, tipo=Inmueble.Tipo.LOTE)
        .order_by("poligono__orden", "codigo")
    )
    poligono_id = request.GET.get("poligono_id")
    if poligono_id:
        lotes = lotes.filter(poligono_id=poligono_id)

    inmueble_ids = [i.pk for i in lotes]
    contratos_por_inmueble: dict[int, Contrato] = {}
    if inmueble_ids:
        contratos = (
            Contrato.objects.filter(inmueble_id__in=inmueble_ids)
            .exclude(estado=Contrato.Estado.CANCELADO)
            .select_related("cliente", "vendedor_perfil")
            .order_by("inmueble_id", "-fecha_firma")
        )
        for c in contratos:
            if c.inmueble_id not in contratos_por_inmueble:
                contratos_por_inmueble[c.inmueble_id] = c

    _leyenda = {
        "contado": "Contado (vendido)",
        "reservado": "Reservado",
        "disponible": "Disponible",
        "bloqueado": "Bloqueado",
    }

    features = []
    for lote in lotes:
        if not lote.geometria_json:
            continue
        c = contratos_por_inmueble.get(lote.pk)
        style_key = _mapa_catastral_style_por_estado(lote.estado)
        features.append(
            {
                "type": "Feature",
                "id": lote.pk,
                "properties": {
                    "inmueble_id": lote.pk,
                    "codigo": lote.codigo,
                    "estado": lote.estado,
                    "estado_display": lote.get_estado_display(),
                    "mapa_style": style_key,
                    "venta_leyenda": _leyenda.get(style_key, lote.get_estado_display()),
                    "poligono_id": lote.poligono_id,
                    "poligono_nombre": lote.poligono.nombre if lote.poligono else "",
                    "popup_html": _popup_html_mapa_catastral(lote, c),
                },
                "geometry": lote.geometria_json,
            }
        )

    return JsonResponse(
        {
            "plano_url": proyecto.plano_maestro.url if proyecto.plano_maestro else "",
            "proyecto_id": proyecto.pk,
            "proyecto_nombre": proyecto.nombre,
            "features": features,
            "lotes": [
                {
                    "id": i.pk,
                    "codigo": i.codigo,
                    "estado": i.estado,
                    "poligono_id": i.poligono_id,
                    "poligono_nombre": i.poligono.nombre if i.poligono else "",
                    "tiene_geometria_plano": bool(i.geometria_json),
                }
                for i in lotes
            ],
        }
    )


@login_required
@require_GET
@never_cache
def api_inmueble_estado(request: HttpRequest, inmueble_id: int) -> JsonResponse:
    """
    Estado actual del lote (disponible / reservado / vendido / bloqueado).
    Para avisar al asesor de ventas al elegir el lote, sin guardar el formato.
    """
    from inmobiliaria.forms_web import mensaje_alerta_lote_ocupado

    inv = get_object_or_404(
        Inmueble.objects.select_related("cliente_reserva", "proyecto", "poligono"),
        pk=inmueble_id,
    )
    cli = inv.cliente_reserva
    cli_txt = ""
    if cli is not None:
        cli_txt = f"{(cli.nombres or '').strip()} {(cli.apellidos or '').strip()}".strip()
    alerta = mensaje_alerta_lote_ocupado(inv, permitir_misma_reserva=False)
    disponible = inv.estado == Inmueble.Estado.DISPONIBLE
    if disponible:
        mensaje = (
            f"✓ El lote {(inv.codigo or '').strip() or '—'} está DISPONIBLE. "
            "Puede continuar con el formato (revise de nuevo si otro asesor de ventas lo reserva)."
        )
    else:
        mensaje = alerta or (
            f"El lote {(inv.codigo or '').strip() or '—'} no está disponible "
            f"({inv.get_estado_display()})."
        )
    return JsonResponse(
        {
            "ok": True,
            "id": inv.pk,
            "codigo": inv.codigo,
            "estado": inv.estado,
            "estado_label": inv.get_estado_display(),
            "cliente_reserva": cli_txt,
            "reserva_hasta": (
                inv.reserva_hasta.isoformat() if inv.reserva_hasta else ""
            ),
            "ocupado": not disponible,
            "disponible": disponible,
            "mensaje": mensaje,
            "consultado_en": timezone.localtime().isoformat(timespec="seconds"),
        }
    )


@login_required
@require_POST
def api_mapa_guardar_lote(request: HttpRequest, inmueble_id: int) -> JsonResponse:
    if not check_sensitive_write(request):
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "Debe confirmar acceso con contraseña (use «Confirmar acceso» en la app) "
                    "antes de guardar cambios en el mapa."
                ),
            },
            status=403,
        )
    inmueble = get_object_or_404(Inmueble, pk=inmueble_id, tipo=Inmueble.Tipo.LOTE)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "JSON inválido."}, status=400)

    geom = payload.get("geometry")
    if not isinstance(geom, dict) or geom.get("type") != "Polygon":
        return JsonResponse({"ok": False, "error": "La geometría debe ser Polygon."}, status=400)
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or not coords or not isinstance(coords[0], list):
        return JsonResponse({"ok": False, "error": "Coordenadas inválidas."}, status=400)

    # Validación mínima de rango en coordenadas relativas (0..100).
    for point in coords[0]:
        if not isinstance(point, list) or len(point) < 2:
            return JsonResponse({"ok": False, "error": "Punto inválido."}, status=400)
        x, y = point[0], point[1]
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return JsonResponse({"ok": False, "error": "Punto inválido."}, status=400)
        if x < 0 or x > 100 or y < 0 or y > 100:
            return JsonResponse(
                {"ok": False, "error": "Las coordenadas deben estar entre 0 y 100."},
                status=400,
            )

    inmueble.geometria_json = geom
    inmueble.save(update_fields=["geometria_json"])
    return JsonResponse({"ok": True})


def _mapa_catastral_style_por_estado(estado: str) -> str:
    """Clave de estilo para el front (coincide con leyenda: contado / reservado / disponible)."""
    if estado == Inmueble.Estado.VENDIDO:
        return "contado"
    if estado == Inmueble.Estado.RESERVADO:
        return "reservado"
    if estado == Inmueble.Estado.BLOQUEADO:
        return "bloqueado"
    return "disponible"


def _contrato_visible_para_inmueble(inmueble: Inmueble) -> Contrato | None:
    return (
        Contrato.objects.filter(inmueble=inmueble)
        .exclude(estado=Contrato.Estado.CANCELADO)
        .select_related("cliente", "vendedor_perfil")
        .order_by("-fecha_firma")
        .first()
    )


def _fmt_money_sv(value: Decimal | None) -> str:
    if value is None:
        return "—"
    q = value.quantize(Decimal("0.01"))
    return f"${q:,.2f}"


def _fmt_fecha_corta(d) -> str:
    if d is None:
        return "—"
    return date_format(d, format="SHORT_DATE_FORMAT")


def _truncate_txt(s: str, n: int = 240) -> str:
    t = (s or "").strip()
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def _popup_html_mapa_catastral(
    inmueble: Inmueble, contrato: Contrato | None = None
) -> str:
    if contrato is None:
        contrato = _contrato_visible_para_inmueble(inmueble)
    pol = inmueble.poligono.nombre if inmueble.poligono else "—"
    proyecto_nombre = inmueble.proyecto.nombre if inmueble.proyecto else "—"
    estado_txt = inmueble.get_estado_display()
    leyenda = {
        "contado": "Contado (vendido)",
        "reservado": "Reservado",
        "disponible": "Disponible",
        "bloqueado": "Bloqueado",
    }.get(_mapa_catastral_style_por_estado(inmueble.estado), estado_txt)

    cliente_reserva = None
    if inmueble.estado == Inmueble.Estado.RESERVADO and inmueble.cliente_reserva_id:
        cliente_reserva = inmueble.cliente_reserva

    def dl_row(label: str, value: str) -> str:
        return f"<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>"

    bloques: list[str] = []

    # 1) Cabecera + estado (lo primero que pide ver)
    head = (
        f'<div class="mapa-catastral-popup__head">'
        f'<p class="mapa-catastral-popup__title">Lote {html.escape(inmueble.codigo)}</p>'
        f'<p class="mapa-catastral-popup__meta muted">{html.escape(proyecto_nombre)} · {html.escape(pol)}</p>'
        f'<p class="mapa-catastral-popup__estado"><strong>Estado:</strong> '
        f'<span class="mapa-catastral-popup__estado-val">{html.escape(estado_txt)}</span>'
        f' · <span class="muted">Plano:</span> {html.escape(leyenda)}</p>'
        f"</div>"
    )
    bloques.append(head)

    # 2) Persona según caso: reserva vs venta vs disponible
    bloques.append('<section class="mapa-catastral-popup__section">')
    bloques.append('<h4 class="mapa-catastral-popup__h4">Quién / compra</h4>')
    bloques.append('<dl class="mapa-catastral-popup__dl">')

    if inmueble.estado == Inmueble.Estado.RESERVADO:
        if cliente_reserva:
            nombre = f"{cliente_reserva.nombres} {cliente_reserva.apellidos}".strip()
            bloques.append(dl_row("Apartado / reservado a", nombre))
            bloques.append(dl_row("Teléfono", cliente_reserva.telefono or "—"))
            bloques.append(dl_row("Correo", cliente_reserva.email or "—"))
            bloques.append(
                dl_row("Reserva válida hasta", _fmt_fecha_corta(inmueble.reserva_hasta))
            )
            bloques.append(
                dl_row(
                    "Precio de lista (referencia)",
                    _fmt_money_sv(inmueble.precio_lista),
                )
            )
        else:
            bloques.append(
                "<dt>Apartado</dt><dd>Sin cliente de reserva registrado.</dd>"
            )
    elif inmueble.estado == Inmueble.Estado.VENDIDO and contrato:
        cli = contrato.cliente
        nombre = f"{cli.nombres} {cli.apellidos}".strip()
        bloques.append(dl_row("Vendido / comprador", nombre))
        bloques.append(dl_row("Teléfono", cli.telefono or "—"))
        bloques.append(dl_row("Correo", cli.email or "—"))
        bloques.append(
            dl_row(
                "Fecha de firma (inicio operación)",
                _fmt_fecha_corta(contrato.fecha_firma),
            )
        )
        bloques.append(dl_row("Precio acordado (contrato)", _fmt_money_sv(contrato.precio_final)))
        if contrato.precio_lista_referencia is not None:
            bloques.append(
                dl_row(
                    "Precio lista (referencia al firmar)",
                    _fmt_money_sv(contrato.precio_lista_referencia),
                )
            )
        if contrato.descuento_implicito_vs_referencia is not None:
            bloques.append(
                dl_row(
                    "Diferencia ref. − precio final",
                    _fmt_money_sv(contrato.descuento_implicito_vs_referencia),
                )
            )
    elif inmueble.estado == Inmueble.Estado.VENDIDO and not contrato:
        bloques.append(
            "<dt>Comprador</dt><dd>Estado vendido sin contrato activo en el sistema; revise el módulo de contratos.</dd>"
        )
    elif contrato and inmueble.estado != Inmueble.Estado.DISPONIBLE:
        cli = contrato.cliente
        nombre = f"{cli.nombres} {cli.apellidos}".strip()
        bloques.append(dl_row("Cliente (contrato)", nombre))
        bloques.append(dl_row("Teléfono", cli.telefono or "—"))
    else:
        bloques.append(
            "<dt>Cliente</dt><dd>No aplica (lote disponible u otro estado sin contrato).</dd>"
        )

    bloques.append("</dl></section>")

    # 3) Contrato y condiciones (si existe)
    if contrato:
        bloques.append('<section class="mapa-catastral-popup__section">')
        bloques.append('<h4 class="mapa-catastral-popup__h4">Contrato y condiciones</h4>')
        bloques.append('<dl class="mapa-catastral-popup__dl">')
        bloques.append(dl_row("Número de contrato", contrato.numero))
        bloques.append(dl_row("Estado del contrato", contrato.get_estado_display()))
        bloques.append(
            dl_row("Etapa en lotificación", contrato.get_etapa_comercial_display())
        )
        bloques.append(
            dl_row("Modalidad de pago", contrato.get_modalidad_financiamiento_display())
        )
        if contrato.plan_anos is not None:
            bloques.append(
                dl_row(
                    "Plazo de financiamiento",
                    str(contrato.get_plan_anos_display()),
                )
            )
        if contrato.cuota_mensual_estimada is not None:
            bloques.append(
                dl_row(
                    "Cuota mensual estimada",
                    _fmt_money_sv(contrato.cuota_mensual_estimada),
                )
            )
        if contrato.tasa_interes_anual is not None:
            bloques.append(
                dl_row(
                    "Tasa anual negociada (%)",
                    f"{contrato.tasa_interes_anual:.4f}",
                )
            )
        vendedor_txt = "—"
        if contrato.vendedor_perfil_id:
            vendedor_txt = str(contrato.vendedor_perfil)
        elif contrato.vendedor_nombre:
            vendedor_txt = contrato.vendedor_nombre
        bloques.append(dl_row("Asesor de ventas", vendedor_txt))
        bloques.append("</dl></section>")

    # 4) Datos del lote (inventario)
    bloques.append('<section class="mapa-catastral-popup__section">')
    bloques.append('<h4 class="mapa-catastral-popup__h4">Datos del lote</h4>')
    bloques.append('<dl class="mapa-catastral-popup__dl">')
    bloques.append(dl_row("Precio de lista", _fmt_money_sv(inmueble.precio_lista)))
    if inmueble.area_m2 is not None:
        bloques.append(dl_row("Área (m²)", f"{inmueble.area_m2:,.4f}".rstrip("0").rstrip(".")))
    if inmueble.area_varas_cuadradas is not None:
        bloques.append(
            dl_row("Área (v²)", f"{inmueble.area_varas_cuadradas:,.4f}".rstrip("0").rstrip("."))
        )
    bloques.append("</dl></section>")

    edit_url = reverse("app:inmueble_update", kwargs={"pk": inmueble.pk})
    acciones = [f'<a href="{html.escape(edit_url)}">Editar inmueble</a>']
    if contrato:
        contrato_url = reverse("app:contrato_update", kwargs={"pk": contrato.pk})
        acciones.append(f'<a href="{html.escape(contrato_url)}">Ver contrato</a>')
    bloques.append(
        f'<p class="mapa-catastral-popup__actions">{" · ".join(acciones)}</p>'
    )

    return f'<div class="mapa-catastral-popup">{"".join(bloques)}</div>'


class MapaCatastralView(AppLoginRequiredMixin, TemplateView):
    """Mapa Leaflet sobre teselas (OSM / Google opcional) con lotes en WGS84."""

    template_name = "app/mapa_catastral.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["proyectos"] = Proyecto.objects.order_by("nombre")
        ctx["poligonos"] = Poligono.objects.select_related("proyecto").order_by(
            "proyecto__nombre", "orden", "nombre"
        )
        ctx["google_maps_api_key"] = getattr(settings, "GOOGLE_MAPS_API_KEY", "") or ""
        return ctx


@login_required
def api_mapa_catastral(request: HttpRequest, proyecto_id: int) -> JsonResponse:
    """GeoJSON FeatureCollection con datos para colorear y popup."""
    proyecto = get_object_or_404(Proyecto, pk=proyecto_id)
    lotes = (
        Inmueble.objects.select_related("poligono", "cliente_reserva", "proyecto")
        .filter(proyecto_id=proyecto_id, tipo=Inmueble.Tipo.LOTE)
        .order_by("poligono__orden", "codigo")
    )
    poligono_id = request.GET.get("poligono_id")
    if poligono_id:
        lotes = lotes.filter(poligono_id=poligono_id)

    # Precarga contratos por inmueble (uno relevante por lote).
    inmueble_ids = [i.pk for i in lotes]
    contratos_por_inmueble: dict[int, Contrato] = {}
    if inmueble_ids:
        contratos = (
            Contrato.objects.filter(inmueble_id__in=inmueble_ids)
            .exclude(estado=Contrato.Estado.CANCELADO)
            .select_related("cliente", "vendedor_perfil")
            .order_by("inmueble_id", "-fecha_firma")
        )
        for c in contratos:
            if c.inmueble_id not in contratos_por_inmueble:
                contratos_por_inmueble[c.inmueble_id] = c

    features = []
    lista_lotes = []
    for lote in lotes:
        lista_lotes.append(
            {
                "id": lote.pk,
                "codigo": lote.codigo,
                "estado": lote.estado,
                "poligono_id": lote.poligono_id,
                "poligono_nombre": lote.poligono.nombre if lote.poligono else "",
                "tiene_geometria_catastral": bool(lote.geometria_catastral_geojson),
            }
        )
        geom = lote.geometria_catastral_geojson
        if not geom or not isinstance(geom, dict) or geom.get("type") != "Polygon":
            continue

        style_key = _mapa_catastral_style_por_estado(lote.estado)
        c = contratos_por_inmueble.get(lote.pk)

        features.append(
            {
                "type": "Feature",
                "id": lote.pk,
                "properties": {
                    "inmueble_id": lote.pk,
                    "codigo": lote.codigo,
                    "estado": lote.estado,
                    "estado_display": lote.get_estado_display(),
                    "mapa_style": style_key,
                    "venta_leyenda": {
                        "contado": "Contado",
                        "reservado": "Reservado",
                        "disponible": "Disponible",
                        "bloqueado": "Bloqueado",
                    }.get(style_key, lote.get_estado_display()),
                    "poligono_id": lote.poligono_id,
                    "poligono_nombre": lote.poligono.nombre if lote.poligono else "",
                    "popup_html": _popup_html_mapa_catastral(lote, c),
                },
                "geometry": geom,
            }
        )

    return JsonResponse(
        {
            "type": "FeatureCollection",
            "proyecto_id": proyecto.pk,
            "proyecto_nombre": proyecto.nombre,
            "features": features,
            "lotes": lista_lotes,
        }
    )


def _validar_polygon_wgs84(geom: dict) -> str | None:
    """Devuelve mensaje de error o None si es válido."""
    if geom.get("type") != "Polygon":
        return "La geometría debe ser Polygon."
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or not coords or not isinstance(coords[0], list):
        return "Coordenadas inválidas."
    ring = coords[0]
    for point in ring:
        if not isinstance(point, list) or len(point) < 2:
            return "Punto inválido."
        try:
            lng = float(point[0])
            lat = float(point[1])
        except (TypeError, ValueError):
            return "Punto inválido."
        if lng < -180 or lng > 180 or lat < -90 or lat > 90:
            return "Las coordenadas deben estar en WGS84 (longitud −180…180, latitud −90…90)."
    return None


@login_required
@require_POST
def api_mapa_catastral_guardar(request: HttpRequest, inmueble_id: int) -> JsonResponse:
    if not check_sensitive_write(request):
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "Debe confirmar acceso con contraseña (use «Confirmar acceso» en la app) "
                    "antes de guardar el mapa catastral."
                ),
            },
            status=403,
        )
    inmueble = get_object_or_404(Inmueble, pk=inmueble_id, tipo=Inmueble.Tipo.LOTE)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "JSON inválido."}, status=400)

    geom = payload.get("geometry")
    if not isinstance(geom, dict):
        return JsonResponse({"ok": False, "error": "Falta geometry."}, status=400)
    err = _validar_polygon_wgs84(geom)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)

    inmueble.geometria_catastral_geojson = geom
    inmueble.save(update_fields=["geometria_catastral_geojson"])
    return JsonResponse({"ok": True})
