from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from docs.services import _saldos_recibo


class ReciboPrecioNegociadoTests(SimpleTestCase):
    def test_saldos_reserva_usan_precio_autorizado(self):
        contrato = Mock()
        contrato.pk = 10
        contrato.precio_final = Decimal("23468.29")

        pago = Mock()
        pago.pk = 1
        pago.contrato = contrato
        pago.contrato_id = 10
        pago.fecha = __import__("datetime").date(2026, 8, 14)
        pago.monto = Decimal("500.00")
        pago.monto_recargo_incluido = Decimal("0.00")
        pago.concepto = "RESERVA"

        qs_mock = Mock()
        qs_mock.filter.return_value = qs_mock
        qs_mock.aggregate.return_value = {"t": None}

        with patch(
            "docs.services._precio_inmueble_vigente_recibo",
            return_value=(Decimal("23000.00"), Mock()),
        ):
            with patch.object(contrato, "pagos", qs_mock):
                with patch("inmobiliaria.models.CuotaProgramada") as cuota_model:
                    cuota_model.objects.filter.return_value.exists.return_value = False
                    saldos = _saldos_recibo(pago)

        self.assertEqual(saldos["saldo_anterior"], Decimal("23000.00"))
        self.assertEqual(saldos["nuevo_saldo"], Decimal("22500.00"))
