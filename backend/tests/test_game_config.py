import os
import re
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_game_config_controller
from app.controllers.game_config_controller import GameConfigController
from app.core.exceptions import (
    AppException,
    BadRequestException,
    NotFoundException,
    ServiceUnavailableException,
)
from app.main import app
from app.schemas.game_config import SymbolKind
from app.schemas.game_context import GameContextUpdate, GameMode
from app.services.game_config_service import GameConfigService
from app.services.game_context_service import GameContextService
from app.utils import game_config as game_settings
from app.utils.log_watcher import LogWatcher

PAYTABLE = "TestGame-100c-90"

MATH_XML = """<?xml version="1.0" encoding="utf-8"?>
<GameMath xmlns="http://scientificgames.com/slotMathXMLSchema.xsd">
  <GamePct>90.00</GamePct>
  <GameBasePct>80.00</GameBasePct>
  <DefaultConfiguration>
    <SymbolSetID>S</SymbolSetID>
    <ReelStripSetID>Reels_BG_0</ReelStripSetID>
    <PaytableID>Paytable_Main</PaytableID>
    <PaylineSetID>5</PaylineSetID>
  </DefaultConfiguration>
  <SymbolSetList><SymbolSet>
    <Identifier>S</Identifier>
    <SymbolList>{symbols}</SymbolList>
    <WildSymbolList><WildSymbol><Identifier>WC</Identifier></WildSymbol></WildSymbolList>
  </SymbolSet></SymbolSetList>
  <ReelStripList>
    {strip_a}
    {strip_b}
  </ReelStripList>
  <ReelStripSetList>
    <ReelStripSet>
      <Identifier>Reels_BG_0</Identifier>
      <ReelStripIDList><ReelStripID>Strip_A</ReelStripID><ReelStripID>Strip_B</ReelStripID></ReelStripIDList>
      <ReelStripVisSymbols>
        <ReelStripVisSymbolsHeight>3</ReelStripVisSymbolsHeight>
        <ReelStripVisSymbolsHeight>3</ReelStripVisSymbolsHeight>
      </ReelStripVisSymbols>
    </ReelStripSet>
    <ReelStripSet>
      <Identifier>Reels_Bonus</Identifier>
      <ReelStripIDList>
        <ReelStripID>Strip_B</ReelStripID><ReelStripID>Strip_B</ReelStripID>
        <ReelStripID>Strip_Gone</ReelStripID>
      </ReelStripIDList>
      <ReelStripVisSymbols><ReelStripVisSymbolsHeight>1</ReelStripVisSymbolsHeight></ReelStripVisSymbols>
    </ReelStripSet>
  </ReelStripSetList>
  <ComboSetList>
    <PaylineComboSet>
      <Identifier>PaylineComboSet_Main</Identifier>
      <PaylineComboList>{combos}</PaylineComboList>
    </PaylineComboSet>
    <PaylineComboSet>
      <Identifier>PaylineComboSet_Other</Identifier>
      <PaylineComboList>{combo_other}</PaylineComboList>
    </PaylineComboSet>
  </ComboSetList>
  <PaytableList>
    <Paytable>
      <Identifier>Paytable_Main</Identifier>
      <ComboSetIDList><ComboSet>PaylineComboSet_Main</ComboSet></ComboSetIDList>
    </Paytable>
  </PaytableList>
  <BonusInfo>
    <WeightedTableList>
      {tables}
    </WeightedTableList>
    <ValueTableList>
      <ValueTable><Identifier>AllowedBetsTbl</Identifier>
        <ValueList><Value>10</Value><Value>20</Value></ValueList></ValueTable>
    </ValueTableList>
  </BonusInfo>
</GameMath>
"""


def strip(identifier: str, stops: list[tuple[str, int]]) -> str:
    elements = "".join(
        f"<WeightedElement><Weight>{weight}</Weight><StringValue>{code}</StringValue></WeightedElement>"
        for code, weight in stops
    )
    return (
        f"<ReelStrip><Identifier>{identifier}</Identifier>"
        f"<WeightedElementList>{elements}</WeightedElementList></ReelStrip>"
    )


def combo(symbols: list[str], value: int, combo_id: int | None = None) -> str:
    listed = "".join(f"<Symbol>{s}</Symbol>" for s in symbols)
    identified = f"<ComboID>{combo_id}</ComboID>" if combo_id is not None else ""
    return f"<PaylineCombo><SymbolList>{listed}</SymbolList>{identified}<Value>{value}</Value></PaylineCombo>"


def table(name: str, rows: list[tuple[int, int]]) -> str:
    elements = "".join(
        f"<WeightedElement><Weight>{weight}</Weight><Value>{value}</Value></WeightedElement>"
        for value, weight in rows
    )
    return (
        f"<WeightedTable><Identifier>{name}</Identifier>"
        f"<WeightedElementList>{elements}</WeightedElementList></WeightedTable>"
    )


def math_xml(**overrides: str) -> str:
    parts = {
        "symbols": "".join(f"<Symbol>{s}</Symbol>" for s in ("WC", "AA", "BB", "CC", "SC")),
        "strip_a": strip("Strip_A", [("AA", 10), ("BB", 10), ("WC", 10)]),
        "strip_b": strip("Strip_B", [("SC", 5), ("CC", 1), ("AA", 3)]),
        "combos": "".join(
            [
                combo(["CC", "CC", "CC", "CC", "CC"], 20),
                combo(["WC", "WC", "WC", "WC", "WC"], 100),
                combo(["WC", "WC", "WC", "WC", "ANY"], 50),
                combo(["AA", "AA", "AA", "AA", "AA"], 20),
                combo(["AA", "AA", "AA", "AA", "ANY"], 5),
                combo(["BB", "BB", "BB", "BB", "BB"], 20),
                combo(["BB", "BB", "BB", "BB", "ANY"], 5),
                combo(["AA", "WC", "WC", "ANY", "ANY"], 7),  # mixed run: skipped
            ]
        ),
        "combo_other": combo(["SC", "SC", "SC", "ANY", "ANY"], 999),
        "tables": table("Orbs_10", [(-5, 1), (100, 10), (50, 39)])
        + table("Orbs_20", [(100, 1)]),
    }
    parts.update(overrides)
    return MATH_XML.format(**parts)


def ways_math_xml(sets: dict[str, list[tuple[str, int]]]) -> str:
    """`math_xml` for a paytable that pays by ways, with a ScatterComboSet of AnywaysCombo per symbol as the GDK
    writes them. `sets` maps a symbol to its combos, each a pattern and a value: ("AA AA AA ANY ANY", 2)."""
    ids = count(1)

    def anyways(pattern: str, value: int) -> str:
        listed = "".join(f"<Symbol>{s}</Symbol>" for s in pattern.split())
        return (
            f"<AnywaysCombo><SymbolList>{listed}</SymbolList><ComboID>{next(ids)}</ComboID>"
            f"<Group>100</Group><Value>{value}</Value><BaseMultiplier>BetPerLine</BaseMultiplier></AnywaysCombo>"
        )

    combo_sets = "".join(
        f"<ScatterComboSet><Identifier>{symbol}Combos</Identifier><ScatterComboList>"
        + "".join(anyways(pattern, value) for pattern, value in combos)
        + "</ScatterComboList></ScatterComboSet>"
        for symbol, combos in sets.items()
    )
    xml = re.sub(r"<ComboSetList>.*</ComboSetList>", f"<ComboSetList>{combo_sets}</ComboSetList>", math_xml(), flags=re.S)
    named = "".join(f"<ComboSet>{symbol}Combos</ComboSet>" for symbol in sets)
    return xml.replace("<ComboSet>PaylineComboSet_Main</ComboSet>", named)


GAME_CFG = """<GameConfig>
  <DisplayGameId>Test 90% Prog:NONE</DisplayGameId>
  <GamePct>91.50</GamePct>
  <GameBasePct>81.25</GameBasePct>
  <MinTotalBet>10</MinTotalBet>
  <NumberOfLines>{lines}</NumberOfLines>
  <DenomConfig><Denom>1</Denom><SpecificMaxBets>10 20</SpecificMaxBets></DenomConfig>
  <DenomConfig><Denom>5</Denom><SpecificMaxBets>20 40 x</SpecificMaxBets></DenomConfig>
</GameConfig>
"""

WIN_GEOMETRY = """<WinGeometryData><PaylineSetList>
  <PaylineSet paylineSetID="5">
    <Payline paylineNumber="0">
      <PaylineElement reelIndex="1" position="1" /><PaylineElement reelIndex="0" position="0" />
    </Payline>
    <Payline paylineNumber="1">
      <PaylineElement reelIndex="0" position="2" /><PaylineElement reelIndex="1" position="2" />
    </Payline>
  </PaylineSet>
  <PaylineSet paylineSetID="3">
    <Payline paylineNumber="0">
      <PaylineElement reelIndex="0" position="1" /><PaylineElement reelIndex="1" position="1" />
    </Payline>
  </PaylineSet>
</PaylineSetList></WinGeometryData>
"""

LOG_LINE = (
    "09/01/26 15:20:44.848 00 TestGame:1 DBG: [WagerGameApp.UpdatePayTable] current denom[100.000] "
    "current paytableId[{paytable}] current supported denoms[1.000,100.000]\n"
)


class World:
    """A fake game install: paytable folder, win geometry, log, and the game's config dict."""

    def __init__(self, root: Path) -> None:
        self.config_dir = root / "GameConfig"
        self.folder = self.config_dir / PAYTABLE
        self.folder.mkdir(parents=True)
        self.geometry = self.config_dir / "winGeometry.xml"
        self.log = root / "TestGame_Client.log"
        self.log.write_text("")
        (self.folder / "math.xml").write_text(math_xml(), encoding="utf-8")
        (self.folder / "gameConfig.cfg").write_text(GAME_CFG.format(lines=5), encoding="utf-8")
        self.geometry.write_text(WIN_GEOMETRY, encoding="utf-8")
        self.config: dict[str, Any] = {
            "name": "TestGame",
            "pay_kind": "lines",
            "simulator": {
                "logs": str(self.log),
                "game_config": str(self.config_dir),
                "win_geometry": str(self.geometry),
            },
            "egm": {"logs": str(root / "egm.log")},
            "symbols": {"WC": "Wild", "AA": "Ace", "BB": "Bell", "CC": "Cherry", "SC": "Scatter"},
            "scatter_symbols": ["SC"],
            "orb_value_tables": [{"title": "Orbs", "table": "Orbs_{bet}"}],
        }

    def touch(self, path: Path) -> None:
        """Makes `path` look modified even if the clock has not moved since it was written."""
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    world = World(tmp_path)
    monkeypatch.setattr(
        game_settings, "load_game_config", lambda game: world.config if game == "TestGame" else None
    )
    return world


@pytest.fixture
def game_context(tmp_path: Path) -> GameContextService:
    games = tmp_path / "games"
    (games / "TestGame").mkdir(parents=True)
    return GameContextService(state_file=tmp_path / "context.json", games_dir=games)


@pytest.fixture
def watcher(game_context: GameContextService, world: World) -> LogWatcher:
    return LogWatcher(lambda: game_settings.active_log_path(game_context))


@pytest.fixture
def service(
    world: World, game_context: GameContextService, watcher: LogWatcher
) -> GameConfigService:
    return GameConfigService(game_context, watcher)


# ------------------------------------------------------------------ summary


def test_summary_comes_from_the_game_config(world: World, service: GameConfigService) -> None:
    summary = service.get_paytable(PAYTABLE).summary

    assert summary.display_name == "Test 90% Prog:NONE"
    assert summary.return_pct == 91.5  # gameConfig.cfg wins over math.xml (90.00)
    assert summary.base_return_pct == 81.25
    assert summary.lines == 5
    assert summary.min_total_bet == 10
    assert summary.max_bets == [10, 20, 40]  # every denom's list together, sorted, junk ignored


def test_the_unlimited_config_is_used_when_there_is_no_plain_one(
    world: World, service: GameConfigService
) -> None:
    (world.folder / "gameConfig.cfg").rename(world.folder / "gameConfig.unlimited.cfg")

    assert service.get_paytable(PAYTABLE).summary.display_name == "Test 90% Prog:NONE"


def test_without_a_game_config_the_math_supplies_what_it_can(
    world: World, service: GameConfigService
) -> None:
    (world.folder / "gameConfig.cfg").unlink()

    result = service.get_paytable(PAYTABLE)

    assert result.summary.display_name is None
    assert result.summary.return_pct == 90.0
    assert result.summary.lines == 5  # math.xml's default payline set
    assert result.summary.min_total_bet == 10  # smallest allowed bet
    assert result.summary.max_bets == [10, 20]
    assert any("gameConfig.cfg" in warning for warning in result.warnings)


# ------------------------------------------------------------------ symbols


def test_symbols_are_named_and_classified(world: World, service: GameConfigService) -> None:
    symbols = {s.code: s for s in service.get_paytable(PAYTABLE).symbols}

    assert symbols["WC"].kind is SymbolKind.WILD  # from math.xml
    assert symbols["SC"].kind is SymbolKind.SCATTER  # from the game's scatter_symbols
    assert symbols["AA"].kind is SymbolKind.REGULAR
    assert symbols["AA"].name == "Ace"


def test_a_symbol_without_a_name_is_shown_by_its_code(
    world: World, service: GameConfigService
) -> None:
    del world.config["symbols"]["CC"]

    symbols = {s.code: s for s in service.get_paytable(PAYTABLE).symbols}

    assert symbols["CC"].name == "CC"


# ------------------------------------------------------------------ payline combos


def test_symbols_that_pay_alike_share_a_row_and_the_best_row_comes_first(
    world: World, service: GameConfigService
) -> None:
    combos = service.get_paytable(PAYTABLE).payline_combos

    assert combos is not None
    assert combos.lengths == [5, 4]
    assert [(row.symbols, row.payouts) for row in combos.rows] == [
        (["WC"], [100, 50]),
        (["AA", "BB"], [20, 5]),  # in symbol set order
        (["CC"], [20, None]),  # only pays for five
    ]


def test_mixed_symbol_combos_are_left_out_with_a_warning(
    world: World, service: GameConfigService
) -> None:
    result = service.get_paytable(PAYTABLE)

    assert any("1 payline combos" in warning for warning in result.warnings)


def test_only_the_combo_set_of_the_default_paytable_is_used(
    world: World, service: GameConfigService
) -> None:
    combos = service.get_paytable(PAYTABLE).payline_combos

    assert combos is not None
    assert all("SC" not in row.symbols for row in combos.rows)


def test_pay_rules_keep_every_combo_in_file_order_with_its_id(
    world: World, service: GameConfigService
) -> None:
    (world.folder / "math.xml").write_text(
        math_xml(
            combos="".join(
                [
                    combo(["AA", "AA", "AA", "AA", "ANY"], 5, combo_id=8),
                    combo(["AA", "WC", "WC", "ANY", "ANY"], 7, combo_id=9),  # mixed: not in the rows
                    combo(["CC", "CC", "CC", "CC", "CC"], 20),
                ]
            )
        ),
        encoding="utf-8",
    )

    rules = service.get_paytable(PAYTABLE).pay_rules

    assert rules is not None
    # The ANY padding is dropped, so a combo's length is its run length; a combo without a ComboID has no id.
    assert [(c.id, c.symbols, c.value) for c in rules.combos] == [
        (8, ["AA", "AA", "AA", "AA"], 5),
        (9, ["AA", "WC", "WC"], 7),
        (None, ["CC", "CC", "CC", "CC", "CC"], 20),
    ]


def test_pay_rules_name_the_symbols_each_wild_stands_in_for(
    world: World, service: GameConfigService
) -> None:
    listed = "".join(f"<Symbol>{s}</Symbol>" for s in ("CC", "AA"))
    math = math_xml().replace(
        "<Identifier>WC</Identifier></WildSymbol>",
        f"<Identifier>WC</Identifier><SymbolList>{listed}</SymbolList></WildSymbol>",
    )
    (world.folder / "math.xml").write_text(math, encoding="utf-8")

    rules = service.get_paytable(PAYTABLE).pay_rules

    assert rules is not None
    assert [(w.code, w.substitutes) for w in rules.wilds] == [("WC", ["AA", "CC"])]


def test_a_wild_without_a_symbol_list_stands_in_for_nothing(
    world: World, service: GameConfigService
) -> None:
    rules = service.get_paytable(PAYTABLE).pay_rules

    assert rules is not None
    assert [(w.code, w.substitutes) for w in rules.wilds] == [("WC", [])]


def test_a_paytable_without_combos_has_no_pay_rules(world: World, service: GameConfigService) -> None:
    (world.folder / "math.xml").write_text(math_xml(combos=""), encoding="utf-8")

    assert service.get_paytable(PAYTABLE).pay_rules is None


def test_the_pay_kind_is_the_one_the_game_config_states(world: World, service: GameConfigService) -> None:
    assert service.get_paytable(PAYTABLE).pay_kind == "lines"


@pytest.mark.parametrize("kind", [None, "", "payways", 243])
def test_a_game_must_state_whether_it_pays_by_lines_or_by_ways(
    world: World, service: GameConfigService, kind: object
) -> None:
    world.config["pay_kind"] = kind
    if kind is None:
        del world.config["pay_kind"]

    with pytest.raises(AppException) as raised:
        service.get_paytable(PAYTABLE)

    assert raised.value.error_code == "CONFIG_INVALID"
    assert "pay_kind" in str(raised.value) and "TestGame" in str(raised.value)


def test_a_game_that_pays_by_lines_does_not_read_ways_combos(
    world: World, service: GameConfigService
) -> None:
    (world.folder / "math.xml").write_text(ways_math_xml({"AA": [("AA AA AA ANY ANY", 2)]}), encoding="utf-8")

    result = service.get_paytable(PAYTABLE)

    assert result.pay_kind == "lines"
    assert result.pay_rules is None and result.payline_combos is None
    assert any("pay_kind 'lines'" in w and "ways combos" in w for w in result.warnings)


def test_a_game_that_pays_by_ways_does_not_read_payline_combos(
    world: World, service: GameConfigService
) -> None:
    world.config["pay_kind"] = "ways"

    result = service.get_paytable(PAYTABLE)  # the default math.xml holds payline combos only

    assert result.pay_kind == "ways"
    assert result.pay_rules is None and result.payline_combos is None
    assert any("pay_kind 'ways'" in w and "lines combos" in w for w in result.warnings)


def test_a_ways_paytable_reads_the_anyways_combos_of_every_combo_set_it_names(
    world: World, service: GameConfigService
) -> None:
    xml = ways_math_xml(
        {
            "AA": [("AA AA AA AA AA", 20), ("AA AA AA ANY ANY", 2)],
            "BB": [("BB BB BB ANY ANY", 3)],
        }
    )
    # A combo set the paytable does not name pays nothing.
    unused = "<ScatterComboSet><Identifier>Other</Identifier><ScatterComboList><AnywaysCombo><SymbolList>"
    unused += "<Symbol>CC</Symbol></SymbolList><Value>9</Value></AnywaysCombo></ScatterComboList></ScatterComboSet>"
    (world.folder / "math.xml").write_text(xml.replace("</ComboSetList>", f"{unused}</ComboSetList>"), encoding="utf-8")
    world.config["pay_kind"] = "ways"

    result = service.get_paytable(PAYTABLE)

    assert result.pay_kind == "ways" and result.pay_rules is not None
    assert not any("pay_kind" in w for w in result.warnings)
    # The ANY padding is dropped, so a combo's length is its run length.
    assert [(c.id, c.symbols, c.value) for c in result.pay_rules.combos] == [
        (1, ["AA"] * 5, 20),
        (2, ["AA"] * 3, 2),
        (3, ["BB"] * 3, 3),
    ]
    # The Game Config tab shows what each symbol pays by run length, the same as for lines.
    assert result.payline_combos is not None
    assert result.payline_combos.lengths == [5, 3]
    assert [(row.symbols, row.payouts) for row in result.payline_combos.rows] == [
        (["AA"], [20, 2]),
        (["BB"], [None, 3]),
    ]


# ------------------------------------------------------------------ win geometry


def test_win_geometry_lists_every_set_and_marks_the_one_in_play(
    world: World, service: GameConfigService
) -> None:
    geometry = service.get_paytable(PAYTABLE).win_geometry

    assert geometry is not None
    assert geometry.file == str(world.geometry)
    assert geometry.active_set == 5
    assert [payline_set.id for payline_set in geometry.sets] == [5, 3]
    # Elements are ordered by reel, whatever order the file lists them in.
    assert geometry.sets[0].lines == [[0, 1], [2, 2]]
    assert (geometry.reels, geometry.rows) == (2, 3)


def test_the_number_of_lines_selects_the_set_in_play(
    world: World, service: GameConfigService
) -> None:
    (world.folder / "gameConfig.cfg").write_text(GAME_CFG.format(lines=3), encoding="utf-8")

    assert service.get_paytable(PAYTABLE).win_geometry.active_set == 3


def test_no_set_is_in_play_when_the_file_has_none_for_the_lines(
    world: World, service: GameConfigService
) -> None:
    (world.folder / "gameConfig.cfg").write_text(GAME_CFG.format(lines=99), encoding="utf-8")
    text = (world.folder / "math.xml").read_text().replace(
        "<PaylineSetID>5<", "<PaylineSetID>98<"
    )
    (world.folder / "math.xml").write_text(text, encoding="utf-8")

    assert service.get_paytable(PAYTABLE).win_geometry.active_set is None


def test_a_missing_win_geometry_file_only_loses_that_section(
    world: World, service: GameConfigService
) -> None:
    world.geometry.unlink()

    result = service.get_paytable(PAYTABLE)

    assert result.win_geometry is None
    assert result.payline_combos is not None
    assert any("Win geometry" in warning for warning in result.warnings)


def test_a_game_without_a_win_geometry_setting_only_loses_that_section(
    world: World, service: GameConfigService
) -> None:
    del world.config["simulator"]["win_geometry"]

    result = service.get_paytable(PAYTABLE)

    assert result.win_geometry is None
    assert any("win_geometry" in warning for warning in result.warnings)


# ------------------------------------------------------------------ reel strips


def test_reel_strips_are_sent_once_and_sets_refer_to_them(
    world: World, service: GameConfigService
) -> None:
    result = service.get_paytable(PAYTABLE)

    assert [strip.id for strip in result.reel_strips] == ["Strip_A", "Strip_B"]
    assert result.default_reel_strip_set == "Reels_BG_0"
    base, bonus = result.reel_strip_sets
    assert (base.id, base.label, base.visible_rows, base.strip_ids) == (
        "Reels_BG_0",
        "base game",
        3,
        ["Strip_A", "Strip_B"],
    )
    # Ids may repeat; ones with no strip are dropped.
    assert (bonus.label, bonus.strip_ids) == (None, ["Strip_B", "Strip_B"])


def test_every_stop_comes_with_its_weight(world: World, service: GameConfigService) -> None:
    strips = {s.id: s for s in service.get_paytable(PAYTABLE).reel_strips}

    assert strips["Strip_A"].stops == ["AA", "BB", "WC"]
    assert strips["Strip_A"].weights == [10, 10, 10]
    assert strips["Strip_B"].weights == [5, 1, 3]


# ------------------------------------------------------------------ orb values


def test_orb_tables_are_picked_by_the_minimum_bet(world: World, service: GameConfigService) -> None:
    (table,) = service.get_paytable(PAYTABLE).orb_tables

    assert (table.title, table.table, table.bet) == ("Orbs", "Orbs_10", 10)
    assert table.total_weight == 50


def test_orb_values_have_probabilities_and_jackpots_come_last(
    world: World, service: GameConfigService
) -> None:
    (table,) = service.get_paytable(PAYTABLE).orb_tables

    assert [(v.label, v.jackpot) for v in table.values] == [
        ("100", False),
        ("50", False),
        ("JP5", True),
    ]
    assert [v.weight for v in table.values] == [10, 39, 1]
    assert table.values[0].probability == pytest.approx(0.2)
    assert sum(v.probability for v in table.values) == pytest.approx(1.0)


def test_an_orb_table_the_math_does_not_have_is_reported(
    world: World, service: GameConfigService
) -> None:
    world.config["orb_value_tables"].append({"title": "More", "table": "Nope_{bet}"})

    result = service.get_paytable(PAYTABLE)

    assert [t.title for t in result.orb_tables] == ["Orbs"]
    assert any("Nope_10" in warning for warning in result.warnings)


def test_a_game_without_orb_tables_has_none(world: World, service: GameConfigService) -> None:
    del world.config["orb_value_tables"]

    assert service.get_paytable(PAYTABLE).orb_tables == []


# ------------------------------------------------------------------ files, cache, errors


def test_a_paytable_is_built_once_until_a_file_changes(
    world: World, service: GameConfigService
) -> None:
    first = service.get_paytable(PAYTABLE)
    assert service.get_paytable(PAYTABLE) is first

    (world.folder / "gameConfig.cfg").write_text(GAME_CFG.format(lines=3), encoding="utf-8")
    world.touch(world.folder / "gameConfig.cfg")
    second = service.get_paytable(PAYTABLE)

    assert second is not first
    assert second.summary.lines == 3


def test_a_changed_win_geometry_file_rebuilds_the_paytable(
    world: World, service: GameConfigService
) -> None:
    first = service.get_paytable(PAYTABLE)

    world.geometry.write_text(WIN_GEOMETRY.replace('paylineSetID="3"', 'paylineSetID="4"'))
    world.touch(world.geometry)

    assert [s.id for s in service.get_paytable(PAYTABLE).win_geometry.sets] == [5, 4]
    assert first.win_geometry.sets[1].id == 3


def test_the_least_recently_used_paytables_are_dropped(
    world: World, service: GameConfigService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.game_config_service._MAX_CACHED", 2)
    for name in ("PT-1", "PT-2", "PT-3"):
        (world.config_dir / name).mkdir()
        (world.config_dir / name / "math.xml").write_text(math_xml(), encoding="utf-8")

    first = service.get_paytable("PT-1")
    service.get_paytable("PT-2")
    service.get_paytable("PT-3")

    assert service.get_paytable("PT-1") is not first


def test_an_unknown_paytable_is_not_found(world: World, service: GameConfigService) -> None:
    with pytest.raises(NotFoundException, match="Nope"):
        service.get_paytable("Nope")


@pytest.mark.parametrize("bad", ["..", ".", "a/b", "a\\b", "..\\..\\x", "x y", ""])
def test_a_paytable_id_cannot_leave_the_game_config_folder(
    world: World, service: GameConfigService, bad: str
) -> None:
    with pytest.raises(BadRequestException):
        service.get_paytable(bad)


def test_a_math_file_that_is_not_xml_is_reported_as_invalid_config(
    world: World, service: GameConfigService
) -> None:
    (world.folder / "math.xml").write_text("<GameMath><oops>")

    with pytest.raises(AppException) as raised:
        service.get_paytable(PAYTABLE)

    assert raised.value.error_code == "CONFIG_INVALID"


def test_a_game_without_a_game_config_folder_for_the_mode_is_not_found(
    world: World, service: GameConfigService, game_context: GameContextService
) -> None:
    game_context.update_context(GameContextUpdate(mode=GameMode.EGM))  # config only has a log

    with pytest.raises(NotFoundException, match="game_config"):
        service.get_paytable(PAYTABLE)
    with pytest.raises(NotFoundException, match="game_config"):
        service.list_paytables()


def test_an_unreachable_config_folder_is_reported_as_unavailable(
    world: World, service: GameConfigService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(*args: object, **kwargs: object) -> None:
        raise OSError("The network path was not found")

    monkeypatch.setattr(os, "scandir", unreachable)

    with pytest.raises(ServiceUnavailableException, match="network path"):
        service.list_paytables()


def test_the_game_and_mode_can_be_named_instead_of_using_the_selection(
    world: World, service: GameConfigService, game_context: GameContextService
) -> None:
    # The selection is EGM, which has no game_config, but the caller asks for the simulator.
    game_context.update_context(GameContextUpdate(mode=GameMode.EGM))

    result = service.get_paytable(PAYTABLE, "TestGame", GameMode.SIMULATOR)

    assert (result.game, result.mode) == ("TestGame", GameMode.SIMULATOR)
    assert service.list_paytables("TestGame", GameMode.SIMULATOR).paytables == [PAYTABLE]


def test_an_unknown_game_is_not_found(world: World, service: GameConfigService) -> None:
    with pytest.raises(NotFoundException, match="Other"):
        service.get_paytable(PAYTABLE, "Other", GameMode.SIMULATOR)


def test_list_paytables_returns_the_folders_only(world: World, service: GameConfigService) -> None:
    (world.config_dir / "Another-PT").mkdir()

    result = service.list_paytables()

    assert result.paytables == ["Another-PT", PAYTABLE]  # winGeometry.xml is not one
    assert result.directory == str(world.config_dir)


# ------------------------------------------------------------------ current paytable


def test_current_reports_what_the_log_says(
    world: World, service: GameConfigService, watcher: LogWatcher
) -> None:
    world.log.write_text(LOG_LINE.format(paytable=PAYTABLE))
    watcher.poll()
    watcher.poll()

    current = service.current()

    assert current.game == "TestGame"
    assert current.mode is GameMode.SIMULATOR
    assert current.log_path == str(world.log)
    assert current.log_unreadable is False
    assert current.paytable_id == PAYTABLE
    assert current.denom == 100.0
    assert current.supported_denoms == [1.0, 100.0]


def test_current_has_no_paytable_until_the_log_reports_one(
    world: World, service: GameConfigService, watcher: LogWatcher
) -> None:
    assert service.current().paytable_id is None  # watcher has not looked yet

    watcher.poll()
    watcher.poll()

    current = service.current()
    assert current.paytable_id is None
    assert current.log_unreadable is False


def test_current_follows_the_paytable_as_the_log_changes(
    world: World, service: GameConfigService, watcher: LogWatcher
) -> None:
    watcher.poll()
    watcher.poll()
    with world.log.open("a") as log:
        log.write(LOG_LINE.format(paytable="PT-A"))
    watcher.poll()
    assert service.current().paytable_id == "PT-A"

    with world.log.open("a") as log:
        log.write(LOG_LINE.format(paytable="PT-B"))
    watcher.poll()
    assert service.current().paytable_id == "PT-B"


def test_current_flags_a_log_that_cannot_be_read(
    world: World, service: GameConfigService, watcher: LogWatcher
) -> None:
    world.log.unlink()
    watcher.poll()
    watcher.poll()

    current = service.current()

    assert current.log_unreadable is True
    assert current.paytable_id is None


def test_current_ignores_a_watcher_that_is_still_on_the_previous_log(
    world: World, service: GameConfigService, watcher: LogWatcher, game_context: GameContextService
) -> None:
    world.log.write_text(LOG_LINE.format(paytable=PAYTABLE))
    watcher.poll()
    watcher.poll()
    assert service.current().paytable_id == PAYTABLE

    # The selection moves to EGM mode, but the watcher has not caught up yet.
    game_context.update_context(GameContextUpdate(mode=GameMode.EGM))
    current = service.current()

    assert current.mode is GameMode.EGM
    assert current.paytable_id is None
    assert current.log_unreadable is False


def test_current_without_a_log_path_says_so(world: World, service: GameConfigService) -> None:
    del world.config["simulator"]["logs"]

    current = service.current()

    assert current.log_path is None
    assert current.paytable_id is None


# ------------------------------------------------------------------ API


@pytest.fixture
def api(service: GameConfigService) -> TestClient:
    controller = GameConfigController(service)
    app.dependency_overrides[get_game_config_controller] = lambda: controller
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_current(world: World, api: TestClient, watcher: LogWatcher) -> None:
    world.log.write_text(LOG_LINE.format(paytable=PAYTABLE))
    watcher.poll()
    watcher.poll()

    body = api.get("/api/v1/game-config/current").json()

    assert body["success"] is True
    assert body["data"]["paytable_id"] == PAYTABLE
    assert body["data"]["mode"] == "simulator"
    assert body["data"]["supported_denoms"] == [1.0, 100.0]


def test_api_paytable_list_and_detail(world: World, api: TestClient) -> None:
    listing = api.get("/api/v1/game-config/paytables").json()["data"]
    assert listing["paytables"] == [PAYTABLE]

    detail = api.get(f"/api/v1/game-config/paytables/{PAYTABLE}").json()["data"]
    assert detail["paytable_id"] == PAYTABLE
    assert detail["summary"]["lines"] == 5
    assert detail["win_geometry"]["active_set"] == 5
    assert detail["payline_combos"]["lengths"] == [5, 4]
    assert detail["orb_tables"][0]["values"][0]["label"] == "100"


def test_api_game_and_mode_are_optional_query_parameters(world: World, api: TestClient) -> None:
    url = f"/api/v1/game-config/paytables/{PAYTABLE}"

    assert api.get(url, params={"game": "TestGame", "mode": "simulator"}).status_code == 200
    assert api.get(url, params={"game": "Other"}).status_code == 404
    assert api.get(url, params={"mode": "nonsense"}).status_code == 422


def test_api_unknown_paytable_uses_the_error_envelope(world: World, api: TestClient) -> None:
    response = api.get("/api/v1/game-config/paytables/Nope")

    assert response.status_code == 404
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_api_rejects_a_paytable_id_that_is_not_a_folder_name(world: World, api: TestClient) -> None:
    assert api.get("/api/v1/game-config/paytables/a b").status_code == 400
