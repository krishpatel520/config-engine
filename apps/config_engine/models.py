import uuid

from django.db import models


class ConfigInstance(models.Model):
    SCOPE_TYPE_CHOICES = [
        ("oob", "Out-of-Box"),
        ("tenant", "Tenant"),
        ("user", "User"),
    ]

    # Primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Core fields
    config_key = models.CharField(max_length=255)
    scope_type = models.CharField(max_length=10, choices=SCOPE_TYPE_CHOICES)
    scope_id = models.CharField(max_length=255, null=True, blank=True)
    release_version = models.CharField(max_length=50)

    # Lineage tracking
    base_config_id = models.UUIDField(null=True, blank=True)
    base_release_version = models.CharField(max_length=50, null=True, blank=True)
    base_config_hash = models.CharField(max_length=64, null=True, blank=True)
    parent_config_instance_id = models.UUIDField(null=True, blank=True)

    # Config payload
    config_json = models.JSONField()

    # Status & timestamps
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_instances"
        unique_together = [
            ("config_key", "scope_type", "scope_id", "is_active"),
        ]
        indexes = [
            models.Index(
                fields=["config_key", "scope_type", "scope_id", "is_active"],
                name="idx_config_lookup",
            ),
            models.Index(
                fields=["release_version"],
                name="idx_release",
            ),
            models.Index(
                fields=["base_config_id"],
                name="idx_base_config",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.config_key} [{self.scope_type}:{self.scope_id}] v{self.release_version}"
