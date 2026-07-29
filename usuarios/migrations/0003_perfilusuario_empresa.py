from django.db import migrations, models


def seed_empresa_por_rol(apps, schema_editor):
    PerfilUsuario = apps.get_model("usuarios", "PerfilUsuario")
    for perfil in PerfilUsuario.objects.select_related("user").all():
        user = perfil.user
        if getattr(user, "is_superuser", False) or perfil.rol == "ADMINISTRADOR":
            perfil.empresa = "ambas"
        else:
            # Por defecto Desarrollos; reasigne Bienes Raíces desde Usuarios.
            perfil.empresa = "desarrollos"
        perfil.save(update_fields=["empresa"])


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0002_seed_perfiles_existentes"),
    ]

    operations = [
        migrations.AddField(
            model_name="perfilusuario",
            name="empresa",
            field=models.CharField(
                choices=[
                    ("ambas", "Ambas empresas (solo administrador)"),
                    ("bienes-raices", "Paredes Bienes Raíces"),
                    ("desarrollos", "Paredes Desarrollos Inmobiliarios"),
                ],
                db_index=True,
                default="ambas",
                help_text=(
                    "Define a qué sistema puede entrar. "
                    "Solo administradores pueden tener «Ambas». "
                    "Gerencia y el resto quedan limitados a la empresa asignada."
                ),
                max_length=32,
                verbose_name="empresa",
            ),
        ),
        migrations.RunPython(seed_empresa_por_rol, migrations.RunPython.noop),
    ]
