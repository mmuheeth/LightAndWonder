import json
from pathlib import Path

import pytest

from app.utils import game_config as game_settings
from app.utils.gaf_objects import COMMON_DIR, ObjectQueryError, load_object_queries

BACKEND_DIR = Path(__file__).resolve().parents[1]
GAME_TYPE = "TestStyle"


def write(path: Path, content: dict | str, encoding: str = "utf-8") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding=encoding)
    return path


@pytest.fixture
def common(tmp_path: Path) -> Path:
    """A small common base with two files per dictionary."""
    base = tmp_path / "common" / GAME_TYPE
    write(
        base / "general" / "a.json",
        {
            "MeterQuery": {"Credit": {"id": "credit"}, "Win": {"id": "win"}},
            "ButtonQuery": {"Spin": 12, "TakeWin": {"id": "take"}},
        },
    )
    write(base / "general" / "b.json", {"DenomQuery": {"Change": {"id": "denom"}}})
    write(base / "generic" / "a.json", {"IDeck_Collect": {"id": "collect"}})
    write(base / "generic" / "b.json", {"MessageArea1": {"id": "msg"}})
    return tmp_path / "common"


# ------------------------------------------------------------------------------ the base


def test_the_base_is_every_file_of_each_dictionary_merged(common: Path) -> None:
    queries = load_object_queries(GAME_TYPE, None, common)

    assert set(queries.general) == {"MeterQuery", "ButtonQuery", "DenomQuery"}
    assert set(queries.generic) == {"IDeck_Collect", "MessageArea1"}


def test_files_are_read_with_their_bom(common: Path) -> None:
    write(common / GAME_TYPE / "generic" / "bom.json", {"WithBom": {"id": "x"}}, encoding="utf-8-sig")

    assert "WithBom" in load_object_queries(GAME_TYPE, None, common).generic


def test_a_later_file_wins_over_an_earlier_one(common: Path) -> None:
    write(common / GAME_TYPE / "generic" / "z.json", {"IDeck_Collect": {"id": "replaced"}})

    assert load_object_queries(GAME_TYPE, None, common).generic["IDeck_Collect"] == {"id": "replaced"}


# ------------------------------------------------------------------------------ overrides


def test_an_override_changes_one_entry_of_a_section_and_keeps_the_rest(
    common: Path, tmp_path: Path
) -> None:
    override = write(tmp_path / "game.json", {"MeterQuery": {"Credit": {"id": "game-credit"}}})

    general = load_object_queries(GAME_TYPE, override, common).general

    assert general["MeterQuery"] == {"Credit": {"id": "game-credit"}, "Win": {"id": "win"}}


def test_an_override_reaches_into_nested_objects(common: Path, tmp_path: Path) -> None:
    override = write(tmp_path / "game.json", {"ButtonQuery": {"TakeWin": {"extra": True}}})

    general = load_object_queries(GAME_TYPE, override, common).general

    assert general["ButtonQuery"]["TakeWin"] == {"id": "take", "extra": True}
    assert general["ButtonQuery"]["Spin"] == 12


def test_a_value_that_is_not_an_object_replaces_instead_of_merging(
    common: Path, tmp_path: Path
) -> None:
    override = write(tmp_path / "game.json", {"ButtonQuery": {"Spin": 5, "TakeWin": None}})

    general = load_object_queries(GAME_TYPE, override, common).general

    assert general["ButtonQuery"] == {"Spin": 5, "TakeWin": None}


def test_entries_go_to_the_dictionary_whose_base_has_them(common: Path, tmp_path: Path) -> None:
    override = write(
        tmp_path / "game.json",
        {"DenomQuery": {"Change": {"id": "g"}}, "IDeck_Collect": {"id": "g2"}},
    )

    queries = load_object_queries(GAME_TYPE, override, common)

    assert queries.general["DenomQuery"]["Change"] == {"id": "g"}
    assert "IDeck_Collect" not in queries.general
    assert queries.generic["IDeck_Collect"] == {"id": "g2"}
    assert "DenomQuery" not in queries.generic


def test_a_new_entry_is_a_named_object_of_the_generic_dictionary(
    common: Path, tmp_path: Path
) -> None:
    override = write(tmp_path / "game.json", {"BrandNewButton": {"id": "new"}})

    queries = load_object_queries(GAME_TYPE, override, common)

    assert queries.generic["BrandNewButton"] == {"id": "new"}
    assert "BrandNewButton" not in queries.general


def test_the_base_is_not_changed_by_an_override(common: Path, tmp_path: Path) -> None:
    override = write(tmp_path / "game.json", {"MeterQuery": {"Credit": {"id": "other"}}})

    load_object_queries(GAME_TYPE, override, common)

    assert load_object_queries(GAME_TYPE, None, common).general["MeterQuery"]["Credit"] == {"id": "credit"}


@pytest.mark.parametrize("content", ["", "  \n\t\n", "{}"])
def test_an_empty_override_leaves_the_base_alone(common: Path, tmp_path: Path, content: str) -> None:
    override = write(tmp_path / "game.json", content)

    assert load_object_queries(GAME_TYPE, override, common) == load_object_queries(GAME_TYPE, None, common)


# ---------------------------------------------------------------------------------- errors


def test_an_override_that_is_not_json_names_the_file(common: Path, tmp_path: Path) -> None:
    override = write(tmp_path / "game.json", "{not json")

    with pytest.raises(ObjectQueryError, match="game.json is not valid JSON"):
        load_object_queries(GAME_TYPE, override, common)


def test_an_override_that_is_not_an_object_is_rejected(common: Path, tmp_path: Path) -> None:
    override = write(tmp_path / "game.json", "[1, 2]")

    with pytest.raises(ObjectQueryError, match="must hold a JSON object, not list"):
        load_object_queries(GAME_TYPE, override, common)


def test_a_missing_override_file_is_reported(common: Path, tmp_path: Path) -> None:
    with pytest.raises(ObjectQueryError, match="Cannot read"):
        load_object_queries(GAME_TYPE, tmp_path / "nope.json", common)


def test_a_broken_base_file_names_the_file(common: Path) -> None:
    write(common / GAME_TYPE / "general" / "broken.json", "{")

    with pytest.raises(ObjectQueryError, match="broken.json is not valid JSON"):
        load_object_queries(GAME_TYPE, None, common)


def test_an_unknown_game_type_has_no_base(common: Path) -> None:
    with pytest.raises(ObjectQueryError, match="No object query files"):
        load_object_queries("OtherStyle", None, common)


def test_a_dictionary_without_files_is_an_error_not_an_empty_dictionary(common: Path) -> None:
    for file in (common / GAME_TYPE / "generic").glob("*.json"):
        file.unlink()

    with pytest.raises(ObjectQueryError, match="No object query files"):
        load_object_queries(GAME_TYPE, None, common)


@pytest.mark.parametrize("game_type", ["../escape", "a/b", "", "with space", "1abc"])
def test_a_game_type_cannot_leave_the_common_folder(common: Path, game_type: str) -> None:
    with pytest.raises(ObjectQueryError, match="not a valid game type"):
        load_object_queries(game_type, None, common)


# ----------------------------------------------------------------------- the shipped files


def test_the_shipped_base_of_ballystyle_is_complete_and_its_two_halves_do_not_overlap() -> None:
    queries = load_object_queries("BallyStyle", None)

    # The sections InitializeGameClient looks entries up in, and named objects of the generic one.
    assert {"NonWagerIDeckButtonQuery", "IDeckWagerButtonQuery", "PlayerInfoMeterQuery"} <= set(
        queries.general
    )
    assert {"DenomQuery", "ReelSets", "WagerSaverQuery", "DemoMenuNew"} <= set(queries.general)
    assert {"IDeck_CollectButton", "DenomChangeButton", "ProgressiveManager"} <= set(queries.generic)
    assert not set(queries.general) & set(queries.generic)


def test_the_shipped_files_live_next_to_the_games() -> None:
    assert COMMON_DIR == BACKEND_DIR / "app" / "games" / "_common" / "gaf"
    assert (COMMON_DIR / "BallyStyle" / "general").is_dir()


@pytest.mark.parametrize("game", ["FortuneOx", "HuffNPuffHighRise"])
def test_every_game_with_gaf_config_loads_its_object_queries(game: str) -> None:
    gaf = game_settings.load_game_config(game)["gaf"]

    queries = load_object_queries(gaf["game_type"], BACKEND_DIR / gaf["object_query_root"])

    assert queries.general and queries.generic
