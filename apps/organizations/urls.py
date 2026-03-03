"""
apps.organizations.urls
~~~~~~~~~~~~~~~~~~~~~~~
URL routing for the Organizations application.
Mounted at /api/v1/ by the root URLconf.
"""
from django.urls import path

from .views import (
    ActiveSchemaView,
    OrganizationConfigView,
    OrganizationDetailView,
    OrganizationEffectiveConfigView,
    OrganizationListCreateView,
)

urlpatterns = [
    # GET  /api/v1/organizations/         – List all organisations
    # POST /api/v1/organizations/         – Create organisation
    path(
        "organizations/",
        OrganizationListCreateView.as_view(),
        name="organization-list-create",
    ),
    # GET /api/v1/organizations/<org_id>/ – Retrieve single organisation
    path(
        "organizations/<str:org_id>/",
        OrganizationDetailView.as_view(),
        name="organization-detail",
    ),
    # PUT /api/v1/organizations/<org_id>/config/
    path(
        "organizations/<str:org_id>/config/",
        OrganizationConfigView.as_view(),
        name="organization-config",
    ),
    # GET /api/v1/organizations/<org_id>/effective-config/
    path(
        "organizations/<str:org_id>/effective-config/",
        OrganizationEffectiveConfigView.as_view(),
        name="organization-effective-config",
    ),
    # GET /api/v1/schema/active/
    path(
        "schema/active/",
        ActiveSchemaView.as_view(),
        name="schema-active",
    ),
]
