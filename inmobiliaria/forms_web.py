"""Formularios para la interfaz web (sin admin)."""

import binascii
import json
import re
from datetime import date
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Count, Prefetch, Q
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.urls import reverse

from .validators import validar_dui_sv, validar_nit_sv

from .models import (
    Cliente,
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

M2_POR_V2 = Decimal("0.698896")  # 1 v² ≈ 0.698896 m² (vara salvadoreña ~0.835905 m)

# IVA estimado en formulario web (referencia; asesoría contable puede variar).
IVA_TASA_SOBRE_PRECIO = Decimal("0.13")


def _cuota_mensual_estimada(
    precio_final: Decimal | None,
    plan_anos: int | None,
    tasa_anual_pct: Decimal | None,
    modalidad: str,
) -> Decimal | None:
    """Cuota nivelada aproximada (PMT); None si es contado o faltan datos."""
    if precio_final is None:
        return None
    if modalidad == Contrato.ModalidadFinanciamiento.SIN_FINANCIAMIENTO:
        return None
    if not plan_anos:
        return None
    n = int(plan_anos) * 12
    if n <= 0:
        return None
    tasa = tasa_anual_pct if tasa_anual_pct is not None else Decimal("0")
    r = (tasa / Decimal("100")) / Decimal("12")
    precio = precio_final
    if r == 0:
        return (precio / Decimal(n)).quantize(Decimal("0.01"))
    rf = float(r)
    nf = int(n)
    pf = float(precio)
    factor = (1 + rf) ** nf
    cuota = pf * rf * factor / (factor - 1)
    return Decimal(str(round(cuota, 2))).quantize(Decimal("0.01"))


def _iva_desde_precio(precio_final: Decimal | None) -> Decimal | None:
    if precio_final is None:
        return None
    return (precio_final * IVA_TASA_SOBRE_PRECIO).quantize(Decimal("0.01"))


def _comision_monto_desde_porcentaje(
    precio_final: Decimal | None, comision_porcentaje: Decimal | None
) -> Decimal | None:
    if precio_final is None or comision_porcentaje is None:
        return None
    return (precio_final * comision_porcentaje / Decimal("100")).quantize(Decimal("0.01"))


def _montos_calculados_contrato(data: dict) -> None:
    """Actualiza data in-place con cuota, IVA y comisión en monto."""
    pf = data.get("precio_final")
    modalidad = data.get("modalidad_financiamiento") or ""
    data["desglose_iva_monto"] = _iva_desde_precio(pf)
    data["comision_monto"] = _comision_monto_desde_porcentaje(pf, data.get("comision_porcentaje"))
    data["cuota_mensual_estimada"] = _cuota_mensual_estimada(
        pf, data.get("plan_anos"), data.get("tasa_interes_anual"), modalidad
    )


class ProyectoForm(forms.ModelForm):
    class Meta:
        model = Proyecto
        fields = "__all__"
        widgets = {
            "plano_maestro": forms.ClearableFileInput(
                attrs={"accept": ".pdf,.png,.jpg,.jpeg,.webp,image/*"}
            ),
        }


class PoligonoForm(forms.ModelForm):
    class Meta:
        model = Poligono
        fields = [
            "proyecto",
            "nombre",
            "orden",
            "plano",
            "recorte_izq_pct",
            "recorte_sup_pct",
            "recorte_ancho_pct",
            "recorte_alto_pct",
        ]
        widgets = {
            "plano": forms.ClearableFileInput(
                attrs={"accept": ".pdf,.png,.jpg,.jpeg,.webp,image/*"}
            ),
            "recorte_izq_pct": forms.NumberInput(
                attrs={"step": "0.1", "min": "0", "max": "100", "placeholder": "ej. 5"}
            ),
            "recorte_sup_pct": forms.NumberInput(
                attrs={"step": "0.1", "min": "0", "max": "100", "placeholder": "ej. 10"}
            ),
            "recorte_ancho_pct": forms.NumberInput(
                attrs={"step": "0.1", "min": "0", "max": "100", "placeholder": "ej. 35"}
            ),
            "recorte_alto_pct": forms.NumberInput(
                attrs={"step": "0.1", "min": "0", "max": "100", "placeholder": "ej. 40"}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        l = cleaned.get("recorte_izq_pct")
        t = cleaned.get("recorte_sup_pct")
        w = cleaned.get("recorte_ancho_pct")
        h = cleaned.get("recorte_alto_pct")
        has_any = any(x is not None for x in (l, t, w, h))
        has_all = all(x is not None for x in (l, t, w, h))
        if has_any and not has_all:
            raise forms.ValidationError(
                "Si usa recorte de vista en el plano, complete los cuatro porcentajes (izquierda, arriba, ancho, alto)."
            )
        if has_all:
            lf, tf, wf, hf = float(l), float(t), float(w), float(h)
            if lf < 0 or tf < 0 or wf <= 0 or hf <= 0:
                raise forms.ValidationError("Los porcentajes de recorte deben ser positivos y el ancho/alto mayor que cero.")
            if lf + wf > 100 or tf + hf > 100:
                raise forms.ValidationError(
                    "El recorte sale de la imagen: izquierda + ancho y arriba + alto no pueden pasar de 100%."
                )
        return cleaned


class InmuebleForm(forms.ModelForm):
    class Meta:
        model = Inmueble
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        m2 = cleaned.get("area_m2")
        v2 = cleaned.get("area_varas_cuadradas")
        if m2 and not v2:
            cleaned["area_varas_cuadradas"] = (m2 / M2_POR_V2).quantize(Decimal("0.0001"))
        elif v2 and not m2:
            cleaned["area_m2"] = (v2 * M2_POR_V2).quantize(Decimal("0.0001"))

        estado = cleaned.get("estado")
        if estado == Inmueble.Estado.RESERVADO:
            if not cleaned.get("reserva_hasta"):
                self.add_error("reserva_hasta", "Indique la fecha límite de la reserva.")
        else:
            cleaned["reserva_hasta"] = None
            cleaned["cliente_reserva"] = None
        return cleaned


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = "__all__"


class VendedorForm(forms.ModelForm):
    class Meta:
        model = Vendedor
        fields = [
            "nombres",
            "apellidos",
            "dui",
            "telefono",
            "email",
            "porcentaje_comision_default",
            "usuario_vinculo",
            "activo",
            "notas",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.fields["usuario_vinculo"].queryset = User.objects.filter(is_active=True).order_by(
            "username"
        )
        self.fields["usuario_vinculo"].required = False
        self.fields["porcentaje_comision_default"].widget.attrs.setdefault("step", "0.01")
        self.fields["porcentaje_comision_default"].widget.attrs.setdefault("min", "0")
        self.fields["porcentaje_comision_default"].widget.attrs.setdefault("max", "100")


class InmuebleSelect(forms.Select):
    """Select de inmueble con data-proyecto-id / data-poligono-id para filtrar en el navegador."""

    def __init__(self, *args, catalog=None, **kwargs):
        self.catalog = catalog or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value not in (None, ""):
            key = str(value)
            c = self.catalog.get(key, {})
            option.setdefault("attrs", {})
            # Siempre data-* para que el filtro JS no oculte todo si falta una clave.
            option["attrs"]["data-proyecto-id"] = c.get("proyecto_id", "")
            option["attrs"]["data-poligono-id"] = c.get("poligono_id", "")
            if "precio_lista" in c:
                option["attrs"]["data-precio-lista"] = c["precio_lista"]
        return option


class ContratoPagoSelect(forms.Select):
    """Select de contrato con datos para panel de referencia (cuota mensual, próxima cuota)."""

    def __init__(self, *args, catalog=None, **kwargs):
        self.catalog = catalog or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value not in (None, ""):
            key = str(value)
            c = self.catalog.get(key, {})
            option.setdefault("attrs", {})
            option["attrs"]["data-cuota-mensual"] = c.get("cuota_mensual", "")
            option["attrs"]["data-cuota-mensual-fuente"] = c.get(
                "cuota_mensual_fuente", ""
            )
            option["attrs"]["data-prox-vence"] = c.get("prox_vence", "")
            option["attrs"]["data-prox-monto"] = c.get("prox_monto", "")
            option["attrs"]["data-prox-numero"] = c.get("prox_numero", "")
            option["attrs"]["data-cliente"] = c.get("cliente", "")
            option["attrs"]["data-contrato-numero"] = c.get("contrato_numero", "")
            option["attrs"]["data-n-cuotas-total"] = c.get("n_cuotas_total", "0")
            option["attrs"]["data-n-cuotas-pagadas"] = c.get("n_cuotas_pagadas", "0")
            option["attrs"]["data-pendientes-json"] = c.get("pendientes_json", "[]")
            option["attrs"]["data-formato-id"] = c.get("formato_id", "")
            option["attrs"]["data-formato-numero"] = c.get("formato_numero_formulario", "")
            option["attrs"]["data-formato-edit-url"] = c.get("formato_edit_url", "")
            option["attrs"]["data-formato-nombre"] = c.get("formato_nombre_cliente", "")
            option["attrs"]["data-formato-letra-mensual"] = c.get("formato_letra_mensual", "")
            option["attrs"]["data-formato-plazo"] = c.get("formato_plazo_txt", "")
            option["attrs"]["data-formato-num-cuotas"] = c.get("formato_num_cuota_txt", "")
            option["attrs"]["data-formato-interes"] = c.get("formato_interes_txt", "")
            option["attrs"]["data-cuotas-todas-json"] = c.get("cuotas_todas_json", "[]")
        return option


class FormatoPagoSelect(forms.Select):
    """Select de formato de aceptación con data-contrato-id para sincronizar el contrato."""

    def __init__(self, *args, catalog=None, **kwargs):
        self.catalog = catalog or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value not in (None, ""):
            key = str(value)
            c = self.catalog.get(key, {})
            option.setdefault("attrs", {})
            option["attrs"]["data-contrato-id"] = c.get("contrato_id", "")
        return option


class ContratoForm(forms.ModelForm):
    class Meta:
        model = Contrato
        fields = [
            "cliente",
            "inmueble",
            "numero",
            "fecha_firma",
            "estado",
            "etapa_comercial",
            "precio_lista_referencia",
            "descuento_efectivo_monto",
            "precio_final",
            "desglose_iva_monto",
            "plan_anos",
            "modalidad_financiamiento",
            "meses_sin_interes",
            "tasa_interes_anual",
            "cuota_mensual_estimada",
            "vendedor_perfil",
            "vendedor_nombre",
            "comision_porcentaje",
            "comision_monto",
            "notas",
        ]

    def __init__(self, *args, **kwargs):
        self.filtro_proyecto_id = kwargs.pop("filtro_proyecto_id", None)
        self.filtro_poligono_id = kwargs.pop("filtro_poligono_id", None)
        super().__init__(*args, **kwargs)
        self.fields["vendedor_perfil"].queryset = Vendedor.objects.filter(activo=True).order_by(
            "apellidos", "nombres"
        )
        self.fields["vendedor_perfil"].required = False
        self.fields["vendedor_perfil"].label = "Vendedor"
        self.fields["vendedor_nombre"].help_text = (
            "Opcional si elige vendedor del catálogo; use este campo para un nombre libre en documentos."
        )

        qs = Inmueble.objects.select_related("proyecto", "poligono").order_by(
            "proyecto__nombre", "poligono__orden", "poligono__nombre", "codigo"
        )
        contrato = getattr(self, "instance", None)
        # Nuevo contrato: todos los inmuebles no vendidos (cualquier tipo). Edición: incluir el lote ya vinculado aunque esté vendido.
        if contrato and contrato.pk and getattr(contrato, "inmueble_id", None):
            qs = qs.filter(
                Q(pk=contrato.inmueble_id) | ~Q(estado=Inmueble.Estado.VENDIDO)
            )
        else:
            qs = qs.exclude(estado=Inmueble.Estado.VENDIDO)

        if self.filtro_proyecto_id:
            try:
                qs = qs.filter(proyecto_id=int(self.filtro_proyecto_id))
            except (ValueError, TypeError):
                pass
        if self.filtro_poligono_id:
            try:
                pid = int(self.filtro_poligono_id)
                proyecto_pol = (
                    Poligono.objects.filter(pk=pid).values_list("proyecto_id", flat=True).first()
                )
                if proyecto_pol is not None:
                    fp = None
                    if self.filtro_proyecto_id:
                        try:
                            fp = int(self.filtro_proyecto_id)
                        except (ValueError, TypeError):
                            fp = None
                    # Polígono y proyecto en GET incoherentes: solo coincidencia estricta por polígono.
                    if fp is not None and fp != proyecto_pol:
                        qs = qs.filter(poligono_id=pid)
                    elif fp is not None:
                        # Mismo proyecto: lotes del polígono + lotes del proyecto aún sin polígono (evita lista vacía).
                        qs = qs.filter(Q(poligono_id=pid) | Q(poligono__isnull=True))
                    else:
                        qs = qs.filter(
                            Q(poligono_id=pid)
                            | Q(poligono__isnull=True, proyecto_id=proyecto_pol)
                        )
            except (ValueError, TypeError):
                pass

        # Edición: el lote ya vinculado debe seguir en la lista aunque el GET filtre otro proyecto/polígono.
        if contrato and contrato.pk and getattr(contrato, "inmueble_id", None):
            inv_id = contrato.inmueble_id
            if not qs.filter(pk=inv_id).exists():
                qs = (
                    Inmueble.objects.filter(Q(pk__in=qs) | Q(pk=inv_id))
                    .select_related("proyecto", "poligono")
                    .order_by("proyecto__nombre", "poligono__orden", "poligono__nombre", "codigo")
                )

        catalog = {}
        for inv in qs:
            catalog[str(inv.pk)] = {
                "proyecto_id": str(inv.proyecto_id),
                "poligono_id": str(inv.poligono_id) if inv.poligono_id else "",
                "precio_lista": str(inv.precio_lista),
            }

        inv_field = self.fields["inmueble"]
        inv_field.queryset = qs
        inv_field.widget = InmuebleSelect(catalog=catalog)
        # Sustituir el widget deja choices vacías en el nuevo Select; hay que copiarlas desde el campo.
        inv_field.widget.choices = inv_field.choices
        inv_field.label = "Lote a escoger"
        inv_field.empty_label = "Seleccione un lote"
        self.fields["inmueble"].help_text = (
            "Arriba filtre por proyecto/polígono y pulse «Aplicar filtro» (recarga la página). "
            "Si hay lotes sin polígono asignado en ese proyecto, también se listan al filtrar por un polígono del mismo proyecto. "
            "Solo inmuebles no vendidos (salvo al editar un contrato ya vinculado)."
        )
        self.fields["inmueble"].label_from_instance = lambda obj: obj.label_venta

        for fname in ("precio_lista_referencia", "descuento_efectivo_monto", "precio_final"):
            if fname in self.fields:
                self.fields[fname].widget.attrs.setdefault("step", "0.01")
                self.fields[fname].widget.attrs.setdefault("min", "0")

        if "meses_sin_interes" in self.fields:
            self.fields["meses_sin_interes"].widget.attrs.setdefault("min", "0")
            self.fields["meses_sin_interes"].widget.attrs.setdefault("max", "120")
            self.fields["meses_sin_interes"].required = False

        if "modalidad_financiamiento" in self.fields:
            self.fields["modalidad_financiamiento"].help_text = (
                "Según la negociación: tasa acordada, período sin intereses, contado u otra condición (amplíe en notas)."
            )

        ff = self.fields.get("fecha_firma")
        if ff:
            wattrs = {**ff.widget.attrs, "type": "date"}
            ff.widget = forms.DateInput(attrs=wattrs, format="%Y-%m-%d")
            ff.input_formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]

        for fname, label, htxt in (
            (
                "cuota_mensual_estimada",
                "Cuota mensual estimada",
                "Calculada con precio final, plazo (años) y tasa anual; no aplica en «Sin financiamiento».",
            ),
            (
                "desglose_iva_monto",
                "IVA estimado",
                f"IVA al {IVA_TASA_SOBRE_PRECIO * 100:.0f} % sobre el precio final (solo lectura).",
            ),
            (
                "comision_monto",
                "Comisión (monto)",
                "Calculada con el precio final y el porcentaje de comisión (solo lectura).",
            ),
        ):
            if fname not in self.fields:
                continue
            f = self.fields[fname]
            f.required = False
            f.label = label
            f.help_text = htxt
            prev = dict(f.widget.attrs)
            attrs = {
                **prev,
                "readonly": True,
                "step": "0.01",
                "class": f"{prev.get('class', '')} input-calculado".strip(),
            }
            f.widget = forms.NumberInput(attrs=attrs)

        if not self.is_bound and getattr(self.instance, "pk", None):
            sync = {
                "precio_final": self.instance.precio_final,
                "plan_anos": self.instance.plan_anos,
                "tasa_interes_anual": self.instance.tasa_interes_anual,
                "modalidad_financiamiento": self.instance.modalidad_financiamiento,
                "comision_porcentaje": self.instance.comision_porcentaje,
            }
            _montos_calculados_contrato(sync)
            for k in ("cuota_mensual_estimada", "desglose_iva_monto", "comision_monto"):
                self.fields[k].initial = sync.get(k)

    def clean(self):
        cleaned_data = super().clean()
        vp = cleaned_data.get("vendedor_perfil")
        pct = cleaned_data.get("comision_porcentaje")
        if vp is not None and pct in (None, ""):
            cleaned_data["comision_porcentaje"] = vp.porcentaje_comision_default
        _montos_calculados_contrato(cleaned_data)
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.vendedor_perfil_id:
            vp = instance.vendedor_perfil
            if not (instance.vendedor_nombre or "").strip():
                instance.vendedor_nombre = vp.nombre_completo[:120]
            instance.vendedor_id = vp.usuario_vinculo_id
        else:
            instance.vendedor_id = None
        if commit:
            instance.save()
        return instance

    class Media:
        js = ("js/contrato_precio_referencia.js", "js/contrato_calculos.js")


class MontoDecimalFormField(forms.DecimalField):
    """Acepta coma como separador decimal (p. ej. 333,82) además del punto."""

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, str):
            value = value.strip().replace(" ", "").replace(",", ".")
        return super().to_python(value)


class PagoForm(forms.ModelForm):
    cuotas_seleccionadas = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Pago
        fields = [
            "formato_aceptacion",
            "contrato",
            "concepto",
            "fecha",
            "monto",
            "referencia",
            "notas",
            "cuotas_incluidas",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        ci = self.fields.get("cuotas_incluidas")
        if ci:
            ci.widget = forms.HiddenInput()
            ci.show_hidden_initial = False

        ff = self.fields.get("fecha")
        if ff:
            ff.label = "Fecha del pago"
            wattrs = {**ff.widget.attrs, "type": "date"}
            ff.widget = forms.DateInput(attrs=wattrs, format="%Y-%m-%d")
            ff.input_formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]
            ff.help_text = (
                "Día en que usted recibe o registra este dinero (ingreso real en el sistema). "
                "El vencimiento de cada cuota está en las cuotas programadas del contrato; "
                "para aplicar mora se razona comparando ese vencimiento con la fecha efectiva de pago "
                "y los parámetros de mora configurados. No es la fecha de vencimiento de la cuota."
            )

        m = self.fields.get("monto")
        if m:
            m.label = "Monto total del pago"
            m.help_text = (
                "Un solo número con el importe completo de este ingreso: incluye todo lo que corresponda "
                "a este movimiento según el concepto (prima, cuota, mantenimiento, mora u otro), sin dividir en varias líneas. "
                "Puede usar coma o punto como decimal (ej. 333,82 o 333.82)."
            )
            self.fields["monto"] = MontoDecimalFormField(
                label=m.label,
                help_text=m.help_text,
                max_digits=14,
                decimal_places=2,
                min_value=Decimal("0.01"),
                required=m.required,
                widget=forms.TextInput(
                    attrs={
                        **getattr(m.widget, "attrs", {}),
                        "inputmode": "decimal",
                        "placeholder": "0,00",
                        "autocomplete": "off",
                        "class": (getattr(m.widget, "attrs", {}).get("class", "") + " input-monto-pago").strip(),
                    }
                ),
            )

        c = self.fields.get("concepto")
        if c:
            c.help_text = "Tipo de ingreso; el monto de arriba debe ser el total de esta operación."

        r = self.fields.get("referencia")
        if r:
            r.help_text = "Opcional: número de transferencia, depósito, cheque u otra referencia bancaria."

        fa = self.fields.get("formato_aceptacion")
        if fa:
            fa.required = False
            fa.label = "Formato de aceptación guardado"
            fa.help_text = (
                "Recomendado: elija el formato guardado y se enlazará el contrato correspondiente. "
                "Los datos de referencia (cliente, letra, plazo) salen del formato; las cuotas a pagar se marcan en la tabla del calendario."
            )
            fmt_qs = (
                FormatoAceptacion.objects.filter(contrato__isnull=False)
                .select_related("contrato", "contrato__cliente")
                .order_by("-numero_formulario", "-id")
            )
            fa.queryset = fmt_qs
            formato_catalog = {str(f.pk): {"contrato_id": str(f.contrato_id)} for f in fmt_qs}
            fa.widget = FormatoPagoSelect(catalog=formato_catalog)
            fa.widget.choices = fa.choices

        ct = self.fields.get("contrato")
        if ct:
            ct.label = "Contrato"
            ct.help_text = (
                "Se puede elegir directamente o derivarse del formato de aceptación. "
                "Al guardar como «Cuota de financiamiento», el sistema liquida las cuotas marcadas en el calendario (orden de vencimiento)."
            )
            ct.queryset = Contrato.objects.select_related("cliente", "inmueble").order_by(
                "-fecha_firma", "numero"
            )
            pks = list(ct.queryset.values_list("pk", flat=True))
            catalog: dict[str, dict[str, str]] = {}
            if pks:
                stats_rows = (
                    CuotaProgramada.objects.filter(contrato_id__in=pks)
                    .values("contrato_id")
                    .annotate(
                        total=Count("id"),
                        pagadas=Count(
                            "id",
                            filter=Q(estado=CuotaProgramada.Estado.PAGADA),
                        ),
                    )
                )
                stats_by_ct = {str(r["contrato_id"]): r for r in stats_rows}
                formato_por_contrato = {
                    f.contrato_id: f
                    for f in FormatoAceptacion.objects.filter(contrato_id__in=pks)
                }
                pref = Prefetch(
                    "cuotas_programadas",
                    queryset=CuotaProgramada.objects.filter(
                        estado__in=[
                            CuotaProgramada.Estado.PENDIENTE,
                            CuotaProgramada.Estado.VENCIDA,
                        ],
                        pago__isnull=True,
                    ).order_by("vence_en", "numero", "id"),
                    to_attr="_cuotas_abiertas_pref",
                )
                pref_all = Prefetch(
                    "cuotas_programadas",
                    queryset=CuotaProgramada.objects.order_by("numero", "id"),
                    to_attr="_todas_cuotas_pref",
                )
                for c in Contrato.objects.filter(pk__in=pks).prefetch_related(pref, pref_all):
                    todas = getattr(c, "_todas_cuotas_pref", [])
                    todas_payload = [
                        {
                            "id": x.id,
                            "n": x.numero,
                            "v": x.vence_en.isoformat(),
                            "m": str(x.monto.quantize(Decimal("0.01"))),
                            "e": x.estado,
                            "abierta": x.pago_id is None
                            and x.estado
                            in (
                                CuotaProgramada.Estado.PENDIENTE,
                                CuotaProgramada.Estado.VENCIDA,
                            ),
                        }
                        for x in todas
                    ]
                    cm = c.cuota_mensual_estimada
                    if cm is None:
                        cm = _cuota_mensual_estimada(
                            c.precio_final,
                            c.plan_anos,
                            c.tasa_interes_anual,
                            c.modalidad_financiamiento or "",
                        )
                    pend = getattr(c, "_cuotas_abiertas_pref", [])
                    first = pend[0] if pend else None
                    st = stats_by_ct.get(str(c.pk), {"total": 0, "pagadas": 0})
                    pendientes_payload = [
                        {
                            "n": x.numero,
                            "v": x.vence_en.isoformat(),
                            "m": str(x.monto.quantize(Decimal("0.01"))),
                        }
                        for x in pend
                    ]
                    fmt = formato_por_contrato.get(c.pk)
                    fmt_id = fmt_num = fmt_url = fmt_nom = fmt_letra = ""
                    fmt_plazo = fmt_nc = fmt_int = ""
                    if fmt is not None:
                        fmt_id = str(fmt.pk)
                        fmt_num = f"{fmt.numero_formulario:04d}"
                        fmt_url = reverse(
                            "app:formato_aceptacion_edit", kwargs={"pk": fmt.pk}
                        )
                        fmt_nom = (fmt.nombre_cliente or "").strip()
                        if fmt.letra_mensual is not None:
                            fmt_letra = str(fmt.letra_mensual.quantize(Decimal("0.01")))
                        fmt_plazo = (fmt.plazo_txt or "").strip()
                        fmt_nc = (fmt.num_cuota_txt or "").strip()
                        fmt_int = (fmt.interes_txt or "").strip()
                    cliente_display = str(c.cliente)
                    if fmt is not None and fmt_nom:
                        cliente_display = fmt_nom
                    cuota_ref = ""
                    cuota_fuente = ""
                    if fmt_letra:
                        cuota_ref = fmt_letra
                        cuota_fuente = "formato"
                    elif cm is not None:
                        cuota_ref = str(cm.quantize(Decimal("0.01")))
                        cuota_fuente = "contrato"
                    catalog[str(c.pk)] = {
                        "cliente": cliente_display,
                        "contrato_numero": c.numero,
                        "cuota_mensual": cuota_ref,
                        "cuota_mensual_fuente": cuota_fuente,
                        "prox_vence": first.vence_en.isoformat() if first else "",
                        "prox_monto": ""
                        if not first
                        else f"{first.monto.quantize(Decimal('0.01'))}",
                        "prox_numero": "" if not first else str(first.numero),
                        "n_cuotas_total": str(st["total"]),
                        "n_cuotas_pagadas": str(st["pagadas"]),
                        "pendientes_json": json.dumps(
                            pendientes_payload, separators=(",", ":")
                        ),
                        "formato_id": fmt_id,
                        "formato_numero_formulario": fmt_num,
                        "formato_edit_url": fmt_url,
                        "formato_nombre_cliente": fmt_nom,
                        "formato_letra_mensual": fmt_letra,
                        "formato_plazo_txt": fmt_plazo,
                        "formato_num_cuota_txt": fmt_nc,
                        "formato_interes_txt": fmt_int,
                        "cuotas_todas_json": json.dumps(
                            todas_payload, separators=(",", ":")
                        ),
                    }
            ct.widget = ContratoPagoSelect(catalog=catalog)
            ct.widget.choices = ct.choices

        if not self.is_bound and not getattr(self.instance, "pk", None):
            if not self.initial.get("fecha"):
                self.fields["fecha"].initial = date.today()

    def clean(self):
        cleaned_data = super().clean()
        formato = cleaned_data.get("formato_aceptacion")
        if formato and formato.contrato_id:
            cleaned_data["contrato"] = formato.contrato

        concepto = cleaned_data.get("concepto")
        contrato = cleaned_data.get("contrato")

        if concepto != Pago.Concepto.CUOTA:
            cleaned_data["cuotas_incluidas"] = 1
            cleaned_data["cuotas_seleccionadas"] = ""
            return cleaned_data

        n = max(1, min(int(cleaned_data.get("cuotas_incluidas") or 1), 200))
        cleaned_data["cuotas_incluidas"] = n

        if not contrato:
            return cleaned_data

        monto = cleaned_data.get("monto")
        monto_q = Decimal(monto).quantize(Decimal("0.01")) if monto is not None else None

        if getattr(self.instance, "pk", None):
            vinculadas = list(
                CuotaProgramada.objects.filter(pago_id=self.instance.pk).order_by(
                    "vence_en", "numero", "id"
                )
            )
            if vinculadas:
                esperado = sum((c.monto for c in vinculadas), Decimal("0")).quantize(
                    Decimal("0.01")
                )
                if monto_q is not None and monto_q != esperado:
                    nums = ", ".join(str(c.numero) for c in vinculadas)
                    raise ValidationError(
                        {
                            "monto": (
                                f"El monto debe ser ${esperado} (suma de las cuotas ya vinculadas a este pago: n.º {nums})."
                            )
                        }
                    )
                return cleaned_data

        pend_full = list(
            CuotaProgramada.objects.filter(
                contrato=contrato,
                estado__in=[
                    CuotaProgramada.Estado.PENDIENTE,
                    CuotaProgramada.Estado.VENCIDA,
                ],
                pago__isnull=True,
            ).order_by("vence_en", "numero", "id")
        )

        sel_raw = (cleaned_data.get("cuotas_seleccionadas") or "").strip()
        ids_pick: list[int] = []
        if sel_raw:
            for part in sel_raw.split(","):
                part = part.strip()
                if part.isdigit():
                    ids_pick.append(int(part))

        if not pend_full:
            raise ValidationError(
                {
                    "concepto": (
                        "Este contrato no tiene cuotas pendientes en el calendario; no puede registrar "
                        "«Cuota de financiamiento» hasta cargar el plan de cuotas en el contrato."
                    )
                }
            )

        if ids_pick:
            k = len(ids_pick)
            expected_ids = [p.pk for p in pend_full[:k]]
            if len(set(ids_pick)) != len(ids_pick) or set(ids_pick) != set(expected_ids):
                raise ValidationError(
                    {
                        "cuotas_seleccionadas": (
                            "Marque cuota(s) consecutiva(s) desde la primera pendiente del calendario, sin saltos."
                        )
                    }
                )
            cleaned_data["cuotas_incluidas"] = k
            n = k
        else:
            raise ValidationError(
                {
                    "cuotas_seleccionadas": (
                        "Indique qué cuota(s) liquida este pago usando las casillas del calendario (desde la primera pendiente)."
                    )
                }
            )

        pend = pend_full[:n]
        if len(pend) < n:
            raise ValidationError(
                {
                    "cuotas_seleccionadas": (
                        f"Solo hay {len(pend)} cuota(s) pendiente(s); no puede liquidar {n} en un solo pago."
                    )
                }
            )
        esperado = sum((c.monto for c in pend), Decimal("0")).quantize(Decimal("0.01"))
        if monto_q is not None and monto_q != esperado:
            raise ValidationError(
                {
                    "monto": (
                        f"Para {n} cuota(s) el monto debe ser exactamente ${esperado} "
                        f"(suma de las cuotas n.º {pend[0].numero} al {pend[-1].numero})."
                    )
                }
            )
        return cleaned_data

    class Media:
        js = ("js/pago_contrato_hint.js", "js/pago_formato_cuotas.js")


class GenerarCuotasCalendarioForm(forms.Form):
    """Parámetros para rellenar la tabla de cuotas de una sola vez."""

    fecha_primera = forms.DateField(
        label="Fecha de vencimiento de la 1.ª cuota",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"],
    )
    num_cuotas = forms.IntegerField(
        label="Cantidad de cuotas (meses)",
        min_value=1,
        max_value=600,
        help_text="Por defecto: años de financiamiento del contrato × 12 (si tiene plazo en años).",
    )
    monto_cuota = forms.DecimalField(
        label="Monto de cada cuota",
        required=False,
        min_value=Decimal("0.01"),
        max_digits=14,
        decimal_places=2,
        help_text="Opcional: si lo deja vacío, se usa la cuota mensual estimada del contrato; si tampoco hay, precio acordado ÷ cantidad de cuotas.",
    )


class CuotaProgramadaEntryForm(forms.ModelForm):
    """Fila del calendario de cuotas (edición en contrato)."""

    class Meta:
        model = CuotaProgramada
        fields = ["numero", "vence_en", "monto"]
        widgets = {
            "numero": forms.NumberInput(attrs={"min": 1, "step": 1}),
            "monto": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        v = self.fields.get("vence_en")
        if v:
            v.widget = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            v.input_formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]
        inst = self.instance
        if inst and inst.pk and inst.estado == CuotaProgramada.Estado.PAGADA:
            for fld in self.fields.values():
                fld.disabled = True


class BaseCuotaProgramadaFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.forms:
            cd = getattr(form, "cleaned_data", None)
            if not cd or not cd.get("DELETE"):
                continue
            inst = form.instance
            if inst.pk and inst.estado == CuotaProgramada.Estado.PAGADA:
                raise ValidationError(
                    "No puede eliminar una cuota que ya está pagada y vinculada a un pago."
                )


CuotaProgramadaFormSet = inlineformset_factory(
    Contrato,
    CuotaProgramada,
    form=CuotaProgramadaEntryForm,
    formset=BaseCuotaProgramadaFormSet,
    extra=2,
    can_delete=True,
    min_num=0,
)


class ParametroMoraForm(forms.ModelForm):
    class Meta:
        model = ParametroMora
        fields = "__all__"


_FORMATO_ACEPTACION_EXCLUDE = (
    "id",
    "contrato",
    "numero_formulario",
    "creado_por",
    "creado_en",
    "actualizado_en",
    "firma_aceptante",
    "firma_vendedor",
    "firma_autorizado",
)
_FORMATO_ACEPTACION_FIELDS = [
    f.name
    for f in FormatoAceptacion._meta.fields
    if f.name not in _FORMATO_ACEPTACION_EXCLUDE
]

_ANOS_PLAZO_CHOICES = [("", "— Años —")] + [(str(i), str(i)) for i in range(0, 51)]
_INTERES_PCT_CHOICES = [("", "— % —")] + [(str(i), f"{i} %") for i in range(0, 51)]


def _formato_plazo_guardado_a_anos_select(val) -> str:
    """Alinea valores viejos (meses o texto) al select 0–50 años."""
    if val is None or str(val).strip() == "":
        return ""
    s = str(val).strip()
    if s.isdigit():
        n = int(s)
        if 0 <= n <= 50:
            return str(n)
        if n > 50 and n % 12 == 0:
            y = n // 12
            if 0 <= y <= 50:
                return str(y)
        return ""
    m = re.search(r"(\d+)", s)
    if not m:
        return ""
    n = int(m.group(1))
    low = s.lower()
    if "mes" in low or (n > 50 and n % 12 == 0):
        y = n // 12
        if 0 <= y <= 50:
            return str(y)
    if 0 <= n <= 50:
        return str(n)
    return ""


def _formato_interes_guardado_a_select(val) -> str:
    if val is None or str(val).strip() == "":
        return ""
    s = str(val).strip()
    if s.isdigit():
        n = int(s)
        return str(n) if 0 <= n <= 50 else ""
    m = re.search(r"(\d+)", s)
    if not m:
        return ""
    n = int(m.group(1))
    return str(n) if 0 <= n <= 50 else ""


class FormatoAceptacionForm(forms.ModelForm):
    """Las firmas se capturan con lienzo (PNG en base64) vía campos ocultos *_canvas."""

    firma_aceptante_canvas = forms.CharField(required=False, widget=forms.HiddenInput)
    firma_vendedor_canvas = forms.CharField(required=False, widget=forms.HiddenInput)
    firma_autorizado_canvas = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = FormatoAceptacion
        fields = _FORMATO_ACEPTACION_FIELDS
        widgets = {
            "direccion_domicilio": forms.Textarea(attrs={"rows": 2}),
            "direccion_notificacion": forms.Textarea(attrs={"rows": 2}),
            "direccion_trabajo": forms.Textarea(attrs={"rows": 2}),
            "direccion_terreno": forms.Textarea(attrs={"rows": 2}),
            "dui_numero": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "00000000-0",
                    "maxlength": 10,
                    "inputmode": "numeric",
                    "autocomplete": "off",
                    "title": "DUI: 8 dígitos, guion, dígito de verificación",
                }
            ),
            "nit_numero": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "0000-000000-000-0",
                    "maxlength": 17,
                    "inputmode": "numeric",
                    "autocomplete": "off",
                    "title": "NIT: 14 dígitos con formato habitual en El Salvador",
                }
            ),
            "telefono_domicilio": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "0000-0000",
                    "maxlength": 9,
                    "inputmode": "numeric",
                    "autocomplete": "tel",
                }
            ),
            "telefono_notificacion": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "0000-0000",
                    "maxlength": 9,
                    "inputmode": "numeric",
                    "autocomplete": "tel",
                }
            ),
            "telefono_trabajo": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "0000-0000",
                    "maxlength": 9,
                    "inputmode": "numeric",
                    "autocomplete": "tel",
                }
            ),
            "ref_com_tel_1": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "0000-0000",
                    "maxlength": 9,
                    "inputmode": "numeric",
                    "autocomplete": "tel",
                }
            ),
            "ref_com_tel_2": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "0000-0000",
                    "maxlength": 9,
                    "inputmode": "numeric",
                    "autocomplete": "tel",
                }
            ),
            "ref_com_tel_3": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "0000-0000",
                    "maxlength": 9,
                    "inputmode": "numeric",
                    "autocomplete": "tel",
                }
            ),
            "ref_per_tel_1": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "0000-0000",
                    "maxlength": 9,
                    "inputmode": "numeric",
                    "autocomplete": "tel",
                }
            ),
            "ref_per_tel_2": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "0000-0000",
                    "maxlength": 9,
                    "inputmode": "numeric",
                    "autocomplete": "tel",
                }
            ),
            "ref_per_tel_3": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "0000-0000",
                    "maxlength": 9,
                    "inputmode": "numeric",
                    "autocomplete": "tel",
                }
            ),
            "ben_porcentaje_1": forms.NumberInput(
                attrs={
                    "class": "input",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                    "placeholder": "%",
                }
            ),
            "ben_porcentaje_2": forms.NumberInput(
                attrs={
                    "class": "input",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                    "placeholder": "%",
                }
            ),
            "num_lote": forms.HiddenInput(),
            "poligono_txt": forms.HiddenInput(),
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "dui_exp_fecha": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "fecha_primera_cuota": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "fecha_pago_mensual": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        dui_f = self.fields.get("dui_numero")
        if dui_f:
            dui_f.validators.append(validar_dui_sv)
        nit_f = self.fields.get("nit_numero")
        if nit_f:
            nit_f.validators.append(validar_nit_sv)
        for fname in (
            "fecha_nacimiento",
            "dui_exp_fecha",
            "fecha_primera_cuota",
            "fecha_pago_mensual",
        ):
            fd = self.fields.get(fname)
            if fd:
                fd.input_formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]

        plazo_f = self.fields.get("plazo_txt")
        if plazo_f:
            plazo_f.widget = forms.Select(
                choices=_ANOS_PLAZO_CHOICES,
                attrs={"class": "input"},
            )
            plazo_f.required = False

        inter_f = self.fields.get("interes_txt")
        if inter_f:
            inter_f.widget = forms.Select(
                choices=_INTERES_PCT_CHOICES,
                attrs={"class": "input"},
            )
            inter_f.required = False

        ncuota_f = self.fields.get("num_cuota_txt")
        if ncuota_f:
            ncuota_f.widget = forms.TextInput(
                attrs={
                    "readonly": True,
                    "class": "input",
                    "autocomplete": "off",
                },
            )
            ncuota_f.required = False

        if self.instance and getattr(self.instance, "pk", None):
            pa = _formato_plazo_guardado_a_anos_select(self.instance.plazo_txt)
            if pa != "":
                self.initial["plazo_txt"] = pa
            inn = _formato_interes_guardado_a_select(self.instance.interes_txt)
            if inn != "":
                self.initial["interes_txt"] = inn
            if pa != "":
                try:
                    y = int(pa)
                    self.initial["num_cuota_txt"] = str(y * 12)
                except ValueError:
                    pass

    def clean(self):
        cleaned = super().clean()
        plazo_raw = (cleaned.get("plazo_txt") or "").strip()
        if plazo_raw.isdigit():
            y = int(plazo_raw)
            if 0 <= y <= 50:
                cleaned["num_cuota_txt"] = str(y * 12)
        return cleaned

    def save(self, commit=True):
        import base64
        import uuid

        from django.core.files.base import ContentFile

        instance = super().save(commit=False)

        def _apply_firma_desde_canvas(attr: str, canvas_key: str) -> None:
            raw = (self.cleaned_data.get(canvas_key) or "").strip()
            if not raw:
                return
            if raw.startswith("data:image") and "," in raw:
                _, b64 = raw.split(",", 1)
            else:
                b64 = raw
            try:
                data = base64.b64decode(b64, validate=False)
            except (ValueError, TypeError, binascii.Error):
                return
            # PNG estándar desde canvas (toDataURL); evita basura o payloads vacíos.
            if len(data) < 8 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                return
            name = f"{attr}_{uuid.uuid4().hex[:12]}.png"
            getattr(instance, attr).save(name, ContentFile(data), save=False)

        _apply_firma_desde_canvas("firma_aceptante", "firma_aceptante_canvas")
        _apply_firma_desde_canvas("firma_vendedor", "firma_vendedor_canvas")
        _apply_firma_desde_canvas("firma_autorizado", "firma_autorizado_canvas")

        if commit:
            instance.save()
        return instance
