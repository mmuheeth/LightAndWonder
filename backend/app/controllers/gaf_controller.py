from app.schemas.gaf import GafActionInfo, GafActionRequest, GafActionResult, GafStatus
from app.schemas.game_context import GameMode
from app.services.gaf_service import GafService


class GafController:
    def __init__(self, gaf_service: GafService) -> None:
        self.gaf_service = gaf_service

    async def status(self, game: str | None = None, mode: GameMode | None = None) -> GafStatus:
        return await self.gaf_service.status(game, mode)

    async def connect(self, game: str | None = None, mode: GameMode | None = None) -> GafStatus:
        return await self.gaf_service.connect(game, mode)

    async def disconnect(self, game: str | None = None, mode: GameMode | None = None) -> GafStatus:
        return await self.gaf_service.disconnect(game, mode)

    def list_actions(self, game: str | None = None, mode: GameMode | None = None) -> list[GafActionInfo]:
        return self.gaf_service.list_actions(game, mode)

    async def run_action(
        self,
        action_id: str,
        request: GafActionRequest | None = None,
        game: str | None = None,
        mode: GameMode | None = None,
    ) -> GafActionResult:
        params = request.params if request else {}
        return await self.gaf_service.run_action(action_id, params, game, mode)
