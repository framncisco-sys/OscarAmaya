"""Formularios para la interfaz web (sin admin)."""

import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db.models import Count, Prefetch, Q
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.urls import reverse

from .phone_sv import aplicar_attrs_telefono, limpiar_telefono_formulario
from .validators import validar_dui_sv, validar_nit_sv

from .formato_aceptacion_db import (
    FORMATO_CREDITO_EXTRA_FIELDS,
    FORMATO_TIPO_FINANCIAMIENTO_FIELD,
    formato_aceptacion_adjuntos_columns_ready,
    formato_aceptacion_credito_extra_columns_ready,
    formato_aceptacion_tipo_financiamiento_column_ready,
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

PROYECTO_CONTENEDOR_CASA_VENTA = "Casas en venta"


def mensaje_alerta_lote_ocupado(
    inv: Inmueble | None,
    *,
    cliente: Cliente | None = None,
    permitir_misma_reserva: bool = True,
) -> str | None:
    """
    Aviso si el lote no está libre para ofrecer / vender.
    None = disponible (o reserva del mismo cliente si permitir_misma_reserva).
    """
    if inv is None:
        return None
    estado = inv.estado
    codigo = (inv.codigo_display or "").strip() or "—"
    if estado == Inmueble.Estado.VENDIDO:
        return (
            f"El lote {codigo} ya está PAGADO TOTALMENTE / VENDIDO. "
            "No se puede ofrecer ni registrar otra venta sobre ese lote."
        )
    if estado == Inmueble.Estado.BLOQUEADO:
        return (
            f"El lote {codigo} está BLOQUEADO. "
            "Consulte con gerencia antes de usarlo en un formato o venta."
        )
    if estado == Inmueble.Estado.RESERVADO:
        if (
            permitir_misma_reserva
            and cliente is not None
            and inv.cliente_reserva_id
            and cliente.pk == inv.cliente_reserva_id
        ):
            return None
        quien = ""
        if inv.cliente_reserva_id:
            c = inv.cliente_reserva
            quien = f"{(c.nombres or '').strip()} {(c.apellidos or '').strip()}".strip()
        quien = quien or "otro cliente"
        hasta = (
            f" (vence {inv.reserva_hasta.strftime('%d/%m/%Y')})"
            if inv.reserva_hasta
            else ""
        )
        return (
            f"El lote {codigo} ya está RESERVADO por {quien}{hasta}. "
            "No lo ofrezca a otro comprador: elija un lote disponible o "
            "espere a que se libere la reserva."
        )
    return None


def proyecto_contenedor_casa_venta() -> Proyecto:
    """Proyecto técnico para casas sueltas en venta (sin elegir lotificación en el alta)."""
    proyecto, _ = Proyecto.objects.get_or_create(
        nombre=PROYECTO_CONTENEDOR_CASA_VENTA,
        defaults={"activo": True},
    )
    return proyecto

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
    from inmobiliaria.lote_codigo import resolver_inmueble_por_codigo_lote

    inv = resolver_inmueble_por_codigo_lote(
        num_lote=num_lote,
        proyecto_nombre=nom_proy,
        poligono_txt=(f.poligono_txt or "").strip(),
    )
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
        "recargo_monto": "0",
        "recargo_cantidad": "0",
        "recargo_total_mes": "",
        "recargo_nota": "",
        "recargo_unitario": "0",
        "dias_gracia": "0",
        "valor_lote": (
            str(f.valor_inmueble.quantize(Decimal("0.01")))
            if f.valor_inmueble is not None
            else ""
        ),
        "tipo_financiamiento": getattr(f, "tipo_financiamiento", "") or "",
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
        fields = [
            "nombre",
            "municipio",
            "departamento",
            "direccion",
            "logo",
            "plano_maestro",
            "porcentaje_prima",
            "porcentaje_reserva",
            "permisos_notas",
            "activo",
        ]
        widgets = {
            "logo": forms.ClearableFileInput(
                attrs={"accept": ".png,.jpg,.jpeg,.webp,image/*"}
            ),
            "plano_maestro": forms.ClearableFileInput(
                attrs={"accept": ".pdf,.png,.jpg,.jpeg,.webp,image/*,application/pdf"}
            ),
            "direccion": forms.Textarea(attrs={"rows": 2}),
            "permisos_notas": forms.Textarea(attrs={"rows": 3}),
            "porcentaje_prima": forms.NumberInput(
                attrs={
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                    "inputmode": "decimal",
                    "placeholder": "ej. 20",
                }
            ),
            "porcentaje_reserva": forms.NumberInput(
                attrs={
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                    "inputmode": "decimal",
                    "placeholder": "ej. 5",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["logo"].label = "Logo del proyecto"
        self.fields["logo"].help_text = (
            "Imagen del logo (PNG o JPG). Aparece en recibos y documentos PDF de este proyecto."
        )
        self.fields["plano_maestro"].label = "Plano del proyecto"
        self.fields["plano_maestro"].help_text = (
            "Plano completo (PDF o imagen). Se usa en el mapa de lotes y polígonos."
        )
        pp = self.fields.get("porcentaje_prima")
        if pp:
            pp.help_text = (
                "Prima total como % del valor del lote. En el formato: "
                "Reserva + Prima a pagar = valor × este %."
            )
        pr = self.fields.get("porcentaje_reserva")
        if pr:
            pr.help_text = (
                "% del valor del lote para la reserva. Debe ser ≤ prima total %. "
                "Se calcula sola al elegir el lote."
            )

    def clean(self):
        cleaned = super().clean()
        pct_p = cleaned.get("porcentaje_prima")
        pct_r = cleaned.get("porcentaje_reserva")
        if pct_p is not None and pct_r is not None and pct_r > pct_p:
            self.add_error(
                "porcentaje_reserva",
                "La reserva % no puede ser mayor que la prima total %.",
            )
        return cleaned


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
        # Campos que no se capturan en el formulario web de lote/inmueble.
        # (La geometría se edita en el mapa; no borrar columnas de BD.)
        for _ocultar in (
            "servicios_basicos",
            "latitud",
            "longitud",
            "frente_m",
            "fondo_m",
            "topografia",
            "tour_virtual_url",
            "notas",
            "geometria_json",
            "geometria_catastral_geojson",
        ):
            self.fields.pop(_ocultar, None)
        inv = self.instance
        if (
            inv.pk
            and inv.tipo in (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA)
            and not inv.en_alquiler
        ):
            for nombre in (
                "en_alquiler",
                "proyecto",
                "poligono",
                "inmueble_padre",
            ):
                self.fields.pop(nombre, None)
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

        for fname in ("precio_preventa", "precio_promocional", "precio_pos_preventa", "precio_lista"):
            f = self.fields.get(fname)
            if f:
                f.widget.attrs.setdefault("inputmode", "decimal")
                f.widget.attrs.setdefault("placeholder", "0.00")
        pl = self.fields.get("precio_lista")
        if pl:
            pl.help_text = (
                "Precio de lista / referencia del lote (no lo cambia el contador de etapas). "
                "Si deja vacíos Preventa/Promocional/Pos al crear, se copia este monto a los tres "
                "como precio de venta inicial."
            )

        # Precios: $25,136.72 (miles con coma, decimales con punto).
        for fname in (
            "precio_lista",
            "precio_preventa",
            "precio_promocional",
            "precio_pos_preventa",
        ):
            old = self.fields.get(fname)
            if not old:
                continue
            self.fields[fname] = MontoDecimalFormField(
                label=old.label,
                help_text=getattr(old, "help_text", "") or "",
                max_digits=14,
                decimal_places=2,
                required=old.required,
                mostrar_simbolo=True,
                min_value=Decimal("0"),
            )
        pl = self.fields.get("precio_lista")
        if pl:
            pl.help_text = (
                "Precio de lista / referencia del lote (no lo cambia el contador de etapas). "
                "Formato: $25,136.72. Si deja vacíos Preventa/Promocional/Pos al crear, "
                "se copia este monto a los tres como precio de venta inicial."
            )
        for fname, tip in (
            (
                "precio_preventa",
                "Precio de venta de contado mientras el proyecto esté en Preventa "
                "(lo elige el contador de lotes comprometidos).",
            ),
            (
                "precio_promocional",
                "Precio de venta de contado en etapa Promocional.",
            ),
            (
                "precio_pos_preventa",
                "Precio de venta de contado en etapa Pos preventa.",
            ),
        ):
            f = self.fields.get(fname)
            if f:
                f.help_text = tip

        # Áreas: 1,234.5678 sin $.
        for fname, decs in (
            ("area_varas_cuadradas", 4),
            ("area_m2", 4),
        ):
            old = self.fields.get(fname)
            if not old:
                continue
            self.fields[fname] = NumeroDecimalFormField(
                label=old.label,
                help_text=getattr(old, "help_text", "") or "",
                max_digits=getattr(old, "max_digits", 12),
                decimal_places=getattr(old, "decimal_places", decs),
                required=old.required,
                decimales_display=decs,
            )
        if "area_m2" in self.fields:
            self.fields["area_m2"].help_text = (
                "Se calcula automáticamente al ingresar las varas (1 v² ≈ 0.698896 m²) "
                "y se redondea a 2 decimales (ej. 286.16 v² → 200.00 m²)."
            )
        if "area_varas_cuadradas" in self.fields:
            self.fields["area_varas_cuadradas"].help_text = (
                "Superficie en varas cuadradas (v²). Al escribirla se calcula el área en m²."
            )

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
        # Prioridad: si hay varas, m² se calcula siempre desde varas (redondeo a 2 decimales).
        if v2 is not None:
            cleaned["area_m2"] = (v2 * M2_POR_V2).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        elif m2 is not None:
            cleaned["area_varas_cuadradas"] = (m2 / M2_POR_V2).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )

        estado = cleaned.get("estado")
        if estado == Inmueble.Estado.RESERVADO:
            if not cleaned.get("reserva_hasta"):
                self.add_error("reserva_hasta", "Indique la fecha límite de la reserva.")
        else:
            cleaned["reserva_hasta"] = None
            cleaned["cliente_reserva"] = None

        # Si solo hay precio_lista, copiar a las 3 etapas (carga rápida).
        pl = cleaned.get("precio_lista")
        for fname in ("precio_preventa", "precio_promocional", "precio_pos_preventa"):
            if cleaned.get(fname) is None and pl is not None:
                cleaned[fname] = pl

        # Unicidad: mismo código OK en otro polígono; no dentro del mismo polígono/proyecto.
        proyecto = cleaned.get("proyecto")
        poligono = cleaned.get("poligono")
        codigo = (cleaned.get("codigo") or "").strip()
        if proyecto is not None and codigo and "codigo" not in self.errors:
            qs = Inmueble.objects.filter(proyecto=proyecto, codigo=codigo)
            if poligono is not None:
                qs = qs.filter(poligono=poligono)
            else:
                qs = qs.filter(poligono__isnull=True)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                if poligono is not None:
                    self.add_error(
                        "codigo",
                        (
                            f"Ya existe el lote «{codigo}» en el polígono "
                            f"«{poligono}» de este proyecto. En otro polígono sí puede repetirse."
                        ),
                    )
                else:
                    self.add_error(
                        "codigo",
                        (
                            f"Ya existe el inmueble «{codigo}» sin polígono en este proyecto. "
                            "Asigne un polígono distinto o use otro código."
                        ),
                    )
        return cleaned

    def save(self, commit=True):
        # precio_lista es referencia: no se pisa con el precio de etapa.
        instance = super().save(commit=commit)
        return instance


class InmuebleCasaAltaForm(InmuebleForm):
    """Alta de casa en venta: sin proyecto ni alquiler (módulo independiente de lotes y arrendamiento)."""

    class Meta(InmuebleForm.Meta):
        fields = [
            "tipo",
            "codigo",
            "precio_lista",
        ]

    def __init__(self, *args, modo_tipo: str = "casa", **kwargs):
        super().__init__(*args, modo_tipo=modo_tipo, **kwargs)
        for _name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                continue
            if not isinstance(w, (forms.HiddenInput,)):
                w.attrs.setdefault("class", "input")
        # precio_lista ya viene como MontoDecimalFormField con máscara $ desde InmuebleForm.

    def save(self, commit=True):
        inmueble = super().save(commit=False)
        inmueble.proyecto = proyecto_contenedor_casa_venta()
        inmueble.en_alquiler = False
        inmueble.estado = Inmueble.Estado.DISPONIBLE
        if commit:
            inmueble.save()
        return inmueble


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
            aplicar_attrs_telefono(td)

    def clean_telefono_dueno(self):
        return limpiar_telefono_formulario(self.cleaned_data.get("telefono_dueno"))


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
        inq = self.fields.get("inquilino")
        if inq:
            inq.queryset = Cliente.objects.order_by("apellidos", "nombres")
            inq.required = False
            inq.empty_label = "— Sin asignar —"
            inq.help_text = "Cliente que arrendará este local (independiente del módulo de ventas)."
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
        inq = self.fields.get("inquilino")
        if inq:
            inq.queryset = Cliente.objects.order_by("apellidos", "nombres")
            inq.required = False
            inq.empty_label = "— Sin asignar —"
            inq.help_text = "Cliente que arrendará esta casa (independiente del módulo de ventas)."

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
            aplicar_attrs_telefono(tf)

    def clean_telefono(self):
        return limpiar_telefono_formulario(self.cleaned_data.get("telefono"))


class VendedorForm(forms.ModelForm):
    class Meta:
        model = Vendedor
        fields = [
            "nombres",
            "apellidos",
            "tipo_persona",
            "dui",
            "nit",
            "nrc",
            "giro",
            "telefono",
            "email",
            "porcentaje_comision_default",
            "usuario_vinculo",
            "dui_frente",
            "dui_reverso",
            "activo",
            "notas",
        ]
        widgets = {
            "tipo_persona": forms.RadioSelect,
            "giro": forms.TextInput(attrs={"placeholder": "Ej. intermediación inmobiliaria"}),
            "nrc": forms.TextInput(attrs={"placeholder": "NRC"}),
            "nit": forms.TextInput(attrs={"placeholder": "0000-000000-000-0"}),
        }

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
        self.fields["porcentaje_comision_default"].label = "Comisión de venta (%)"
        self.fields["porcentaje_comision_default"].help_text = (
            "Cuánto % le corresponde sobre el precio de venta. Se usa al asignarlo en un contrato "
            "y al generar el recibo de comisión (solo si el cliente ya pagó reserva y prima "
            "validadas, y este registro está completo: DUI, teléfono y correo)."
        )
        self.fields["tipo_persona"].label = "Tipo de persona"
        self.fields["tipo_persona"].help_text = (
            "Si elige Contribuyente, debe indicar NIT, NRC y giro."
        )
        self.fields["dui_frente"].help_text = "Imagen o PDF del frente del DUI."
        self.fields["dui_reverso"].help_text = "Imagen o PDF del reverso del DUI."
        for name in ("nit", "nrc", "giro"):
            self.fields[name].required = False
        # En alta pedimos ambas caras; en edición solo si aún no hay archivo.
        es_nuevo = self.instance.pk is None
        self.fields["dui_frente"].required = es_nuevo or not bool(
            getattr(self.instance, "dui_frente", None)
            and getattr(self.instance.dui_frente, "name", "")
        )
        self.fields["dui_reverso"].required = es_nuevo or not bool(
            getattr(self.instance, "dui_reverso", None)
            and getattr(self.instance.dui_reverso, "name", "")
        )
        vt = self.fields.get("telefono")
        if vt:
            aplicar_attrs_telefono(vt)

    def clean_telefono(self):
        return limpiar_telefono_formulario(self.cleaned_data.get("telefono"))

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get("tipo_persona") or Vendedor.TipoPersona.NATURAL
        if tipo == Vendedor.TipoPersona.CONTRIBUYENTE:
            for campo, etiqueta in (
                ("nit", "NIT"),
                ("nrc", "NRC"),
                ("giro", "giro"),
            ):
                val = (cleaned.get(campo) or "").strip()
                cleaned[campo] = val
                if not val:
                    self.add_error(campo, f"Obligatorio para contribuyente: indique el {etiqueta}.")
        else:
            # Natural: no exigir datos fiscales (se pueden dejar en blanco).
            cleaned["nit"] = (cleaned.get("nit") or "").strip()
            cleaned["nrc"] = (cleaned.get("nrc") or "").strip()
            cleaned["giro"] = (cleaned.get("giro") or "").strip()
        return cleaned


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
        "data-recargo-monto": c.get("recargo_monto", "0"),
        "data-recargo-cantidad": c.get("recargo_cantidad", "0"),
        "data-recargo-total-mes": c.get("recargo_total_mes", ""),
        "data-recargo-nota": c.get("recargo_nota", ""),
        "data-recargo-unitario": c.get("recargo_unitario", "0"),
        "data-dias-gracia": c.get("dias_gracia", "0"),
        "data-valor-lote": c.get("valor_lote", ""),
        "data-tipo-financiamiento": c.get("tipo_financiamiento", ""),
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
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["vendedor_perfil"].queryset = Vendedor.objects.filter(activo=True).order_by(
            "apellidos", "nombres"
        )
        self.fields["vendedor_perfil"].required = False
        self.fields["vendedor_perfil"].label = "Asesor de ventas (catálogo)"
        self.fields["vendedor_perfil"].help_text = (
            "Obligatorio para comisión de venta. Al elegirlo se copia su % de comisión. "
            "El recibo de comisión solo se emite cuando reserva y prima estén validadas."
        )
        if "vendedor_nombre" in self.fields:
            self.fields["vendedor_nombre"].help_text = (
                "Opcional si elige asesor del catálogo; use este campo para un nombre libre en documentos."
            )
        # Asesor de ventas de campo: el contrato queda siempre a su nombre en catálogo.
        if self.user is not None:
            from inmobiliaria.contratos_acceso import vendedor_catalogo_activo_vinculado
            from inmobiliaria.vendedor_acceso import es_vendedor_restringido

            if es_vendedor_restringido(self.user):
                vc = vendedor_catalogo_activo_vinculado(self.user)
                if vc is not None:
                    self.fields["vendedor_perfil"].queryset = Vendedor.objects.filter(pk=vc.pk)
                    self.fields["vendedor_perfil"].initial = vc.pk
                    self.fields["vendedor_perfil"].required = True
                    self.fields["vendedor_perfil"].help_text = (
                        "Asignado automáticamente a su registro de asesor de ventas."
                    )
                    if not getattr(self.instance, "pk", None):
                        self.initial.setdefault("vendedor_perfil", vc.pk)
        if "comision_porcentaje" in self.fields:
            self.fields["comision_porcentaje"].label = "Comisión del asesor de ventas (%)"
            self.fields["comision_porcentaje"].help_text = (
                "Porcentaje sobre el precio final. Se rellena al elegir asesor; puede ajustarlo."
            )
        if "comision_monto" in self.fields:
            self.fields["comision_monto"].label = "Comisión del asesor de ventas (monto fijo USD)"
            self.fields["comision_monto"].help_text = (
                "Si define monto fijo, tiene prioridad sobre el % al calcular el recibo de comisión."
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
                "En a plazos desde formato: se usa «Primer año sin intereses». "
                "Meses 1–12 = cuota del asesor de ventas; desde el 13 = nueva deuda con interés."
            )
        if "descuento_efectivo_monto" in self.fields:
            self.fields["descuento_efectivo_monto"].help_text = (
                "Se resta del monto inicial junto con lo abonado en meses 1–12 para calcular la nueva deuda."
            )
        if "precio_final" in self.fields:
            self.fields["precio_final"].help_text = (
                "Con crédito a plazos del formato: se rellena con la nueva deuda "
                "(inicial − descuento − abonado 1–12)."
            )
        if "cuota_mensual_estimada" in self.fields:
            self.fields["cuota_mensual_estimada"].help_text = (
                "Desde el mes 13: cuota mensual sobre la nueva deuda incluyendo intereses."
            )

        ff = self.fields.get("fecha_firma")
        if ff:
            wattrs = {**ff.widget.attrs, "type": "date"}
            ff.widget = forms.DateInput(attrs=wattrs, format="%Y-%m-%d")
            ff.input_formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]

        for fname, label, htxt in (
            (
                "cuota_mensual_estimada",
                "Cuota mensual (desde mes 13, con interés)",
                "Calculada con la nueva deuda, cuotas restantes e interés del formato a plazos.",
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
        if self.user is not None:
            from inmobiliaria.contratos_acceso import vendedor_catalogo_activo_vinculado
            from inmobiliaria.vendedor_acceso import es_vendedor_restringido

            if es_vendedor_restringido(self.user):
                vc = vendedor_catalogo_activo_vinculado(self.user)
                if vc is not None:
                    cleaned_data["vendedor_perfil"] = vc
        vp = cleaned_data.get("vendedor_perfil")
        pct = cleaned_data.get("comision_porcentaje")
        if vp is not None and pct in (None, ""):
            cleaned_data["comision_porcentaje"] = vp.porcentaje_comision_default
        _montos_calculados_contrato(cleaned_data)

        inv = cleaned_data.get("inmueble")
        cli = cleaned_data.get("cliente")
        if inv is not None:
            # Al editar el mismo contrato, no bloquear por el estado actual del lote.
            mismo = (
                getattr(self.instance, "pk", None)
                and getattr(self.instance, "inmueble_id", None) == inv.pk
            )
            if not mismo:
                # En contrato nuevo: vendido/bloqueado siempre; reserva solo si es de otro cliente.
                alerta = mensaje_alerta_lote_ocupado(
                    inv, cliente=cli, permitir_misma_reserva=True
                )
                if alerta:
                    self.add_error("inmueble", alerta)
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


class PlanPagosForm(ContratoForm):
    """
    Pantalla «Plan de pagos»: solo elige cliente; el resto (reserva, prima,
    cuotas 1–12, nueva deuda, cuota desde mes 13) se carga del formato.
    """

    prima_monto = forms.DecimalField(
        label="Prima",
        required=False,
        min_value=Decimal("0"),
        max_digits=14,
        decimal_places=2,
        widget=forms.HiddenInput(),
    )

    class Meta(ContratoForm.Meta):
        fields = [
            "cliente",
            "descuento_efectivo_monto",
            "inmueble",
            "precio_lista_referencia",
            "precio_final",
            "plan_anos",
            "tasa_interes_anual",
            "cuota_mensual_estimada",
            "modalidad_financiamiento",
            "meses_sin_interes",
            "notas",
            "vendedor_perfil",
        ]

    class Media:
        js = ()  # el plan se carga con contrato_credito_formato.js en la plantilla

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo visible: cliente. Todo lo demás va al panel de crédito.
        ocultos = (
            "descuento_efectivo_monto",
            "inmueble",
            "precio_lista_referencia",
            "precio_final",
            "plan_anos",
            "tasa_interes_anual",
            "cuota_mensual_estimada",
            "modalidad_financiamiento",
            "meses_sin_interes",
            "notas",
            "vendedor_perfil",
        )
        for fname in ocultos:
            if fname not in self.fields:
                continue
            self.fields[fname].widget = forms.HiddenInput()
            self.fields[fname].required = False

        if "cliente" in self.fields:
            self.fields["cliente"].label = "Cliente"
            self.fields["cliente"].help_text = (
                "Solo después de pagar las 12 cuotas sin interés del plan base. "
                "Se crea un único plan por cliente con la nueva deuda e interés desde el mes 13. "
                "Al elegirlo verá el desglose; luego pulse Guardar."
            )

        self.fields["prima_monto"].required = False
        self.order_fields(
            [
                "cliente",
                "descuento_efectivo_monto",
                "prima_monto",
                "inmueble",
                "precio_lista_referencia",
                "precio_final",
                "plan_anos",
                "tasa_interes_anual",
                "cuota_mensual_estimada",
                "modalidad_financiamiento",
                "meses_sin_interes",
                "notas",
                "vendedor_perfil",
            ]
        )

        # Valores por defecto del plan a plazos
        if not getattr(self.instance, "pk", None):
            self.initial.setdefault(
                "modalidad_financiamiento",
                Contrato.ModalidadFinanciamiento.PRIMER_ANO_SIN_INTERESES,
            )
            self.initial.setdefault("meses_sin_interes", 12)

    def clean(self):
        # Conservar la cuota del panel (mes 13+); el padre la recalcula con otra fórmula.
        raw_cuota = None
        if self.is_bound:
            raw_cuota = self.data.get("cuota_mensual_estimada")
        cleaned = super().clean()
        if raw_cuota not in (None, ""):
            try:
                from .money_fmt import normalizar_monto_a_decimal_str

                cleaned["cuota_mensual_estimada"] = Decimal(
                    normalizar_monto_a_decimal_str(str(raw_cuota))
                )
            except Exception:
                try:
                    cleaned["cuota_mensual_estimada"] = Decimal(
                        str(raw_cuota).replace(",", "").strip()
                    )
                except Exception:
                    pass
        pf = cleaned.get("precio_final")
        if pf is None:
            self.add_error(
                "cliente",
                "Seleccione un cliente con formato a plazos para calcular la nueva deuda, "
                "o revise que el formato tenga cuota y plazo.",
            )

        # Alta: solo tras 12 cuotas pagadas y un solo plan PP- por cliente.
        if not getattr(self.instance, "pk", None):
            cliente = cleaned.get("cliente")
            if cliente is not None:
                from inmobiliaria.credito_contrato import elegibilidad_nuevo_plan_mes13

                eleg = elegibilidad_nuevo_plan_mes13(cliente)
                if not eleg.get("puede_crear_plan_mes13"):
                    self.add_error(
                        "cliente",
                        eleg.get("motivo_plan_mes13")
                        or "No se puede crear el plan de pagos para este cliente.",
                    )
        return cleaned

    def save(self, commit=True):
        from django.utils import timezone

        instance = super().save(commit=False)
        if not (instance.numero or "").strip():
            stamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
            base = f"PP-{stamp}"
            numero = base
            n = 1
            while Contrato.objects.filter(numero=numero).exclude(pk=instance.pk or 0).exists():
                n += 1
                numero = f"{base}-{n}"
            instance.numero = numero
        if not instance.fecha_firma:
            instance.fecha_firma = timezone.localdate()
        if not instance.estado:
            instance.estado = Contrato.Estado.BORRADOR
        if not instance.etapa_comercial:
            instance.etapa_comercial = Contrato.EtapaComercial.CONVERSACION
        if not instance.modalidad_financiamiento:
            instance.modalidad_financiamiento = (
                Contrato.ModalidadFinanciamiento.PRIMER_ANO_SIN_INTERESES
            )
        if instance.meses_sin_interes is None:
            instance.meses_sin_interes = 12

        # Vendedor + comisión desde «Elaborado por» del formato de aceptación.
        if instance.cliente_id and not instance.vendedor_perfil_id:
            from inmobiliaria.comision_vendedor import vendedor_por_nombre_elaborado
            from inmobiliaria.credito_contrato import buscar_formato_plazos_del_cliente

            fmt = buscar_formato_plazos_del_cliente(instance.cliente)
            if fmt and (fmt.elaborado_por or "").strip():
                vp = vendedor_por_nombre_elaborado(fmt.elaborado_por)
                if vp is not None:
                    instance.vendedor_perfil = vp
                    instance.vendedor_nombre = vp.nombre_completo[:120]
                    if vp.usuario_vinculo_id:
                        instance.vendedor_id = vp.usuario_vinculo_id
                    if instance.comision_porcentaje is None:
                        instance.comision_porcentaje = vp.porcentaje_comision_default

        if commit:
            instance.save()
        return instance


class MontoDecimalFormField(forms.DecimalField):
    """
    Montos con miles en coma y decimales en punto (22,500.00).
    También acepta 22500.00 o formato europeo 22.500,00 al pegar.
    Con mostrar_simbolo=True muestra $22,500.00 (se quita al guardar).
    """

    def __init__(self, *args, mostrar_simbolo: bool = False, **kwargs):
        self.mostrar_simbolo = bool(mostrar_simbolo)
        attrs = {
            "class": "input input-monto-us"
            + (" input-monto-us--symbol" if self.mostrar_simbolo else ""),
            "inputmode": "decimal",
            "placeholder": "$0.00" if self.mostrar_simbolo else "0.00",
            "autocomplete": "off",
        }
        kwargs.setdefault("widget", forms.TextInput(attrs=attrs))
        super().__init__(*args, **kwargs)
        # Asegurar clase aunque pasen widget custom.
        wattrs = getattr(self.widget, "attrs", None)
        if isinstance(wattrs, dict):
            cls = (wattrs.get("class") or "").strip()
            if "input-monto-us" not in cls.split():
                wattrs["class"] = (cls + " input input-monto-us").strip()
            if self.mostrar_simbolo and "input-monto-us--symbol" not in (
                wattrs.get("class") or ""
            ):
                wattrs["class"] = (wattrs.get("class", "") + " input-monto-us--symbol").strip()
            wattrs.setdefault(
                "placeholder", "$0.00" if self.mostrar_simbolo else "0.00"
            )

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, str):
            from .money_fmt import normalizar_monto_a_decimal_str

            value = normalizar_monto_a_decimal_str(value)
        return super().to_python(value)

    def prepare_value(self, value):
        if value is None or value == "":
            return ""
        from .money_fmt import format_monto_us, normalizar_monto_a_decimal_str

        if isinstance(value, str):
            try:
                normalized = normalizar_monto_a_decimal_str(value)
                if not normalized:
                    return value
                return format_monto_us(normalized, con_simbolo=self.mostrar_simbolo)
            except Exception:
                return value
        return format_monto_us(value, con_simbolo=self.mostrar_simbolo)


class NumeroDecimalFormField(forms.DecimalField):
    """Áreas y cantidades: 1,234.5678 (sin símbolo $)."""

    def __init__(self, *args, decimales_display: int | None = None, **kwargs):
        self.decimales_display = (
            decimales_display
            if decimales_display is not None
            else kwargs.get("decimal_places", 2)
        )
        kwargs.setdefault(
            "widget",
            forms.TextInput(
                attrs={
                    "class": "input input-numero-us",
                    "inputmode": "decimal",
                    "placeholder": "0.00",
                    "autocomplete": "off",
                }
            ),
        )
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, str):
            from .money_fmt import normalizar_monto_a_decimal_str

            value = normalizar_monto_a_decimal_str(value)
        return super().to_python(value)

    def prepare_value(self, value):
        if value is None or value == "":
            return ""
        from .money_fmt import format_numero_us, normalizar_monto_a_decimal_str

        if isinstance(value, str):
            try:
                normalized = normalizar_monto_a_decimal_str(value)
                if not normalized:
                    return value
                return format_numero_us(normalized, decimales=self.decimales_display)
            except Exception:
                return value
        return format_numero_us(value, decimales=self.decimales_display)


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
            "monto_recargo_incluido",
            "referencia",
            "voucher_transferencia",
            "notas",
            "cuotas_incluidas",
        ]

    def __init__(self, *args, ocultar_contrato=False, user=None, concepto_fijo=None, **kwargs):
        self.ocultar_contrato = bool(ocultar_contrato)
        self._pago_user = user
        self._concepto_fijo = (concepto_fijo or "").strip().upper() or None
        super().__init__(*args, **kwargs)

        ci = self.fields.get("cuotas_incluidas")
        if ci:
            ci.widget = forms.HiddenInput()
            ci.show_hidden_initial = False

        mri = self.fields.get("monto_recargo_incluido")
        if mri:
            mri.widget = forms.HiddenInput()
            mri.required = False
            mri.initial = Decimal("0.00")

        ff = self.fields.get("fecha")
        if ff:
            ff.label = "Fecha en que se realizó el pago"
            wattrs = {**ff.widget.attrs, "type": "date"}
            ff.widget = forms.DateInput(attrs=wattrs, format="%Y-%m-%d")
            ff.input_formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]
            ff.help_text = (
                "Día real en que el cliente pagó / usted recibió el dinero. "
                "NO ponga aquí el vencimiento de la cuota (eso está en la columna «Vence» del calendario). "
                "El atraso y el recargo se calculan comparando esta fecha con el vencimiento + días de gracia. "
                "Si esta cuota se atrasa, el recargo se cobra en la siguiente."
            )

        m = self.fields.get("monto")
        if m:
            m.label = "Monto total del pago"
            m.help_text = (
                "Importe total recibido. Ejemplo: cuota $200 y abona $250 → ponga $250. "
                "En el recibo saldrá la cuota y el excedente como abono a capital; "
                "el total ($250) se descuenta del saldo. Use coma o punto decimal."
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

        n = self.fields.get("notas")
        if n:
            n.label = "Notas (salen en el recibo)"
            n.help_text = (
                "Opcional. Sale en el recibo. Si hay excedente a capital, el PDF ya lo desglosa solo."
            )

        c = self.fields.get("concepto")
        if c:
            c.label = "Concepto del recibo"
            # Si viene del flujo (Reserva / Prima / Cuota), solo ese concepto.
            fijo = self._concepto_fijo
            if fijo in {x.value for x in Pago.Concepto}:
                # Etiquetas del flujo (no depender solo del modelo por caché / SW).
                labels_flujo = {
                    Pago.Concepto.RESERVA: "Reserva pagada (recibo)",
                    Pago.Concepto.PRIMA: "Prima pagada (recibo)",
                    Pago.Concepto.CONTADO: "Pago de contado (total del lote)",
                    Pago.Concepto.CUOTA: "Cuota de financiamiento (plazos)",
                }
                label = labels_flujo.get(fijo) or dict(Pago.Concepto.choices).get(fijo, fijo)
                c.choices = [(fijo, label)]
                c.initial = fijo
                c.disabled = True
                c.required = False  # disabled no se envía; se fuerza en clean()
                c.help_text = "Fijado por el paso del flujo de venta."
            else:
                c.help_text = (
                    "Orden: 1) Reserva → 2) Prima → 3) Cuotas. "
                    "Si paga más que la cuota, deje concepto «Cuota de financiamiento» y el monto total: "
                    "un solo recibo con cuota + abono a capital. "
                    "«Abono a capital» solo si abona a capital sin liquidar cuota del mes."
                )
                orden = [
                    Pago.Concepto.RESERVA,
                    Pago.Concepto.PRIMA,
                    Pago.Concepto.CUOTA,
                    Pago.Concepto.MANTENIMIENTO,
                    Pago.Concepto.ABONO_CAPITAL,
                    Pago.Concepto.MORA,
                    Pago.Concepto.OTRO,
                ]
                # Vendedor: no registra cuotas a plazos (solo gerencia/admin).
                from inmobiliaria.vendedor_acceso import es_vendedor_restringido

                if self._pago_user is not None and es_vendedor_restringido(self._pago_user):
                    orden = [x for x in orden if x != Pago.Concepto.CUOTA]
                    c.help_text = (
                        "Puede registrar reserva, prima u otros conceptos de su flujo. "
                        "Los recibos a plazos (cuotas) los registra gerencia o administrador."
                    )
                c.choices = [(x.value, x.label) for x in orden]

        r = self.fields.get("referencia")
        if r:
            if self._concepto_fijo == Pago.Concepto.CUOTA or (
                (self.data.get("concepto") if self.is_bound else None) or ""
            ).strip().upper() == Pago.Concepto.CUOTA:
                r.help_text = (
                    "Se completa solo al marcar cuota(s): «PAGO DE CUOTA 18» o «PAGO DE CUOTA 18-19». "
                    "Puede editarlo si necesita otra referencia (transferencia, depósito, etc.)."
                )
            else:
                r.help_text = (
                    "Opcional: número de transferencia, depósito, cheque u otra referencia bancaria."
                )

        vch = self.fields.get("voucher_transferencia")
        if vch:
            vch.label = "Subir voucher PDF de la transferencia"
            vch.help_text = (
                "Obligatorio: el asesor de ventas debe subir el comprobante PDF de la transferencia "
                "o depósito bancario."
            )
            vch.widget = forms.ClearableFileInput(
                attrs={
                    "accept": ".pdf,application/pdf",
                    "class": "input pago-voucher-file",
                }
            )
            # En alta de reserva/prima se exige; en edición si ya hay archivo, no.
            concepto_ini = self._concepto_fijo or ""
            if not concepto_ini:
                if self.is_bound:
                    concepto_ini = (self.data.get("concepto") or "").strip().upper()
                elif self.initial.get("concepto"):
                    concepto_ini = str(self.initial.get("concepto")).strip().upper()
                elif getattr(self.instance, "concepto", None):
                    concepto_ini = self.instance.concepto
            if concepto_ini in {
                Pago.Concepto.RESERVA,
                Pago.Concepto.PRIMA,
                Pago.Concepto.CONTADO,
            }:
                tiene_archivo = bool(
                    getattr(self.instance, "pk", None)
                    and getattr(self.instance, "voucher_transferencia", None)
                    and self.instance.voucher_transferencia.name
                )
                vch.required = not tiene_archivo
            else:
                vch.required = False

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
                from django.utils import timezone as dj_tz

                from inmobiliaria.recargo_administrativo import (
                    contar_eventos_recargo,
                    cuota_genera_recargo,
                    parametro_recargo_activo,
                )

                param_recargo = parametro_recargo_activo()
                dias_gracia_r = int(param_recargo.dias_gracia) if param_recargo else 0
                unitario_r = (
                    (param_recargo.monto_recargo or Decimal("0"))
                    if param_recargo
                    else Decimal("0")
                )
                hoy_r = dj_tz.localdate()
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
                    queryset=CuotaProgramada.objects.select_related("pago")
                    .prefetch_related("pago__cuotas_aplicadas")
                    .order_by("numero", "id"),
                    to_attr="_todas_cuotas_pref",
                )
                for c in Contrato.objects.filter(pk__in=pks).prefetch_related(pref, pref_all):
                    from inmobiliaria.pago_desglose import desglose_aplicado_por_cuota

                    todas = getattr(c, "_todas_cuotas_pref", [])
                    todas_payload = []
                    for x in todas:
                        dg = desglose_aplicado_por_cuota(x)
                        fecha_pago = ""
                        if x.pago_id and x.pago is not None and x.pago.fecha:
                            fecha_pago = x.pago.fecha.isoformat()
                        elif x.pagado_en:
                            fecha_pago = x.pagado_en.isoformat()
                        todas_payload.append(
                            {
                                "id": x.id,
                                "n": x.numero,
                                "v": x.vence_en.isoformat(),
                                "fp": fecha_pago,
                                "m": str(x.monto.quantize(Decimal("0.01"))),
                                "e": x.estado,
                                "abierta": x.pago_id is None
                                and x.estado
                                in (
                                    CuotaProgramada.Estado.PENDIENTE,
                                    CuotaProgramada.Estado.VENCIDA,
                                ),
                                "rg": cuota_genera_recargo(
                                    x, hoy=hoy_r, dias_gracia=dias_gracia_r
                                ),
                                "rec": str(dg["recargo"]),
                                "cap": str(dg["capital"]),
                                "tot": (
                                    str(dg["total_pago"])
                                    if dg["total_pago"] is not None
                                    else ""
                                ),
                                "ult": bool(dg["es_ultima_del_pago"]),
                            }
                        )
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
                    n_recargos, monto_recargos, _, _gens = contar_eventos_recargo(
                        c,
                        fecha=hoy_r,
                        cuotas_a_liquidar=[first] if first else None,
                    )
                    total_mes = (
                        (first.monto + monto_recargos).quantize(Decimal("0.01"))
                        if first
                        else monto_recargos
                    )
                    nota_r = ""
                    if n_recargos and first:
                        nota_r = (
                            f"Cuota #{first.numero} (${first.monto.quantize(Decimal('0.01'))}) "
                            f"+ {n_recargos} recargo(s) administrativo(s) (${monto_recargos}) "
                            f"= ${total_mes}"
                        )
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
                        "recargo_monto": str(monto_recargos),
                        "recargo_cantidad": str(n_recargos),
                        "recargo_total_mes": str(total_mes) if first else "",
                        "recargo_nota": nota_r,
                        "recargo_unitario": str(unitario_r.quantize(Decimal("0.01"))),
                        "dias_gracia": str(dias_gracia_r),
                    }
            ct.widget = ContratoPagoSelect(catalog=catalog)
            ct.widget.choices = ct.choices

        fa = self.fields.get("formato_aceptacion")
        if fa:
            fa.required = False
            fa.label = "Formato de aceptación guardado"
            fa.help_text = (
                "Elija el formato guardado. No necesita crear un plan de pagos antes: "
                "al guardar reserva o prima el sistema vincula solo el lote del formato."
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
                        "valor_lote": (
                            str(f.valor_inmueble.quantize(Decimal("0.01")))
                            if f.valor_inmueble is not None
                            else base.get("valor_lote", "")
                        ),
                        "tipo_financiamiento": getattr(f, "tipo_financiamiento", "")
                        or "",
                    }
                )
                formato_catalog[str(f.pk)] = base
                if f.contrato_id:
                    fmt_labels[f.pk] = (
                        f"Nº {fmt_num} — {fnom} — {f.contrato.numero}"
                    )
                elif res_ct:
                    fmt_labels[f.pk] = (
                        f"Nº {fmt_num} — {fnom} — {res_ct.numero}"
                    )
                else:
                    fmt_labels[f.pk] = (
                        f"Nº {fmt_num} — {fnom} (al guardar reserva/prima se vincula el lote)"
                    )
            fa.widget = FormatoPagoSelect(catalog=formato_catalog)
            fa.widget.choices = fa.choices
            fa.label_from_instance = lambda o: fmt_labels.get(o.pk, str(o))

        if not self.is_bound and not getattr(self.instance, "pk", None):
            if not self.initial.get("fecha"):
                from django.utils import timezone as dj_tz

                self.fields["fecha"].initial = dj_tz.localdate()

    def clean(self):
        cleaned_data = super().clean()
        # Campo disabled no llega en POST: restaurar concepto del flujo.
        if self._concepto_fijo:
            cleaned_data["concepto"] = self._concepto_fijo
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
            concepto_flujo = cleaned_data.get("concepto") or self._concepto_fijo
            # Contado / reserva / prima: crear contrato automático si el formato aún no tiene.
            if (
                concepto_flujo
                in {
                    Pago.Concepto.CONTADO,
                    Pago.Concepto.RESERVA,
                    Pago.Concepto.PRIMA,
                }
                and not cleaned_data.get("contrato")
            ):
                if concepto_flujo == Pago.Concepto.CONTADO:
                    from inmobiliaria.credito_contrato import (
                        asegurar_contrato_contado_desde_formato,
                    )

                    c_auto = asegurar_contrato_contado_desde_formato(formato)
                else:
                    from inmobiliaria.credito_contrato import (
                        asegurar_contrato_reserva_prima_desde_formato,
                    )

                    c_auto = asegurar_contrato_reserva_prima_desde_formato(formato)
                if c_auto:
                    from inmobiliaria.validacion_gerencia import (
                        aplicar_validacion_formato_o_plan,
                    )

                    if self._pago_user and aplicar_validacion_formato_o_plan(
                        c_auto, self._pago_user
                    ):
                        c_auto.save(
                            update_fields=[
                                "validacion_gerencia",
                                "validado_gerencia_por",
                                "validado_gerencia_en",
                                "validacion_gerencia_nota",
                                "estado",
                            ]
                        )
                    cleaned_data["contrato"] = c_auto
        if (
            self.ocultar_contrato
            and not getattr(self.instance, "pk", None)
            and cleaned_data.get("formato_aceptacion")
            and not cleaned_data.get("contrato")
        ):
            concepto_err = cleaned_data.get("concepto") or self._concepto_fijo
            if concepto_err == Pago.Concepto.CONTADO:
                raise ValidationError(
                    {
                        "formato_aceptacion": (
                            "No se pudo armar la venta de contado: revise que el formato tenga "
                            "lote, proyecto y valor del inmueble, y que el lote exista en inventario."
                        )
                    }
                )
            if concepto_err in {Pago.Concepto.RESERVA, Pago.Concepto.PRIMA}:
                raise ValidationError(
                    {
                        "formato_aceptacion": (
                            "No se pudo crear el contrato desde este formato. "
                            "Revise que el lote exista y no esté vendido, y que proyecto y valor del inmueble estén completos. "
                            "El PDF del voucher sí se recibió; el bloqueo es el lote/contrato, no el archivo."
                        )
                    }
                )
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

        from inmobiliaria.vendedor_acceso import es_vendedor_restringido

        if (
            concepto == Pago.Concepto.CUOTA
            and self._pago_user is not None
            and es_vendedor_restringido(self._pago_user)
        ):
            raise ValidationError(
                "Los recibos a plazos (cuotas) solo los registra gerencia o administrador."
            )

        if (
            concepto
            in {
                Pago.Concepto.RESERVA,
                Pago.Concepto.PRIMA,
                Pago.Concepto.CONTADO,
            }
            and contrato is not None
            and getattr(contrato, "inmueble_id", None)
        ):
            inv = (
                Inmueble.objects.select_related("cliente_reserva")
                .filter(pk=contrato.inmueble_id)
                .first()
            )
            cli = getattr(contrato, "cliente", None)
            # Mismo cliente con su reserva: OK. Vendido / reserva ajena / bloqueado: no.
            alerta = mensaje_alerta_lote_ocupado(
                inv, cliente=cli, permitir_misma_reserva=True
            )
            if alerta:
                self.add_error("formato_aceptacion", alerta)

        if concepto in {
            Pago.Concepto.RESERVA,
            Pago.Concepto.PRIMA,
            Pago.Concepto.CONTADO,
        }:
            archivo = cleaned_data.get("voucher_transferencia")
            existente = (
                getattr(self.instance, "voucher_transferencia", None)
                if getattr(self.instance, "pk", None)
                else None
            )
            if not archivo and not (existente and existente.name):
                self.add_error(
                    "voucher_transferencia",
                    "El asesor de ventas debe subir el voucher PDF de la transferencia. Es obligatorio.",
                )
            elif archivo is not None:
                name = (getattr(archivo, "name", "") or "").lower()
                if name and not name.endswith(".pdf"):
                    self.add_error(
                        "voucher_transferencia",
                        "El voucher debe ser un archivo PDF.",
                    )

        if concepto == Pago.Concepto.CONTADO:
            cleaned_data["cuotas_incluidas"] = 1
            cleaned_data["cuotas_seleccionadas"] = ""
            cleaned_data["monto_recargo_incluido"] = Decimal("0.00")
            # Sugerir monto = valor del lote del formato si el usuario dejó vacío o cero.
            monto = cleaned_data.get("monto")
            if formato and (monto is None or monto <= 0):
                valor = formato.valor_inmueble
                if valor is None and contrato is not None:
                    valor = contrato.precio_final
                if valor is not None and valor > 0:
                    cleaned_data["monto"] = Decimal(valor).quantize(Decimal("0.01"))
            return cleaned_data

        if concepto != Pago.Concepto.CUOTA:
            cleaned_data["cuotas_incluidas"] = 1
            cleaned_data["cuotas_seleccionadas"] = ""
            cleaned_data["monto_recargo_incluido"] = Decimal("0.00")
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
                recargo_exist = Decimal(
                    getattr(self.instance, "monto_recargo_incluido", 0) or 0
                ).quantize(Decimal("0.01"))
                minimo = (esperado + recargo_exist).quantize(Decimal("0.01"))
                cleaned_data["monto_recargo_incluido"] = recargo_exist
                if monto_q is not None and monto_q < minimo:
                    nums = ", ".join(str(c.numero) for c in vinculadas)
                    raise ValidationError(
                        {
                            "monto": (
                                f"El monto no puede ser menor a ${minimo} "
                                f"(suma de las cuotas vinculadas: n.º {nums}"
                                + (
                                    f" + recargo ${recargo_exist}"
                                    if recargo_exist > 0
                                    else ""
                                )
                                + "). "
                                "Si abona de más, ese excedente va a capital en el mismo recibo."
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
        from inmobiliaria.recargo_administrativo import monto_recargo_para_liquidacion

        fecha_pago = cleaned_data.get("fecha")
        monto_recargo = monto_recargo_para_liquidacion(
            contrato,
            fecha=fecha_pago,
            cuotas_a_liquidar=pend,
            excluir_pago_id=getattr(self.instance, "pk", None),
        )
        minimo = (esperado + monto_recargo).quantize(Decimal("0.01"))
        cleaned_data["monto_recargo_incluido"] = monto_recargo
        if monto_q is not None and monto_q < minimo:
            detalle_recargo = (
                f" + recargo administrativo ${monto_recargo}"
                if monto_recargo > 0
                else ""
            )
            raise ValidationError(
                {
                    "monto": (
                        f"Para {n} cuota(s) el monto mínimo es ${minimo} "
                        f"(cuotas n.º {pend[0].numero} al {pend[-1].numero}: ${esperado}"
                        f"{detalle_recargo}). "
                        "Si esta cuota viene atrasada, el recargo se cobra en la siguiente. "
                        "Si el cliente abona de más, el excedente va a capital en el mismo recibo."
                    )
                }
            )

        # Referencia automática según cuota(s) marcada(s).
        ref_actual = (cleaned_data.get("referencia") or "").strip()
        ref_auto = (
            f"PAGO DE CUOTA {pend[0].numero}"
            if len(pend) == 1
            else f"PAGO DE CUOTA {pend[0].numero}-{pend[-1].numero}"
        )
        if not ref_actual or re.fullmatch(
            r"PAGO DE CUOTA\s+\d+(-\d+)?", ref_actual, flags=re.IGNORECASE
        ):
            cleaned_data["referencia"] = ref_auto

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
        fields = ("nombre", "monto_recargo", "dias_gracia", "activo")
        labels = {
            "nombre": "Nombre de la política",
            "monto_recargo": "Monto del recargo administrativo ($)",
            "dias_gracia": "Días de gracia tras la fecha de pago",
            "activo": "Activo",
        }
        help_texts = {
            "monto_recargo": (
                "Cantidad fija que define la empresa. Si no pagan un mes "
                "(después de la gracia), al siguiente mes sale la cuota + este recargo."
            ),
            "dias_gracia": (
                "Días después del vencimiento de la cuota antes de que aplique el recargo. "
                "Ejemplo: vencimiento día 5, gracia 5 → aplica desde el día 11."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        m = self.fields.get("monto_recargo")
        if m:
            m.widget.attrs.setdefault("inputmode", "decimal")
            m.widget.attrs.setdefault("placeholder", "0.00")
        g = self.fields.get("dias_gracia")
        if g:
            g.widget.attrs.setdefault("min", "0")
            g.widget.attrs.setdefault("max", "90")


_FORMATO_ACEPTACION_EXCLUDE = (
    "id",
    "contrato",
    "creado_por",
    "creado_en",
    "actualizado_en",
    "firma_aceptante",
    "firma_vendedor",
    "firma_autorizado",
    "promesa_venta_escaneada",
    "contrato_compraventa_escaneado",
    "boucher_pago_reserva",
    "validacion_precio",
    "precio_solicitado_por",
    "precio_solicitado_en",
    "precio_validado_por",
    "precio_validado_en",
    "precio_validacion_nota",
    "validacion_gerencia",
    "validado_gerencia_por",
    "validado_gerencia_en",
    "validacion_gerencia_nota",
)
_FORMATO_ACEPTACION_FIELDS = [
    f.name
    for f in FormatoAceptacion._meta.fields
    if f.name not in _FORMATO_ACEPTACION_EXCLUDE
]

_FORMATO_ADJUNTOS_FIELDS = (
    "dui_cliente_archivo",
    "formato_aceptacion_fisico",
)

_ANOS_PLAZO_MAX = 6
_ANOS_PLAZO_CHOICES = [("", "— Años —")] + [
    (str(i), str(i)) for i in range(1, _ANOS_PLAZO_MAX + 1)
]
_INTERES_PCT_CHOICES = [("", "— % —")] + [(str(i), f"{i} %") for i in range(0, 51)]


def _formato_plazo_guardado_a_anos_select(val) -> str:
    """Alinea valores viejos (meses o texto) al select 1–6 años."""
    if val is None or str(val).strip() == "":
        return ""
    s = str(val).strip()
    if s.isdigit():
        n = int(s)
        if 1 <= n <= _ANOS_PLAZO_MAX:
            return str(n)
        if n > _ANOS_PLAZO_MAX and n % 12 == 0:
            y = n // 12
            if 1 <= y <= _ANOS_PLAZO_MAX:
                return str(y)
        return ""
    m = re.search(r"(\d+)", s)
    if not m:
        return ""
    n = int(m.group(1))
    low = s.lower()
    if "mes" in low or (n > _ANOS_PLAZO_MAX and n % 12 == 0):
        y = n // 12
        if 1 <= y <= _ANOS_PLAZO_MAX:
            return str(y)
    if 1 <= n <= _ANOS_PLAZO_MAX:
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
        if 1 <= y <= _ANOS_PLAZO_MAX and not (instance.plazo_txt or "").strip():
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
    """Todos los vendedores del catálogo (activos primero) para «Elaborado por»."""
    opts: list[tuple[str, str]] = [("", "— Seleccione vendedor —")]
    seen_lower: set[str] = set()
    qs = Vendedor.objects.all().order_by("-activo", "apellidos", "nombres", "id")
    for v in qs:
        n = v.nombre_completo.strip()
        if not n:
            continue
        k = n.casefold()
        if k in seen_lower:
            continue
        seen_lower.add(k)
        pct = v.porcentaje_comision_default
        pct_txt = f"{pct:g}%" if pct is not None else "sin %"
        estado = "" if v.activo else " · inactivo"
        label = f"{n} — comisión {pct_txt}{estado}"
        opts.append((n, label))
    return opts


class FormatoAceptacionForm(forms.ModelForm):
    """Formato de aceptación; adjuntos (DUI y formato físico) se suben como archivos."""

    correo_cliente = forms.EmailField(
        label="Correo electrónico del cliente",
        required=False,
        widget=forms.EmailInput(
            attrs={
                "class": "input",
                "placeholder": "cliente@correo.com",
                "autocomplete": "email",
                "inputmode": "email",
            }
        ),
        help_text="Opcional. Se guarda en el cliente para enviar el PDF por correo (Brevo).",
    )

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
            "dui_cliente_archivo": forms.ClearableFileInput(
                attrs={
                    "class": "input formato-adjunto-input",
                    "accept": ".pdf,application/pdf",
                }
            ),
            "formato_aceptacion_fisico": forms.ClearableFileInput(
                attrs={
                    "class": "input formato-adjunto-input",
                    "accept": ".pdf,application/pdf",
                }
            ),
            "tipo_financiamiento": forms.Select(attrs={"class": "input"}),
            "numero_formulario": forms.NumberInput(
                attrs={
                    "class": "input formato-numero-input",
                    "min": "1",
                    "step": "1",
                    "inputmode": "numeric",
                    "placeholder": "Ej. 42",
                    "required": True,
                }
            ),
            "telefono_domicilio": forms.TextInput(
                attrs={
                    "class": "input input--tel-intl",
                    "placeholder": "+503 7012 3456 · +52 55 1234 5678",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "title": "Cualquier país: use + y código (ej. +503, +52, +1). Sin + se asume El Salvador.",
                    "data-tel-intl": "1",
                }
            ),
            "telefono_notificacion": forms.TextInput(
                attrs={
                    "class": "input input--tel-intl",
                    "placeholder": "+503 7012 3456 · +52 55 1234 5678",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "title": "Cualquier país: use + y código (ej. +503, +52, +1). Sin + se asume El Salvador.",
                    "data-tel-intl": "1",
                }
            ),
            "telefono_trabajo": forms.TextInput(
                attrs={
                    "class": "input input--tel-intl",
                    "placeholder": "+503 7012 3456 · +52 55 1234 5678",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "title": "Cualquier país: use + y código (ej. +503, +52, +1). Sin + se asume El Salvador.",
                    "data-tel-intl": "1",
                }
            ),
            "ref_com_tel_1": forms.TextInput(
                attrs={
                    "class": "input input--tel-intl",
                    "placeholder": "+503 … o +código país",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "data-tel-intl": "1",
                }
            ),
            "ref_com_tel_2": forms.TextInput(
                attrs={
                    "class": "input input--tel-intl",
                    "placeholder": "+503 … o +código país",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "data-tel-intl": "1",
                }
            ),
            "ref_com_tel_3": forms.TextInput(
                attrs={
                    "class": "input input--tel-intl",
                    "placeholder": "+503 … o +código país",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "data-tel-intl": "1",
                }
            ),
            "ref_per_tel_1": forms.TextInput(
                attrs={
                    "class": "input input--tel-intl",
                    "placeholder": "+503 … o +código país",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "data-tel-intl": "1",
                }
            ),
            "ref_per_tel_2": forms.TextInput(
                attrs={
                    "class": "input input--tel-intl",
                    "placeholder": "+503 … o +código país",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "data-tel-intl": "1",
                }
            ),
            "ref_per_tel_3": forms.TextInput(
                attrs={
                    "class": "input input--tel-intl",
                    "placeholder": "+503 … o +código país",
                    "maxlength": 40,
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "data-tel-intl": "1",
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
        num_f = self.fields.get("numero_formulario")
        if num_f:
            num_f.required = True
            num_f.label = "Nº formulario"
            num_f.help_text = (
                "Ingrese el número impreso del formato. Debe coincidir con el del PDF físico."
            )
            num_f.min_value = 1
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
            plazo_f.help_text = (
                f"Máximo {_ANOS_PLAZO_MAX} años. "
                "Meses 1–12 sin interés; desde el mes 13 aplica el interés."
            )

        inter_f = self.fields.get("interes_txt")
        if inter_f:
            inter_f.widget = forms.Select(
                choices=_INTERES_PCT_CHOICES,
                attrs={"class": "input"},
            )
            inter_f.required = False
        inter_f.help_text = (
            "Interés anual que se aplica desde el mes 13. "
            "Los meses 1–12 van sin interés con la cuota que escribe el asesor de ventas."
        )

        letra_f = self.fields.get("letra_mensual")
        if letra_f:
            letra_f.label = "Cuota meses 1–12 (sin interés)"
            letra_f.help_text = (
                "La escribe el asesor de ventas. Ese monto se aplica en los meses 1–12 sin interés. "
                "Desde el mes 13 el sistema suma el interés."
            )

        # Reserva primero, luego prima (mismos campos en BD: prima_1 / prima_2)
        if "prima_1" in self.fields:
            self.fields["prima_1"].label = "Reserva $"
            self.fields["prima_1"].help_text = (
                "Se calcula con el % de reserva del proyecto sobre el valor del lote. "
                "Puede corregirla si hace falta."
            )
        if "prima_1_fecha" in self.fields:
            self.fields["prima_1_fecha"].label = "Fecha de pago de reserva"
        if "prima_2" in self.fields:
            self.fields["prima_2"].label = "Prima a pagar $"
            self.fields["prima_2"].help_text = (
                "Se calcula: (valor × % prima) − reserva. "
                "Puede corregirla si hace falta."
            )
        if "prima_2_fecha" in self.fields:
            self.fields["prima_2_fecha"].label = "Fecha de pago de prima"

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
            ncuota_f.help_text = "Se calcula solo: años × 12."

        for fname in _FORMATO_TELEFONO_FIELDS:
            tf = self.fields.get(fname)
            if tf:
                aplicar_attrs_telefono(tf)

        # Montos con formato 22,500.00
        for fname in (
            "sueldo",
            "valor_inmueble",
            "valor_inmueble_sistema",
            "valor_inmueble_solicitado",
            "prima_1",
            "prima_2",
            "valor_financiamiento",
            "letra_mensual",
        ):
            old = self.fields.get(fname)
            if not old:
                continue
            self.fields[fname] = MontoDecimalFormField(
                label=old.label,
                help_text=getattr(old, "help_text", "") or "",
                max_digits=14,
                decimal_places=2,
                required=False if fname in (
                    "valor_inmueble_sistema",
                    "valor_inmueble_solicitado",
                ) else old.required,
                mostrar_simbolo=True,
            )
            if fname == "letra_mensual":
                self.fields[fname].label = "Cuota meses 1–12 (sin interés)"
                self.fields[fname].help_text = (
                    "La escribe el asesor de ventas. Meses 1–12 sin interés; desde el mes 13 ya va con intereses."
                )
            if fname == "valor_financiamiento":
                self.fields[fname].help_text = (
                    "Se calcula automáticamente: valor del inmueble − reserva − prima a pagar."
                )

        sis = self.fields.get("valor_inmueble_sistema")
        if sis:
            sis.widget.attrs["readonly"] = True
            sis.required = False
        etapa_f = self.fields.get("etapa_venta_aplicada")
        if etapa_f:
            etapa_f.widget = forms.HiddenInput()
            etapa_f.required = False
        vin = self.fields.get("valor_inmueble")
        if vin:
            vin.widget.attrs["readonly"] = True
            vin.help_text = (
                "Precio de venta de la etapa actual (Preventa / Promocional / Pos). "
                "El Precio lista es solo referencia. "
                "Para otro monto use «Valor solicitado» + motivo (requiere gerencia)."
            )
        sol = self.fields.get("valor_inmueble_solicitado")
        if sol:
            sol.required = False
            sol.help_text = "Opcional. Si indica un monto distinto, gerencia debe aprobarlo."
        vf = self.fields.get("valor_financiamiento")
        if vf:
            vf.widget.attrs["readonly"] = True
        mot = self.fields.get("precio_solicitud_motivo")
        if mot:
            mot.required = False
            mot.widget.attrs.setdefault("class", "input")
            mot.widget.attrs["placeholder"] = (
                "Motivo del cambio (obligatorio si solicita otro monto)"
            )

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
            tiene_vendedores = any(c[0] for c in choices)
            self.fields["elaborado_por"] = forms.ChoiceField(
                label=lbl,
                required=tiene_vendedores,
                choices=choices,
                widget=forms.Select(attrs={"class": "input"}),
                help_text=(
                    "Lista de todos los asesores de ventas registrados (con su % de comisión). "
                    "Elija quién elaboró el formato; ese mismo asesor de ventas cobrará la comisión "
                    "cuando el cliente tenga reserva y prima pagadas y validadas."
                    if tiene_vendedores
                    else "No hay asesores de ventas en el catálogo. Regístrelos en Asesores de ventas (registro) primero."
                ),
                error_messages={
                    "required": "Seleccione el asesor de ventas que elaboró este formato.",
                },
            )

        if not formato_aceptacion_credito_extra_columns_ready():
            for fname in FORMATO_CREDITO_EXTRA_FIELDS:
                self.fields.pop(fname, None)
        if not formato_aceptacion_tipo_financiamiento_column_ready():
            self.fields.pop(FORMATO_TIPO_FINANCIAMIENTO_FIELD, None)
        if not formato_aceptacion_adjuntos_columns_ready():
            for fname in _FORMATO_ADJUNTOS_FIELDS:
                self.fields.pop(fname, None)

        if "correo_cliente" in self.fields and not self.is_bound:
            correo_ini = ""
            inst = self.instance
            if inst is not None and getattr(inst, "contrato_id", None):
                c = getattr(inst, "contrato", None)
                if c is None:
                    c = (
                        Contrato.objects.filter(pk=inst.contrato_id)
                        .select_related("cliente")
                        .first()
                    )
                if c and c.cliente_id:
                    correo_ini = (c.cliente.email or "").strip()
            if not correo_ini and inst is not None and getattr(inst, "pk", None):
                from inmobiliaria.credito_contrato import _norm_dui, _norm_nombre
                from inmobiliaria.models import Cliente

                dui = _norm_dui(getattr(inst, "dui_numero", ""))
                if dui:
                    for cli in Cliente.objects.exclude(email="").only("dui", "email")[:300]:
                        if _norm_dui(cli.dui) == dui:
                            correo_ini = (cli.email or "").strip()
                            break
                if not correo_ini:
                    nom = _norm_nombre(getattr(inst, "nombre_cliente", ""))
                    if nom:
                        for cli in Cliente.objects.exclude(email="").only(
                            "nombres", "apellidos", "email"
                        )[:300]:
                            cn = _norm_nombre(
                                f"{cli.nombres or ''} {cli.apellidos or ''}"
                            )
                            if cn == nom:
                                correo_ini = (cli.email or "").strip()
                                break
            if correo_ini:
                self.initial["correo_cliente"] = correo_ini

    def clean_numero_formulario(self):
        num = self.cleaned_data.get("numero_formulario")
        if num is None:
            raise ValidationError("Indique el número del formato de aceptación.")
        try:
            num = int(num)
        except (TypeError, ValueError):
            raise ValidationError("El número del formato debe ser un entero positivo.")
        if num < 1:
            raise ValidationError("El número del formato debe ser mayor que cero.")
        qs = FormatoAceptacion.objects.filter(numero_formulario=num)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(
                f"Ya existe un formato con el número {num:04d}. Use otro número."
            )
        return num

    def clean(self):
        cleaned = super().clean()
        plazo_raw = (cleaned.get("plazo_txt") or "").strip()
        if plazo_raw.isdigit():
            y = int(plazo_raw)
            if y < 1 or y > _ANOS_PLAZO_MAX:
                self.add_error(
                    "plazo_txt",
                    f"El plazo a plazos debe ser entre 1 y {_ANOS_PLAZO_MAX} años.",
                )
            else:
                cleaned["num_cuota_txt"] = str(y * 12)
        for fname in _FORMATO_TELEFONO_FIELDS:
            v = cleaned.get(fname)
            if v is not None and str(v).strip():
                try:
                    cleaned[fname] = limpiar_telefono_formulario(v)
                except ValidationError as e:
                    self.add_error(fname, e)
        tipo = (cleaned.get("tipo_financiamiento") or "").strip()
        if tipo == FormatoAceptacion.TipoFinanciamiento.CONTADO:
            cleaned["valor_financiamiento"] = Decimal("0")
            cleaned["letra_mensual"] = None
            cleaned["plazo_txt"] = ""
            cleaned["num_cuota_txt"] = ""
            cleaned["interes_txt"] = ""
        elif tipo == FormatoAceptacion.TipoFinanciamiento.A_PLAZOS or not tipo:
            letra = cleaned.get("letra_mensual")
            n_raw = (cleaned.get("num_cuota_txt") or "").strip()
            if n_raw.isdigit() and int(n_raw) > 0 and (letra is None or letra <= 0):
                self.add_error(
                    "letra_mensual",
                    "Escriba la cuota de los meses 1–12 (sin interés). El asesor de ventas la define; "
                    "desde el mes 13 el sistema le suma el interés.",
                )

        num = cleaned.get("numero_formulario")
        fisico = cleaned.get("formato_aceptacion_fisico")
        from django.core.files.uploadedfile import UploadedFile

        from .formato_numero_pdf import (
            archivo_es_pdf,
            pdf_contiene_numero_formulario,
        )

        # Solo validar contra un PDF recién subido (o el existente si es PDF y cambió el número).
        archivo_a_validar = None
        if isinstance(fisico, UploadedFile):
            if not archivo_es_pdf(fisico.name, getattr(fisico, "content_type", None)):
                self.add_error(
                    "formato_aceptacion_fisico",
                    "Para validar el número del formato, suba el archivo en PDF. "
                    "El Nº ingresado arriba debe aparecer en ese PDF.",
                )
            else:
                archivo_a_validar = fisico
        elif (
            num is not None
            and self.instance
            and getattr(self.instance, "pk", None)
            and "numero_formulario" in self.changed_data
        ):
            existing = getattr(self.instance, "formato_aceptacion_fisico", None)
            if existing and existing.name and archivo_es_pdf(existing.name):
                archivo_a_validar = existing

        if num is not None and archivo_a_validar is not None:
            ok, msg = pdf_contiene_numero_formulario(archivo_a_validar, int(num))
            if not ok:
                self.add_error("formato_aceptacion_fisico", msg)
                self.add_error(
                    "numero_formulario",
                    "No coincide con el número del PDF del formato físico.",
                )

        # Alerta / bloqueo: lote ya reservado, vendido o bloqueado.
        num_lote = (cleaned.get("num_lote") or "").strip()
        if num_lote:
            from inmobiliaria.credito_contrato import resolver_inmueble_desde_formato

            # Construir un stub mínimo con los campos que usa el resolver.
            class _FmtStub:
                pass

            stub = _FmtStub()
            stub.num_lote = num_lote
            stub.nombre_proyecto = (cleaned.get("nombre_proyecto") or "").strip()
            stub.poligono_txt = (cleaned.get("poligono_txt") or "").strip()
            inv = resolver_inmueble_desde_formato(stub)
            # Si el resolver excluyó VENDIDO, buscar también vendidos para el mensaje.
            if inv is None and num_lote:
                from inmobiliaria.lote_codigo import resolver_inmueble_por_codigo_lote

                inv = resolver_inmueble_por_codigo_lote(
                    num_lote=num_lote,
                    proyecto_nombre=stub.nombre_proyecto,
                    poligono_txt=(cleaned.get("poligono_txt") or "").strip(),
                )
            mismo_lote_edit = False
            if (
                inv is not None
                and self.instance
                and getattr(self.instance, "pk", None)
            ):
                from inmobiliaria.lote_codigo import codigos_lote_equivalentes

                prev = (self.instance.num_lote or "").strip()
                letra = ""
                if inv.poligono_id:
                    letra = inv.poligono.letra_codigo
                mismo_lote_edit = codigos_lote_equivalentes(prev, num_lote, letra)
                if not mismo_lote_edit:
                    prev_inv = resolver_inmueble_desde_formato(self.instance)
                    mismo_lote_edit = bool(prev_inv and prev_inv.pk == inv.pk)
            if inv is not None and not mismo_lote_edit:
                alerta = mensaje_alerta_lote_ocupado(inv, permitir_misma_reserva=False)
                if alerta:
                    self.add_error("num_lote", alerta)

        # Reserva / prima del proyecto (ambos % del valor del lote):
        # reserva = valor × % reserva; prima_total = valor × % prima;
        # prima_a_pagar = prima_total − reserva.
        proy_nombre = (cleaned.get("nombre_proyecto") or "").strip()
        if proy_nombre:
            proy = (
                Proyecto.objects.filter(nombre__iexact=proy_nombre, activo=True).first()
                or Proyecto.objects.filter(
                    nombre__icontains=proy_nombre, activo=True
                ).first()
            )
        else:
            proy = None

        valor = cleaned.get("valor_inmueble")
        if valor is None:
            valor = cleaned.get("valor_inmueble_sistema")

        if proy is not None and valor is not None:
            valor_d = Decimal(valor)
            if proy.porcentaje_reserva is not None and cleaned.get("prima_1") is None:
                cleaned["prima_1"] = (
                    valor_d * Decimal(proy.porcentaje_reserva) / Decimal("100")
                ).quantize(Decimal("0.01"))

            reserva = cleaned.get("prima_1")
            if proy.porcentaje_prima is not None and reserva is not None:
                prima_total = (
                    valor_d * Decimal(proy.porcentaje_prima) / Decimal("100")
                ).quantize(Decimal("0.01"))
                restante = (prima_total - Decimal(reserva)).quantize(Decimal("0.01"))
                if restante < 0:
                    self.add_error(
                        "prima_1",
                        "La reserva no puede superar la prima total "
                        f"({proy.porcentaje_prima}% del lote = ${prima_total}).",
                    )
                else:
                    cleaned["prima_2"] = restante

        # Cambio de precio: si piden otro monto, exige motivo.
        from inmobiliaria.etapa_venta import decimales_iguales

        sistema = cleaned.get("valor_inmueble_sistema")
        solicitado = cleaned.get("valor_inmueble_solicitado")
        motivo = (cleaned.get("precio_solicitud_motivo") or "").strip()
        if solicitado is not None and sistema is not None:
            if not decimales_iguales(solicitado, sistema) and not motivo:
                self.add_error(
                    "precio_solicitud_motivo",
                    "Indique el motivo del cambio de precio para que gerencia lo revise.",
                )
        elif solicitado is not None and sistema is None and not motivo:
            self.add_error(
                "precio_solicitud_motivo",
                "Indique el motivo del cambio de precio.",
            )

        # El valor vigente del documento: conservar decisión de gerencia salvo nueva solicitud.
        nueva_solicitud = (
            solicitado is not None
            and sistema is not None
            and not decimales_iguales(solicitado, sistema)
            and motivo
        ) or (solicitado is not None and sistema is None and motivo)
        if (
            self.instance
            and self.instance.pk
            and self.instance.validacion_precio
            in (
                FormatoAceptacion.ValidacionPrecio.APROBADO,
                FormatoAceptacion.ValidacionPrecio.RECHAZADO,
            )
            and self.instance.valor_inmueble is not None
            and not nueva_solicitud
        ):
            cleaned["valor_inmueble"] = self.instance.valor_inmueble
        elif sistema is not None:
            cleaned["valor_inmueble"] = sistema

        return cleaned

    def save(self, commit=True):
        from django.utils import timezone
        from inmobiliaria.etapa_venta import decimales_iguales
        from usuarios.roles import puede_aprobar_precio_formato

        instance = super().save(commit=False)
        _aplicar_elaborado_por_desde_vendedor(instance, getattr(self, "_formato_user", None))
        user = getattr(self, "_formato_user", None)

        sistema = instance.valor_inmueble_sistema
        solicitado = instance.valor_inmueble_solicitado
        motivo = (instance.precio_solicitud_motivo or "").strip()

        pide_cambio = (
            solicitado is not None
            and sistema is not None
            and not decimales_iguales(solicitado, sistema)
        ) or (solicitado is not None and sistema is None)

        if pide_cambio and motivo:
            if user and puede_aprobar_precio_formato(user):
                instance.valor_inmueble = solicitado
                instance.validacion_precio = FormatoAceptacion.ValidacionPrecio.APROBADO
                instance.precio_validado_por = user
                instance.precio_validado_en = timezone.localtime()
                instance.precio_validacion_nota = motivo or "Aplicado por gerencia/admin"
                instance.precio_solicitado_por = user
                instance.precio_solicitado_en = timezone.localtime()
            else:
                if sistema is not None:
                    instance.valor_inmueble = sistema
                instance.validacion_precio = FormatoAceptacion.ValidacionPrecio.PENDIENTE
                instance.precio_solicitado_por = user if user and user.is_authenticated else None
                instance.precio_solicitado_en = timezone.localtime()
                instance.precio_validado_por = None
                instance.precio_validado_en = None
                instance.precio_validacion_nota = ""
        elif instance.validacion_precio in (
            FormatoAceptacion.ValidacionPrecio.APROBADO,
            FormatoAceptacion.ValidacionPrecio.RECHAZADO,
        ):
            # Conservar precio y trazabilidad ya definidos por gerencia.
            pass
        elif instance.validacion_precio == FormatoAceptacion.ValidacionPrecio.PENDIENTE:
            if sistema is not None:
                instance.valor_inmueble = sistema
        else:
            if sistema is not None:
                instance.valor_inmueble = sistema
            instance.valor_inmueble_solicitado = None
            instance.precio_solicitud_motivo = ""
            instance.precio_validado_por = None
            instance.precio_validado_en = None
            instance.precio_validacion_nota = ""
            instance.precio_solicitado_por = None
            instance.precio_solicitado_en = None
            instance.validacion_precio = FormatoAceptacion.ValidacionPrecio.NO_APLICA

        if formato_aceptacion_credito_extra_columns_ready():
            _aplicar_pistas_observaciones_financiamiento(instance)
        plazo_sync = (instance.plazo_txt or "").strip()
        if plazo_sync.isdigit():
            y = int(plazo_sync)
            if 1 <= y <= _ANOS_PLAZO_MAX:
                instance.num_cuota_txt = str(y * 12)
        if instance.tipo_financiamiento != FormatoAceptacion.TipoFinanciamiento.CONTADO:
            if instance.valor_inmueble is not None:
                p1s = instance.prima_1 or Decimal("0")
                p2s = instance.prima_2 or Decimal("0")
                vf = (Decimal(instance.valor_inmueble) - p1s - p2s).quantize(Decimal("0.01"))
                instance.valor_financiamiento = max(Decimal("0"), vf)
        # Detalle automático del plan a plazos (para imprimir / PDF)
        if formato_aceptacion_credito_extra_columns_ready():
            from .cuotas_calendario import texto_plan_financiamiento_a_plazos

            plan = texto_plan_financiamiento_a_plazos(instance)
            if plan:
                obs = (instance.observaciones_financiamiento or "").strip()
                # Reemplaza bloque previo del sistema o lo antepone si está vacío
                marker = "Plan a plazos"
                if not obs:
                    instance.observaciones_financiamiento = plan
                elif obs.startswith(marker) or "meses 1–12 sin interés" in obs:
                    # Conservar notas del usuario después de la 1.ª línea del plan
                    resto = ""
                    if "\n" in obs:
                        resto = "\n".join(obs.splitlines()[1:]).strip()
                    instance.observaciones_financiamiento = (
                        plan + (f"\n{resto}" if resto else "")
                    )
                elif marker not in obs and "meses 1–12 sin interés" not in obs:
                    instance.observaciones_financiamiento = f"{plan}\n{obs}"
        if commit:
            instance.save()
            correo = (self.cleaned_data.get("correo_cliente") or "").strip()
            if correo:
                from inmobiliaria.credito_contrato import cliente_desde_formato_aceptacion

                cli = cliente_desde_formato_aceptacion(instance)
                if (cli.email or "").strip().casefold() != correo.casefold():
                    cli.email = correo[:254]
                    cli.save(update_fields=["email"])
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


class FormatoAceptacionCompraventaForm(forms.Form):
    contrato_compraventa_escaneado = forms.FileField(
        label="Contrato de compraventa (PDF o imagen)",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg"],
                message="Use PDF, JPG o PNG.",
            )
        ],
    )
