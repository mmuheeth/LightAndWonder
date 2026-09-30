"""Turning what the OCR read on a game's meter into labelled amounts.

The meter is three boxes side by side, each an amount with its label underneath: the balance (CASH, or
CREDITS while the meter counts credits), the WIN and the BET. The same crop also holds text that is not
the meter's (the cyclic messages at its left edge, "88 CREDIT GAME ACTIVE", the denomination button), so
an amount is taken for what it sits above, never for where it comes in the text."""

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
# How far above its label (in label heights) an amount may sit.
_MAX_GAP = 3.0

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
    amounts = [box for box in boxes if clean_amount(box.text) is not None]
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

    taken: set[int] = set()
    balance = _amount_above(labels.get(balance_label or ""), amounts, taken)
    bet = _amount_above(labels.get("bet"), amounts, taken)
    win = _amount_above(labels.get("win"), amounts, taken)

    if "win" not in labels and balance_label is not None and "bet" in labels:
        # The WIN label sits on the crop's bottom edge, and is the first thing a tight crop loses.
        left, right = labels[balance_label].center_x, labels["bet"].center_x
        between = [box for box in amounts if id(box) not in taken and left < box.center_x < right]
        if len(between) == 1:
            win = between[0]
            issues.append("The WIN label was not read: took the amount between the balance and the bet as the win.")

    balance_name = balance_label.upper() if balance_label else "Balance"
    if balance_label is not None and balance is None:
        issues.append(f"No amount was read above the {balance_name} label.")
    if "bet" not in labels:
        issues.append("No BET label was read.")
    elif bet is None:
        issues.append("No amount was read above the BET label.")
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


def _amount_above(label: TextBox | None, amounts: list[TextBox], taken: set[int]) -> TextBox | None:
    """The amount printed above `label`: over it, not over another label, and closest to it."""
    if label is None:
        return None
    above = [
        box
        for box in amounts
        if id(box) not in taken
        and box.center_y < label.center_y
        and abs(box.center_x - label.center_x) <= max(box.width, label.width) / 2
        and label.top - box.bottom <= _MAX_GAP * label.height
    ]
    if not above:
        return None
    nearest = min(above, key=lambda box: abs(label.top - box.bottom))
    taken.add(id(nearest))
    return nearest


def _amount_read(box: TextBox | None) -> AmountRead:
    if box is None:
        return AmountRead()
    return AmountRead(text=box.text, value=clean_amount(box.text), confidence=round(box.score * 100, 1))
