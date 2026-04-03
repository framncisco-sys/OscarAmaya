from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_migrate
from django.dispatch import receiver


ROLE_ADMIN = "Administrador"
ROLE_CONTADOR = "Contador"
ROLE_AUXILIAR = "Auxiliar"


@receiver(post_migrate)
def ensure_default_roles(sender, **kwargs):
    # Se ejecuta después de migraciones; crea los roles si no existen.
    for role_name in (ROLE_ADMIN, ROLE_CONTADOR, ROLE_AUXILIAR):
        Group.objects.get_or_create(name=role_name)

