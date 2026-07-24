"""Genera el Manual de funcionamiento (PDF) con capturas, diagramas y enlaces."""

from __future__ import annotations

from pathlib import Path

import qrcode
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "manual" / "Manual_Funcionamiento_Paredes_Bienes_Raices.pdf"
IMG = ROOT / "docs" / "manual" / "imagenes" / "_thumb"
IMG_RAW = ROOT / "docs" / "manual" / "imagenes"
FONTS = Path(r"C:\Windows\Fonts")
BASE_URL = "http://127.0.0.1:8000"

pdfmetrics.registerFont(TTFont("ArialPBR", str(FONTS / "arial.ttf")))
pdfmetrics.registerFont(TTFont("ArialPBR-Bold", str(FONTS / "arialbd.ttf")))

NAVY = colors.HexColor("#003366")
MUTED = colors.HexColor("#5c6b7a")
BLUE = colors.HexColor("#3d6ea3")
SOFT = colors.HexColor("#f0f4f9")
BORDER = colors.HexColor("#c8d4e3")
WARN_BG = colors.HexColor("#fffbeb")
WARN_BD = colors.HexColor("#b45309")
OK_BG = colors.HexColor("#f0fdfa")
OK_BD = colors.HexColor("#0f766e")
LINK = colors.HexColor("#0b57d0")


class UriLink(Flowable):
    """Texto azul clicable que abre una URL."""

    def __init__(self, label: str, url: str, width: float = 16.5 * cm):
        super().__init__()
        self.label = label
        self.url = url
        self._width = width
        self._height = 14

    def wrap(self, availWidth, availHeight):
        self._width = min(self._width, availWidth)
        return self._width, self._height

    def draw(self):
        self.canv.setFillColor(LINK)
        self.canv.setFont("ArialPBR", 9)
        self.canv.drawString(0, 3, self.label)
        self.canv.linkURL(self.url, (0, 0, self._width, self._height), relative=1)


def styles():
    return {
        "cover_kicker": ParagraphStyle(
            "cover_kicker",
            fontName="ArialPBR-Bold",
            fontSize=10,
            textColor=BLUE,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "cover_title": ParagraphStyle(
            "cover_title",
            fontName="ArialPBR-Bold",
            fontSize=22,
            textColor=NAVY,
            alignment=TA_CENTER,
            leading=28,
            spaceAfter=8,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            fontName="ArialPBR",
            fontSize=11,
            textColor=MUTED,
            alignment=TA_CENTER,
            leading=15,
            spaceAfter=14,
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName="ArialPBR-Bold",
            fontSize=14,
            textColor=NAVY,
            spaceBefore=6,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "h2",
            fontName="ArialPBR-Bold",
            fontSize=11,
            textColor=NAVY,
            spaceBefore=10,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "h3",
            fontName="ArialPBR-Bold",
            fontSize=10,
            textColor=BLUE,
            spaceBefore=8,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="ArialPBR",
            fontSize=9.5,
            textColor=colors.HexColor("#152433"),
            leading=13,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "li": ParagraphStyle(
            "li",
            fontName="ArialPBR",
            fontSize=9.5,
            textColor=colors.HexColor("#152433"),
            leading=12.5,
            leftIndent=14,
            spaceAfter=3,
        ),
        "muted": ParagraphStyle(
            "muted",
            fontName="ArialPBR",
            fontSize=9,
            textColor=MUTED,
            leading=12,
            spaceAfter=6,
        ),
        "caption": ParagraphStyle(
            "caption",
            fontName="ArialPBR",
            fontSize=8.5,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceBefore=3,
            spaceAfter=10,
            leading=11,
        ),
        "meta": ParagraphStyle(
            "meta",
            fontName="ArialPBR",
            fontSize=9.5,
            textColor=MUTED,
            leading=13,
            spaceAfter=2,
        ),
        "cell": ParagraphStyle(
            "cell",
            fontName="ArialPBR",
            fontSize=8.5,
            textColor=colors.HexColor("#152433"),
            leading=11,
        ),
        "cell_h": ParagraphStyle(
            "cell_h",
            fontName="ArialPBR-Bold",
            fontSize=8.5,
            textColor=colors.white,
            leading=11,
        ),
        "toc": ParagraphStyle(
            "toc",
            fontName="ArialPBR",
            fontSize=10,
            textColor=NAVY,
            leading=15,
            spaceAfter=2,
        ),
        "tip": ParagraphStyle(
            "tip",
            fontName="ArialPBR",
            fontSize=9,
            textColor=NAVY,
            leading=12,
            spaceAfter=4,
        ),
    }


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def bullets(items: list[str], s, ordered: bool = False) -> list:
    out = []
    for i, it in enumerate(items, start=1):
        prefix = f"{i}." if ordered else "•"
        out.append(Paragraph(f"{prefix} {it}", s["li"]))
    out.append(Spacer(1, 4))
    return out


def callout(text: str, s, kind: str = "note") -> Table:
    if kind == "warn":
        bg, bd = WARN_BG, WARN_BD
    elif kind == "ok":
        bg, bd = OK_BG, OK_BD
    else:
        bg, bd = SOFT, NAVY
    t = Table([[Paragraph(text, s["body"])]], colWidths=[16.5 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.5, bd),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def table(headers: list[str], rows: list[list[str]], s, widths=None) -> Table:
    head = [Paragraph(h, s["cell_h"]) for h in headers]
    body = [[Paragraph(c, s["cell"]) for c in row] for row in rows]
    data = [head] + body
    t = Table(data, colWidths=widths, repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), SOFT))
    t.setStyle(TableStyle(cmds))
    return t


def check_table(items: list[str], s) -> Table:
    rows = [[Paragraph("☐", s["cell"]), Paragraph(it, s["cell"])] for it in items]
    t = Table(rows, colWidths=[1.0 * cm, 15.5 * cm])
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND", (0, 0), (0, -1), SOFT),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ]
        )
    )
    return t


def figure(filename: str, caption: str, s, max_w: float = 16.2 * cm, max_h: float = 9.2 * cm):
    path = IMG / filename
    if not path.exists():
        path = IMG_RAW / filename
    if not path.exists():
        return [p(f"<i>[Imagen no disponible: {filename}]</i>", s["muted"])]

    ir = ImageReader(str(path))
    iw, ih = ir.getSize()
    aspect = ih / float(iw)
    w = max_w
    h = w * aspect
    if h > max_h:
        h = max_h
        w = h / aspect

    img = Table([[ir]], colWidths=[w])
    # ReportLab Image via platypus
    from reportlab.platypus import Image as RLImage

    rl_img = RLImage(str(path), width=w, height=h)
    box = Table([[rl_img]], colWidths=[w + 4])
    box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    wrap = Table([[box]], colWidths=[16.5 * cm])
    wrap.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    return [wrap, p(caption, s["caption"])]


def make_qr(path: Path, url: str) -> None:
    qr = qrcode.QRCode(version=2, box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#003366", back_color="white")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, "PNG")


def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    y = 12 * mm
    canvas.line(16 * mm, y + 5, A4[0] - 16 * mm, y + 5)
    canvas.setFont("ArialPBR", 8)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(
        A4[0] / 2,
        y,
        f"Manual interactivo v1.3  ·  Paredes Desarrollos Inmobiliarios  ·  Página {doc.page}",
    )
    canvas.restoreState()


def build():
    s = styles()
    story: list = []

    qr_path = IMG_RAW / "qr_catalogo.png"
    make_qr(qr_path, f"{BASE_URL}/catalogo/")

    # Portada
    story.append(Spacer(1, 2.2 * cm))
    story.append(p("DOCUMENTO INTERNO · CAPACITACIÓN · CON CAPTURAS", s["cover_kicker"]))
    story.append(p("Manual de funcionamiento<br/>del sistema", s["cover_title"]))
    story.append(
        p(
            "Paredes Desarrollos Inmobiliarios<br/>Guía visual e interactiva (enlaces + pantallas reales)",
            s["cover_sub"],
        )
    )
    meta_inner = Table(
        [
            [Paragraph("<b>Versión:</b> 1.3 (con imágenes e interacciones)", s["meta"])],
            [Paragraph("<b>Fecha:</b> 15 de julio de 2026", s["meta"])],
            [
                Paragraph(
                    "<b>Incluye:</b> Capturas del sistema, diagramas de flujo, QR del catálogo y enlaces clicables",
                    s["meta"],
                )
            ],
            [Paragraph("<b>Público:</b> Personal operativo y administración", s["meta"])],
        ],
        colWidths=[13.5 * cm],
    )
    meta_inner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 16),
                ("RIGHTPADDING", (0, 0), (-1, -1), 16),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(Table([["", meta_inner, ""]], colWidths=[1.5 * cm, 13.5 * cm, 1.5 * cm]))
    story.append(Spacer(1, 14))
    story.append(p("<b>Accesos rápidos (clic en el PDF):</b>", s["tip"]))
    story.append(UriLink(f"Abrir login » {BASE_URL}/login/", f"{BASE_URL}/login/"))
    story.append(Spacer(1, 2))
    story.append(UriLink(f"Abrir catálogo público » {BASE_URL}/catalogo/", f"{BASE_URL}/catalogo/"))
    story.append(UriLink(f"Abrir app interna » {BASE_URL}/app/", f"{BASE_URL}/app/"))
    story.append(PageBreak())

    # Cómo usar este manual
    story.append(p("Cómo usar este manual", s["h1"]))
    story.append(
        p(
            "Este documento es <b>visual e interactivo</b>: incluye capturas reales del sistema, "
            "diagramas de flujo y enlaces que puede abrir con un clic (si visualiza el PDF en un lector "
            "con soporte de hipervínculos, como Adobe Acrobat, Edge o Chrome).",
            s["body"],
        )
    )
    story.extend(
        bullets(
            [
                "Mire primero el <b>diagrama</b> del proceso (venta, alquiler o catálogo).",
                "Luego revise la <b>captura de pantalla</b> para ubicar el menú.",
                "Pulse los <b>enlaces azules</b> para abrir la pantalla en el navegador.",
                "Use el <b>QR</b> del catálogo para probar el enlace en el celular.",
            ],
            s,
            ordered=True,
        )
    )
    story.append(callout(
        "<b>Tip:</b> Si un enlace no abre, copie la URL y péguela en el navegador. "
        "En local el servidor debe estar encendido en el puerto 8000.",
        s,
    ))

    story.append(p("Índice", s["h1"]))
    for line in [
        "1. Acceso al sistema (login)",
        "2. Mapa del menú y vista general",
        "3. Clientes",
        "4. Vendedores vs Asesores alquiler",
        "5. Inmuebles: venta y alquiler",
        "6. Contratos y dónde asignar el vendedor",
        "7. Catálogo público + QR",
        "8. Documentos PDF",
        "9. Flujos visuales (venta / alquiler / fotos)",
        "10. Checklist de capacitación",
        "11. Preguntas frecuentes",
    ]:
        story.append(p(line, s["toc"]))
    story.append(PageBreak())

    # 1 Login
    story.append(p("1. Acceso al sistema (login)", s["h1"]))
    story.append(
        p(
            "Para entrar escriba usuario y contraseña. Ejemplo local:",
            s["body"],
        )
    )
    story.append(UriLink(f"{BASE_URL}/login/", f"{BASE_URL}/login/"))
    story.append(Spacer(1, 6))
    story.extend(
        figure(
            "01_login.png",
            "Figura 1. Pantalla de ingreso al sistema (Usuario + Contraseña + Entrar).",
            s,
            max_h=8.5 * cm,
        )
    )
    story.extend(
        bullets(
            [
                "Campo <b>Usuario</b>.",
                "Campo <b>Contraseña</b> (ojo para mostrar/ocultar).",
                "Botón <b>Entrar</b>.",
            ],
            s,
            ordered=True,
        )
    )
    story.append(
        callout(
            "<b>Nota:</b> Si aparece «Usuario o contraseña incorrectos», la clave no coincide. "
            "Contacte al administrador para restablecerla.",
            s,
            "warn",
        )
    )
    story.append(PageBreak())

    # 2 Menu
    story.append(p("2. Mapa del menú y vista general", s["h1"]))
    story.append(
        p(
            "Tras ingresar verá el menú lateral: Clientes, Vendedores, Inmuebles, Asesores alquiler y Gestión.",
            s["body"],
        )
    )
    story.extend(
        figure(
            "04_gestion_inicio.png",
            "Figura 2. Inicio de Gestión: módulos del día a día y acceso al catálogo para clientes.",
            s,
            max_h=10 * cm,
        )
    )
    story.append(
        table(
            ["Módulo", "Para qué"],
            [
                ["Clientes", "Expediente comprador / inquilino"],
                ["Vendedores", "Asesores de venta de proyectos"],
                ["Inmuebles", "Alquileres, venta y catálogo público"],
                ["Asesores alquiler", "Asesores de arrendamientos (aparte)"],
                ["Gestión", "Proyectos, contratos, pagos, documentos"],
            ],
            s,
            widths=[4.5 * cm, 12 * cm],
        )
    )
    story.append(
        callout(
            "<b>Regla de oro:</b> Vendedores (venta) ≠ Asesores alquiler. Son catálogos independientes.",
            s,
            "warn",
        )
    )
    story.extend(
        figure(
            "11_dashboard.png",
            "Figura 3. Dashboard: resumen de inventario, disponibles, contratos y atajos.",
            s,
            max_h=8.2 * cm,
        )
    )
    story.append(PageBreak())

    # 3 Clientes
    story.append(p("3. Clientes", s["h1"]))
    story.append(UriLink(f"Abrir listado de clientes » {BASE_URL}/app/clientes/", f"{BASE_URL}/app/clientes/"))
    story.append(Spacer(1, 4))
    story.extend(
        figure(
            "07_clientes.png",
            "Figura 4. Módulo Clientes: listado, alta y reportes del expediente.",
            s,
            max_h=9 * cm,
        )
    )
    story.extend(
        bullets(
            [
                "Alta: <b>Clientes » Nuevo cliente</b>.",
                "Uso en venta (contrato), alquiler (inquilino) o reserva.",
                "Opcional: <b>Reporte PDF</b> del cliente.",
            ],
            s,
            ordered=True,
        )
    )

    # 4 Vendedores vs asesores
    story.append(p("4. Vendedores vs Asesores alquiler", s["h1"]))
    story.append(
        p(
            "Son dos menús distintos. Compárelos en las capturas siguientes.",
            s["body"],
        )
    )
    story.append(UriLink(f"Vendedores » {BASE_URL}/app/vendedores/", f"{BASE_URL}/app/vendedores/"))
    story.append(UriLink(f"Asesores alquiler » {BASE_URL}/app/asesores-alquiler/", f"{BASE_URL}/app/asesores-alquiler/"))
    story.append(Spacer(1, 4))
    story.extend(
        figure(
            "05_vendedores.png",
            "Figura 5. Catálogo de Vendedores (proyectos / venta / contratos).",
            s,
            max_h=7.8 * cm,
        )
    )
    story.extend(
        figure(
            "06_asesores_alquiler.png",
            "Figura 6. Catálogo de Asesores alquiler (solo arrendamientos).",
            s,
            max_h=7.8 * cm,
        )
    )
    story.append(
        table(
            ["Pregunta", "Respuesta"],
            [
                ["¿Vendió casa/lote?", "Asignar en el <b>Contrato</b> » campo Vendedor"],
                ["¿Intermedió un alquiler?", "En el <b>recibo de comisión de alquiler</b> » Asesor"],
                ["¿En el proyecto?", "No se asigna vendedor al proyecto"],
            ],
            s,
            widths=[5.5 * cm, 11 * cm],
        )
    )
    story.append(PageBreak())

    # 5 Inmuebles
    story.append(p("5. Inmuebles: venta y alquiler", s["h1"]))
    story.append(UriLink(f"Hub venta » {BASE_URL}/app/inmuebles/venta/", f"{BASE_URL}/app/inmuebles/venta/"))
    story.append(UriLink(f"Hub alquiler » {BASE_URL}/app/inmuebles/alquileres/", f"{BASE_URL}/app/inmuebles/alquileres/"))
    story.append(Spacer(1, 4))
    story.extend(
        figure(
            "08_inmuebles_venta.png",
            "Figura 7. Hub de Venta: casas, lotes y comisión de venta.",
            s,
            max_h=8.5 * cm,
        )
    )
    story.extend(
        figure(
            "09_inmuebles_alquiler.png",
            "Figura 8. Hub de Alquileres: locales, casas, comisión y asesores de alquiler.",
            s,
            max_h=8.5 * cm,
        )
    )

    # 6 Contratos
    story.append(p("6. Contratos y dónde asignar el vendedor", s["h1"]))
    story.append(
        p(
            "La venta formal se registra en Contratos. Ahí se elige el <b>Vendedor</b> del catálogo de proyectos.",
            s["body"],
        )
    )
    story.append(UriLink(f"Abrir contratos » {BASE_URL}/app/contratos/", f"{BASE_URL}/app/contratos/"))
    story.append(Spacer(1, 4))
    story.extend(
        figure(
            "10_contratos.png",
            "Figura 9. Contratos: cliente + inmueble + vendedor; promesa y recibo de comisión.",
            s,
            max_h=8.8 * cm,
        )
    )
    story.append(
        callout(
            "<b>Recuerde:</b> el proyecto solo organiza inventario. El vendedor se asigna por cada venta en el contrato.",
            s,
            "ok",
        )
    )
    story.append(PageBreak())

    # 7 Catalogo + QR
    story.append(p("7. Catálogo público + QR", s["h1"]))
    story.append(
        p(
            "Página abierta (sin login) con fotos de inmuebles <b>Disponibles</b>. "
            "Desde la app: <b>Inmuebles » Catálogo para clientes</b>.",
            s["body"],
        )
    )
    story.append(UriLink(f"Abrir catálogo » {BASE_URL}/catalogo/", f"{BASE_URL}/catalogo/"))
    story.append(Spacer(1, 4))
    story.extend(
        figure(
            "02_catalogo_publico.png",
            "Figura 10. Catálogo público: listado, copiar enlace y WhatsApp.",
            s,
            max_h=8.8 * cm,
        )
    )

    # QR block
    from reportlab.platypus import Image as RLImage

    qr_img = RLImage(str(qr_path), width=4.2 * cm, height=4.2 * cm)
    qr_block = Table(
        [
            [
                qr_img,
                Paragraph(
                    "<b>Escanee para abrir el catálogo en el celular</b><br/><br/>"
                    f"URL: {BASE_URL}/catalogo/<br/><br/>"
                    "Ideal para compartir en visitas o capacitaciones. "
                    "El cliente solo ve fotos; no entra al sistema interno.",
                    s["body"],
                ),
            ]
        ],
        colWidths=[5 * cm, 11.5 * cm],
    )
    qr_block.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                ("BOX", (0, 0), (-1, -1), 0.7, NAVY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(Spacer(1, 6))
    story.append(qr_block)
    story.append(PageBreak())

    # 8 Docs
    story.append(p("8. Documentos PDF", s["h1"]))
    story.append(
        table(
            ["Documento", "Desde dónde", "Beneficiario"],
            [
                ["Promesa de venta", "Contratos » Promesa PDF", "Cliente / venta"],
                ["Recibo de ingreso", "Pagos / Documentos", "Cliente"],
                ["Comisión vendedor", "Contratos » Recibo vendedor", "Vendedor de proyectos"],
                ["Comisión alquiler", "Alquileres » Comisión...", "Asesor de alquiler"],
                ["Formato de aceptación", "Gestión » Documentos", "Uso interno"],
                ["Reporte de cliente", "Clientes » Reporte PDF", "Expediente"],
            ],
            s,
            widths=[4.5 * cm, 7 * cm, 5 * cm],
        )
    )

    # 9 Flujos visuales
    story.append(p("9. Flujos visuales", s["h1"]))
    story.append(p("9.1 Venta de proyectos", s["h2"]))
    story.extend(
        figure(
            "flujo_venta.png",
            "Figura 11. Flujo de venta: Cliente » Contrato (Vendedor) » Documentos.",
            s,
            max_h=7.2 * cm,
        )
    )
    story.append(p("9.2 Arrendamientos", s["h2"]))
    story.extend(
        figure(
            "flujo_alquiler.png",
            "Figura 12. Flujo de alquiler: Inquilino » Ficha » Asesor alquiler + recibo.",
            s,
            max_h=7.2 * cm,
        )
    )
    story.append(p("9.3 Compartir fotos", s["h2"]))
    story.extend(
        figure(
            "flujo_catalogo.png",
            "Figura 13. Flujo del catálogo: fotos » Disponible » enlace/WhatsApp.",
            s,
            max_h=7.2 * cm,
        )
    )
    story.append(PageBreak())

    # 10 Checklist
    story.append(p("10. Checklist de capacitación", s["h1"]))
    story.append(p("Marque cada actividad al capacitar a un colaborador.", s["muted"]))
    story.append(p("10.1 Acceso y menú", s["h2"]))
    story.append(
        check_table(
            [
                "Entrar y salir del sistema (Figura 1)",
                "Reconocer los 5 bloques del menú (Figura 2)",
                "Abrir Dashboard (Figura 3)",
            ],
            s,
        )
    )
    story.append(p("10.2 Catálogos separados", s["h2"]))
    story.append(
        check_table(
            [
                "Crear un Vendedor de proyectos (Figura 5)",
                "Crear un Asesor de alquiler (Figura 6)",
                "Explicar por qué no son el mismo catálogo",
            ],
            s,
        )
    )
    story.append(p("10.3 Operación", s["h2"]))
    story.append(
        check_table(
            [
                "Registrar cliente (Figura 4)",
                "Usar hub venta y hub alquiler (Figuras 7 y 8)",
                "Crear contrato y asignar Vendedor (Figura 9)",
                "Abrir catálogo, copiar enlace o escanear QR (Figura 10)",
            ],
            s,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        p(
            "Capacitador: _________________ &nbsp;&nbsp; Colaborador: _________________ &nbsp;&nbsp; Fecha: ________",
            s["muted"],
        )
    )
    story.append(PageBreak())

    # 11 FAQ
    story.append(p("11. Preguntas frecuentes", s["h1"]))
    faqs = [
        (
            "¿Dónde asigno quién vendió una casa?",
            "En el <b>Contrato</b>, campo <b>Vendedor</b> (Figura 9). No en el proyecto.",
        ),
        (
            "¿Dónde asigno quién intermediaron un alquiler?",
            "En el recibo de comisión de alquiler, catálogo <b>Asesores alquiler</b> (Figura 6 y 8).",
        ),
        (
            "El catálogo no muestra un inmueble",
            "Proyecto activo + estado Disponible + fotos cargadas. Luego abra /catalogo/.",
        ),
        (
            "Un enlace del PDF no abre",
            "Confirme que el servidor esté activo y use la URL local http://127.0.0.1:8000/…",
        ),
    ]
    for title, ans in faqs:
        story.append(KeepTogether([p(title, s["h3"]), p(ans, s["body"])]))

    story.append(Spacer(1, 12))
    story.append(p("<b>Accesos finales:</b>", s["tip"]))
    story.append(UriLink(f"Login » {BASE_URL}/login/", f"{BASE_URL}/login/"))
    story.append(UriLink(f"Catálogo » {BASE_URL}/catalogo/", f"{BASE_URL}/catalogo/"))
    story.append(UriLink(f"App » {BASE_URL}/app/", f"{BASE_URL}/app/"))
    story.append(Spacer(1, 10))
    story.append(
        p(
            "Fin del manual v1.3. Paredes Desarrollos Inmobiliarios — A &amp; Z<br/>"
            "Archivo: docs/manual/Manual_Funcionamiento_Paredes_Bienes_Raices.pdf",
            s["muted"],
        )
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=18 * mm,
        title="Manual interactivo — Paredes Bienes Raíces",
        author="Paredes Desarrollos Inmobiliarios",
    )
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"OK {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
