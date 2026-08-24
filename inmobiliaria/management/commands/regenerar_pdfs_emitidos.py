"""Regenera en disco todos los PDF de documentos emitidos (recibos, promesas, comisiones)."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from docs.models import DocumentoEmitido, DocumentoTipo
from docs.services import regenerar_pdf_y_persistir


class Command(BaseCommand):
    help = (
        "Vuelve a generar y guardar los PDF de DocumentoEmitido "
        "(aplica plantillas y datos vigentes en media/docs/)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tipo",
            choices=[c.value for c in DocumentoTipo],
            help="Solo un tipo de documento.",
        )
        parser.add_argument(
            "--solo-con-archivo",
            action="store_true",
            help="Omitir documentos que nunca tuvieron pdf_file guardado.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Lista documentos sin regenerar.",
        )

    def handle(self, *args, **options):
        qs = DocumentoEmitido.objects.all().order_by("id")
        if options["tipo"]:
            qs = qs.filter(tipo=options["tipo"])
        if options["solo_con_archivo"]:
            qs = qs.filter(Q(pdf_file__isnull=False) & ~Q(pdf_file=""))

        total = qs.count()
        self.stdout.write(f"Documentos a procesar: {total}")
        if options["dry_run"]:
            for doc in qs.iterator():
                self.stdout.write(f"  {doc.numero} ({doc.get_tipo_display()})")
            return

        ok = 0
        fail = 0
        for doc in qs.iterator():
            try:
                regenerar_pdf_y_persistir(doc)
                ok += 1
                self.stdout.write(
                    self.style.SUCCESS(f"OK  {doc.numero} ({doc.get_tipo_display()})")
                )
            except Exception as exc:
                fail += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"ERR {doc.numero} ({doc.get_tipo_display()}): {exc}"
                    )
                )

        self.stdout.write("")
        if fail:
            self.stdout.write(
                self.style.WARNING(f"Listo: {ok} regenerado(s), {fail} error(es).")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Listo: {ok} PDF regenerado(s) en disco.")
            )
