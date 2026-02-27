"""
apps.schema_registry.validators
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pure-Python schema validation engine for GlobalConfigSchema.

No Django view, serializer, or model imports are allowed here so that this
module can be used as a standalone utility and tested without Django setup.

Public API:
    SchemaValidationError   – raised when validation finds one or more errors
    SchemaValidator.validate(schema_definition) – validates the full schema dict
"""


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class SchemaValidationError(Exception):
    """
    Raised by :meth:`SchemaValidator.validate` when the supplied
    ``schema_definition`` dict contains one or more structural or semantic
    errors.

    All errors are collected before this exception is raised so callers
    receive a complete picture of every problem at once.

    Attributes:
        errors (list[dict]): Non-empty list of error dicts, each with the
            shape ``{"field": "<dot-separated path>", "message": "<reason>"}``.

    Example::

        try:
            SchemaValidator.validate(my_schema)
        except SchemaValidationError as exc:
            for err in exc.errors:
                print(err["field"], err["message"])
    """

    def __init__(self, errors: list[dict]) -> None:
        self.errors: list[dict] = errors
        super().__init__(str(errors))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

#: Mapping from the string type name used in schema_definition to the Python
#: built-in type(s) that a ``default`` value must be an instance of.
_TYPE_CHECKERS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,   # NOTE: bool is a subclass of int; handled specially below
    "boolean": bool,
    "float": (float, int),
    "list": list,
    "dict": dict,
}

#: Complete set of valid field type names.
_VALID_TYPES: frozenset[str] = frozenset(_TYPE_CHECKERS)

#: Allowed keys inside a ``constraints`` block.
_VALID_CONSTRAINT_KEYS: frozenset[str] = frozenset({"min", "max", "allowed_values"})

#: Allowed keys inside a ``policy`` block.
_VALID_POLICY_KEYS: frozenset[str] = frozenset({"editable_by_roles", "environment_restrictions"})


def _is_numeric(value: object) -> bool:
    """Return True if *value* is an :class:`int` (but not :class:`bool`) or a
    :class:`float`."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class SchemaValidator:
    """
    Stateless validator for the ``schema_definition`` JSON contract used by
    :class:`~apps.schema_registry.models.GlobalConfigSchema`.

    The validator collects **all** validation errors before raising so that
    callers receive a single, exhaustive report rather than discovering one
    problem at a time.

    Usage::

        SchemaValidator.validate({"namespaces": { ... }})
        # Raises SchemaValidationError if any rule is violated.
        # Returns None on success.
    """

    @staticmethod
    def validate(schema_definition: dict) -> None:
        """
        Validate *schema_definition* against the GlobalConfigSchema JSON
        contract.

        All validation rules are checked and errors are accumulated.  A
        :class:`SchemaValidationError` is raised at the end if any errors
        were found.

        Args:
            schema_definition: The raw Python dictionary to validate.  Must
                conform to the contract documented in the class docstring.

        Raises:
            SchemaValidationError: If one or more validation rules are
                violated.  ``exc.errors`` contains the complete list.
            TypeError: If *schema_definition* is not a :class:`dict`.

        Returns:
            None on success.
        """
        errors: list[dict] = []

        # ── Rule 1: top-level must have "namespaces" as a non-empty dict ────
        if not isinstance(schema_definition, dict) or "namespaces" not in schema_definition:
            errors.append({
                "field": "namespaces",
                "message": 'Top-level key "namespaces" is required.',
            })
            # Cannot proceed further without the namespaces key.
            raise SchemaValidationError(errors)

        namespaces = schema_definition["namespaces"]

        if not isinstance(namespaces, dict) or len(namespaces) == 0:
            errors.append({
                "field": "namespaces",
                "message": '"namespaces" must be a non-empty dict.',
            })
            raise SchemaValidationError(errors)

        # ── Rules 2-7: iterate over each namespace and its fields ───────────
        for ns_name, ns_value in namespaces.items():
            ns_path = f"namespaces.{ns_name}"

            # Rule 2: each namespace value must be a dict
            if not isinstance(ns_value, dict):
                errors.append({
                    "field": ns_path,
                    "message": f'Namespace "{ns_name}" must be a dict of field definitions.',
                })
                continue  # Cannot validate individual fields for this namespace

            for field_name, field_def in ns_value.items():
                field_path = f"{ns_path}.{field_name}"

                if not isinstance(field_def, dict):
                    errors.append({
                        "field": field_path,
                        "message": "Field definition must be a dict.",
                    })
                    continue

                SchemaValidator._validate_field(
                    field_path=field_path,
                    field_def=field_def,
                    errors=errors,
                )

        if errors:
            raise SchemaValidationError(errors)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_field(
        field_path: str,
        field_def: dict,
        errors: list[dict],
    ) -> None:
        """
        Validate a single field definition dict, appending any errors found
        to *errors*.

        Args:
            field_path: Dot-separated path used in error reports, e.g.
                ``"namespaces.payments.amount"``.
            field_def: The field definition dict to validate.
            errors: Mutable list to which error dicts are appended.
        """
        # ── Rule 3: "type" must be present and valid ─────────────────────
        declared_type = field_def.get("type")
        type_valid = False

        if declared_type is None:
            errors.append({
                "field": field_path,
                "message": '"type" is required.',
            })
        elif declared_type not in _VALID_TYPES:
            errors.append({
                "field": field_path,
                "message": (
                    f'"type" must be one of {sorted(_VALID_TYPES)}; '
                    f'got "{declared_type}".'
                ),
            })
        else:
            type_valid = True

        # ── Rule 4: "default" must be present ────────────────────────────
        if "default" not in field_def:
            errors.append({
                "field": field_path,
                "message": '"default" is required.',
            })
        elif type_valid:
            # ── Rule 5: default must match declared type ──────────────────
            SchemaValidator._validate_default(
                field_path=field_path,
                declared_type=declared_type,  # type: ignore[arg-type]
                default_value=field_def["default"],
                errors=errors,
            )

        # ── Rules 6-7: optional constraints / policy blocks ──────────────
        if "constraints" in field_def:
            SchemaValidator._validate_constraints(
                field_path=field_path,
                constraints=field_def["constraints"],
                errors=errors,
            )

        if "policy" in field_def:
            SchemaValidator._validate_policy(
                field_path=field_path,
                policy=field_def["policy"],
                errors=errors,
            )

    @staticmethod
    def _validate_default(
        field_path: str,
        declared_type: str,
        default_value: object,
        errors: list[dict],
    ) -> None:
        """
        Validate that *default_value* matches *declared_type*.

        Special-cases:
        - ``"integer"`` rejects :class:`bool` values because ``bool`` is a
          subclass of :class:`int` in Python.
        - ``"float"`` accepts both :class:`float` and :class:`int` (not bool).

        Args:
            field_path: Dot-separated path for error messages.
            declared_type: One of the valid type strings (e.g. ``"string"``).
            default_value: The value to type-check.
            errors: Mutable list to which error dicts are appended.
        """
        checker = _TYPE_CHECKERS[declared_type]

        # bool must be rejected when declared_type is "integer"
        if declared_type == "integer" and isinstance(default_value, bool):
            errors.append({
                "field": field_path,
                "message": (
                    f'"default" must be an integer (not bool) for type "integer"; '
                    f"got {type(default_value).__name__}."
                ),
            })
            return

        # float accepts int (but not bool)
        if declared_type == "float" and isinstance(default_value, bool):
            errors.append({
                "field": field_path,
                "message": (
                    '"default" must be a float or int (not bool) for type "float".'
                ),
            })
            return

        if not isinstance(default_value, checker):
            errors.append({
                "field": field_path,
                "message": (
                    f'"default" must be of type {declared_type}; '
                    f"got {type(default_value).__name__}."
                ),
            })

    @staticmethod
    def _validate_constraints(
        field_path: str,
        constraints: object,
        errors: list[dict],
    ) -> None:
        """
        Validate the optional ``constraints`` block of a field definition.

        Rules:
        - Must be a dict.
        - Keys must be a subset of ``{min, max, allowed_values}``.
        - ``min`` and ``max`` must be numeric.
        - ``allowed_values`` must be a non-empty list.
        - When both ``min`` and ``max`` are present, ``min <= max``.

        Args:
            field_path: Dot-separated path for error messages.
            constraints: The raw value of the ``"constraints"`` key.
            errors: Mutable list to which error dicts are appended.
        """
        c_path = f"{field_path}.constraints"

        if not isinstance(constraints, dict):
            errors.append({
                "field": c_path,
                "message": '"constraints" must be a dict.',
            })
            return

        invalid_keys = set(constraints) - _VALID_CONSTRAINT_KEYS
        if invalid_keys:
            errors.append({
                "field": c_path,
                "message": (
                    f"Unknown constraint key(s): {sorted(invalid_keys)}. "
                    f"Allowed: {sorted(_VALID_CONSTRAINT_KEYS)}."
                ),
            })

        min_val = constraints.get("min")
        max_val = constraints.get("max")

        if "min" in constraints and not _is_numeric(min_val):
            errors.append({
                "field": f"{c_path}.min",
                "message": '"min" must be a numeric value (int or float, not bool).',
            })
            min_val = None  # prevent cross-check below

        if "max" in constraints and not _is_numeric(max_val):
            errors.append({
                "field": f"{c_path}.max",
                "message": '"max" must be a numeric value (int or float, not bool).',
            })
            max_val = None

        if min_val is not None and max_val is not None and min_val > max_val:
            errors.append({
                "field": c_path,
                "message": f'"min" ({min_val}) must be ≤ "max" ({max_val}).',
            })

        if "allowed_values" in constraints:
            av = constraints["allowed_values"]
            if not isinstance(av, list) or len(av) == 0:
                errors.append({
                    "field": f"{c_path}.allowed_values",
                    "message": '"allowed_values" must be a non-empty list.',
                })

    @staticmethod
    def _validate_policy(
        field_path: str,
        policy: object,
        errors: list[dict],
    ) -> None:
        """
        Validate the optional ``policy`` block of a field definition.

        Rules:
        - Must be a dict.
        - Keys must be a subset of ``{editable_by_roles, environment_restrictions}``.
        - Both keys, if present, must be non-empty lists of strings.

        Args:
            field_path: Dot-separated path for error messages.
            policy: The raw value of the ``"policy"`` key.
            errors: Mutable list to which error dicts are appended.
        """
        p_path = f"{field_path}.policy"

        if not isinstance(policy, dict):
            errors.append({
                "field": p_path,
                "message": '"policy" must be a dict.',
            })
            return

        invalid_keys = set(policy) - _VALID_POLICY_KEYS
        if invalid_keys:
            errors.append({
                "field": p_path,
                "message": (
                    f"Unknown policy key(s): {sorted(invalid_keys)}. "
                    f"Allowed: {sorted(_VALID_POLICY_KEYS)}."
                ),
            })

        for key in ("editable_by_roles", "environment_restrictions"):
            if key not in policy:
                continue
            value = policy[key]
            key_path = f"{p_path}.{key}"

            if not isinstance(value, list) or len(value) == 0:
                errors.append({
                    "field": key_path,
                    "message": f'"{key}" must be a non-empty list.',
                })
                continue

            non_strings = [item for item in value if not isinstance(item, str)]
            if non_strings:
                errors.append({
                    "field": key_path,
                    "message": (
                        f'All items in "{key}" must be strings; '
                        f"found non-string items: {non_strings}."
                    ),
                })
