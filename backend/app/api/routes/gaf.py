from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_gaf_controller
from app.controllers.gaf_controller import GafController
from app.schemas.gaf import GafActionInfo, GafActionRequest, GafActionResult, GafStatus
from app.schemas.game_context import GameMode
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/gaf", tags=["GAF"])

_GAME = Query(None, description="Defaults to the selected game.")
_MODE = Query(None, description="Defaults to the selected mode.")


@router.get("/status", response_model=ApiResponse[GafStatus])
async def get_status(
    request: Request,
    game: str | None = _GAME,
    mode: GameMode | None = _MODE,
    controller: GafController = Depends(get_gaf_controller),
) -> ApiResponse[GafStatus]:
    """Whether NRobot answers and a session to the game is open."""
    return ApiResponse.ok(data=await controller.status(game, mode), path=str(request.url.path))


@router.post("/connect", response_model=ApiResponse[GafStatus])
async def connect(
    request: Request,
    game: str | None = _GAME,
    mode: GameMode | None = _MODE,
    controller: GafController = Depends(get_gaf_controller),
) -> ApiResponse[GafStatus]:
    """Opens a session to the game and mode, replacing any that is open."""
    return ApiResponse.ok(data=await controller.connect(game, mode), path=str(request.url.path))


@router.post("/disconnect", response_model=ApiResponse[GafStatus])
async def disconnect(
    request: Request,
    game: str | None = _GAME,
    mode: GameMode | None = _MODE,
    controller: GafController = Depends(get_gaf_controller),
) -> ApiResponse[GafStatus]:
    return ApiResponse.ok(data=await controller.disconnect(game, mode), path=str(request.url.path))


@router.get("/actions", response_model=ApiResponse[list[GafActionInfo]])
def list_actions(
    request: Request,
    game: str | None = _GAME,
    mode: GameMode | None = _MODE,
    controller: GafController = Depends(get_gaf_controller),
) -> ApiResponse[list[GafActionInfo]]:
    """The common actions, and the ones the game's config lists."""
    return ApiResponse.ok(data=controller.list_actions(game, mode), path=str(request.url.path))


@router.post("/actions/{action_id}", response_model=ApiResponse[GafActionResult])
async def run_action(
    action_id: str,
    request: Request,
    body: GafActionRequest | None = None,
    game: str | None = _GAME,
    mode: GameMode | None = _MODE,
    controller: GafController = Depends(get_gaf_controller),
) -> ApiResponse[GafActionResult]:
    """Runs one action on the game, with the inputs `GET /actions` lists for it (if any).
    A spin is answered once it has settled, which can take a while."""
    data = await controller.run_action(action_id, body, game, mode)
    return ApiResponse.ok(data=data, path=str(request.url.path))
