"""
apps.organizations.views
~~~~~~~~~~~~~~~~~~~~~~~~~
Thin DRF API views for the Organizations application.
All business logic is delegated to
:mod:`apps.organizations.services.org_service`.

Endpoints
---------
POST   /organizations/                   – Create organisation
PUT    /organizations/{id}/config/       – Apply + validate config overrides
GET    /organizations/{id}/effective-config/ – Resolve effective config
GET    /schema/active/                   – Return active GlobalConfigSchema
"""
from __future__ import annotations

from django.db import IntegrityError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.services import org_service
from .serializers import (
    ActiveSchemaSerializer,
    EffectiveConfigResponseSerializer,
    OrganizationCreateSerializer,
    OrganizationSerializer,
    PutConfigRequestSerializer,
    ValidationErrorResponseSerializer,
)


class OrganizationCreateView(APIView):
    """POST /organizations/ – create a new organisation."""

    @extend_schema(
        summary="Create Organisation",
        description="Creates a new organisation with empty config overrides.",
        request=OrganizationCreateSerializer,
        responses={
            201: OrganizationSerializer,
            400: OpenApiResponse(description="Validation error – name missing or blank."),
            409: OpenApiResponse(description="An organisation with that name already exists."),
        },
        tags=["Organizations"],
    )
    def post(self, request: Request) -> Response:
        serializer = OrganizationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            org = org_service.create_organization(
                name=serializer.validated_data["name"]
            )
        except IntegrityError:
            return Response(
                {"detail": "An organisation with that name already exists."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            OrganizationSerializer(org).data,
            status=status.HTTP_201_CREATED,
        )


class OrganizationConfigView(APIView):
    """PUT /organizations/{id}/config/ – validate and apply config overrides."""

    @extend_schema(
        summary="Apply Config Overrides",
        description=(
            "Validates the supplied overrides against the active GlobalConfigSchema "
            "using OverrideValidationService.  On success, persists the overrides and "
            "returns the fully-resolved effective config.  On failure, returns 400 "
            "with the list of validation errors."
        ),
        request=PutConfigRequestSerializer,
        responses={
            200: EffectiveConfigResponseSerializer,
            400: ValidationErrorResponseSerializer,
            404: OpenApiResponse(
                description="Organisation not found or no active schema."
            ),
        },
        tags=["Organizations"],
    )
    def put(self, request: Request, org_id: str) -> Response:
        serializer = PutConfigRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        result, effective_config = org_service.apply_config_overrides(
            org_id=org_id,
            overrides=vd["overrides"],
            acting_role=vd["acting_role"],
            environment=vd["environment"],
        )

        if not result.valid:
            return Response(
                {"errors": result.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"effective_config": effective_config},
            status=status.HTTP_200_OK,
        )


class OrganizationEffectiveConfigView(APIView):
    """GET /organizations/{id}/effective-config/ – resolve effective config."""

    @extend_schema(
        summary="Get Effective Config",
        description=(
            "Fetches the active GlobalConfigSchema and merges org overrides on top "
            "of schema defaults to produce the fully-resolved effective configuration."
        ),
        responses={
            200: EffectiveConfigResponseSerializer,
            404: OpenApiResponse(
                description="Organisation not found or no active schema."
            ),
        },
        tags=["Organizations"],
    )
    def get(self, request: Request, org_id: str) -> Response:
        effective_config = org_service.get_effective_config(org_id=org_id)
        return Response(
            {"effective_config": effective_config},
            status=status.HTTP_200_OK,
        )


class ActiveSchemaView(APIView):
    """GET /schema/active/ – return the currently active GlobalConfigSchema."""

    @extend_schema(
        summary="Get Active Schema",
        description=(
            "Returns the currently active GlobalConfigSchema record. "
            "Returns 404 if no schema has been activated."
        ),
        responses={
            200: ActiveSchemaSerializer,
            404: OpenApiResponse(description="No active schema found."),
        },
        tags=["Schema"],
    )
    def get(self, request: Request) -> Response:
        schema = org_service.get_active_schema()
        return Response(
            ActiveSchemaSerializer(schema).data,
            status=status.HTTP_200_OK,
        )
