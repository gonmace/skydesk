"""post_delete en vez de override de Model.delete(): así también corre en los deletes por
cascada (ej. comment.delete() cascadeando sus Attachment vía GenericRelation) — un
QuerySet.delete() en cascada no invoca Model.delete() por fila, pero sí emite post_delete
por cada instancia una vez que hay un receiver conectado (desactiva el fast-delete de
Django). Si delete_blob() falla, la excepción hace rollback de todo el delete() (ver
attachments/services.py:delete_blob).
"""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Attachment
from .services import delete_blob


@receiver(post_delete, sender=Attachment, dispatch_uid='attachments.delete_blob_on_delete')
def delete_blob_on_delete(sender, instance, **kwargs):
    delete_blob(instance)
