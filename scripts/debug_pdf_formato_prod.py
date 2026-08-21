import os
import re

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
import django

django.setup()

from django.template.loader import render_to_string

from docs.services import _html_to_pdf_bytes, branding_pdf_context
from inmobiliaria.models import FormatoAceptacion
from inmobiliaria.views_web import _proyecto_para_pdf_formato

fmt = FormatoAceptacion.objects.order_by("-pk").first()
proy = _proyecto_para_pdf_formato(fmt)
ctx = {
    "formato": fmt,
    "proyecto": proy,
    "pie_inmobiliaria": "Formato de aceptación — documento interno",
    **branding_pdf_context(proy),
}
html = render_to_string("docs/formato_aceptacion_pdf.html", ctx)
print("HTML hardcoded Desarrollos:", "Paredes Desarrollos Inmobiliarios" in html)
print("HTML data-uri logos:", html.count("data:image/png;base64,"))
print("HTML old Inmobiliaria kicker:", ">Inmobiliaria<" in html)
print("HTML BIENES RAICES in caption:", 'pdf-brand-name">Paredes Bienes' in html)
for i, src in enumerate(re.findall(r'<img[^>]+src="([^"]+)"', html)[:3]):
    print(f"img{i} src prefix:", src[:80])
pdf = _html_to_pdf_bytes(html)
print("PDF bytes:", len(pdf))
text = pdf.decode("latin-1", errors="ignore")
print("PDF contains Desarrollos:", "Desarrollos" in text)
print("PDF contains BIENES RA:", "BIENES RA" in text.upper())
