"""
apps.organizations.serializers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
I/O-only serializers for the Organizations API.
No business logic; shape validation only.
"""
from rest_framework import serializers

from apps.schema_registry.models import GlobalConfigSchema
from .models import Organization


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------

class OrganizationSerializer(serializers.ModelSerializer):
    """Read serializer for a full Organization object."""

    class Meta:
        model = Organization
        fields = ["id", "name", "config_overrides", "created_at", "updated_at"]
        read_only_fields = ["id", "config_overrides", "created_at", "updated_at"]


class OrganizationCreateSerializer(serializers.Serializer):
    """Validates POST /organizations/ request body."""

    name = serializers.CharField(max_length=255)


# ---------------------------------------------------------------------------
# Config overrides
# ---------------------------------------------------------------------------

class PutConfigRequestSerializer(serializers.Serializer):
    """Validates PUT /organizations/{id}/config/ request body."""

    overrides = serializers.JSONField()
    acting_role = serializers.CharField(max_length=100)
    environment = serializers.CharField(max_length=50)


class EffectiveConfigResponseSerializer(serializers.Serializer):
    """Response shape for a successful PUT /config/ or GET /effective-config/."""

    effective_config = serializers.JSONField()


class ValidationErrorResponseSerializer(serializers.Serializer):
    """Response shape for a 400 validation failure on PUT /config/."""

    errors = serializers.ListField(child=serializers.DictField())


# ---------------------------------------------------------------------------
# Active schema
# ---------------------------------------------------------------------------

class ActiveSchemaSerializer(serializers.ModelSerializer):
    """Read serializer for GET /schema/active/."""

    class Meta:
        model = GlobalConfigSchema
        fields = ["id", "schema_version", "schema_definition", "created_at"]
        read_only_fields = fields
