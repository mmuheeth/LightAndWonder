from app.schemas.game_config import CurrentPaytable, PaytableConfig, PaytableList
from app.schemas.game_context import GameMode
from app.services.game_config_service import GameConfigService


class GameConfigController:
    def __init__(self, game_config_service: GameConfigService) -> None:
        self.game_config_service = game_config_service

    def current(self) -> CurrentPaytable:
        return self.game_config_service.current()

    def list_paytables(self, game: str | None, mode: GameMode | None) -> PaytableList:
        return self.game_config_service.list_paytables(game, mode)

    def get_paytable(
        self, paytable_id: str, game: str | None, mode: GameMode | None
    ) -> PaytableConfig:
        return self.game_config_service.get_paytable(paytable_id, game, mode)
