from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PerfilUsuario


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def crear_perfil_si_no_existe(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return
    if not PerfilUsuario.objects.filter(user_id=instance.pk).exists():
        rol = (
            PerfilUsuario.Rol.ADMINISTRADOR
            if instance.is_superuser
            else PerfilUsuario.Rol.LECTURA
        )
        PerfilUsuario.objects.create(
            user=instance,
            rol=rol,
            empresa=(
                PerfilUsuario.Empresa.AMBAS
                if rol == PerfilUsuario.Rol.ADMINISTRADOR
                else PerfilUsuario.Empresa.DESARROLLOS
            ),
        )
