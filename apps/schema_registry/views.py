"""
apps.schema_registry.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~
DRF views for ConfigSchema – thin layer; all logic delegated to services.
"""
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .serializers import (
    ConfigSchemaCreateSerializer,
    ConfigSchemaSerializer,
    ConfigSchemaUpdateSerializer,
)


class ConfigSchemaListCreateView(APIView):
    """GET /api/v1/schemas/  –  POST /api/v1/schemas/"""

    @extend_schema(
        summary="List Config Schemas",
        description="Return all org-scoped ConfigSchemas, optionally filtered by org_id and/or is_active.",
        parameters=[
            OpenApiParameter(name="org_id", type=int, required=False, description="Filter by organisation ID."),
            OpenApiParameter(name="is_active", type=str, required=False, description="Filter by active status (1/true/yes or 0/false/no)."),
        ],
        responses={200: ConfigSchemaSerializer(many=True)},
        tags=["Config Schemas"],
    )
    def get(self, request: Request) -> Response:
        org_id = request.query_params.get("org_id")
        is_active_param = request.query_params.get("is_active")
        is_active = None
        if is_active_param is not None:
            is_active = is_active_param.lower() in ("1", "true", "yes")
        schemas = services.list_schemas(org_id=org_id, is_active=is_active)
        return Response(ConfigSchemaSerializer(schemas, many=True).data)

    @extend_schema(
        summary="Create Config Schema",
        description="Create a new versioned ConfigSchema document under the given organisation.",
        request=ConfigSchemaCreateSerializer,
        responses={
            201: ConfigSchemaSerializer,
            409: OpenApiResponse(description="A schema with this name + version already exists for the org."),
        },
        tags=["Config Schemas"],
    )
    def post(self, request: Request) -> Response:
        serializer = ConfigSchemaCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        schema = services.create_schema(
            org_id=str(vd["org_id"]),
            name=vd["name"],
            version=vd.get("version", 1),
            schema_definition=vd["schema_definition"],
            description=vd.get("description", ""),
        )
        return Response(
            ConfigSchemaSerializer(schema).data,
            status=status.HTTP_201_CREATED,
        )


class ConfigSchemaDetailView(APIView):
    """GET / PATCH / DELETE /api/v1/schemas/<pk>/"""

    @extend_schema(
        summary="Get Config Schema",
        description="Retrieve a single ConfigSchema by its integer ID.",
        responses={
            200: ConfigSchemaSerializer,
            404: OpenApiResponse(description="Schema not found."),
        },
        tags=["Config Schemas"],
    )
    def get(self, request: Request, pk: str) -> Response:
        schema = services.get_schema(pk)
        return Response(ConfigSchemaSerializer(schema).data)

    @extend_schema(
        summary="Update Config Schema",
        description="Partially update a ConfigSchema's description, schema_definition, or is_active flag.",
        request=ConfigSchemaUpdateSerializer,
        responses={
            200: ConfigSchemaSerializer,
            404: OpenApiResponse(description="Schema not found."),
        },
        tags=["Config Schemas"],
    )
    def patch(self, request: Request, pk: str) -> Response:
        serializer = ConfigSchemaUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        schema = services.update_schema(pk, data=serializer.validated_data)
        return Response(ConfigSchemaSerializer(schema).data)

    @extend_schema(
        summary="Delete Config Schema",
        description="Soft-delete (deactivate) a ConfigSchema.",
        responses={
            204: OpenApiResponse(description="Deleted successfully."),
            404: OpenApiResponse(description="Schema not found."),
        },
        tags=["Config Schemas"],
    )
    def delete(self, request: Request, pk: str) -> Response:
        services.delete_schema(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
