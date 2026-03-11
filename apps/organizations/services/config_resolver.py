"""
apps.organizations.services.config_resolver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Deterministic, pure-function configuration resolver.

Merge precedence (lowest → highest priority):
    1. **Schema defaults** - every field's ``"default"`` value declared in the
       ``GlobalConfigSchema.schema_definition``.  This is the foundation and
       always provides every field defined in the schema.
    2. **Org overrides** - the organisation's stored override blob.  Fields
       present here replace the corresponding schema defaults.
    3. **User overrides** - the requesting user's session/preference overrides.
       Fields present here take final precedence over both defaults and org
       overrides.

Unknown namespaces or fields in either override layer are silently ignored
so that stale overrides do not break resolution as the schema evolves.

The function is **pure** — input dicts are never mutated.  Given the same
inputs it always returns an identical output (no randomness, no I/O, no
side-effects).

This module is **pure Python** — it has zero Django view, serializer,
or ORM imports.

Public API
----------
ConfigResolver.resolve(schema, org_overrides, user_overrides) -> dict
"""
from __future__ import annotations

import copy


class ConfigResolver:
    """
    Merges a ``GlobalConfigSchema`` definition with optional organisation-
    and user-level override blobs to produce a fully-resolved configuration
    dict.

    The result always contains **every namespace and field** declared in the
    schema, preserving all field metadata (``type``, ``editable``, ``required``,
    ``constraints``, ``policy``, etc.), with the ``"default"`` key of each
    overridden field replaced by the override value.

    Example::

        schema = {
            "namespaces": {
                "payments": {
                    "currency": {"type": "string", "default": "USD"},
                    "max_retries": {"type": "integer", "default": 3},
                }
            }
        }
        org_overrides  = {"payments": {"currency": "EUR"}}
        user_overrides = {"payments": {"max_retries": 5}}

        resolved = ConfigResolver.resolve(schema, org_overrides, user_overrides)
        # → {
        #     "namespaces": {
        #         "payments": {
        #             "currency": {"type": "string", "default": "EUR"},
        #             "max_retries": {"type": "integer", "default": 5},
        #         }
        #     }
        #   }
    """

    @staticmethod
    def resolve(
        schema: dict,
        org_overrides: dict | None = None,
        user_overrides: dict | None = None,
    ) -> dict:
        """
        Produce a fully-resolved configuration dict by merging schema
        defaults, organisation overrides, and user overrides.

        **Merge algorithm** (executed in this exact order):

        1. Deep-copy the entire ``"namespaces"`` structure from the schema,
           preserving all field metadata (``type``, ``default``, ``editable``,
           ``required``, ``constraints``, ``policy``, etc.).

        2. Deep-merge *org_overrides* onto the copy.  For each namespace key
           present in *org_overrides* that also exists in the copy: for each
           field key present in that namespace that also exists in the schema
           namespace, replace ``copy[namespace][field]["default"]`` with the
           override value.  Unknown namespaces and fields are silently skipped.

        3. Deep-merge *user_overrides* onto the result of step 2, using the
           same rule as step 2.

        4. Return ``{"namespaces": <merged copy>}`` — the same top-level shape
           as the original ``GlobalConfigSchema.schema_definition``.

        .. note::
            The ``"default"`` key inside each field definition holds the
            effective resolved value for that field.  All other field metadata
            (type, constraints, policy, etc.) is preserved verbatim from the
            schema.

        Args:
            schema: A structurally valid ``GlobalConfigSchema.schema_definition``
                dict (must contain a ``"namespaces"`` key).
            org_overrides: Organisation-level override blob shaped as
                ``{namespace_name: {field_name: value}}``.  ``None`` or ``{}``
                means "no org overrides"; the result will reflect pure
                schema defaults for every field.
            user_overrides: User-level override blob, same shape as
                *org_overrides*.  ``None`` or ``{}`` means "no user
                overrides".

        Returns:
            A new dict with the shape ``{"namespaces": {namespace: {field: field_def}}}``
            containing every namespace and field from the schema, with the
            ``"default"`` key of each overridden field replaced by the
            override value.  The returned dict is independent of all input
            dicts (deep copy semantics); mutating it will not affect the inputs.

        Raises:
            KeyError: If *schema* does not contain a ``"namespaces"`` key.
                Callers should ensure the schema has been validated by
                :class:`~apps.schema_registry.validators.SchemaValidator`
                before calling this method.

        Example::

            resolved = ConfigResolver.resolve(
                schema=gs.schema_definition,
                org_overrides=org.config_overrides,
                user_overrides=session.get("user_overrides"),
            )
            # resolved["namespaces"]["payments"]["currency"]["default"]
            # → the effective currency for this org.
        """
        # ── Step 1: deep-copy the full schema namespace structure ─────────
        # This preserves all field metadata (type, editable, constraints, …).
        base: dict[str, dict] = copy.deepcopy(schema["namespaces"])

        # ── Steps 2 & 3: apply override layers ───────────────────────────
        for override_layer in (org_overrides, user_overrides):
            ConfigResolver._apply_overrides(base, override_layer)

        return {"namespaces": base}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_overrides(
        base: dict[str, dict],
        overrides: dict | None,
    ) -> None:
        """
        Mutate *base* in-place by applying a single override layer.

        For each overridden field, only the ``"default"`` key inside the
        field definition dict is replaced.  All other field metadata is
        preserved.  Unknown namespaces and unknown fields within a known
        namespace are silently skipped.

        Args:
            base: The mutable deep-copied namespaces dict (keyed by namespace
                name, then field name, then field definition dict).
            overrides: The override blob to merge, or ``None`` / ``{}`` to
                skip this layer entirely.
        """
        if not overrides:
            return

        for ns_name, ns_overrides in overrides.items():
            # Silently skip unknown namespaces
            if ns_name not in base:
                continue
            if not isinstance(ns_overrides, dict):
                continue

            ns_fields: dict = base[ns_name]

            for field_name, override_value in ns_overrides.items():
                # Silently skip unknown fields
                if field_name not in ns_fields:
                    continue

                # Patch only the "default" key; all other metadata is kept.
                ns_fields[field_name]["default"] = copy.deepcopy(override_value)
