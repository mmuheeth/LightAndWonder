from app.schemas.game_context import GameMode
from app.schemas.payline import PaylineResult
from app.services.payline_service import PaylineService


class PaylineController:
    def __init__(self, payline_service: PaylineService) -> None:
        self.payline_service = payline_service

    async def evaluate(
        self,
        game: str | None = None,
        mode: GameMode | None = None,
        min_confidence: float | None = None,
        paytable: str | None = None,
    ) -> PaylineResult:
        return await self.payline_service.evaluate(
            game, mode, min_confidence=min_confidence, paytable=paytable
        )

    def score_reading(
        self, reading_id: str, min_confidence: float | None = None, paytable: str | None = None
    ) -> PaylineResult:
        return self.payline_service.score_reading(
            reading_id, min_confidence=min_confidence, paytable=paytable
        )
