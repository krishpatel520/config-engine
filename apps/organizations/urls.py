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
    OrganizationCreateView,
    OrganizationEffectiveConfigView,
)

urlpatterns = [
    # POST /api/v1/organizations/
    path(
        "organizations/",
        OrganizationCreateView.as_view(),
        name="organization-create",
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
