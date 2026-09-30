"""The GAF tab's API: session, status, and every action, against a fake NRobot with a game behind it."""

import copy
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import BACKEND_DIR, get_gaf_controller
from app.controllers.gaf_controller import GafController
from app.main import app
from app.schemas.game_context import GameContextUpdate, GameMode
from app.services import gaf_service
from app.services.game_context_service import GameContextService
from app.services.gaf_service import GafService
from app.utils import game_config as game_settings
from app.utils.nrobot import NRobot
from tests.fake_gaf import FakeGaf

URL = "/api/v1/gaf"
COMMON = ["spin", "game_state", "active_denom", "available_denoms", "meters"]
GAME_SPECIFIC = ["take_win", "gamble", "toggle_credit_meter", "front_panel_messages", "unique_front_panel_messages"]
FORTUNE_OX_ACTIONS = [*COMMON, *GAME_SPECIFIC]


def make_service(fake: FakeGaf, context: GameContextService, settle_timeout: float = 1.0) -> GafService:
    return GafService(
        nrobot=NRobot(fake.url, timeout=5),
        probe_nrobot=NRobot(fake.url, timeout=0.3),
        game_context=context,
        base_dir=BACKEND_DIR,
        settle_timeout=settle_timeout,
        connect_attempts=3,
        connect_retry_delay=0.01,
    )


@pytest.fixture
def gaf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Real waits are seconds; the fake game answers at once, so the polls can be fast. A wait that is
    # expected to succeed keeps a generous limit, because on a loaded machine scheduling alone can eat
    # 0.1s of wall-clock time; only the tests that expect a wait to give up shorten it.
    monkeypatch.setattr(gaf_service, "_POLL_INTERVAL", 0.001)
    monkeypatch.setattr(gaf_service, "_DEPARTURE_TIMEOUT", 2.0)
    monkeypatch.setattr(gaf_service, "_COLLECT_TIMEOUT", 0.1)
    monkeypatch.setattr(gaf_service, "_METER_TIMEOUT", 0.1)
    fake = FakeGaf()
    context = GameContextService(state_file=tmp_path / "game_context.json")
    context.update_context(GameContextUpdate(game="FortuneOx", mode=GameMode.SIMULATOR))
    service = make_service(fake, context)
    app.dependency_overrides[get_gaf_controller] = lambda: GafController(service)
    yield SimpleNamespace(fake=fake, service=service, context=context, client=TestClient(app))
    app.dependency_overrides.clear()
    fake.close()


@pytest.fixture
def connected(gaf) -> SimpleNamespace:
    assert connect(gaf).status_code == 200
    return gaf


def connect(gaf, **params):
    return gaf.client.post(f"{URL}/connect", params=params)


def status(gaf, **params) -> dict:
    response = gaf.client.get(f"{URL}/status", params=params)
    assert response.status_code == 200
    return response.json()["data"]


def act(gaf, action: str, **params):
    return gaf.client.post(f"{URL}/actions/{action}", params=params)


def act_with(gaf, action: str, **inputs):
    """Runs an action with the inputs the UI would send in the request body."""
    return gaf.client.post(f"{URL}/actions/{action}", json={"params": inputs})


def result(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()["data"]


def refused(response, status_code: int, code: str) -> dict:
    assert response.status_code == status_code, response.text
    error = response.json()["error"]
    assert error["code"] == code
    return error


def patch_config(monkeypatch: pytest.MonkeyPatch, edit) -> None:
    real = game_settings.load_game_config

    def load(game: str):
        config = copy.deepcopy(real(game))
        if config is not None:
            edit(config)
        return config

    monkeypatch.setattr(game_settings, "load_game_config", load)


# ---------------------------------------------------------------------------- actions catalog


def test_fortune_ox_offers_the_common_actions_and_its_own(gaf) -> None:
    listed = gaf.client.get(f"{URL}/actions").json()["data"]

    assert [a["id"] for a in listed] == FORTUNE_OX_ACTIONS
    assert {a["id"]: a["scope"] for a in listed} == {**{c: "common" for c in COMMON}, **{g: "game" for g in GAME_SPECIFIC}}
    assert all(a["label"] and a["description"] for a in listed)


def test_a_game_that_lists_no_actions_gets_only_the_common_ones(gaf) -> None:
    listed = gaf.client.get(f"{URL}/actions", params={"game": "HuffNPuffHighRise"}).json()["data"]

    assert [a["id"] for a in listed] == COMMON


def test_a_game_without_a_gaf_config_has_no_actions(gaf, monkeypatch) -> None:
    patch_config(monkeypatch, lambda config: config.pop("gaf"))

    assert gaf.client.get(f"{URL}/actions").json()["data"] == []
    refused(act(gaf, "spin"), 404, "NOT_FOUND")


def test_actions_the_config_lists_but_do_not_exist_are_left_out(gaf, monkeypatch) -> None:
    patch_config(monkeypatch, lambda config: config["gaf"].update(actions=["take_win", "fly_to_the_moon"]))

    listed = gaf.client.get(f"{URL}/actions").json()["data"]

    assert [a["id"] for a in listed] == [*COMMON, "take_win"]


# ------------------------------------------------------------------------------------ status


def test_status_before_connecting(gaf) -> None:
    data = status(gaf)

    assert data["game"] == "FortuneOx" and data["mode"] == "simulator"
    assert data["target"] == "127.0.0.1:9090"
    assert data["nrobot_url"] == gaf.fake.url
    assert (data["reachable"], data["connected"], data["state"], data["detail"]) == (True, False, None, None)


def test_status_follows_the_mode_asked_for(gaf) -> None:
    data = status(gaf, mode="egm")

    assert data["mode"] == "egm"
    assert data["target"] == "10.2.168.252:9090"


def test_status_says_when_nrobot_is_not_running(gaf) -> None:
    gaf.fake.close()

    data = status(gaf)

    assert (data["reachable"], data["connected"]) == (False, False)
    assert "NRobot" in data["detail"]


def test_a_stalled_nrobot_answers_the_status_poll_quickly_instead_of_hanging(connected) -> None:
    # NRobot blocks for 10-20s when the game drops its link and it reconnects. The UI polls status with
    # a 10s timeout of its own, so the poll has to give up first, and say it is a stall, not a dead NRobot.
    connected.fake.delay["GETCURRENTSTATE"] = 1.5
    started = time.monotonic()

    data = status(connected)

    assert time.monotonic() - started < 1.0
    assert (data["reachable"], data["connected"]) == (False, False)
    assert "did not answer in time" in data["detail"] and "reconnecting" in data["detail"]
    assert "NRobot.Server.exe" not in data["detail"]


def test_the_session_survives_a_stall_and_is_connected_again_once_nrobot_answers(connected) -> None:
    connected.fake.delay["GETCURRENTSTATE"] = 1.5
    assert status(connected)["connected"] is False

    connected.fake.delay.clear()
    data = status(connected)

    assert (data["connected"], data["state"]) == (True, "stateIdleWithCredits")
    assert len(connected.fake.keywords("CONNECTGAMECLIENTTOSERVER")) == 1  # no reconnect needed


def test_concurrent_polls_share_one_probe_instead_of_piling_up_on_nrobot(connected) -> None:
    connected.fake.delay["GETCURRENTSTATE"] = 0.25
    polls, barrier, answers = 8, threading.Barrier(8), []
    before = len(connected.fake.keywords("GETCURRENTSTATE"))

    def poll() -> None:
        barrier.wait()
        answers.append(connected.service._status(None, None))

    threads = [threading.Thread(target=poll) for _ in range(polls)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert len(answers) == polls and all(a.connected for a in answers)
    assert len(connected.fake.keywords("GETCURRENTSTATE")) - before <= 2


def test_a_poll_after_another_finished_asks_again(connected) -> None:
    assert status(connected)["state"] == "stateIdleWithCredits"
    connected.fake.idle_state = "stateDisabled"

    assert status(connected)["state"] == "stateDisabled"  # a shared answer is only for polls that overlap


def test_a_keyword_that_times_out_mid_action_is_reported_as_a_stall(connected) -> None:
    connected.service._nrobot = NRobot(connected.fake.url, timeout=0.3)
    connected.fake.delay["GETCURRENTACTIVEDENOM"] = 1.5

    error = refused(act(connected, "active_denom"), 503, "GAF_UNREACHABLE")

    assert "did not answer in time" in error["message"]


def test_status_reports_a_broken_game_config_instead_of_failing(gaf, monkeypatch) -> None:
    patch_config(monkeypatch, lambda config: config["simulator"].pop("host"))

    data = status(gaf)

    assert data["target"] is None
    assert data["reachable"] is True
    assert "invalid" in data["detail"]


def test_status_for_a_game_without_gaf_says_so(gaf, monkeypatch) -> None:
    patch_config(monkeypatch, lambda config: config.pop("gaf"))

    data = status(gaf)

    assert data["target"] is None
    assert "no GAF config" in data["detail"]


# --------------------------------------------------------------------------------- connecting


def test_connect_opens_a_session_the_game_accepts(gaf) -> None:
    data = connect(gaf).json()["data"]

    assert (data["connected"], data["state"], data["detail"]) == (True, "stateIdleWithCredits", None)
    assert gaf.fake.session_open
    assert gaf.fake.keywords("CONNECTGAMECLIENTTOSERVER") == [["127.0.0.1", "9090"]]
    assert gaf.fake.game_type == "BallyStyle"
    assert gaf.fake.gdk_version == "12"


def test_connect_sends_the_games_own_mappings_on_top_of_the_common_base(gaf) -> None:
    connect(gaf)

    general = gaf.fake.general
    assert general["IDeckWagerButtonQuery"]["MechanicalSpinBtnID"] == 12
    assert general["NonWagerIDeckButtonQuery"]["TakeWinButton"]["GameObjectIdentifier"] == "TakeWinButton"
    assert general["PlayerInfoMeterQuery"]["CreditMeter"]["GameObjectIdentifier"] == "Meter_CashCredit"
    # Both initialisers are needed: the denomination keywords use the generic client.
    assert gaf.fake.generic


def test_connect_retries_while_the_game_is_not_accepting_yet(gaf) -> None:
    gaf.fake.connect_failures = 2

    assert connect(gaf).json()["data"]["connected"] is True
    assert len(gaf.fake.keywords("CONNECTGAMECLIENTTOSERVER")) == 3


def test_connect_gives_up_after_its_attempts_and_leaves_nothing_open(gaf) -> None:
    gaf.fake.connect_failures = 3

    error = refused(connect(gaf), 502, "GAF_CONNECT_FAILED")

    assert "127.0.0.1:9090" in error["message"] and "Thrift" in error["message"]
    assert not gaf.fake.session_open
    assert status(gaf)["connected"] is False


def test_connect_without_nrobot_is_unreachable(gaf) -> None:
    gaf.fake.close()

    error = refused(connect(gaf), 503, "GAF_UNREACHABLE")

    assert "NRobot.Server.exe" in error["message"]


def test_connect_replaces_a_session_that_is_already_open(connected) -> None:
    assert connect(connected).json()["data"]["connected"] is True

    # The old one is torn down first, or the new one is blocked.
    assert len(connected.fake.keywords("DESTROYGAMECLIENT")) >= 2
    assert connected.fake.session_open


def test_connect_reports_an_unusable_object_query_file(gaf, monkeypatch, tmp_path) -> None:
    broken = tmp_path / "ObjectQuery.json"
    broken.write_text("{ not json", encoding="utf-8")
    patch_config(monkeypatch, lambda config: config["gaf"].update(object_query_root=str(broken)))

    error = refused(connect(gaf), 500, "CONFIG_INVALID")

    assert "not valid JSON" in error["message"]
    assert not gaf.fake.session_open


def test_connect_reports_an_invalid_game_config(gaf, monkeypatch) -> None:
    patch_config(monkeypatch, lambda config: config["gaf"].pop("game_type"))

    refused(connect(gaf), 500, "CONFIG_INVALID")


def test_a_game_with_an_empty_object_query_file_still_connects_on_the_common_base(gaf) -> None:
    data = connect(gaf, game="HuffNPuffHighRise").json()["data"]

    assert data["game"] == "HuffNPuffHighRise"
    assert data["connected"] is True


def test_disconnect_closes_the_session(connected) -> None:
    data = connected.client.post(f"{URL}/disconnect").json()["data"]

    assert data["connected"] is False
    assert not connected.fake.session_open
    refused(act(connected, "game_state"), 409, "GAF_NOT_CONNECTED")


def test_a_session_this_backend_did_not_start_is_reported_not_adopted(connected, tmp_path) -> None:
    # A backend restart forgets which game the open session was made for.
    restarted = make_service(connected.fake, connected.context)
    app.dependency_overrides[get_gaf_controller] = lambda: GafController(restarted)

    data = status(connected)

    assert data["connected"] is False
    assert "did not start" in data["detail"]
    refused(act(connected, "game_state"), 409, "GAF_NOT_CONNECTED")
    assert connect(connected).json()["data"]["connected"] is True


def test_a_session_for_another_game_is_not_a_session_for_this_one(connected) -> None:
    data = status(connected, game="HuffNPuffHighRise")

    assert data["connected"] is False
    assert "FortuneOx" in data["detail"] and "Connect switches" in data["detail"]
    refused(act(connected, "game_state", game="HuffNPuffHighRise"), 409, "GAF_NOT_CONNECTED")
    # ... and connecting to that one replaces it.
    assert connect(connected, game="HuffNPuffHighRise").json()["data"]["connected"] is True
    assert status(connected)["connected"] is False


def test_a_session_for_another_mode_is_not_a_session_for_this_one(connected) -> None:
    assert status(connected, mode="egm")["connected"] is False
    refused(act(connected, "game_state", mode="egm"), 409, "GAF_NOT_CONNECTED")


# --------------------------------------------------------------------------- action guards


def test_actions_need_a_session(gaf) -> None:
    error = refused(act(gaf, "spin"), 409, "GAF_NOT_CONNECTED")

    assert "Connect first" in error["message"]
    assert gaf.fake.keywords("PRESSMECHANICALSPINBUTTON") == []


def test_an_unknown_action_is_not_found(connected) -> None:
    refused(act(connected, "fly_to_the_moon"), 404, "NOT_FOUND")


def test_a_game_specific_action_is_not_found_where_the_game_does_not_list_it(gaf) -> None:
    connect(gaf, game="HuffNPuffHighRise")

    refused(act(gaf, "take_win", game="HuffNPuffHighRise"), 404, "NOT_FOUND")


def test_a_lost_session_is_reported_and_forgotten(connected) -> None:
    connected.fake.lose_session()  # the game restarted under NRobot

    error = refused(act(connected, "game_state"), 409, "GAF_NOT_CONNECTED")

    assert "lost" in error["message"]
    assert status(connected)["connected"] is False


def test_nrobot_dying_mid_session_is_unreachable(connected) -> None:
    connected.fake.close()

    refused(act(connected, "game_state"), 503, "GAF_UNREACHABLE")


def test_a_keyword_that_fails_is_a_bad_gateway_naming_the_keyword(connected) -> None:
    connected.fake.failing["GETCURRENTACTIVEDENOM"] = "boom"

    error = refused(act(connected, "active_denom"), 502, "GAF_KEYWORD_FAILED")

    assert error["details"] == {"keyword": "GETCURRENTACTIVEDENOM"}
    assert "boom" in error["message"]
    assert status(connected)["connected"] is True  # one failing keyword is not a lost session


def test_a_status_read_that_hiccups_does_not_drop_the_session(connected) -> None:
    connected.fake.failing["GETCURRENTSTATE"] = "boom"

    data = status(connected)

    assert (data["connected"], data["state"]) == (True, "unavailable")
    del connected.fake.failing["GETCURRENTSTATE"]
    assert result(act(connected, "game_state"))["values"]["IdleStateMachine"] == "stateIdleWithCredits"


def test_only_one_command_runs_at_a_time_but_reads_are_not_blocked(connected) -> None:
    with connected.service._lock:  # a command (or a connect) is in progress
        error = refused(act(connected, "spin"), 409, "GAF_BUSY")
        assert "still running" in error["message"]
        assert result(act(connected, "game_state"))["action"] == "game_state"
        assert status(connected)["connected"] is True
    assert connected.fake.keywords("PRESSMECHANICALSPINBUTTON") == []


# ------------------------------------------------------------------------------------- spin


def test_spin_presses_the_button_and_waits_for_the_game_to_settle(connected) -> None:
    data = result(act(connected, "spin"))

    assert data["action"] == "spin" and data["label"] == "Spin"
    assert data["values"]["outcome"] == "settled"
    assert data["values"]["state"] == "stateIdleWithCredits"
    assert "settled" in data["message"]
    assert connected.fake.keywords("PRESSMECHANICALSPINBUTTON") == [[]]


def test_spin_waits_for_the_game_to_leave_its_old_state_before_judging_it_finished(connected) -> None:
    # The game stays idle for a beat after the press. Reading "idle" then must not end the wait.
    connected.fake.spin_script = ["stateIdleWithCredits"] * 3 + ["statePlaying"] * 4 + ["stateIdleWithCredits"]

    data = result(act(connected, "spin"))

    assert data["values"]["outcome"] == "settled"
    idle_reads = [a for a in connected.fake.keywords("GETCURRENTSTATE") if a == ["IdleStateMachine"]]
    assert len(idle_reads) >= 1 + 3 + 4  # the one before the press, the beat, and the whole spin


def test_a_win_holds_the_game_playing_so_spin_ends_when_the_win_is_offered(connected) -> None:
    connected.fake.spin_script = ["stateIdleWithCredits", "statePlaying"]  # and it stays there
    connected.fake.win_on_offer = True

    data = result(act(connected, "spin"))

    assert data["values"]["outcome"] == "win_offered"
    assert data["values"]["state"] == "statePlaying"
    assert "win on offer" in data["message"]


def test_spin_gives_up_on_a_game_that_keeps_playing(connected) -> None:
    connected.fake.spin_script = ["stateIdleWithCredits", "statePlaying"]
    connected.service._settle_timeout = 0.05

    data = result(act(connected, "spin"))

    assert data["values"]["outcome"] == "timeout"
    assert "still playing" in data["message"]


def test_spin_says_when_the_game_never_started(connected, monkeypatch) -> None:
    monkeypatch.setattr(gaf_service, "_DEPARTURE_TIMEOUT", 0.05)  # this one waits the whole time
    connected.fake.ignore_input = True  # e.g. a suspended game: the press is accepted and ignored
    connected.fake.idle_state = "stateDisabled"

    data = result(act(connected, "spin"))

    assert data["values"] == {"outcome": "not_started", "state": "stateDisabled"}
    assert "did not start" in data["message"] and "stateDisabled" in data["message"]


def test_spin_refuses_a_game_that_is_still_playing(connected) -> None:
    connected.fake.idle_state = "statePlaying"  # mid-spin, or holding a win

    error = refused(act(connected, "spin"), 409, "GAF_NOT_IDLE")

    assert "take the win" in error["message"]
    assert connected.fake.keywords("PRESSMECHANICALSPINBUTTON") == []


# --------------------------------------------------------------------------- take win, gamble


@pytest.mark.parametrize("action,button,label", [("take_win", "TakeWinButton", "Take win"), ("gamble", "GambleButton", "Gamble")])
def test_a_win_on_offer_can_be_taken_or_gambled(connected, action: str, button: str, label: str) -> None:
    connected.fake.win_on_offer = True

    data = result(act(connected, action))

    assert data["label"] == label
    assert data["values"] == {"outcome": "done", "state": "stateIdleWithCredits"}
    assert connected.fake.keywords("PRESSNONWAGERBUTTON") == [[button]]


@pytest.mark.parametrize("action", ["take_win", "gamble"])
def test_nothing_is_pressed_when_nothing_is_on_offer(connected, action: str) -> None:
    # The game reports success for a press with nothing to take, so the service asks first.
    error = refused(act(connected, action), 409, "GAF_NOT_AVAILABLE")

    assert "not on offer" in error["message"]
    assert connected.fake.keywords("PRESSNONWAGERBUTTON") == []


def test_a_button_the_game_has_not_mapped_is_not_on_offer(connected) -> None:
    connected.fake.mapped_buttons = set()

    refused(act(connected, "take_win"), 409, "GAF_NOT_AVAILABLE")


def test_a_press_the_game_ignores_is_reported_as_still_on_offer(connected) -> None:
    connected.fake.win_on_offer = True
    connected.fake.ignore_input = True

    data = result(act(connected, "take_win"))

    assert data["values"]["outcome"] == "still_on_offer"
    assert "still on offer" in data["message"]


# ---------------------------------------------------------------------- toggle credit meter


def test_toggling_the_credit_meter_reports_what_it_now_shows(connected) -> None:
    first = result(act(connected, "toggle_credit_meter"))
    second = result(act(connected, "toggle_credit_meter"))

    assert first["values"] == {"outcome": "toggled", "label": "CREDITS", "value": "10297"}
    assert second["values"] == {"outcome": "toggled", "label": "CASH", "value": "$20,594.00"}
    assert connected.fake.keywords("TOGGLEMETERVALUE") == [["CreditMeter"], ["CreditMeter"]]


def test_a_toggle_the_game_ignores_is_reported_as_unchanged(connected) -> None:
    # Pressing succeeds even on a suspended game, so only the meter can tell.
    connected.fake.ignore_input = True

    data = result(act(connected, "toggle_credit_meter"))

    assert data["values"]["outcome"] == "unchanged"
    assert "did not change" in data["message"]


# ----------------------------------------------------------------------------------- reads


def test_game_state_reads_every_state_machine(connected) -> None:
    data = result(act(connected, "game_state"))

    assert data["values"] == {
        "IdleStateMachine": "stateIdleWithCredits",
        "SlotGameStateMachine": "stateIdle",
        "GambleOfferStateMachine": "idleState",
        "GameStateMachine": "stateIdle",
    }
    assert "stateIdleWithCredits" in data["message"]


def test_a_state_machine_the_game_does_not_have_reads_as_unavailable(connected) -> None:
    # An unknown machine is a normal reply carrying "ERROR: ...", which must not pass for a state.
    del connected.fake.states["GameStateMachine"]

    values = result(act(connected, "game_state"))["values"]

    assert values["GameStateMachine"] == "unavailable"
    assert values["IdleStateMachine"] == "stateIdleWithCredits"


def test_active_denom_is_read_and_shown_the_way_people_read_it(connected) -> None:
    data = result(act(connected, "active_denom"))

    assert data["values"] == {"active_denom": "200.000"}
    assert "$2.00" in data["message"]


def test_available_denoms_lists_what_the_game_offers(connected) -> None:
    data = result(act(connected, "available_denoms"))

    assert data["values"]["available_denoms"] == ["1.000", "2.000", "5.000", "10.000", "100.000", "200.000"]
    assert "1¢, 2¢, 5¢, 10¢, $1.00, $2.00" in data["message"]


def test_meters_are_read_with_their_labels_and_a_blank_one_says_so(connected) -> None:
    data = result(act(connected, "meters"))

    assert data["values"] == {
        "CreditMeter": "CASH: $20,594.00",
        "BetMeter": "BET: $20.00",
        "WinMeter": "WIN: (blank)",
        "CollectMeter": "COLLECT: (blank)",
    }
    assert {a[1] for a in connected.fake.keywords_with_args("METERINFO")} == {"name", "value"}


# ------------------------------------------------------------------- front-panel messages


def test_front_panel_messages_are_read_for_every_area_the_game_maps(connected) -> None:
    data = result(act(connected, "front_panel_messages"))

    assert data["values"] == {"MessageArea1": ["Game Over"]}
    assert "1 showing text" in data["message"]
    assert connected.fake.keywords("GETFRONTPANELGAMEMESSAGE") == [["MessageArea1"]]


def test_an_area_showing_nothing_says_so(connected) -> None:
    # A cyclic message is blank between messages.
    connected.fake.messages["MessageArea1"] = []

    data = result(act(connected, "front_panel_messages"))

    assert data["values"] == {"MessageArea1": "(none)"}
    assert "0 showing text" in data["message"]


def test_an_area_that_cannot_be_read_is_unavailable_not_a_failure(connected) -> None:
    connected.fake.failing["GETFRONTPANELGAMEMESSAGE"] = "Arithmetic operation resulted in an overflow."

    assert result(act(connected, "front_panel_messages"))["values"] == {"MessageArea1": "unavailable"}


def test_a_lost_session_still_fails_a_message_read(connected) -> None:
    connected.fake.lose_session()

    refused(act(connected, "front_panel_messages"), 409, "GAF_NOT_CONNECTED")


def test_message_actions_are_not_offered_where_the_game_maps_no_area(gaf, monkeypatch, tmp_path) -> None:
    none_mapped = tmp_path / "ObjectQuery.json"
    none_mapped.write_text('{"ThemeFrontPanelMsgQuery": {"MessageArea1": null}}', encoding="utf-8")
    patch_config(monkeypatch, lambda config: config["gaf"].update(object_query_root=str(none_mapped)))
    connect(gaf)

    listed = [a["id"] for a in gaf.client.get(f"{URL}/actions").json()["data"]]

    assert "front_panel_messages" not in listed and "unique_front_panel_messages" not in listed
    assert "take_win" in listed
    refused(act(gaf, "unique_front_panel_messages"), 404, "NOT_FOUND")


def test_the_watch_action_describes_its_inputs_for_the_ui(gaf) -> None:
    listed = {a["id"]: a for a in gaf.client.get(f"{URL}/actions").json()["data"]}

    watch = listed["unique_front_panel_messages"]["params"]
    assert [p["name"] for p in watch] == ["area", "seconds"]
    assert (watch[0]["kind"], watch[0]["options"], watch[0]["default"]) == ("choice", ["MessageArea1"], "MessageArea1")
    assert (watch[1]["kind"], watch[1]["min"], watch[1]["max"], watch[1]["default"]) == ("number", 1, 60, 15)
    assert listed["spin"]["params"] == []


def test_watching_an_area_lists_every_different_message_it_showed(connected) -> None:
    data = result(act(connected, "unique_front_panel_messages"))

    assert data["values"] == {
        "area": "MessageArea1",
        "watched": "15s",
        "messages": ["Game Over", "Game Pays 0", "Play 880 Credits"],
    }
    assert "3 different message(s)" in data["message"]
    assert connected.fake.keywords("GETALLUNIQUEFRONTPANELMESSAGES") == [["MessageArea1", "15"]]


def test_the_watch_takes_the_area_and_time_it_is_given(connected) -> None:
    result(act_with(connected, "unique_front_panel_messages", area="MessageArea1", seconds=7.5))

    assert connected.fake.keywords("GETALLUNIQUEFRONTPANELMESSAGES") == [["MessageArea1", "7.5"]]


def test_a_watch_that_saw_nothing_says_so(connected) -> None:
    connected.fake.unique_messages["MessageArea1"] = []

    assert result(act(connected, "unique_front_panel_messages"))["values"]["messages"] == "(none)"


@pytest.mark.parametrize(
    "params",
    [
        {"seconds": 0},
        {"seconds": 61},
        {"seconds": "soon"},
        {"area": "MessageArea9"},
        {"area": ""},
        {"colour": "red"},
    ],
)
def test_a_watch_with_unusable_inputs_is_refused_before_anything_is_asked_of_the_game(connected, params) -> None:
    connected.fake.calls.clear()

    refused(act_with(connected, "unique_front_panel_messages", **params), 400, "BAD_REQUEST")

    assert connected.fake.keywords("GETALLUNIQUEFRONTPANELMESSAGES") == []


def test_an_action_without_inputs_refuses_any(connected) -> None:
    refused(act_with(connected, "spin", seconds=3), 400, "BAD_REQUEST")
    assert connected.fake.keywords("PRESSMECHANICALSPINBUTTON") == []


def test_a_watch_is_a_command_so_nothing_else_is_pressed_meanwhile(connected) -> None:
    with connected.service._lock:
        refused(act(connected, "unique_front_panel_messages"), 409, "GAF_BUSY")
    assert connected.fake.keywords("GETALLUNIQUEFRONTPANELMESSAGES") == []


def test_the_watch_outlasts_the_keyword_timeout_of_other_calls(connected) -> None:
    connected.service._nrobot = NRobot(connected.fake.url, timeout=0.2)  # every other keyword gives up at 0.2s
    connected.fake.delay["GETALLUNIQUEFRONTPANELMESSAGES"] = 0.6  # the watch takes longer than that

    assert result(act_with(connected, "unique_front_panel_messages", seconds=1))["values"]["watched"] == "1s"


# ----------------------------------------------------------------------------- bet layout


def test_the_bet_layout_is_not_offered_unless_the_game_lists_it(gaf) -> None:
    assert "bet_layout" not in [a["id"] for a in gaf.client.get(f"{URL}/actions").json()["data"]]
    connect(gaf)
    refused(act(gaf, "bet_layout"), 404, "NOT_FOUND")


def test_the_bet_layout_is_read_from_the_object_the_game_names(gaf, monkeypatch) -> None:
    patch_config(monkeypatch, lambda c: c["gaf"].update(actions=["bet_layout"], bet_layout_object="IDeckBetSliderController"))
    connect(gaf)

    data = result(act(gaf, "bet_layout"))

    assert data["values"] == {"object": "IDeckBetSliderController", "layout": ["BetButtonPanelLayout", "3 rows"]}
    assert gaf.fake.keywords("GETACTIVEBETLAYOUT") == [["IDeckBetSliderController"]]


def test_a_game_naming_no_layout_object_asks_for_the_legacy_layout(gaf, monkeypatch) -> None:
    patch_config(monkeypatch, lambda c: c["gaf"].update(actions=["bet_layout"]))
    connect(gaf)

    data = result(act(gaf, "bet_layout"))

    assert data["values"]["object"] == "(legacy server-side layout)"
    assert gaf.fake.keywords("GETACTIVEBETLAYOUT") == [[""]]


def test_a_game_that_does_not_implement_the_bet_layout_reports_why(gaf, monkeypatch) -> None:
    patch_config(monkeypatch, lambda c: c["gaf"].update(actions=["bet_layout"]))
    connect(gaf)
    gaf.fake.failing["GETACTIVEBETLAYOUT"] = "Invalid method name: 'GetActiveBetLayoutWithObject'"

    error = refused(act(gaf, "bet_layout"), 502, "GAF_KEYWORD_FAILED")

    assert "GetActiveBetLayoutWithObject" in error["message"]
    assert error["details"] == {"keyword": "GETACTIVEBETLAYOUT"}


# ------------------------------------------------------------- one keyword at a time


def test_keywords_never_overlap_on_the_game_connection(connected) -> None:
    # The UI polls status while actions run; on the real game two keywords at once corrupt its connection
    # (overflow / out-of-memory errors, then a 10-25s reconnect). So the backend never has two in flight.
    connected.fake.delay["GETCURRENTSTATE"] = 0.005
    connected.fake.delay["METERINFO"] = 0.005
    errors: list[Exception] = []

    def hammer(work) -> None:
        try:
            for _ in range(15):
                work()
        except Exception as exc:  # noqa: BLE001 - the assertion below reports it
            errors.append(exc)

    work = [
        lambda: connected.service._status(None, None),
        lambda: connected.service._status(None, None),
        lambda: connected.service._run_action("game_state", {}, None, None),
        lambda: connected.service._run_action("meters", {}, None, None),
        lambda: connected.service._run_action("front_panel_messages", {}, None, None),
    ]
    threads = [threading.Thread(target=hammer, args=(w,)) for w in work]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert errors == []
    assert connected.fake.max_active == 1


def test_status_answers_from_what_it_last_saw_while_a_long_keyword_holds_the_connection(connected, monkeypatch) -> None:
    monkeypatch.setattr(gaf_service, "_PROBE_WAIT", 0.05)
    connected.fake.delay["GETALLUNIQUEFRONTPANELMESSAGES"] = 0.8
    watching = threading.Thread(target=lambda: connected.service._run_action("unique_front_panel_messages", {"seconds": 1}, None, None))
    watching.start()
    deadline = time.monotonic() + 2
    while connected.service._activity is None and time.monotonic() < deadline:
        time.sleep(0.005)
    started = time.monotonic()

    data = status(connected)

    assert time.monotonic() - started < 0.5  # it did not queue behind the watch
    assert (data["connected"], data["state"], data["busy"]) == (True, "stateIdleWithCredits", "Watch messages")
    watching.join()
    assert status(connected)["busy"] is None
    assert connected.fake.max_active == 1


def test_a_read_that_cannot_get_the_connection_is_refused_as_busy_naming_what_holds_it(connected, monkeypatch) -> None:
    monkeypatch.setattr(gaf_service, "_IO_WAIT", 0.05)
    connected.fake.delay["GETALLUNIQUEFRONTPANELMESSAGES"] = 0.8
    watching = threading.Thread(target=lambda: connected.service._run_action("unique_front_panel_messages", {"seconds": 1}, None, None))
    watching.start()
    deadline = time.monotonic() + 2
    while connected.service._activity is None and time.monotonic() < deadline:
        time.sleep(0.005)

    error = refused(act(connected, "game_state"), 409, "GAF_BUSY")

    assert "Watch messages" in error["message"]
    watching.join()
    assert result(act(connected, "game_state"))["action"] == "game_state"  # and it works again afterwards


def test_status_names_a_spin_while_it_runs(connected) -> None:
    connected.fake.spin_script = ["stateIdleWithCredits", "statePlaying", "statePlaying", "statePlaying", "stateIdleWithCredits"]
    connected.fake.delay["GETCURRENTSTATE"] = 0.02
    spinning = threading.Thread(target=lambda: connected.service._run_action("spin", {}, None, None))
    spinning.start()
    seen: set[str | None] = set()
    while spinning.is_alive():
        seen.add(status(connected)["busy"])
    spinning.join()

    assert "Spin" in seen
    assert status(connected)["busy"] is None
    assert connected.fake.max_active == 1


def test_a_meter_the_game_has_not_mapped_reads_as_unavailable(connected) -> None:
    connected.fake.unmapped_meters = {"CollectMeter"}

    values = result(act(connected, "meters"))["values"]

    assert values["CollectMeter"] == "unavailable"
    assert values["CreditMeter"] == "CASH: $20,594.00"
