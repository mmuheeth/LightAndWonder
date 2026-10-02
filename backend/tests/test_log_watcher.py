import os
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from app.schemas.game_context import GameContextUpdate, GameMode
from app.services.game_context_service import GameContextService
from app.utils import log_watcher
from app.utils.game_config import active_log_path, game_log_path, load_game_config
from app.utils.log_watcher import Bet, LogEvent, LogEventType, LogWatcher

PREFIX = "09/01/26 15:20:{sec:02d}.{ms:03d} 00 FortuneOx:24856 "


def stamp(sec: int = 44, ms: int = 848) -> str:
    return PREFIX.format(sec=sec, ms=ms)


def paytable_line(paytable: str = "FortuneOx-1102ZX-5c-89", denom: str = "5.000", **kw) -> str:
    return (
        f"{stamp(**kw)}DBG: [WagerGameApp.UpdatePayTable] current denom[{denom}] "
        f"current paytableId[{paytable}] current supported denoms[1.000,2.000,5.000]"
    )


def bet_line(bets_per_unit: str = "6.000", total: str = "528.000", **kw) -> str:
    return (
        f"{stamp(**kw)}INF: [BetManager.UpdateCurrentBet][CurrentBet {{{{ BetsPerUnit:{bets_per_unit}, "
        f"UnitData:[ units: 40, cost: 88 ], TotalBetCost:{total}, TotalBetValue:{total}, "
        "DirectPlayData:{{ DirectPlayType:NotDirectPlay, BonusID:, BonusIndex:0, BonusOption:0 }} }}]"
    )


def machine_line(state: str, machine: str = "SlotGameStateMachine", **kw) -> str:
    return (
        f"{stamp(**kw)}INF: StateMachine[{machine}] transitioned from [stateX] to [{state}] "
        "on event [GDK.Common.ServerAPI.SpinMsg]"
    )


NOISE = f"{stamp()}DBG: [MessageQueue.Publish] msg[GDK.Common.ServerAPI.SpinDoneMsg]"


def result_line(won: bool = True, amount: str = "400.000", **kw) -> str:
    return (
        f"{stamp(**kw)}DBG: SpinBufferManager.OnGameStateResults "
        f"resultsStateEvent.totalWin.Zero()={not won}:{amount}"
    )


def published_line(message: str, namespace: str = "GDK.Common.ServerAPI", **kw) -> str:
    return f"{stamp(**kw)}DBG: [MessageQueue.Publish] msg[{namespace}.{message}]"


def append(path: Path, *lines: str) -> None:
    with path.open("ab") as file:
        file.write(("\n".join(lines) + "\n").encode())


@pytest.fixture
def log(tmp_path: Path) -> Path:
    path = tmp_path / "Game_Client.log"
    path.write_bytes(b"")
    return path


def watch(path: Path | None) -> tuple[LogWatcher, list[LogEvent]]:
    watcher = LogWatcher(lambda: path)
    events: list[LogEvent] = []
    watcher.subscribe(events.append)
    return watcher, events


def test_reports_paytable_spin_start_and_spin_end(log: Path) -> None:
    watcher, events = watch(log)
    watcher.poll()  # attaches at the end of the (empty) file

    append(
        log,
        NOISE,
        paytable_line(),
        machine_line("stateSpin", sec=45, ms=1),
        machine_line("stateSpinWithStops"),
        machine_line("stateReelSpinDone", sec=48, ms=62),
    )
    watcher.poll()

    assert [event.type for event in events] == [
        LogEventType.PAYTABLE,
        LogEventType.SPIN_START,
        LogEventType.SPIN_END,
    ]
    paytable, start, end = events
    assert paytable.paytable_id == "FortuneOx-1102ZX-5c-89"
    assert paytable.denom == 5.0
    assert paytable.supported_denoms == (1.0, 2.0, 5.0)
    assert paytable.log_time == datetime(2026, 9, 1, 15, 20, 44, 848000)
    assert start.state_machine == end.state_machine == "SlotGameStateMachine"
    assert (end.log_time - start.log_time).total_seconds() == pytest.approx(3.061)


def test_spin_events_of_any_state_machine_are_reported(log: Path) -> None:
    watcher, events = watch(log)
    watcher.poll()

    append(log, machine_line("stateSpin", machine="FreeSpinStateMachineFreeSpin"))
    watcher.poll()

    assert events[0].type is LogEventType.SPIN_START
    assert events[0].state_machine == "FreeSpinStateMachineFreeSpin"


def test_lookalike_states_are_ignored(log: Path) -> None:
    watcher, events = watch(log)
    watcher.poll()

    append(log, machine_line("stateSpinSetup"), machine_line("stateSpinWithStops"))
    watcher.poll()

    assert events == []


def test_state_tracks_paytable_and_spinning(log: Path) -> None:
    watcher, _ = watch(log)
    watcher.poll()

    append(log, paytable_line("PT-A", "1.000"), machine_line("stateSpin"))
    watcher.poll()
    assert watcher.state.paytable_id == "PT-A"
    assert watcher.state.denom == 1.0
    assert watcher.state.spinning is True

    append(log, machine_line("stateReelSpinDone"), paytable_line("PT-B", "2.000"))
    watcher.poll()
    assert watcher.state.paytable_id == "PT-B"
    assert watcher.state.spinning is False


def test_existing_lines_are_not_replayed_but_current_paytable_is_found(log: Path) -> None:
    append(
        log,
        paytable_line("PT-OLD"),
        machine_line("stateSpin"),
        machine_line("stateReelSpinDone"),
        paytable_line("PT-CURRENT", "10.000"),
        NOISE,
    )
    watcher, events = watch(log)

    watcher.poll()

    assert events == []
    assert watcher.state.paytable_id == "PT-CURRENT"
    assert watcher.state.denom == 10.0


def test_history_search_reaches_back_across_chunks_but_respects_the_limit(tmp_path: Path) -> None:
    path = tmp_path / "big.log"
    filler = "x" * 200
    append(path, paytable_line("PT-FAR"), *[filler] * 4000)  # ~800 KB of other lines after it

    found = LogWatcher(lambda: path, history_bytes=4 * 1024 * 1024)
    found.poll()
    too_small = LogWatcher(lambda: path, history_bytes=100 * 1024)
    too_small.poll()

    assert found.state.paytable_id == "PT-FAR"
    assert too_small.state.paytable_id is None


def test_half_written_line_is_reported_once_it_is_complete(log: Path) -> None:
    watcher, events = watch(log)
    watcher.poll()
    line = machine_line("stateSpin")

    with log.open("ab") as file:
        file.write(line[:60].encode())
    watcher.poll()
    assert events == []

    with log.open("ab") as file:
        file.write((line[60:] + "\n").encode())
    watcher.poll()
    watcher.poll()
    assert [event.type for event in events] == [LogEventType.SPIN_START]


def test_truncated_log_is_read_again_from_the_start(log: Path) -> None:
    append(log, *[NOISE] * 50)
    watcher, events = watch(log)
    watcher.poll()

    log.write_bytes(b"")  # the game restarted with a fresh file
    append(log, machine_line("stateSpin"))
    watcher.poll()

    assert [event.type for event in events] == [LogEventType.SPIN_START]


def test_replaced_log_is_read_from_the_start_even_if_it_is_larger(log: Path, tmp_path: Path) -> None:
    append(log, NOISE)
    watcher, events = watch(log)
    watcher.poll()

    fresh = tmp_path / "fresh.log"
    append(fresh, *[NOISE] * 20, machine_line("stateSpin"))
    os.replace(fresh, log)  # what a rotation looks like: same name, different file
    watcher.poll()

    assert [event.type for event in events] == [LogEventType.SPIN_START]


def test_rotation_clears_a_spin_left_open(log: Path) -> None:
    watcher, _ = watch(log)
    watcher.poll()
    append(log, machine_line("stateSpin"))
    watcher.poll()
    assert watcher.state.spinning is True

    log.write_bytes(b"")
    watcher.poll()

    assert watcher.state.spinning is False


def test_log_that_does_not_exist_yet_is_read_from_the_start_when_it_appears(tmp_path: Path) -> None:
    path = tmp_path / "later.log"
    watcher, events = watch(path)

    watcher.poll()
    watcher.poll()
    assert events == []

    append(path, paytable_line(), machine_line("stateSpin"))
    watcher.poll()

    assert [event.type for event in events] == [LogEventType.PAYTABLE, LogEventType.SPIN_START]


def test_unreadable_is_true_only_while_the_log_cannot_be_read(tmp_path: Path) -> None:
    path = tmp_path / "later.log"
    watcher, _ = watch(path)
    assert watcher.unreadable is False  # nothing attempted yet

    watcher.poll()
    assert watcher.unreadable is True

    append(path, paytable_line())
    watcher.poll()
    assert watcher.unreadable is False


def test_state_keeps_the_supported_denoms_of_the_paytable(log: Path) -> None:
    watcher, _ = watch(log)
    watcher.poll()

    append(log, paytable_line("PT-A", "2.000"))
    watcher.poll()

    assert watcher.state.supported_denoms == (1.0, 2.0, 5.0)


def test_reports_the_bet_in_force(log: Path) -> None:
    watcher, events = watch(log)
    watcher.poll()

    append(log, paytable_line("PT-A", "2.000"), bet_line("6.000", "528.000"))
    watcher.poll()

    assert [event.type for event in events] == [LogEventType.PAYTABLE, LogEventType.BET]
    assert events[1].bet == Bet(bets_per_unit=6.0, total_bet=528.0)
    assert watcher.state.bet == Bet(bets_per_unit=6.0, total_bet=528.0)


def test_a_bet_means_nothing_under_another_denom(log: Path) -> None:
    watcher, _ = watch(log)
    watcher.poll()
    append(log, paytable_line("PT-A", "2.000"), bet_line("6.000", "528.000"))
    watcher.poll()

    # The game restates the paytable on every bet change; under the same denom the bet stands.
    append(log, paytable_line("PT-A", "2.000", sec=50))
    watcher.poll()
    assert watcher.state.bet == Bet(6.0, 528.0)

    # Under another one it is in other cents, so it is dropped until the game logs the bet again.
    append(log, paytable_line("PT-B", "1.000", sec=51))
    watcher.poll()
    assert watcher.state.bet is None
    append(log, bet_line("1.000", "88.000", sec=51))
    watcher.poll()
    assert watcher.state.bet == Bet(1.0, 88.0)


def test_the_current_bet_is_found_in_an_existing_log(log: Path) -> None:
    append(
        log,
        paytable_line("PT-OLD", "1.000"),
        bet_line("1.000", "88.000"),
        machine_line("stateSpin"),
        paytable_line("PT-CURRENT", "2.000"),
        bet_line("6.000", "528.000"),
        NOISE,
    )
    watcher, events = watch(log)

    watcher.poll()

    assert events == []
    assert (watcher.state.paytable_id, watcher.state.denom) == ("PT-CURRENT", 2.0)
    assert watcher.state.bet == Bet(6.0, 528.0)


def test_a_bet_logged_before_the_current_paytable_is_not_taken_for_its_own(log: Path) -> None:
    append(log, bet_line("1.000", "88.000"), paytable_line("PT-CURRENT", "2.000"), NOISE)
    watcher, _ = watch(log)

    watcher.poll()

    assert watcher.state.paytable_id == "PT-CURRENT"
    assert watcher.state.bet is None


def test_the_bet_is_found_in_a_later_chunk_than_the_paytable(tmp_path: Path) -> None:
    path = tmp_path / "big.log"
    append(path, paytable_line("PT-FAR", "2.000"), *["x" * 200] * 4000, bet_line("4.000", "352.000"))
    watcher = LogWatcher(lambda: path, history_bytes=4 * 1024 * 1024)

    watcher.poll()

    assert watcher.state.paytable_id == "PT-FAR"
    assert watcher.state.bet == Bet(4.0, 352.0)


def test_reports_the_result_and_the_win_presentation_events(log: Path) -> None:
    watcher, events = watch(log)
    watcher.poll()

    append(
        log,
        published_line("CycleResultsStoppedMsg_BaseGame", sec=40, ms=1),
        machine_line("stateSpin", sec=40, ms=100),
        machine_line("stateReelSpinDone", sec=43, ms=50),
        result_line(won=True, amount="400.000", sec=43, ms=400),
        published_line("FirstCycleResultsIterationFinishedMsg", "GDK.Client.ClientMessaging", sec=49),
        published_line("GameOverMsg", sec=58),
    )
    watcher.poll()

    assert [event.type for event in events] == [
        LogEventType.CYCLE_STOPPED,
        LogEventType.SPIN_START,
        LogEventType.SPIN_END,
        LogEventType.RESULT,
        LogEventType.CYCLE_FIRST_ITERATION_DONE,
        LogEventType.GAME_OVER,
    ]
    result = events[3]
    assert result.won is True
    assert result.win_amount == 400.0
    assert result.log_time == datetime(2026, 9, 1, 15, 20, 43, 400000)
    assert events[5].log_time == datetime(2026, 9, 1, 15, 20, 58, 848000)


def test_a_result_with_no_win_says_so(log: Path) -> None:
    watcher, events = watch(log)
    watcher.poll()

    append(log, result_line(won=False, amount="0.000"))
    watcher.poll()

    assert [(event.type, event.won, event.win_amount) for event in events] == [(LogEventType.RESULT, False, 0.0)]


def test_results_and_messages_do_not_change_whether_a_spin_is_on(log: Path) -> None:
    watcher, _ = watch(log)
    watcher.poll()

    append(log, machine_line("stateSpin"), result_line(), published_line("GameOverMsg"))
    watcher.poll()
    assert watcher.state.spinning is True

    append(log, machine_line("stateReelSpinDone"), published_line("GameOverMsg"))
    watcher.poll()
    assert watcher.state.spinning is False


def test_lookalike_published_messages_are_ignored(log: Path) -> None:
    watcher, events = watch(log)
    watcher.poll()

    append(
        log,
        published_line("GameOverMsgLater"),
        published_line("SpinDoneMsg"),
        # The same message being queued by the game's other process is not the game going idle.
        f"{stamp()}INF: [SGIPCGameModel.QueueMessage] Enqueued msg[GDK.Common.ServerAPI.GameOverMsg]",
    )
    watcher.poll()

    assert events == []


def test_no_path_means_idle() -> None:
    watcher, events = watch(None)

    watcher.poll()

    assert events == []
    assert watcher.path is None


def test_following_the_provider_to_another_log_resets_state(tmp_path: Path) -> None:
    first, second = tmp_path / "a.log", tmp_path / "b.log"
    append(first, paytable_line("PT-A"))
    append(second, paytable_line("PT-B"))
    current = [first]
    watcher = LogWatcher(lambda: current[0])
    events: list[LogEvent] = []
    watcher.subscribe(events.append)

    watcher.poll()
    assert watcher.state.paytable_id == "PT-A"

    current[0] = second
    watcher.poll()
    assert watcher.path == second
    assert watcher.state.paytable_id == "PT-B"

    append(first, machine_line("stateSpin"))  # the old log no longer matters
    append(second, machine_line("stateReelSpinDone"))
    watcher.poll()
    assert [event.type for event in events] == [LogEventType.SPIN_END]


def test_a_failing_listener_does_not_affect_the_others(log: Path) -> None:
    watcher, events = watch(log)

    def broken(event: LogEvent) -> None:
        raise RuntimeError("boom")

    watcher.subscribe(broken)
    watcher.poll()

    append(log, machine_line("stateSpin"))
    watcher.poll()

    assert len(events) == 1


def test_unsubscribe_stops_delivery(log: Path) -> None:
    watcher = LogWatcher(lambda: log)
    events: list[LogEvent] = []
    unsubscribe = watcher.subscribe(events.append)
    watcher.poll()

    unsubscribe()
    append(log, machine_line("stateSpin"))
    watcher.poll()

    assert events == []


def watcher_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name in ("log-watcher", "log-tail")]


def wait_until(condition, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_background_threads_deliver_events_and_stop(log: Path) -> None:
    watcher = LogWatcher(lambda: log, poll_interval=0.01)
    seen = threading.Event()
    watcher.subscribe(lambda event: seen.set())
    watcher.start()
    watcher.start()  # idempotent
    try:
        # The reader attaches at the end of the file on its first pass; keep writing until
        # a pass after that picks a line up.
        for _ in range(300):
            append(log, machine_line("stateSpin"))
            if seen.wait(0.01):
                break
        assert seen.is_set()
        assert len(watcher_threads()) == 2  # the follower and one reader, not one per start()
    finally:
        watcher.stop()

    assert wait_until(lambda: not watcher_threads())


def test_no_events_are_delivered_after_stop(log: Path) -> None:
    watcher = LogWatcher(lambda: log, poll_interval=0.01)
    events: list[LogEvent] = []
    watcher.subscribe(events.append)
    watcher.start()
    assert wait_until(lambda: watcher.path == log)
    time.sleep(0.05)  # let the reader attach at the end of the file

    watcher.stop()
    append(log, machine_line("stateSpin"))
    time.sleep(0.1)

    assert events == []


def test_a_read_stuck_on_a_dead_share_does_not_hold_up_switching_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead, alive = tmp_path / "dead.log", tmp_path / "alive.log"
    append(dead, paytable_line("PT-DEAD"))
    alive.write_bytes(b"")
    stuck, release = threading.Event(), threading.Event()
    real_open = log_watcher._open_shared

    def open_shared(path: Path):
        if path == dead:
            stuck.set()
            release.wait(10)  # what opening a file on an unreachable host looks like
        return real_open(path)

    monkeypatch.setattr(log_watcher, "_open_shared", open_shared)
    current = [dead]
    watcher = LogWatcher(lambda: current[0], poll_interval=0.01)
    seen = threading.Event()
    watcher.subscribe(lambda event: seen.set())
    watcher.start()
    try:
        assert stuck.wait(3)

        current[0] = alive
        for _ in range(300):
            append(alive, machine_line("stateSpin"))
            if seen.wait(0.01):
                break
        assert seen.is_set()

        release.set()  # the abandoned read now finishes; it must not touch the new state
        time.sleep(0.1)
        assert watcher.path == alive
        assert watcher.state.paytable_id is None
    finally:
        release.set()
        watcher.stop()


# ------------------------------------------------------------------ game config


def test_game_log_path_reads_the_logs_key_of_the_mode() -> None:
    config = load_game_config("FortuneOx")

    assert game_log_path("FortuneOx", "simulator") == Path(config["simulator"]["logs"])
    assert game_log_path("FortuneOx", "egm") == Path(config["egm"]["logs"])
    assert game_log_path("FortuneOx", "simulator") != game_log_path("FortuneOx", "egm")


@pytest.mark.parametrize(
    ("game", "mode"),
    [("Nope", "egm"), ("FortuneOx", "nope"), ("..", "egm"), ("a.b", "egm"), ("", "egm")],
)
def test_game_log_path_is_none_when_not_configured(game: str, mode: str) -> None:
    assert game_log_path(game, mode) is None


def test_active_log_path_uses_the_default_game_before_anything_is_chosen(tmp_path: Path) -> None:
    context = GameContextService(state_file=tmp_path / "ctx.json")
    assert context.current_game is None

    first_game = context.get_context().context.game

    assert active_log_path(context) == game_log_path(first_game, "simulator")


def test_active_log_path_follows_the_game_context(tmp_path: Path) -> None:
    context = GameContextService(state_file=tmp_path / "ctx.json")

    context.update_context(GameContextUpdate(game="FortuneOx", mode=GameMode.SIMULATOR))
    assert active_log_path(context) == game_log_path("FortuneOx", "simulator")

    context.update_context(GameContextUpdate(game="HuffNPuffHighRise", mode=GameMode.EGM))
    assert active_log_path(context) == game_log_path("HuffNPuffHighRise", "egm")
