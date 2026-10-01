"""The meter parser and the currency cleanup, on the boxes PaddleOCR really produced for the game's crops."""

import pytest

from app.utils.ocr_parse import clean_amount, parse_meter
from tests.ocr_helpers import CASH_NO_WIN, CASH_WITH_WIN, CREDITS_NO_WIN, HUFF_CASH_WITH_WIN, box


# ------------------------------------------------------------------------- currency cleanup


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("$1,039.55", 1039.55),
        ("$20,594.00", 20594.0),
        ("$0.88", 0.88),
        ("$1.30", 1.3),
        ("99720", 99720.0),
        ("88", 88.0),
        ("1,039", 1039.0),  # credits with a thousands separator
        ("1,039,500", 1039500.0),
        ("£ 1 039.55", 1039.55),  # the OCR may put spaces in
        ("USD 5.00", 5.0),
        ("  $7.25  ", 7.25),
        ("$5.", 5.0),
    ],
)
def test_clean_amount_drops_the_currency_and_keeps_the_value(text: str, value: float) -> None:
    assert clean_amount(text) == value


@pytest.mark.parametrize(
    "text", ["", "$", "CASH", "WIN", "Game Pays 0", "88 CREDIT GAMEACTIVE", "Line 14 Pays 10", "1.2.3"]
)
def test_clean_amount_is_none_for_text_that_is_not_an_amount(text: str) -> None:
    assert clean_amount(text) is None


# ------------------------------------------------------------------------------ the meters


def test_a_credit_meter_with_no_win_reads_credits_and_bet_and_an_empty_win() -> None:
    parsed = parse_meter(CREDITS_NO_WIN, "credits")

    assert parsed.shows == "credits"
    assert (parsed.balance.text, parsed.balance.value, parsed.balance.confidence) == ("99720", 99720.0, 100.0)
    assert (parsed.bet.text, parsed.bet.value) == ("88", 88.0)
    assert parsed.win.model_dump() == {"text": None, "value": None, "confidence": None}
    assert parsed.issues == []


def test_a_cash_meter_with_a_win_reads_all_three_without_the_currency() -> None:
    parsed = parse_meter(CASH_WITH_WIN, "cash")

    assert parsed.shows == "cash"
    assert (parsed.balance.text, parsed.balance.value) == ("$1,039.55", 1039.55)
    assert (parsed.win.text, parsed.win.value) == ("$1.30", 1.3)
    assert (parsed.bet.text, parsed.bet.value) == ("$0.88", 0.88)
    assert parsed.issues == []


def test_the_win_label_read_as_w1n_still_anchors_the_win() -> None:
    assert parse_meter(CASH_WITH_WIN, "cash").win.value == 1.3


def test_an_empty_win_box_is_no_win_and_not_a_problem() -> None:
    parsed = parse_meter(CASH_NO_WIN, "cash")

    assert parsed.win.value is None
    assert parsed.balance.value == 1039.13
    assert parsed.bet.value == 0.88
    assert parsed.issues == []  # the stray "1" of the denomination button is nobody's amount


def test_the_meter_can_be_identified_by_its_labels_alone() -> None:
    assert parse_meter(CREDITS_NO_WIN).shows == "credits"
    assert parse_meter(CASH_WITH_WIN).shows == "cash"
    assert parse_meter(CASH_WITH_WIN).balance.value == 1039.55


def test_a_crop_of_the_other_meter_is_reported_and_not_read_as_this_one() -> None:
    parsed = parse_meter(CREDITS_NO_WIN, "cash")

    assert parsed.shows == "credits"
    assert parsed.balance.value is None
    assert parsed.issues == ["The crop shows the credits meter, not the cash one."]


def test_a_crop_with_no_balance_label_says_so() -> None:
    parsed = parse_meter([b for b in CASH_WITH_WIN if b.text != "CASH"], "cash")

    assert parsed.shows is None
    assert parsed.balance.value is None
    assert "No CASH label was read." in parsed.issues


def test_a_crop_with_no_labels_at_all_cannot_be_identified() -> None:
    parsed = parse_meter([box("Game Over", 20, 10, 80, 30)])

    assert parsed.shows is None
    assert parsed.issues[0].startswith("Neither a CASH nor a CREDITS label was read")


def test_a_missing_bet_label_is_reported() -> None:
    parsed = parse_meter([b for b in CASH_NO_WIN if b.text != "BET"], "cash")

    assert parsed.bet.value is None
    assert "No BET label was read." in parsed.issues


def test_a_label_with_no_amount_above_it_is_reported() -> None:
    parsed = parse_meter([b for b in CASH_NO_WIN if b.text != "$0.88"], "cash")

    assert parsed.bet.value is None
    assert "No amount was read next to the BET label." in parsed.issues


def test_a_win_whose_label_was_cut_off_is_found_between_the_balance_and_the_bet() -> None:
    parsed = parse_meter([b for b in CASH_WITH_WIN if b.text != "W1N"], "cash")

    assert parsed.win.value == 1.3
    assert parsed.issues == [
        "The WIN label was not read: took the amount between the balance and the bet as the win."
    ]


def test_with_the_win_label_read_an_amount_elsewhere_is_never_taken_for_the_win() -> None:
    # The "1" of the denomination button lies right of the bet, and a label that is there owns its own column.
    assert parse_meter(CASH_NO_WIN, "cash").win.value is None


def test_a_shaky_reading_is_flagged() -> None:
    shaky = [b if b.text != "$0.88" else box("$0.88", 697, 12, 782, 45, 0.55) for b in CASH_WITH_WIN]

    parsed = parse_meter(shaky, "cash")

    assert parsed.bet.value == 0.88 and parsed.bet.confidence == 55.0
    assert parsed.issues == ["BET was read with low confidence (55%): '$0.88'."]


def test_it_becomes_the_reading_of_the_meter_it_is() -> None:
    credit = parse_meter(CREDITS_NO_WIN, "credits").as_credit_meter()
    cash = parse_meter(CASH_WITH_WIN, "cash").as_cash_meter()

    assert credit.credits.value == 99720.0 and credit.bet.value == 88.0 and credit.win.value is None
    assert cash.cash.value == 1039.55 and cash.win.value == 1.3 and cash.bet.value == 0.88


# ------------------------------------------------------------ labels placed differently by another game


def test_a_meter_with_each_label_left_of_its_amount_is_read_in_full() -> None:
    parsed = parse_meter(HUFF_CASH_WITH_WIN, "cash")

    assert parsed.shows == "cash"
    assert (parsed.balance.text, parsed.balance.value) == ("$998.20", 998.2)
    assert (parsed.win.text, parsed.win.value) == ("$3.00", 3.0)
    assert (parsed.bet.text, parsed.bet.value) == ("$2.00", 2.0)
    assert parsed.issues == []  # the credits under each label and the denomination button are nobody's amount


def test_the_amount_before_a_label_is_not_taken_for_it() -> None:
    # The WIN amount ends 18 px left of the BET label, and the BET amount starts 18 px right of it; the WIN
    # amount is taller, so by text height it is the nearer of the two (0.39 against 0.51).
    parsed = parse_meter(HUFF_CASH_WITH_WIN, "cash")

    assert parsed.bet.value == 2.0 and parsed.win.value == 3.0


def test_the_meter_can_be_identified_by_its_labels_when_they_are_beside_the_amounts() -> None:
    parsed = parse_meter(HUFF_CASH_WITH_WIN)

    assert parsed.shows == "cash" and parsed.balance.value == 998.2


def test_a_win_that_is_not_shown_beside_its_label_is_no_win() -> None:
    parsed = parse_meter([b for b in HUFF_CASH_WITH_WIN if b.text not in {"$3.00", "300"}], "cash")

    assert parsed.win.value is None
    assert (parsed.balance.value, parsed.bet.value) == (998.2, 2.0)
    assert parsed.issues == []


def test_a_win_whose_label_was_cut_off_is_found_between_the_balance_and_the_bet_beside_the_labels() -> None:
    parsed = parse_meter([b for b in HUFF_CASH_WITH_WIN if b.text != "WIN"], "cash")

    assert parsed.win.value == 3.0
    assert parsed.issues == [
        "The WIN label was not read: took the amount between the balance and the bet as the win."
    ]


def test_a_label_with_no_amount_beside_it_is_reported() -> None:
    parsed = parse_meter([b for b in HUFF_CASH_WITH_WIN if b.text not in {"$998.20", "99820"}], "cash")

    assert parsed.balance.value is None
    assert "No amount was read next to the CASH label." in parsed.issues


def test_labels_over_their_amounts_are_read_the_same_as_labels_under_them() -> None:
    # CASH_WITH_WIN with its labels moved above their amounts, which are moved down to the label's row.
    swapped = [
        box("CREDITS", 294, 12, 383, 32),
        box("99720", 293, 42, 384, 75),
        box("WIN", 514, 12, 567, 33, 0.84),
        box("$1.30", 477, 42, 597, 84),
        box("BET", 722, 13, 765, 31, 0.988),
        box("88", 718, 43, 762, 75),
    ]

    parsed = parse_meter(swapped, "credits")

    assert (parsed.balance.value, parsed.win.value, parsed.bet.value) == (99720.0, 1.3, 88.0)
    assert parsed.issues == []


def test_an_amount_too_far_from_every_label_is_nobodys() -> None:
    parsed = parse_meter([box("CASH", 20, 40, 80, 60), box("$5.00", 600, 36, 700, 66)], "cash")

    assert parsed.balance.value is None
