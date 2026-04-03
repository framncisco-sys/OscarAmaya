"""Vistas web minimalistas (azul / blanco / gris) — gestión sin depender del admin."""

import csv
import json
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.forms import ValidationError
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from usuarios.roles import puede_gestionar_vendedores

from core.sensitive_access import (
    SensitiveDeleteMixin,
    SensitiveEditMixin,
    SensitiveEditSessionMixin,
    check_sensitive_write,
    grant,
    safe_next_url,
    skips_sensitive_reauth,
)

from . import forms_web as forms
from .cuotas_calendario import construir_cuotas_programadas, monto_uniforme_por_cuota
from docs.services import generar_pdf_desde_plantilla

from .models import (
    Cliente,
    ClienteDocumento,
    Contrato,
    CuotaProgramada,
    Inmueble,
    Pago,
    ParametroMora,
    Poligono,
    Proyecto,
    Vendedor,
)


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
    queryset = Contrato.objects.select_related(
        "cliente", "inmueble", "inmueble__proyecto", "vendedor", "vendedor_perfil"
    )


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
    queryset = Contrato.objects.select_related(
        "inmueble",
        "inmueble__proyecto",
        "inmueble__poligono",
        "vendedor_perfil",
        "vendedor",
        "cliente",
    )

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
            if getattr(self.object, "fecha_firma", None):
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


@login_required
def contrato_estado_cuenta(request: HttpRequest, pk: int) -> HttpResponse:
    contrato = get_object_or_404(
        Contrato.objects.select_related("cliente", "inmueble", "inmueble__proyecto"),
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
def export_pagos_csv(_request: HttpRequest) -> HttpResponse:
    rows = (
        Pago.objects.select_related("contrato", "contrato__cliente")
        .order_by("-fecha", "-id")
        .iterator(chunk_size=500)
    )
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
    queryset = Pago.objects.select_related("contrato", "contrato__cliente")

    def get_queryset(self):
        qs = super().get_queryset()
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
    template_name = "app/object_form.html"
    success_url = reverse_lazy("app:pago_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo pago"
        ctx["cancel_url"] = reverse_lazy("app:pago_list")
        ctx["pago_contrato_panel"] = True
        return ctx


class PagoUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = Pago
    form_class = forms.PagoForm
    template_name = "app/object_form.html"
    success_url = reverse_lazy("app:pago_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Editar pago"
        ctx["cancel_url"] = reverse_lazy("app:pago_list")
        ctx["pago_contrato_panel"] = True
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
    template_name = "app/object_form.html"
    success_url = reverse_lazy("app:parametro_mora_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Nuevo parámetro de mora"
        ctx["cancel_url"] = reverse_lazy("app:parametro_mora_list")
        return ctx


class ParametroMoraUpdateView(AppLoginRequiredMixin, SensitiveEditMixin, UpdateView):
    model = ParametroMora
    form_class = forms.ParametroMoraForm
    template_name = "app/object_form.html"
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

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["delete_title"] = "Eliminar contrato"
        ctx["delete_blurb"] = "Elimina el contrato y datos vinculados permitidos. Si hay pagos u otras restricciones, fallará."
        return ctx


class PagoDeleteView(AppLoginRequiredMixin, SensitiveDeleteMixin, DeleteView):
    model = Pago
    template_name = "app/confirm_delete.html"
    success_url = reverse_lazy("app:pago_list")

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
        Inmueble.objects.select_related("poligono")
        .filter(proyecto_id=proyecto_id, tipo=Inmueble.Tipo.LOTE)
        .order_by("poligono__orden", "codigo")
    )
    poligono_id = request.GET.get("poligono_id")
    if poligono_id:
        lotes = lotes.filter(poligono_id=poligono_id)

    features = []
    for lote in lotes:
        if lote.geometria_json:
            features.append(
                {
                    "type": "Feature",
                    "id": lote.pk,
                    "properties": {
                        "inmueble_id": lote.pk,
                        "codigo": lote.codigo,
                        "estado": lote.estado,
                        "poligono_id": lote.poligono_id,
                        "poligono_nombre": lote.poligono.nombre if lote.poligono else "",
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
