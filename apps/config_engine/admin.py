import json

from django.contrib import admin, messages
from django.contrib.admin import ModelAdmin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.http import urlencode

from apps.config_engine.models import ConfigInstance
from apps.config_engine.services import ConfigResolutionService


@admin.register(ConfigInstance)
class ConfigInstanceAdmin(ModelAdmin):
    # ------------------------------------------------------------------
    # Custom change-form template (JSON editor + client-side validation)
    # ------------------------------------------------------------------
    change_form_template = (
        "admin/config_engine/configinstance/change_form.html"
    )

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
        "diff_link",
    )
    list_filter = ("scope_type", "is_active", "release_version")
    search_fields = ("config_key", "scope_id")
    ordering = ("-created_at",)

    # ------------------------------------------------------------------
    # Detail view
    # ------------------------------------------------------------------
    readonly_fields = ("id", "base_config_hash", "created_at", "updated_at")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    actions = ("mark_as_inactive", "reset_selected_to_oob")

    @admin.action(description="Mark selected as inactive")
    def mark_as_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} config instance(s) marked as inactive.")

    @admin.action(description="Reset selected to OOB")
    def reset_selected_to_oob(self, request, queryset):
        """
        For each selected record:
          - Skip OOB configs with a warning.
          - Deactivate all active overrides for (config_key, scope_type, scope_id).
        """
        reset_count = 0
        skipped = 0

        for obj in queryset:
            if obj.scope_type == "oob":
                skipped += 1
                continue
            ConfigResolutionService.reset_to_oob(
                config_key=obj.config_key,
                scope_type=obj.scope_type,
                scope_id=obj.scope_id,
            )
            reset_count += 1

        if reset_count:
            self.message_user(
                request,
                f"{reset_count} config(s) reset to OOB.",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"{skipped} OOB config(s) skipped — OOB records cannot be reset.",
                level=messages.WARNING,
            )

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

    def has_change_permission(self, request, obj=None):
        """Prevent editing of OOB configs in the admin."""
        if obj is not None and obj.scope_type == "oob":
            return False
        return super().has_change_permission(request, obj)

    # ------------------------------------------------------------------
    # Changelist override — outdated-configs banner
    # ------------------------------------------------------------------
    def changelist_view(self, request, extra_context=None):
        outdated_qs = ConfigResolutionService.detect_outdated_tenant_configs()
        count = outdated_qs.count()
        if count > 0:
            self.message_user(
                request,
                (
                    f"⚠ {count} tenant config(s) are outdated and based on a "
                    "superseded OOB release. Use the 'Reset selected to OOB' "
                    "action or review the Diff Viewer."
                ),
                level=messages.WARNING,
            )
        return super().changelist_view(request, extra_context=extra_context)

    # ------------------------------------------------------------------
    # Custom URLs — diff view
    # ------------------------------------------------------------------
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<uuid:pk>/diff/",
                self.admin_site.admin_view(self.diff_view),
                name="config_engine_configinstance_diff",
            ),
        ]
        return custom + urls

    def diff_view(self, request, pk):
        """Side-by-side JSON diff: this config vs current active OOB."""
        obj = get_object_or_404(ConfigInstance, pk=pk)

        oob = ConfigResolutionService.get_active(
            config_key=obj.config_key,
            scope_type="oob",
            scope_id=None,
        )

        is_drifted = ConfigResolutionService.detect_drift(obj)
        is_outdated = (
            oob is not None and obj.base_config_id != oob.id
        )

        context = {
            **self.admin_site.each_context(request),
            "obj": obj,
            "oob": oob,
            "this_json": json.dumps(obj.config_json, indent=2, sort_keys=True),
            "oob_json": json.dumps(oob.config_json, indent=2, sort_keys=True) if oob else "",
            "is_drifted": is_drifted,
            "is_outdated": is_outdated,
            "title": f"Config Diff — {obj.config_key}",
        }
        return render(
            request,
            "admin/config_engine/configinstance/diff_view.html",
            context,
        )

    # ------------------------------------------------------------------
    # Custom list columns
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

    @admin.display(description="Diff")
    def diff_link(self, obj):
        """Renders a 'View Diff' link to the custom diff view for this record."""
        url = reverse(
            "admin:config_engine_configinstance_diff",
            args=[obj.pk],
        )
        return format_html('<a href="{}">View Diff</a>', url)
