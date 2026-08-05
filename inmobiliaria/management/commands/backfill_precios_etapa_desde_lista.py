"""Copia precio_lista → precios de etapa vacíos (carga inicial / datos viejos)."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from inmobiliaria.models import Inmueble


class Command(BaseCommand):
    help = (
        "En lotes con precio_lista y sin precio de etapa, copia lista a "
        "preventa / promocional / pos_preventa (solo campos vacíos)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo muestra cuántos se actualizarían, sin guardar.",
        )

    def handle(self, *args, **options):
        dry = bool(options.get("dry_run"))
        qs = (
            Inmueble.objects.filter(tipo=Inmueble.Tipo.LOTE)
            .filter(precio_lista__isnull=False)
            .filter(
                Q(precio_preventa__isnull=True)
                | Q(precio_promocional__isnull=True)
                | Q(precio_pos_preventa__isnull=True)
            )
            .order_by("pk")
        )
        updated = 0
        for inv in qs.iterator():
            fields: list[str] = []
            pl = inv.precio_lista
            if inv.precio_preventa is None:
                inv.precio_preventa = pl
                fields.append("precio_preventa")
            if inv.precio_promocional is None:
                inv.precio_promocional = pl
                fields.append("precio_promocional")
            if inv.precio_pos_preventa is None:
                inv.precio_pos_preventa = pl
                fields.append("precio_pos_preventa")
            if not fields:
                continue
            updated += 1
            self.stdout.write(
                f"{'DRY ' if dry else ''}"
                f"lote id={inv.pk} {inv.codigo}: copia lista ${pl} → {', '.join(fields)}"
            )
            if not dry:
                inv.save(update_fields=fields)
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Simulación: ' if dry else ''}"
                f"{updated} lote(s) con precios de etapa completados desde lista."
            )
        )
