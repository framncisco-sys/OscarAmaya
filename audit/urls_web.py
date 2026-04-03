from django.urls import path

from . import views_web as views

urlpatterns = [
    path("auditoria/", views.AuditLogListView.as_view(), name="audit_log_list"),
    path("auditoria/<int:pk>/", views.AuditLogDetailView.as_view(), name="audit_log_detail"),
]
