"""Crea un formato de aceptación de prueba completo (4 años a plazos)."""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone

from inmobiliaria.forms_web import FormatoAceptacionForm
from inmobiliaria.models import FormatoAceptacion, Inmueble, Vendedor
from inmobiliaria.validacion_gerencia import aplicar_validacion_formato_o_plan

User = get_user_model()


def main() -> None:
    admin = User.objects.filter(username="admin", is_superuser=True).first()
    if admin is None:
        admin = User.objects.filter(is_superuser=True).first()
    if admin is None:
        raise SystemExit("No hay superusuario local (admin).")

    inv = (
        Inmueble.objects.select_related("proyecto", "poligono")
        .filter(proyecto__nombre__icontains="VALLE", codigo="1")
        .first()
    )
    if inv is None:
        inv = Inmueble.objects.select_related("proyecto", "poligono").first()
    if inv is None:
        raise SystemExit("No hay inmuebles en la BD local.")

    proy = inv.proyecto
    vendedor = Vendedor.objects.filter(activo=True).order_by("id").first()
    elaborado = (vendedor.nombre_completo if vendedor else "OSCAR PAREDES").strip()

    valor = (inv.precio_preventa or inv.precio_lista or Decimal("25000")).quantize(
        Decimal("0.01")
    )
    pct_res = Decimal(proy.porcentaje_reserva or 0) / Decimal("100")
    pct_prima = Decimal(proy.porcentaje_prima or 0) / Decimal("100")
    reserva = (valor * pct_res).quantize(Decimal("0.01"))
    prima_total = (valor * pct_prima).quantize(Decimal("0.01"))
    prima = (prima_total - reserva).quantize(Decimal("0.01"))
    financiamiento = (valor - prima_total).quantize(Decimal("0.01"))
    cuota = (financiamiento / Decimal("48")).quantize(Decimal("0.01"))

    num_fmt = 1
    while FormatoAceptacion.objects.filter(numero_formulario=num_fmt).exists():
        num_fmt += 1

    hoy = timezone.localdate()
    data = {
        "numero_formulario": str(num_fmt),
        "nombre_cliente": "Juan Carlos Pérez López",
        "lugar_nacimiento": "San Salvador, El Salvador",
        "fecha_nacimiento": "1985-03-15",
        "dui_numero": "04567891-2",
        "dui_exp_lugar": "San Salvador",
        "dui_exp_fecha": "2018-06-20",
        "nit_numero": "0614-120586-101-5",
        "direccion_domicilio": "Colonia Escalón, Calle La Mascota #123, San Salvador",
        "telefono_domicilio": "+503 7012 3456",
        "direccion_notificacion": "Colonia Escalón, Calle La Mascota #123, San Salvador",
        "telefono_notificacion": "+503 7012 3456",
        "trabaja_lo_propio": "No",
        "nombre_empresa_trabajo": "Distribuidora La Ceiba S.A. de C.V.",
        "direccion_trabajo": "Zona Industrial, Soyapango",
        "telefono_trabajo": "+503 2234 5678",
        "cargo": "Gerente de ventas",
        "sueldo": "1850.00",
        "num_familia_grupo": "4",
        "num_personas_trabajan": "2",
        "num_personas_estudian": "2",
        "ref_com_nombre_1": "Ferretería El Constructor",
        "ref_com_tel_1": "+503 7123 4567",
        "ref_com_obs_1": "Cliente desde 2019",
        "ref_com_nombre_2": "Banco Agrícola",
        "ref_com_tel_2": "+503 2210 0000",
        "ref_com_obs_2": "Cuenta activa",
        "ref_per_nombre_1": "María Elena Pérez",
        "ref_per_tel_1": "+503 7890 1234",
        "ref_per_obs_1": "Hermana",
        "ref_per_nombre_2": "Roberto López",
        "ref_per_tel_2": "+503 7011 9988",
        "ref_per_obs_2": "Cuñado",
        "nombre_proyecto": proy.nombre,
        "direccion_terreno": proy.direccion or "Residencial Valle Alegre, La Libertad",
        "num_lote": inv.codigo_display,
        "poligono_txt": inv.poligono.nombre if inv.poligono_id else "",
        "area_m2_txt": str(inv.area_m2 or ""),
        "area_v2_txt": str(inv.area_varas_cuadradas or ""),
        "valor_inmueble_sistema": str(valor),
        "valor_inmueble": str(valor),
        "etapa_venta_aplicada": "PREVENTA",
        "tipo_financiamiento": FormatoAceptacion.TipoFinanciamiento.A_PLAZOS,
        "prima_1": str(reserva),
        "prima_1_fecha": hoy.isoformat(),
        "prima_2": str(prima),
        "prima_2_fecha": (date(hoy.year, hoy.month, min(hoy.day + 15, 28))).isoformat(),
        "valor_financiamiento": str(financiamiento),
        "letra_mensual": str(cuota),
        "plazo_txt": "4",
        "num_cuota_txt": "48",
        "interes_txt": "12",
        "fecha_primera_cuota": date(hoy.year, hoy.month + 1 if hoy.month < 12 else 1, 5).isoformat(),
        "fecha_pago_mensual": "5 de cada mes",
        "lugar_pago": "Oficinas Paredes Desarrollos Inmobiliarios, San Salvador",
        "observaciones_financiamiento": (
            "Financiamiento a 4 años. Meses 1–12 sin interés; "
            "desde el mes 13 aplica 12% anual. Formato de prueba local."
        ),
        "ben_nombre_1": "María Elena Pérez",
        "ben_parentesco_1": "Hermana",
        "ben_porcentaje_1": "100",
        "elaborado_por": elaborado,
        "lugar_y_fecha": f"San Salvador, {hoy.strftime('%d/%m/%Y')}",
    }

    form = FormatoAceptacionForm(data=data, user=admin)
    if not form.is_valid():
        print("Errores del formulario:")
        for field, errs in form.errors.items():
            print(f"  {field}: {errs}")
        raise SystemExit(1)

    fmt = form.save(commit=False)
    fmt.creado_por = admin
    aplicar_validacion_formato_o_plan(fmt, admin)
    fmt.save()

    edit_url = f"/app/formato-aceptacion/{fmt.pk}/editar/"
    print(f"Formato #{fmt.numero_formulario:04d} creado (pk={fmt.pk})")
    print(f"Cliente: {fmt.nombre_cliente}")
    print(f"Lote: {fmt.num_lote} — {fmt.nombre_proyecto}")
    print(f"Valor: ${fmt.valor_inmueble} | Plazo: {fmt.plazo_txt} años ({fmt.num_cuota_txt} cuotas)")
    print(f"Cuota meses 1-12: ${fmt.letra_mensual} | Interés: {fmt.interes_txt}%")
    print(f"Reserva: ${fmt.prima_1} | Prima: ${fmt.prima_2} | Financiamiento: ${fmt.valor_financiamiento}")
    print(f"Validación gerencia: {fmt.get_validacion_gerencia_display()}")
    print(f"Ver en: http://127.0.0.1:8001{edit_url}")


if __name__ == "__main__":
    main()
