from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_payline_controller
from app.controllers.payline_controller import PaylineController
from app.schemas.game_context import GameMode
from app.schemas.payline import PaylineResult
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/paylines", tags=["Paylines"])

_MIN_CONFIDENCE = Query(
    None, ge=0, le=100, description="Percent a tile must reach to be read. Defaults to the Symbol tab's setting."
)
_PAYTABLE = Query(None, description="Defaults to the paytable the game log reported last.")


@router.post("/evaluate", response_model=ApiResponse[PaylineResult])
async def evaluate_paylines(
    request: Request,
    game: str | None = Query(None, description="Defaults to the selected game."),
    mode: GameMode | None = Query(None, description="Defaults to the selected mode."),
    min_confidence: float | None = _MIN_CONFIDENCE,
    paytable: str | None = _PAYTABLE,
    controller: PaylineController = Depends(get_payline_controller),
) -> ApiResponse[PaylineResult]:
    """Takes an OBS screenshot, reads the symbols on the reels, and works out which paylines pay and the total credits."""
    data = await controller.evaluate(game, mode, min_confidence, paytable)
    return ApiResponse.ok(data=data, path=str(request.url.path))


@router.get("/score", response_model=ApiResponse[PaylineResult])
def score_paylines(
    request: Request,
    reading: str = Query(description="The id of a symbol reading, from POST /symbols/identify or /paylines/evaluate."),
    min_confidence: float | None = _MIN_CONFIDENCE,
    paytable: str | None = _PAYTABLE,
    controller: PaylineController = Depends(get_payline_controller),
) -> ApiResponse[PaylineResult]:
    """Scores a symbol reading that was made before, without a new screenshot."""
    data = controller.score_reading(reading, min_confidence, paytable)
    return ApiResponse.ok(data=data, path=str(request.url.path))
