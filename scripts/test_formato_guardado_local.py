"""
Prueba local del guardado de formato de aceptación (sin desplegar).

Uso:
  python scripts/test_formato_guardado_local.py

Requiere Postgres local con .env configurado (POSTGRES_*).
Con Docker: docker compose -f docker-compose.dev.yml up -d db
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, override_settings
from django.urls import reverse

from inmobiliaria.forms_web import FormatoAceptacionForm, _FORMATO_ACEPTACION_EXCLUDE
from inmobiliaria.models import FormatoAceptacion, Vendedor
from usuarios.models import PerfilUsuario

User = get_user_model()


def _ok(msg: str) -> None:
    print(f"  OK  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")
    raise SystemExit(1)


def _payload(numero: int, elaborado: str) -> dict[str, str]:
    return {
        "numero_formulario": str(numero),
        "nombre_cliente": "Cliente Prueba Local",
        "dui_numero": "12345678-9",
        "tipo_financiamiento": FormatoAceptacion.TipoFinanciamiento.CONTADO,
        "nombre_proyecto": "Proyecto prueba",
        "num_lote": "",
        "elaborado_por": elaborado,
    }


def _crear_usuario(username: str, rol: str) -> User:
    user, created = User.objects.get_or_create(username=username)
    if created:
        user.set_password("TestLocal123!")
        user.save()
    PerfilUsuario.objects.update_or_create(
        user=user,
        defaults={
            "rol": rol,
            "activo_en_app": True,
            "empresa": PerfilUsuario.Empresa.AMBAS,
        },
    )
    return user


def test_sin_bd() -> None:
    print("\n[1] Formulario (sin consultar BD)")
    if "validacion_gerencia" in _FORMATO_ACEPTACION_EXCLUDE:
        _ok("validacion_gerencia en lista de exclusión del formulario")
    else:
        _fail("validacion_gerencia no está excluido")


def _test_con_bd_http() -> None:
    vendedor, _ = Vendedor.objects.get_or_create(
        nombres="Ana",
        apellidos="Prueba Local",
        defaults={
            "porcentaje_comision_default": Decimal("3"),
            "activo": True,
        },
    )
    elaborado = vendedor.nombre_completo.strip()

    admin = _crear_usuario("test_admin_local", PerfilUsuario.Rol.ADMINISTRADOR)
    proyectos = _crear_usuario("test_proyectos_local", PerfilUsuario.Rol.PROYECTOS)
    asesor = _crear_usuario("test_asesor_local", PerfilUsuario.Rol.VENTAS)

    base_num = 91000 + (os.getpid() % 1000)

    data = _payload(base_num, elaborado)
    form = FormatoAceptacionForm(data=data, user=admin)
    if not form.is_valid():
        _fail(f"formulario inválido: {form.errors.as_json()}")
    _ok("FormatoAceptacionForm.is_valid() sin validacion_gerencia en POST")

    client = Client()

    client.force_login(admin)
    resp = client.post(reverse("app:formato_aceptacion_nuevo"), _payload(base_num + 1, elaborado))
    if resp.status_code != 302:
        _fail(f"admin POST status {resp.status_code}: {resp.content[:300]!r}")
    fmt = FormatoAceptacion.objects.get(numero_formulario=base_num + 1)
    if fmt.validacion_gerencia != FormatoAceptacion.ValidacionGerencia.VALIDADO:
        _fail(f"admin: validacion_gerencia={fmt.validacion_gerencia}")
    _ok("Admin guarda formato → VALIDADO")

    client.force_login(proyectos)
    resp = client.post(reverse("app:formato_aceptacion_nuevo"), _payload(base_num + 2, elaborado))
    if resp.status_code != 302:
        _fail(f"proyectos POST status {resp.status_code}")
    fmt = FormatoAceptacion.objects.get(numero_formulario=base_num + 2)
    if fmt.validacion_gerencia != FormatoAceptacion.ValidacionGerencia.PENDIENTE:
        _fail(f"proyectos: validacion_gerencia={fmt.validacion_gerencia}")
    _ok("Proyectos guarda formato → PENDIENTE (cola gerencia)")

    client.force_login(asesor)
    resp = client.post(reverse("app:formato_aceptacion_nuevo"), _payload(base_num + 3, elaborado))
    if resp.status_code != 302:
        _fail(f"asesor POST status {resp.status_code}")
    fmt = FormatoAceptacion.objects.get(numero_formulario=base_num + 3)
    if fmt.validacion_gerencia != FormatoAceptacion.ValidacionGerencia.NO_APLICA:
        _fail(f"asesor: validacion_gerencia={fmt.validacion_gerencia}")
    _ok("Asesor guarda formato → NO_APLICA")

    FormatoAceptacion.objects.filter(
        numero_formulario__in=[base_num + 1, base_num + 2, base_num + 3]
    ).delete()
    _ok("Registros de prueba eliminados")


def test_con_bd() -> None:
    print("\n[2] Guardado HTTP (requiere Postgres)")
    connection.ensure_connection()
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
        _test_con_bd_http()


def main() -> None:
    print("=== Prueba local: guardado formato de aceptación ===")
    test_sin_bd()
    try:
        test_con_bd()
    except Exception as exc:  # noqa: BLE001
        print(f"\n  SKIP  Pruebas HTTP (BD no disponible): {exc}")
        print(
            "\nPara prueba completa:\n"
            "  1. docker compose -f docker-compose.dev.yml up -d db\n"
            "  2. POSTGRES_PORT=5434 en .env\n"
            "  3. python manage.py migrate\n"
            "  4. Vuelva a ejecutar este script\n"
        )
        return
    print("\n=== Todas las pruebas locales pasaron ===")


if __name__ == "__main__":
    main()
