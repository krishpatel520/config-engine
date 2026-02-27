"""
apps.organizations.services.org_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
All business logic for the Organizations application.

Views must call only these functions.  No business logic lives in views or
serializers.

Responsibilities
----------------
- CRUD for :class:`~apps.organizations.models.Organization`.
- Applying and persisting config overrides (after delegate-validation via
  :class:`~apps.config_core.services.override_validator.OverrideValidationService`).
- Resolving effective configuration via
  :class:`~apps.config_core.services.config_resolver.ConfigResolver`.
- Fetching the currently active
  :class:`~apps.schema_registry.models.GlobalConfigSchema`.
"""
from __future__ import annotations

import structlog
from django.shortcuts import get_object_or_404

from apps.config_core.services.config_resolver import ConfigResolver
from apps.config_core.services.override_validator import (
    OverrideValidationRequest,
    OverrideValidationResult,
    OverrideValidationService,
)
from apps.organizations.models import Organization
from apps.schema_registry.models import GlobalConfigSchema

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def get_active_schema() -> GlobalConfigSchema:
    """
    Return the currently active :class:`GlobalConfigSchema`, or raise
    :class:`~django.http.Http404` if none exists.

    Returns:
        The single active ``GlobalConfigSchema`` instance.

    Raises:
        django.http.Http404: When no ``GlobalConfigSchema`` with
            ``is_active=True`` exists.
    """
    schema = GlobalConfigSchema.objects.filter(is_active=True).first()
    if schema is None:
        from django.http import Http404  # noqa: PLC0415
        raise Http404("No active GlobalConfigSchema found.")
    return schema


# ---------------------------------------------------------------------------
# Organization CRUD
# ---------------------------------------------------------------------------

def create_organization(*, name: str) -> Organization:
    """
    Create a new :class:`Organization` with empty ``config_overrides``.

    Args:
        name: Unique display name for the organisation.

    Returns:
        The newly created and persisted ``Organization`` instance.

    Raises:
        django.db.IntegrityError: If an organisation with *name* already
            exists (propagated to the caller for HTTP-layer handling).
    """
    org = Organization.objects.create(name=name, config_overrides={})
    logger.info("organization_created", org_id=str(org.id), name=org.name)
    return org


def get_organization(org_id: str | int) -> Organization:
    """
    Fetch an :class:`Organization`, raising 404 if absent.
    Supports lookup by ID or slug for convenience.

    Args:
        org_id: Integer ID or slug string of the target.

    Returns:
        The matching ``Organization`` instance.

    Raises:
        django.http.Http404: If no organisation exists.
    """
    from django.db.models import Q
    from django.http import Http404

    # Try matching ID or Slug
    if str(org_id).isdigit():
        q = Q(id=int(org_id)) | Q(slug=str(org_id))
    else:
        q = Q(slug=str(org_id))

    org = Organization.objects.filter(q).first()
    if not org:
        raise Http404(f"Organization '{org_id}' not found.")
    return org


# ---------------------------------------------------------------------------
# Config override application
# ---------------------------------------------------------------------------

def apply_config_overrides(
    *,
    org_id: str,
    overrides: dict,
    acting_role: str,
    environment: str,
) -> dict:
    """
    Validate *overrides* against the active schema and, if valid, persist them
    on the organisation and return the fully-resolved effective config.

    Steps:

    1. Fetch the active ``GlobalConfigSchema`` (404 if none).
    2. Fetch the ``Organization`` by *org_id* (404 if not found).
    3. Pass overrides through
       :class:`~apps.config_core.services.override_validator.OverrideValidationService`.
    4. If validation fails, return the :class:`OverrideValidationResult` so
       the view can return a 400.
    5. If validation passes, persist the overrides and return
       ``ConfigResolver.resolve(schema, overrides)`` as the effective config.

    Args:
        org_id: UUID string of the target organisation.
        overrides: Proposed override blob ``{namespace: {field: value}}``.
        acting_role: Role of the requesting actor.
        environment: Deployment environment string.

    Returns:
        A tuple ``(result, effective_config)`` where *result* is the
        :class:`OverrideValidationResult` and *effective_config* is the
        resolved dict (``None`` when validation failed).
    """
    active_schema = get_active_schema()
    org = get_organization(org_id)

    validation_request = OverrideValidationRequest(
        schema=active_schema.schema_definition,
        overrides=overrides,
        acting_role=acting_role,
        environment=environment,
    )
    result: OverrideValidationResult = OverrideValidationService.validate(
        validation_request
    )

    if not result.valid:
        logger.warning(
            "config_override_validation_failed",
            org_id=org_id,
            error_count=len(result.errors),
        )
        return result, None

    # Persist the overrides on the organisation.
    org.config_overrides = overrides
    org.save(update_fields=["config_overrides", "updated_at"])

    logger.info(
        "config_overrides_applied",
        org_id=org_id,
        environment=environment,
        acting_role=acting_role,
    )

    effective_config = ConfigResolver.resolve(
        schema=active_schema.schema_definition,
        org_overrides=org.config_overrides,
    )
    return result, effective_config


# ---------------------------------------------------------------------------
# Effective config resolution
# ---------------------------------------------------------------------------

def get_effective_config(*, org_id: str) -> dict:
    """
    Return the fully-resolved effective configuration for an organisation.

    Merges ``schema defaults → org overrides`` using
    :class:`~apps.config_core.services.config_resolver.ConfigResolver`.

    Args:
        org_id: UUID string of the target organisation.

    Returns:
        Fully-resolved ``{namespace: {field: value}}`` dict.

    Raises:
        django.http.Http404: If no active schema or no organisation found.
    """
    active_schema = get_active_schema()
    org = get_organization(org_id)

    return ConfigResolver.resolve(
        schema=active_schema.schema_definition,
        org_overrides=org.config_overrides,
    )
