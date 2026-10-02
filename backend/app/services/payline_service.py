import asyncio
import logging
from typing import Literal

from app.core.exceptions import AppException
from app.schemas.game_config import PaytableConfig
from app.schemas.game_context import GameMode
from app.schemas.payline import PaylineBet, PaylineCell, PaylineOutcome, PaylineResult, WayOutcome
from app.schemas.symbol import SymbolReading
from app.services.game_config_service import GameConfigService
from app.services.symbol_service import SymbolService
from app.utils import paylines

logger = logging.getLogger(__name__)


class PaylineService:
    """Finds which paylines of a result screenshot pay, and how much. The symbols on the reels come from
    the symbol reading; the lines (win geometry) and what a run pays (payline combos) from the game's
    paytable, which is the one the game log reported last unless one is asked for. A paytable that pays
    by ways has no lines: its symbols are scored over every route across the reels instead. What a combo pays
    is for one credit bet on the line; the credits that win are that times the credits bet on each line,
    which is the log's current bet over the current denom."""

    def __init__(
        self, *, symbols: SymbolService, game_config: GameConfigService, min_confidence: float
    ) -> None:
        self._symbols = symbols
        self._game_config = game_config
        self._min_confidence = min_confidence

    async def evaluate(
        self,
        game: str | None = None,
        mode: GameMode | None = None,
        *,
        min_confidence: float | None = None,
        paytable: str | None = None,
    ) -> PaylineResult:
        """Takes a screenshot, reads the symbols on it (the Symbol tab's identify) and scores the lines.
        Game and mode default to the selected ones."""
        reading = await self._symbols.identify(game, mode)
        return await asyncio.to_thread(self.score, reading, min_confidence=min_confidence, paytable=paytable)

    def score_reading(
        self, reading_id: str, *, min_confidence: float | None = None, paytable: str | None = None
    ) -> PaylineResult:
        """Scores a reading that was made before, e.g. to see what another confidence floor makes of it."""
        return self.score(self._symbols.get_reading(reading_id), min_confidence=min_confidence, paytable=paytable)

    def score(
        self, reading: SymbolReading, *, min_confidence: float | None = None, paytable: str | None = None
    ) -> PaylineResult:
        floor = self._min_confidence if min_confidence is None else min_confidence
        paytable_id, source = self._paytable(reading, paytable)
        config = self._game_config.get_paytable(paytable_id, reading.game, reading.mode)

        rules = config.pay_rules
        by_ways = config.pay_kind == "ways"
        lines = [] if by_ways else self._lines(reading, config)
        if rules is None:
            raise AppException(
                f"Paytable '{paytable_id}' has no {'ways' if by_ways else 'payline'} combos, so nothing can be paid.",
                status_code=422,
                error_code="PAYLINES_NO_COMBOS",
            )
        ways_in_grid = reading.rows**reading.columns
        if by_ways and config.summary.lines not in (None, ways_in_grid):
            raise AppException(
                f"Paytable '{paytable_id}' pays {config.summary.lines} ways, but the {reading.rows} by "
                f"{reading.columns} grid that was read holds {ways_in_grid}.",
                status_code=422,
                error_code="PAYLINES_GRID_MISMATCH",
            )

        bet = self._bet(reading)
        credits_per_unit = bet.credits_per_unit if bet else 1.0
        names = {symbol.code: symbol.name for symbol in config.symbols}
        tiles = [
            PaylineCell(
                row=tile.row,
                column=tile.column,
                code=tile.code if tile.confidence >= floor else None,
                guess=tile.code,
                name=tile.name,
                confidence=tile.confidence,
            )
            for tile in reading.tiles
        ]
        grid = {(t.row, t.column): t for t in tiles}
        line_outcomes: list[PaylineOutcome] = []
        way_outcomes: list[WayOutcome] = []
        if by_ways:
            way_outcomes = paylines.score_ways(
                grid, reading.rows, reading.columns, rules, names, credits_per_unit=credits_per_unit
            )
        else:
            line_outcomes = paylines.score_lines(lines, grid, rules, names, credits_per_unit=credits_per_unit)
        scored = [*line_outcomes, *way_outcomes]
        total = round(sum(outcome.credits for outcome in scored), 6)

        logger.info(
            "Scored %d %s of %s with %s: %s credits over %d paying",
            len(scored), "ways" if by_ways else "lines", reading.id, paytable_id, total,
            sum(1 for o in scored if o.pays > 0),
        )
        return PaylineResult(
            reading_id=reading.id,
            created_at=reading.created_at,
            game=reading.game,
            mode=reading.mode,
            paytable_id=paytable_id,
            paytable_source=source,
            kind="ways" if by_ways else "lines",
            line_set=ways_in_grid if by_ways else len(lines),
            min_confidence=floor,
            rows=reading.rows,
            columns=reading.columns,
            reels=reading.reels,
            tiles=tiles,
            lines=line_outcomes,
            ways=way_outcomes,
            bet=bet,
            total_credits=total,
            complete=not any(outcome.uncertain for outcome in scored),
        )

    # ---------------------------------------------------------------- internals

    def _paytable(
        self, reading: SymbolReading, requested: str | None
    ) -> tuple[str, Literal["log", "request"]]:
        if requested:
            return requested, "request"
        current = self._game_config.current()
        # The log watcher may still be on the previous game's log for a moment after the selection moves.
        if current.paytable_id and (current.game, current.mode) == (reading.game, reading.mode):
            return current.paytable_id, "log"
        raise AppException(
            f"The game log has not reported a paytable for {reading.game} · {reading.mode.value} yet, "
            "so its paylines cannot be scored; play a spin, or name the paytable.",
            status_code=409,
            error_code="PAYTABLE_UNKNOWN",
        )

    def _bet(self, reading: SymbolReading) -> PaylineBet | None:
        """The bet and denom the game log reports now, if they are the reading's game's and both are known."""
        current = self._game_config.current()
        if (current.game, current.mode) != (reading.game, reading.mode):
            return None
        if not current.denom or current.bet is None:
            return None
        return PaylineBet(
            denom=current.denom,
            bets_per_unit=current.bet.bets_per_unit,
            credits_per_unit=round(current.bet.bets_per_unit / current.denom, 6),
            total_bet=round(current.bet.total_bet / current.denom, 6),
        )

    @staticmethod
    def _lines(reading: SymbolReading, config: PaytableConfig) -> list[list[int]]:
        """The lines of the payline set this paytable plays, checked against the grid that was read."""
        geometry = config.win_geometry
        if geometry is None:
            raise AppException(
                f"'{config.game}' has no win geometry for paytable '{config.paytable_id}', so it has no paylines.",
                status_code=422,
                error_code="PAYLINES_NO_GEOMETRY",
            )
        line_set = next((s for s in geometry.sets if s.id == geometry.active_set), None)
        if line_set is None:
            raise AppException(
                f"{geometry.file} has no payline set for the {config.summary.lines or 'configured'} lines "
                f"of paytable '{config.paytable_id}'.",
                status_code=422,
                error_code="PAYLINES_NO_LINE_SET",
            )
        if any(
            len(line) != reading.columns or any(not 0 <= row < reading.rows for row in line)
            for line in line_set.lines
        ):
            raise AppException(
                f"The {line_set.id}-line set does not fit the {reading.rows} by {reading.columns} grid that was read.",
                status_code=422,
                error_code="PAYLINES_GRID_MISMATCH",
            )
        return line_set.lines
