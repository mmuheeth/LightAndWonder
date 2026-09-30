from pathlib import Path

from app.schemas.game_context import GameMode
from app.schemas.ocr import OcrEngineStatus, OcrRecord
from app.services.ocr_service import OcrService


class OcrController:
    def __init__(self, ocr_service: OcrService) -> None:
        self.ocr_service = ocr_service

    async def extract(self, game: str | None = None, mode: GameMode | None = None) -> OcrRecord:
        return await self.ocr_service.extract(game, mode)

    def warm_up(self) -> OcrEngineStatus:
        return self.ocr_service.warm_up()

    async def read(self, record_id: str) -> OcrRecord:
        return await self.ocr_service.read(record_id)

    def list_records(self, limit: int) -> list[OcrRecord]:
        return self.ocr_service.list_records(limit)

    def image_path(self, record_id: str, filename: str) -> Path:
        return self.ocr_service.image_path(record_id, filename)
