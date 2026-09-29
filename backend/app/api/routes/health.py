from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_health_controller
from app.controllers.health_controller import HealthController
from app.schemas.health import HealthCheckResponse
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=ApiResponse[HealthCheckResponse])
def health_check(
    request: Request,
    controller: HealthController = Depends(get_health_controller),
) -> ApiResponse[HealthCheckResponse]:
    result = controller.check()
    return ApiResponse.ok(data=result, path=str(request.url.path))
