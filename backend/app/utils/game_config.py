import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.game_context_service import GameContextService


def load_game_config(game: str) -> dict[str, Any] | None:
    """The config dict of `app/games/<game>/<game>.py`, or None if the game has none.
    Its variable is named per game (e.g. `fortune_ox`), so it is found by its `"name"` entry."""
    if not game.isidentifier():  # the name becomes part of an import path
        return None
    try:
        module = importlib.import_module(f"app.games.{game}.{game}")
    except ImportError:
        return None
    return next(
        (
            value
            for value in vars(module).values()
            if isinstance(value, dict) and value.get("name") == game
        ),
        None,
    )


def game_path(game: str, mode: str, key: str) -> Path | None:
    """A path setting of `game` in `mode` ("simulator" / "egm"), e.g. `"logs"`, `"game_config"`
    or `"win_geometry"`; None if the game does not configure it."""
    section = (load_game_config(game) or {}).get(mode)
    value = section.get(key) if isinstance(section, dict) else None
    return Path(value) if value else None


def game_log_path(game: str, mode: str) -> Path | None:
    """The `"logs"` path of `game` in `mode`, or None if not configured."""
    return game_path(game, mode, "logs")


def active_log_path(context: "GameContextService") -> Path | None:
    """The log file of the selected game and mode. Runs every watcher pass, so it reads the selection
    directly and only calls `get_context()` (which scans the games folder) when no game is chosen."""
    game = context.current_game
    path = game_log_path(game, context.current_mode.value) if game else None
    if path is None:
        current = context.get_context().context
        path = game_log_path(current.game, current.mode.value)
    return path
