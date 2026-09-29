"""Multi-empresa, paso 2: crea la empresa inicial y le asigna TODO lo existente.

Hasta acá el sistema era de una sola empresa (Embol), así que cada fila operativa
pasa a esa empresa. Los tickets se renumeran de `SKY-####` a `EMBOL-####` (pedido
explícito) conservando el número: `SKY-0014-1` → `EMBOL-0014-1`. Los adjuntos ya subidos
siguen accesibles porque `Attachment.storage_key` está persistido.

En una base vacía (instalación nueva, tests) crea igual la empresa `embol`: el
superuser la renombra desde /empresas/.
"""
import os
import re
import sys

from django.core.files.storage import default_storage
from django.db import migrations, models
from django.db.models import Value
from django.db.models.functions import Concat, Substr

OLD_PREFIX = 'SKY'
COMPANY = {'name': 'Embol', 'slug': 'embol', 'ticket_prefix': 'EMBOL', 'brand_name': 'Embol'}
_LEGACY_NUM = re.compile(rf'^{OLD_PREFIX}-(\d+)')


def _copy_logo(company, branding, attr):
    name = getattr(branding, attr).name
    if not name or not default_storage.exists(name):
        return
    ext = os.path.splitext(name)[1].lower()
    with default_storage.open(name, 'rb') as f:
        new_name = default_storage.save(f'branding/{company.slug}/{attr.replace("_", "-")}{ext}', f)
    setattr(company, attr, new_name)


def forwards(apps, schema_editor):
    Company = apps.get_model('accounts', 'Company')
    if Company.objects.exists():
        return
    Profile = apps.get_model('accounts', 'Profile')
    AllowedDomain = apps.get_model('accounts', 'AllowedDomain')
    AllowedEmail = apps.get_model('accounts', 'AllowedEmail')
    RolePermission = apps.get_model('accounts', 'RolePermission')
    NextcloudOAuthConfig = apps.get_model('accounts', 'NextcloudOAuthConfig')
    BrandingConfig = apps.get_model('accounts', 'BrandingConfig')
    Project = apps.get_model('tickets', 'Project')
    Label = apps.get_model('tickets', 'Label')
    Ticket = apps.get_model('tickets', 'Ticket')
    Attachment = apps.get_model('attachments', 'Attachment')
    NextcloudConfig = apps.get_model('attachments', 'NextcloudConfig')

    seq = 0
    for code in Ticket.objects.exclude(code='').values_list('code', flat=True):
        m = _LEGACY_NUM.match(code)
        if m:
            seq = max(seq, int(m.group(1)))
    company = Company.objects.create(ticket_seq=seq, **COMPANY)

    # Renombre de códigos: 'SKY-' (4 chars) → 'EMBOL-'; Substr es 1-based.
    Ticket.objects.filter(code__startswith=f'{OLD_PREFIX}-').update(
        code=Concat(Value(f'{company.ticket_prefix}-'), Substr('code', len(OLD_PREFIX) + 2),
                    output_field=models.CharField()),
    )

    branding = BrandingConfig.objects.filter(pk=1).first()
    if branding:
        try:
            _copy_logo(company, branding, 'logo_light')
            _copy_logo(company, branding, 'logo_dark')
            company.save(update_fields=['logo_light', 'logo_dark'])
        except Exception as exc:  # noqa: BLE001 — un logo perdido no debe frenar el migrate
            print(f'[0021] no se pudieron copiar los logos: {exc}', file=sys.stderr)

    # El superuser es global (sin empresa); todo el resto pasa a la empresa inicial.
    Profile.objects.filter(user__is_superuser=False).update(company=company)
    for Model in (AllowedDomain, AllowedEmail, RolePermission, Project, Label, Ticket, Attachment):
        Model.objects.filter(company__isnull=True).update(company=company)

    for Model in (NextcloudOAuthConfig, NextcloudConfig):
        rows = list(Model.objects.order_by('pk'))
        if rows:
            rows[0].company = company
            rows[0].save(update_fields=['company'])
            Model.objects.exclude(pk=rows[0].pk).delete()  # solo debería existir pk=1
        else:
            Model.objects.create(company=company)


def backwards(apps, schema_editor):
    Company = apps.get_model('accounts', 'Company')
    Ticket = apps.get_model('tickets', 'Ticket')
    company = Company.objects.filter(slug=COMPANY['slug']).first()
    if not company:
        return
    new = f'{company.ticket_prefix}-'
    Ticket.objects.filter(company=company, code__startswith=new).update(
        code=Concat(Value(f'{OLD_PREFIX}-'), Substr('code', len(new) + 1), output_field=models.CharField()),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0020_company_fks_nullable'),
        ('tickets', '0019_company_nullable'),
        ('attachments', '0005_company_nullable'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
