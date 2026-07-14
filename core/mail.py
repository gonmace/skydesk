"""Correo saliente: conexión según `accounts.EmailConfig` (DB pisa al .env) y envío
en background para no bloquear el request (un SMTP lento retiene al worker hasta
EMAIL_TIMEOUT — ver el comentario en core/settings.py sobre el cuelgue con gunicorn).
"""
import logging
import threading

from django.conf import settings
from django.core.mail import get_connection, send_mail

logger = logging.getLogger(__name__)


def get_mail_connection():
    """Conexión SMTP desde `EmailConfig` si está activa, o None (= backend del settings).

    Import lazy del modelo: este módulo se importa desde views al cargar las apps.
    """
    from accounts.models import EmailConfig
    cfg = EmailConfig.load()
    if not (cfg.enabled and cfg.host):
        return None
    return get_connection(
        'django.core.mail.backends.smtp.EmailBackend',
        host=cfg.host, port=cfg.port, username=cfg.username,
        password=cfg.password, use_tls=cfg.use_tls,
        timeout=getattr(settings, 'EMAIL_TIMEOUT', 10),
    )


def resolve_from_email():
    from accounts.models import EmailConfig
    cfg = EmailConfig.load()
    if cfg.enabled and cfg.from_email:
        return cfg.from_email
    return settings.DEFAULT_FROM_EMAIL


def send_mail_now(subject, message, recipient_list, from_email=None):
    """Envía en el request (síncrono) con fail_silently=False: propaga la excepción
    de SMTP para que el llamador la muestre. Usar solo donde el usuario espera ver
    el resultado del envío en el momento (p.ej. solicitar acceso) — en el resto de
    los casos preferir `send_mail_async` para no retener el request con un SMTP lento.
    """
    connection = get_mail_connection()
    from_email = from_email or resolve_from_email()
    send_mail(subject, message, from_email, recipient_list,
               connection=connection, fail_silently=False)


def send_mail_async(subject, message, recipient_list, from_email=None):
    """`send_mail` en un thread daemon: el request responde sin esperar al SMTP.

    La conexión y el remitente se resuelven acá (queries a EmailConfig incluidas)
    para que dentro del thread no se toque ni el ORM ni el request. Trade-off
    asumido: un reinicio del proceso en el instante justo pierde el email pendiente
    — aceptable para notificaciones.

    Con backend locmem (tests) envía inline: los asserts sobre `mail.outbox`
    corren inmediatamente después del post y un thread sería una carrera.
    """
    connection = get_mail_connection()
    from_email = from_email or resolve_from_email()

    def _send():
        try:
            send_mail(subject, message, from_email, recipient_list,
                      connection=connection, fail_silently=False)
        except Exception:
            logger.exception('No se pudo enviar el email «%s» a %s', subject, recipient_list)

    if 'locmem' in settings.EMAIL_BACKEND:
        _send()
        return
    threading.Thread(target=_send, daemon=True, name='skydesk-mail').start()
