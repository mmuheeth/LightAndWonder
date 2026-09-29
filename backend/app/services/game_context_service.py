import json
import logging
import os
from pathlib import Path
from threading import Lock

from app.core.exceptions import BadRequestException
from app.schemas.game_context import (
    GameContext,
    GameContextOptions,
    GameContextResponse,
    GameContextUpdate,
    GameMode,
)

logger = logging.getLogger(__name__)

GAMES_DIR = Path(__file__).resolve().parent.parent / "games"


class GameContextService:
    """Holds the active game/mode selection, saved to `state_file` and reloaded on startup.
    It only changes when explicitly updated (e.g. from the UI dropdowns), never on restart."""

    def __init__(self, state_file: Path, games_dir: Path = GAMES_DIR) -> None:
        self._state_file = state_file
        self._games_dir = games_dir
        self._lock = Lock()
        self.current_game: str | None = None
        self.current_mode: GameMode = GameMode.SIMULATOR
        self._load()

    def list_games(self) -> list[str]:
        if not self._games_dir.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self._games_dir.iterdir()
            if entry.is_dir() and not entry.name.startswith(("_", "."))
        )

    def get_context(self) -> GameContextResponse:
        with self._lock:
            return self._build_response(self.list_games())

    def update_context(self, update: GameContextUpdate) -> GameContextResponse:
        games = self.list_games()
        if update.game is not None and update.game not in games:
            raise BadRequestException(
                f"Unknown game '{update.game}'",
                details={"available_games": games},
            )
        with self._lock:
            # Pin the effective game too, so an implicit default doesn't drift
            # if game folders are added later.
            self.current_game = update.game or self._effective_game(games)
            if update.mode is not None:
                self.current_mode = update.mode
            self._save()
            return self._build_response(games)

    def _build_response(self, games: list[str]) -> GameContextResponse:
        # Only when nothing valid was ever chosen (first run, or the chosen game
        # folder was deleted) do we fall back to the first game. This is not saved,
        # so a game that reappears is picked up again.
        game = self._effective_game(games)
        return GameContextResponse(
            context=GameContext(game=game or "", mode=self.current_mode),
            options=GameContextOptions(games=games, modes=list(GameMode)),
        )

    def _effective_game(self, games: list[str]) -> str | None:
        if self.current_game in games:
            return self.current_game
        return games[0] if games else None

    def _load(self) -> None:
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            game = data.get("game")
            self.current_game = game if isinstance(game, str) else None
            self.current_mode = GameMode(data.get("mode", GameMode.SIMULATOR))
        except FileNotFoundError:
            return
        except (OSError, ValueError, AttributeError):
            logger.warning("Ignoring unreadable game context file: %s", self._state_file)

    def _save(self) -> None:
        payload = {"game": self.current_game, "mode": self.current_mode.value}
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self._state_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp_file, self._state_file)  # atomic: never leaves a half-written file
