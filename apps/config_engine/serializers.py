from rest_framework import serializers

from apps.config_engine.models import ConfigInstance


class ConfigInstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfigInstance
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "base_config_hash")
