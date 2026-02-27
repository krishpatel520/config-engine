"""
apps.schema_registry.apps
"""
from django.apps import AppConfig


class SchemaRegistryConfig(AppConfig):
    name = "apps.schema_registry"
    label = "schema_registry"
    verbose_name = "Schema Registry"
