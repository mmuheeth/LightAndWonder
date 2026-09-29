from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app.api.dependencies import get_obs_controller
from app.controllers.obs_controller import ObsController
from app.schemas.obs import (
    ObsCaptureSetup,
    ObsConfig,
    ObsStatus,
    ObsWindow,
    RecordingResult,
    ScreenshotFormat,
    ScreenshotInfo,
    ScreenshotMode,
)
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/obs", tags=["OBS"])

_MEDIA_TYPES = {".bmp": "image/bmp", ".png": "image/png"}


@router.get("/status", response_model=ApiResponse[ObsStatus])
async def get_status(
    request: Request, controller: ObsController = Depends(get_obs_controller)
) -> ApiResponse[ObsStatus]:
    return ApiResponse.ok(data=await controller.status(), path=str(request.url.path))


@router.get("/config", response_model=ApiResponse[ObsConfig])
def get_config(
    request: Request, controller: ObsController = Depends(get_obs_controller)
) -> ApiResponse[ObsConfig]:
    return ApiResponse.ok(data=controller.get_config(), path=str(request.url.path))


@router.put("/config", response_model=ApiResponse[ObsConfig])
async def update_config(
    body: ObsConfig, request: Request, controller: ObsController = Depends(get_obs_controller)
) -> ApiResponse[ObsConfig]:
    """Changes the OBS server host/port. Disconnects from the current server."""
    return ApiResponse.ok(data=await controller.update_config(body), path=str(request.url.path))


@router.post("/connect", response_model=ApiResponse[ObsStatus])
async def connect(
    request: Request, controller: ObsController = Depends(get_obs_controller)
) -> ApiResponse[ObsStatus]:
    """Launches OBS if it is not running, then connects to its websocket server."""
    return ApiResponse.ok(data=await controller.connect(), path=str(request.url.path))


@router.post("/disconnect", response_model=ApiResponse[ObsStatus])
async def disconnect(
    request: Request, controller: ObsController = Depends(get_obs_controller)
) -> ApiResponse[ObsStatus]:
    return ApiResponse.ok(data=await controller.disconnect(), path=str(request.url.path))


@router.get("/windows", response_model=ApiResponse[list[ObsWindow]])
async def list_windows(
    request: Request, controller: ObsController = Depends(get_obs_controller)
) -> ApiResponse[list[ObsWindow]]:
    """Windows OBS can capture right now."""
    return ApiResponse.ok(data=await controller.list_windows(), path=str(request.url.path))


@router.get("/window", response_model=ApiResponse[ObsCaptureSetup])
async def get_capture_setup(
    request: Request, controller: ObsController = Depends(get_obs_controller)
) -> ApiResponse[ObsCaptureSetup]:
    return ApiResponse.ok(data=await controller.capture_setup(), path=str(request.url.path))


@router.put("/window", response_model=ApiResponse[ObsCaptureSetup])
async def select_window(
    body: ObsWindow, request: Request, controller: ObsController = Depends(get_obs_controller)
) -> ApiResponse[ObsCaptureSetup]:
    """Captures this window: points OBS at it and fits the canvas to its size."""
    return ApiResponse.ok(data=await controller.select_window(body), path=str(request.url.path))


@router.post("/screenshots", response_model=ApiResponse[ScreenshotInfo])
async def take_screenshot(
    request: Request,
    image_format: ScreenshotFormat | None = Query(
        None, alias="format", description="Defaults to OBS_SCREENSHOT_FORMAT (bmp)."
    ),
    mode: ScreenshotMode | None = Query(
        None, description="Defaults to OBS_SCREENSHOT_MODE (scene)."
    ),
    controller: ObsController = Depends(get_obs_controller),
) -> ApiResponse[ScreenshotInfo]:
    """Captures the current program scene and saves it to disk, losslessly."""
    data = await controller.take_screenshot(image_format, mode)
    return ApiResponse.ok(data=data, path=str(request.url.path))


@router.get("/screenshots", response_model=ApiResponse[list[ScreenshotInfo]])
def list_screenshots(
    request: Request,
    limit: int = Query(5, ge=1, le=50),
    controller: ObsController = Depends(get_obs_controller),
) -> ApiResponse[list[ScreenshotInfo]]:
    return ApiResponse.ok(data=controller.list_screenshots(limit), path=str(request.url.path))


@router.get("/screenshots/{filename}")
def get_screenshot(
    filename: str, controller: ObsController = Depends(get_obs_controller)
) -> FileResponse:
    path = controller.screenshot_path(filename)
    return FileResponse(path, media_type=_MEDIA_TYPES[path.suffix])


@router.post("/recording/start", response_model=ApiResponse[ObsStatus])
async def start_recording(
    request: Request, controller: ObsController = Depends(get_obs_controller)
) -> ApiResponse[ObsStatus]:
    return ApiResponse.ok(data=await controller.start_recording(), path=str(request.url.path))


@router.post("/recording/stop", response_model=ApiResponse[RecordingResult])
async def stop_recording(
    request: Request, controller: ObsController = Depends(get_obs_controller)
) -> ApiResponse[RecordingResult]:
    return ApiResponse.ok(data=await controller.stop_recording(), path=str(request.url.path))
