"""
apps.schema_registry.services
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Business logic for ConfigSchema management.
"""
from __future__ import annotations

import structlog
from django.db import IntegrityError

from common.exceptions import ConflictError, NotFoundError
from apps.organizations.services import get_organization
from .models import ConfigSchema

logger = structlog.get_logger(__name__)


def list_schemas(*, org_id: str | None = None, is_active: bool | None = None) -> list[ConfigSchema]:
    """Return all schemas, optionally filtered by org and/or active status."""
    qs = ConfigSchema.objects.select_related("organization").all()
    if org_id:
        qs = qs.filter(organization_id=org_id)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return list(qs)


def get_schema(schema_id: str) -> ConfigSchema:
    """Fetch a single ConfigSchema by UUID, raise NotFoundError if missing."""
    try:
        return ConfigSchema.objects.select_related("organization").get(pk=schema_id)
    except ConfigSchema.DoesNotExist:
        raise NotFoundError(f"ConfigSchema '{schema_id}' not found.")


def create_schema(
    *,
    org_id: str,
    name: str,
    schema_definition: dict,
    version: int = 1,
    description: str = "",
) -> ConfigSchema:
    """Create a new versioned ConfigSchema under the given organisation."""
    org = get_organization(org_id)
    try:
        schema = ConfigSchema.objects.create(
            organization=org,
            name=name,
            version=version,
            schema_definition=schema_definition,
            description=description,
        )
    except IntegrityError as exc:
        raise ConflictError(
            f"Schema '{name}' v{version} already exists for this organisation."
        ) from exc

    logger.info("schema_created", schema_id=str(schema.id), name=name, version=version)
    return schema


def update_schema(schema_id: str, *, data: dict) -> ConfigSchema:
    """Partial-update a ConfigSchema (description, is_active, schema_definition)."""
    schema = get_schema(schema_id)
    updatable_fields = {"description", "schema_definition", "is_active"}
    for field, value in data.items():
        if field in updatable_fields:
            setattr(schema, field, value)
    schema.save()
    logger.info("schema_updated", schema_id=str(schema.id))
    return schema


def delete_schema(schema_id: str) -> None:
    """Soft-delete a schema."""
    schema = get_schema(schema_id)
    schema.is_active = False
    schema.save(update_fields=["is_active", "updated_at"])
    logger.info("schema_deactivated", schema_id=str(schema.id))
