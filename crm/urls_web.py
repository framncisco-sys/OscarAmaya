from django.urls import path

from . import views_web as views

urlpatterns = [
    path("crm/leads/", views.LeadListView.as_view(), name="crm_lead_list"),
    path("crm/leads/nuevo/", views.LeadCreateView.as_view(), name="crm_lead_create"),
    path("crm/leads/<int:pk>/", views.LeadDetailView.as_view(), name="crm_lead_detail"),
    path("crm/leads/<int:pk>/editar/", views.LeadUpdateView.as_view(), name="crm_lead_update"),
    path("crm/leads/<int:pk>/actividad/", views.lead_add_actividad, name="crm_lead_add_actividad"),
    path("crm/leads/<int:pk>/visita/", views.lead_add_visita, name="crm_lead_add_visita"),
]

