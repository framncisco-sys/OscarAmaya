from decimal import Decimal

from django.conf import settings
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models

from .validators import validar_dui_sv, validar_nit_sv


class Proyecto(models.Model):
    """Lotificación o residencial."""

    nombre = models.CharField(max_length=200)
    municipio = models.CharField(max_length=120, blank=True)
    departamento = models.CharField(max_length=120, blank=True)
    direccion = models.TextField(blank=True)
    permisos_notas = models.TextField(
        blank=True,
        help_text="Permisos, observaciones registrales, etc.",
    )
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    plano_maestro = models.FileField(
        "Plano maestro del proyecto",
        upload_to="proyectos/planos/%Y/%m/",
        blank=True,
        help_text="Una sola imagen o PDF del plano completo de la lotificación. Cada polígono marcará su zona sobre este archivo (sin volver a subirlo).",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg", "webp"],
                message="Use PDF, JPG, PNG o WEBP.",
            )
        ],
    )

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Proyecto"
        verbose_name_plural = "Proyectos"

    def __str__(self) -> str:
        return self.nombre


class Poligono(models.Model):
    """Agrupación lógica de lotes (ej. Polígono A, B)."""

    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name="poligonos",
    )
    nombre = models.CharField(max_length=120)
    orden = models.PositiveSmallIntegerField(default=0)
    plano = models.FileField(
        "Plano propio (opcional)",
        upload_to="poligonos/planos/%Y/%m/",
        blank=True,
        help_text="Solo si este polígono usa otro archivo distinto al plano maestro del proyecto. Si lo deja vacío, se usa el plano del proyecto.",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg", "webp"],
                message="Use PDF, JPG, PNG o WEBP.",
            )
        ],
    )
    # Vista del plano: rectángulo sobre la imagen (0–100 %). Si sube el plano completo del proyecto,
    # indique aquí solo la zona de ESTE polígono para que en pantalla no se vea todo el mapa.
    recorte_izq_pct = models.DecimalField(
        "Recorte: desde la izquierda (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Distancia desde el borde izquierdo de la imagen hasta donde empieza la zona de este polígono (0–100).",
    )
    recorte_sup_pct = models.DecimalField(
        "Recorte: desde arriba (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Distancia desde el borde superior (0–100).",
    )
    recorte_ancho_pct = models.DecimalField(
        "Recorte: ancho visible (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Ancho del rectángulo que corresponde a este polígono (0–100).",
    )
    recorte_alto_pct = models.DecimalField(
        "Recorte: alto visible (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Alto del rectángulo (0–100).",
    )

    class Meta:
        ordering = ["proyecto", "orden", "nombre"]
        unique_together = [("proyecto", "nombre")]
        verbose_name = "Polígono"
        verbose_name_plural = "Polígonos"

    def __str__(self) -> str:
        return f"{self.proyecto} — {self.nombre}"

    @property
    def _nombre_archivo_plano_fuente(self) -> str | None:
        """Archivo usado para vista y recorte: primero plano del polígono, si no, plano maestro del proyecto."""
        if self.plano and self.plano.name:
            return self.plano.name
        try:
            if self.proyecto_id and self.proyecto.plano_maestro and self.proyecto.plano_maestro.name:
                return self.proyecto.plano_maestro.name
        except Proyecto.DoesNotExist:
            pass
        return None

    @property
    def plano_vista_url(self) -> str | None:
        """URL del archivo a mostrar (polígono o proyecto)."""
        if self.plano and self.plano.name:
            return self.plano.url
        try:
            if self.proyecto_id and self.proyecto.plano_maestro and self.proyecto.plano_maestro.name:
                return self.proyecto.plano_maestro.url
        except Proyecto.DoesNotExist:
            pass
        return None

    @property
    def plano_clip_path(self) -> str | None:
        """Valor CSS clip-path:inset(...) para mostrar solo el recorte; None = imagen completa."""
        name = self._nombre_archivo_plano_fuente
        if not name or name.lower().endswith(".pdf"):
            return None
        if (
            self.recorte_izq_pct is None
            or self.recorte_sup_pct is None
            or self.recorte_ancho_pct is None
            or self.recorte_alto_pct is None
        ):
            return None
        L = float(self.recorte_izq_pct)
        T = float(self.recorte_sup_pct)
        W = float(self.recorte_ancho_pct)
        H = float(self.recorte_alto_pct)
        if W <= 0 or H <= 0:
            return None
        if L < 0 or T < 0 or L + W > 100.01 or T + H > 100.01:
            return None
        r = 100.0 - L - W
        b = 100.0 - T - H
        return f"inset({T:.2f}% {r:.2f}% {b:.2f}% {L:.2f}%)"

    @property
    def plano_vista_es_pdf(self) -> bool:
        n = self._nombre_archivo_plano_fuente
        return bool(n and n.lower().endswith(".pdf"))


class Inmueble(models.Model):
    """Lote, casa o local; inventario con jerarquía y segregación."""

    class Tipo(models.TextChoices):
        LOTE = "LOTE", "Lote"
        CASA_NUEVA = "CASA_NUEVA", "Casa nueva"
        CASA_SEGUNDA = "CASA_SEGUNDA", "Casa segunda"
        LOCAL = "LOCAL", "Local comercial"

    class Estado(models.TextChoices):
        DISPONIBLE = "DISPONIBLE", "Disponible"
        RESERVADO = "RESERVADO", "Reservado"
        VENDIDO = "VENDIDO", "Vendido"
        BLOQUEADO = "BLOQUEADO", "Bloqueado"

    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name="inmuebles",
    )
    poligono = models.ForeignKey(
        Poligono,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lotes",
        help_text="Opcional: lotes dentro de un polígono.",
    )
    inmueble_padre = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hijos_segregados",
        help_text="Lote padre si este es resultado de segregación.",
    )

    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.LOTE)
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.DISPONIBLE,
    )
    codigo = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Referencia interna (ej. A-15).",
    )

    precio_lista = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )

    area_varas_cuadradas = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Superficie en varas cuadradas (v²).",
    )
    area_m2 = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Superficie en metros cuadrados (m²).",
    )
    frente_m = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    fondo_m = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    topografia = models.CharField(max_length=200, blank=True)
    servicios_basicos = models.TextField(blank=True)

    latitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    tour_virtual_url = models.URLField(blank=True)
    notas = models.TextField(blank=True)
    # Geometría del lote en coordenadas relativas (0..100) sobre el plano del proyecto.
    # Formato esperado: {"type":"Polygon","coordinates":[[[x,y],[x,y],...]]}
    geometria_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Coordenadas del lote para el mapa interactivo (formato JSON).",
    )

    cliente_reserva = models.ForeignKey(
        "Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inmuebles_reservados",
        help_text="Cliente que tiene el lote apartado (solo si está reservado).",
    )
    reserva_hasta = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha límite de la reserva. Pasada esa fecha, ejecute el comando expirar_reservas o revierta manualmente.",
    )

    class Meta:
        ordering = ["proyecto", "codigo"]
        unique_together = [("proyecto", "codigo")]
        verbose_name = "Inmueble"
        verbose_name_plural = "Inmuebles"

    def __str__(self) -> str:
        return f"{self.codigo} ({self.get_tipo_display()})"

    @property
    def label_venta(self) -> str:
        """Texto para elegir el lote en contratos (proyecto, polígono, código, estado, precio)."""
        pol = self.poligono.nombre if self.poligono else "Sin polígono"
        return (
            f"{self.proyecto.nombre} — {pol} — Lote {self.codigo} · "
            f"{self.get_estado_display()} · ${self.precio_lista}"
        )

    @property
    def etiqueta_lote(self) -> str:
        """Una línea corta: polígono + código del lote."""
        pol = self.poligono.nombre if self.poligono else "—"
        return f"{pol} · Lote {self.codigo}"


class InmuebleImagen(models.Model):
    """Galería (URL para no exigir almacenamiento de archivos en MVP)."""

    inmueble = models.ForeignKey(
        Inmueble,
        on_delete=models.CASCADE,
        related_name="imagenes",
    )
    url = models.URLField()
    orden = models.PositiveSmallIntegerField(default=0)
    descripcion = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["orden", "id"]
        verbose_name = "Imagen de inmueble"
        verbose_name_plural = "Imágenes de inmuebles"

    def __str__(self) -> str:
        return f"Img {self.inmueble.codigo}"


class HistorialPrecioInmueble(models.Model):
    """Registro automático cuando cambia el precio de lista."""

    inmueble = models.ForeignKey(
        Inmueble,
        on_delete=models.CASCADE,
        related_name="historial_precios",
    )
    precio_anterior = models.DecimalField(max_digits=14, decimal_places=2)
    precio_nuevo = models.DecimalField(max_digits=14, decimal_places=2)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]
        verbose_name = "Historial de precio"
        verbose_name_plural = "Historial de precios"

    def __str__(self) -> str:
        return f"{self.inmueble.codigo} {self.precio_anterior} → {self.precio_nuevo}"


class Cliente(models.Model):
    nombres = models.CharField(max_length=120)
    apellidos = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=40, blank=True)

    dui = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        validators=[validar_dui_sv],
    )
    nit = models.CharField(
        max_length=20,
        blank=True,
        validators=[validar_nit_sv],
    )
    pasaporte = models.CharField(max_length=40, blank=True)
    direccion = models.TextField(blank=True)
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["apellidos", "nombres"]
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def __str__(self) -> str:
        return f"{self.nombres} {self.apellidos}".strip()


class ClienteDocumento(models.Model):
    """Archivos asociados al expediente del cliente (DUI, constancias, etc.)."""

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name="documentos",
    )
    archivo = models.FileField(
        upload_to="clientes/documentos/%Y/%m/",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg", "webp", "doc", "docx"],
                message="Use PDF, imágenes (JPG, PNG, WEBP) o Word (.doc, .docx).",
            )
        ],
    )
    descripcion = models.CharField(max_length=200, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]
        verbose_name = "Documento de cliente"
        verbose_name_plural = "Documentos de clientes"

    def __str__(self) -> str:
        return self.descripcion or self.archivo.name


class Vendedor(models.Model):
    """Asesor o corredor: catálogo para asignar ventas, comisión y recibo de comisión."""

    nombres = models.CharField(max_length=120)
    apellidos = models.CharField(max_length=120)
    dui = models.CharField(max_length=20, blank=True, validators=[validar_dui_sv])
    telefono = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    porcentaje_comision_default = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("3"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Porcentaje sugerido sobre el precio de venta al elegir este vendedor en un contrato.",
    )
    usuario_vinculo = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vendedor_catalogo",
        help_text="Usuario interno opcional si el vendedor tiene cuenta en el sistema.",
    )
    activo = models.BooleanField(default=True)
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["apellidos", "nombres"]
        verbose_name = "Vendedor"
        verbose_name_plural = "Vendedores"

    def __str__(self) -> str:
        return self.nombre_completo

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellidos}".strip()


class Contrato(models.Model):
    """Vincula cliente e inmueble; base para crédito propio y cartera."""

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        ACTIVO = "ACTIVO", "Activo"
        LIQUIDADO = "LIQUIDADO", "Liquidado"
        CANCELADO = "CANCELADO", "Cancelado"

    class EtapaComercial(models.TextChoices):
        """Embudo de venta (independiente del estado legal del contrato)."""
        CONVERSACION = "CONVERSACION", "En conversación"
        RESERVA = "RESERVA", "Reserva / apartado"
        DOCUMENTOS = "DOCUMENTOS", "Documentación"
        CIERRE = "CIERRE", "Cierre / venta"

    class PlanAnos(models.IntegerChoices):
        ANOS_5 = 5, "5 años"
        ANOS_10 = 10, "10 años"
        ANOS_15 = 15, "15 años"

    class ModalidadFinanciamiento(models.TextChoices):
        """Condición negociada del crédito propio; la tasa y plazo se documentan en los campos numéricos."""
        TASA_NEGOCIADA = "TASA_NEGOCIADA", "Financiamiento con tasa anual negociada"
        PRIMER_ANO_SIN_INTERESES = (
            "PRIMER_ANO_SIN_INTERESES",
            "Primer año sin intereses (luego aplica tasa acordada)",
        )
        MESES_INICIALES_SIN_INTERES = (
            "MESES_INICIALES_SIN_INTERES",
            "Meses iniciales sin intereses (indique cantidad abajo)",
        )
        SIN_FINANCIAMIENTO = "SIN_FINANCIAMIENTO", "Sin financiamiento (contado / pago único)"
        OTRO = "OTRO", "Otra modalidad (detalle en notas)"

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name="contratos",
    )
    inmueble = models.ForeignKey(
        Inmueble,
        on_delete=models.PROTECT,
        related_name="contratos",
    )

    numero = models.CharField(max_length=50, unique=True)
    fecha_firma = models.DateField()
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.BORRADOR,
    )
    etapa_comercial = models.CharField(
        max_length=20,
        choices=EtapaComercial.choices,
        default=EtapaComercial.CONVERSACION,
        db_index=True,
        help_text="Etapa en el embudo de ventas.",
    )

    vendedor_perfil = models.ForeignKey(
        Vendedor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contratos",
        verbose_name="Vendedor (catálogo)",
        help_text="Vendedor del módulo de ventas; define comisión sugerida y recibo de comisión.",
    )
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contratos_como_vendedor",
        help_text="Usuario interno (se sincroniza si el vendedor tiene vínculo).",
    )
    vendedor_nombre = models.CharField(
        max_length=120,
        blank=True,
        help_text="Texto libre si no usa el catálogo o como respaldo en documentos.",
    )
    comision_porcentaje = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Porcentaje de comisión sobre el precio final (opcional).",
    )
    comision_monto = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Monto fijo de comisión (opcional). Si rellena ambos, use el criterio que defina la empresa.",
    )

    precio_final = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Precio total acordado en esta operación (financiado, efectivo u otra condición).",
    )
    precio_lista_referencia = models.DecimalField(
        "Precio de lista (referencia)",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Precio de lista del lote al momento de la venta (referencia; puede ser cualquier valor acordado internamente).",
    )
    descuento_efectivo_monto = models.DecimalField(
        "Descuento por efectivo u otra condición",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Monto de descuento aplicado (ej. pago en efectivo). Opcional; puede ser cualquier valor.",
    )

    plan_anos = models.PositiveSmallIntegerField(
        choices=PlanAnos.choices,
        null=True,
        blank=True,
        help_text="Plazo de financiamiento propio (años).",
    )
    modalidad_financiamiento = models.CharField(
        max_length=40,
        choices=ModalidadFinanciamiento.choices,
        default=ModalidadFinanciamiento.TASA_NEGOCIADA,
        db_index=True,
        help_text="Cómo se acordó el interés o el período sin intereses.",
    )
    meses_sin_interes = models.PositiveSmallIntegerField(
        "Meses sin interés (iniciales)",
        null=True,
        blank=True,
        help_text="Solo si aplica: cantidad de meses al inicio sin cargo de intereses (ej. 12 = un año).",
    )
    tasa_interes_anual = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Tasa anual negociada (cuando aplique después del período sin interés o en modalidad estándar). Use 0 si acuerda tasa cero en todo el plazo.",
    )
    cuota_mensual_estimada = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )

    desglose_iva_monto = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="IVA u otros impuestos desglosados (según asesoría contable).",
    )
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_firma", "numero"]
        verbose_name = "Contrato"
        verbose_name_plural = "Contratos"

    def __str__(self) -> str:
        return f"{self.numero} — {self.cliente}"

    @property
    def descuento_implicito_vs_referencia(self) -> Decimal | None:
        """Diferencia referencia − precio final, si hay referencia."""
        if self.precio_lista_referencia is None:
            return None
        return (self.precio_lista_referencia - self.precio_final).quantize(Decimal("0.01"))

    def monto_comision_efectivo(self) -> Decimal | None:
        """Monto de comisión para recibos: monto fijo o % sobre precio final."""
        if self.comision_monto is not None:
            return self.comision_monto
        if self.precio_final is not None and self.comision_porcentaje is not None:
            return (self.precio_final * self.comision_porcentaje / Decimal("100")).quantize(
                Decimal("0.01")
            )
        return None

    def nombre_vendedor_documentos(self) -> str:
        """Nombre para PDF y listados de comisión."""
        if self.vendedor_perfil_id:
            return self.vendedor_perfil.nombre_completo
        t = (self.vendedor_nombre or "").strip()
        if t:
            return t
        if self.vendedor_id:
            u = self.vendedor
            fn = u.get_full_name().strip()
            return fn or u.get_username()
        return ""


class Pago(models.Model):
    """Registro de primas, cuotas, mantenimiento, abonos y mora."""

    class Concepto(models.TextChoices):
        PRIMA = "PRIMA", "Prima / enganche"
        CUOTA = "CUOTA", "Cuota de financiamiento"
        MANTENIMIENTO = "MANTENIMIENTO", "Cuota de mantenimiento"
        ABONO_CAPITAL = "ABONO_CAPITAL", "Abono a capital"
        MORA = "MORA", "Intereses moratorios"
        OTRO = "OTRO", "Otro"

    contrato = models.ForeignKey(
        Contrato,
        on_delete=models.CASCADE,
        related_name="pagos",
    )
    fecha = models.DateField()
    concepto = models.CharField(max_length=24, choices=Concepto.choices)
    monto = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    referencia = models.CharField(max_length=120, blank=True)
    notas = models.TextField(blank=True)
    cuotas_incluidas = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text="Si el concepto es cuota de financiamiento: cuántas cuotas consecutivas (en orden de vencimiento) liquida este pago.",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def __str__(self) -> str:
        return f"{self.fecha} {self.get_concepto_display()} {self.monto}"


class CuotaProgramada(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        PAGADA = "PAGADA", "Pagada"
        VENCIDA = "VENCIDA", "Vencida"

    contrato = models.ForeignKey(
        Contrato,
        on_delete=models.CASCADE,
        related_name="cuotas_programadas",
    )
    numero = models.PositiveSmallIntegerField(help_text="Número de cuota (1..N).")
    vence_en = models.DateField()
    monto = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
        db_index=True,
    )
    pagado_en = models.DateField(null=True, blank=True)
    pago = models.ForeignKey(
        Pago,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cuotas_aplicadas",
        help_text="Pago que liquidó esta cuota (si aplica).",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["contrato", "numero"]
        unique_together = [("contrato", "numero")]
        verbose_name = "Cuota programada"
        verbose_name_plural = "Cuotas programadas"

    def __str__(self) -> str:
        return f"{self.contrato.numero} cuota {self.numero} ({self.get_estado_display()})"


class RecordatorioPago(models.Model):
    class Canal(models.TextChoices):
        EMAIL = "EMAIL", "Correo"
        WHATSAPP_MANUAL = "WHATSAPP_MANUAL", "WhatsApp (manual)"

    cuota = models.ForeignKey(
        CuotaProgramada,
        on_delete=models.CASCADE,
        related_name="recordatorios",
    )
    canal = models.CharField(max_length=20, choices=Canal.choices)
    programado_para = models.DateField(help_text="Fecha objetivo del recordatorio.")
    mensaje = models.TextField(blank=True)
    wa_link = models.URLField(blank=True)
    enviado = models.BooleanField(default=False)
    enviado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-programado_para", "-id"]
        unique_together = [("cuota", "canal", "programado_para")]
        verbose_name = "Recordatorio de pago"
        verbose_name_plural = "Recordatorios de pago"

    def __str__(self) -> str:
        return f"{self.cuota_id} {self.canal} {self.programado_para}"


class ParametroMora(models.Model):
    """Parámetros para cálculo de mora (ajustar según política interna y asesoría legal)."""

    nombre = models.CharField(max_length=80, default="Default")
    tasa_diaria_porcentaje = models.DecimalField(
        max_digits=8,
        decimal_places=6,
        default=Decimal("0"),
        help_text="Porcentaje diario sobre saldo vencido (ej. 0.05 = 0.05% diario).",
    )
    dias_gracia = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Parámetro de mora"
        verbose_name_plural = "Parámetros de mora"

    def __str__(self) -> str:
        return self.nombre
