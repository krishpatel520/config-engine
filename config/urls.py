"""
Root URL configuration for config_engine.
"""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from common.health import health_check

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # Health check
    path("health/", health_check, name="health-check"),

    # OpenAPI schema & Swagger UI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),

    # Application API routes
    path("api/v1/", include("apps.organizations.urls")),
    path("api/v1/", include("apps.schema_registry.urls")),
    path("api/v1/", include("apps.config_core.urls")),
]
