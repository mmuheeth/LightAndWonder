from app.schemas.game_context import GameMode
from app.schemas.symbol import SymbolModelStatus, SymbolReading
from app.services.symbol_service import SymbolService


class SymbolController:
    def __init__(self, symbol_service: SymbolService) -> None:
        self.symbol_service = symbol_service

    def model_status(self, game: str | None = None) -> SymbolModelStatus:
        return self.symbol_service.model_status(game)

    def start_training(self, game: str | None = None) -> SymbolModelStatus:
        return self.symbol_service.start_training(game)

    async def identify(self, game: str | None = None, mode: GameMode | None = None) -> SymbolReading:
        return await self.symbol_service.identify(game, mode)

    def list_readings(self, limit: int) -> list[SymbolReading]:
        return self.symbol_service.list_readings(limit)
