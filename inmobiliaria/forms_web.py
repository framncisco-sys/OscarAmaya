"""Formularios para la interfaz web (sin admin)."""

import binascii
import json
import re
from datetime import date
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db.models import Count, Prefetch, Q
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.urls import reverse

from .phone_sv import normalizar_guardado_telefono_sv
from .validators import validar_dui_sv, validar_nit_sv

from .formato_aceptacion_db import (
    FORMATO_CREDITO_EXTRA_FIELDS,
    formato_aceptacion_credito_extra_columns_ready,
)
from .models import (
    Cliente,
    Contrato,
    CuotaProgramada,
    FormatoAceptacion,
    Inmueble,
    InmuebleDetalleCasa,
    InmuebleDetalleCasaAlquiler,
    InmuebleDetalleLocalAlquiler,
    Pago,
    ParametroMora,
    Poligono,
    Proyecto,
    Vendedor,
)

M2_POR_V2 = Decimal("0.698896")  # 1 v² ≈ 0.698896 m² (vara salvadoreña ~0.835905 m)

# IVA estimado en formulario web (referencia; asesoría contable puede variar).
IVA_TASA_SOBRE_PRECIO = Decimal("0.13")


def contrato_desde_formato_aceptacion(f: FormatoAceptacion) -> Contrato | None:
    """
    Contrato explícito en el formato, o el más reciente del inmueble que coincida
    por código de lote + nombre de proyecto (formatos guardados sin FK a contrato).
    """
    if f.contrato_id:
        return f.contrato
    num_lote = (f.num_lote or "").strip()
    nom_proy = (f.nombre_proyecto or "").strip()
    if not num_lote or not nom_proy:
        return None
    inv_qs = (
        Inmueble.objects.filter(codigo__iexact=num_lote)
        .select_related("proyecto")
        .order_by("id")
    )
    inv = None
    nom_lower = nom_proy.lower()
    for candidate in inv_qs:
        pn = (candidate.proyecto.nombre or "").strip() if candidate.proyecto_id else ""
        if pn.lower() == nom_lower:
            inv = candidate
            break
    if inv is None and inv_qs.count() == 1:
        inv = inv_qs.first()
    if inv is None:
        return None
    return (
        Contrato.objects.filter(inmueble_id=inv.pk)
        .order_by("-fecha_firma", "-id")
        .select_related("cliente", "inmueble")
        .first()
    )


def _formato_sin_contrato_catalogo(f: FormatoAceptacion) -> dict[str, str]:
    """Panel mínimo cuando no hay contrato ni resolución por lote/proyecto."""
    fnom = (f.nombre_cliente or "").strip()
    fmt_num = f"{f.numero_formulario:04d}"
    fmt_url = reverse("app:formato_aceptacion_edit", kwargs={"pk": f.pk})
    fmt_letra = ""
    if f.letra_mensual is not None:
        fmt_letra = str(f.letra_mensual.quantize(Decimal("0.01")))
    lote_txt = (f.num_lote or "").strip()
    proy_txt = (f.nombre_proyecto or "").strip()
    ref_lote = " — ".join(x for x in (lote_txt, proy_txt) if x) or "—"
    return {
        "contrato_id": "",
        "cliente": fnom,
        "contrato_numero": ref_lote,
        "cuota_mensual": fmt_letra,
        "cuota_mensual_fuente": "formato" if fmt_letra else "",
        "prox_vence": "",
        "prox_monto": "",
        "prox_numero": "",
        "n_cuotas_total": "0",
        "n_cuotas_pagadas": "0",
        "pendientes_json": "[]",
        "formato_id": str(f.pk),
        "formato_numero_formulario": fmt_num,
        "formato_edit_url": fmt_url,
        "formato_nombre_cliente": fnom,
        "formato_letra_mensual": fmt_letra,
        "formato_plazo_txt": (f.plazo_txt or "").strip(),
        "formato_num_cuota_txt": (f.num_cuota_txt or "").strip(),
        "formato_interes_txt": (f.interes_txt or "").strip(),
        "cuotas_todas_json": "[]",
    }


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

    def __init__(self, *args, modo_tipo: str = "", **kwargs):
        """
        modo_tipo:
          - "" : edición / formulario completo (todos los tipos).
          - "lote_local" : alta solo lote o local comercial.
          - "casa" : alta solo casa nueva o segunda.
        """
        self.modo_tipo = modo_tipo or ""
        super().__init__(*args, **kwargs)
        tf = self.fields.get("tipo")
        if not tf:
            return
        if self.modo_tipo == "lote_local":
            tf.choices = [
                (Inmueble.Tipo.LOTE, Inmueble.Tipo.LOTE.label),
                (Inmueble.Tipo.LOCAL, Inmueble.Tipo.LOCAL.label),
            ]
            if self.instance.pk:
                pass
            elif "tipo" not in self.initial:
                tf.initial = Inmueble.Tipo.LOTE
        elif self.modo_tipo == "casa":
            tf.choices = [
                (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_NUEVA.label),
                (Inmueble.Tipo.CASA_SEGUNDA, Inmueble.Tipo.CASA_SEGUNDA.label),
            ]
            if not self.instance.pk and "tipo" not in self.initial:
                tf.initial = Inmueble.Tipo.CASA_NUEVA

    def clean(self):
        cleaned = super().clean()
        t = cleaned.get("tipo")
        if self.modo_tipo == "lote_local" and t not in (Inmueble.Tipo.LOTE, Inmueble.Tipo.LOCAL):
            self.add_error("tipo", "Seleccione lote o local comercial.")
        if self.modo_tipo == "casa" and t not in (
            Inmueble.Tipo.CASA_NUEVA,
            Inmueble.Tipo.CASA_SEGUNDA,
        ):
            self.add_error("tipo", "Seleccione casa nueva o casa de segunda.")
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


class InmuebleCasaAltaForm(InmuebleForm):
    """Alta de casa: inventario mínimo; tipo de construcción, distribución y documentos van en InmuebleDetalleCasa."""

    class Meta(InmuebleForm.Meta):
        fields = [
            "proyecto",
            "tipo",
            "codigo",
            "precio_lista",
            "en_alquiler",
        ]

    def __init__(self, *args, modo_tipo: str = "casa", **kwargs):
        super().__init__(*args, modo_tipo=modo_tipo, **kwargs)
        for _name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                continue
            if not isinstance(w, (forms.HiddenInput,)):
                w.attrs.setdefault("class", "input")
        pf = self.fields.get("precio_lista")
        if pf:
            pf.widget.attrs.setdefault("step", "0.01")
            pf.widget.attrs.setdefault("min", "0")


class InmuebleLocalAlquilerInventarioForm(forms.ModelForm):
    """Inventario del local en una sola pantalla con la ficha de alquiler (tipo = local, sin ir a otro formulario)."""

    class Meta:
        model = Inmueble
        fields = [
            "proyecto",
            "poligono",
            "estado",
            "codigo",
            "precio_lista",
            "en_alquiler",
            "area_m2",
            "area_varas_cuadradas",
            "notas",
            "cliente_reserva",
            "reserva_hasta",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                continue
            if not isinstance(w, (forms.HiddenInput,)):
                w.attrs.setdefault("class", "input")
        pf = self.fields.get("precio_lista")
        if pf:
            pf.widget.attrs.setdefault("step", "0.01")
            pf.widget.attrs.setdefault("min", "0")
        nt = self.fields.get("notas")
        if nt and isinstance(nt.widget, forms.Textarea):
            nt.widget.attrs.setdefault("rows", 3)
        if not self.instance.pk:
            self.fields["en_alquiler"].initial = True

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


class InmuebleCasaAlquilerInventarioForm(forms.ModelForm):
    """Inventario de la vivienda en alquiler en una sola pantalla con la ficha de arrendamiento."""

    class Meta:
        model = Inmueble
        fields = [
            "proyecto",
            "poligono",
            "estado",
            "tipo",
            "codigo",
            "precio_lista",
            "en_alquiler",
            "area_m2",
            "area_varas_cuadradas",
            "notas",
            "cliente_reserva",
            "reserva_hasta",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tf = self.fields.get("tipo")
        if tf:
            tf.choices = [
                (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_NUEVA.label),
                (Inmueble.Tipo.CASA_SEGUNDA, Inmueble.Tipo.CASA_SEGUNDA.label),
            ]
            if not self.instance.pk and "tipo" not in self.initial:
                tf.initial = Inmueble.Tipo.CASA_NUEVA
        for _name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                continue
            if not isinstance(w, (forms.HiddenInput,)):
                w.attrs.setdefault("class", "input")
        pf = self.fields.get("precio_lista")
        if pf:
            pf.widget.attrs.setdefault("step", "0.01")
            pf.widget.attrs.setdefault("min", "0")
        nt = self.fields.get("notas")
        if nt and isinstance(nt.widget, forms.Textarea):
            nt.widget.attrs.setdefault("rows", 3)
        if not self.instance.pk:
            self.fields["en_alquiler"].initial = True

    def clean(self):
        cleaned = super().clean()
        t = cleaned.get("tipo")
        if t not in (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA):
            self.add_error("tipo", "Seleccione casa nueva o casa de segunda.")
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


class InmuebleDetalleCasaForm(forms.ModelForm):
    """Ficha de venta de casa (nueva o segunda); se muestra solo si el tipo de inmueble es casa."""

    class Meta:
        model = InmuebleDetalleCasa
        exclude = ("inmueble",)
        widgets = {
            "direccion_exacta": forms.Textarea(attrs={"rows": 2, "class": "input"}),
            "garantia_construccion": forms.Textarea(attrs={"rows": 2, "class": "input"}),
            "extras_incluidos": forms.Textarea(attrs={"rows": 2, "class": "input"}),
            "conexiones_ac_calentador": forms.Textarea(attrs={"rows": 2, "class": "input"}),
            "aire_ac_ubicacion": forms.Textarea(attrs={"rows": 2, "class": "input"}),
            "muebles_incluidos": forms.Textarea(attrs={"rows": 2, "class": "input"}),
            "remodelaciones_recientes": forms.Textarea(attrs={"rows": 2, "class": "input"}),
            "gravamenes_hipoteca": forms.Textarea(attrs={"rows": 2, "class": "input"}),
            "direccion_dueno": forms.Textarea(attrs={"rows": 2, "class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                continue
            if isinstance(w, forms.ClearableFileInput):
                w.attrs.setdefault("class", "input")
            elif not isinstance(w, (forms.HiddenInput,)):
                w.attrs.setdefault("class", "input")
        ac = self.fields.get("aire_ac_cantidad")
        if ac:
            ac.widget.attrs.setdefault("min", "0")
            ac.widget.attrs.setdefault("placeholder", "ej. 3")
        td = self.fields.get("telefono_dueno")
        if td:
            td.widget.attrs.setdefault("maxlength", "40")
            td.widget.attrs.setdefault("placeholder", "+503 7012 3456")
            td.widget.attrs.setdefault("inputmode", "tel")
            td.widget.attrs.setdefault("autocomplete", "tel")

    def clean_telefono_dueno(self):
        v = self.cleaned_data.get("telefono_dueno")
        if not v or not str(v).strip():
            return ""
        return normalizar_guardado_telefono_sv(v)


class InmuebleDetalleLocalAlquilerForm(forms.ModelForm):
    """Ficha de arrendamiento para locales comerciales."""

    class Meta:
        model = InmuebleDetalleLocalAlquiler
        exclude = ("inmueble",)
        widgets = {
            "uso_permitido": forms.Textarea(attrs={"rows": 3, "class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                continue
            if not isinstance(w, (forms.HiddenInput,)):
                w.attrs.setdefault("class", "input")
        for name in (
            "renta_mensual",
            "cuota_mantenimiento",
            "deposito_garantia",
        ):
            f = self.fields.get(name)
            if f:
                f.widget.attrs.setdefault("step", "0.01")
                f.widget.attrs.setdefault("min", "0")
                f.widget.attrs.setdefault("placeholder", "ej. 500.00")
        inc = self.fields.get("incremento_anual_pct")
        if inc:
            inc.widget.attrs.setdefault("step", "0.01")
            inc.widget.attrs.setdefault("min", "0")
            inc.widget.attrs.setdefault("max", "100")
            inc.widget.attrs.setdefault("placeholder", "ej. 5 o 10")
        pg = self.fields.get("periodo_gracia_dias")
        if pg:
            pg.widget.attrs.setdefault("min", "0")
            pg.widget.attrs.setdefault("placeholder", "días")


class InmuebleDetalleCasaAlquilerForm(forms.ModelForm):
    """Ficha de arrendamiento para casas en alquiler."""

    class Meta:
        model = InmuebleDetalleCasaAlquiler
        exclude = ("inmueble",)
        widgets = {
            "inventario_detallado_estado": forms.Textarea(attrs={"rows": 4, "class": "input"}),
            "servicios_incluidos_renta": forms.Textarea(attrs={"rows": 3, "class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                continue
            if not isinstance(w, (forms.HiddenInput,)):
                w.attrs.setdefault("class", "input")
        for name in ("arrendamiento_mensual", "deposito_garantia_monto"):
            f = self.fields.get(name)
            if f:
                f.widget.attrs.setdefault("step", "0.01")
                f.widget.attrs.setdefault("min", "0")
                f.widget.attrs.setdefault("placeholder", "ej. 450.00")
        mx = self.fields.get("maximo_personas")
        if mx:
            mx.widget.attrs.setdefault("min", "1")
            mx.widget.attrs.setdefault("placeholder", "ej. 4")

    def clean(self):
        cleaned = super().clean()
        ini = cleaned.get("vigencia_inicio")
        fin = cleaned.get("vigencia_fin")
        if ini and fin and fin < ini:
            self.add_error(
                "vigencia_fin",
                "La fecha de fin no puede ser anterior a la de inicio.",
            )
        return cleaned


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tf = self.fields.get("telefono")
        if tf:
            tf.widget.attrs.setdefault("maxlength", "40")
            tf.widget.attrs.setdefault("placeholder", "+503 7012 3456 (hasta 40 caracteres)")
            tf.widget.attrs.setdefault("inputmode", "tel")
            tf.widget.attrs.setdefault("autocomplete", "tel")

    def clean_telefono(self):
        v = self.cleaned_data.get("telefono")
        if not v or not str(v).strip():
            return ""
        return normalizar_guardado_telefono_sv(v)


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
        vt = self.fields.get("telefono")
        if vt:
            vt.widget.attrs.setdefault("maxlength", "40")
            vt.widget.attrs.setdefault("placeholder", "+503 7012 3456 (hasta 40 caracteres)")
            vt.widget.attrs.setdefault("inputmode", "tel")
            vt.widget.attrs.setdefault("autocomplete", "tel")

    def clean_telefono(self):
        v = self.cleaned_data.get("telefono")
        if not v or not str(v).strip():
            return ""
        return normalizar_guardado_telefono_sv(v)


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


def _pago_contrato_catalog_option_attrs(c: dict) -> dict[str, str]:
    """Atributos data-* compartidos entre select de contrato y select de formato (panel + cuotas)."""
    return {
        "data-contrato-id": c.get("contrato_id", ""),
        "data-cuota-mensual": c.get("cuota_mensual", ""),
        "data-cuota-mensual-fuente": c.get("cuota_mensual_fuente", ""),
        "data-prox-vence": c.get("prox_vence", ""),
        "data-prox-monto": c.get("prox_monto", ""),
        "data-prox-numero": c.get("prox_numero", ""),
        "data-cliente": c.get("cliente", ""),
        "data-contrato-numero": c.get("contrato_numero", ""),
        "data-n-cuotas-total": c.get("n_cuotas_total", "0"),
        "data-n-cuotas-pagadas": c.get("n_cuotas_pagadas", "0"),
        "data-pendientes-json": c.get("pendientes_json", "[]"),
        "data-formato-id": c.get("formato_id", ""),
        "data-formato-numero": c.get("formato_numero_formulario", ""),
        "data-formato-edit-url": c.get("formato_edit_url", ""),
        "data-formato-nombre": c.get("formato_nombre_cliente", ""),
        "data-formato-letra-mensual": c.get("formato_letra_mensual", ""),
        "data-formato-plazo": c.get("formato_plazo_txt", ""),
        "data-formato-num-cuotas": c.get("formato_num_cuota_txt", ""),
        "data-formato-interes": c.get("formato_interes_txt", ""),
        "data-cuotas-todas-json": c.get("cuotas_todas_json", "[]"),
    }


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
            option["attrs"].update(_pago_contrato_catalog_option_attrs(c))
        return option


class FormatoPagoSelect(forms.Select):
    """Select de formato: mismos data-* que el contrato para panel y tabla sin depender del <select> oculto."""

    def __init__(self, *args, catalog=None, **kwargs):
        self.catalog = catalog or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value not in (None, ""):
            key = str(value)
            c = self.catalog.get(key, {})
            option.setdefault("attrs", {})
            option["attrs"].update(_pago_contrato_catalog_option_attrs(c))
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

    def __init__(self, *args, ocultar_contrato=False, user=None, **kwargs):
        self.ocultar_contrato = bool(ocultar_contrato)
        self._pago_user = user
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

        ct = self.fields.get("contrato")
        if ct:
            ct.label = "Contrato"
            ct.help_text = (
                "En «Nuevo pago» se rellena solo al elegir el formato (no visible en pantalla). "
                "Al editar un pago puede cambiar el contrato si aplica."
                if self.ocultar_contrato
                else (
                    "Contrato al que aplica el pago. Con «Cuota de financiamiento», use la tabla del calendario para marcar cuotas."
                )
            )
            from inmobiliaria.contratos_acceso import filtrar_contratos_queryset_por_vendedor

            ct_base = Contrato.objects.select_related("cliente", "inmueble").order_by(
                "-fecha_firma", "numero"
            )
            if self._pago_user is not None:
                ct_base = filtrar_contratos_queryset_por_vendedor(ct_base, self._pago_user)
            ct.queryset = ct_base
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
                    for f in FormatoAceptacion.objects.filter(
                        contrato_id__in=pks
                    ).defer("promesa_venta_escaneada")
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
                        "contrato_id": str(c.pk),
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

        fa = self.fields.get("formato_aceptacion")
        if fa:
            fa.required = False
            fa.label = "Formato de aceptación guardado"
            fa.help_text = (
                "Lista igual que en «Formatos de aceptación guardados». Si el formato no tiene contrato enlazado, "
                "el sistema intenta localizarlo por lote y proyecto del documento; si no puede, debe vincular el contrato al editar el formato."
            )
            fmt_qs = (
                FormatoAceptacion.objects.select_related("contrato", "contrato__cliente")
                .defer("promesa_venta_escaneada")
                .order_by("-numero_formulario", "-id")
            )
            fa.queryset = fmt_qs
            formato_catalog: dict[str, dict[str, str]] = {}
            fmt_labels: dict[int, str] = {}
            ct_catalog = getattr(ct.widget, "catalog", {}) if ct else {}
            for f in fmt_qs:
                if f.contrato_id:
                    res_ct: Contrato | None = f.contrato
                    ckey = str(f.contrato_id)
                else:
                    res_ct = contrato_desde_formato_aceptacion(f)
                    ckey = str(res_ct.pk) if res_ct else None
                if ckey:
                    base = dict(ct_catalog.get(ckey, {}))
                else:
                    base = _formato_sin_contrato_catalogo(f)
                fnom = (f.nombre_cliente or "").strip()
                cliente_src = (
                    str(res_ct.cliente)
                    if res_ct and res_ct.cliente_id
                    else base.get("cliente", "")
                )
                cliente_fmt = fnom or cliente_src
                fmt_num = f"{f.numero_formulario:04d}"
                fmt_url = reverse("app:formato_aceptacion_edit", kwargs={"pk": f.pk})
                fmt_letra = ""
                if f.letra_mensual is not None:
                    fmt_letra = str(f.letra_mensual.quantize(Decimal("0.01")))
                cuota_ref = fmt_letra or base.get("cuota_mensual", "")
                cuota_fuente = "formato" if fmt_letra else base.get("cuota_mensual_fuente", "")
                base.update(
                    {
                        "contrato_id": ckey or "",
                        "cliente": cliente_fmt,
                        "cuota_mensual": cuota_ref,
                        "cuota_mensual_fuente": cuota_fuente,
                        "formato_id": str(f.pk),
                        "formato_numero_formulario": fmt_num,
                        "formato_edit_url": fmt_url,
                        "formato_nombre_cliente": fnom,
                        "formato_letra_mensual": fmt_letra,
                        "formato_plazo_txt": (f.plazo_txt or "").strip(),
                        "formato_num_cuota_txt": (f.num_cuota_txt or "").strip(),
                        "formato_interes_txt": (f.interes_txt or "").strip(),
                    }
                )
                formato_catalog[str(f.pk)] = base
                if f.contrato_id:
                    fmt_labels[f.pk] = (
                        f"Nº {fmt_num} — {fnom} — Contrato {f.contrato.numero}"
                    )
                elif res_ct:
                    fmt_labels[f.pk] = (
                        f"Nº {fmt_num} — {fnom} — Contrato {res_ct.numero} (lote/proyecto)"
                    )
                else:
                    fmt_labels[f.pk] = (
                        f"Nº {fmt_num} — {fnom} (sin contrato: edite el formato para vincularlo)"
                    )
            fa.widget = FormatoPagoSelect(catalog=formato_catalog)
            fa.widget.choices = fa.choices
            fa.label_from_instance = lambda o: fmt_labels.get(o.pk, str(o))

        if not self.is_bound and not getattr(self.instance, "pk", None):
            if not self.initial.get("fecha"):
                self.fields["fecha"].initial = date.today()

    def clean(self):
        cleaned_data = super().clean()
        if self.ocultar_contrato and not getattr(self.instance, "pk", None):
            if not cleaned_data.get("formato_aceptacion"):
                raise ValidationError(
                    {
                        "formato_aceptacion": (
                            "Seleccione un formato de la lista de formatos guardados."
                        )
                    }
                )
        formato = cleaned_data.get("formato_aceptacion")
        if formato:
            if formato.contrato_id:
                cleaned_data["contrato"] = formato.contrato
            else:
                c_res = contrato_desde_formato_aceptacion(formato)
                if c_res:
                    cleaned_data["contrato"] = c_res
        if (
            self.ocultar_contrato
            and not getattr(self.instance, "pk", None)
            and cleaned_data.get("formato_aceptacion")
            and not cleaned_data.get("contrato")
        ):
            raise ValidationError(
                {
                    "formato_aceptacion": (
                        "Este formato no tiene contrato vinculado y no se encontró uno por lote y proyecto. "
                        "Abra «Editar» en ese formato y asocie el contrato, o revise que lote y nombre de proyecto coincidan con el inventario."
                    )
                }
            )

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
        help_text="Si el contrato tiene formato de aceptación vinculado con «Fecha pago primera cuota» "
        "o «Fecha de pago mensual», aquí se sugiere esa fecha. Las cuotas siguientes vencen el "
        "mismo día de cada mes hasta completar el plazo.",
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


_FORMATO_TELEFONO_FIELDS = (
    "telefono_domicilio",
    "telefono_notificacion",
    "telefono_trabajo",
    "ref_com_tel_1",
    "ref_com_tel_2",
    "ref_com_tel_3",
    "ref_per_tel_1",
    "ref_per_tel_2",
    "ref_per_tel_3",
)


def elaborado_por_sugerido_formato(contrato: Contrato | None, user) -> str:
    """Nombre para «Elaborado por»: vendedor del contrato o perfil de vendedor vinculado al usuario."""
    if contrato is not None:
        n = (contrato.nombre_vendedor_documentos() or "").strip()
        if n:
            return n
    if user is not None and getattr(user, "is_authenticated", False):
        v = (
            Vendedor.objects.filter(usuario_vinculo=user, activo=True)
            .only("nombres", "apellidos")
            .first()
        )
        if v:
            return v.nombre_completo.strip()
        fn = (user.get_full_name() or "").strip()
        if fn:
            return fn
        return (user.get_username() or "").strip()
    return ""


def _aplicar_pistas_observaciones_financiamiento(instance: FormatoAceptacion) -> None:
    """
    Completa plazo o interés solo si el campo correspondiente está vacío y el texto lo sugiere.
    Alineado con las mismas pistas que `formato_aceptacion_credito.js`.
    """
    obs = (instance.observaciones_financiamiento or "").lower()
    if not obs.strip():
        return
    if re.search(r"\b(sin\s*inter[eé]s|sin\s*interes|cero\s*inter[eé]s|0\s*%)\b", obs):
        if not (instance.interes_txt or "").strip():
            instance.interes_txt = "0"
    m_plazo = re.search(r"\b(\d{1,2})\s*(?:años?|anos?)\b", obs)
    if not m_plazo:
        m_plazo = re.search(r"\bplazo\s*[:\s]*(\d{1,2})\b", obs)
    if m_plazo:
        y = int(m_plazo.group(1))
        if 0 <= y <= 50 and not (instance.plazo_txt or "").strip():
            instance.plazo_txt = str(y)


def _aplicar_elaborado_por_desde_vendedor(instance: FormatoAceptacion, user) -> None:
    """Si «elaborado por» sigue vacío al guardar, sugerir desde contrato o usuario (no pisa el select)."""
    if (instance.elaborado_por or "").strip():
        return
    if instance.contrato_id:
        c = (
            Contrato.objects.filter(pk=instance.contrato_id)
            .select_related("vendedor_perfil", "vendedor")
            .first()
        )
        if c:
            n = (c.nombre_vendedor_documentos() or "").strip()
            if n:
                instance.elaborado_por = n
                return
    s = elaborado_por_sugerido_formato(None, user).strip()
    if s:
        instance.elaborado_por = s


def _choices_elaborado_por_vendedores() -> list[tuple[str, str]]:
    opts: list[tuple[str, str]] = [("", "— Seleccione vendedor —")]
    seen_lower: set[str] = set()
    for v in Vendedor.objects.filter(activo=True).order_by("apellidos", "nombres", "id"):
        n = v.nombre_completo.strip()
        if not n:
            continue
        k = n.lower()
        if k in seen_lower:
            continue
        seen_lower.add(k)
        opts.append((n, n))
    return opts


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
            "observaciones_financiamiento": forms.Textarea(
                attrs={"rows": 3, "class": "input", "placeholder": "Ej. sin interés, plazo 15 años, condición especial…"}
            ),
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
                    "placeholder": "+503 7012 3456 (hasta 40 caracteres)",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "title": "Móvil El Salvador: 8 dígitos o con prefijo 503 (área país).",
                }
            ),
            "telefono_notificacion": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "+503 7012 3456 (hasta 40 caracteres)",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "title": "Móvil El Salvador: 8 dígitos o con prefijo 503 (área país).",
                }
            ),
            "telefono_trabajo": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "+503 7012 3456 (hasta 40 caracteres)",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "title": "Móvil El Salvador: 8 dígitos o con prefijo 503 (área país).",
                }
            ),
            "ref_com_tel_1": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "+503 7012 3456 (hasta 40 caracteres)",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                }
            ),
            "ref_com_tel_2": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "+503 7012 3456 (hasta 40 caracteres)",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                }
            ),
            "ref_com_tel_3": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "+503 7012 3456 (hasta 40 caracteres)",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                }
            ),
            "ref_per_tel_1": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "+503 7012 3456 (hasta 40 caracteres)",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                }
            ),
            "ref_per_tel_2": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "+503 7012 3456 (hasta 40 caracteres)",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                }
            ),
            "ref_per_tel_3": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "+503 7012 3456 (hasta 40 caracteres)",
                    "maxlength": 40,
                    "inputmode": "tel",
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
            "prima_1_fecha": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "prima_2_fecha": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, user=None, **kwargs):
        self._formato_user = user
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
            "prima_1_fecha",
            "prima_2_fecha",
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

        ep = self.fields.get("elaborado_por")
        if ep:
            inst = self.instance
            choices = list(_choices_elaborado_por_vendedores())
            cur = ""
            if self.is_bound:
                cur = (self.data.get("elaborado_por") or "").strip()
            else:
                cur = (getattr(inst, "elaborado_por", None) or "").strip()
                if not cur:
                    contrato = None
                    if inst is not None and getattr(inst, "contrato_id", None):
                        contrato = getattr(inst, "contrato", None)
                        if contrato is None:
                            contrato = (
                                Contrato.objects.filter(pk=inst.contrato_id)
                                .select_related("vendedor_perfil", "vendedor")
                                .first()
                            )
                    sug = elaborado_por_sugerido_formato(contrato, user)
                    if sug:
                        cur = sug.strip()
                        self.initial["elaborado_por"] = cur
            choice_vals = {c[0] for c in choices}
            if cur and cur not in choice_vals:
                choices.insert(1, (cur, f"{cur} (guardado)"))
            lbl = FormatoAceptacion._meta.get_field("elaborado_por").verbose_name
            self.fields["elaborado_por"] = forms.ChoiceField(
                label=lbl,
                required=False,
                choices=choices,
                widget=forms.Select(attrs={"class": "input"}),
                help_text=(
                    "Catálogo de Vendedores (activos). Al crear el registro se sugiere el del contrato o su usuario; "
                    "puede elegir otro de la lista."
                ),
            )

        if not formato_aceptacion_credito_extra_columns_ready():
            for fname in FORMATO_CREDITO_EXTRA_FIELDS:
                self.fields.pop(fname, None)

    def clean(self):
        cleaned = super().clean()
        plazo_raw = (cleaned.get("plazo_txt") or "").strip()
        if plazo_raw.isdigit():
            y = int(plazo_raw)
            if 0 <= y <= 50:
                cleaned["num_cuota_txt"] = str(y * 12)
        for fname in _FORMATO_TELEFONO_FIELDS:
            v = cleaned.get(fname)
            if v is not None and str(v).strip():
                cleaned[fname] = normalizar_guardado_telefono_sv(v)
        return cleaned

    def save(self, commit=True):
        import base64
        import uuid

        from django.core.files.base import ContentFile

        instance = super().save(commit=False)
        _aplicar_elaborado_por_desde_vendedor(instance, getattr(self, "_formato_user", None))
        if formato_aceptacion_credito_extra_columns_ready():
            _aplicar_pistas_observaciones_financiamiento(instance)
        plazo_sync = (instance.plazo_txt or "").strip()
        if plazo_sync.isdigit():
            y = int(plazo_sync)
            if 0 <= y <= 50:
                instance.num_cuota_txt = str(y * 12)

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


class FormatoAceptacionPromesaForm(forms.Form):
    promesa_venta_escaneada = forms.FileField(
        label="Archivo escaneado (PDF o imagen)",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg"],
                message="Use PDF, JPG o PNG.",
            )
        ],
    )
