from pathlib import Path

from app.schemas.game_context import GameMode
from app.schemas.roi import RoiRecord
from app.services.roi_service import RoiService


class RoiController:
    def __init__(self, roi_service: RoiService) -> None:
        self.roi_service = roi_service

    async def extract(self, game: str | None = None, mode: GameMode | None = None) -> RoiRecord:
        return await self.roi_service.extract(game, mode)

    def list_records(self, limit: int) -> list[RoiRecord]:
        return self.roi_service.list_records(limit)

    def image_path(self, record_id: str, filename: str) -> Path:
        return self.roi_service.image_path(record_id, filename)
