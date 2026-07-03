"""Migra adjuntos de un backend de almacenamiento a otro (ej. Nextcloud → CDN/S3).

Idempotente y resumible: procesa archivo por archivo y actualiza
(storage_backend, storage_key) al terminar cada uno.

Uso::

    python manage.py migrate_attachments --from nextcloud --to s3 [--delete-source] [--batch 100]
"""
from django.core.management.base import BaseCommand, CommandError

from attachments.backends import get_backend
from attachments.models import Attachment


class Command(BaseCommand):
    help = 'Migra los archivos de adjuntos de un backend a otro.'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='src', required=True, help='Backend origen')
        parser.add_argument('--to', dest='dst', required=True, help='Backend destino')
        parser.add_argument('--delete-source', action='store_true',
                            help='Borra el archivo del origen tras copiarlo.')
        parser.add_argument('--batch', type=int, default=0,
                            help='Procesar como máximo N adjuntos (0 = todos).')

    def handle(self, *args, **opts):
        src_name, dst_name = opts['src'], opts['dst']
        try:
            src = get_backend(src_name)
            dst = get_backend(dst_name)
        except Exception as exc:
            raise CommandError(f'No se pudo inicializar backend: {exc}')

        qs = Attachment.objects.filter(storage_backend=src_name).order_by('pk')
        if opts['batch']:
            qs = qs[:opts['batch']]

        total = qs.count()
        self.stdout.write(f'Procesando {total} adjunto(s): {src_name} → {dst_name}')
        ok = errors = 0

        for att in qs:
            try:
                if src_name == dst_name:
                    # No-op de verificación: confirmar que el archivo existe.
                    if not src.exists(att.storage_key):
                        raise FileNotFoundError(att.storage_key)
                else:
                    stream, content_type = src.open(att.storage_key)
                    new_key = dst.save(att.storage_key, stream, content_type or att.mime_type)
                    if opts['delete_source']:
                        src.delete(att.storage_key)
                    att.storage_backend = dst_name
                    att.storage_key = new_key
                    att.save(update_fields=['storage_backend', 'storage_key'])
                ok += 1
            except Exception as exc:
                errors += 1
                self.stderr.write(f'  ✕ #{att.pk} {att.filename}: {exc}')

        self.stdout.write(self.style.SUCCESS(f'Listo. OK={ok} errores={errors}'))
