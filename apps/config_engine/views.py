from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.config_engine.models import ConfigInstance
from apps.config_engine.serializers import ConfigInstanceSerializer
from apps.config_engine.services import ConfigHasher, ConfigResolutionService


@extend_schema(
    parameters=[
        OpenApiParameter("key", str, required=True, description="Config key to resolve"),
        OpenApiParameter("tenant_id", str, required=False),
        OpenApiParameter("user_id", str, required=False),
    ],
    responses={200: OpenApiResponse(description="Effective config with source and release"), 404: OpenApiResponse(description="No OOB config found")},
)
class GetEffectiveConfigView(APIView):
    """
    GET /api/v1/config/
    Query params: key (required), tenant_id (optional), user_id (optional)
    """

    def get(self, request: Request) -> Response:
        config_key = request.query_params.get("key")
        if not config_key:
            return Response(
                {"detail": "'key' query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant_id = request.query_params.get("tenant_id")
        user_id = request.query_params.get("user_id")

        try:
            result = ConfigResolutionService.get_effective_config(
                config_key=config_key,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        except ConfigInstance.DoesNotExist:
            return Response(
                {"detail": f"No active OOB config found for key '{config_key}'."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(result, status=status.HTTP_200_OK)


@extend_schema(
    request=ConfigInstanceSerializer,
    responses={201: ConfigInstanceSerializer},
)
class CreateOverrideView(APIView):
    """
    POST /api/v1/config/override/
    Body: { config_key, scope_type, tenant_id | user_id, config_json, release_version }
    """

    def post(self, request: Request) -> Response:
        data = request.data

        config_key = data.get("config_key")
        scope_type = data.get("scope_type")
        config_json = data.get("config_json")
        release_version = data.get("release_version")

        # --- validation ---
        missing = [
            f for f in ("config_key", "scope_type", "config_json", "release_version")
            if not data.get(f)
        ]
        if missing:
            return Response(
                {"detail": f"Missing required fields: {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if scope_type == "oob":
            return Response(
                {"detail": "OOB configs are immutable via the API."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if scope_type not in ("tenant", "user"):
            return Response(
                {"detail": "scope_type must be 'tenant' or 'user'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve scope_id from tenant_id / user_id
        scope_id = data.get("tenant_id") if scope_type == "tenant" else data.get("user_id")
        if not scope_id:
            return Response(
                {"detail": f"'{ 'tenant_id' if scope_type == 'tenant' else 'user_id' }' is required for scope_type='{scope_type}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance = ConfigResolutionService.create_or_replace_override(
            config_key=config_key,
            scope_type=scope_type,
            scope_id=scope_id,
            config_json=config_json,
            release_version=release_version,
            base_config_id=data.get("base_config_id"),
            base_release_version=data.get("base_release_version"),
            parent_config_instance_id=data.get("parent_config_instance_id"),
        )

        return Response(
            ConfigInstanceSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    responses={204: OpenApiResponse(description="Reset successful")},
)
class ResetToOOBView(APIView):
    """
    POST /api/v1/config/reset/
    Body: { config_key, scope_type, scope_id }
    """

    def post(self, request: Request) -> Response:
        data = request.data

        missing = [f for f in ("config_key", "scope_type", "scope_id") if not data.get(f)]
        if missing:
            return Response(
                {"detail": f"Missing required fields: {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ConfigResolutionService.reset_to_oob(
            config_key=data["config_key"],
            scope_type=data["scope_type"],
            scope_id=data["scope_id"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    parameters=[OpenApiParameter("config_key", str, required=True)],
    responses={200: ConfigInstanceSerializer(many=True)},
)
class GetLineageView(APIView):
    """
    GET /api/v1/config/lineage/
    Query param: config_key (required)
    Returns all ConfigInstances for this key across all scopes and activity states.
    """

    def get(self, request: Request) -> Response:
        config_key = request.query_params.get("config_key")
        if not config_key:
            return Response(
                {"detail": "'config_key' query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instances = (
            ConfigInstance.objects.filter(config_key=config_key)
            .order_by("created_at")
        )
        serializer = ConfigInstanceSerializer(instances, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    parameters=[
        OpenApiParameter("config_key", str, required=True),
        OpenApiParameter("scope_type", str, required=True),
        OpenApiParameter("scope_id", str, required=False),
    ],
    responses={200: OpenApiResponse(description="Diff result with drift/outdated flags"), 404: OpenApiResponse(description="Config not found")},
)
class DiffConfigView(APIView):
    """
    GET /api/v1/config/diff/
    Query params: config_key, scope_type, scope_id
    Returns the requested config alongside the active OOB config plus drift/outdated flags.
    """

    def get(self, request: Request) -> Response:
        config_key = request.query_params.get("config_key")
        scope_type = request.query_params.get("scope_type")
        scope_id = request.query_params.get("scope_id") or None

        missing = [
            p for p in ("config_key", "scope_type")
            if not request.query_params.get(p)
        ]
        if missing:
            return Response(
                {"detail": f"Missing required query params: {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target = ConfigResolutionService.get_active(
            config_key=config_key,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        if target is None:
            return Response(
                {"detail": "No active config found for the given scope."},
                status=status.HTTP_404_NOT_FOUND,
            )

        oob_instance = ConfigResolutionService.get_active(
            config_key=config_key,
            scope_type="oob",
            scope_id=None,
        )

        is_drifted = ConfigResolutionService.detect_drift(target) if oob_instance else False

        # Outdated: base_config_id no longer matches the current OOB id
        is_outdated = (
            oob_instance is not None
            and target.base_config_id != oob_instance.id
        )

        return Response(
            {
                "current": ConfigInstanceSerializer(target).data,
                "oob": ConfigInstanceSerializer(oob_instance).data if oob_instance else None,
                "is_drifted": is_drifted,
                "is_outdated": is_outdated,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    responses={200: ConfigInstanceSerializer(many=True)},
)
class OutdatedConfigsView(APIView):
    """
    GET /api/v1/config/outdated/
    Returns all active tenant configs that are outdated relative to their OOB base.
    """

    def get(self, request: Request) -> Response:
        qs = ConfigResolutionService.detect_outdated_tenant_configs()
        serializer = ConfigInstanceSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
