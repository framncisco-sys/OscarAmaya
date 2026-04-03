from django.conf import settings
from django.db import migrations


def crear_perfiles(apps, schema_editor):
    User = apps.get_model("auth", "User")
    PerfilUsuario = apps.get_model("usuarios", "PerfilUsuario")
    for u in User.objects.all().iterator():
        if PerfilUsuario.objects.filter(user_id=u.pk).exists():
            continue
        rol = "ADMINISTRADOR" if getattr(u, "is_superuser", False) else "LECTURA"
        PerfilUsuario.objects.create(
            user_id=u.pk,
            rol=rol,
            activo_en_app=True,
            telefono="",
            notas="",
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("usuarios", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(crear_perfiles, noop_reverse),
    ]
