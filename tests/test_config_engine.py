"""
tests.test_config_engine
~~~~~~~~~~~~~~~~~~~~~~~~~
Comprehensive pytest-django test suite for the config_engine project.

Covers:
- SchemaValidator   (unit, no DB)
- OverrideValidationService  (unit, no DB)
- ConfigResolver    (unit, no DB)
- API Endpoints     (integration, DB)
"""
from __future__ import annotations

import uuid

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.config_core.services.config_resolver import ConfigResolver
from apps.config_core.services.override_validator import (
    OverrideValidationRequest,
    OverrideValidationService,
)
from apps.organizations.models import Organization
from apps.schema_registry.models import GlobalConfigSchema
from apps.schema_registry.validators import SchemaValidationError, SchemaValidator


# ===========================================================================
# Shared realistic schema
# ===========================================================================

# Used by both unit tests (no DB) and integration fixtures (DB).
REALISTIC_SCHEMA: dict = {
    "namespaces": {
        "payments": {
            # required, editable, constrained with min/max
            "max_transaction_limit": {
                "type": "float",
                "default": 10000.0,
                "required": True,
                "editable": True,
                "constraints": {"min": 100, "max": 500000},
            },
            # required, editable, constrained with allowed_values
            "currency": {
                "type": "string",
                "default": "USD",
                "required": True,
                "editable": True,
                "constraints": {"allowed_values": ["USD", "EUR", "GBP", "JPY"]},
            },
            # immutable – must never appear in overrides
            "processor_id": {
                "type": "string",
                "default": "stripe_v2",
                "required": False,
                "editable": False,
            },
            # role-restricted
            "fee_percentage": {
                "type": "float",
                "default": 2.5,
                "required": False,
                "editable": True,
                "policy": {
                    "editable_by_roles": ["admin", "finance"],
                },
            },
        },
        "features": {
            # env-restricted
            "dark_mode": {
                "type": "boolean",
                "default": False,
                "required": False,
                "editable": True,
                "policy": {
                    "environment_restrictions": ["staging", "dev"],
                },
            },
            # non-required, freely editable
            "max_users": {
                "type": "integer",
                "default": 50,
                "required": False,
                "editable": True,
                "constraints": {"min": 1, "max": 10000},
            },
        },
    }
}


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def active_schema(db) -> GlobalConfigSchema:
    """
    Create and return a GlobalConfigSchema with is_active=True using the
    realistic REALISTIC_SCHEMA containing 2 namespaces and 6 fields covering:
    required, non-required, editable=False, role-restricted, env-restricted,
    and constrained fields.
    """
    return GlobalConfigSchema.objects.create(
        schema_version="1.0.0",
        schema_definition=REALISTIC_SCHEMA,
        is_active=True,
    )


@pytest.fixture
def org(db) -> Organization:
    """Create and return an Organisation with empty config_overrides."""
    return Organization.objects.create(name="Test Corp", config_overrides={})


@pytest.fixture
def schema_dict(active_schema: GlobalConfigSchema) -> dict:
    """Return the raw schema_definition dict from the active schema fixture."""
    return active_schema.schema_definition


@pytest.fixture
def api_client() -> APIClient:
    """Return an unauthenticated DRF APIClient."""
    return APIClient()


# ===========================================================================
# TestSchemaValidation  (unit — no DB)
# ===========================================================================

class TestSchemaValidation:
    """Unit tests for SchemaValidator.  No database access required."""

    def test_valid_schema_passes(self):
        """A well-formed schema raises no exception."""
        SchemaValidator.validate(REALISTIC_SCHEMA)  # must not raise

    def test_missing_namespaces_key_raises(self):
        """Top-level dict without 'namespaces' must raise."""
        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaValidator.validate({"not_namespaces": {}})
        codes = [e["field"] for e in exc_info.value.errors]
        assert "namespaces" in codes

    def test_missing_type_raises(self):
        """A field definition without 'type' must raise."""
        bad = {
            "namespaces": {
                "ns": {
                    "field_a": {"default": "hello"}  # no "type"
                }
            }
        }
        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaValidator.validate(bad)
        fields = [e["field"] for e in exc_info.value.errors]
        assert any("field_a" in f for f in fields)

    def test_missing_default_raises(self):
        """A field definition without 'default' must raise."""
        bad = {
            "namespaces": {
                "ns": {
                    "field_b": {"type": "string"}  # no "default"
                }
            }
        }
        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaValidator.validate(bad)
        fields = [e["field"] for e in exc_info.value.errors]
        assert any("field_b" in f for f in fields)

    def test_type_mismatch_default_raises(self):
        """When default type doesn't match declared type, error must be raised."""
        bad = {
            "namespaces": {
                "ns": {
                    # declared integer but default is a string
                    "count": {"type": "integer", "default": "not-an-int"}
                }
            }
        }
        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaValidator.validate(bad)
        assert any("count" in e["field"] for e in exc_info.value.errors)

    def test_invalid_constraint_min_gt_max_raises(self):
        """Constraint with min > max must raise."""
        bad = {
            "namespaces": {
                "ns": {
                    "amount": {
                        "type": "float",
                        "default": 1.0,
                        "constraints": {"min": 100, "max": 10},  # min > max
                    }
                }
            }
        }
        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaValidator.validate(bad)
        assert any("min" in e["message"] or "max" in e["message"]
                   for e in exc_info.value.errors)

    def test_invalid_policy_empty_roles_raises(self):
        """Policy with an empty editable_by_roles list must raise."""
        bad = {
            "namespaces": {
                "ns": {
                    "fee": {
                        "type": "float",
                        "default": 1.0,
                        "policy": {"editable_by_roles": []},  # empty list
                    }
                }
            }
        }
        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaValidator.validate(bad)
        assert any("editable_by_roles" in e["field"] for e in exc_info.value.errors)

    def test_all_errors_collected(self):
        """Multiple broken fields must produce multiple errors in one raise."""
        bad = {
            "namespaces": {
                "ns": {
                    # missing type AND default
                    "field_x": {},
                    # type mismatch on default
                    "field_y": {"type": "integer", "default": "oops"},
                }
            }
        }
        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaValidator.validate(bad)
        # Should contain at least 3 errors (type missing, default missing for
        # field_x; type-mismatch for field_y).
        assert len(exc_info.value.errors) >= 3


# ===========================================================================
# TestOverrideValidation  (unit — no DB)
# ===========================================================================

class TestOverrideValidation:
    """Unit tests for OverrideValidationService.  No database access required."""

    def _make_request(self, overrides: dict, role: str = "admin", env: str = "prod"):
        return OverrideValidationRequest(
            schema=REALISTIC_SCHEMA,
            overrides=overrides,
            acting_role=role,
            environment=env,
        )

    def test_valid_override_passes(self):
        """A well-formed override must return valid=True."""
        req = self._make_request(
            {"payments": {"max_transaction_limit": 20000.0, "currency": "EUR"}}
        )
        result = OverrideValidationService.validate(req)
        assert result.valid is True
        assert result.errors == []

    def test_unknown_field_rejected(self):
        """A field that doesn't exist in the schema must be reported as unknown_field."""
        req = self._make_request({"payments": {"nonexistent_field": 99}})
        result = OverrideValidationService.validate(req)
        assert result.valid is False
        assert any(e["code"] == "unknown_field" for e in result.errors)

    def test_required_field_removal_rejected(self):
        """When a required field is absent from its overridden namespace, error reported."""
        # Override the 'payments' namespace but omit required 'currency'
        req = self._make_request({"payments": {"max_transaction_limit": 200.0}})
        result = OverrideValidationService.validate(req)
        assert result.valid is False
        assert any(e["code"] == "missing_required" and "currency" in e["field"]
                   for e in result.errors)

    def test_immutable_field_rejected(self):
        """A field with editable=False must yield immutable_field error code."""
        req = self._make_request(
            {"payments": {
                "max_transaction_limit": 200.0,
                "currency": "EUR",
                "processor_id": "other_processor",  # editable=False
            }}
        )
        result = OverrideValidationService.validate(req)
        assert result.valid is False
        assert any(e["code"] == "immutable_field" for e in result.errors)

    def test_role_forbidden(self):
        """Acting role not in editable_by_roles must yield role_forbidden."""
        req = self._make_request(
            {"payments": {
                "max_transaction_limit": 200.0,
                "currency": "EUR",
                "fee_percentage": 3.0,  # editable_by_roles: ["admin", "finance"]
            }},
            role="viewer",  # not in allowed roles
        )
        result = OverrideValidationService.validate(req)
        assert result.valid is False
        assert any(e["code"] == "role_forbidden" and "fee_percentage" in e["field"]
                   for e in result.errors)

    def test_env_forbidden(self):
        """Environment not in environment_restrictions must yield env_forbidden."""
        req = self._make_request(
            {"features": {"dark_mode": True}},  # environment_restrictions: ["staging","dev"]
            env="prod",  # not in allowed envs
        )
        result = OverrideValidationService.validate(req)
        assert result.valid is False
        assert any(e["code"] == "env_forbidden" and "dark_mode" in e["field"]
                   for e in result.errors)

    def test_type_mismatch_rejected(self):
        """Override value of wrong type must yield type_mismatch error."""
        req = self._make_request(
            {"payments": {
                "max_transaction_limit": "not-a-number",  # should be float
                "currency": "USD",
            }}
        )
        result = OverrideValidationService.validate(req)
        assert result.valid is False
        assert any(e["code"] == "type_mismatch" and "max_transaction_limit" in e["field"]
                   for e in result.errors)

    def test_constraint_min_violation(self):
        """Value below min constraint must yield constraint_violation."""
        req = self._make_request(
            {"payments": {
                "max_transaction_limit": 50.0,  # min is 100
                "currency": "USD",
            }}
        )
        result = OverrideValidationService.validate(req)
        assert result.valid is False
        assert any(e["code"] == "constraint_violation" for e in result.errors)

    def test_constraint_max_violation(self):
        """Value above max constraint must yield constraint_violation."""
        req = self._make_request(
            {"payments": {
                "max_transaction_limit": 999999.0,  # max is 500000
                "currency": "USD",
            }}
        )
        result = OverrideValidationService.validate(req)
        assert result.valid is False
        assert any(e["code"] == "constraint_violation" for e in result.errors)

    def test_constraint_allowed_values_violation(self):
        """Value not in allowed_values must yield constraint_violation."""
        req = self._make_request(
            {"payments": {
                "max_transaction_limit": 200.0,
                "currency": "CAD",  # not in ["USD","EUR","GBP","JPY"]
            }}
        )
        result = OverrideValidationService.validate(req)
        assert result.valid is False
        assert any(
            e["code"] == "constraint_violation" and "currency" in e["field"]
            for e in result.errors
        )

    def test_multiple_errors_all_returned(self):
        """A single validate() call with multiple violations returns all errors."""
        req = self._make_request(
            {"payments": {
                "max_transaction_limit": 50.0,   # below min → constraint_violation
                "currency": "CAD",               # not allowed → constraint_violation
                "processor_id": "hijacked",      # editable=False → immutable_field
                "fee_percentage": 9.9,           # role_forbidden (role=viewer)
            }},
            role="viewer",
        )
        result = OverrideValidationService.validate(req)
        assert result.valid is False
        codes = {e["code"] for e in result.errors}
        assert "immutable_field" in codes
        assert "role_forbidden" in codes
        assert "constraint_violation" in codes
        assert len(result.errors) >= 3


# ===========================================================================
# TestConfigResolver  (unit — no DB)
# ===========================================================================

class TestConfigResolver:
    """Unit tests for ConfigResolver.  No database access required."""

    def test_defaults_only_no_overrides(self):
        """With no overrides the result must equal the schema defaults."""
        result = ConfigResolver.resolve(schema=REALISTIC_SCHEMA)
        assert result["payments"]["max_transaction_limit"] == 10000.0
        assert result["payments"]["currency"] == "USD"
        assert result["payments"]["processor_id"] == "stripe_v2"
        assert result["features"]["dark_mode"] is False
        assert result["features"]["max_users"] == 50

    def test_org_overrides_applied(self):
        """Org overrides must replace defaults for the specified fields."""
        org_overrides = {"payments": {"currency": "EUR"}}
        result = ConfigResolver.resolve(schema=REALISTIC_SCHEMA, org_overrides=org_overrides)
        assert result["payments"]["currency"] == "EUR"
        # Other fields must still be defaults
        assert result["payments"]["max_transaction_limit"] == 10000.0

    def test_user_overrides_take_precedence_over_org(self):
        """User overrides must win over org overrides."""
        org_overrides = {"payments": {"currency": "EUR"}}
        user_overrides = {"payments": {"currency": "GBP"}}
        result = ConfigResolver.resolve(
            schema=REALISTIC_SCHEMA,
            org_overrides=org_overrides,
            user_overrides=user_overrides,
        )
        assert result["payments"]["currency"] == "GBP"

    def test_unknown_override_fields_silently_ignored(self):
        """Unknown namespaces and fields in overrides must be silently skipped."""
        org_overrides = {
            "ghost_namespace": {"ghost_field": 42},
            "payments": {"ghost_field": "ignored", "currency": "GBP"},
        }
        result = ConfigResolver.resolve(schema=REALISTIC_SCHEMA, org_overrides=org_overrides)
        assert "ghost_namespace" not in result
        assert "ghost_field" not in result["payments"]
        assert result["payments"]["currency"] == "GBP"

    def test_all_schema_fields_always_present_in_result(self):
        """Every namespace and field from the schema must appear in the result."""
        result = ConfigResolver.resolve(schema=REALISTIC_SCHEMA)
        for ns, fields in REALISTIC_SCHEMA["namespaces"].items():
            assert ns in result, f"Namespace '{ns}' missing from result"
            for fname in fields:
                assert fname in result[ns], f"Field '{ns}.{fname}' missing from result"

    def test_none_overrides_treated_as_empty(self):
        """None for either override parameter must produce pure defaults."""
        result_none = ConfigResolver.resolve(
            schema=REALISTIC_SCHEMA, org_overrides=None, user_overrides=None
        )
        result_empty = ConfigResolver.resolve(
            schema=REALISTIC_SCHEMA, org_overrides={}, user_overrides={}
        )
        assert result_none == result_empty


# ===========================================================================
# TestAPIEndpoints  (integration — DB)
# ===========================================================================

CREATE_URL = "/api/v1/organizations/"


def config_url(org_id):
    return f"/api/v1/organizations/{org_id}/config/"


def effective_config_url(org_id):
    return f"/api/v1/organizations/{org_id}/effective-config/"


ACTIVE_SCHEMA_URL = "/api/v1/schema/active/"


@pytest.mark.django_db
class TestAPIEndpoints:
    """Integration tests against all four API endpoints using actual DB."""

    # ── POST /organizations/ ────────────────────────────────────────────────

    def test_create_organization_201(self, api_client):
        """POST /organizations/ with a unique name returns 201 and org data."""
        resp = api_client.post(
            CREATE_URL,
            data={"name": "New Org"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert body["name"] == "New Org"
        assert body["config_overrides"] == {}
        assert "id" in body
        assert "created_at" in body

    # ── PUT /organizations/{id}/config/ ─────────────────────────────────────

    def test_put_config_valid_returns_200_with_effective_config(
        self, api_client, org, active_schema
    ):
        """Valid overrides are saved and effective_config is returned."""
        payload = {
            "overrides": {
                "payments": {
                    "max_transaction_limit": 25000.0,
                    "currency": "EUR",
                }
            },
            "acting_role": "admin",
            "environment": "prod",
        }
        resp = api_client.put(config_url(org.id), data=payload, format="json")
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert "effective_config" in body
        assert body["effective_config"]["payments"]["currency"] == "EUR"
        assert body["effective_config"]["payments"]["max_transaction_limit"] == 25000.0
        # Schema defaults still present for non-overridden fields
        assert "processor_id" in body["effective_config"]["payments"]

    def test_put_config_invalid_returns_400_with_errors(
        self, api_client, org, active_schema
    ):
        """Invalid overrides return 400 with an 'errors' list."""
        payload = {
            "overrides": {
                "payments": {
                    "max_transaction_limit": 50.0,  # below min=100
                    "currency": "CAD",              # not in allowed_values
                }
            },
            "acting_role": "admin",
            "environment": "prod",
        }
        resp = api_client.put(config_url(org.id), data=payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        body = resp.json()
        assert "errors" in body
        assert len(body["errors"]) >= 1
        codes = {e["code"] for e in body["errors"]}
        assert "constraint_violation" in codes

    # ── GET /organizations/{id}/effective-config/ ───────────────────────────

    def test_get_effective_config_200(self, api_client, org, active_schema):
        """GET returns 200 with effective_config reflecting schema defaults."""
        resp = api_client.get(effective_config_url(org.id))
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert "effective_config" in body
        ef = body["effective_config"]
        assert "payments" in ef
        assert "features" in ef
        # With no overrides, defaults should be returned
        assert ef["payments"]["currency"] == "USD"
        assert ef["features"]["dark_mode"] is False

    # ── GET /schema/active/ ──────────────────────────────────────────────────

    def test_get_active_schema_200(self, api_client, active_schema):
        """GET /schema/active/ returns 200 with schema fields when one is active."""
        resp = api_client.get(ACTIVE_SCHEMA_URL)
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert body["schema_version"] == "1.0.0"
        assert "schema_definition" in body
        assert "namespaces" in body["schema_definition"]
        assert active_schema.id == body["id"]

    def test_get_active_schema_404_when_none(self, api_client, db):
        """GET /schema/active/ returns 404 when no active schema exists."""
        # Ensure no active schema exists
        GlobalConfigSchema.objects.filter(is_active=True).update(is_active=False)
        resp = api_client.get(ACTIVE_SCHEMA_URL)
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# Coverage Additions for Views and Services
# ===========================================================================

@pytest.mark.django_db
class TestCoverageAdditions:
    """Extra tests to hit 100% line coverage for apps/organizations/views.py etc."""

    def test_create_organization_duplicate_409(self, api_client, org):
        """Line 56-57 in apps/organizations/views.py"""
        resp = api_client.post(CREATE_URL, data={"name": org.name}, format="json")
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert "already exists" in resp.json()["detail"]

    def test_schema_list_create_get(self, api_client, org):
        """Lines 23-29 in apps/schema_registry/views.py"""
        from apps.schema_registry import services
        services.create_schema(org_id=str(org.id), name="Cov Schema", schema_definition={})
        res = api_client.get(f"/api/v1/schemas/?org_id={org.id}&is_active=1")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()) >= 1

    def test_schema_list_create_post(self, api_client, org):
        """Lines 32-42 in apps/schema_registry/views.py"""
        data = {
            "org_id": org.id,
            "name": "Cov Schema Post",
            "version": 1,
            "schema_definition": {},
            "description": "desc"
        }
        res = api_client.post("/api/v1/schemas/", data=data, format="json")
        assert res.status_code == status.HTTP_201_CREATED

    def test_schema_detail_get_patch_delete(self, api_client, org):
        """Lines 52-53, 56-59, 62-63 in apps/schema_registry/views.py"""
        from apps.schema_registry import services
        schema = services.create_schema(org_id=str(org.id), name="Cov Detail", schema_definition={})
        
        # GET
        res = api_client.get(f"/api/v1/schemas/{schema.id}/")
        assert res.status_code == status.HTTP_200_OK

        # PATCH
        res = api_client.patch(f"/api/v1/schemas/{schema.id}/", data={"description": "new"}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.json()["description"] == "new"

        # DELETE
        res = api_client.delete(f"/api/v1/schemas/{schema.id}/")
        assert res.status_code == status.HTTP_204_NO_CONTENT
        
    def test_schema_services_get_missing(self, db):
        """Lines in apps/schema_registry/services.py (get_schema 404)"""
        from apps.schema_registry import services
        from common.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            services.get_schema(999999)

    def test_schema_services_create_conflict(self, db, org):
        """Lines in apps/schema_registry/services.py (create_schema conflict)"""
        from apps.schema_registry import services
        from common.exceptions import ConflictError
        services.create_schema(org_id=str(org.id), name="dup", schema_definition={}, version=1)
        with pytest.raises(ConflictError):
            services.create_schema(org_id=str(org.id), name="dup", schema_definition={}, version=1)
