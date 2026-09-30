"""The dictionaries that map friendly names ("TakeWinButton", "CreditMeter") to Unity objects.

The game's client cannot resolve a single named control without them, and it needs a complete set:
handed only a game's own few entries, `InitializeGameClient` fails with "The given key was not present
in the dictionary". So a game only lists what differs from the common base of its game type, in
`app/games/_common/gaf/<game_type>/`, and the two are deep-merged.

There are two dictionaries, one per initialiser. Each is a folder of files copied from the
GameCommon object-query files of the AGTF workspace; refresh them by copying the new files over.
Knows nothing about NRobot."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COMMON_DIR = Path(__file__).resolve().parents[1] / "games" / "_common" / "gaf"

_GENERAL = "general"  # -> InitializeGameClient
_GENERIC = "generic"  # -> InitializeGenericGameClient


class ObjectQueryError(Exception):
    """A dictionary could not be built; the message says which file and why."""


@dataclass(frozen=True)
class ObjectQueries:
    general: dict[str, Any]
    generic: dict[str, Any]


def load_object_queries(
    game_type: str, override_file: Path | None, common_dir: Path = COMMON_DIR
) -> ObjectQueries:
    """The common base of `game_type` with the game's own `override_file` merged over it.

    The override is one flat file. Each of its top-level entries goes to the dictionary whose base
    already has that entry; a new one is a named object, which is the generic dictionary's kind."""
    if not game_type.isidentifier():  # the name becomes part of a path
        raise ObjectQueryError(f"'{game_type}' is not a valid game type")
    base = common_dir / game_type
    general = _merge_folder(base / _GENERAL)
    generic = _merge_folder(base / _GENERIC)

    overrides = _read(override_file) if override_file is not None else {}
    to_general = {key: value for key, value in overrides.items() if key in general}
    to_generic = {key: value for key, value in overrides.items() if key not in general}
    return ObjectQueries(
        general=_deep_merge(general, to_general), generic=_deep_merge(generic, to_generic)
    )


def _merge_folder(folder: Path) -> dict[str, Any]:
    try:
        files = sorted(folder.glob("*.json"))
    except OSError as exc:
        raise ObjectQueryError(f"Cannot read {folder}: {exc}") from exc
    if not files:
        raise ObjectQueryError(f"No object query files in {folder}")
    merged: dict[str, Any] = {}
    for file in files:
        merged = _deep_merge(merged, _read(file))
    return merged


def _read(path: Path) -> dict[str, Any]:
    """An empty file counts as an empty dictionary, so a game can have its file before it has entries."""
    try:
        text = path.read_text(encoding="utf-8-sig")  # the files carry a BOM
    except OSError as exc:
        raise ObjectQueryError(f"Cannot read {path}: {exc}") from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ObjectQueryError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ObjectQueryError(f"{path} must hold a JSON object, not {type(data).__name__}")
    return data


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """`over` wins, but objects merge rather than replace, so a game can change one entry of a section."""
    merged = dict(base)
    for key, value in over.items():
        current = merged.get(key)
        merged[key] = (
            _deep_merge(current, value) if isinstance(current, dict) and isinstance(value, dict) else value
        )
    return merged
