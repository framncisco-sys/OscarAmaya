from django.contrib import admin

from .models import (
    Cliente,
    ClienteDocumento,
    Contrato,
    CuotaProgramada,
    FormatoAceptacion,
    HistorialPrecioInmueble,
    Inmueble,
    InmuebleDetalleCasa,
    InmuebleDetalleCasaAlquiler,
    InmuebleDetalleLocalAlquiler,
    InmuebleImagen,
    Pago,
    ParametroMora,
    Poligono,
    Proyecto,
    Vendedor,
)


class PoligonoInline(admin.TabularInline):
    model = Poligono
    extra = 0


class InmuebleImagenInline(admin.TabularInline):
    model = InmuebleImagen
    extra = 0
    fields = ("imagen", "url", "es_portada", "orden", "descripcion")


class InmuebleDetalleCasaInline(admin.StackedInline):
    model = InmuebleDetalleCasa
    extra = 0
    max_num = 1
    can_delete = True


class InmuebleDetalleLocalAlquilerInline(admin.StackedInline):
    model = InmuebleDetalleLocalAlquiler
    extra = 0
    max_num = 1
    can_delete = True


class InmuebleDetalleCasaAlquilerInline(admin.StackedInline):
    model = InmuebleDetalleCasaAlquiler
    extra = 0
    max_num = 1
    can_delete = True


@admin.register(Proyecto)
class ProyectoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "municipio", "departamento", "activo", "plano_maestro")
    list_filter = ("activo", "departamento")
    search_fields = ("nombre", "direccion")
    inlines = [PoligonoInline]


@admin.register(Poligono)
class PoligonoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "proyecto", "orden", "plano")
    list_filter = ("proyecto",)
    search_fields = ("nombre",)


@admin.register(HistorialPrecioInmueble)
class HistorialPrecioInmuebleAdmin(admin.ModelAdmin):
    list_display = ("inmueble", "precio_anterior", "precio_nuevo", "creado_en")
    list_filter = ("creado_en",)
    readonly_fields = ("inmueble", "precio_anterior", "precio_nuevo", "creado_en")
    ordering = ("-creado_en",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Inmueble)
class InmuebleAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "proyecto",
        "poligono",
        "tipo",
        "estado",
        "en_alquiler",
        "reserva_hasta",
        "precio_lista",
    )
    list_filter = ("proyecto", "tipo", "estado", "poligono")
    search_fields = ("codigo", "notas")
    raw_id_fields = ("inmueble_padre",)
    inlines = [
        InmuebleDetalleCasaInline,
        InmuebleDetalleCasaAlquilerInline,
        InmuebleDetalleLocalAlquilerInline,
        InmuebleImagenInline,
    ]
    fieldsets = (
        (
            "Identificación",
            {
                "fields": (
                    "proyecto",
                    "poligono",
                    "inmueble_padre",
                    "tipo",
                    "estado",
                    "en_alquiler",
                    "codigo",
                ),
            },
        ),
        (
            "Precio y dimensiones",
            {
                "fields": (
                    "precio_lista",
                    "area_varas_cuadradas",
                    "area_m2",
                    "frente_m",
                    "fondo_m",
                ),
            },
        ),
        (
            "Detalle",
            {
                "fields": (
                    "topografia",
                    "servicios_basicos",
                    "latitud",
                    "longitud",
                    "tour_virtual_url",
                    "notas",
                ),
            },
        ),
        (
            "Mapas",
            {
                "fields": ("geometria_json", "geometria_catastral_geojson"),
                "description": (
                    "geometria_json: polígono en coordenadas relativas 0–100 sobre el plano. "
                    "geometria_catastral_geojson: GeoJSON Polygon en WGS84 (lon/lat) para el mapa catastral Leaflet."
                ),
            },
        ),
        (
            "Reserva",
            {"fields": ("cliente_reserva", "reserva_hasta")},
        ),
    )


class ClienteDocumentoInline(admin.TabularInline):
    model = ClienteDocumento
    extra = 0


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("apellidos", "nombres", "dui", "nit", "telefono")
    search_fields = ("nombres", "apellidos", "dui", "nit", "email")
    inlines = [ClienteDocumentoInline]


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0


class CuotaProgramadaInline(admin.TabularInline):
    model = CuotaProgramada
    extra = 1
    fields = ("numero", "vence_en", "monto", "estado", "pago")
    readonly_fields = ("pago",)


@admin.register(Vendedor)
class VendedorAdmin(admin.ModelAdmin):
    list_display = ("apellidos", "nombres", "dui", "telefono", "porcentaje_comision_default", "activo")
    list_filter = ("activo",)
    search_fields = ("nombres", "apellidos", "dui", "email", "telefono")
    raw_id_fields = ("usuario_vinculo",)


@admin.register(Contrato)
class ContratoAdmin(admin.ModelAdmin):
    list_display = (
        "numero",
        "cliente",
        "inmueble",
        "fecha_firma",
        "estado",
        "etapa_comercial",
        "precio_final",
    )
    list_filter = ("estado", "etapa_comercial", "fecha_firma")
    search_fields = ("numero", "cliente__nombres", "cliente__apellidos")
    raw_id_fields = ("cliente", "inmueble")
    inlines = [CuotaProgramadaInline, PagoInline]


@admin.register(CuotaProgramada)
class CuotaProgramadaAdmin(admin.ModelAdmin):
    list_display = ("contrato", "numero", "vence_en", "monto", "estado", "pago")
    list_filter = ("estado", "vence_en")
    search_fields = ("contrato__numero",)
    raw_id_fields = ("contrato", "pago")


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "contrato", "concepto", "cuotas_incluidas", "monto")
    list_filter = ("concepto", "fecha")
    search_fields = ("referencia", "contrato__numero")


@admin.register(FormatoAceptacion)
class FormatoAceptacionAdmin(admin.ModelAdmin):
    list_display = ("numero_formulario", "contrato", "nombre_cliente", "creado_en")
    list_filter = ("creado_en",)
    search_fields = ("nombre_cliente", "contrato__numero")
    raw_id_fields = ("contrato", "creado_por")
    readonly_fields = ("numero_formulario", "creado_en", "actualizado_en")


@admin.register(ParametroMora)
class ParametroMoraAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tasa_diaria_porcentaje", "dias_gracia", "activo")
