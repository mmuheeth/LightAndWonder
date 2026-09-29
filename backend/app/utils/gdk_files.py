"""Readers for the GDK config files of a paytable: `math.xml`, `gameConfig.cfg` and `winGeometry.xml`.
They return what the files say and nothing more; deciding what to show is up to the caller."""

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from app.schemas.game_config import PaylineSet, ReelStrip

_ANY_SYMBOL = "ANY"  # padding in a payline combo: "any symbol may follow"


@dataclass(frozen=True)
class GameCfg:
    """The `gameConfig.cfg` of a paytable (LATAM ones only ship `gameConfig.unlimited.cfg`)."""

    display_name: str | None
    return_pct: float | None
    base_return_pct: float | None
    lines: int | None
    min_total_bet: int | None
    max_bets: tuple[int, ...]


@dataclass(frozen=True)
class RawReelSet:
    id: str
    strip_ids: tuple[str, ...]
    visible_rows: int


@dataclass(frozen=True)
class RawCombo:
    """A payline combo: `symbols` without the ANY padding, so its length is the run length."""

    symbols: tuple[str, ...]
    value: float


@dataclass(frozen=True)
class MathData:
    return_pct: float | None
    base_return_pct: float | None
    default_reel_set: str | None
    payline_set: int | None
    symbols: tuple[str, ...]  # in symbol set order
    wilds: frozenset[str]
    reel_strips: tuple[ReelStrip, ...]
    reel_sets: tuple[RawReelSet, ...]
    payline_combos: tuple[RawCombo, ...]
    allowed_bets: tuple[int, ...]
    weighted_tables: dict[str, tuple[tuple[int, int], ...]]  # name -> ((value, weight), ...)


def read_game_cfg(folder: Path) -> GameCfg | None:
    """None if the folder has neither config file."""
    for name in ("gameConfig.cfg", "gameConfig.unlimited.cfg"):
        try:
            root = _parse(folder / name)
        except FileNotFoundError:
            continue
        max_bets = {
            int(bet)
            for config in root.iterfind("DenomConfig")
            for bet in (_text(config, "SpecificMaxBets") or "").split()
            if bet.isdigit()
        }
        return GameCfg(
            display_name=_text(root, "DisplayGameId"),
            return_pct=_number(_text(root, "GamePct")),
            base_return_pct=_number(_text(root, "GameBasePct")),
            lines=_integer(_text(root, "NumberOfLines")),
            min_total_bet=_integer(_text(root, "MinTotalBet")),
            max_bets=tuple(sorted(max_bets)),
        )
    return None


def read_math(path: Path) -> MathData:
    root = _parse(path)
    default = root.find("DefaultConfiguration")
    symbol_set = root.find("SymbolSetList/SymbolSet")

    return MathData(
        return_pct=_number(_text(root, "GamePct")),
        base_return_pct=_number(_text(root, "GameBasePct")),
        default_reel_set=_text(default, "ReelStripSetID"),
        payline_set=_integer(_text(default, "PaylineSetID")),
        symbols=tuple(_texts(symbol_set, "SymbolList/Symbol")),
        wilds=frozenset(_texts(symbol_set, "WildSymbolList/WildSymbol/Identifier")),
        reel_strips=tuple(_reel_strips(root)),
        reel_sets=tuple(_reel_sets(root)),
        payline_combos=tuple(_payline_combos(root, _text(default, "PaytableID"))),
        allowed_bets=tuple(
            int(bet) for bet in _value_table(root, "AllowedBetsTbl") if bet.isdigit()
        ),
        weighted_tables=_weighted_tables(root),
    )


def read_win_geometry(path: Path) -> list[PaylineSet]:
    """Every payline set in the file; the set id is the number of lines it holds."""
    sets = []
    for payline_set in _parse(path).iter("PaylineSet"):
        lines = []
        for payline in payline_set.iterfind("Payline"):
            elements = sorted(
                payline.iterfind("PaylineElement"), key=lambda element: int(element.get("reelIndex", 0))
            )
            lines.append([int(element.get("position", 0)) for element in elements])
        sets.append(PaylineSet(id=int(payline_set.get("paylineSetID", 0)), lines=lines))
    return sets


# ------------------------------------------------------------------ math.xml sections


def _reel_strips(root: ET.Element) -> list[ReelStrip]:
    strips = []
    for strip in root.iterfind("ReelStripList/ReelStrip"):
        stops, weights = [], []
        for element in strip.iterfind("WeightedElementList/WeightedElement"):
            stops.append(_text(element, "StringValue") or "")
            weights.append(_integer(_text(element, "Weight")) or 0)
        strips.append(ReelStrip(id=_text(strip, "Identifier") or "", stops=stops, weights=weights))
    return strips


def _reel_sets(root: ET.Element) -> list[RawReelSet]:
    sets = []
    for reel_set in root.iterfind("ReelStripSetList/ReelStripSet"):
        heights = [
            _integer(height.text) or 0
            for height in reel_set.iterfind("ReelStripVisSymbols/ReelStripVisSymbolsHeight")
        ]
        sets.append(
            RawReelSet(
                id=_text(reel_set, "Identifier") or "",
                strip_ids=tuple(_texts(reel_set, "ReelStripIDList/ReelStripID")),
                visible_rows=max(heights, default=0),
            )
        )
    return sets


def _payline_combos(root: ET.Element, paytable_id: str | None) -> list[RawCombo]:
    """The combos of the first payline combo set that the default paytable uses."""
    used: set[str] = set()
    for paytable in root.iterfind("PaytableList/Paytable"):
        if _text(paytable, "Identifier") == paytable_id:
            used = set(_texts(paytable, "ComboSetIDList/ComboSet"))
    for combo_set in root.iterfind("ComboSetList/PaylineComboSet"):
        if _text(combo_set, "Identifier") not in used:
            continue
        combos = []
        for combo in combo_set.iterfind("PaylineComboList/PaylineCombo"):
            symbols = _texts(combo, "SymbolList/Symbol")
            value = _number(_text(combo, "Value"))
            if value is not None:
                combos.append(RawCombo(tuple(s for s in symbols if s != _ANY_SYMBOL), value))
        return combos
    return []


def _value_table(root: ET.Element, name: str) -> list[str]:
    for table in root.iterfind("BonusInfo/ValueTableList/ValueTable"):
        if _text(table, "Identifier") == name:
            return _texts(table, "ValueList/Value")
    return []


def _weighted_tables(root: ET.Element) -> dict[str, tuple[tuple[int, int], ...]]:
    tables = {}
    for table in root.iterfind("BonusInfo/WeightedTableList/WeightedTable"):
        name = _text(table, "Identifier")
        if name is None:
            continue
        rows = []
        for element in table.iterfind("WeightedElementList/WeightedElement"):
            value, weight = _integer(_text(element, "Value")), _integer(_text(element, "Weight"))
            if value is not None and weight is not None:
                rows.append((value, weight))
        tables[name] = tuple(rows)
    return tables


# ------------------------------------------------------------------ element helpers


def _parse(path: Path) -> ET.Element:
    """The root of `path` with XML namespaces removed, so every path can be written plainly."""
    root = ET.parse(path).getroot()
    for element in root.iter():
        element.tag = element.tag.rpartition("}")[2]
    return root


def _text(parent: ET.Element | None, path: str) -> str | None:
    element = parent.find(path) if parent is not None else None
    text = element.text.strip() if element is not None and element.text else ""
    return text or None


def _texts(parent: ET.Element | None, path: str) -> list[str]:
    if parent is None:
        return []
    return [element.text.strip() for element in parent.iterfind(path) if element.text]


def _number(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def _integer(text: str | None) -> int | None:
    number = _number(text)
    return int(number) if number is not None and number.is_integer() else None
