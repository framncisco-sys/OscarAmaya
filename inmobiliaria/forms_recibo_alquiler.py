"""Formularios del recibo de comisión — solo módulo de alquileres (independiente de ventas/contratos)."""



from __future__ import annotations



from decimal import Decimal



from django import forms

from django.core.validators import MinValueValidator



from .models import AsesorAlquiler, Inmueble





class ReciboComisionAlquilerForm(forms.Form):

    asesor_perfil = forms.ModelChoiceField(

        label="Asesor del catálogo de alquiler",

        queryset=AsesorAlquiler.objects.none(),

        required=False,

        empty_label="— Seleccione del catálogo —",

        help_text="Catálogo independiente de asesores de ventas de proyectos. Si lo elige, se completa el nombre automáticamente.",

    )

    vendedor_nombre = forms.CharField(

        label="Nombre en el recibo (si no usa catálogo)",

        max_length=120,

        required=False,

        help_text="Opcional si eligió asesor del catálogo de alquiler; use este campo solo para un nombre libre.",

    )

    monto_comision = forms.DecimalField(

        label="Monto de comisión (USD)",

        max_digits=14,

        decimal_places=2,

        min_value=Decimal("0.01"),

        validators=[MinValueValidator(Decimal("0.01"))],

        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),

        help_text="Importe a liquidar. Puede basarse en la renta mensual del inmueble en alquiler.",

    )

    comision_porcentaje = forms.DecimalField(

        label="Porcentaje de comisión (opcional)",

        max_digits=6,

        decimal_places=2,

        required=False,

        min_value=Decimal("0"),

        max_value=Decimal("100"),

        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0", "max": "100"}),

        help_text="Referencia en el PDF. Si lo cambia, ajuste el monto si corresponde.",

    )

    concepto = forms.CharField(

        label="Concepto en el recibo",

        required=False,

        widget=forms.Textarea(attrs={"rows": 3}),

        help_text="Descripción de la comisión por intermediación en el arrendamiento.",

    )



    def __init__(self, *args, inmueble: Inmueble | None = None, **kwargs):

        super().__init__(*args, **kwargs)

        self.inmueble = inmueble

        self.fields["asesor_perfil"].queryset = AsesorAlquiler.objects.filter(activo=True).order_by(

            "apellidos", "nombres"

        )

        if inmueble is not None and not self.is_bound:

            renta = renta_mensual_alquiler(inmueble)

            if renta is not None:

                self.fields["monto_comision"].initial = renta

            self.fields["concepto"].initial = concepto_comision_alquiler(inmueble)



    def clean(self):

        cleaned = super().clean()

        ap = cleaned.get("asesor_perfil")

        nombre = (cleaned.get("vendedor_nombre") or "").strip()

        if ap:

            cleaned["vendedor_nombre"] = nombre or ap.nombre_completo

        elif not nombre:

            raise forms.ValidationError(

                "Seleccione un asesor del catálogo de alquiler o escriba el nombre del beneficiario."

            )

        else:

            cleaned["vendedor_nombre"] = nombre

        return cleaned





def nombre_beneficiario_recibo_alquiler(cleaned_data: dict) -> str:

    ap = cleaned_data.get("asesor_perfil")

    nombre = (cleaned_data.get("vendedor_nombre") or "").strip()

    if ap:

        return nombre or ap.nombre_completo

    return nombre





def renta_mensual_alquiler(inmueble: Inmueble):

    if inmueble.tipo == Inmueble.Tipo.LOCAL and hasattr(inmueble, "detalle_local_alquiler"):

        return inmueble.detalle_local_alquiler.renta_mensual

    if inmueble.tipo in (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA) and hasattr(

        inmueble, "detalle_casa_alquiler"

    ):

        return inmueble.detalle_casa_alquiler.arrendamiento_mensual

    return None





def concepto_comision_alquiler(inmueble: Inmueble) -> str:

    tipo = inmueble.get_tipo_display().lower()

    return (

        f"Comisión por intermediación en el arrendamiento del {tipo} "

        f"{inmueble.codigo} — {inmueble.proyecto.nombre}."

    )

