from core.pbr_icons import PBR_CACHE_VERSION
from inmobiliaria.models import FormatoAceptacion, Cliente, Contrato, Inmueble

print("cache_v", PBR_CACHE_VERSION)
print("formatos", FormatoAceptacion.objects.count())
print("clientes", Cliente.objects.count())
print("contratos", Contrato.objects.count())
print("inmuebles", Inmueble.objects.count())
