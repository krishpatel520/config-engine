"""
apps.schema_registry.urls
"""
from django.urls import path

from .views import ConfigSchemaDetailView, ConfigSchemaListCreateView

urlpatterns = [
    path("schemas/", ConfigSchemaListCreateView.as_view(), name="schema-list-create"),
    path("schemas/<str:pk>/", ConfigSchemaDetailView.as_view(), name="schema-detail"),
]
