"""
apps.config_core.services.override_validator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Validates a proposed set of configuration overrides against a
``GlobalConfigSchema`` definition.

This module is **pure Python** — it has zero Django view, serializer, or ORM
imports and can be exercised in plain ``pytest`` tests without any Django
setup.

Public API
----------
OverrideValidationRequest   – Input dataclass
OverrideValidationResult    – Output dataclass
OverrideValidationService   – Single-entry-point validator
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

#: A single validation error dict with "field", "code", and "message" keys.
ErrorDict = dict[str, str]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OverrideValidationRequest:
    """
    Encapsulates all inputs required to validate a set of configuration
    overrides against a schema.

    Attributes:
        schema: The ``schema_definition`` dict from a
            ``GlobalConfigSchema`` instance — must already be structurally
            valid (i.e. passed through
            :class:`~apps.schema_registry.validators.SchemaValidator`).
        overrides: The proposed override blob from an organisation or user,
            shaped as ``{namespace_name: {field_name: value}}``.
        acting_role: Role string of the actor proposing the overrides
            (e.g. ``"admin"``, ``"editor"``, ``"viewer"``).
        environment: Deployment environment for which the overrides apply
            (e.g. ``"prod"``, ``"staging"``, ``"dev"``).
    """

    schema: dict
    overrides: dict
    acting_role: str
    environment: str


@dataclass
class OverrideValidationResult:
    """
    Result of a validation run performed by
    :class:`OverrideValidationService`.

    Attributes:
        valid: ``True`` iff no errors were found.
        errors: List of error dicts, each with keys:

            - ``"field"``   – dot-separated path, e.g. ``"payments.amount"``
            - ``"code"``    – machine-readable error code (see below)
            - ``"message"`` – human-readable description

            Error codes used by this service:

            =====================  ==============================================
            Code                   Meaning
            =====================  ==============================================
            ``unknown_namespace``  Override targets a namespace not in schema.
            ``unknown_field``      Override targets a field not in that namespace.
            ``missing_required``   Required field absent from override namespace.
            ``immutable_field``    Field is ``editable: false``; override rejected.
            ``role_forbidden``     ``acting_role`` not in ``editable_by_roles``.
            ``env_forbidden``      ``environment`` not in ``environment_restrictions``.
            ``type_mismatch``      Override value type ≠ declared field type.
            ``constraint_violation`` Override value violates min/max/allowed_values.
            =====================  ==============================================
    """

    valid: bool
    errors: list[ErrorDict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal constants shared with SchemaValidator logic
# ---------------------------------------------------------------------------

#: Maps type name → Python type(s).  Must stay in sync with validators.py.
_TYPE_CHECKERS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "boolean": bool,
    "float": (float, int),
    "list": list,
    "dict": dict,
}


def _is_numeric(value: object) -> bool:
    """Return True if *value* is a numeric int or float (not bool)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _type_matches(declared_type: str, value: object) -> bool:
    """
    Return ``True`` if *value* is an instance of the Python type(s) that
    correspond to *declared_type*.

    Mirrors the isinstance logic used in
    :class:`~apps.schema_registry.validators.SchemaValidator` so that type
    checks are consistent across the codebase.

    Special cases:
    - ``"integer"`` rejects :class:`bool` (bool is a subclass of int).
    - ``"float"`` rejects :class:`bool` but accepts :class:`int`.

    Args:
        declared_type: One of ``string``, ``integer``, ``boolean``,
            ``float``, ``list``, ``dict``.
        value: The Python value to check.

    Returns:
        ``True`` if the value's type is compatible with *declared_type*.
    """
    if declared_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared_type == "float":
        return isinstance(value, (float, int)) and not isinstance(value, bool)
    checker = _TYPE_CHECKERS.get(declared_type)
    if checker is None:
        return False
    return isinstance(value, checker)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class OverrideValidationService:
    """
    Validates that a set of configuration overrides conforms to a
    ``GlobalConfigSchema`` definition.

    All rules are evaluated and **all errors are accumulated** before
    returning — the validator never short-circuits on the first failure.

    Usage::

        request = OverrideValidationRequest(
            schema=global_schema.schema_definition,
            overrides={"payments": {"amount": 500}},
            acting_role="editor",
            environment="prod",
        )
        result = OverrideValidationService.validate(request)
        if not result.valid:
            for err in result.errors:
                print(err["field"], err["code"], err["message"])
    """

    @staticmethod
    def validate(request: OverrideValidationRequest) -> OverrideValidationResult:
        """
        Validate *request.overrides* against *request.schema*.

        Enforces, in order:

        1. Unknown namespaces / fields in the override blob.
        2. Required fields that are absent when their namespace is overridden.
        3. Non-editable (``editable: false``) fields.
        4. Role restrictions (``policy.editable_by_roles``).
        5. Environment restrictions (``policy.environment_restrictions``).
        6. Type consistency between override value and declared field type.
        7. Constraint enforcement (``min`` / ``max`` / ``allowed_values``).

        Args:
            request: An :class:`OverrideValidationRequest` carrying all
                inputs needed for validation.

        Returns:
            An :class:`OverrideValidationResult` where ``valid`` is
            ``True`` iff no errors were found.
        """
        errors: list[ErrorDict] = []
        schema_namespaces: dict = request.schema.get("namespaces", {})
        overrides: dict = request.overrides or {}

        # ── Rule 1: unknown namespaces ────────────────────────────────────
        for ns_name, ns_overrides in overrides.items():
            if ns_name not in schema_namespaces:
                errors.append({
                    "field": ns_name,
                    "code": "unknown_namespace",
                    "message": (
                        f'Namespace "{ns_name}" does not exist in the schema.'
                    ),
                })
                continue  # Cannot validate fields without a schema namespace

            if not isinstance(ns_overrides, dict):
                errors.append({
                    "field": ns_name,
                    "code": "unknown_namespace",
                    "message": (
                        f'Override value for namespace "{ns_name}" must be a dict.'
                    ),
                })
                continue

            schema_fields: dict = schema_namespaces[ns_name]

            # ── Rule 1 (cont): unknown fields within a valid namespace ────
            for field_name in ns_overrides:
                if field_name not in schema_fields:
                    errors.append({
                        "field": f"{ns_name}.{field_name}",
                        "code": "unknown_field",
                        "message": (
                            f'Field "{field_name}" does not exist in '
                            f'namespace "{ns_name}".'
                        ),
                    })

            # ── Rule 2: required fields missing from this namespace ───────
            for field_name, field_def in schema_fields.items():
                if field_def.get("required") is True and field_name not in ns_overrides:
                    errors.append({
                        "field": f"{ns_name}.{field_name}",
                        "code": "missing_required",
                        "message": (
                            f'Field "{ns_name}.{field_name}" is required but '
                            f"was not provided in the override."
                        ),
                    })

            # ── Rules 3-7: per-field validation for fields that exist ─────
            for field_name, override_value in ns_overrides.items():
                if field_name not in schema_fields:
                    continue  # already reported as unknown_field above

                field_def = schema_fields[field_name]
                field_path = f"{ns_name}.{field_name}"

                OverrideValidationService._validate_field_override(
                    field_path=field_path,
                    field_def=field_def,
                    override_value=override_value,
                    acting_role=request.acting_role,
                    environment=request.environment,
                    errors=errors,
                )

        return OverrideValidationResult(valid=len(errors) == 0, errors=errors)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_field_override(
        field_path: str,
        field_def: dict,
        override_value: object,
        acting_role: str,
        environment: str,
        errors: list[ErrorDict],
    ) -> None:
        """
        Run rules 3-7 for a single field in a namespace override.

        Appends any errors found to *errors*; does not raise.

        Args:
            field_path: Dot-separated path for error reports, e.g.
                ``"payments.amount"``.
            field_def: The field definition dict from the schema.
            override_value: The value the caller wishes to set.
            acting_role: Role of the actor proposing the override.
            environment: Deployment environment string.
            errors: Mutable list to accumulate error dicts.
        """
        declared_type: str = field_def.get("type", "")

        # ── Rule 3: non-editable fields ───────────────────────────────────
        if field_def.get("editable") is False:
            errors.append({
                "field": field_path,
                "code": "immutable_field",
                "message": (
                    f'"{field_path}" is immutable (editable=false) and '
                    "cannot be overridden."
                ),
            })
            # Still run type/constraint checks so we give a full picture.

        # ── Rule 4: role restrictions ─────────────────────────────────────
        policy: dict = field_def.get("policy", {})
        editable_by_roles: list | None = policy.get("editable_by_roles")
        if editable_by_roles is not None and acting_role not in editable_by_roles:
            errors.append({
                "field": field_path,
                "code": "role_forbidden",
                "message": (
                    f'Role "{acting_role}" is not authorised to override '
                    f'"{field_path}". Allowed roles: {editable_by_roles}.'
                ),
            })

        # ── Rule 5: environment restrictions ──────────────────────────────
        env_restrictions: list | None = policy.get("environment_restrictions")
        if env_restrictions is not None and environment not in env_restrictions:
            errors.append({
                "field": field_path,
                "code": "env_forbidden",
                "message": (
                    f'Environment "{environment}" is not permitted for '
                    f'"{field_path}". Allowed environments: {env_restrictions}.'
                ),
            })

        # ── Rule 6: type consistency ──────────────────────────────────────
        if declared_type and not _type_matches(declared_type, override_value):
            errors.append({
                "field": field_path,
                "code": "type_mismatch",
                "message": (
                    f'"{field_path}" expects type "{declared_type}"; '
                    f"got {type(override_value).__name__}."
                ),
            })
            # Skip constraint checks if the type is already wrong — the
            # constraint checks assume the value has the right type.
            return

        # ── Rule 7: constraint enforcement ───────────────────────────────
        constraints: dict = field_def.get("constraints", {})
        if constraints:
            OverrideValidationService._validate_constraints(
                field_path=field_path,
                declared_type=declared_type,
                override_value=override_value,
                constraints=constraints,
                errors=errors,
            )

    @staticmethod
    def _validate_constraints(
        field_path: str,
        declared_type: str,
        override_value: object,
        constraints: dict,
        errors: list[ErrorDict],
    ) -> None:
        """
        Enforce ``min``, ``max``, and ``allowed_values`` constraints.

        For numeric types (``integer``, ``float``), ``min`` / ``max`` are
        applied directly to the value.  For ``list`` types, ``min`` / ``max``
        are applied to ``len(override_value)``.  For all other types,
        ``min`` / ``max`` are ignored (but ``allowed_values`` still applies).

        Args:
            field_path: Dot-separated path for error messages.
            declared_type: The schema-declared type of the field.
            override_value: The override value (already type-checked).
            constraints: The ``constraints`` dict from the field definition.
            errors: Mutable list to accumulate error dicts.
        """
        min_val = constraints.get("min")
        max_val = constraints.get("max")
        allowed_values = constraints.get("allowed_values")

        # ── min / max ─────────────────────────────────────────────────────
        if min_val is not None or max_val is not None:
            if declared_type in ("integer", "float"):
                comparable: float | int | None = override_value  # type: ignore[assignment]
            elif declared_type == "list":
                comparable = len(override_value)  # type: ignore[arg-type]
            else:
                comparable = None  # min/max not meaningful for other types

            if comparable is not None:
                if min_val is not None and comparable < min_val:
                    errors.append({
                        "field": field_path,
                        "code": "constraint_violation",
                        "message": (
                            f'"{field_path}" value {comparable!r} is below '
                            f"the minimum of {min_val}."
                        ),
                    })
                if max_val is not None and comparable > max_val:
                    errors.append({
                        "field": field_path,
                        "code": "constraint_violation",
                        "message": (
                            f'"{field_path}" value {comparable!r} exceeds '
                            f"the maximum of {max_val}."
                        ),
                    })

        # ── allowed_values ────────────────────────────────────────────────
        if allowed_values is not None and override_value not in allowed_values:
            errors.append({
                "field": field_path,
                "code": "constraint_violation",
                "message": (
                    f'"{field_path}" value {override_value!r} is not in the '
                    f"allowed values: {allowed_values}."
                ),
            })
