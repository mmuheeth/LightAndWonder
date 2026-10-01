import logging
import os
import re
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any, TypeVar, get_args
from xml.etree import ElementTree as ET

from app.core.exceptions import (
    AppException,
    BadRequestException,
    NotFoundException,
    ServiceUnavailableException,
)
from app.schemas.game_config import (
    CurrentPaytable,
    OrbTable,
    OrbValue,
    PayCombo,
    PayKind,
    PaylineComboRow,
    PaylineCombos,
    PayRules,
    PaytableConfig,
    PaytableList,
    PaytableSummary,
    ReelStripSet,
    SymbolInfo,
    SymbolKind,
    WildRule,
    WinGeometry,
)
from app.schemas.game_context import GameMode
from app.services.game_context_service import GameContextService
from app.utils import game_config as game_settings
from app.utils.gdk_files import (
    GameCfg,
    MathData,
    RawCombo,
    read_game_cfg,
    read_math,
    read_win_geometry,
)
from app.utils.log_watcher import LogState, LogWatcher

logger = logging.getLogger(__name__)

T = TypeVar("T")

# A paytable id becomes a folder name, and it comes from a log and a URL. Starting with a word
# character rules out "." and "..".
_PAYTABLE_ID = re.compile(r"^\w[\w.\-]*$")
_REEL_SET_LABELS = {"BG": "base game", "FG": "free games"}
_MAX_CACHED = 8


class GameConfigService:
    """Answers which paytable is in play (the one the game log reported last) and what is in it.
    A paytable is built once and cached until one of its files changes on disk."""

    def __init__(self, game_context: GameContextService, log_watcher: LogWatcher) -> None:
        self._game_context = game_context
        self._log = log_watcher
        self._cache: OrderedDict[tuple[str, str, str], tuple[tuple, PaytableConfig]] = OrderedDict()
        self._lock = Lock()

    # ------------------------------------------------------------------ public

    def current(self) -> CurrentPaytable:
        """The log's paytable. Only reads memory, so it is cheap enough to poll."""
        selection = self._game_context.get_context().context
        log_path = game_settings.active_log_path(self._game_context)
        # Right after a game or mode change the watcher may still be on the previous log.
        following = log_path is not None and self._log.path == log_path
        state = self._log.state if following else LogState()
        return CurrentPaytable(
            game=selection.game,
            mode=selection.mode,
            log_path=str(log_path) if log_path else None,
            log_unreadable=following and self._log.unreadable,
            paytable_id=state.paytable_id,
            denom=state.denom,
            supported_denoms=list(state.supported_denoms),
        )

    def list_paytables(self, game: str | None = None, mode: GameMode | None = None) -> PaytableList:
        game, mode, _, directory = self._locate(game, mode)
        try:
            with os.scandir(directory) as entries:
                names = sorted(entry.name for entry in entries if entry.is_dir())
        except FileNotFoundError:
            raise NotFoundException(f"Game config folder not found: {directory}") from None
        except OSError as exc:
            raise _unreachable(directory, exc) from exc
        return PaytableList(game=game, mode=mode, directory=str(directory), paytables=names)

    def get_paytable(
        self, paytable_id: str, game: str | None = None, mode: GameMode | None = None
    ) -> PaytableConfig:
        if not _PAYTABLE_ID.match(paytable_id):
            raise BadRequestException(f"Invalid paytable id '{paytable_id}'")
        game, mode, config, directory = self._locate(game, mode)
        folder = directory / paytable_id
        geometry_path = game_settings.game_path(game, mode.value, "win_geometry")

        try:
            math_stamp = _stamp(folder / "math.xml")
        except FileNotFoundError:
            raise NotFoundException(f"Paytable '{paytable_id}' not found in {directory}") from None
        except OSError as exc:
            raise _unreachable(folder, exc) from exc
        optional = [folder / "gameConfig.cfg", folder / "gameConfig.unlimited.cfg", geometry_path]
        stamp = (math_stamp, *(_stamp_or_none(path) for path in optional if path))

        key = (game, mode.value, paytable_id)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] == stamp:
                self._cache.move_to_end(key)
                return cached[1]

        built = self._build(game, mode, config, paytable_id, folder, geometry_path)
        with self._lock:
            self._cache[key] = (stamp, built)
            self._cache.move_to_end(key)
            while len(self._cache) > _MAX_CACHED:
                self._cache.popitem(last=False)
        return built

    # ---------------------------------------------------------------- internals

    def _locate(
        self, game: str | None, mode: GameMode | None
    ) -> tuple[str, GameMode, dict[str, Any], Path]:
        """The game and mode (the selected ones unless given), the game's config and its paytables folder.
        Callers that cache the result pass game and mode explicitly, as the selection can change meanwhile."""
        selection = self._game_context.get_context().context
        game, mode = game or selection.game, mode or selection.mode
        config = game_settings.load_game_config(game) if game else None
        if config is None:
            raise NotFoundException(f"Game '{game}' has no config")
        directory = game_settings.game_path(game, mode.value, "game_config")
        if directory is None:
            raise NotFoundException(f"'{game}' has no game_config folder for mode '{mode.value}'")
        return game, mode, config, directory

    def _build(
        self,
        game: str,
        mode: GameMode,
        config: dict[str, Any],
        paytable_id: str,
        folder: Path,
        geometry_path: Path | None,
    ) -> PaytableConfig:
        warnings: list[str] = []
        pay_kind = _pay_kind(game, config)
        try:
            math = read_math(folder / "math.xml", pay_kind)
        except FileNotFoundError:
            raise NotFoundException(f"Paytable '{paytable_id}' not found in {folder.parent}") from None
        except OSError as exc:
            raise _unreachable(folder, exc) from exc
        except ET.ParseError as exc:
            raise AppException(
                f"math.xml of '{paytable_id}' is not valid XML: {exc}", error_code="CONFIG_INVALID"
            ) from exc

        if math.other_pay_kind:
            warnings.append(
                f"{game} is configured with pay_kind '{pay_kind}', but the combos in math.xml are "
                f"{math.other_pay_kind} combos"
            )
        cfg = _optional(lambda: read_game_cfg(folder), "gameConfig.cfg", warnings)
        if cfg is None:
            warnings.append(f"No gameConfig.cfg in {folder}; using math.xml only")
        summary = _summary(cfg, math)

        symbols = _symbols(config, math)
        win_geometry = self._win_geometry(geometry_path, summary, math, warnings)
        combos = _payline_combos(math.payline_combos, [s.code for s in symbols], warnings)
        used_strips = {strip.id for strip in math.reel_strips}
        reel_sets = [
            ReelStripSet(
                id=reel_set.id,
                label=_reel_set_label(reel_set.id),
                visible_rows=reel_set.visible_rows,
                strip_ids=[i for i in reel_set.strip_ids if i in used_strips],
            )
            for reel_set in math.reel_sets
        ]

        return PaytableConfig(
            game=game,
            mode=mode,
            paytable_id=paytable_id,
            pay_kind=pay_kind,
            summary=summary,
            symbols=symbols,
            win_geometry=win_geometry,
            payline_combos=combos,
            pay_rules=_pay_rules(math),
            default_reel_strip_set=math.default_reel_set,
            reel_strip_sets=reel_sets,
            reel_strips=list(math.reel_strips),
            orb_tables=_orb_tables(config, summary.min_total_bet, math, warnings),
            warnings=warnings,
        )

    def _win_geometry(
        self,
        path: Path | None,
        summary: PaytableSummary,
        math: MathData,
        warnings: list[str],
    ) -> WinGeometry | None:
        if path is None:
            warnings.append("This game has no win_geometry file configured")
            return None
        sets = _optional(lambda: read_win_geometry(path), f"Win geometry ({path})", warnings)
        if not sets:
            return None
        ids = {payline_set.id for payline_set in sets}
        # The number of lines is what selects the set; math.xml names one as its default.
        active = next((i for i in (summary.lines, math.payline_set) if i in ids), None)
        default_reels = next((r for r in math.reel_sets if r.id == math.default_reel_set), None)
        return WinGeometry(
            file=str(path),
            reels=max((len(line) for s in sets for line in s.lines), default=0),
            rows=max(
                default_reels.visible_rows if default_reels else 0,
                max((row + 1 for s in sets for line in s.lines for row in line), default=0),
            ),
            active_set=active,
            sets=sets,
        )


# ------------------------------------------------------------------ presentation


def _pay_kind(game: str, config: dict[str, Any]) -> PayKind:
    """The game's `pay_kind`: every game says whether it pays along lines or by ways, and nothing is guessed."""
    kind = config.get("pay_kind")
    if kind not in get_args(PayKind):
        raise AppException(
            f"'{game}' needs a pay_kind of 'lines' or 'ways' in its config, not {kind!r}",
            error_code="CONFIG_INVALID",
        )
    return kind


def _summary(cfg: GameCfg | None, math: MathData) -> PaytableSummary:
    min_total_bet = (cfg.min_total_bet if cfg else None) or min(math.allowed_bets, default=None)
    return PaytableSummary(
        display_name=cfg.display_name if cfg else None,
        return_pct=_first(cfg.return_pct if cfg else None, math.return_pct),
        base_return_pct=_first(cfg.base_return_pct if cfg else None, math.base_return_pct),
        lines=_first(cfg.lines if cfg else None, math.payline_set),
        min_total_bet=min_total_bet,
        max_bets=list((cfg.max_bets if cfg else ()) or math.allowed_bets),
    )


def _symbols(config: dict[str, Any], math: MathData) -> list[SymbolInfo]:
    names: dict[str, str] = config.get("symbols", {})
    scatters = set(config.get("scatter_symbols", []))
    # Every code the tables refer to gets an entry, even if the symbol set does not list it.
    codes = dict.fromkeys(math.symbols)
    codes.update(dict.fromkeys(s for strip in math.reel_strips for s in strip.stops if s))
    codes.update(dict.fromkeys(s for combo in math.payline_combos for s in combo.symbols))

    def kind(code: str) -> SymbolKind:
        if code in math.wilds:
            return SymbolKind.WILD
        return SymbolKind.SCATTER if code in scatters else SymbolKind.REGULAR

    return [SymbolInfo(code=code, name=names.get(code, code), kind=kind(code)) for code in codes]


def _payline_combos(
    combos: tuple[RawCombo, ...], symbol_order: list[str], warnings: list[str]
) -> PaylineCombos | None:
    """Pays per symbol by run length, with symbols that pay identically put on one row."""
    payouts: dict[str, dict[int, float]] = {}
    skipped = 0
    for combo in combos:
        if len(set(combo.symbols)) != 1:  # a mixed run (e.g. wild + symbol) is not a single row
            skipped += 1
            continue
        payouts.setdefault(combo.symbols[0], {})[len(combo.symbols)] = combo.value
    if skipped:
        warnings.append(f"{skipped} payline combos mix symbols and are not shown")
    if not payouts:
        return None

    lengths = sorted({length for pays in payouts.values() for length in pays}, reverse=True)
    rank = {code: index for index, code in enumerate(symbol_order)}
    rows: dict[tuple[float | None, ...], list[str]] = {}
    for code in sorted(payouts, key=lambda c: rank.get(c, len(rank))):
        rows.setdefault(tuple(payouts[code].get(length) for length in lengths), []).append(code)

    best_first = sorted(rows, key=lambda pays: tuple(p or 0 for p in pays), reverse=True)
    return PaylineCombos(
        lengths=lengths,
        rows=[PaylineComboRow(symbols=rows[pays], payouts=list(pays)) for pays in best_first],
    )


def _pay_rules(math: MathData) -> PayRules | None:
    if not math.payline_combos:
        return None
    return PayRules(
        combos=[PayCombo(id=c.id, symbols=list(c.symbols), value=c.value) for c in math.payline_combos],
        wilds=[WildRule(code=code, substitutes=sorted(subs)) for code, subs in math.wilds.items()],
    )


def _reel_set_label(set_id: str) -> str | None:
    return next((_REEL_SET_LABELS[t] for t in re.split(r"\W|_", set_id) if t in _REEL_SET_LABELS), None)


def _orb_tables(
    config: dict[str, Any], bet: int | None, math: MathData, warnings: list[str]
) -> list[OrbTable]:
    if bet is None:
        return []
    tables = []
    for spec in config.get("orb_value_tables", []):
        name = spec["table"].format(bet=bet)
        rows = math.weighted_tables.get(name)
        if not rows:
            warnings.append(f"Orb table {name} not found")
            continue
        total = sum(weight for _, weight in rows)
        tables.append(
            OrbTable(
                title=spec["title"],
                table=name,
                bet=bet,
                total_weight=total,
                values=[
                    OrbValue(
                        # GDK weighted tables encode a jackpot level as a negative value.
                        label=f"JP{-value}" if value < 0 else str(value),
                        jackpot=value < 0,
                        weight=weight,
                        probability=weight / total if total else 0.0,
                    )
                    for value, weight in _credits_first(rows)
                ],
            )
        )
    return tables


def _credits_first(rows: tuple[tuple[int, int], ...]) -> list[tuple[int, int]]:
    return [r for r in rows if r[0] >= 0] + [r for r in rows if r[0] < 0]


# ------------------------------------------------------------------ helpers


def _optional(read: Callable[[], T], what: str, warnings: list[str]) -> T | None:
    """Runs a reader for a part of the config that the rest can do without."""
    try:
        return read()
    except (OSError, ET.ParseError, ValueError) as exc:
        logger.warning("Could not read %s: %s", what, exc)
        warnings.append(f"Could not read {what}: {exc}")
        return None


def _stamp(path: Path) -> tuple[int, int]:
    """Changes whenever the file does."""
    info = path.stat()
    return info.st_mtime_ns, info.st_size


def _stamp_or_none(path: Path) -> tuple[int, int] | None:
    try:
        return _stamp(path)
    except OSError:
        return None


def _first(*values: T | None) -> T | None:
    return next((value for value in values if value is not None), None)


def _unreachable(path: Path, exc: OSError) -> ServiceUnavailableException:
    return ServiceUnavailableException(f"Cannot read {path}: {exc}")
