from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app.api.dependencies import get_roi_controller
from app.controllers.roi_controller import RoiController
from app.schemas.game_context import GameMode
from app.schemas.response import ApiResponse
from app.schemas.roi import RoiRecord

router = APIRouter(prefix="/roi", tags=["ROI"])


@router.post("/records", response_model=ApiResponse[RoiRecord])
async def extract_roi(
    request: Request,
    game: str | None = Query(None, description="Defaults to the selected game."),
    mode: GameMode | None = Query(None, description="Defaults to the selected mode."),
    controller: RoiController = Depends(get_roi_controller),
) -> ApiResponse[RoiRecord]:
    """Takes an OBS screenshot and cuts the game's regions of interest and reel tiles out of it."""
    data = await controller.extract(game, mode)
    return ApiResponse.ok(data=data, path=str(request.url.path))


@router.get("/records", response_model=ApiResponse[list[RoiRecord]])
def list_roi_records(
    request: Request,
    limit: int = Query(5, ge=1, le=50),
    controller: RoiController = Depends(get_roi_controller),
) -> ApiResponse[list[RoiRecord]]:
    return ApiResponse.ok(data=controller.list_records(limit), path=str(request.url.path))


@router.get("/records/{record_id}/images/{filename}")
def get_roi_image(
    record_id: str, filename: str, controller: RoiController = Depends(get_roi_controller)
) -> FileResponse:
    return FileResponse(controller.image_path(record_id, filename), media_type="image/png")
