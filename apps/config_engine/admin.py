from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.core.exceptions import PermissionDenied
from django.utils.html import format_html
from django.utils.http import urlencode

from apps.config_engine.models import ConfigInstance


@admin.register(ConfigInstance)
class ConfigInstanceAdmin(ModelAdmin):
    # ------------------------------------------------------------------
    # List view
    # ------------------------------------------------------------------
    list_display = (
        "id",
        "config_key",
        "scope_type",
        "scope_id",
        "release_version",
        "is_active",
        "created_at",
        "lineage_link",
    )
    list_filter = ("scope_type", "is_active", "release_version")
    search_fields = ("config_key", "scope_id")
    ordering = ("-created_at",)

    # ------------------------------------------------------------------
    # Detail view
    # ------------------------------------------------------------------
    readonly_fields = ("id", "base_config_hash", "created_at", "updated_at")

    # ------------------------------------------------------------------
    # Custom action — mark selected as inactive
    # ------------------------------------------------------------------
    actions = ("mark_as_inactive",)

    @admin.action(description="Mark selected as inactive")
    def mark_as_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} config instance(s) marked as inactive.")

    # ------------------------------------------------------------------
    # OOB immutability — block delete
    # ------------------------------------------------------------------
    def delete_model(self, request, obj):
        """Block deletion of OOB configs from the object detail page."""
        if obj.scope_type == "oob":
            raise PermissionDenied(
                "OOB configs are immutable and cannot be deleted."
            )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """Block deletion of OOB configs from the list bulk-delete action."""
        if queryset.filter(scope_type="oob").exists():
            raise PermissionDenied(
                "OOB configs are immutable and cannot be deleted."
            )
        super().delete_queryset(request, queryset)

    def has_delete_permission(self, request, obj=None):
        """Grey-out the delete button on the detail page for OOB configs."""
        if obj is not None and obj.scope_type == "oob":
            return False
        return super().has_delete_permission(request, obj)

    # ------------------------------------------------------------------
    # Custom list column — lineage link
    # ------------------------------------------------------------------
    @admin.display(description="Lineage")
    def lineage_link(self, obj):
        """
        Renders a clickable 'View lineage' link that filters the changelist
        to all records sharing the same base_config_id, making it easy to
        trace the full override tree for a given OOB base.
        """
        if not obj.base_config_id:
            return "—"

        qs = urlencode({"base_config_id": str(obj.base_config_id)})
        url = f"../config_engine/configinstance/?{qs}"
        return format_html('<a href="{}">View lineage</a>', url)
