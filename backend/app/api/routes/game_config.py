from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_game_config_controller
from app.controllers.game_config_controller import GameConfigController
from app.schemas.game_config import CurrentPaytable, PaytableConfig, PaytableList
from app.schemas.game_context import GameMode
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/game-config", tags=["Game Config"])

_GAME = Query(None, description="Defaults to the selected game.")
_MODE = Query(None, description="Defaults to the selected mode.")


@router.get("/current", response_model=ApiResponse[CurrentPaytable])
def get_current_paytable(
    request: Request,
    controller: GameConfigController = Depends(get_game_config_controller),
) -> ApiResponse[CurrentPaytable]:
    """The paytable the game log last reported. Reads memory only, so it is cheap to poll."""
    return ApiResponse.ok(data=controller.current(), path=str(request.url.path))


@router.get("/paytables", response_model=ApiResponse[PaytableList])
def list_paytables(
    request: Request,
    game: str | None = _GAME,
    mode: GameMode | None = _MODE,
    controller: GameConfigController = Depends(get_game_config_controller),
) -> ApiResponse[PaytableList]:
    """Every paytable folder of the game and mode."""
    data = controller.list_paytables(game, mode)
    return ApiResponse.ok(data=data, path=str(request.url.path))


@router.get("/paytables/{paytable_id}", response_model=ApiResponse[PaytableConfig])
def get_paytable(
    paytable_id: str,
    request: Request,
    game: str | None = _GAME,
    mode: GameMode | None = _MODE,
    controller: GameConfigController = Depends(get_game_config_controller),
) -> ApiResponse[PaytableConfig]:
    """What a paytable contains: summary, win geometry, payline combos, reel strips, orb values."""
    data = controller.get_paytable(paytable_id, game, mode)
    return ApiResponse.ok(data=data, path=str(request.url.path))
