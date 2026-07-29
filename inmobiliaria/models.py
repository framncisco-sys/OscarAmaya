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
    logo = models.ImageField(
        "Logo del proyecto",
        upload_to="proyectos/logos/%Y/%m/",
        blank=True,
        help_text="Logo del residencial/lotificación (PNG o JPG). Se usa en recibos y documentos PDF.",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["png", "jpg", "jpeg", "webp"],
                message="Use PNG, JPG o WEBP.",
            )
        ],
    )
    plano_maestro = models.FileField(
        "Plano del proyecto",
        upload_to="proyectos/planos/%Y/%m/",
        blank=True,
        help_text="Plano completo de la lotificación (imagen o PDF). Los polígonos se marcan sobre este archivo.",
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

    @property
    def tiene_logo(self) -> bool:
        return bool(self.logo and self.logo.name)

    @property
    def tiene_plano(self) -> bool:
        return bool(self.plano_maestro and self.plano_maestro.name)


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
    # Polígono en WGS84 (lon/lat) para mapa Leaflet sobre teselas OSM/Google — no mezclar con geometria_json (0–100).
    geometria_catastral_geojson = models.JSONField(
        null=True,
        blank=True,
        help_text="GeoJSON Polygon en EPSG:4326 (ej. dibujado sobre OpenStreetMap). Opcional; ver también geometria_json sobre el plano.",
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
    en_alquiler = models.BooleanField(
        "En alquiler",
        default=False,
        help_text="Si está marcado, el inmueble aparece en Arrendamientos (locales o casas según el tipo).",
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


class InmuebleDetalleCasa(models.Model):
    """Ficha ampliada para venta de casa nueva o de segunda (no aplica a lotes ni locales)."""

    class TipoConstruccion(models.TextChoices):
        SISTEMA_BLOQUE = "SISTEMA_BLOQUE", "Sistema bloque"
        PREFABRICADA = "PREFABRICADA", "Prefabricada"
        ADOBE_REFORZADO = "ADOBE_REFORZADO", "Adobe reforzado"

    class DistribucionSalaComedorCocina(models.TextChoices):
        INDEPENDIENTES = "INDEPENDIENTES", "Independientes"
        CONCEPTO_ABIERTO = "CONCEPTO_ABIERTO", "Concepto abierto"
        MIXTO = "MIXTO", "Mixto / otro (amplíe en notas)"

    class EstadoConservacion(models.TextChoices):
        EXCELENTE = "EXCELENTE", "Excelente"
        BUENO = "BUENO", "Bueno"
        REQUIERE_REPARACIONES = "REQUIERE_REPARACIONES", "Requiere reparaciones"

    inmueble = models.OneToOneField(
        Inmueble,
        on_delete=models.CASCADE,
        related_name="detalle_casa",
        verbose_name="Inmueble",
    )
    direccion_exacta = models.TextField(
        "Dirección exacta del inmueble",
        blank=True,
        help_text="Dirección completa para ubicar la propiedad.",
    )
    tipo_construccion = models.CharField(
        "Tipo de construcción",
        max_length=24,
        choices=TipoConstruccion.choices,
        blank=True,
    )
    niveles = models.PositiveSmallIntegerField(
        "Niveles (plantas)",
        null=True,
        blank=True,
        help_text="1, 2 o 3 plantas.",
        validators=[MaxValueValidator(3), MinValueValidator(1)],
    )
    distribucion_sala_comedor_cocina = models.CharField(
        "Sala, comedor y cocina",
        max_length=24,
        choices=DistribucionSalaComedorCocina.choices,
        blank=True,
        help_text="¿Independientes o concepto abierto?",
    )
    habitaciones = models.PositiveSmallIntegerField(
        "Número de habitaciones",
        null=True,
        blank=True,
    )
    banos = models.DecimalField(
        "Número de baños",
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="Ej. 2 o 2,5.",
    )
    cochera_capacidad_vehiculos = models.PositiveSmallIntegerField(
        "Cochera: capacidad (vehículos)",
        null=True,
        blank=True,
    )
    cochera_techada = models.BooleanField(
        "Cochera techada",
        default=False,
    )
    amueblada = models.BooleanField(
        "Amueblada",
        default=False,
    )
    muebles_incluidos = models.TextField(
        "Muebles incluidos (inventario)",
        blank=True,
        help_text="Si está amueblada, indique con qué muebles se entrega.",
    )
    area_construccion_m2 = models.DecimalField(
        "Área de construcción (m²)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    modelo_casa = models.CharField(
        "Modelo de casa",
        max_length=120,
        blank=True,
        help_text='Ej. «Modelo Roble», «Modelo Gardenia».',
    )
    ano_finalizacion_obra = models.PositiveSmallIntegerField(
        "Año de finalización de la obra",
        null=True,
        blank=True,
        help_text="Cuándo se entrega o entregó la obra (casa nueva).",
    )
    garantia_construccion = models.TextField(
        "Garantía de construcción",
        blank=True,
        help_text="Ej. 1 año en vicios ocultos, 5 años en estructura.",
    )
    extras_incluidos = models.TextField(
        "Extras incluidos",
        blank=True,
        help_text="Ej. piso cerámico, encimeras de granito, closets.",
    )
    conexiones_ac_calentador = models.TextField(
        "Conexiones (aire acondicionado / calentador)",
        blank=True,
        help_text="Si ya tiene acometida u observaciones.",
    )
    aire_ac_cantidad = models.PositiveSmallIntegerField(
        "Cantidad de aires acondicionados",
        null=True,
        blank=True,
        help_text="Número de unidades instaladas (vacío si no aplica).",
    )
    aire_ac_ubicacion = models.TextField(
        "Ubicación de los aires acondicionados",
        blank=True,
        help_text="Ej. habitaciones, sala, comedor.",
    )
    edad_construccion_anios = models.PositiveSmallIntegerField(
        "Edad de la construcción (años, aprox.)",
        null=True,
        blank=True,
    )
    estado_conservacion = models.CharField(
        "Estado de conservación",
        max_length=24,
        choices=EstadoConservacion.choices,
        blank=True,
    )
    remodelaciones_recientes = models.TextField(
        "Remodelaciones recientes",
        blank=True,
        help_text='Ej. «Techo cambiado en 2024», «Piso nuevo».',
    )
    gravamenes_hipoteca = models.TextField(
        "Gravámenes / hipoteca",
        blank=True,
        help_text="¿Hipoteca vigente con algún banco? (relevante para compraventa).",
    )
    servicio_anda_al_dia = models.BooleanField(
        "Servicio de agua (ANDA) al día",
        default=False,
    )
    servicio_eeh_al_dia = models.BooleanField(
        "Energía eléctrica (EEH/DELSUR) al día",
        default=False,
    )
    servicio_alcaldia_al_dia = models.BooleanField(
        "Impuestos municipales (Alcaldía) al día",
        default=False,
    )
    escritura_copia = models.FileField(
        "Escritura (copia simple)",
        upload_to="inmuebles/casas/escritura/%Y/%m/",
        blank=True,
        help_text="Para validar matrícula en CNR.",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg", "webp"],
                message="Use PDF o imagen (JPG, PNG, WEBP).",
            )
        ],
    )
    dui_dueno = models.CharField(
        "DUI del dueño",
        max_length=20,
        blank=True,
        help_text="Para formato de aceptación y trámites.",
        validators=[validar_dui_sv],
    )
    direccion_dueno = models.TextField(
        "Dirección del dueño",
        blank=True,
    )
    telefono_dueno = models.CharField(
        "Teléfono del dueño",
        max_length=40,
        blank=True,
    )
    pago_dueno_efectivo = models.BooleanField(
        "Efectivo",
        default=False,
        help_text="El dueño acepta pago en efectivo.",
    )
    pago_dueno_fondo_social = models.BooleanField(
        "Financiamiento con Fondo Social",
        default=False,
    )
    pago_dueno_sistema_financiero = models.BooleanField(
        "Sistema financiero (banco)",
        default=False,
        help_text="El dueño acepta trato o financiamiento vía banco.",
    )
    recibo_luz_agua = models.FileField(
        "Recibo de luz y/o agua",
        upload_to="inmuebles/casas/recibos/%Y/%m/",
        blank=True,
        help_text="Verificar dirección y ausencia de mora.",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg", "webp"],
                message="Use PDF o imagen.",
            )
        ],
    )
    plano_catastro = models.FileField(
        "Plano de catastro",
        upload_to="inmuebles/casas/catastro/%Y/%m/",
        blank=True,
        help_text="Ayuda a la valuación bancaria.",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg", "webp"],
                message="Use PDF o imagen.",
            )
        ],
    )

    class Meta:
        verbose_name = "Detalle de casa (venta)"
        verbose_name_plural = "Detalles de casas (venta)"

    def __str__(self) -> str:
        return f"Detalle casa · {self.inmueble.codigo}"


class InmuebleDetalleLocalAlquiler(models.Model):
    """Condiciones de arrendamiento para locales comerciales en alquiler."""

    inmueble = models.OneToOneField(
        Inmueble,
        on_delete=models.CASCADE,
        related_name="detalle_local_alquiler",
        verbose_name="Inmueble",
    )
    inquilino = models.ForeignKey(
        "Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alquileres_local",
        verbose_name="Inquilino / arrendatario",
        help_text="Cliente al que se arrienda este local (módulo alquiler, aparte de contratos de venta).",
    )
    renta_mensual = models.DecimalField(
        "Monto de renta mensual",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Ej. $500.00.",
    )
    cuota_mantenimiento = models.DecimalField(
        "Cuota de mantenimiento / vigilancia",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Si el local está en una plaza.",
    )
    deposito_garantia = models.DecimalField(
        "Depósito en garantía",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Suele equivaler a un mes de renta.",
    )
    uso_permitido = models.TextField(
        "Uso permitido",
        blank=True,
        help_text="Ej. oficina, restaurante, clínica. Vital en San Miguel para no saturar una plaza con el mismo rubro.",
    )
    plazo_contrato = models.CharField(
        "Plazo del contrato",
        max_length=200,
        blank=True,
        help_text="Ej. mínimo 1 año o 12 meses.",
    )
    incremento_anual_pct = models.DecimalField(
        "Incremento anual (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="En El Salvador suele estilarse 5 % o 10 % cada año.",
    )
    periodo_gracia_dias = models.PositiveSmallIntegerField(
        "Período de gracia (días)",
        null=True,
        blank=True,
        help_text="Días sin cobrar renta para remodelar u otros acuerdos.",
    )

    class Meta:
        verbose_name = "Detalle local en alquiler"
        verbose_name_plural = "Detalles locales en alquiler"

    def __str__(self) -> str:
        return f"Alquiler local · {self.inmueble.codigo}"


class InmuebleDetalleCasaAlquiler(models.Model):
    """Arrendamiento de vivienda: inventario, restricciones, renta, depósito y vigencia."""

    inmueble = models.OneToOneField(
        Inmueble,
        on_delete=models.CASCADE,
        related_name="detalle_casa_alquiler",
        verbose_name="Inmueble",
    )
    inquilino = models.ForeignKey(
        "Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alquileres_casa",
        verbose_name="Inquilino / arrendatario",
        help_text="Cliente al que se arrienda esta casa (módulo alquiler, aparte de contratos de venta).",
    )
    inventario_detallado_estado = models.TextField(
        "Inventario detallado y estado",
        blank=True,
        help_text="Ej. bomba de agua, calentador, lámparas: indique estado (funcionando, nueva, etc.).",
    )
    acepta_mascotas = models.BooleanField(
        "Se aceptan mascotas",
        default=False,
    )
    maximo_personas = models.PositiveSmallIntegerField(
        "Máximo de personas",
        null=True,
        blank=True,
        help_text="Cupos permitidos; vacío si no aplica límite explícito.",
    )
    uso_exclusivo_habitacional = models.BooleanField(
        "Uso exclusivo habitacional",
        default=False,
    )
    servicios_incluidos_renta = models.TextField(
        "Servicios incluidos en la renta",
        blank=True,
        help_text="Ej. vigilancia, internet, agua; relevante para el recibo mensual.",
    )
    arrendamiento_mensual = models.DecimalField(
        "Arrendamiento mensual",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Ej. $450.00.",
    )
    deposito_garantia_monto = models.DecimalField(
        "Depósito (fondo en garantía)",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="No es renta: fianza o mes adelantado en garantía.",
    )
    vigencia_inicio = models.DateField(
        "Vigencia: fecha de inicio",
        null=True,
        blank=True,
    )
    vigencia_fin = models.DateField(
        "Vigencia: fecha de fin",
        null=True,
        blank=True,
        help_text="Ej. contrato 12 meses forzosos hasta esta fecha.",
    )

    class Meta:
        verbose_name = "Detalle casa en alquiler"
        verbose_name_plural = "Detalles casas en alquiler"

    def __str__(self) -> str:
        return f"Alquiler casa · {self.inmueble.codigo}"


class InmuebleImagen(models.Model):
    """Galería: URL externa y/o archivo; una imagen puede marcarse como portada."""

    inmueble = models.ForeignKey(
        Inmueble,
        on_delete=models.CASCADE,
        related_name="imagenes",
    )
    url = models.URLField(blank=True, default="")
    imagen = models.ImageField(
        "Archivo de imagen",
        upload_to="inmuebles/galeria/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["png", "jpg", "jpeg", "webp", "gif"],
                message="Use PNG, JPG, JPEG, WEBP o GIF.",
            )
        ],
    )
    es_portada = models.BooleanField("Portada", default=False)
    orden = models.PositiveSmallIntegerField(default=0)
    descripcion = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["orden", "id"]
        verbose_name = "Imagen de inmueble"
        verbose_name_plural = "Imágenes de inmuebles"

    def __str__(self) -> str:
        return f"Img {self.inmueble.codigo}"

    def clean(self) -> None:
        super().clean()
        if not (self.url or "").strip() and not self.imagen:
            from django.core.exceptions import ValidationError

            raise ValidationError("Indique una URL o suba un archivo de imagen.")

    @property
    def url_visual(self) -> str:
        if self.imagen and self.imagen.name:
            return self.imagen.url
        u = (self.url or "").strip()
        return u


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
    """Asesor o corredor de venta de proyectos (lotes, casas). No aplica al módulo de alquileres."""

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
        help_text="Porcentaje de comisión sobre el precio de venta. Se copia al contrato al elegir este vendedor; con eso se calcula el recibo de comisión de venta.",
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


class AsesorAlquiler(models.Model):
    """Asesor o intermediario del módulo de alquileres (independiente del catálogo de venta de proyectos)."""

    nombres = models.CharField(max_length=120)
    apellidos = models.CharField(max_length=120)
    dui = models.CharField(max_length=20, blank=True, validators=[validar_dui_sv])
    telefono = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    comision_arrendamiento_pct = models.DecimalField(
        "Comisión sugerida (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("100"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Porcentaje de referencia sobre la renta mensual al emitir recibo de comisión de alquiler.",
    )
    activo = models.BooleanField(default=True)
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["apellidos", "nombres"]
        verbose_name = "Asesor de alquiler"
        verbose_name_plural = "Asesores de alquiler"

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
        ANOS_1 = 1, "1 año"
        ANOS_2 = 2, "2 años"
        ANOS_3 = 3, "3 años"
        ANOS_4 = 4, "4 años"
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
    """Registro de primas, cuotas, mantenimiento, abonos y recargo administrativo."""

    class Concepto(models.TextChoices):
        RESERVA = "RESERVA", "Reserva pagada"
        PRIMA = "PRIMA", "Prima pagada (recibo)"
        CONTADO = "CONTADO", "Pago de contado (total del lote)"
        CUOTA = "CUOTA", "Cuota de financiamiento (plazos)"
        MANTENIMIENTO = "MANTENIMIENTO", "Cuota de mantenimiento"
        ABONO_CAPITAL = "ABONO_CAPITAL", "Abono a capital"
        MORA = "MORA", "Recargo administrativo"
        OTRO = "OTRO", "Otro"

    class ValidacionAbono(models.TextChoices):
        NO_APLICA = "NO_APLICA", "No requiere validación"
        PENDIENTE = "PENDIENTE", "Pendiente de gerencia"
        VALIDADO = "VALIDADO", "Abono confirmado en cuenta"
        RECHAZADO = "RECHAZADO", "Rechazado por gerencia"

    CONCEPTOS_CON_VALIDACION = frozenset(
        {
            Concepto.RESERVA,
            Concepto.PRIMA,
            Concepto.CONTADO,
            Concepto.CUOTA,
            Concepto.ABONO_CAPITAL,
        }
    )

    contrato = models.ForeignKey(
        Contrato,
        on_delete=models.CASCADE,
        related_name="pagos",
    )
    formato_aceptacion = models.ForeignKey(
        "FormatoAceptacion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos",
        verbose_name="Formato de aceptación",
        help_text="Opcional: formato guardado desde el cual se tomó la referencia de este pago.",
    )
    fecha = models.DateField()
    concepto = models.CharField(max_length=24, choices=Concepto.choices)
    monto = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    monto_recargo_incluido = models.DecimalField(
        "Recargo administrativo incluido",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=(
            "Parte del monto total que corresponde a recargo administrativo "
            "(días de gracia vencidos). No reduce el capital del contrato."
        ),
    )
    referencia = models.CharField(max_length=120, blank=True)
    voucher_transferencia = models.FileField(
        "Voucher de transferencia (PDF)",
        upload_to="pagos/vouchers/%Y/%m/",
        blank=True,
        null=True,
        help_text="Comprobante PDF (o imagen) de la transferencia/depósito bancario.",
    )
    notas = models.TextField(blank=True)
    cuotas_incluidas = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(200)],
        help_text="Si el concepto es cuota de financiamiento: cuántas cuotas consecutivas (en orden de vencimiento) liquida este pago.",
    )
    validacion_abono = models.CharField(
        max_length=12,
        choices=ValidacionAbono.choices,
        default=ValidacionAbono.NO_APLICA,
        db_index=True,
        verbose_name="Validación de abono",
        help_text="Reserva, prima, cuotas a plazos y abono a capital: gerencia confirma el depósito en cuenta antes de emitir recibo al cliente.",
    )
    validado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_abono_validados",
        verbose_name="Validado por",
    )
    validado_en = models.DateTimeField(null=True, blank=True, verbose_name="Validado en")
    validacion_nota = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Nota de validación",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def __str__(self) -> str:
        return f"{self.fecha} {self.get_concepto_display()} {self.monto}"

    @property
    def requiere_validacion_gerente(self) -> bool:
        return self.concepto in self.CONCEPTOS_CON_VALIDACION

    @property
    def pendiente_validacion_gerente(self) -> bool:
        return self.validacion_abono == self.ValidacionAbono.PENDIENTE

    @property
    def puede_emitir_recibo_cliente(self) -> bool:
        if self.validacion_abono == self.ValidacionAbono.RECHAZADO:
            return False
        if self.requiere_validacion_gerente:
            return self.validacion_abono == self.ValidacionAbono.VALIDADO
        return True

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.concepto in self.CONCEPTOS_CON_VALIDACION:
                if self.validacion_abono in (
                    "",
                    None,
                    self.ValidacionAbono.NO_APLICA,
                ):
                    self.validacion_abono = self.ValidacionAbono.PENDIENTE
            else:
                self.validacion_abono = self.ValidacionAbono.NO_APLICA
        super().save(*args, **kwargs)


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


class FormatoAceptacion(models.Model):
    """
    Formato de aceptación (documento impreso en pantalla) con firmas para el PDF.
    El vínculo con contrato es opcional: el formulario puede usarse solo con los campos del modelo.
    """

    class TipoFinanciamiento(models.TextChoices):
        A_PLAZOS = "A_PLAZOS", "Con Financiamiento (A Plazos)"
        CONTADO = "CONTADO", "Contado"

    contrato = models.ForeignKey(
        Contrato,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="formatos_aceptacion",
        verbose_name="Contrato (opcional)",
    )
    numero_formulario = models.PositiveIntegerField(
        "Nº formulario",
        unique=True,
        db_index=True,
        help_text="Número del formato impreso. Debe coincidir con el del PDF físico que se suba.",
    )

    nombre_cliente = models.CharField("Nombre del cliente", max_length=200)
    lugar_nacimiento = models.CharField("Lugar de nacimiento", max_length=200, blank=True)
    fecha_nacimiento = models.DateField("Fecha de nacimiento", null=True, blank=True)
    dui_numero = models.CharField("No. DUI", max_length=30, blank=True)
    dui_exp_lugar = models.CharField("Lugar de exp. DUI", max_length=120, blank=True)
    dui_exp_fecha = models.DateField("Fecha de exp. DUI", null=True, blank=True)
    nit_numero = models.CharField("NIT", max_length=30, blank=True)
    direccion_domicilio = models.TextField("Dirección de domicilio", blank=True)
    telefono_domicilio = models.CharField("Teléfono (domicilio)", max_length=40, blank=True)
    direccion_notificacion = models.TextField("Dirección para notificación", blank=True)
    telefono_notificacion = models.CharField("Teléfono (notificación)", max_length=40, blank=True)
    trabaja_lo_propio = models.CharField("Trabaja en lo propio", max_length=200, blank=True)
    nombre_empresa_trabajo = models.CharField(
        "Nombre de la empresa donde trabaja", max_length=200, blank=True
    )
    direccion_trabajo = models.TextField("Dirección / trabajo", blank=True)
    telefono_trabajo = models.CharField("Teléfono (trabajo)", max_length=40, blank=True)
    cargo = models.CharField("Cargo que desempeña", max_length=120, blank=True)
    sueldo = models.DecimalField("Sueldo $", max_digits=14, decimal_places=2, null=True, blank=True)
    num_familia_grupo = models.PositiveSmallIntegerField(
        "No. personas del grupo familiar", null=True, blank=True
    )
    num_personas_trabajan = models.PositiveSmallIntegerField(
        "No. personas que trabajan", null=True, blank=True
    )
    num_personas_estudian = models.PositiveSmallIntegerField(
        "No. personas que estudian", null=True, blank=True
    )

    ref_com_nombre_1 = models.CharField("Ref. comercial — empresa 1", max_length=200, blank=True)
    ref_com_tel_1 = models.CharField("Ref. comercial — tel. 1", max_length=40, blank=True)
    ref_com_obs_1 = models.CharField("Ref. comercial — observación 1", max_length=200, blank=True)
    ref_com_nombre_2 = models.CharField("Ref. comercial — empresa 2", max_length=200, blank=True)
    ref_com_tel_2 = models.CharField("Ref. comercial — tel. 2", max_length=40, blank=True)
    ref_com_obs_2 = models.CharField("Ref. comercial — observación 2", max_length=200, blank=True)
    ref_com_nombre_3 = models.CharField("Ref. comercial — empresa 3", max_length=200, blank=True)
    ref_com_tel_3 = models.CharField("Ref. comercial — tel. 3", max_length=40, blank=True)
    ref_com_obs_3 = models.CharField("Ref. comercial — observación 3", max_length=200, blank=True)

    ref_per_nombre_1 = models.CharField("Ref. personal — nombre 1", max_length=200, blank=True)
    ref_per_tel_1 = models.CharField("Ref. personal — tel. 1", max_length=40, blank=True)
    ref_per_obs_1 = models.CharField("Ref. personal — observación 1", max_length=200, blank=True)
    ref_per_nombre_2 = models.CharField("Ref. personal — nombre 2", max_length=200, blank=True)
    ref_per_tel_2 = models.CharField("Ref. personal — tel. 2", max_length=40, blank=True)
    ref_per_obs_2 = models.CharField("Ref. personal — observación 2", max_length=200, blank=True)
    ref_per_nombre_3 = models.CharField("Ref. personal — nombre 3", max_length=200, blank=True)
    ref_per_tel_3 = models.CharField("Ref. personal — tel. 3", max_length=40, blank=True)
    ref_per_obs_3 = models.CharField("Ref. personal — observación 3", max_length=200, blank=True)

    nombre_proyecto = models.CharField("Nombre del proyecto", max_length=200, blank=True)
    direccion_terreno = models.TextField("Dirección (terreno)", blank=True)

    num_lote = models.CharField("No. de lote", max_length=80, blank=True)
    poligono_txt = models.CharField("Polígono", max_length=120, blank=True)
    area_m2_txt = models.CharField("Área m²", max_length=40, blank=True)
    area_v2_txt = models.CharField("Área v²", max_length=40, blank=True)
    valor_inmueble = models.DecimalField(
        "Valor del inmueble", max_digits=14, decimal_places=2, null=True, blank=True
    )
    prima_1 = models.DecimalField(
        "Reserva $",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Monto de la reserva (se paga al llenar el formato).",
    )
    prima_1_fecha = models.DateField(
        "Fecha de pago de reserva",
        null=True,
        blank=True,
    )
    prima_2 = models.DecimalField(
        "Prima a pagar $",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Monto de la prima / enganche (se paga después de la reserva).",
    )
    prima_2_fecha = models.DateField(
        "Fecha de pago de prima",
        null=True,
        blank=True,
    )
    tipo_financiamiento = models.CharField(
        "Tipo de financiamiento",
        max_length=20,
        choices=TipoFinanciamiento.choices,
        default=TipoFinanciamiento.A_PLAZOS,
        blank=True,
        db_index=True,
        help_text="Con financiamiento a plazos o pago de contado.",
    )
    valor_financiamiento = models.DecimalField(
        "Valor del financiamiento", max_digits=14, decimal_places=2, null=True, blank=True
    )
    letra_mensual = models.DecimalField(
        "Cuota meses 1–12 (sin interés)",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="La escribe el vendedor. Meses 1–12 sin interés; desde el mes 13 ya va con intereses.",
    )
    plazo_txt = models.CharField("Plazo", max_length=80, blank=True)
    num_cuota_txt = models.CharField("No. cuota", max_length=40, blank=True)
    interes_txt = models.CharField("Interés", max_length=80, blank=True)
    fecha_primera_cuota = models.DateField("Fecha pago primera cuota", null=True, blank=True)
    fecha_pago_mensual = models.CharField("Fecha de pago mensual", max_length=80, blank=True)
    lugar_pago = models.CharField("Lugar de pago", max_length=200, blank=True)
    observaciones_financiamiento = models.TextField(
        "Observaciones (financiamiento)",
        blank=True,
        help_text="Detalles especiales. Frases como «sin interés», «0 %» o «10 años» pueden completar plazo o interés si esos campos están vacíos al guardar.",
    )

    ben_nombre_1 = models.CharField("Beneficiario 1 — nombre", max_length=200, blank=True)
    ben_parentesco_1 = models.CharField("Beneficiario 1 — parentesco", max_length=80, blank=True)
    ben_porcentaje_1 = models.DecimalField(
        "Beneficiario 1 — %",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    ben_nombre_2 = models.CharField("Beneficiario 2 — nombre", max_length=200, blank=True)
    ben_parentesco_2 = models.CharField("Beneficiario 2 — parentesco", max_length=80, blank=True)
    ben_porcentaje_2 = models.DecimalField(
        "Beneficiario 2 — %",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )

    elaborado_por = models.CharField("Elaborado por", max_length=120, blank=True)
    lugar_y_fecha = models.CharField("Lugar y fecha", max_length=200, blank=True)

    firma_aceptante = models.ImageField(
        "Firma aceptante (cliente)",
        upload_to="formatos_aceptacion/firmas/%Y/%m/",
        blank=True,
    )
    firma_vendedor = models.ImageField(
        "Firma vendedor",
        upload_to="formatos_aceptacion/firmas/%Y/%m/",
        blank=True,
    )
    firma_autorizado = models.ImageField(
        "Firma autorizado",
        upload_to="formatos_aceptacion/firmas/%Y/%m/",
        blank=True,
    )
    dui_cliente_archivo = models.FileField(
        "DUI del cliente (frente y reverso)",
        upload_to="formatos_aceptacion/dui/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf"],
                message="El DUI debe ser un archivo PDF.",
            )
        ],
    )
    formato_aceptacion_fisico = models.FileField(
        "Formato de aceptación en físico",
        upload_to="formatos_aceptacion/fisico/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf"],
                message="Use PDF del formato físico (para validar el número).",
            )
        ],
    )
    boucher_pago_reserva = models.FileField(
        "Voucher de Reserva",
        upload_to="formatos_aceptacion/vouchers/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "jpg", "jpeg", "png"],
                message="Use PDF, JPG o PNG.",
            )
        ],
    )
    promesa_venta_escaneada = models.FileField(
        "Promesa de venta escaneada",
        upload_to="formatos_aceptacion/promesas/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg"],
                message="Use PDF, JPG o PNG.",
            )
        ],
    )
    contrato_compraventa_escaneado = models.FileField(
        "Contrato de compraventa (PDF)",
        upload_to="formatos_aceptacion/compraventa/%Y/%m/",
        blank=True,
        help_text="Escritura o contrato de compraventa firmado; forma parte del expediente del formato.",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg"],
                message="Use PDF, JPG o PNG.",
            )
        ],
    )

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="formatos_aceptacion_creados",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-numero_formulario"]
        verbose_name = "Formato de aceptación"
        verbose_name_plural = "Formatos de aceptación"
        constraints = [
            models.UniqueConstraint(
                fields=("contrato",),
                condition=models.Q(contrato__isnull=False),
                name="formato_aceptacion_contrato_id_uniq_when_set",
            ),
        ]

    def __str__(self) -> str:
        if self.contrato_id:
            return f"Formato #{self.numero_formulario} — {self.contrato.numero}"
        return f"Formato #{self.numero_formulario} — (sin contrato)"

    @property
    def firmas_completas(self) -> bool:
        """True si DUI y formato físico están guardados (requisito para PDF)."""
        from inmobiliaria.formato_aceptacion_db import (
            formato_aceptacion_adjuntos_columns_ready,
        )

        if not formato_aceptacion_adjuntos_columns_ready():
            return False
        for attr in (
            "dui_cliente_archivo",
            "formato_aceptacion_fisico",
        ):
            f = getattr(self, attr)
            if not f or not f.name:
                return False
        return True

    def save(self, *args, **kwargs):
        # El vendedor ingresa el número; no se autoasigna.
        super().save(*args, **kwargs)


class ParametroMora(models.Model):
    """
    Recargo administrativo (monto fijo), no interés diario.
    Si una cuota no se paga y pasan los días de gracia, al mes siguiente
    corresponde cobrar la cuota + el recargo definido aquí.
    """

    nombre = models.CharField(max_length=80, default="Default")
    monto_recargo = models.DecimalField(
        "Monto del recargo administrativo",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Monto fijo que ustedes definen. Se suma a la cuota del mes siguiente "
        "si el mes anterior quedó sin pagar después de los días de gracia.",
    )
    tasa_diaria_porcentaje = models.DecimalField(
        max_digits=8,
        decimal_places=6,
        default=Decimal("0"),
        blank=True,
        help_text="Obsoleto: ya no se usa. El cobro es un monto fijo (recargo administrativo).",
    )
    dias_gracia = models.PositiveSmallIntegerField(
        "Días de gracia",
        default=0,
        help_text="Días naturales después de la fecha de vencimiento de la cuota "
        "antes de aplicar el recargo administrativo. Ej.: si vence el 5 y gracia = 5, "
        "el recargo aplica a partir del 11; en el siguiente mes se cobra cuota + recargo.",
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Parámetro de recargo administrativo"
        verbose_name_plural = "Parámetros de recargo administrativo"

    def __str__(self) -> str:
        return self.nombre
