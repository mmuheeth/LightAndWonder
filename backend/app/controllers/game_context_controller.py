from app.schemas.game_context import GameContextResponse, GameContextUpdate
from app.services.game_context_service import GameContextService


class GameContextController:
    def __init__(self, game_context_service: GameContextService) -> None:
        self.game_context_service = game_context_service

    def get(self) -> GameContextResponse:
        return self.game_context_service.get_context()

    def update(self, update: GameContextUpdate) -> GameContextResponse:
        return self.game_context_service.update_context(update)
