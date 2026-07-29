from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Crear"
        UPDATE = "UPDATE", "Actualizar"
        DELETE = "DELETE", "Eliminar"

    created_at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=16, choices=Action.choices)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    actor_role = models.CharField(max_length=64, blank=True)

    app_label = models.CharField(max_length=64)
    model_name = models.CharField(max_length=128)
    object_pk = models.CharField(max_length=128)

    # encoder explícito: sin él, json.dumps(cls=None) falla con datetime/Decimal en el dict.
    before = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    after = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    # Slug de sesión al momento del evento: bienes-raices | desarrollos | vacío.
    marca_slug = models.CharField(max_length=32, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["app_label", "model_name", "object_pk"]),
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["marca_slug", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{self.created_at:%Y-%m-%d %H:%M:%S}] {self.action} {self.app_label}.{self.model_name}({self.object_pk})"
