from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_symbol_controller
from app.controllers.symbol_controller import SymbolController
from app.schemas.game_context import GameMode
from app.schemas.response import ApiResponse
from app.schemas.symbol import SymbolModelStatus, SymbolReading

router = APIRouter(prefix="/symbols", tags=["Symbols"])


@router.get("/model", response_model=ApiResponse[SymbolModelStatus])
def get_symbol_model(
    request: Request,
    game: str | None = Query(None, description="Defaults to the selected game."),
    controller: SymbolController = Depends(get_symbol_controller),
) -> ApiResponse[SymbolModelStatus]:
    """Whether the game's symbol classifier is trained, being trained, or missing."""
    return ApiResponse.ok(data=controller.model_status(game), path=str(request.url.path))


@router.post("/model/train", response_model=ApiResponse[SymbolModelStatus])
def train_symbol_model(
    request: Request,
    game: str | None = Query(None, description="Defaults to the selected game."),
    controller: SymbolController = Depends(get_symbol_controller),
) -> ApiResponse[SymbolModelStatus]:
    """Starts fitting ResNet34 to the game's symbol artwork and returns at once; poll GET /symbols/model."""
    return ApiResponse.ok(data=controller.start_training(game), path=str(request.url.path))


@router.post("/identify", response_model=ApiResponse[SymbolReading])
async def identify_symbols(
    request: Request,
    game: str | None = Query(None, description="Defaults to the selected game."),
    mode: GameMode | None = Query(None, description="Defaults to the selected mode."),
    controller: SymbolController = Depends(get_symbol_controller),
) -> ApiResponse[SymbolReading]:
    """Takes an OBS screenshot, cuts the reel grid into tiles and names each tile's symbol with the classifier."""
    data = await controller.identify(game, mode)
    return ApiResponse.ok(data=data, path=str(request.url.path))


@router.get("/readings", response_model=ApiResponse[list[SymbolReading]])
def list_symbol_readings(
    request: Request,
    limit: int = Query(1, ge=1, le=50),
    controller: SymbolController = Depends(get_symbol_controller),
) -> ApiResponse[list[SymbolReading]]:
    return ApiResponse.ok(data=controller.list_readings(limit), path=str(request.url.path))
