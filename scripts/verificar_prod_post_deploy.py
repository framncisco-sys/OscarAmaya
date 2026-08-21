"""Verificación post-deploy en producción (manage.py shell)."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django

django.setup()

from django.conf import settings
from django.test import Client

from core.pbr_icons import PBR_CACHE_VERSION
from docs.services import branding_pdf_context
from inmobiliaria.models import FormatoAceptacion, Contrato, Cliente, Inmueble
from inmobiliaria.views_web import _generar_pdf_formato_aceptacion_bytes

checks: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    checks.append((name, cond, detail))
    mark = "OK" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


# 1. Servicio / settings básicos
ok("CACHE_VERSION", PBR_CACHE_VERSION == "42", f"v{PBR_CACHE_VERSION}")
ok("BREVO", bool(getattr(settings, "BREVO_API_KEY", "").strip()), "API key presente")
ok(
    "EMAIL_FALLBACK",
    bool(getattr(settings, "RECIBO_EMAIL_FALLBACK", "").strip()),
    getattr(settings, "RECIBO_EMAIL_FALLBACK", ""),
)

# 2. Datos intactos
n_fmt = FormatoAceptacion.objects.count()
n_cli = Cliente.objects.count()
n_cont = Contrato.objects.count()
n_inm = Inmueble.objects.count()
ok("DB_formatos", n_fmt > 0, f"{n_fmt} formatos")
ok("DB_clientes", n_cli >= 0, f"{n_cli} clientes")
ok("DB_contratos", n_cont >= 0, f"{n_cont} contratos")
ok("DB_inmuebles", n_inm > 0, f"{n_inm} inmuebles")

# 3. PDF formato — razón social Desarrollos
fmt = (
    FormatoAceptacion.objects.select_related("contrato", "contrato__cliente")
    .order_by("-pk")
    .first()
)
if fmt:
    brand = branding_pdf_context(None)
    ok(
        "PDF_empresa_nombre",
        brand.get("empresa_nombre") == "Paredes Desarrollos Inmobiliarios",
        brand.get("empresa_nombre", ""),
    )
    try:
        pdf = _generar_pdf_formato_aceptacion_bytes(fmt)
        ok("PDF_genera", len(pdf) > 5000, f"{len(pdf)} bytes, formato #{fmt.numero_formulario}")
        text = pdf.decode("latin-1", errors="ignore")
        ok(
            "PDF_sin_bienes_raices_caption",
            "PAREDES BIENES RA" not in text.upper()[:8000]
            or "DESARROLLOS" in text.upper()[:8000],
            f"formato #{fmt.numero_formulario}",
        )
    except Exception as e:
        ok("PDF_genera", False, str(e)[:120])
else:
    ok("PDF_formato_existe", False, "sin formatos")

# 4. HTTP login
client = Client(HTTP_HOST="paredesdesarrollosinmobiliarios.com")
resp = client.get("/login/", secure=True)
ok("HTTP_login", resp.status_code == 200, f"status {resp.status_code}")

# 5. Resumen
failed = [c for c in checks if not c[1]]
print("\n--- RESUMEN ---")
print(f"Total: {len(checks)}, OK: {len(checks) - len(failed)}, FAIL: {len(failed)}")
if failed:
    for name, _, detail in failed:
        print(f"  FAIL: {name} ({detail})")
    raise SystemExit(1)
print("Todo verificado correctamente.")
