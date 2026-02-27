"""
apps.schema_registry.serializers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
I/O serializers for ConfigSchema – no business logic.
"""
from rest_framework import serializers

from .models import ConfigSchema


class ConfigSchemaSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True)

    class Meta:
        model = ConfigSchema
        fields = [
            "id",
            "organization",
            "organization_name",
            "name",
            "version",
            "schema_definition",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ConfigSchemaCreateSerializer(serializers.Serializer):
    org_id = serializers.IntegerField()
    name = serializers.CharField(max_length=255)
    version = serializers.IntegerField(default=1, min_value=1)
    schema_definition = serializers.JSONField()
    description = serializers.CharField(required=False, default="", allow_blank=True)


class ConfigSchemaUpdateSerializer(serializers.Serializer):
    description = serializers.CharField(required=False, allow_blank=True)
    schema_definition = serializers.JSONField(required=False)
    is_active = serializers.BooleanField(required=False)
