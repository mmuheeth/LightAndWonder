from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.dependencies import get_obs_controller, get_payline_controller
from app.controllers.obs_controller import ObsController
from app.controllers.payline_controller import PaylineController
from app.main import app
from app.schemas.game_context import GameMode
from app.schemas.symbol import SymbolModelInfo, SymbolReading, SymbolTile
from app.services.game_config_service import GameConfigService
from app.services.game_context_service import GameContextService
from app.services.obs_window_service import ObsWindowService
from app.services.payline_service import PaylineService
from app.services.symbol_service import SymbolService
from app.utils import game_config as game_settings
from app.utils import symbol_classifier
from app.utils.log_watcher import LogWatcher
from tests.fake_obs import FakeObs
from tests.test_game_config import GAME_CFG, LOG_LINE, math_xml, ways_math_xml
from tests.test_log_watcher import bet_line, paytable_line
from tests.test_roi import (  # noqa: F401  (fixtures and helpers of the ROI tests, which this builds on)
    GAME,
    connected,
    fake_games,
    game_screenshot,
    make_config,
    png,
    roi_service,
)
from tests.test_symbols import games_dir, symbol_service  # noqa: F401

URL = "/api/v1/paylines"
PAYTABLE = "TestGame-100c-90"
NAMES = {"WC": "Wild", "AA": "Ace", "BB": "Bell", "CC": "Cherry", "SC": "Scatter"}

# Three lines over the 3 x 5 grid: the middle row, the top row, and a diagonal.
LINES = ["11111", "00000", "01210"]

COMBOS = "".join(
    "<PaylineCombo><SymbolList>"
    + "".join(f"<Symbol>{s}</Symbol>" for s in symbols.split())
    + f"</SymbolList><ComboID>{combo_id}</ComboID><Value>{value}</Value></PaylineCombo>"
    for combo_id, symbols, value in [
        (1, "WC WC WC WC WC", 100),
        (2, "AA AA AA AA AA", 20),
        (3, "AA AA AA AA ANY", 5),
        (4, "AA AA AA ANY ANY", 2),
        (5, "BB BB BB ANY ANY", 3),
    ]
)


def with_wild_standing_in(xml: str) -> str:
    """Lets the wild of the test paytable stand in for Ace, Bell and Cherry, but not for the scatter."""
    wild = "<WildSymbol><Identifier>WC</Identifier></WildSymbol>"
    stands_in = "".join(f"<Symbol>{s}</Symbol>" for s in ("AA", "BB", "CC"))
    return xml.replace(
        wild, f"<WildSymbol><Identifier>WC</Identifier><SymbolList>{stands_in}</SymbolList></WildSymbol>"
    )


def geometry_xml(lines: list[str], set_id: int = 3) -> str:
    paylines = "".join(
        f'<Payline paylineNumber="{number}">'
        + "".join(f'<PaylineElement reelIndex="{reel}" position="{row}" />' for reel, row in enumerate(rows))
        + "</Payline>"
        for number, rows in enumerate(lines)
    )
    return f'<WinGeometryData><PaylineSetList><PaylineSet paylineSetID="{set_id}">{paylines}</PaylineSet></PaylineSetList></WinGeometryData>'


class Install:
    """A fake game install: one paytable, its win geometry, the game log, and the game's config entry."""

    def __init__(self, root: Path, fake_games: dict[str, dict]) -> None:
        self.config_dir = root / "GameConfig"
        self.folder = self.config_dir / PAYTABLE
        self.folder.mkdir(parents=True)
        self.geometry = self.config_dir / "winGeometry.xml"
        self.log = root / "TestGame_Client.log"
        self.log.write_text("")

        (self.folder / "math.xml").write_text(with_wild_standing_in(math_xml(combos=COMBOS)), encoding="utf-8")
        (self.folder / "gameConfig.cfg").write_text(GAME_CFG.format(lines=len(LINES)), encoding="utf-8")
        self.geometry.write_text(geometry_xml(LINES), encoding="utf-8")

        self.config = make_config(symbols=NAMES, scatter_symbols=["SC"], pay_kind="lines")
        self.config["simulator"] = {
            **self.config["simulator"],
            "logs": str(self.log),
            "game_config": str(self.config_dir),
            "win_geometry": str(self.geometry),
        }
        fake_games[GAME] = self.config


@pytest.fixture
def install(tmp_path: Path, fake_games: dict[str, dict]) -> Install:
    return Install(tmp_path, fake_games)


@pytest.fixture
def game_context(games_dir: Path, tmp_path: Path) -> GameContextService:  # noqa: F811
    """Selects the test game, the only one in the games folder."""
    return GameContextService(state_file=tmp_path / "context.json", games_dir=games_dir)


@pytest.fixture
def watcher(game_context: GameContextService) -> LogWatcher:
    return LogWatcher(lambda: game_settings.active_log_path(game_context))


@pytest.fixture
def payline_service(
    install: Install, symbol_service: SymbolService, game_context: GameContextService, watcher: LogWatcher  # noqa: F811
) -> PaylineService:
    return PaylineService(
        symbols=symbol_service,
        game_config=GameConfigService(game_context, watcher),
        min_confidence=90.0,
    )


@pytest.fixture
def payline_client(payline_service: PaylineService, window_service: ObsWindowService, fake_obs: FakeObs):
    fake_obs.image = png(game_screenshot())
    app.dependency_overrides[get_payline_controller] = lambda: PaylineController(payline_service)
    app.dependency_overrides[get_obs_controller] = lambda: ObsController(
        payline_service._symbols._roi._obs, window_service
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def reading(rows: list[str], reading_id: str = "roi_20260930_120000_000_aaaaaa", **confidence: float) -> SymbolReading:
    """Symbols as rows of codes; `r1c3=85` puts the classifier at 85% on the tile in row 1, reel 3."""
    tiles = [
        SymbolTile(
            row=row,
            column=column,
            code=code,
            name=NAMES.get(code),
            confidence=confidence.get(f"r{row + 1}c{column + 1}", 99.0),
        )
        for row, text in enumerate(rows)
        for column, code in enumerate(text.split())
    ]
    return SymbolReading(
        id=reading_id,
        created_at=datetime.now().astimezone(),
        game=GAME,
        mode=GameMode.SIMULATOR,
        rows=len(rows),
        columns=len(tiles) // len(rows),
        model=SymbolModelInfo(
            architecture="ResNet34", trained_at=datetime.now().astimezone(), classes=["AA"], image_count=1, epochs=1
        ),
        tiles=tiles,
    )


def keep(service: PaylineService, saved: SymbolReading) -> SymbolReading:
    service._symbols._save_reading(saved)
    return saved


WINNING = ["AA AA AA BB CC", "BB AA CC CC CC", "CC AA AA AA SC"]  # line 1 pays 2 (Ace x3)


def play(install: Install, watcher: LogWatcher, *lines: str) -> None:
    """Has the game log say `lines`, and the watcher read them."""
    install.log.write_text("\n".join(lines) + "\n")
    watcher.poll()
    watcher.poll()


def score(client: TestClient, reading_id: str, **params) -> dict:
    response = client.get(f"{URL}/score", params={"reading": reading_id, "paytable": PAYTABLE, **params})
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ----------------------------------------------------------------------------- scoring


def test_a_saved_reading_is_scored_along_the_lines_of_the_win_geometry(
    payline_client: TestClient, payline_service: PaylineService
) -> None:
    saved = keep(payline_service, reading(["AA AA AA BB CC", "BB BB BB AA CC", "CC AA AA AA SC"]))

    result = score(payline_client, saved.id)

    assert (result["reading_id"], result["game"], result["mode"]) == (saved.id, GAME, "simulator")
    assert (result["paytable_id"], result["paytable_source"], result["line_set"]) == (PAYTABLE, "request", 3)
    assert (result["kind"], result["ways"]) == ("lines", [])
    assert (result["rows"], result["columns"], result["min_confidence"]) == (3, 5, 90.0)
    assert [t["code"] for t in result["tiles"]] == [t.code for t in saved.tiles]
    lines = {line["number"]: line for line in result["lines"]}
    assert sorted(lines) == [1, 2, 3]
    # Line 1 is the middle row: Bell x3, then Ace, Cherry.
    assert (lines[1]["symbol"], lines[1]["symbol_name"], lines[1]["matches"], lines[1]["pays"]) == (
        "BB", "Bell", 3, 3,
    )
    assert lines[1]["combo"] == {"id": 5, "pattern": ["BB", "BB", "BB", "ANY", "ANY"], "value": 3}
    assert [(c["row"], c["column"], c["code"]) for c in lines[1]["cells"]] == [
        (1, 0, "BB"), (1, 1, "BB"), (1, 2, "BB"), (1, 3, "AA"), (1, 4, "CC"),
    ]
    assert [s["relation"] for s in lines[1]["steps"]] == ["same", "same", "different", "different"]
    assert [s["counted"] for s in lines[1]["steps"]] == [True, True, True, False]
    # Line 2 is the top row: Ace x3.
    assert (lines[2]["symbol"], lines[2]["pays"], lines[2]["combo"]["id"]) == ("AA", 2, 4)
    # Line 3 crosses rows 1-2-3-2-1: Ace, Bell, Ace, Ace, Cherry. Its run ends at once.
    assert [c["code"] for c in lines[3]["cells"]] == ["AA", "BB", "AA", "AA", "CC"]
    assert (lines[3]["pays"], lines[3]["combo"]) == (0, None)
    assert result["total_credits"] == 5
    assert result["complete"] is True


def test_the_credits_follow_the_bet_and_denom_the_game_log_reports(
    payline_client: TestClient, payline_service: PaylineService, install: Install, watcher: LogWatcher
) -> None:
    saved = keep(payline_service, reading(["AA AA AA BB CC", "BB BB BB AA CC", "CC AA AA AA SC"]))
    # 6 cents on each line at a 2c denom is 3 credits on each line, and 528 cents is 264 credits.
    play(install, watcher, paytable_line(PAYTABLE, "2.000"), bet_line("6.000", "528.000"))

    result = score(payline_client, saved.id)

    assert result["bet"] == {"denom": 2.0, "bets_per_unit": 6.0, "credits_per_unit": 3.0, "total_bet": 264.0}
    lines = {line["number"]: line for line in result["lines"]}
    assert (lines[1]["pays"], lines[1]["credits"]) == (3, 9)  # Bell x3
    assert (lines[2]["pays"], lines[2]["credits"]) == (2, 6)  # Ace x3
    assert (lines[3]["pays"], lines[3]["credits"]) == (0, 0)
    assert result["total_credits"] == 15


def test_a_dearer_denom_does_not_make_the_same_cents_worth_more_credits(
    payline_client: TestClient, payline_service: PaylineService, install: Install, watcher: LogWatcher
) -> None:
    saved = keep(payline_service, reading(["AA AA AA BB CC", "BB BB BB AA CC", "CC AA AA AA SC"]))
    # The same 6 cents on each line, but at a 1c denom: 6 credits on each line.
    play(install, watcher, paytable_line(PAYTABLE, "1.000"), bet_line("6.000", "528.000"))

    result = score(payline_client, saved.id)

    assert result["bet"]["credits_per_unit"] == 6 and result["bet"]["total_bet"] == 528
    assert result["total_credits"] == 30


def test_the_awards_are_for_one_credit_on_each_line_while_the_log_has_no_bet(
    payline_client: TestClient, payline_service: PaylineService, install: Install, watcher: LogWatcher
) -> None:
    saved = keep(payline_service, reading(["AA AA AA BB CC", "BB BB BB AA CC", "CC AA AA AA SC"]))
    play(install, watcher, paytable_line(PAYTABLE, "2.000"))  # a denom, but no bet yet

    result = score(payline_client, saved.id)

    assert result["bet"] is None
    assert all(line["credits"] == line["pays"] for line in result["lines"])
    assert result["total_credits"] == 5


def test_a_run_the_paytable_does_not_pay_is_reported(
    payline_client: TestClient, payline_service: PaylineService
) -> None:
    saved = keep(payline_service, reading(["BB BB CC AA AA", "AA CC BB CC AA", "CC BB AA BB CC"]))

    result = score(payline_client, saved.id)

    unpaid = [line["number"] for line in result["lines"] if line["unpaid"]]
    assert unpaid == [2]  # the top row: two Bells, which pay from three
    assert result["total_credits"] == 0


def test_the_confidence_floor_decides_which_tiles_are_read(
    payline_client: TestClient, payline_service: PaylineService
) -> None:
    saved = keep(payline_service, reading(WINNING, r1c3=85))

    default_floor = score(payline_client, saved.id)
    lower_floor = score(payline_client, saved.id, min_confidence=80)

    # At the default 90% the top row's third Ace is not read, so line 2 (the top row) cannot pay.
    assert default_floor["min_confidence"] == 90
    top = {line["number"]: line for line in default_floor["lines"]}[2]
    assert [c["code"] for c in top["cells"]][:3] == ["AA", "AA", None]
    assert top["cells"][2]["guess"] == "AA" and top["cells"][2]["confidence"] == 85
    assert (top["pays"], top["matches"], top["uncertain"]) == (0, 2, True)
    assert default_floor["complete"] is False
    assert [t["code"] for t in default_floor["tiles"]].count(None) == 1
    # At 80% it is read, and the line pays.
    assert lower_floor["min_confidence"] == 80
    assert {line["number"]: line for line in lower_floor["lines"]}[2]["pays"] == 2
    assert lower_floor["complete"] is True
    assert lower_floor["total_credits"] == default_floor["total_credits"] + 2


def test_an_unread_tile_off_the_lines_leaves_the_total_complete(
    payline_client: TestClient, payline_service: PaylineService
) -> None:
    saved = keep(payline_service, reading(WINNING, r3c5=10))

    result = score(payline_client, saved.id)

    assert [t["code"] for t in result["tiles"]].count(None) == 1
    assert result["complete"] is True


def test_the_floor_must_be_a_percent(payline_client: TestClient, payline_service: PaylineService) -> None:
    saved = keep(payline_service, reading(WINNING))

    response = payline_client.get(f"{URL}/score", params={"reading": saved.id, "min_confidence": 120})

    assert response.status_code == 422


# ---------------------------------------------------------------------------- paytable


def test_the_paytable_is_the_one_the_game_log_reported(
    payline_client: TestClient, payline_service: PaylineService, install: Install, watcher: LogWatcher
) -> None:
    saved = keep(payline_service, reading(WINNING))
    install.log.write_text(LOG_LINE.format(paytable=PAYTABLE))
    watcher.poll()
    watcher.poll()

    response = payline_client.get(f"{URL}/score", params={"reading": saved.id})

    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["paytable_id"], data["paytable_source"]) == (PAYTABLE, "log")


def test_a_log_that_has_reported_no_paytable_is_refused(
    payline_client: TestClient, payline_service: PaylineService
) -> None:
    saved = keep(payline_service, reading(WINNING))

    response = payline_client.get(f"{URL}/score", params={"reading": saved.id})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PAYTABLE_UNKNOWN"


def test_an_unknown_paytable_is_not_found(payline_client: TestClient, payline_service: PaylineService) -> None:
    saved = keep(payline_service, reading(WINNING))

    response = payline_client.get(f"{URL}/score", params={"reading": saved.id, "paytable": "Nope-1c-90"})

    assert response.status_code == 404


def test_an_unknown_reading_is_not_found(payline_client: TestClient) -> None:
    assert payline_client.get(f"{URL}/score", params={"reading": "roi_nope"}).status_code == 404


def test_a_reading_id_cannot_leave_the_readings_folder(payline_client: TestClient) -> None:
    for bad in ("../game_context", "..", "a/b", "a b"):
        assert payline_client.get(f"{URL}/score", params={"reading": bad}).status_code == 400


def test_a_game_without_win_geometry_has_no_paylines(
    payline_client: TestClient, payline_service: PaylineService, install: Install
) -> None:
    del install.config["simulator"]["win_geometry"]
    saved = keep(payline_service, reading(WINNING))

    response = payline_client.get(f"{URL}/score", params={"reading": saved.id, "paytable": PAYTABLE})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAYLINES_NO_GEOMETRY"


def test_a_paytable_whose_line_count_has_no_set_in_the_geometry_is_refused(
    payline_client: TestClient, payline_service: PaylineService, install: Install
) -> None:
    (install.folder / "gameConfig.cfg").write_text(GAME_CFG.format(lines=7), encoding="utf-8")
    saved = keep(payline_service, reading(WINNING))

    response = payline_client.get(f"{URL}/score", params={"reading": saved.id, "paytable": PAYTABLE})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAYLINES_NO_LINE_SET"


def test_lines_that_do_not_fit_the_grid_that_was_read_are_refused(
    payline_client: TestClient, payline_service: PaylineService, install: Install
) -> None:
    (install.folder / "gameConfig.cfg").write_text(GAME_CFG.format(lines=2), encoding="utf-8")
    install.geometry.write_text(geometry_xml(["1111", "0000"], set_id=2), encoding="utf-8")
    saved = keep(payline_service, reading(WINNING))

    response = payline_client.get(f"{URL}/score", params={"reading": saved.id, "paytable": PAYTABLE})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAYLINES_GRID_MISMATCH"


# -------------------------------------------------------------------------------- ways

WAYS = {
    "AA": [("AA AA AA AA AA", 20), ("AA AA AA AA ANY", 5), ("AA AA AA ANY ANY", 2)],
    "BB": [("BB BB BB ANY ANY", 3)],
}


@pytest.fixture
def ways_install(install: Install) -> Install:
    """The same game with a paytable that pays by ways: 243 of them over its 3 x 5 grid, and no payline set."""
    install.config["pay_kind"] = "ways"
    (install.folder / "math.xml").write_text(with_wild_standing_in(ways_math_xml(WAYS)), encoding="utf-8")
    (install.folder / "gameConfig.cfg").write_text(GAME_CFG.format(lines=243), encoding="utf-8")
    return install


def test_a_ways_paytable_is_scored_over_every_route_across_the_reels(
    payline_client: TestClient, payline_service: PaylineService, ways_install: Install
) -> None:
    saved = keep(payline_service, reading(["AA BB AA CC BB", "AA AA WC CC AA", "BB CC AA BB CC"]))

    result = score(payline_client, saved.id)

    assert (result["kind"], result["line_set"], result["lines"]) == ("ways", 243, [])
    ways = {way["symbol"]: way for way in result["ways"]}
    assert sorted(ways) == ["AA", "BB"]
    # Ace: two cells on reel 1, one on reel 2, three on reel 3 (the wild stands in): 6 ways at 2 each.
    ace = ways["AA"]
    assert (ace["symbol_name"], ace["matches"], ace["ways"], ace["pays"]) == ("Ace", 3, 6, 12)
    assert ace["combo"] == {"id": 3, "pattern": ["AA", "AA", "AA", "ANY", "ANY"], "value": 2}
    assert [[(c["row"], c["column"], c["code"]) for c in reel] for reel in ace["reels"]] == [
        [(0, 0, "AA"), (1, 0, "AA")],
        [(1, 1, "AA")],
        [(0, 2, "AA"), (1, 2, "WC"), (2, 2, "AA")],
    ]
    # Bell runs over all five reels, but the paytable only pays it for three.
    assert (ways["BB"]["matches"], ways["BB"]["ways"], ways["BB"]["pays"]) == (3, 1, 3)
    assert result["total_credits"] == 15
    assert result["complete"] is True


def test_a_ways_paytable_pays_the_credits_bet_on_each_way(
    payline_client: TestClient, payline_service: PaylineService, ways_install: Install, watcher: LogWatcher
) -> None:
    saved = keep(payline_service, reading(["AA BB AA CC BB", "AA AA WC CC AA", "BB CC AA BB CC"]))
    play(ways_install, watcher, paytable_line(PAYTABLE, "1.000"), bet_line("5.000", "500.000"))

    result = score(payline_client, saved.id)

    assert result["bet"]["credits_per_unit"] == 5
    ways = {way["symbol"]: way for way in result["ways"]}
    assert (ways["AA"]["pays"], ways["AA"]["credits"]) == (12, 60)
    assert (ways["BB"]["pays"], ways["BB"]["credits"]) == (3, 15)
    assert result["total_credits"] == 75


def test_a_ways_game_whose_math_has_no_ways_combos_is_refused_as_such(
    payline_client: TestClient, payline_service: PaylineService, install: Install
) -> None:
    install.config["pay_kind"] = "ways"  # while its math.xml holds payline combos only
    saved = keep(payline_service, reading(WINNING))

    response = payline_client.get(f"{URL}/score", params={"reading": saved.id, "paytable": PAYTABLE})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAYLINES_NO_COMBOS"
    assert "ways combos" in response.json()["error"]["message"]


def test_a_ways_paytable_needs_no_win_geometry(
    payline_client: TestClient, payline_service: PaylineService, ways_install: Install
) -> None:
    del ways_install.config["simulator"]["win_geometry"]
    saved = keep(payline_service, reading(["AA AA AA CC CC", "CC CC CC CC CC", "CC CC CC CC CC"]))

    result = score(payline_client, saved.id)

    assert (result["kind"], result["total_credits"]) == ("ways", 2)


def test_an_unread_tile_makes_a_ways_total_incomplete(
    payline_client: TestClient, payline_service: PaylineService, ways_install: Install
) -> None:
    saved = keep(payline_service, reading(["AA AA AA CC CC", "CC CC CC CC CC", "CC CC CC CC CC"], r1c3=85))

    result = score(payline_client, saved.id)

    assert [way["symbol"] for way in result["ways"]] == ["AA"]
    ace = result["ways"][0]
    assert (ace["pays"], ace["matches"], ace["uncertain"], ace["unpaid"]) == (0, 2, True, False)
    assert [(c["row"], c["column"], c["code"], c["guess"]) for c in ace["unread"]] == [(0, 2, None, "AA")]
    assert (result["total_credits"], result["complete"]) == (0, False)
    # With the floor lowered the tile is read, and Ace pays.
    lenient = score(payline_client, saved.id, min_confidence=80)
    assert (lenient["total_credits"], lenient["complete"]) == (2, True)


def test_a_grid_that_does_not_hold_the_ways_of_the_paytable_is_refused(
    payline_client: TestClient, payline_service: PaylineService, ways_install: Install
) -> None:
    # Three rows over four reels hold 81 ways, not the 243 the paytable pays.
    saved = keep(payline_service, reading(["AA AA AA CC", "CC CC CC CC", "CC CC CC CC"]))

    response = payline_client.get(f"{URL}/score", params={"reading": saved.id, "paytable": PAYTABLE})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAYLINES_GRID_MISMATCH"
    assert "243" in response.json()["error"]["message"] and "81" in response.json()["error"]["message"]


# --------------------------------------------------------------------------- evaluating


class GridClassifier:
    """Names the tiles of the screenshot as it is told to, row by row, with a confidence for each."""

    classes = ["AA"]

    def __init__(self, tiles: list[tuple[str, float]]) -> None:
        self.tiles = tiles

    def classify(self, images: list[Image.Image]) -> list[symbol_classifier.Prediction]:
        assert len(images) == len(self.tiles)
        return [symbol_classifier.Prediction(code=code, confidence=confidence) for code, confidence in self.tiles]


def see(monkeypatch: pytest.MonkeyPatch, symbols: SymbolService, rows: list[str], **confidence: float) -> None:
    """Makes the classifier read `rows` off the screenshot, and gives the game a trained model to do it with."""
    shown = reading(rows, **confidence)
    tiles = [(tile.code, tile.confidence) for tile in shown.tiles]
    monkeypatch.setattr(
        symbol_classifier.SymbolClassifier, "load", classmethod(lambda cls, path: GridClassifier(tiles))
    )
    symbols._write_info(GAME, shown.model)


def test_evaluate_takes_a_screenshot_reads_the_symbols_and_scores_the_lines(
    payline_client: TestClient,
    payline_service: PaylineService,
    monkeypatch: pytest.MonkeyPatch,
    connected,
    fake_obs: FakeObs,
) -> None:
    see(monkeypatch, payline_service._symbols, ["AA AA AA AA CC", "BB BB BB AA CC", "CC AA AA AA SC"])

    response = payline_client.post(f"{URL}/evaluate", params={"game": GAME, "paytable": PAYTABLE})

    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert len(fake_obs.calls("SaveSourceScreenshot")) == 1
    assert (result["game"], result["mode"], result["paytable_source"]) == (GAME, "simulator", "request")
    # Line 1 (middle row): Bell x3 = 3. Line 2 (top row): Ace x4 = 5. Line 3 (diagonal): nothing.
    assert [(line["number"], line["pays"]) for line in result["lines"]] == [(1, 3), (2, 5), (3, 0)]
    assert result["total_credits"] == 8
    # The reading it scored is kept as the Symbol tab's, and the result points at the grid it was read from.
    kept = payline_service._symbols.list_readings(1)[0]
    assert result["reading_id"] == kept.id
    assert result["reels"] == kept.reels.model_dump()
    assert result["reels"] is not None
    # Scoring it again later gives the same answer, without a new screenshot.
    again = score(payline_client, kept.id)
    assert again["lines"] == result["lines"] and again["total_credits"] == 8
    assert len(fake_obs.calls("SaveSourceScreenshot")) == 1


def test_evaluate_uses_the_floor_it_is_given(
    payline_client: TestClient,
    payline_service: PaylineService,
    monkeypatch: pytest.MonkeyPatch,
    connected,
) -> None:
    see(monkeypatch, payline_service._symbols, ["AA AA AA AA CC", "BB BB BB AA CC", "CC AA AA AA SC"], r1c2=70)

    strict = payline_client.post(f"{URL}/evaluate", params={"game": GAME, "paytable": PAYTABLE}).json()["data"]
    lenient = payline_client.post(
        f"{URL}/evaluate", params={"game": GAME, "paytable": PAYTABLE, "min_confidence": 60}
    ).json()["data"]

    assert (strict["total_credits"], strict["complete"]) == (3, False)
    assert (lenient["total_credits"], lenient["complete"]) == (8, True)


def test_evaluate_needs_a_trained_model_and_leaves_obs_alone(
    payline_client: TestClient, connected, fake_obs: FakeObs
) -> None:
    response = payline_client.post(f"{URL}/evaluate", params={"game": GAME, "paytable": PAYTABLE})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SYMBOL_MODEL_MISSING"
    assert fake_obs.calls("SaveSourceScreenshot") == []


def test_evaluate_needs_an_obs_connection(
    payline_client: TestClient, payline_service: PaylineService, monkeypatch: pytest.MonkeyPatch
) -> None:
    see(monkeypatch, payline_service._symbols, WINNING)

    assert payline_client.post(f"{URL}/evaluate", params={"game": GAME, "paytable": PAYTABLE}).status_code == 503
