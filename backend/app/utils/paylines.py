"""Scoring a grid of symbols along the lines of a win geometry, against the combos of a paytable.
Pure functions: nothing here reads a file, a screen or the clock."""

from collections.abc import Mapping, Sequence

from app.schemas.game_config import PayCombo, PayRules
from app.schemas.payline import PaidCombo, PaylineCell, PaylineOutcome, PaylineStep

ANY = "ANY"  # pads a combo out to the reels: "any symbol may follow"

# Wild code -> the symbols it stands in for.
Wilds = Mapping[str, frozenset[str]]


def wild_map(rules: PayRules) -> dict[str, frozenset[str]]:
    return {wild.code: frozenset(wild.substitutes) for wild in rules.wilds}


def score_line(
    number: int,
    cells: Sequence[PaylineCell],
    rules: PayRules,
    wilds: Wilds,
    names: Mapping[str, str],
) -> PaylineOutcome:
    """A line pays the best combo that its symbols fill from the first reel on. A wild fills what it
    stands in for, and a combo of wilds is filled by wilds alone. A tile that was not read fills nothing;
    if it could have changed the outcome, the outcome is flagged `uncertain`."""
    codes = [cell.code for cell in cells]
    paid = _best_combo(codes, rules.combos, wilds, unread_fills=False)

    symbol = paid.symbols[0] if paid else _run_symbol(codes, wilds)
    matches = _run_length(codes, symbol, wilds) if symbol else 0
    pays = paid.value if paid else 0.0

    if any(code is None for code in codes):
        best_case = _best_combo(codes, rules.combos, wilds, unread_fills=True)
        uncertain = best_case is not None and best_case.value > pays
    else:
        uncertain = False

    paying = {combo.symbols[0] for combo in rules.combos if combo.symbols}
    return PaylineOutcome(
        number=number,
        cells=list(cells),
        steps=_steps(codes, matches, symbol, wilds),
        symbol=symbol,
        symbol_name=names.get(symbol) if symbol else None,
        matches=matches,
        combo=_paid_combo(paid, len(cells)) if paid else None,
        pays=pays,
        unpaid=paid is None and matches >= 2 and symbol in paying and not uncertain,
        uncertain=uncertain,
    )


def score_lines(
    lines: Sequence[Sequence[int]],
    grid: Mapping[tuple[int, int], PaylineCell],
    rules: PayRules,
    names: Mapping[str, str],
) -> list[PaylineOutcome]:
    """`lines[n][reel]` is the row line n crosses on that reel; `grid` is keyed by (row, reel)."""
    wilds = wild_map(rules)
    return [
        score_line(number, [grid[(row, reel)] for reel, row in enumerate(line)], rules, wilds, names)
        for number, line in enumerate(lines, start=1)
    ]


# ------------------------------------------------------------------------ matching


def _fills(symbol: str, code: str | None, wilds: Wilds, *, unread_fills: bool) -> bool:
    """Whether a tile showing `code` fills a place that wants `symbol`."""
    if code is None:
        return unread_fills
    return code == symbol or symbol in wilds.get(code, ())


def _best_combo(
    codes: Sequence[str | None], combos: Sequence[PayCombo], wilds: Wilds, *, unread_fills: bool
) -> PayCombo | None:
    """The best paying combo the codes fill; of equal pays, the one that asks for more symbols."""
    best: PayCombo | None = None
    for combo in combos:
        wanted = combo.symbols
        if not wanted or len(wanted) > len(codes):
            continue
        if not all(_fills(s, c, wilds, unread_fills=unread_fills) for s, c in zip(wanted, codes)):
            continue
        if best is None or (combo.value, len(wanted)) > (best.value, len(best.symbols)):
            best = combo
    return best


def _run_length(codes: Sequence[str | None], symbol: str, wilds: Wilds) -> int:
    """How many tiles from the left fill `symbol`."""
    length = 0
    for code in codes:
        if not _fills(symbol, code, wilds, unread_fills=False):
            break
        length += 1
    return length


def _run_symbol(codes: Sequence[str | None], wilds: Wilds) -> str | None:
    """The symbol the line's run is of when no combo paid it. A line led by wilds is a run of the
    symbol that follows them, or of the wild itself if that goes on for longer."""
    first = codes[0] if codes else None
    if first is None:
        return None
    if first not in wilds:
        return first
    follower = next((code for code in codes if code not in wilds), None)
    if follower is None:  # nothing but wilds, or an unread tile after them
        return first
    return follower if _run_length(codes, follower, wilds) >= _run_length(codes, first, wilds) else first


# ----------------------------------------------------------------------- presentation


def _steps(
    codes: Sequence[str | None], matches: int, symbol: str | None, wilds: Wilds
) -> list[PaylineStep]:
    # The run's first tile is always looked at, even when it is unread, so its step is counted.
    reached = max(matches, 1)
    steps = []
    for index in range(len(codes) - 1):
        left, right = codes[index], codes[index + 1]
        counted = index < reached
        if counted and symbol is not None and index < matches - 1:
            relation = "same" if left == right else "wild"
        elif left is None or right is None:
            relation = "unknown"
        else:
            relation = "same" if left == right else "different"
        steps.append(PaylineStep(relation=relation, counted=counted))
    return steps


def _paid_combo(combo: PayCombo, reels: int) -> PaidCombo:
    padding = [ANY] * (reels - len(combo.symbols))
    return PaidCombo(id=combo.id, pattern=[*combo.symbols, *padding], value=combo.value)
