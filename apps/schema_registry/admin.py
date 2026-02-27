"""
apps.schema_registry.admin
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Django admin registrations for the Schema Registry application.
"""
from django.contrib import admin

from .models import ConfigSchema, GlobalConfigSchema


@admin.register(ConfigSchema)
class ConfigSchemaAdmin(admin.ModelAdmin):
    """Admin interface for organisation-scoped ConfigSchema records."""

    list_display = ["name", "version", "organization", "is_active", "created_at"]
    list_filter = ["is_active", "organization"]
    search_fields = ["name", "organization__name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["organization", "name", "-version"]

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        if obj and "id" in fields:
            fields = list(fields)
            fields.remove("id")
            fields.insert(0, "id")
        return fields


@admin.register(GlobalConfigSchema)
class GlobalConfigSchemaAdmin(admin.ModelAdmin):
    """
    Admin interface for GlobalConfigSchema.

    Only one row may be active at a time; activating a record via the admin
    will automatically deactivate all others (enforced in the model's
    :meth:`~apps.schema_registry.models.GlobalConfigSchema.save` method).
    """

    list_display = ["schema_version", "id", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["schema_version"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["-created_at"]

    def get_readonly_fields(self, request, obj=None):
        """
        Make ``schema_version`` and ``schema_definition`` read-only for
        existing records to prevent accidental mutation of a deployed schema.
        New records can set both fields freely.
        """
        if obj is not None:
            return list(self.readonly_fields) + ["schema_version", "schema_definition"]
        return self.readonly_fields

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        if obj and "id" in fields:
            fields = list(fields)
            fields.remove("id")
            fields.insert(0, "id")
        return fields
