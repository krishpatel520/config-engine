"""
apps.schema_registry.models
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Models for the Schema Registry application.

Models
------
ConfigSchema
    Organisation-scoped, versioned JSON Schema document.

GlobalConfigSchema
    Singleton-style, system-wide active schema with a partial unique
    constraint ensuring only one row can be active at any time.
"""
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models import Q

from apps.organizations.models import Organization


# ---------------------------------------------------------------------------
# ConfigSchema  (existing model – unchanged)
# ---------------------------------------------------------------------------

class ConfigSchema(models.Model):
    """
    A versioned JSON Schema document owned by an Organization.

    The ``schema_definition`` field stores the full JSON Schema as JSONB,
    enabling efficient server-side querying via ``__contains`` lookups.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="schemas",
    )
    name = models.CharField(max_length=255)
    version = models.PositiveIntegerField(default=1)
    schema_definition = models.JSONField(
        help_text="Full JSON Schema document stored as JSONB.",
    )
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization", "name", "-version"]
        unique_together = [("organization", "name", "version")]
        verbose_name = "Config Schema"
        verbose_name_plural = "Config Schemas"

    def __str__(self) -> str:
        return f"{self.organization.slug}/{self.name}@v{self.version}"


# ---------------------------------------------------------------------------
# GlobalConfigSchema  (new model)
# ---------------------------------------------------------------------------

#: Validator that enforces semantic versioning format ``MAJOR.MINOR.PATCH``.
_semver_validator = RegexValidator(
    regex=r"^\d+\.\d+\.\d+$",
    message=(
        'schema_version must follow semantic versioning: "MAJOR.MINOR.PATCH" '
        "(e.g. 1.0.0, 2.3.14).  Only digits and dots are allowed."
    ),
    code="invalid_semver",
)


class GlobalConfigSchema(models.Model):
    """
    System-wide, singleton-style configuration schema.

    At most **one** ``GlobalConfigSchema`` row may be active at a given time.
    This is enforced at two levels:

    1. Database level – a partial :class:`~django.db.models.UniqueConstraint`
       on rows where ``is_active=True`` (named ``"unique_active_schema"``).
    2. Application level – :meth:`save` runs inside a ``SELECT FOR UPDATE``
       transaction that deactivates all other active rows before persisting the
       new one.

    The ``schema_definition`` JSON must conform to the namespace/field contract
    validated by :class:`~apps.schema_registry.validators.SchemaValidator`.

    Fields
    ------
    id
        Auto-incrementing integer (1, 2, 3…), used as the primary key.
    schema_version
        Semantic version string (``MAJOR.MINOR.PATCH``) validated by
        :data:`_semver_validator`.
    schema_definition
        JSONB blob conforming to the namespaces contract.  Validated in
        :meth:`clean` via :class:`~apps.schema_registry.validators.SchemaValidator`.
    is_active
        Whether this schema is the currently active system schema.
    created_at / updated_at
        Automatic timestamps.

    Example usage::

        schema = GlobalConfigSchema(
            schema_version="1.2.0",
            schema_definition={"namespaces": {"payments": {"amount": {"type": "float", "default": 0.0}}}},
            is_active=True,
        )
        schema.full_clean()  # runs validators + clean()
        schema.save()
    """

    schema_version = models.CharField(
        max_length=20,
        validators=[_semver_validator],
        help_text=(
            "Semantic version of this schema (MAJOR.MINOR.PATCH). "
            "Must match the regex ^\\d+\\.\\d+\\.\\d+$."
        ),
    )
    schema_definition = models.JSONField(
        help_text=(
            "JSON Schema definition conforming to the namespaces contract. "
            "Validated by SchemaValidator before every save."
        ),
    )
    is_active = models.BooleanField(
        default=False,
        help_text=(
            "Marks this schema as the active system configuration schema. "
            "Only one row may be active at a time."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Global Config Schema"
        verbose_name_plural = "Global Config Schemas"
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=Q(is_active=True),
                name="unique_active_schema",
                violation_error_message=(
                    "Another GlobalConfigSchema is already active. "
                    "Deactivate it before activating a new one."
                ),
            ),
        ]

    def __str__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return f"GlobalConfigSchema v{self.schema_version} [{status}]"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def clean(self) -> None:
        """
        Validate the ``schema_definition`` against the namespaces contract.

        Delegates to :meth:`SchemaValidator.validate
        <apps.schema_registry.validators.SchemaValidator.validate>` and
        converts any :class:`~apps.schema_registry.validators.SchemaValidationError`
        into a :class:`django.core.exceptions.ValidationError` so that Django
        forms and the admin interface display a human-readable error.

        Raises:
            django.core.exceptions.ValidationError: If
                :class:`~apps.schema_registry.validators.SchemaValidator`
                finds one or more problems with ``schema_definition``.
        """
        # Import here to avoid any risk of circular imports at module load time.
        from apps.schema_registry.validators import (  # noqa: PLC0415
            SchemaValidationError,
            SchemaValidator,
        )

        try:
            SchemaValidator.validate(self.schema_definition)
        except SchemaValidationError as exc:
            # Convert list of error dicts into a Django ValidationError.
            # Each entry is a separate message so the admin can display them
            # as an unordered list.
            raise ValidationError(
                {
                    "schema_definition": [
                        f"{err['field']}: {err['message']}" for err in exc.errors
                    ]
                }
            ) from exc

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, *args, **kwargs) -> None:
        """
        Persist the instance, ensuring the "only one active row" invariant.

        If ``self.is_active`` is ``True``, all *other* active
        ``GlobalConfigSchema`` rows are deactivated atomically within the same
        database transaction using ``SELECT FOR UPDATE`` to prevent race
        conditions under concurrent writes.

        The deactivation happens **before** the current row is saved so that
        the partial unique constraint ``unique_active_schema`` is never
        momentarily violated for the outgoing row.

        Args:
            *args: Passed through to :meth:`django.db.models.Model.save`.
            **kwargs: Passed through to :meth:`django.db.models.Model.save`.
        """
        with transaction.atomic():
            if self.is_active:
                # Lock all currently active rows (excluding self) and
                # deactivate them before we insert/update this one.
                (
                    GlobalConfigSchema.objects
                    .select_for_update()
                    .filter(is_active=True)
                    .exclude(pk=self.pk)
                    .update(is_active=False)
                )
            super().save(*args, **kwargs)
