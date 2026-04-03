from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "action",
        "app_label",
        "model_name",
        "object_pk",
        "actor",
        "actor_role",
        "ip_address",
        "request_id",
    )
    list_filter = ("action", "app_label", "model_name", "actor")
    search_fields = ("object_pk", "request_id", "user_agent", "actor__username", "actor__email")
    readonly_fields = (
        "created_at",
        "action",
        "actor",
        "actor_role",
        "app_label",
        "model_name",
        "object_pk",
        "before",
        "after",
        "ip_address",
        "user_agent",
        "request_id",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

from django.contrib import admin

# Register your models here.
