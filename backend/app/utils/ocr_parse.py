"""Turning what the OCR read on a game's meter into labelled amounts.

A meter shows three amounts, each with its label next to it: the balance (CASH, or CREDITS while the meter
counts credits), the WIN and the BET. Where a label sits differs between games (an amount over its label, or to
the right of it), and some meters print a small second figure by each label as well (the amount in credits).
The same crop also holds text that is not the meter's (the cyclic messages at its left edge, "88 CREDIT GAME
ACTIVE", the denomination button), so an amount is taken for what it sits next to, never for where it comes in
the text."""

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from app.schemas.ocr import AmountRead, CashMeterReading, CreditMeterReading
from app.utils.ocr_engine import TextBox

MeterMode = Literal["credits", "cash"]

# What the meter prints under each amount.
_LABELS = ("cash", "credits", "win", "bet")
# A label is read as the word it most resembles, at least this much: OCR drops and swaps letters.
_LABEL_SIMILARITY = 0.8
_LABEL_LENGTHS = range(3, 9)
# Digits a recognizer takes for the letters they look like: "W1N", "8ET".
_LOOKALIKES = str.maketrans("0158", "OISB")
# An amount read with less confidence than this (percent) is reported.
_LOW_CONFIDENCE = 80.0
# How far from its label an amount may sit, in text heights (the taller of the two boxes).
_MAX_GAP = 3.0
# Where an amount may be in relation to its label.
_PLACEMENTS = ("above", "below", "left", "right")
# An amount under this fraction of the tallest one by a label is the label's small second figure (the same
# amount in credits), not the amount.
_SECOND_FIGURE = 0.6

# A number with at most a few symbols around it: "$1,039.55", "99720", "USD 5.00".
_AMOUNT = re.compile(r"^[^\d\s.,]{0,3}\s*(?P<number>\d[\d\s.,]*)\s*[^\d\s.,]{0,3}$")


def clean_amount(text: str) -> float | None:
    """The number in an amount with the currency left out: "$1,039.55" -> 1039.55, "99720" -> 99720.0.
    Commas are thousands separators and the period is the decimal point, as the games print them. None when
    the text is not an amount."""
    match = _AMOUNT.match(text.strip())
    if match is None:
        return None
    try:
        return float(re.sub(r"[\s,]", "", match["number"]))
    except ValueError:  # "1.2.3"
        return None


@dataclass(frozen=True)
class MeterParse:
    """What was found on one meter crop. `shows` is the meter the labels say it is, None if neither was read."""

    shows: MeterMode | None
    balance: AmountRead
    win: AmountRead
    bet: AmountRead
    issues: list[str] = field(default_factory=list)

    def as_credit_meter(self) -> CreditMeterReading:
        return CreditMeterReading(credits=self.balance, win=self.win, bet=self.bet, issues=self.issues)

    def as_cash_meter(self) -> CashMeterReading:
        return CashMeterReading(cash=self.balance, win=self.win, bet=self.bet, issues=self.issues)


def parse_meter(boxes: list[TextBox], expected: MeterMode | None = None) -> MeterParse:
    """Finds the balance, win and bet of a meter crop from its text boxes. `expected` is the meter the crop
    is meant to be of; a crop that turns out to be the other one is reported, not read as this one.
    Without it the labels decide."""
    labels = _find_labels(boxes)
    # "W1N" is a label the recognizer put a digit in, and would pass for an amount.
    amounts = [box for box in boxes if clean_amount(box.text) is not None and _label_of(box.text) is None]
    issues: list[str] = []

    shows: MeterMode | None = next((m for m in ("cash", "credits") if m in labels), None)
    if expected in labels:
        shows = expected
    balance_label = expected or shows
    if balance_label is None:
        issues.append("Neither a CASH nor a CREDITS label was read, so the meter could not be identified.")
    elif balance_label not in labels:
        issues.append(
            f"The crop shows the {shows} meter, not the {balance_label} one."
            if shows
            else f"No {balance_label.upper()} label was read."
        )
        balance_label = None

    wanted = {name: labels[name] for name in (balance_label, "bet", "win") if name in labels}
    found = _assign_amounts(wanted, amounts)
    balance, bet, win = found.get(balance_label or ""), found.get("bet"), found.get("win")
    taken = {id(box) for box in found.values()}

    if "win" not in labels and balance_label is not None and "bet" in labels:
        # The WIN label sits on the crop's bottom edge, and is the first thing a tight crop loses.
        left, right = labels[balance_label].center_x, labels["bet"].center_x
        between = _without_second_figures(
            [box for box in amounts if id(box) not in taken and left < box.center_x < right]
        )
        if len(between) == 1:
            win = between[0]
            issues.append("The WIN label was not read: took the amount between the balance and the bet as the win.")

    balance_name = balance_label.upper() if balance_label else "Balance"
    if balance_label is not None and balance is None:
        issues.append(f"No amount was read next to the {balance_name} label.")
    if "bet" not in labels:
        issues.append("No BET label was read.")
    elif bet is None:
        issues.append("No amount was read next to the BET label.")
    for name, box in ((balance_name, balance), ("BET", bet), ("WIN", win)):
        if box is not None and box.score * 100 < _LOW_CONFIDENCE:
            issues.append(f"{name} was read with low confidence ({box.score * 100:.0f}%): {box.text!r}.")

    return MeterParse(shows=shows, balance=_amount_read(balance), win=_amount_read(win), bet=_amount_read(bet), issues=issues)


def _find_labels(boxes: list[TextBox]) -> dict[str, TextBox]:
    """The box of each label the meter prints, the surest reading of it where several look like one."""
    found: dict[str, TextBox] = {}
    for box in boxes:
        label = _label_of(box.text)
        if label is not None and (label not in found or box.score > found[label].score):
            found[label] = box
    return found


def _label_of(text: str) -> str | None:
    letters = re.sub(r"[^A-Z0-9]", "", text.upper()).translate(_LOOKALIKES).lower()
    if len(letters) not in _LABEL_LENGTHS:
        return None  # "Play 880 Credits" and "88 CREDIT GAME ACTIVE" are long; a label is a word
    similarity, word = max((SequenceMatcher(None, letters, label).ratio(), label) for label in _LABELS)
    return word if similarity >= _LABEL_SIMILARITY else None


@dataclass(frozen=True)
class _Candidate:
    box: TextBox
    placement: str  # where the box is in relation to the label
    distance: float  # in text heights


def _assign_amounts(labels: dict[str, TextBox], amounts: list[TextBox]) -> dict[str, TextBox]:
    """The amount of each label that has one. A meter places all its labels alike (each amount over its label,
    or right of it), and the amount of one label is also near the next: the BET label is closer to the WIN
    amount before it than to its own. So the placement that gives the most labels an amount is taken for all of
    them. A label still without one then looks in every placement, among the amounts left over."""
    options = {name: _candidates(label, amounts) for name, label in labels.items()}
    best: dict[str, _Candidate] = {}
    for placement in _PLACEMENTS:
        matched = _match({name: [c for c in found if c.placement == placement] for name, found in options.items()}, set())
        if _score(matched) > _score(best):
            best = matched
    best |= _match({name: found for name, found in options.items() if name not in best}, {id(c.box) for c in best.values()})
    return {name: candidate.box for name, candidate in best.items()}


def _score(matched: dict[str, _Candidate]) -> tuple[int, float]:
    """More labels with an amount is better; among those, amounts closer to their labels."""
    return len(matched), -sum(candidate.distance for candidate in matched.values())


def _match(options: dict[str, list[_Candidate]], taken: set[int]) -> dict[str, _Candidate]:
    """One amount for each label, the closest pairs first, so that no label takes the amount nearer another."""
    pairs = sorted(((name, c) for name, found in options.items() for c in found), key=lambda pair: pair[1].distance)
    matched: dict[str, _Candidate] = {}
    for name, candidate in pairs:
        if name not in matched and id(candidate.box) not in taken:
            matched[name] = candidate
            taken.add(id(candidate.box))
    return matched


def _candidates(label: TextBox, amounts: list[TextBox]) -> list[_Candidate]:
    """The amounts that may be `label`'s: in line with it, close to it, and not its small second figure."""
    near = []
    for box in amounts:
        placement = _placement(label, box)
        if placement is not None and (distance := _distance(label, box)) <= _MAX_GAP:
            near.append(_Candidate(box, placement, distance))
    main = {id(box) for box in _without_second_figures([c.box for c in near])}
    return [c for c in near if id(c.box) in main]


def _without_second_figures(boxes: list[TextBox]) -> list[TextBox]:
    tallest = max((box.height for box in boxes), default=0.0)
    return [box for box in boxes if box.height >= _SECOND_FIGURE * tallest]


def _placement(label: TextBox, box: TextBox) -> str | None:
    """Where `box` is in relation to `label` when it is in line with it: over or under it, or on its row."""
    if abs(box.center_x - label.center_x) <= max(box.width, label.width) / 2:
        return "above" if box.center_y < label.center_y else "below"
    if box.top <= label.center_y <= box.bottom or label.top <= box.center_y <= label.bottom:
        return "right" if box.center_x > label.center_x else "left"
    return None


def _distance(label: TextBox, box: TextBox) -> float:
    """The space between the two boxes, in text heights; 0 when they touch."""
    dx = max(box.left - label.right, label.left - box.right, 0.0)
    dy = max(box.top - label.bottom, label.top - box.bottom, 0.0)
    return math.hypot(dx, dy) / max(label.height, box.height)


def _amount_read(box: TextBox | None) -> AmountRead:
    if box is None:
        return AmountRead()
    return AmountRead(text=box.text, value=clean_amount(box.text), confidence=round(box.score * 100, 1))
