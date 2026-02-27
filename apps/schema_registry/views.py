"""
apps.schema_registry.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~
DRF views for ConfigSchema – thin layer; all logic delegated to services.
"""
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

    def get(self, request: Request) -> Response:
        org_id = request.query_params.get("org_id")
        is_active_param = request.query_params.get("is_active")
        is_active = None
        if is_active_param is not None:
            is_active = is_active_param.lower() in ("1", "true", "yes")
        schemas = services.list_schemas(org_id=org_id, is_active=is_active)
        return Response(ConfigSchemaSerializer(schemas, many=True).data)

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

    def get(self, request: Request, pk: str) -> Response:
        schema = services.get_schema(pk)
        return Response(ConfigSchemaSerializer(schema).data)

    def patch(self, request: Request, pk: str) -> Response:
        serializer = ConfigSchemaUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        schema = services.update_schema(pk, data=serializer.validated_data)
        return Response(ConfigSchemaSerializer(schema).data)

    def delete(self, request: Request, pk: str) -> Response:
        services.delete_schema(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
