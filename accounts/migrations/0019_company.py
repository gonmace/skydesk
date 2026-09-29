import accounts.models
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0018_brandingconfig'),
    ]

    operations = [
        migrations.CreateModel(
            name='Company',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, verbose_name='Nombre')),
                ('slug', models.SlugField(help_text='Prefijo de todas las rutas de la empresa, ej. "embol" → /embol/. Cambiarlo invalida los links ya enviados por correo.', max_length=31, unique=True, validators=[django.core.validators.RegexValidator('^[a-z][a-z0-9-]{1,30}$', 'Solo minúsculas, números y guiones (2 a 31 caracteres), empezando con una letra.')], verbose_name='Identificador en la URL')),
                ('is_active', models.BooleanField(default=True, help_text='Desactivada: nadie de la empresa puede entrar (sus datos se conservan).', verbose_name='Activa')),
                ('ticket_prefix', models.CharField(help_text='Ej. EMBOL → EMBOL-0001. Cambiarlo no renumera: el correlativo sigue.', max_length=6, unique=True, validators=[django.core.validators.RegexValidator('^[A-Z]{2,6}$', 'Entre 2 y 6 letras mayúsculas, ej. EMBOL.')], verbose_name='Prefijo de tickets')),
                ('ticket_seq', models.PositiveIntegerField(default=0, verbose_name='Último correlativo')),
                ('brand_name', models.CharField(default='SkyDesk', help_text='Título de la pestaña, pantalla de login y firma de los correos.', max_length=60, verbose_name='Nombre de marca')),
                ('logo_light', models.ImageField(blank=True, help_text='PNG/JPG/WEBP, máx. 2 MB. Vacío = logo por defecto.', upload_to=accounts.models._logo_light_path, validators=[accounts.models._validate_logo_size], verbose_name='Logo (tema claro)')),
                ('logo_dark', models.ImageField(blank=True, help_text='Vacío = se usa el logo del tema claro.', upload_to=accounts.models._logo_dark_path, validators=[accounts.models._validate_logo_size], verbose_name='Logo (tema oscuro)')),
                ('favicon', models.FileField(blank=True, help_text='PNG o ICO. Vacío = favicon por defecto.', upload_to=accounts.models._favicon_path, validators=[accounts.models._validate_logo_size, accounts.models._validate_favicon_ext], verbose_name='Favicon')),
                ('primary_color', models.CharField(blank=True, help_text='Botones, links y acentos de marca. Vacío = el del tema por defecto.', max_length=7, validators=[django.core.validators.RegexValidator('^#[0-9A-Fa-f]{6}$', 'Color hexadecimal de 6 dígitos, ej. #E4002B.')], verbose_name='Color primario (claro)')),
                ('primary_color_dark', models.CharField(blank=True, help_text='Vacío = se usa el color primario claro también en modo oscuro.', max_length=7, validators=[django.core.validators.RegexValidator('^#[0-9A-Fa-f]{6}$', 'Color hexadecimal de 6 dígitos, ej. #E4002B.')], verbose_name='Color primario (oscuro)')),
                ('accent_color', models.CharField(blank=True, max_length=7, validators=[django.core.validators.RegexValidator('^#[0-9A-Fa-f]{6}$', 'Color hexadecimal de 6 dígitos, ej. #E4002B.')], verbose_name='Color de acento (claro)')),
                ('accent_color_dark', models.CharField(blank=True, max_length=7, validators=[django.core.validators.RegexValidator('^#[0-9A-Fa-f]{6}$', 'Color hexadecimal de 6 dígitos, ej. #E4002B.')], verbose_name='Color de acento (oscuro)')),
                ('email_from_name', models.CharField(blank=True, help_text='Ej. "Embol Tickets". Vacío = el remitente del servidor.', max_length=100, verbose_name='Nombre del remitente')),
                ('email_from', models.EmailField(blank=True, help_text='Debe estar autorizado en el SMTP del servidor. Vacío = el del servidor.', max_length=254, verbose_name='Correo del remitente')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Empresa',
                'verbose_name_plural': 'Empresas',
                'ordering': ['name'],
            },
        ),
    ]
