from app.schemas.game_config import PayCombo, PayRules, WildRule
from app.schemas.payline import PaylineCell, PaylineOutcome
from app.utils import paylines

NAMES = {"AA": "Ace", "BB": "Bell", "CC": "Cherry", "WC": "Wild", "SC": "Scatter"}


def combo(symbols: str, value: float, combo_id: int | None = None) -> PayCombo:
    return PayCombo(id=combo_id, symbols=symbols.split(), value=value)


RULES = PayRules(
    combos=[
        combo("WC WC WC WC WC", 100, 1),
        combo("AA AA AA AA AA", 20, 2),
        combo("AA AA AA AA", 5, 3),
        combo("AA AA AA", 2, 4),
        combo("BB BB BB AA", 9, 5),  # a run of mixed symbols
        combo("BB BB BB", 3, 6),
        combo("CC CC CC CC CC", 8, 7),
    ],
    # The wild stands in for the regular symbols, but not for the scatter.
    wilds=[WildRule(code="WC", substitutes=["AA", "BB", "CC"])],
)


def cells(text: str, **unread: bool) -> list[PaylineCell]:
    """A line read as 'AA BB ??': a '??' is a tile the classifier was not sure of."""
    return [
        PaylineCell(
            row=1,
            column=column,
            code=None if code == "??" else code,
            guess="AA" if code == "??" else code,
            confidence=50.0 if code == "??" else 99.0,
        )
        for column, code in enumerate(text.split())
    ]


def score(text: str) -> PaylineOutcome:
    return paylines.score_line(1, cells(text), RULES, paylines.wild_map(RULES), NAMES)


def relations(outcome: PaylineOutcome) -> list[tuple[str, bool]]:
    return [(step.relation, step.counted) for step in outcome.steps]


# ------------------------------------------------------------------------ what pays


def test_a_full_run_pays_its_combo() -> None:
    line = score("AA AA AA AA AA")

    assert (line.symbol, line.symbol_name, line.matches, line.pays) == ("AA", "Ace", 5, 20)
    assert line.combo is not None
    assert (line.combo.id, line.combo.pattern, line.combo.value) == (2, ["AA"] * 5, 20)
    assert relations(line) == [("same", True)] * 4
    assert (line.unpaid, line.uncertain) == (False, False)


def test_a_shorter_run_pays_its_combo_padded_with_any() -> None:
    line = score("AA AA AA BB CC")

    assert (line.matches, line.pays) == (3, 2)
    assert line.combo is not None and line.combo.pattern == ["AA", "AA", "AA", "ANY", "ANY"]
    # The step that ended the run is counted; the one after it only shows how the tiles compare.
    assert relations(line) == [("same", True), ("same", True), ("different", True), ("different", False)]


def test_the_best_combo_that_a_line_fills_pays() -> None:
    assert score("AA AA AA AA BB").pays == 5  # not the 3-run's 2
    assert score("AA AA AA AA AA").pays == 20


def test_a_run_counts_from_the_first_reel_only() -> None:
    line = score("BB AA AA AA AA")

    assert (line.symbol, line.matches, line.pays) == ("BB", 1, 0)
    assert relations(line)[0] == ("different", True)
    # Later tiles that match each other are shown, but not counted.
    assert relations(line)[1:] == [("same", False)] * 3


def test_a_combo_of_mixed_symbols_needs_each_one_in_its_place() -> None:
    assert score("BB BB BB AA CC").pays == 9
    assert score("BB BB BB CC AA").pays == 3


def test_a_wild_fills_for_the_symbols_it_stands_in_for() -> None:
    line = score("WC AA AA BB CC")

    assert (line.symbol, line.matches, line.pays) == ("AA", 3, 2)
    assert relations(line)[:2] == [("wild", True), ("same", True)]

    assert score("AA WC WC AA BB").pays == 5
    assert score("AA WC AA AA WC").pays == 20


def test_a_wild_does_not_fill_for_a_symbol_it_does_not_stand_in_for() -> None:
    line = score("SC WC SC SC SC")

    assert (line.symbol, line.matches, line.pays) == ("SC", 1, 0)
    assert score("WC SC SC SC SC").pays == 0


def test_wilds_pay_as_wilds_or_as_the_symbol_that_pays_more() -> None:
    assert score("WC WC WC WC WC").pays == 100
    # As Ace they would pay 20; there is no smaller wild combo, so 20 it is.
    assert score("WC WC AA AA AA").pays == 20
    line = score("WC WC BB CC CC")
    assert (line.symbol, line.matches, line.pays) == ("BB", 3, 3)


def test_a_wild_led_line_that_pays_nothing_is_a_run_of_whatever_goes_on_longer() -> None:
    # Cherries only pay from five, so nothing pays here; the wilds count as cherries, which make three.
    cherries = score("WC WC CC BB BB")
    assert (cherries.symbol, cherries.matches, cherries.pays) == ("CC", 3, 0)
    assert cherries.unpaid is True
    # The wild cannot be a scatter, so the leading wilds are a run of their own (which wilds
    # only pay from five).
    wilds = score("WC WC SC SC SC")
    assert (wilds.symbol, wilds.matches, wilds.unpaid) == ("WC", 2, True)


# --------------------------------------------------------------------- unpaid runs


def test_a_run_of_a_paying_symbol_that_the_paytable_does_not_pay_is_flagged() -> None:
    line = score("BB BB CC AA AA")

    assert (line.pays, line.matches, line.unpaid) == (0, 2, True)
    assert line.combo is None and line.symbol_name == "Bell"


def test_a_run_of_a_symbol_that_never_pays_on_a_line_is_not_flagged() -> None:
    line = score("SC SC AA AA AA")

    assert (line.pays, line.matches, line.unpaid) == (0, 2, False)


def test_a_single_symbol_is_no_run() -> None:
    assert score("AA BB CC AA BB").unpaid is False


# ---------------------------------------------------------------------- unread tiles


def test_an_unread_tile_fills_nothing() -> None:
    line = score("AA AA ?? AA AA")

    assert (line.pays, line.matches) == (0, 2)
    assert relations(line) == [("same", True), ("unknown", True), ("unknown", False), ("same", False)]


def test_an_unread_tile_that_could_change_the_outcome_makes_it_uncertain() -> None:
    hidden_win = score("AA AA ?? AA AA")
    hidden_gain = score("AA AA AA ?? AA")

    assert hidden_win.uncertain is True
    # A run that might have been paid is not "a run the paytable does not pay".
    assert hidden_win.unpaid is False
    assert (hidden_gain.pays, hidden_gain.uncertain) == (2, True)


def test_an_unread_tile_that_could_not_change_it_leaves_it_certain() -> None:
    assert score("AA BB ?? ?? ??").uncertain is False
    assert score("AA AA AA AA AA").uncertain is False
    assert score("AA AA AA BB ??").uncertain is False


def test_a_line_whose_first_tile_is_unread_has_no_run() -> None:
    line = score("?? AA AA AA AA")

    assert (line.symbol, line.matches, line.pays) == (None, 0, 0)
    assert line.uncertain is True
    assert relations(line)[0] == ("unknown", True)


# ------------------------------------------------------------------- whole grids


def test_lines_are_numbered_from_one_and_read_the_rows_they_cross() -> None:
    grid = {
        (row, reel): PaylineCell(row=row, column=reel, code=code, guess=code, confidence=99.0)
        for row, text in enumerate(["AA AA AA AA AA", "BB BB BB BB BB", "CC CC CC CC CC"])
        for reel, code in enumerate(text.split())
    }

    lines = paylines.score_lines([[0] * 5, [1] * 5, [2, 1, 0, 1, 2], [0, 1, 1, 1, 0]], grid, RULES, NAMES)

    assert [line.number for line in lines] == [1, 2, 3, 4]
    assert [[cell.code for cell in line.cells] for line in lines] == [
        ["AA"] * 5,
        ["BB"] * 5,
        ["CC", "BB", "AA", "BB", "CC"],
        ["AA", "BB", "BB", "BB", "AA"],
    ]
    assert [line.pays for line in lines] == [20, 3, 0, 0]


# -------------------------------------------------------- FortuneOx, from a real screenshot

# The 40 lines of FortuneOx's winGeometry.xml: the row each reel's tile is read from (0 is the top).
FORTUNE_OX_LINES = [
    "11111", "00000", "22222", "01210", "21012",
    "10001", "12221", "00122", "22100", "10101",
    "12121", "01112", "21110", "11012", "11210",
    "01010", "21212", "00200", "22022", "10201",
    "12021", "02020", "20202", "02220", "20002",
    "02120", "20102", "11211", "11011", "02011",
    "20211", "00012", "22210", "01222", "21000",
    "10012", "12210", "00100", "22122", "10121",
]  # fmt: skip

# The payline combos of its math.xml: (ComboID, run, pays).
FORTUNE_OX_COMBOS = [
    (1, "WC WC WC WC WC", 250), (2, "WC WC WC WC", 100), (3, "WC WC WC", 50),
    (4, "AA AA AA AA AA", 50), (5, "AA AA AA AA", 25), (6, "AA AA AA", 15),
    (7, "BB BB BB BB BB", 25), (8, "BB BB BB BB", 15), (9, "BB BB BB", 10),
    (10, "CC CC CC CC CC", 25), (11, "CC CC CC CC", 15), (12, "CC CC CC", 10),
    (13, "DD DD DD DD DD", 25), (14, "DD DD DD DD", 15), (15, "DD DD DD", 10),
    (16, "EE EE EE EE EE", 15), (17, "EE EE EE EE", 10), (18, "EE EE EE", 5),
    (19, "FF FF FF FF FF", 15), (20, "FF FF FF FF", 10), (21, "FF FF FF", 5),
    (22, "GG GG GG GG GG", 15), (23, "GG GG GG GG", 10), (24, "GG GG GG", 5),
    (25, "HH HH HH HH HH", 15), (26, "HH HH HH HH", 10), (27, "HH HH HH", 5),
    (28, "JJ JJ JJ JJ JJ", 15), (29, "JJ JJ JJ JJ", 10), (30, "JJ JJ JJ", 5),
]  # fmt: skip

FORTUNE_OX = PayRules(
    combos=[combo(run, pays, combo_id) for combo_id, run, pays in FORTUNE_OX_COMBOS],
    wilds=[WildRule(code="WC", substitutes=["AA", "BB", "CC", "DD", "EE", "FF", "GG", "HH", "JJ"])],
)


def test_the_fortune_ox_screen_of_two_rows_of_pisces_pays_255_over_13_lines() -> None:
    """Pisces (BB) fill the top two rows; the bottom row is Ox, Ten, Ace, King, Ace."""
    screen = ["BB BB BB BB BB", "BB BB BB BB BB", "AA JJ EE FF EE"]
    grid = {
        (row, reel): PaylineCell(row=row, column=reel, code=code, guess=code, confidence=99.0)
        for row, text in enumerate(screen)
        for reel, code in enumerate(text.split())
    }
    lines = paylines.score_lines([[int(row) for row in line] for line in FORTUNE_OX_LINES], grid, FORTUNE_OX, NAMES)

    paying = {line.number: (line.matches, line.pays, line.combo.id) for line in lines if line.pays}
    assert paying == {
        1: (5, 25, 7), 2: (5, 25, 7), 6: (5, 25, 7), 8: (3, 10, 9), 10: (5, 25, 7),
        12: (4, 15, 8), 14: (4, 15, 8), 16: (5, 25, 7), 29: (5, 25, 7), 32: (4, 15, 8),
        36: (4, 15, 8), 38: (5, 25, 7), 40: (3, 10, 9),
    }  # fmt: skip
    assert sum(line.pays for line in lines) == 255
    # Runs of two Pisces, which the paytable only pays from three.
    assert [line.number for line in lines if line.unpaid] == [4, 15, 18, 20, 28, 34]
    assert not any(line.uncertain for line in lines)
    assert lines[6].symbol == "BB" and lines[6].matches == 1  # line 7 stops at its second tile
    assert lines[7].combo is not None and lines[7].combo.pattern == ["BB", "BB", "BB", "ANY", "ANY"]
