"""
apps.config_core.admin
"""
from django.contrib import admin

from .models import ConfigEntry


@admin.register(ConfigEntry)
class ConfigEntryAdmin(admin.ModelAdmin):
    list_display = ["key", "environment", "organization", "schema", "is_active", "created_at"]
    list_filter = ["is_active", "environment", "organization"]
    search_fields = ["key", "organization__name", "schema__name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["organization", "key", "environment"]
