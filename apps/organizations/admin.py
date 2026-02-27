"""
apps.organizations.admin
"""
from django.contrib import admin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "slug", "created_at"]
    search_fields = ["name", "slug"]
    readonly_fields = ["id", "slug", "created_at", "updated_at"]
    ordering = ["id"]

    def get_fields(self, request, obj=None):
        """Show full UUID and ID prominently at top of detail form."""
        fields = super().get_fields(request, obj)
        if obj:
            fields = list(fields)
            if "id" in fields:
                fields.remove("id")
                fields.insert(0, "id")
        return fields
