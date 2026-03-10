"""
apps.organizations.models
~~~~~~~~~~~~~~~~~~~~~~~~~
Organization – tenant entity that holds configuration overrides.
"""
from django.db import models
from django.utils.text import slugify


class Organization(models.Model):
    """
    A tenant organisation that can store configuration overrides on top of
    the active ``GlobalConfigSchema``.

    Fields
    ------
    id
        Auto-incrementing integer (1, 2, 3…), used as the primary key and for
        clean API lookups.
    name
        Human-readable unique name (e.g. ``"Acme Corp"``).
    slug
        URL-safe version of ``name``, auto-generated on first save.
    config_overrides
        JSONB blob shaped as ``{namespace: {field: value}}``.  Defaults to
        an empty dict (no overrides – pure schema defaults apply).
    effective_config
        JSONB blob holding the last-computed fully-resolved configuration
        (schema defaults → org overrides).  Updated automatically whenever
        overrides are saved or the active global schema changes.  ``None``
        when the configuration has never been computed or the stored overrides
        are stale/invalid under the current schema.
    created_at / updated_at
        Automatic timestamps.
    """

    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(
        max_length=255,
        unique=True,
        blank=True,
        help_text="URL-safe identifier auto-generated from the organisation name.",
    )
    config_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="Org-level overrides applied on top of the active GlobalConfigSchema.",
    )
    effective_config = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Last-computed effective configuration (schema defaults + org overrides). "
            "Null if never computed or if stored overrides are stale under the current schema."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def save(self, *args, **kwargs) -> None:
        """Auto-populate ``slug`` on first save."""
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        # ID might be None before saving, so fallback gracefully
        return f"#{self.id} {self.name}" if self.id else self.name
