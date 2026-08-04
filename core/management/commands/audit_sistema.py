"""
Auditoría integral: base de datos, integridad referencial y persistencia.
Uso: python manage.py audit_sistema
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from inmobiliaria.models import (
    Cliente,
    Contrato,
    FormatoAceptacion,
    Inmueble,
    InmuebleDetalleCasaAlquiler,
    InmuebleDetalleLocalAlquiler,
    Pago,
    Proyecto,
    Vendedor,
)


class Command(BaseCommand):
    help = "Audita conexión BD, migraciones, conteos e integridad de datos guardados."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix-orphans",
            action="store_true",
            help="Elimina inmuebles en alquiler sin ficha (huérfanos técnicos).",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.HTTP_INFO("=== Auditoría Paredes Bienes Raíces ===\n"))
        ok = True

        ok &= self._check_database()
        ok &= self._check_migrations()
        self._report_counts()
        issues = self._check_integrity()
        ok &= len(issues) == 0
        if issues:
            self.stdout.write(self.style.WARNING("\n--- Problemas de integridad ---"))
            for msg in issues:
                self.stdout.write(f"  • {msg}")
            if options["fix_orphans"]:
                n = self._fix_orphan_rentals()
                self.stdout.write(self.style.SUCCESS(f"  Corregidos: {n} inmueble(s) huérfano(s) eliminado(s)."))
        else:
            self.stdout.write(self.style.SUCCESS("\nIntegridad referencial: OK"))

        ok &= self._probe_save_rollback()
        self.stdout.write("")
        if ok:
            self.stdout.write(self.style.SUCCESS("RESULTADO: sistema OK — la BD responde y los guardados son coherentes."))
        else:
            self.stdout.write(self.style.ERROR("RESULTADO: revise los puntos marcados arriba."))

    def _check_database(self) -> bool:
        db = settings.DATABASES["default"]
        self.stdout.write("--- Base de datos ---")
        self.stdout.write(f"  Motor: {db.get('ENGINE', '').split('.')[-1]}")
        self.stdout.write(f"  Nombre: {db.get('NAME')}")
        self.stdout.write(f"  Host: {db.get('HOST') or 'localhost'}")
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
            self.stdout.write(self.style.SUCCESS("  Conexión: OK"))
            return True
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Conexión: FALLO ({exc})"))
            return False

    def _check_migrations(self) -> bool:
        self.stdout.write("\n--- Migraciones ---")
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            self.stdout.write(self.style.ERROR(f"  Pendientes: {len(plan)} migración(es)"))
            for mig, _ in plan[:10]:
                self.stdout.write(f"    - {mig.app_label}.{mig.name}")
            return False
        self.stdout.write(self.style.SUCCESS("  Todas aplicadas: OK"))
        return True

    def _report_counts(self) -> None:
        self.stdout.write("\n--- Registros en BD (datos reales) ---")
        rows = [
            ("Proyectos", Proyecto.objects.count()),
            ("Clientes", Cliente.objects.count()),
            ("Inmuebles (total)", Inmueble.objects.count()),
            ("  · en alquiler", Inmueble.objects.filter(en_alquiler=True).count()),
            ("  · venta", Inmueble.objects.filter(en_alquiler=False).count()),
            ("Contratos", Contrato.objects.count()),
            ("Pagos", Pago.objects.count()),
            ("Asesores de ventas", Vendedor.objects.count()),
            ("Formatos aceptación", FormatoAceptacion.objects.count()),
        ]
        try:
            from docs.models import DocumentoEmitido

            rows.append(("Documentos emitidos (PDF)", DocumentoEmitido.objects.count()))
            rows.append(
                (
                    "  · sin archivo PDF",
                    DocumentoEmitido.objects.filter(pdf_file="").count()
                    + DocumentoEmitido.objects.filter(pdf_file__isnull=True).count(),
                )
            )
        except Exception:
            pass
        for label, n in rows:
            self.stdout.write(f"  {label}: {n}")

    def _check_integrity(self) -> list[str]:
        issues: list[str] = []

        # Locales en alquiler sin ficha
        loc_orphans = (
            Inmueble.objects.filter(en_alquiler=True, tipo=Inmueble.Tipo.LOCAL)
            .exclude(pk__in=InmuebleDetalleLocalAlquiler.objects.values("inmueble_id"))
        )
        n_loc = loc_orphans.count()
        if n_loc:
            issues.append(f"{n_loc} local(es) en alquiler sin ficha (InmuebleDetalleLocalAlquiler).")

        # Casas en alquiler sin ficha
        casa_orphans = (
            Inmueble.objects.filter(
                en_alquiler=True,
                tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA),
            )
            .exclude(pk__in=InmuebleDetalleCasaAlquiler.objects.values("inmueble_id"))
        )
        n_casa = casa_orphans.count()
        if n_casa:
            issues.append(f"{n_casa} casa(s) en alquiler sin ficha (InmuebleDetalleCasaAlquiler).")

        # Contratos activos sin inmueble
        n_con = Contrato.objects.filter(inmueble__isnull=True).count()
        if n_con:
            issues.append(f"{n_con} contrato(s) sin inmueble vinculado.")

        # Pagos huérfanos
        n_pago = Pago.objects.filter(contrato__isnull=True).count()
        if n_pago:
            issues.append(f"{n_pago} pago(s) sin contrato.")

        try:
            from docs.models import DocumentoEmitido

            sin_pdf = DocumentoEmitido.objects.filter(pdf_file="").count()
            if sin_pdf:
                issues.append(
                    f"{sin_pdf} documento(s) emitido(s) sin PDF en disco (puede regenerarse al descargar)."
                )
        except Exception:
            pass

        if not Proyecto.objects.exists():
            issues.append("No hay proyectos: el alta de alquileres requiere al menos uno.")

        return issues

    def _fix_orphan_rentals(self) -> int:
        loc_ids = (
            Inmueble.objects.filter(en_alquiler=True, tipo=Inmueble.Tipo.LOCAL)
            .exclude(pk__in=InmuebleDetalleLocalAlquiler.objects.values("inmueble_id"))
            .values_list("pk", flat=True)
        )
        casa_ids = (
            Inmueble.objects.filter(
                en_alquiler=True,
                tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA),
            )
            .exclude(pk__in=InmuebleDetalleCasaAlquiler.objects.values("inmueble_id"))
            .values_list("pk", flat=True)
        )
        ids = list(loc_ids) + list(casa_ids)
        if ids:
            return Inmueble.objects.filter(pk__in=ids).delete()[0]
        return 0

    def _probe_save_rollback(self) -> bool:
        """Prueba que INSERT/ROLLBACK funciona (no deja basura)."""
        self.stdout.write("\n--- Prueba de guardado (rollback) ---")
        proyecto = Proyecto.objects.order_by("pk").first()
        if not proyecto:
            self.stdout.write(self.style.WARNING("  Omitida: no hay proyecto para probar."))
            return True
        tag = f"AUDIT-{timezone.now().strftime('%H%M%S')}"
        try:
            with transaction.atomic():
                c = Cliente.objects.create(
                    nombres="Audit",
                    apellidos="Temporal",
                    telefono=tag,
                )
                assert Cliente.objects.filter(pk=c.pk).exists()
                transaction.set_rollback(True)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Prueba de guardado: FALLO ({exc})"))
            return False
        if Cliente.objects.filter(telefono=tag).exists():
            self.stdout.write(self.style.ERROR("  Rollback no funcionó: quedó registro de prueba."))
            return False
        self.stdout.write(self.style.SUCCESS("  INSERT + rollback: OK (la BD persiste y revierte bien)."))
        return True
