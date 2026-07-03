import io

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from tickets.models import Ticket

from . import services
from .backends import get_backend
from .backends.memory import MemoryBackend

User = get_user_model()

OV = dict(
    ATTACHMENT_DEFAULT_BACKEND='memory',
    ATTACHMENT_BACKENDS={'memory': {'BACKEND': 'attachments.backends.memory.MemoryBackend', 'OPTIONS': {}}},
)


def png_bytes(color='red'):
    """PNG real y mínimo — validate_upload ahora decodifica los bytes de las imágenes
    (ver services._verify_image), así que los tests ya no pueden usar bytes cualquiera."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), color).save(buf, 'PNG')
    return buf.getvalue()


class SanitizeTests(TestCase):
    def test_strips_path(self):
        self.assertEqual(services._sanitize('/etc/passwd'), 'passwd')
        self.assertEqual(services._sanitize('../../x.png'), 'x.png')

    def test_all_dots_becomes_archivo(self):
        self.assertEqual(services._sanitize('..'), 'archivo')
        self.assertEqual(services._sanitize('.'), 'archivo')


class ValidateTests(TestCase):
    def test_rejects_disallowed_type(self):
        f = SimpleUploadedFile('a.zip', b'hi', content_type='application/zip')
        with self.assertRaises(ValidationError):
            services.validate_upload(f)

    def test_accepts_image_pdf_and_office(self):
        services.validate_upload(SimpleUploadedFile('a.png', png_bytes(), content_type='image/png'))
        services.validate_upload(SimpleUploadedFile('a.pdf', b'x', content_type='application/pdf'))
        services.validate_upload(SimpleUploadedFile(
            'a.docx', b'x',
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'))

    @override_settings(ATTACHMENT_MAX_SIZE=3)
    def test_rejects_oversize(self):
        f = SimpleUploadedFile('a.png', b'too big', content_type='image/png')
        with self.assertRaises(ValidationError):
            services.validate_upload(f)

    def test_rejects_svg(self):
        f = SimpleUploadedFile('a.svg', b'<svg onload="alert(1)"></svg>', content_type='image/svg+xml')
        with self.assertRaises(ValidationError):
            services.validate_upload(f)

    def test_rejects_image_mime_with_non_image_bytes(self):
        """Content-Type mentido por el cliente: el archivo real no es una imagen decodificable."""
        f = SimpleUploadedFile('fake.png', b'<script>alert(1)</script>', content_type='image/png')
        with self.assertRaises(ValidationError):
            services.validate_upload(f)


@override_settings(**OV)
class StoreTests(TestCase):
    def setUp(self):
        MemoryBackend.clear()
        self.user = User.objects.create_user('u@e.com', 'u@e.com', 'x')
        self.ticket = Ticket.objects.create(title='t', reporter=self.user)

    def test_store_open_delete(self):
        content = png_bytes()
        f = SimpleUploadedFile('foto.png', content, content_type='image/png')
        att = services.store(f, owner=self.user, content_object=self.ticket)
        self.assertEqual(att.storage_backend, 'memory')
        stream, ct = services.open_blob(att)
        self.assertEqual(b''.join(stream), content)
        self.assertEqual(ct, 'image/png')
        services.delete_blob(att)
        self.assertFalse(get_backend('memory').exists(att.storage_key))

    def test_unique_key_on_collision(self):
        a1 = services.store(SimpleUploadedFile('foto.png', png_bytes('red'), content_type='image/png'),
                            owner=self.user, content_object=self.ticket)
        a2 = services.store(SimpleUploadedFile('foto.png', png_bytes('blue'), content_type='image/png'),
                            owner=self.user, content_object=self.ticket)
        self.assertNotEqual(a1.storage_key, a2.storage_key)

    def test_key_is_human_readable(self):
        att = services.store(SimpleUploadedFile('foto.png', png_bytes(), content_type='image/png'),
                             owner=self.user, content_object=self.ticket)
        self.assertTrue(att.storage_key.startswith(f'{self.ticket.key}/'))

    def test_dedup_same_content_same_object(self):
        same = png_bytes()
        services.store(SimpleUploadedFile('a.png', same, content_type='image/png'),
                       owner=self.user, content_object=self.ticket)
        with self.assertRaises(services.DuplicateAttachment):
            services.store(SimpleUploadedFile('other.png', same, content_type='image/png'),
                           owner=self.user, content_object=self.ticket)

    def test_image_thumbnail_generates_png(self):
        import io
        from PIL import Image
        from attachments import thumbnails
        buf = io.BytesIO()
        Image.new('RGB', (12, 12), 'red').save(buf, 'PNG')
        att = services.store(SimpleUploadedFile('r.png', buf.getvalue(), content_type='image/png'),
                             owner=self.user, content_object=self.ticket)
        png = thumbnails.get_thumbnail(att, 64)
        self.assertTrue(png and png[:4] == b'\x89PNG')


@override_settings(**OV)
class CascadeDeleteTests(TestCase):
    """Attachment.delete() ya no es un override de Model.delete() sino un receiver de
    post_delete (ver signals.py) — debe correr también cuando el borrado viene por
    cascada (GenericRelation de Comment/Ticket), no solo cuando se llama attachment.delete()
    directo."""

    def setUp(self):
        MemoryBackend.clear()
        self.user = User.objects.create_user('u@e.com', 'u@e.com', 'x')
        self.ticket = Ticket.objects.create(title='t', reporter=self.user)

    def test_cascade_delete_via_comment_removes_blob(self):
        from .models import Attachment
        from tickets.models import Comment
        comment = Comment.objects.create(ticket=self.ticket, body='hola')
        att = services.store(SimpleUploadedFile('f.png', png_bytes(), content_type='image/png'),
                             owner=self.user, content_object=comment)
        key = att.storage_key
        self.assertTrue(get_backend('memory').exists(key))
        comment.delete()
        self.assertFalse(get_backend('memory').exists(key))
        self.assertFalse(Attachment.objects.filter(pk=att.pk).exists())

    def test_blob_delete_failure_rolls_back_the_whole_delete(self):
        from unittest.mock import patch

        from django.db import transaction

        from .models import Attachment
        from tickets.models import Comment
        comment = Comment.objects.create(ticket=self.ticket, body='hola')
        att = services.store(SimpleUploadedFile('f.png', png_bytes(), content_type='image/png'),
                             owner=self.user, content_object=comment)
        with patch.object(MemoryBackend, 'delete', side_effect=RuntimeError('backend caído')):
            with self.assertRaises(RuntimeError):
                # atomic() propio: Model.delete() ya abre uno sin savepoint (nested en el
                # atomic del TestCase), así que sin este savepoint la excepción envenena
                # la transacción del test entero, no solo el delete que estamos probando.
                with transaction.atomic():
                    comment.delete()
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())
        self.assertTrue(Attachment.objects.filter(pk=att.pk).exists())


@override_settings(ATTACHMENT_BACKENDS={
    'nextcloud': {
        'BACKEND': 'attachments.backends.nextcloud.NextcloudBackend',
        'OPTIONS': {
            'base_url': 'https://env.example/dav', 'user': 'envuser',
            'token': 'envtoken', 'root': 'EnvRoot',
        },
    },
})
class NextcloudConfigOverrideTests(TestCase):
    """La config de BD (superuser) pisa a la de .env solo cuando está `enabled`."""

    def test_env_config_used_when_no_db_row(self):
        backend = get_backend('nextcloud')
        self.assertEqual(backend.base_url, 'https://env.example/dav')
        self.assertEqual(backend.user, 'envuser')

    def test_db_config_overrides_when_enabled(self):
        from .models import NextcloudConfig
        NextcloudConfig.objects.create(
            pk=1, enabled=True, base_url='https://db.example/dav',
            user='dbuser', token='dbtoken', root='DbRoot',
        )
        backend = get_backend('nextcloud')
        self.assertEqual(backend.base_url, 'https://db.example/dav')
        self.assertEqual(backend.user, 'dbuser')
        self.assertEqual(backend.token, 'dbtoken')
        self.assertEqual(backend.root, 'DbRoot')

    def test_disabled_db_row_is_ignored(self):
        from .models import NextcloudConfig
        NextcloudConfig.objects.create(
            pk=1, enabled=False, base_url='https://db.example/dav', user='dbuser', token='dbtoken',
        )
        backend = get_backend('nextcloud')
        self.assertEqual(backend.base_url, 'https://env.example/dav')
