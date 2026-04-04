"""Vistas web minimalistas (azul / blanco / gris) — gestión sin depender del admin."""

import csv
import html
import json
import logging
import mimetypes
import os
import tempfile
import time
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
from django.db.models import ProtectedError, Sum
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
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
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
    skips_sensitive_reauth,
    ttl_seconds,
)

from . import forms_web as forms
from .cuotas_calendario import (
    construir_cuotas_programadas,
    fecha_primera_cuota_desde_formato_contrato,
    monto_uniforme_por_cuota,
)
from docs.services import generar_pdf_desde_plantilla

from .models import (
    Cliente,
    ClienteDocumento,
    Contrato,
    CuotaProgramada,
    FormatoAceptacion,
    Inmueble,
    Pago,
    ParametroMora,
    Poligono,
    Proyecto,
    Vendedor,
)

logger = logging.getLogger(__name__)


def _formato_aceptacion_promesa_column_ready() -> bool:
    """
    True si existe la columna promesa_venta_escaneada (migración 0024 aplicada).
    Si no, varias vistas usan .defer() para que el listado y la edición no rompan el SELECT.
    """
    table = FormatoAceptacion._meta.db_table
    col = "promesa_venta_escaneada"
    try:
        with connection.cursor() as cursor:
            desc = connection.introspection.get_table_description(cursor, table)
        names = {getattr(row, "name", "") or "" for row in desc}
        names_l = {n.lower() for n in names}
        return col.lower() in names_l
    except Exception:
        # Si falla introspección, asumir columna presente: el listado ya usa defer y el botón debe verse.
        return True


def _formato_aceptacion_qs_contrato_pdf():
    qs = FormatoAceptacion.objects.select_related(
        "contrato",
        "contrato__cliente",
        "contrato__inmueble",
        "contrato__inmueble__proyecto",
    )
    if not _formato_aceptacion_promesa_column_ready():
        qs = qs.defer("promesa_venta_escaneada")
    return qs


def _formato_aceptacion_qs_pk():
    qs = FormatoAceptacion.objects.all()
    if not _formato_aceptacion_promesa_column_ready():
        qs = qs.defer("promesa_venta_escaneada")
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


def _firma_preview_flags(formato: FormatoAceptacion | None) -> dict[str, bool]:
    """True solo si hay archivo legible en storage (evita <img> roto en producción)."""
    empty = {"aceptante": False, "vendedor": False, "autorizado": False}
    if not formato or not getattr(formato, "pk", None):
        return empty
    out: dict[str, bool] = {}
    for key, attr in (
        ("aceptante", "firma_aceptante"),
        ("vendedor", "firma_vendedor"),
        ("autorizado", "firma_autorizado"),
    ):
        ff = getattr(formato, attr, None)
        out[key] = bool(ff and ff.name and default_storage.exists(ff.name))
    return out


def _formato_firmas_ausentes_en_storage(formato: FormatoAceptacion) -> list[str]:
    """
    Firmas con ruta en BD pero archivo inexistente en default_storage.
    Ocurre en App Platform sin S3/volumen: el PDF y las miniaturas fallan.
    """
    faltan: list[str] = []
    for label, attr in (
        ("aceptante", "firma_aceptante"),
        ("vendedor", "firma_vendedor"),
        ("autorizado", "firma_autorizado"),
    ):
        ff = getattr(formato, attr, None)
        if ff and ff.name and not default_storage.exists(ff.name):
            faltan.append(label)
    return faltan


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
        "16 Calle Ote. Pol. C-1 #24. Col. El Molino. San Miguel. Tel. 7547-0186",
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
        ctx = {
            "formato": formato,
            "proyecto": _proyecto_para_pdf_formato(formato),
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
    return list(
        Proyecto.objects.filter(activo=True)
        .order_by("nombre")
        .values("id", "nombre", "direccion")
    )


def _catalogo_inmuebles_formato_aceptacion() -> dict:
    """Polígonos por proyecto, lotes por polígono (o sin polígono) e índice por id de inmueble."""
    polis_por_proyecto: dict[int, list[dict]] = defaultdict(list)
    for pol in (
        Poligono.objects.filter(proyecto__activo=True)
        .select_related("proyecto")
        .order_by("proyecto_id", "orden", "nombre")
    ):
        polis_por_proyecto[pol.proyecto_id].append({"id": pol.pk, "nombre": pol.nombre})

    lotes_por_clave: dict[str, list[dict]] = defaultdict(list)
    inmueble_por_id: dict[str, dict] = {}
    for inv in (
        Inmueble.objects.filter(proyecto__activo=True)
        .select_related("poligono", "proyecto")
        .order_by("proyecto_id", "poligono_id", "codigo")
    ):
        clave = str(inv.poligono_id) if inv.poligono_id else f"np:{inv.proyecto_id}"
        pol_nombre = inv.poligono.nombre if inv.poligono_id else ""
        entry = {
            "id": inv.pk,
            "codigo": inv.codigo,
            "precio": str(inv.precio_lista),
            "area_m2": str(inv.area_m2) if inv.area_m2 is not None else "",
            "area_v2": str(inv.area_varas_cuadradas)
            if inv.area_varas_cuadradas is not None
            else "",
            "poligono_nombre": pol_nombre,
            "proyecto_id": inv.proyecto_id,
            "clave_poligono": clave,
        }
        lotes_por_clave[clave].append(entry)
        inmueble_por_id[str(inv.pk)] = entry

    return {
        "poligonosPorProyecto": {str(k): v for k, v in polis_por_proyecto.items()},
        "lotesPorClave": dict(lotes_por_clave),
        "inmueblePorId": inmueble_por_id,
    }


def _formato_aceptacion_form_sections(form: forms.FormatoAceptacionForm) -> list[dict]:
    """Agrupa campos del formato impreso para el template (sin campos ocultos de lienzo)."""
    G = form.__getitem__
    return [
        {
            "title": "Datos personales",
            "rows": [
                [G("nombre_cliente")],
                [G("lugar_nacimiento"), G("fecha_nacimiento")],
                [G("dui_numero"), G("dui_exp_lugar"), G("dui_exp_fecha"), G("nit_numero")],
                [G("direccion_domicilio"), G("telefono_domicilio")],
                [G("direccion_notificacion"), G("telefono_notificacion")],
                [G("trabaja_lo_propio"), G("nombre_empresa_trabajo")],
                [G("direccion_trabajo"), G("telefono_trabajo")],
                [G("cargo"), G("sueldo")],
                [G("num_familia_grupo"), G("num_personas_trabajan"), G("num_personas_estudian")],
            ],
        },
        {
            "title": "Referencias comerciales",
            "rows": [
                [G("ref_com_nombre_1"), G("ref_com_tel_1"), G("ref_com_obs_1")],
                [G("ref_com_nombre_2"), G("ref_com_tel_2"), G("ref_com_obs_2")],
                [G("ref_com_nombre_3"), G("ref_com_tel_3"), G("ref_com_obs_3")],
            ],
        },
        {
            "title": "Referencias personales",
            "rows": [
                [G("ref_per_nombre_1"), G("ref_per_tel_1"), G("ref_per_obs_1")],
                [G("ref_per_nombre_2"), G("ref_per_tel_2"), G("ref_per_obs_2")],
                [G("ref_per_nombre_3"), G("ref_per_tel_3"), G("ref_per_obs_3")],
            ],
        },
        {
            "title": "Datos del terreno",
            "rows": [
                [G("nombre_proyecto")],
                [G("direccion_terreno")],
            ],
        },
        {
            "title": "Datos del crédito",
            "rows": [
                [G("area_m2_txt"), G("area_v2_txt")],
                [G("valor_inmueble")],
                [G("prima_1"), G("prima_1_fecha")],
                [G("prima_2"), G("prima_2_fecha")],
                [G("valor_financiamiento"), G("letra_mensual")],
                [G("plazo_txt"), G("num_cuota_txt"), G("interes_txt")],
                [G("fecha_primera_cuota"), G("fecha_pago_mensual")],
                [G("lugar_pago")],
                [G("observaciones_financiamiento")],
            ],
        },
        {
            "title": "Beneficiarios",
            "rows": [
                [G("ben_nombre_1"), G("ben_parentesco_1"), G("ben_porcentaje_1")],
                [G("ben_nombre_2"), G("ben_parentesco_2"), G("ben_porcentaje_2")],
            ],
        },
        {
            "title": "Elaborado por y cierre",
            "rows": [
                [G("elaborado_por"), G("lugar_y_fecha")],
            ],
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
    """Hub de módulos (menú de gestión)."""

    template_name = "app/index.html"


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
    template_name = "app/object_form.html"
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
    template_name = "app/object_form.html"
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
class InmuebleListView(AppLoginRequiredMixin, ListView):
    model = Inmueble
    template_name = "app/inmueble_list.html"
    context_object_name = "items"
    paginate_by = 25
    queryset = Inmueble.objects.select_related("proyecto", "poligono")


class InmuebleCreateView(AppLoginRequiredMixin, CreateView):
    model = Inmueble
    form_class = forms.InmuebleForm
    template_name = "app/object_form.html"
    success_url = reverse_lazy("app:inmueble_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo inmueble"
        ctx["cancel_url"] = reverse_lazy("app:inmueble_list")
        return ctx


class InmuebleUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = Inmueble
    form_class = forms.InmuebleForm
    template_name = "app/inmueble_form.html"
    success_url = reverse_lazy("app:inmueble_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar inmueble"
        ctx["cancel_url"] = reverse_lazy("app:inmueble_list")
        ctx["historial_precios"] = self.object.historial_precios.all()[:50]
        return ctx


# ——— Clientes ———
class ClienteListView(AppLoginRequiredMixin, ListView):
    model = Cliente
    template_name = "app/cliente_list.html"
    context_object_name = "items"
    paginate_by = 30


def _guardar_documentos_cliente_upload(request, cliente: Cliente) -> None:
    desc = (request.POST.get("documento_descripcion_cliente") or "").strip()[:200]
    for f in request.FILES.getlist("documentos_cliente"):
        ClienteDocumento.objects.create(cliente=cliente, archivo=f, descripcion=desc)


class ClienteCreateView(AppLoginRequiredMixin, CreateView):
    model = Cliente
    form_class = forms.ClienteForm
    template_name = "app/object_form.html"
    success_url = reverse_lazy("app:cliente_list")

    def form_valid(self, form):
        resp = super().form_valid(form)
        _guardar_documentos_cliente_upload(self.request, self.object)
        return resp

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
    template_name = "app/object_form.html"
    success_url = reverse_lazy("app:cliente_list")

    def form_valid(self, form):
        resp = super().form_valid(form)
        _guardar_documentos_cliente_upload(self.request, self.object)
        return resp

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
        return ctx


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
    razon = getattr(
        settings,
        "PBR_PROMESA_RAZON_SOCIAL_VENDEDOR",
        "PAREDES BIENES RAÍCES",
    )
    pdf_bytes = generar_pdf_desde_plantilla(
        template_name="docs/reporte_cliente.html",
        context={
            "cliente": cliente,
            "contratos": contratos,
            "documentos": documentos_reporte,
            "emitido_en": timezone.now(),
            "razon_social": razon,
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
        ctx["form_title"] = "Nuevo vendedor"
        ctx["cancel_url"] = reverse_lazy("app:vendedor_list")
        return ctx


class VendedorUpdateView(VendedoresGestionMixin, SensitiveEditMixin, UpdateView):
    model = Vendedor
    form_class = forms.VendedorForm
    template_name = "app/vendedor_form.html"
    success_url = reverse_lazy("app:vendedor_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = f"Editar vendedor: {self.object.nombre_completo}"
        ctx["cancel_url"] = reverse_lazy("app:vendedor_list")
        return ctx


class VendedorDeleteView(VendedoresGestionMixin, SensitiveDeleteMixin, DeleteView):
    model = Vendedor
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:vendedor_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar vendedor"
        ctx["delete_blurb"] = (
            "Los contratos vinculados quedarán sin vendedor del catálogo (no se borran contratos)."
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
    form_class = forms.ContratoForm
    template_name = "app/contrato_form.html"
    success_url = reverse_lazy("app:contrato_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["filtro_proyecto_id"] = self.request.GET.get("proyecto") or None
        kwargs["filtro_poligono_id"] = self.request.GET.get("poligono") or None
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo contrato"
        ctx["cancel_url"] = reverse_lazy("app:contrato_list")
        ctx["form_inmueble_filters"] = True
        ctx["proyectos_filtro"] = Proyecto.objects.order_by("nombre")
        ctx["poligonos_filtro"] = Poligono.objects.select_related("proyecto").order_by(
            "proyecto__nombre", "orden", "nombre"
        )
        ctx["filtro_get_proyecto"] = self.request.GET.get("proyecto") or ""
        ctx["filtro_get_poligono"] = self.request.GET.get("poligono") or ""
        ctx["form_contrato_autocomplete_off"] = True
        return ctx


class ContratoUpdateView(AppLoginRequiredMixin, SensitiveEditSessionMixin, UpdateView):
    model = Contrato
    form_class = forms.ContratoForm
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
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar contrato"
        ctx["cancel_url"] = reverse_lazy("app:contrato_list")
        ctx["form_inmueble_filters"] = True
        ctx["proyectos_filtro"] = Proyecto.objects.order_by("nombre")
        ctx["poligonos_filtro"] = Poligono.objects.select_related("proyecto").order_by(
            "proyecto__nombre", "orden", "nombre"
        )
        ctx["filtro_get_proyecto"] = self.request.GET.get("proyecto") or ""
        ctx["filtro_get_poligono"] = self.request.GET.get("poligono") or ""
        ctx["form_contrato_autocomplete_off"] = True
        if "cuotas_formset" not in ctx:
            ctx["cuotas_formset"] = forms.CuotaProgramadaFormSet(
                instance=self.object,
                prefix="cuotas",
            )
        if "generar_cuotas_form" not in ctx:
            gen_initial: dict = {}
            if self.object.plan_anos:
                gen_initial["num_cuotas"] = int(self.object.plan_anos) * 12
            cm = self.object.cuota_mensual_estimada
            if cm is None:
                cm = forms._cuota_mensual_estimada(
                    self.object.precio_final,
                    self.object.plan_anos,
                    self.object.tasa_interes_anual,
                    self.object.modalidad_financiamiento or "",
                )
            if cm is not None:
                gen_initial["monto_cuota"] = cm
            fd_fmt = fecha_primera_cuota_desde_formato_contrato(self.object)
            if fd_fmt:
                gen_initial["fecha_primera"] = fd_fmt
            elif getattr(self.object, "fecha_firma", None):
                gen_initial.setdefault("fecha_primera", self.object.fecha_firma)
            ctx["generar_cuotas_form"] = forms.GenerarCuotasCalendarioForm(
                prefix="gen",
                initial=gen_initial,
            )
        return ctx

    def _handle_generar_cuotas(self, request: HttpRequest) -> HttpResponse:
        self.object = self.get_object()
        post = request.POST.copy()
        if not (post.get("gen-num_cuotas") or "").strip() and self.object.plan_anos:
            post["gen-num_cuotas"] = str(int(self.object.plan_anos) * 12)
        gform = forms.GenerarCuotasCalendarioForm(post, prefix="gen")
        if not gform.is_valid():
            form = self.get_form_class()(
                instance=self.object,
                **self.get_form_kwargs(),
            )
            formset = forms.CuotaProgramadaFormSet(
                instance=self.object,
                prefix="cuotas",
            )
            return self.render_to_response(
                self.get_context_data(
                    form=form,
                    cuotas_formset=formset,
                    generar_cuotas_form=gform,
                )
            )

        if self.object.cuotas_programadas.filter(
            estado=CuotaProgramada.Estado.PAGADA
        ).exists():
            messages.error(
                request,
                "No se puede generar el calendario automáticamente porque ya hay cuotas pagadas. "
                "Agregue o ajuste cuotas manualmente en la tabla.",
            )
            url = reverse("app:contrato_update", kwargs={"pk": self.object.pk})
            q = request.GET.urlencode()
            if q:
                url = f"{url}?{q}"
            return HttpResponseRedirect(url)

        n = gform.cleaned_data["num_cuotas"]
        fecha_primera = gform.cleaned_data["fecha_primera"]
        monto_in = gform.cleaned_data.get("monto_cuota")

        monto_efectivo = monto_in
        if monto_efectivo is None:
            monto_efectivo = self.object.cuota_mensual_estimada
        if monto_efectivo is None:
            monto_efectivo = forms._cuota_mensual_estimada(
                self.object.precio_final,
                self.object.plan_anos,
                self.object.tasa_interes_anual,
                self.object.modalidad_financiamiento or "",
            )
        try:
            monto_linea = monto_uniforme_por_cuota(
                self.object.precio_final, n, monto_efectivo
            )
        except (ValueError, ArithmeticError):
            messages.error(request, "Revise precio del contrato y cantidad de cuotas.")
            url = reverse("app:contrato_update", kwargs={"pk": self.object.pk})
            q = request.GET.urlencode()
            if q:
                url = f"{url}?{q}"
            return HttpResponseRedirect(url)

        with transaction.atomic():
            self.object.cuotas_programadas.all().delete()
            nuevas = construir_cuotas_programadas(
                self.object,
                fecha_primera=fecha_primera,
                n_cuotas=n,
                monto_cuota=monto_linea,
            )
            CuotaProgramada.objects.bulk_create(nuevas)

        messages.success(
            request,
            f"Se generaron {n} cuotas mensuales a partir del {fecha_primera.strftime('%d/%m/%Y')}.",
        )
        url = reverse("app:contrato_update", kwargs={"pk": self.object.pk})
        q = request.GET.urlencode()
        if q:
            url = f"{url}?{q}"
        return HttpResponseRedirect(url)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.POST.get("btn_generar_cuotas"):
            if not check_sensitive_write(request):
                messages.error(
                    request,
                    "Debe confirmar su contraseña para generar cuotas. Use «Confirmar contraseña» al pie o vuelva a confirmar acceso.",
                )
                url = reverse("app:contrato_update", kwargs={"pk": self.object.pk})
                q = request.GET.urlencode()
                if q:
                    url = f"{url}?{q}"
                return HttpResponseRedirect(url)
            return self._handle_generar_cuotas(request)
        form_class = self.get_form_class()
        form = form_class(**self.get_form_kwargs())
        formset = forms.CuotaProgramadaFormSet(
            request.POST,
            instance=self.object,
            prefix="cuotas",
        )
        if form.is_valid() and formset.is_valid():
            if not check_sensitive_write(request):
                form.add_error(
                    None,
                    ValidationError(
                        "Debe ingresar su contraseña en «Confirmar contraseña» para guardar los cambios.",
                    ),
                )
                return self.render_to_response(
                    self.get_context_data(form=form, cuotas_formset=formset)
                )
            with transaction.atomic():
                self.object = form.save()
                formset.instance = self.object
                formset.save()
            if not skips_sensitive_reauth(request.user):
                grant(request)
            return HttpResponseRedirect(self.get_success_url())
        return self.render_to_response(
            self.get_context_data(form=form, cuotas_formset=formset)
        )


class FormatoAceptacionCreateStandaloneView(AppLoginRequiredMixin, CreateView):
    """Alta directa del formato, sin contrato obligatorio ni pasos previos."""

    model = FormatoAceptacion
    form_class = forms.FormatoAceptacionForm
    template_name = "app/formato_aceptacion_form.html"

    def form_valid(self, form):
        form.instance.creado_por = self.request.user
        prev_firmas = False
        response = super().form_valid(form)
        messages.success(self.request, "Formato de aceptación guardado.")
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
        ctx["formato_encabezado_direccion"] = _formato_aceptacion_direccion_impreso()
        ctx["proyectos_formato"] = _proyectos_para_formato_aceptacion()
        ctx["formato_catalogo_inmuebles"] = _catalogo_inmuebles_formato_aceptacion()
        form = ctx.get("form") or self.get_form()
        ctx["formato_sections"] = _formato_aceptacion_form_sections(form)
        col_ok = _formato_aceptacion_promesa_column_ready()
        ctx["formato_promesa_columna_bd"] = col_ok
        ctx["formato_promesa_migrate_pendiente"] = bool(
            getattr(self, "object", None) and self.object.pk and not col_ok
        )
        if getattr(self, "object", None) and self.object.pk:
            if col_ok:
                ctx["formato_promesa_subir_url"] = reverse(
                    "app:formato_aceptacion_promesa_subir", kwargs={"pk": self.object.pk}
                )
                f = self.object.promesa_venta_escaneada
                ctx["formato_promesa_descargar_url"] = (
                    reverse(
                        "app:formato_aceptacion_promesa_descargar",
                        kwargs={"pk": self.object.pk},
                    )
                    if f and f.name
                    else None
                )
            else:
                ctx["formato_promesa_subir_url"] = None
                ctx["formato_promesa_descargar_url"] = None
        else:
            ctx["formato_promesa_subir_url"] = None
            ctx["formato_promesa_descargar_url"] = None
        return ctx


@method_decorator(never_cache, name="dispatch")
class FormatoAceptacionListView(AppLoginRequiredMixin, ListView):
    """Módulo aparte: todos los formatos de aceptación y acceso rápido a edición/PDF."""

    model = FormatoAceptacion
    template_name = "app/formato_aceptacion_list.html"
    context_object_name = "items"
    paginate_by = 30

    def get_queryset(self):
        # defer: si en producción aún no corrió migrate 0024, el listado no falla al no
        # pedir la columna promesa_venta_escaneada en el SELECT.
        return (
            FormatoAceptacion.objects.order_by("-numero_formulario", "-id")
            .select_related(
                "contrato",
                "contrato__inmueble",
                "contrato__inmueble__proyecto",
            )
            .defer("promesa_venta_escaneada")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["formato_promesa_lista_ok"] = _formato_aceptacion_promesa_column_ready()
        return ctx


class FormatoAceptacionUpdateView(
    AppLoginRequiredMixin, FormatoSuperuserGateMixin, UpdateView
):
    model = FormatoAceptacion
    form_class = forms.FormatoAceptacionForm
    template_name = "app/formato_aceptacion_form.html"

    def get_queryset(self):
        return _formato_aceptacion_qs_contrato_pdf()

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        return kw

    def form_valid(self, form):
        pk = self.object.pk
        prev_firmas = False
        if pk:
            try:
                q = FormatoAceptacion.objects.filter(pk=pk)
                if not _formato_aceptacion_promesa_column_ready():
                    q = q.defer("promesa_venta_escaneada")
                prev_firmas = q.get().firmas_completas
            except FormatoAceptacion.DoesNotExist:
                prev_firmas = False
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
        ctx["formato_encabezado_direccion"] = _formato_aceptacion_direccion_impreso()
        ctx["proyectos_formato"] = _proyectos_para_formato_aceptacion()
        ctx["formato_catalogo_inmuebles"] = _catalogo_inmuebles_formato_aceptacion()
        form = ctx.get("form") or self.get_form()
        ctx["formato_sections"] = _formato_aceptacion_form_sections(form)
        col_ok = _formato_aceptacion_promesa_column_ready()
        ctx["formato_promesa_columna_bd"] = col_ok
        ctx["formato_promesa_migrate_pendiente"] = not col_ok
        if col_ok:
            ctx["formato_promesa_subir_url"] = reverse(
                "app:formato_aceptacion_promesa_subir", kwargs={"pk": self.object.pk}
            )
            pf = self.object.promesa_venta_escaneada
            ctx["formato_promesa_descargar_url"] = (
                reverse(
                    "app:formato_aceptacion_promesa_descargar",
                    kwargs={"pk": self.object.pk},
                )
                if pf and pf.name
                else None
            )
        else:
            ctx["formato_promesa_subir_url"] = None
            ctx["formato_promesa_descargar_url"] = None
        return ctx


class FormatoAceptacionDeleteView(
    AppLoginRequiredMixin, FormatoSuperuserGateMixin, DeleteView
):
    model = FormatoAceptacion
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:formato_aceptacion_list")

    def get_queryset(self):
        qs = FormatoAceptacion.objects.all()
        if not _formato_aceptacion_promesa_column_ready():
            qs = qs.defer("promesa_venta_escaneada")
        return qs

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
            "Quitará este formato y sus datos. Los archivos de firma en almacenamiento pueden quedar huérfanos; "
            "revise su bucket o carpeta media si aplica."
        )
        return ctx


@login_required
def formato_aceptacion_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    formato = get_object_or_404(_formato_aceptacion_qs_contrato_pdf(), pk=pk)
    if not formato.firmas_completas:
        messages.error(
            request,
            "Guarde el formulario con las tres firmas dibujadas (aceptante, vendedor y autorizado) "
            "antes de generar el PDF.",
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


@login_required
@never_cache
def formato_firma_preview(request: HttpRequest, pk: int, tipo: str) -> HttpResponse:
    """
    Sirve la imagen de firma bajo /app/ con sesión iniciada.
    En producción (DEBUG=False) /media/ no es público por defecto: usar .url en <img> rompe la vista previa.
    """
    if tipo not in _FORMATO_FIRMA_PREVIEW_ROLES:
        raise Http404()
    formato = get_object_or_404(_formato_aceptacion_qs_pk(), pk=pk)
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
    formato = get_object_or_404(FormatoAceptacion, pk=pk)
    form = forms.FormatoAceptacionPromesaForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Revise el archivo (PDF, JPG o PNG).")
        return HttpResponseRedirect(redir)
    formato.promesa_venta_escaneada = form.cleaned_data["promesa_venta_escaneada"]
    formato.save()
    try:
        from docs.formato_aceptacion_notificacion import notificar_promesa_escaneada_tras_subir

        # select_related para correo/tel del cliente al notificar (evita instancia sin contrato cargado)
        formato = FormatoAceptacion.objects.select_related("contrato", "contrato__cliente").get(
            pk=formato.pk
        )
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
    formato = get_object_or_404(FormatoAceptacion, pk=pk)
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
def contrato_estado_cuenta(request: HttpRequest, pk: int) -> HttpResponse:
    base = Contrato.objects.select_related("cliente", "inmueble", "inmueble__proyecto")
    contrato = get_object_or_404(
        filtrar_contratos_queryset_por_vendedor(base, request.user),
        pk=pk,
    )
    pagos = contrato.pagos.all().order_by("-fecha", "-id")
    cuotas_qs = (
        contrato.cuotas_programadas.select_related("pago").order_by("numero")
    )
    hoy = timezone.localdate()
    filas_cuotas: list[dict] = []
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
        filas_cuotas.append(
            {
                "cuota": c,
                "fecha_pago": fecha_pago,
                "dias_tarde_al_pagar": dias_tarde_al_pagar,
                "dias_impago_tras_venc": dias_impago_tras_venc,
                "pago_monto": pago_monto,
                "pago_referencia": pago_referencia,
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

    total_pagado = pagos.aggregate(t=Sum("monto"))["t"] or Decimal("0")
    saldo_estimado = contrato.precio_final - total_pagado
    context = {
        "contrato": contrato,
        "pagos": pagos,
        "filas_cuotas": filas_cuotas,
        "cuotas_resumen": cuotas_resumen,
        "hoy": hoy,
        "total_pagado": total_pagado,
        "saldo_estimado": saldo_estimado,
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
        qs = Pago.objects.select_related("contrato", "contrato__cliente")
        qs = filtrar_pagos_queryset_por_vendedor(qs, self.request.user)
        cid = (self.request.GET.get("contrato") or "").strip()
        if cid.isdigit():
            qs = qs.filter(contrato_id=int(cid))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cid = (self.request.GET.get("contrato") or "").strip()
        ctx["contrato_filtro"] = None
        if cid.isdigit():
            ctx["contrato_filtro"] = Contrato.objects.filter(pk=int(cid)).first()
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
        return kw

    def get_initial(self):
        initial = super().get_initial()
        fid = (self.request.GET.get("formato") or "").strip()
        if fid.isdigit():
            initial["formato_aceptacion"] = int(fid)
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo pago"
        ctx["cancel_url"] = reverse_lazy("app:pago_list")
        ctx["pago_contrato_panel"] = True
        ctx["pago_cuotas_checkboxes"] = True
        ctx["pago_ocultar_contrato"] = True
        ctx["pago_panel_debajo_formato"] = True
        return ctx

    def form_valid(self, form):
        messages.success(
            self.request,
            "Pago registrado. El recibo de ingreso se genera automáticamente al guardar; el envío por correo y WhatsApp "
            "depende de la configuración del servidor (correo SMTP y proveedor de mensajería en variables de entorno).",
        )
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
        return ctx


# ——— Parámetros mora ———
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
        ctx["form_title"] = "Nuevo parámetro de mora"
        ctx["cancel_url"] = reverse_lazy("app:parametro_mora_list")
        return ctx


class ParametroMoraUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = ParametroMora
    form_class = forms.ParametroMoraForm
    template_name = "app/parametro_mora_form.html"
    success_url = reverse_lazy("app:parametro_mora_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar parámetro de mora"
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
    success_url = reverse_lazy("app:inmueble_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar inmueble"
        ctx["delete_blurb"] = "No se puede eliminar si hay contratos u otros registros enlazados a este lote o bien."
        return ctx


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
        ctx["delete_title"] = "Eliminar parámetro de mora"
        ctx["delete_blurb"] = "Quita esta configuración del sistema."
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
        bloques.append(dl_row("Vendedor", vendedor_txt))
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
    if inmueble.frente_m is not None:
        bloques.append(dl_row("Frente (m)", str(inmueble.frente_m)))
    if inmueble.fondo_m is not None:
        bloques.append(dl_row("Fondo (m)", str(inmueble.fondo_m)))
    if inmueble.latitud is not None and inmueble.longitud is not None:
        bloques.append(
            dl_row(
                "Coord. punto (WGS84)",
                f"{inmueble.latitud}, {inmueble.longitud}",
            )
        )
    if inmueble.topografia:
        bloques.append(dl_row("Topografía", _truncate_txt(inmueble.topografia, 120)))
    if inmueble.servicios_basicos:
        bloques.append(
            dl_row("Servicios", _truncate_txt(inmueble.servicios_basicos, 160))
        )
    if inmueble.notas:
        bloques.append(dl_row("Notas", _truncate_txt(inmueble.notas)))
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
