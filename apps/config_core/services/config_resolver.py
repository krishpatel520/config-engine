"""
apps.config_core.services.config_resolver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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
    schema, with values drawn from the highest-priority source that provides
    them.

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
        # → {"payments": {"currency": "EUR", "max_retries": 5}}
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

        1. Build *base* from schema defaults::

               {
                   namespace: {
                       field: field_def["default"]
                       for field, field_def in fields.items()
                   }
                   for namespace, fields in schema["namespaces"].items()
               }

        2. Deep-merge *org_overrides* onto *base*.  For each namespace key
           present in *org_overrides* that also exists in *base*: for each
           field key present in that namespace that also exists in the schema
           namespace, set ``base[namespace][field] = override_value``.
           Unknown namespaces and fields are silently skipped.

        3. Deep-merge *user_overrides* onto the result of step 2, using the
           same rule as step 2.

        4. Return the merged dict.

        .. note::
            Field values are treated as **atomic** — nested dicts inside a
            field value are replaced wholesale, not recursively merged.

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
            A new dict containing every namespace and field from the schema,
            with values resolved according to the merge precedence order.
            The returned dict is independent of all input dicts (deep copy
            semantics); mutating it will not affect the inputs.

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
        """
        namespaces: dict[str, dict] = schema["namespaces"]

        # ── Step 1: build base from schema defaults ───────────────────────
        # deep-copy each default value so the caller cannot mutate the result
        # back into the schema definition.
        base: dict[str, dict] = {
            namespace: {
                fname: copy.deepcopy(fdef["default"])
                for fname, fdef in fields.items()
            }
            for namespace, fields in namespaces.items()
        }

        # ── Steps 2 & 3: apply override layers ───────────────────────────
        for override_layer in (org_overrides, user_overrides):
            ConfigResolver._apply_overrides(base, namespaces, override_layer)

        return base

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_overrides(
        base: dict[str, dict],
        schema_namespaces: dict[str, dict],
        overrides: dict | None,
    ) -> None:
        """
        Mutate *base* in-place by applying a single override layer.

        Unknown namespaces and unknown fields within a known namespace are
        silently skipped.  Field values are treated as atomic — no recursive
        merge is performed within a field value.

        Args:
            base: The mutable resolved-config dict built from schema defaults
                (and potentially already patched by a previous override layer).
            schema_namespaces: The ``"namespaces"`` dict from the schema,
                used to identify which namespaces and fields are valid.
            overrides: The override blob to merge, or ``None`` / ``{}`` to
                skip this layer entirely.
        """
        if not overrides:
            return

        for ns_name, ns_overrides in overrides.items():
            # Silently skip unknown namespaces
            if ns_name not in schema_namespaces:
                continue
            if not isinstance(ns_overrides, dict):
                continue

            schema_fields: dict = schema_namespaces[ns_name]

            for field_name, override_value in ns_overrides.items():
                # Silently skip unknown fields
                if field_name not in schema_fields:
                    continue

                # Treat field values as atomic — deep-copy so the caller
                # cannot mutate the result through the override dict reference.
                base[ns_name][field_name] = copy.deepcopy(override_value)
