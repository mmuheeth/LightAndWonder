from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_game_context_controller
from app.controllers.game_context_controller import GameContextController
from app.schemas.game_context import GameContextResponse, GameContextUpdate
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/game-context", tags=["Game Context"])


@router.get("", response_model=ApiResponse[GameContextResponse])
def get_game_context(
    request: Request,
    controller: GameContextController = Depends(get_game_context_controller),
) -> ApiResponse[GameContextResponse]:
    return ApiResponse.ok(data=controller.get(), path=str(request.url.path))


@router.patch("", response_model=ApiResponse[GameContextResponse])
def update_game_context(
    body: GameContextUpdate,
    request: Request,
    controller: GameContextController = Depends(get_game_context_controller),
) -> ApiResponse[GameContextResponse]:
    return ApiResponse.ok(data=controller.update(body), path=str(request.url.path))
