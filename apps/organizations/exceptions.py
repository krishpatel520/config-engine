"""
apps.organizations.exceptions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Domain exceptions for the Organizations application.
"""
from __future__ import annotations


class ConfigOverrideStaleError(Exception):
    """
    Raised by ``get_effective_config`` when an organisation's saved
    ``config_overrides`` are no longer valid against the currently active
    ``GlobalConfigSchema``.

    This happens when the global schema is updated (e.g. a constraint is
    tightened) after the organisation's overrides were last saved.

    Attributes:
        errors: Non-empty list of validation error dicts, each with the
            shape ``{\"field\": \"...\", \"code\": \"...\", \"message\": \"...\"}``.
    """

    def __init__(self, errors: list[dict]) -> None:
        self.errors: list[dict] = errors
        super().__init__(
            f"Stored config overrides are no longer valid against the active "
            f"schema ({len(errors)} error(s))."
        )
