import hashlib
import json
import uuid

from django.core.cache import cache
from django.db import models

from apps.config_engine.models import ConfigInstance

CACHE_TIMEOUT = 300  # seconds


class ConfigHasher:
    """Utility for producing deterministic SHA-256 hashes of config payloads."""

    @staticmethod
    def generate_hash(config_json: dict) -> str:
        """SHA256 of the JSON with keys sorted deterministically."""
        normalized = json.dumps(config_json, sort_keys=True)
        return hashlib.sha256(normalized.encode()).hexdigest()


class ConfigResolutionService:
    """
    Service layer for all ConfigInstance read/write operations.

    Resolution hierarchy (highest → lowest priority):
        user  →  tenant  →  oob
    """

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @staticmethod
    def get_active(
        config_key: str,
        scope_type: str,
        scope_id: str | None = None,
    ) -> ConfigInstance | None:
        """
        Return the single active ConfigInstance that matches
        (config_key, scope_type, scope_id), or None if not found.
        """
        try:
            return ConfigInstance.objects.get(
                config_key=config_key,
                scope_type=scope_type,
                scope_id=scope_id,
                is_active=True,
            )
        except ConfigInstance.DoesNotExist:
            return None

    @staticmethod
    def _cache_key(config_key: str, tenant_id: str | None, user_id: str | None) -> str:
        """Build a deterministic cache key for the given resolution inputs."""
        t = tenant_id or "none"
        u = user_id or "none"
        return f"config:{config_key}:{t}:{u}"

    @staticmethod
    def invalidate_cache(
        config_key: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Delete the cached result for the given (config_key, tenant_id, user_id) combination."""
        key = ConfigResolutionService._cache_key(config_key, tenant_id, user_id)
        cache.delete(key)

    @staticmethod
    def get_effective_config(
        config_key: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        """
        Resolve the effective config for a given key using the priority order:
            1. User   (scope_type='user',   scope_id=user_id)   — if user_id provided
            2. Tenant (scope_type='tenant', scope_id=tenant_id) — if tenant_id provided
            3. OOB    (scope_type='oob',    scope_id=None)

        Returns a dict:
            {
                "config":  <config_json dict>,
                "source":  "user" | "tenant" | "oob",
                "release": <release_version str>,
            }

        Results are cached for CACHE_TIMEOUT seconds (300 s by default).
        Raises ConfigInstance.DoesNotExist if no OOB config exists.
        """
        cache_key = ConfigResolutionService._cache_key(config_key, tenant_id, user_id)

        # --- cache read ---
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        candidates = []

        if user_id is not None:
            candidates.append(("user", user_id))
        if tenant_id is not None:
            candidates.append(("tenant", tenant_id))
        candidates.append(("oob", None))

        for source, scope_id in candidates:
            instance = ConfigResolutionService.get_active(config_key, source, scope_id)
            if instance is not None:
                result = {
                    "config": instance.config_json,
                    "source": source,
                    "release": instance.release_version,
                }
                # --- cache write ---
                cache.set(cache_key, result, timeout=CACHE_TIMEOUT)
                return result

        # No OOB found — surface Django's own DoesNotExist
        raise ConfigInstance.DoesNotExist(
            f"No active OOB ConfigInstance found for config_key='{config_key}'."
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @staticmethod
    def create_or_replace_override(
        config_key: str,
        scope_type: str,
        scope_id: str,
        config_json: dict,
        release_version: str,
        base_config_id: uuid.UUID | None = None,
        base_release_version: str | None = None,
        parent_config_instance_id: uuid.UUID | None = None,
    ) -> ConfigInstance:
        """
        Deactivate any existing active config for (config_key, scope_type, scope_id),
        resolve the OOB base for hash calculation, then create and return a new
        active ConfigInstance.

        If base_config_id is not provided it is auto-resolved from the current
        active OOB config for the same config_key.
        """
        # 1. Deactivate existing active override(s) for this scope
        ConfigInstance.objects.filter(
            config_key=config_key,
            scope_type=scope_type,
            scope_id=scope_id,
            is_active=True,
        ).update(is_active=False)

        # 2. Resolve OOB base for lineage / hash
        oob_instance = ConfigResolutionService.get_active(
            config_key, scope_type="oob", scope_id=None
        )

        if base_config_id is None and oob_instance is not None:
            base_config_id = oob_instance.id

        if base_release_version is None and oob_instance is not None:
            base_release_version = oob_instance.release_version

        base_config_hash = (
            ConfigHasher.generate_hash(oob_instance.config_json)
            if oob_instance is not None
            else None
        )

        # 3. Create the new active instance
        instance = ConfigInstance.objects.create(
            config_key=config_key,
            scope_type=scope_type,
            scope_id=scope_id,
            config_json=config_json,
            release_version=release_version,
            base_config_id=base_config_id,
            base_release_version=base_release_version,
            base_config_hash=base_config_hash,
            parent_config_instance_id=parent_config_instance_id,
            is_active=True,
        )

        # 4. Invalidate cached resolution for the affected scope
        tenant_id = scope_id if scope_type == "tenant" else None
        user_id   = scope_id if scope_type == "user"   else None
        ConfigResolutionService.invalidate_cache(config_key, tenant_id=tenant_id, user_id=user_id)

        return instance

    @staticmethod
    def reset_to_oob(
        config_key: str,
        scope_type: str,
        scope_id: str,
    ) -> None:
        """
        Deactivate all active overrides for (config_key, scope_type, scope_id),
        effectively falling the scope back to OOB resolution.
        """
        ConfigInstance.objects.filter(
            config_key=config_key,
            scope_type=scope_type,
            scope_id=scope_id,
            is_active=True,
        ).update(is_active=False)

        # Invalidate cached resolution for the affected scope
        tenant_id = scope_id if scope_type == "tenant" else None
        user_id   = scope_id if scope_type == "user"   else None
        ConfigResolutionService.invalidate_cache(config_key, tenant_id=tenant_id, user_id=user_id)

    # ------------------------------------------------------------------
    # Drift / staleness detection
    # ------------------------------------------------------------------

    @staticmethod
    def detect_outdated_tenant_configs() -> models.QuerySet:
        """
        Return all active tenant ConfigInstances whose base_config_id no longer
        matches the current active OOB config for the same config_key.

        A tenant config is considered outdated when the OOB it was derived from
        has since been superseded by a newer OOB version.
        """
        # Build a subquery: for each config_key, find the id of the active OOB config.
        oob_qs = (
            ConfigInstance.objects.filter(
                scope_type="oob",
                is_active=True,
            )
            .values("config_key")
            .annotate(current_oob_id=models.F("id"))
        )

        current_oob_by_key: dict[str, uuid.UUID] = {
            row["config_key"]: row["current_oob_id"] for row in oob_qs
        }

        if not current_oob_by_key:
            return ConfigInstance.objects.none()

        # Return tenant configs whose stored base_config_id doesn't match
        from django.db.models import Q

        outdated_filter = Q()
        for config_key, current_oob_id in current_oob_by_key.items():
            outdated_filter |= Q(
                config_key=config_key,
                scope_type="tenant",
                is_active=True,
            ) & ~Q(base_config_id=current_oob_id)

        return ConfigInstance.objects.filter(outdated_filter)

    @staticmethod
    def detect_drift(tenant_instance: ConfigInstance) -> bool:
        """
        Return True if the tenant config's base_config_hash differs from the
        SHA-256 hash of the *current* active OOB config_json for the same key.

        This catches cases where the OOB payload changed but the tenant config
        was not re-evaluated (even if the OOB id is the same, unlikely but
        possible in manual DB edits or test scenarios).
        """
        oob_instance = ConfigResolutionService.get_active(
            tenant_instance.config_key, scope_type="oob", scope_id=None
        )

        if oob_instance is None:
            # No OOB to compare against; treat as drifted
            return True

        current_oob_hash = ConfigHasher.generate_hash(oob_instance.config_json)
        return tenant_instance.base_config_hash != current_oob_hash
