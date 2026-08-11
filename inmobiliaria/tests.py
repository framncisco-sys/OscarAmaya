from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from inmobiliaria.forms_web import FormatoAceptacionForm
from inmobiliaria.models import FormatoAceptacion, Vendedor
from inmobiliaria.validacion_gerencia import aplicar_validacion_formato_o_plan
from usuarios.models import PerfilUsuario

from .formato_numero_pdf import (
    numero_desde_token_qr,
    numero_en_nombre_archivo,
    token_qr_formato,
)

User = get_user_model()


class FormatoNumeroPdfTests(TestCase):
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


def _crear_usuario(username: str, rol: str, *, password: str = "TestLocal123!") -> User:
    user = User.objects.create_user(username=username, password=password)
    PerfilUsuario.objects.create(
        user=user,
        rol=rol,
        activo_en_app=True,
        empresa=PerfilUsuario.Empresa.AMBAS,
    )
    return user


def _payload_formato_minimo(*, numero: int, elaborado: str) -> dict[str, str]:
    return {
        "numero_formulario": str(numero),
        "nombre_cliente": "Cliente Prueba Local",
        "dui_numero": "12345678-9",
        "tipo_financiamiento": FormatoAceptacion.TipoFinanciamiento.CONTADO,
        "nombre_proyecto": "Proyecto prueba",
        "num_lote": "",
        "elaborado_por": elaborado,
    }


class FormatoAceptacionGuardadoLocalTests(TestCase):
    """Guardado de formato sin enviar validacion_gerencia (regresión v38)."""

    @classmethod
    def setUpTestData(cls):
        cls.vendedor = Vendedor.objects.create(
            nombres="Ana",
            apellidos="Prueba",
            porcentaje_comision_default=Decimal("3"),
            activo=True,
        )
        cls.elaborado = cls.vendedor.nombre_completo.strip()
        cls.admin = _crear_usuario("test_admin_local", PerfilUsuario.Rol.ADMINISTRADOR)
        cls.proyectos = _crear_usuario("test_proyectos_local", PerfilUsuario.Rol.PROYECTOS)
        cls.asesor = _crear_usuario("test_asesor_local", PerfilUsuario.Rol.VENTAS)

    def test_formulario_no_incluye_validacion_gerencia(self):
        form = FormatoAceptacionForm(user=self.admin)
        self.assertNotIn("validacion_gerencia", form.fields)
        self.assertNotIn("validado_gerencia_por", form.fields)

    def test_formulario_valido_sin_validacion_gerencia(self):
        data = _payload_formato_minimo(numero=90001, elaborado=self.elaborado)
        form = FormatoAceptacionForm(data=data, user=self.admin)
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_admin_guarda_por_http_sin_validacion_gerencia(self):
        client = Client()
        client.force_login(self.admin)
        url = reverse("app:formato_aceptacion_nuevo")
        data = _payload_formato_minimo(numero=90002, elaborado=self.elaborado)
        resp = client.post(url, data, follow=False)
        self.assertEqual(resp.status_code, 302, resp.content[:500])
        fmt = FormatoAceptacion.objects.get(numero_formulario=90002)
        self.assertEqual(fmt.nombre_cliente, "Cliente Prueba Local")
        self.assertEqual(
            fmt.validacion_gerencia,
            FormatoAceptacion.ValidacionGerencia.VALIDADO,
        )
        self.assertEqual(fmt.creado_por_id, self.admin.pk)

    def test_proyectos_guarda_pendiente_validacion(self):
        client = Client()
        client.force_login(self.proyectos)
        url = reverse("app:formato_aceptacion_nuevo")
        data = _payload_formato_minimo(numero=90003, elaborado=self.elaborado)
        resp = client.post(url, data, follow=False)
        self.assertEqual(resp.status_code, 302, resp.content[:500])
        fmt = FormatoAceptacion.objects.get(numero_formulario=90003)
        self.assertEqual(
            fmt.validacion_gerencia,
            FormatoAceptacion.ValidacionGerencia.PENDIENTE,
        )

    def test_asesor_guarda_sin_cola_gerencia(self):
        client = Client()
        client.force_login(self.asesor)
        url = reverse("app:formato_aceptacion_nuevo")
        data = _payload_formato_minimo(numero=90004, elaborado=self.elaborado)
        resp = client.post(url, data, follow=False)
        self.assertEqual(resp.status_code, 302, resp.content[:500])
        fmt = FormatoAceptacion.objects.get(numero_formulario=90004)
        self.assertEqual(
            fmt.validacion_gerencia,
            FormatoAceptacion.ValidacionGerencia.NO_APLICA,
        )

    def test_aplicar_validacion_no_exige_campo_en_post(self):
        inst = FormatoAceptacion(
            numero_formulario=90005,
            nombre_cliente="Directo",
        )
        aplicar_validacion_formato_o_plan(inst, self.admin)
        self.assertEqual(
            inst.validacion_gerencia,
            FormatoAceptacion.ValidacionGerencia.VALIDADO,
        )
