"""
apps.config_core.models
~~~~~~~~~~~~~~~~~~~~~~~~
ConfigEntry – a JSON configuration value validated against a ConfigSchema.
"""
from django.db import models

from apps.organizations.models import Organization
from apps.schema_registry.models import ConfigSchema


class ConfigEntry(models.Model):
    """
    A concrete JSON configuration blob associated with a schema version.

    `data` is stored as JSONB for efficient querying.
    """

    class Environment(models.TextChoices):
        DEVELOPMENT = "development", "Development"
        STAGING = "staging", "Staging"
        PRODUCTION = "production", "Production"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="config_entries",
    )
    schema = models.ForeignKey(
        ConfigSchema,
        on_delete=models.PROTECT,
        related_name="entries",
    )
    key = models.CharField(
        max_length=255,
        help_text="Namespaced config key, e.g. 'feature_flags.dark_mode'.",
    )
    environment = models.CharField(
        max_length=20,
        choices=Environment.choices,
        default=Environment.DEVELOPMENT,
    )
    data = models.JSONField(
        help_text="Configuration value stored as JSONB.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization", "key", "environment"]
        unique_together = [("organization", "key", "environment")]
        verbose_name = "Config Entry"
        verbose_name_plural = "Config Entries"

    def __str__(self) -> str:
        return f"{self.organization.slug}/{self.key} [{self.environment}]"
