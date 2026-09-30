from pathlib import Path

from app.schemas.cyclic import CyclicRound, CyclicStatus
from app.schemas.game_context import GameMode
from app.services.cyclic_service import CyclicMessageService


class CyclicController:
    def __init__(self, cyclic_service: CyclicMessageService) -> None:
        self.cyclic_service = cyclic_service

    async def start(self, game: str | None = None, mode: GameMode | None = None) -> CyclicStatus:
        return await self.cyclic_service.start(game, mode)

    async def stop(self) -> CyclicStatus:
        return await self.cyclic_service.stop()

    def status(self) -> CyclicStatus:
        return self.cyclic_service.status()

    def list_rounds(self, limit: int) -> list[CyclicRound]:
        return self.cyclic_service.list_rounds(limit)

    def image_path(self, round_id: str, filename: str) -> Path:
        return self.cyclic_service.image_path(round_id, filename)
