from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator

from inmobiliaria.models import Contrato


class ReciboComisionVendedorForm(forms.Form):
    """Recibo de comisión por venta — solo vía contratos (módulo ventas)."""

    monto_comision = forms.DecimalField(
        label="Monto de comisión (USD)",
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        validators=[MinValueValidator(Decimal("0.01"))],
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
        help_text="Importe que figurará en el recibo. Puede ajustarlo respecto al sugerido del contrato.",
    )
    comision_porcentaje = forms.DecimalField(
        label="Porcentaje de comisión (opcional)",
        max_digits=6,
        decimal_places=2,
        required=False,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0", "max": "100"}),
        help_text="Solo referencia en el PDF. Si lo cambia, revise que el monto coincida con su criterio.",
    )
    concepto = forms.CharField(
        label="Concepto en el recibo",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Texto que describe la comisión en el documento impreso.",
    )

    def __init__(self, *args, contrato: Contrato | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.contrato = contrato
        if contrato is not None and not self.is_bound:
            monto = contrato.monto_comision_efectivo()
            if monto is not None:
                self.fields["monto_comision"].initial = monto
            if contrato.comision_porcentaje is not None:
                self.fields["comision_porcentaje"].initial = contrato.comision_porcentaje
            self.fields["concepto"].initial = _concepto_comision_default(contrato)


def _concepto_comision_default(contrato: Contrato) -> str:
    inm = contrato.inmueble
    tipo = inm.get_tipo_display().lower() if inm else "inmueble"
    codigo = inm.codigo_display if inm else "—"
    return (
        f"Comisión por intermediación en la venta del {tipo} {codigo} "
        f"(contrato {contrato.numero})."
    )
