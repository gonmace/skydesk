"""Poda thumbnails huérfanos en disco (`private_attachments/thumbnails/`).

Los thumbnails se cachean en disco indexados por sha256 (ver attachments/thumbnails.py) y
NO se borran cuando se borra el Attachment (el mismo sha256 puede estar compartido por otro
adjunto deduplicado, y el archivo es diminuto). Este comando es solo higiene opcional para
liberar espacio de tickets/adjuntos borrados hace tiempo — no es necesario para que el
sistema funcione.

Uso::

    python manage.py prune_thumbnails [--dry-run]
"""
import os

from django.core.management.base import BaseCommand

from attachments.models import Attachment
from attachments.thumbnails import THUMB_ROOT


class Command(BaseCommand):
    help = 'Borra thumbnails en disco cuyo sha256 ya no corresponde a ningún adjunto.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                             help='Solo mostrar qué se borraría, sin borrar nada.')

    def handle(self, *args, **opts):
        if not os.path.isdir(THUMB_ROOT):
            self.stdout.write('No hay carpeta de thumbnails, nada que podar.')
            return

        live_shas = set(Attachment.objects.exclude(sha256='').values_list('sha256', flat=True))
        removed = kept = 0

        for shard in sorted(os.listdir(THUMB_ROOT)):
            shard_path = os.path.join(THUMB_ROOT, shard)
            if not os.path.isdir(shard_path):
                continue
            for name in os.listdir(shard_path):
                # Formato: '<sha256>_<size>.png'
                sha = name.split('_', 1)[0]
                if sha in live_shas:
                    kept += 1
                    continue
                removed += 1
                path = os.path.join(shard_path, name)
                if opts['dry_run']:
                    self.stdout.write(f'[dry-run] borraría {path}')
                else:
                    os.remove(path)

        self.stdout.write(self.style.SUCCESS(
            f'Thumbnails huérfanos {"detectados" if opts["dry_run"] else "borrados"}: '
            f'{removed} (conservados: {kept})',
        ))
