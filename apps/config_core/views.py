"""
apps.config_core.views
~~~~~~~~~~~~~~~~~~~~~~~
This app's views are intentionally minimal for the PoC.

The core config resolution logic lives in:
  - apps.config_core.services.override_validator  (validation)
  - apps.config_core.services.config_resolver     (merging)

These are consumed by apps.organizations.services.org_service and surfaced
via the organizations API.  No standalone endpoints are exposed for
ConfigEntry in the PoC — all access goes through /api/v1/organizations/.
"""
# Intentionally empty for PoC.
# Add ConfigEntry CRUD views here when moving beyond PoC.
