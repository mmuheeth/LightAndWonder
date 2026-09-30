from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app.api.dependencies import get_cyclic_controller
from app.controllers.cyclic_controller import CyclicController
from app.schemas.cyclic import CyclicRound, CyclicStatus
from app.schemas.game_context import GameMode
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/cyclic", tags=["Cyclic messages"])


@router.get("/status", response_model=ApiResponse[CyclicStatus])
async def get_status(
    request: Request, controller: CyclicController = Depends(get_cyclic_controller)
) -> ApiResponse[CyclicStatus]:
    """Whether tracking is on, where the current spin is, and the round being captured so far."""
    return ApiResponse.ok(data=controller.status(), path=str(request.url.path))


@router.post("/tracking/start", response_model=ApiResponse[CyclicStatus])
async def start_tracking(
    request: Request,
    game: str | None = Query(None, description="Defaults to the selected game."),
    mode: GameMode | None = Query(None, description="Defaults to the selected mode."),
    controller: CyclicController = Depends(get_cyclic_controller),
) -> ApiResponse[CyclicStatus]:
    """Starts following the game's log. From each spin's reels stopping, the cyclic message areas are screenshotted
    and read with OCR until every one has cycled or held steady, or the next spin starts. Needs OBS connected.
    Nothing happens if tracking is already on."""
    return ApiResponse.ok(data=await controller.start(game, mode), path=str(request.url.path))


@router.post("/tracking/stop", response_model=ApiResponse[CyclicStatus])
async def stop_tracking(
    request: Request, controller: CyclicController = Depends(get_cyclic_controller)
) -> ApiResponse[CyclicStatus]:
    """Stops tracking; the round being captured is ended and kept."""
    return ApiResponse.ok(data=await controller.stop(), path=str(request.url.path))


@router.get("/rounds", response_model=ApiResponse[list[CyclicRound]])
def list_rounds(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    controller: CyclicController = Depends(get_cyclic_controller),
) -> ApiResponse[list[CyclicRound]]:
    """One round per spin, newest first, the one being captured included."""
    return ApiResponse.ok(data=controller.list_rounds(limit), path=str(request.url.path))


@router.get("/rounds/{round_id}/images/{filename}")
def get_round_image(
    round_id: str, filename: str, controller: CyclicController = Depends(get_cyclic_controller)
) -> FileResponse:
    return FileResponse(controller.image_path(round_id, filename), media_type="image/png")
