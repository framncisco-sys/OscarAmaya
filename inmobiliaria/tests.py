from django.test import SimpleTestCase

from inmobiliaria.formato_numero_pdf import (
    numero_desde_token_qr,
    numero_en_nombre_archivo,
    token_qr_formato,
)


class FormatoNumeroPdfTests(SimpleTestCase):
    def test_token_qr_formato(self):
        self.assertEqual(token_qr_formato(18), "PBR-FA-0018")
        self.assertEqual(numero_desde_token_qr("PBR-FA-0018"), 18)
        self.assertEqual(numero_desde_token_qr("  pbr-fa-42  "), 42)

    def test_numero_en_nombre_archivo(self):
        self.assertTrue(numero_en_nombre_archivo("Formato de aceptación 18.pdf", 18))
        self.assertTrue(numero_en_nombre_archivo("formato_aceptacion_0018.pdf", 18))
        self.assertTrue(numero_en_nombre_archivo("FORMATO ACEPTACION 18.PDF", 18))
        self.assertFalse(numero_en_nombre_archivo("formato.pdf", 18))
        self.assertFalse(numero_en_nombre_archivo("formato 118.pdf", 18))
