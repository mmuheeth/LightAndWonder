"""Tracking the cyclic messages of every spin: the game's log says when the reels stop, what was won and when the
game is idle again; OBS is a fake that serves the next synthetic frame of the message areas per screenshot (with
hooks that let the "game" write to its log at a given frame), and the OCR engine is a fake that reads a message by
where its text is."""

import asyncio
import copy
import io
import json
import time
from collections.abc import Callable
from itertools import zip_longest
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
import pytest_asyncio
from PIL import Image

from app.api.dependencies import get_cyclic_controller
from app.controllers.cyclic_controller import CyclicController
from app.core.exceptions import AppException, NotFoundException, ServiceUnavailableException
from app.main import app
from app.schemas.cyclic import CyclicRound
from app.schemas.game_context import GameContextUpdate, GameMode
from app.services import cyclic_service
from app.services.cyclic_service import CyclicMessageService
from app.services.game_context_service import GameContextService
from app.utils import game_config as game_settings
from app.utils.log_watcher import LogWatcher
from app.utils.ocr_engine import OcrEngineError, TextLine
from tests.fake_obs import FakeObs
from tests.obs_helpers import make_service
from tests.test_log_watcher import append, machine_line, published_line, result_line

URL = "/api/v1/cyclic"
GAME = "FortuneOx"  # the real config; only its ROIs are replaced
SIZE = (200, 100)
ROIS = {"cyclic_message": [0.0, 0.0, 0.6, 0.1], "cyclic_message_2": [0.0, 0.1, 0.6, 0.2]}  # 120x10 px each
BANDS = {"cyclic_message": 0, "cyclic_message_2": 10}  # the row each one starts at in a screenshot

# What the fake engine reads, by message number: the upper line's two, then the lower line's three.
GAME_PAYS, LINE_1, GAME_OVER, PAYS_AGAIN, PLAY = 0, 1, 2, 3, 4
TEXTS = {GAME_PAYS: "Game Pays 4", LINE_1: "Line 1 Pays 2", GAME_OVER: "Game Over", PAYS_AGAIN: "Game Pays 4", PLAY: "Play 50 Credits"}

SPIN = [machine_line("stateSpin"), machine_line("stateReelSpinDone")]
FIRST_CYCLE = published_line("FirstCycleResultsIterationFinishedMsg", "GDK.Client.ClientMessaging")
GAME_OVER_LINE = published_line("GameOverMsg")


# ----------------------------------------------------------------------------------------------------- frames


BITS = 6  # messages 0-62: message m is drawn as the blocks of the bits of m + 1, so none is blank


def screenshot(upper: int | None, lower: int | None) -> bytes:
    """The game with a message on each line (white blocks that say which) or none."""
    image = Image.new("RGB", SIZE, (40, 10, 50))
    for name, message in (("cyclic_message", upper), ("cyclic_message_2", lower)):
        if message is not None:
            for bit in range(BITS):
                if (message + 1) >> bit & 1:
                    left, top = 4 + 18 * bit, BANDS[name] + 3
                    image.paste((230, 230, 230), (left, top, left + 14, top + 4))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def cycle(messages: list[int], *, show: int = 4, gap: int = 2, rounds: int = 3) -> list[int | None]:
    """A line cycling through `messages`, each shown for `show` frames with `gap` blank ones after it."""
    return [frame for _ in range(rounds) for message in messages for frame in [message] * show + [None] * gap]


def frames_of(upper: list[int | None], lower: list[int | None]) -> list[bytes]:
    """Frame by frame, each line holding its last state once its list runs out."""
    last = [upper[-1], lower[-1]]
    return [screenshot(*pair) for pair in zip_longest(upper, lower, fillvalue=None)] + [screenshot(*last)]


class ScriptedObs(FakeObs):
    """Every screenshot is the next of `frames` (the last one from then on); `hooks[n]` runs after the nth."""

    def __init__(self) -> None:
        super().__init__()
        self.frames: list[bytes] = [screenshot(None, None)]
        self.hooks: dict[int, Callable[[], None]] = {}
        self.shots = 0

    def handle(self, request_type: str, data: dict | None) -> dict:
        shot = request_type in ("SaveSourceScreenshot", "GetSourceScreenshot")
        if shot:
            self.shots += 1
            self.image = self.frames[min(self.shots, len(self.frames)) - 1]
        result = super().handle(request_type, data)
        if shot and (hook := self.hooks.get(self.shots)):
            hook()
        return result


class TextEngine:
    """Reads a message by the blocks it is drawn with; `failure` makes every read fail."""

    lanes = 2

    def __init__(self) -> None:
        self.preloaded = False
        self.failure: Exception | None = None

    @property
    def ready(self) -> bool:
        return self.preloaded

    def preload(self) -> None:
        self.preloaded = True

    def read_boxes(self, image: Image.Image):
        raise AssertionError("a message line is one line")

    def read_line(self, image: Image.Image) -> TextLine:
        if self.failure:
            raise self.failure
        bright = (np.asarray(image.convert("L")) >= 110).any(axis=0)
        number = sum(1 << bit for bit in range(BITS) if bright[4 + 18 * bit : 18 + 18 * bit].any())
        return TextLine(TEXTS.get(number - 1, f"Message {number - 1}"), 0.95) if number else TextLine("", 0.0)


# ------------------------------------------------------------------------------------------------------- rig


@pytest_asyncio.fixture
async def rig(tmp_path: Path, captures_dir: Path, config_file: Path, monkeypatch: pytest.MonkeyPatch):
    rois = dict(ROIS)
    real = game_settings.load_game_config

    def load(game: str):
        config = copy.deepcopy(real(game))
        if config is not None and game == GAME:
            config[GameMode.SIMULATOR.value]["roi"] = rois
        return config

    monkeypatch.setattr(game_settings, "load_game_config", load)
    monkeypatch.setattr(cyclic_service, "_IDLE_WAKEUP", 0.01)

    obs = ScriptedObs()
    obs_service = make_service(obs, captures_dir, config_file)
    await obs_service.connect()
    log = tmp_path / "Game_Client.log"
    log.write_bytes(b"")
    watcher = LogWatcher(lambda: log)
    watcher.poll()  # attaches at the end of the (empty) file
    context = GameContextService(state_file=tmp_path / "game_context.json")
    context.update_context(GameContextUpdate(game=GAME, mode=GameMode.SIMULATOR))
    engine = TextEngine()

    def build(**overrides) -> CyclicMessageService:
        # A frame takes ~15 ms here, so "steady" is ~15 of them: as long against the 3-frame gap between the game going
        # idle and the lower line's first message as FortuneOx's 5 s is against its ~2 s.
        settings = {"capture_interval": 0.01, "hold_capture_interval": 0.01, "steady_seconds": 0.25, **overrides}
        return CyclicMessageService(
            obs=obs_service, log=watcher, game_context=context, engine=engine, captures_dir=captures_dir, **settings
        )

    def send(*lines: str) -> Callable[[], None]:
        """What the game writes to its log, as a function so a hook can run it at a given frame."""

        def write() -> None:
            append(log, *lines)
            watcher.poll()

        return write

    service = build()
    rig = SimpleNamespace(
        obs=obs,
        obs_service=obs_service,
        watcher=watcher,
        context=context,
        engine=engine,
        rois=rois,
        build=build,
        send=send,
        service=service,
        captures_dir=captures_dir,
    )
    yield rig
    await service.stop()


async def until(condition: Callable[[], object], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        await asyncio.sleep(0.01)


def finished(service: CyclicMessageService) -> bool:
    rounds = service.list_rounds(1)
    return bool(rounds) and rounds[0].end_reason is not None


def texts(record: CyclicRound, region: str) -> list[str | None]:
    return [message.text for message in next(r for r in record.regions if r.name == region).messages]


def region(record: CyclicRound, name: str):
    return next(r for r in record.regions if r.name == name)


# ------------------------------------------------------------------------------------------------- a round


@pytest.mark.asyncio
async def test_a_winning_spin_is_captured_and_read(rig) -> None:
    # "Game Pays 4" then "Line 1 Pays 2" held while the win waits; once it is collected the lower line cycles.
    upper = [None] * 2 + [GAME_PAYS] * 4 + [LINE_1]
    lower = [None] * 12 + cycle([GAME_OVER, PAYS_AGAIN, PLAY])
    rig.obs.frames = frames_of(upper, lower)
    rig.obs.hooks[10] = rig.send(GAME_OVER_LINE)

    await rig.service.start()
    rig.send(*SPIN, result_line(won=True, amount="400.000"))()
    await until(lambda: finished(rig.service))

    record = rig.service.list_rounds(1)[0]
    assert record.end_reason == "complete"
    assert (record.won, record.win_amount) == (True, 400.0)
    assert [event.type for event in record.events] == ["result", "game_over"]
    assert texts(record, "cyclic_message") == ["Game Pays 4", "Line 1 Pays 2"]
    assert region(record, "cyclic_message").sequence == [0, 1]
    assert region(record, "cyclic_message").cycle == "steady"
    assert texts(record, "cyclic_message_2") == ["Game Over", "Game Pays 4", "Play 50 Credits"]
    assert region(record, "cyclic_message_2").sequence == [0, 1, 2, 0]
    assert region(record, "cyclic_message_2").cycle == "closed"
    lower_first = region(record, "cyclic_message_2").messages[0]
    assert (lower_first.appearances, lower_first.confidence, lower_first.read_error) == (2, 95.0, None)
    assert record.frames == rig.obs.shots


@pytest.mark.asyncio
async def test_a_losing_spin_has_messages_on_the_lower_line_only(rig) -> None:
    lower = [None] * 12 + cycle([GAME_OVER, PAYS_AGAIN, PLAY])
    rig.obs.frames = frames_of([None], lower)
    rig.obs.hooks[10] = rig.send(GAME_OVER_LINE)

    await rig.service.start()
    rig.send(*SPIN, result_line(won=False, amount="0.000"))()
    await until(lambda: finished(rig.service))

    record = rig.service.list_rounds(1)[0]
    assert record.end_reason == "complete"
    assert (record.won, record.win_amount) == (False, 0.0)
    assert region(record, "cyclic_message").messages == []
    assert region(record, "cyclic_message").cycle == "steady"
    assert texts(record, "cyclic_message_2") == ["Game Over", "Game Pays 4", "Play 50 Credits"]
    assert region(record, "cyclic_message_2").cycle == "closed"


@pytest.mark.asyncio
async def test_only_the_message_areas_are_kept_of_every_screenshot(rig) -> None:
    rig.obs.frames = frames_of([None], [None] * 12 + cycle([GAME_OVER, PAYS_AGAIN, PLAY]))
    rig.obs.hooks[10] = rig.send(GAME_OVER_LINE)

    await rig.service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: finished(rig.service))

    assert rig.obs.shots > 20
    assert list((rig.captures_dir / "screenshots").iterdir()) == []  # each was deleted once cut
    record = rig.service.list_rounds(1)[0]
    path = rig.service.image_path(record.id, "cyclic_message_2-0.png")
    with Image.open(path) as image:
        assert image.size == (120, 10)
    assert sorted(p.name for p in path.parent.iterdir()) == [
        "cyclic_message_2-0.png",
        "cyclic_message_2-1.png",
        "cyclic_message_2-2.png",
        "record.json",
    ]


@pytest.mark.asyncio
async def test_a_round_is_not_finished_while_the_win_waits_to_be_collected(rig) -> None:
    # The upper line holds "Line 1 Pays 2" and the lower one is blank, which looks steady, until the game is idle.
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], [None])

    await rig.service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: rig.obs.shots > 40)

    status = rig.service.status()
    assert status.phase == "capturing"
    assert status.current.end_reason is None
    assert status.current.frames >= 40

    rig.send(GAME_OVER_LINE)()
    await until(lambda: finished(rig.service))
    assert rig.service.list_rounds(1)[0].end_reason == "complete"


@pytest.mark.asyncio
async def test_the_next_spin_ends_the_round_that_was_being_captured(rig) -> None:
    rig.obs.frames = frames_of([None], [None] * 12 + cycle([GAME_OVER, PAYS_AGAIN, PLAY]))
    rig.obs.hooks[10] = rig.send(GAME_OVER_LINE)
    # The lower line's first message is on frames 13-16 and its second on 19-22: the next spin comes during the second.
    rig.obs.hooks[21] = rig.send(published_line("CycleResultsStoppedMsg_BaseGame"), machine_line("stateSpin"))

    await rig.service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: finished(rig.service))

    record = rig.service.list_rounds(1)[0]
    assert record.end_reason == "next_spin"
    assert [event.type for event in record.events][-1] == "cycle_stopped"
    assert region(record, "cyclic_message_2").cycle == "open"  # only part of the cycle was seen
    assert region(record, "cyclic_message_2").sequence == [0, 1]


@pytest.mark.asyncio
async def test_a_spin_whose_reels_never_stopped_leaves_no_round(rig) -> None:
    await rig.service.start()
    rig.send(machine_line("stateSpin"), machine_line("stateSpin"))()  # two machines entering it, say
    await until(lambda: rig.service.status().rounds == 2)
    await rig.service.stop()

    assert rig.service.list_rounds(10) == []


@pytest.mark.asyncio
async def test_tracking_that_begins_while_the_reels_turn_captures_from_when_they_stop(rig) -> None:
    rig.obs.frames = frames_of([None], [None] * 12 + cycle([GAME_OVER, PAYS_AGAIN, PLAY]))
    rig.obs.hooks[10] = rig.send(GAME_OVER_LINE)

    await rig.service.start()
    rig.send(machine_line("stateReelSpinDone"), result_line())()  # the spin began before tracking did
    await until(lambda: finished(rig.service))

    assert rig.service.list_rounds(1)[0].end_reason == "complete"


@pytest.mark.asyncio
async def test_a_win_that_is_never_collected_is_given_up_on(rig) -> None:
    service = rig.build(max_wait_for_idle_seconds=0.1)
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], [None])

    await service.start()
    rig.send(*SPIN, result_line())()  # the game never goes idle
    await until(lambda: finished(service))
    await service.stop()

    assert service.list_rounds(1)[0].end_reason == "timeout"


@pytest.mark.asyncio
async def test_a_round_that_is_idle_but_never_settles_is_given_up_on(rig) -> None:
    service = rig.build(max_idle_seconds=0.1)  # less than the lower line takes to come round, or to look steady
    rig.obs.frames = frames_of([None], [None] * 12 + cycle([GAME_OVER, PAYS_AGAIN, PLAY]))
    rig.obs.hooks[10] = rig.send(GAME_OVER_LINE)

    await service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: finished(service))
    await service.stop()

    record = service.list_rounds(1)[0]
    assert record.end_reason == "timeout"
    assert region(record, "cyclic_message_2").cycle == "open"


@pytest.mark.asyncio
async def test_a_win_waiting_to_be_collected_is_not_cut_short_by_the_limit_for_an_idle_round(rig) -> None:
    # The limit on a round once the game is idle is a hundredth of a second here, and a second passes before the win
    # is collected: a person collects it, so that wait has a limit of its own (10 minutes).
    service = rig.build(max_idle_seconds=0.01)
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], [None] * 80 + cycle([GAME_OVER, PAYS_AGAIN, PLAY]))
    rig.obs.hooks[70] = rig.send(GAME_OVER_LINE)
    await service.start()
    rig.send(*SPIN, result_line())()

    await until(lambda: rig.obs.shots > 60)

    assert service.status().phase == "capturing"
    assert service.status().current.end_reason is None
    await service.stop()


# ------------------------------------------------------------------------ the first pass over the lines


@pytest.mark.asyncio
async def test_the_lines_of_a_win_are_followed_for_one_loop_and_the_lower_line_once_the_win_is_collected(rig) -> None:
    # "Game Pays 4" and three lines, the game reporting the first pass done, then the lines going round again while
    # the win waits. Only when it is collected does the lower line start to cycle.
    upper = [None] * 2 + [GAME_PAYS] * 3 + [10] * 3 + [11] * 3 + [12] * 3 + [10] * 3 + [11] * 3 + [12] * 3
    lower = [None] * 40 + cycle([GAME_OVER, PAYS_AGAIN, PLAY])
    rig.obs.frames = frames_of(upper, lower)
    rig.obs.hooks[13] = rig.send(FIRST_CYCLE)  # the third line has been on show for a moment
    rig.obs.hooks[38] = rig.send(GAME_OVER_LINE)  # the win is collected

    await rig.service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: rig.obs.shots > 30)  # the second pass has been on the screen, and the win is still held

    held = rig.service.status().current
    assert rig.service.status().phase == "capturing"  # waiting for the win to be collected, not finished
    assert region(held, "cyclic_message").sequence == [0, 1, 2, 3]
    assert region(held, "cyclic_message").cycle == "closed"
    assert region(held, "cyclic_message_2").cycle == "open"

    await until(lambda: finished(rig.service))

    record = rig.service.list_rounds(1)[0]
    assert record.end_reason == "complete"
    assert [event.type for event in record.events] == ["result", "first_cycle_done", "game_over"]
    assert region(record, "cyclic_message").sequence == [0, 1, 2, 3]  # no second loop
    assert len(region(record, "cyclic_message").messages) == 4
    assert region(record, "cyclic_message_2").sequence == [0, 1, 2, 0]
    assert region(record, "cyclic_message_2").cycle == "closed"


@pytest.mark.asyncio
async def test_a_win_on_forty_lines_is_captured_for_one_pass_and_the_lower_line_after_it_is_collected(rig) -> None:
    lines = list(range(10, 50))
    upper = [None] * 2 + [GAME_PAYS] * 4 + [line for line in lines for _ in range(3)] * 2  # two passes
    last_line_shown = 6 + 3 * 39 + 1  # the frame on which the 40th line has been on show for a moment
    lower = [None] * 160 + cycle([GAME_OVER, PAYS_AGAIN, PLAY])
    rig.obs.frames = frames_of(upper, lower)
    rig.obs.hooks[last_line_shown] = rig.send(FIRST_CYCLE)
    rig.obs.hooks[158] = rig.send(GAME_OVER_LINE)  # collected during the second pass

    await rig.service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: finished(rig.service), timeout=30)

    record = rig.service.list_rounds(1)[0]
    upper_line = region(record, "cyclic_message")
    assert record.end_reason == "complete"
    assert upper_line.sequence == [0, *range(1, 41)]  # all of them, and not the second pass
    assert len(upper_line.messages) == 41
    assert [event.type for event in record.events] == ["result", "first_cycle_done", "game_over"]
    assert region(record, "cyclic_message_2").sequence == [0, 1, 2, 0]
    assert region(record, "cyclic_message_2").cycle == "closed"


@pytest.mark.asyncio
async def test_screenshots_are_taken_more_slowly_while_the_win_is_waited_for_and_at_once_at_full_pace_after(rig) -> None:
    service = rig.build(hold_capture_interval=0.25)
    rig.obs.frames = frames_of([None, GAME_PAYS, GAME_PAYS, LINE_1], [None])  # then held
    rig.obs.hooks[8] = rig.send(FIRST_CYCLE)

    await service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: rig.obs.shots >= 8)
    await asyncio.sleep(0.1)  # the event has been handled
    before = rig.obs.shots
    await asyncio.sleep(1.0)
    held = rig.obs.shots - before
    rig.send(GAME_OVER_LINE)()
    before = rig.obs.shots
    await asyncio.sleep(0.4)
    collected = rig.obs.shots - before
    await service.stop()

    assert 2 <= held <= 6  # about one every quarter of a second
    assert collected > 8  # about one every hundredth, less what each takes


@pytest.mark.asyncio
async def test_a_game_with_one_message_line_ends_its_round_with_the_first_loop_and_ignores_the_collection(rig) -> None:
    rig.rois["cyclic_message_2"] = []
    rig.obs.frames = frames_of([None, GAME_PAYS, GAME_PAYS, LINE_1], [None])
    rig.obs.hooks[8] = rig.send(FIRST_CYCLE)

    await rig.service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: finished(rig.service))

    assert rig.service.list_rounds(1)[0].end_reason == "complete"
    assert rig.service.status().phase == "waiting"

    rig.send(GAME_OVER_LINE)()  # the win is collected afterwards: nothing is left to capture, so it is not a round
    await asyncio.sleep(0.15)
    assert len(rig.service.list_rounds(10)) == 1
    assert rig.service.status().phase == "waiting"


@pytest.mark.asyncio
async def test_a_win_collected_during_its_first_pass_also_waits_for_the_line_that_starts_then(rig) -> None:
    lines = list(range(10, 50))
    upper = [None] * 2 + [GAME_PAYS] * 4 + [line for line in lines for _ in range(3)] * 2
    lower = [None] * 12 + cycle([GAME_OVER, PAYS_AGAIN, PLAY])  # comes round by frame ~31, long before the pass ends
    last_line_shown = 6 + 3 * 39 + 1
    rig.obs.frames = frames_of(upper, lower)
    rig.obs.hooks[10] = rig.send(GAME_OVER_LINE)
    rig.obs.hooks[last_line_shown] = rig.send(FIRST_CYCLE)

    await rig.service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: finished(rig.service), timeout=20)

    record = rig.service.list_rounds(1)[0]
    assert record.end_reason == "complete"
    assert [event.type for event in record.events] == ["result", "game_over", "first_cycle_done"]
    assert region(record, "cyclic_message").sequence == [0, *range(1, 41)]
    assert region(record, "cyclic_message").cycle == "closed"
    # The lower line came round long before, and kept cycling while the pass went on.
    assert region(record, "cyclic_message_2").sequence[:4] == [0, 1, 2, 0]
    assert region(record, "cyclic_message_2").cycle == "closed"


@pytest.mark.asyncio
async def test_a_win_collected_before_the_game_reports_its_first_pass_waits_for_the_idle_line(rig) -> None:
    # The game reports the pass over while the lower line is still cycling: that line is not part of the pass, so
    # the round goes on until it has come round, or held steady.
    lower = [None] * 8 + cycle([GAME_OVER, PAYS_AGAIN, PLAY])  # its first message comes after the game went idle
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], lower)
    rig.obs.hooks[6] = rig.send(GAME_OVER_LINE)
    rig.obs.hooks[8] = rig.send(FIRST_CYCLE)

    await rig.service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: finished(rig.service))

    record = rig.service.list_rounds(1)[0]
    assert record.end_reason == "complete"
    assert region(record, "cyclic_message_2").sequence == [0, 1, 2, 0]
    assert region(record, "cyclic_message_2").cycle == "closed"
    assert record.frames > 20


# -------------------------------------------------------------------------------- tracking that begins late


@pytest.mark.asyncio
async def test_tracking_started_while_a_win_is_held_captures_what_cycles_once_it_is_collected(rig) -> None:
    rig.obs.frames = frames_of([None], [None] * 3 + cycle([GAME_OVER, PAYS_AGAIN, PLAY]))
    await rig.service.start()  # the spin and its result went by before this

    rig.send(GAME_OVER_LINE)()  # the win is collected
    await until(lambda: finished(rig.service))

    record = rig.service.list_rounds(1)[0]
    assert record.end_reason == "complete"
    assert record.won is None  # its result was never seen
    assert [event.type for event in record.events] == ["game_over"]
    assert texts(record, "cyclic_message_2") == ["Game Over", "Game Pays 4", "Play 50 Credits"]
    assert region(record, "cyclic_message_2").cycle == "closed"


@pytest.mark.asyncio
async def test_a_win_collected_after_the_wait_gave_up_is_still_captured(rig) -> None:
    service = rig.build(max_wait_for_idle_seconds=0.05)
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], [None])
    await service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: finished(service))
    assert service.list_rounds(1)[0].end_reason == "timeout"

    rig.obs.shots = 0  # the next screenshots are of the lines cycling
    rig.obs.frames = frames_of([None], [None] * 3 + cycle([GAME_OVER, PAYS_AGAIN, PLAY]))
    rig.send(GAME_OVER_LINE)()
    await until(lambda: len(service.list_rounds(5)) == 2 and finished(service))
    await service.stop()

    rounds = service.list_rounds(5)
    assert [r.end_reason for r in rounds] == ["complete", "timeout"]
    assert region(rounds[0], "cyclic_message_2").cycle == "closed"


# ------------------------------------------------------------------------------------------ forty lines


@pytest.mark.asyncio
async def test_a_win_on_forty_lines_is_captured_whole(rig) -> None:
    lines = list(range(10, 50))  # message numbers of "Line 1" to "Line 40"
    upper = [None] * 2 + [GAME_PAYS] * 4 + [line for line in lines for _ in range(3)] * 2
    lower = [None] * 12 + cycle([GAME_OVER, PAYS_AGAIN, PLAY])
    rig.obs.frames = frames_of(upper, lower)
    rig.obs.hooks[10] = rig.send(GAME_OVER_LINE)

    await rig.service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: finished(rig.service), timeout=20)

    record = rig.service.list_rounds(1)[0]
    upper_line = region(record, "cyclic_message")
    # The lower line has come round long before, but the round waits for every line of the upper one to do so.
    assert record.end_reason == "complete"
    assert upper_line.cycle == "closed"
    assert len(upper_line.messages) == 41
    assert upper_line.sequence == [0, *range(1, 41), 1]
    assert [m.text for m in upper_line.messages[1:4]] == ["Message 10", "Message 11", "Message 12"]
    assert all(m.text for m in upper_line.messages)


@pytest.mark.asyncio
async def test_stopping_ends_the_round_and_later_spins_are_not_noticed(rig) -> None:
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], [None])

    await rig.service.start()
    rig.send(*SPIN, result_line())()
    await until(lambda: rig.service.status().phase == "capturing" and rig.obs.shots > 3)
    status = await rig.service.stop()

    assert (status.tracking, status.phase, status.current) == (False, "stopped", None)
    assert rig.service.list_rounds(1)[0].end_reason == "stopped"

    rig.send(*SPIN)()
    await asyncio.sleep(0.1)
    assert rig.service.status().rounds == 1
    assert len(rig.service.list_rounds(10)) == 1


@pytest.mark.asyncio
async def test_starting_twice_follows_the_log_once(rig) -> None:
    await rig.service.start()
    await rig.service.start()
    rig.send(machine_line("stateSpin"))()
    await until(lambda: rig.service.status().rounds >= 1)
    await asyncio.sleep(0.05)

    assert rig.service.status().rounds == 1


# --------------------------------------------------------------------------------------------- reading


@pytest.mark.asyncio
async def test_messages_are_read_while_the_capture_goes_on(rig) -> None:
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], [None])
    await rig.service.start()
    rig.send(*SPIN, result_line())()

    await until(lambda: rig.service.status().current and texts(rig.service.status().current, "cyclic_message") == ["Game Pays 4", "Line 1 Pays 2"])

    assert rig.service.status().phase == "capturing"  # still going
    assert rig.engine.preloaded


@pytest.mark.asyncio
async def test_a_message_the_ocr_cannot_read_says_why_and_the_capture_goes_on(rig) -> None:
    rig.engine.failure = OcrEngineError("The OCR models did not load in time")
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], [None])
    await rig.service.start()
    rig.send(*SPIN, result_line())()

    await until(lambda: (r := rig.service.list_rounds(1)) and all(m.read_error for m in region(r[0], "cyclic_message").messages) and len(region(r[0], "cyclic_message").messages) == 2)

    message = region(rig.service.list_rounds(1)[0], "cyclic_message").messages[0]
    assert (message.text, message.read_error) == (None, "The OCR models did not load in time")
    assert rig.service.status().phase == "capturing"


@pytest.mark.asyncio
async def test_a_failing_screenshot_is_reported_until_one_succeeds(rig) -> None:
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], [None])
    rig.obs.rejected["SaveSourceScreenshot"] = "OBS is busy"
    await rig.service.start()
    rig.send(*SPIN, result_line())()

    await until(lambda: rig.service.status().problem)
    assert "OBS is busy" in rig.service.status().problem
    assert rig.service.status().tracking

    del rig.obs.rejected["SaveSourceScreenshot"]
    await until(lambda: rig.service.status().problem is None and rig.obs.shots > 3)


# ------------------------------------------------------------------------------------------ refusals


@pytest.mark.asyncio
async def test_tracking_needs_obs(rig) -> None:
    await rig.obs_service.disconnect()

    with pytest.raises(ServiceUnavailableException, match="Connect first"):
        await rig.service.start()
    assert not rig.service.tracking


@pytest.mark.asyncio
async def test_a_game_without_cyclic_message_areas_is_refused(rig) -> None:
    rig.rois["cyclic_message"] = []
    rig.rois["cyclic_message_2"] = []

    with pytest.raises(NotFoundException, match="no cyclic message ROI"):
        await rig.service.start()
    assert not rig.service.tracking


@pytest.mark.asyncio
async def test_a_game_with_one_message_area_tracks_just_that(rig) -> None:
    rig.rois["cyclic_message_2"] = []
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], [None])
    await rig.service.start()
    rig.send(*SPIN, result_line())()

    await until(lambda: rig.service.status().current and rig.service.status().current.frames > 3)

    assert [r.name for r in rig.service.status().current.regions] == ["cyclic_message"]


@pytest.mark.asyncio
async def test_an_invalid_roi_is_refused(rig) -> None:
    rig.rois["cyclic_message"] = [0.5, 0.5, 0.2, 0.2]

    with pytest.raises(AppException) as error:
        await rig.service.start()
    assert error.value.error_code == "CONFIG_INVALID"


@pytest.mark.asyncio
async def test_an_unknown_game_is_not_found(rig) -> None:
    with pytest.raises(NotFoundException, match="no config"):
        await rig.service.start(game="Nope")


@pytest.mark.asyncio
async def test_changing_the_selected_game_stops_tracking(rig) -> None:
    await rig.service.start()
    assert rig.service.tracking

    rig.context.update_context(GameContextUpdate(game="HuffNPuffHighRise"))
    await until(lambda: not rig.service.tracking)

    assert "changed" in rig.service.status().problem


# ---------------------------------------------------------------------------------------------- records


@pytest.mark.asyncio
async def test_a_round_left_unfinished_by_a_stopped_backend_is_reported_as_interrupted(rig) -> None:
    directory = rig.captures_dir / "cyclic" / "cyc_20260930_120000_000_abcdef"
    directory.mkdir(parents=True)
    record = CyclicRound(id=directory.name, created_at="2026-09-30T12:00:00+05:30", game=GAME, mode=GameMode.SIMULATOR)
    (directory / "record.json").write_text(record.model_dump_json(), encoding="utf-8")

    assert rig.service.list_rounds(5)[0].end_reason == "interrupted"


@pytest.mark.asyncio
async def test_rounds_come_newest_first_and_honour_the_limit(rig) -> None:
    for stamp in ("120000", "130000", "110000"):
        directory = rig.captures_dir / "cyclic" / f"cyc_20260930_{stamp}_000_abcdef"
        directory.mkdir(parents=True)
        record = CyclicRound(
            id=directory.name, created_at="2026-09-30T12:00:00+05:30", game=GAME, mode=GameMode.SIMULATOR, end_reason="stopped"
        )
        (directory / "record.json").write_text(record.model_dump_json(), encoding="utf-8")
    (rig.captures_dir / "cyclic" / "cyc_20260930_140000_000_abcdef").mkdir()  # no record: not finished writing

    assert [r.id for r in rig.service.list_rounds(2)] == ["cyc_20260930_130000_000_abcdef", "cyc_20260930_120000_000_abcdef"]
    assert rig.service.list_rounds(10)[-1].id == "cyc_20260930_110000_000_abcdef"


@pytest.mark.asyncio
async def test_there_are_no_rounds_before_the_first_spin(rig) -> None:
    assert rig.service.list_rounds(10) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "round_id, filename",
    [
        ("../cyc_20260930_120000_000_abcdef", "cyclic_message-0.png"),
        ("cyc_20260930_120000_000_abcdef", "../record.json"),
        ("cyc_20260930_120000_000_abcdef", "record.json"),
        ("cyc_20260930_120000_000_abcdef", "missing.png"),
        ("not-an-id", "cyclic_message-0.png"),
    ],
)
async def test_only_the_images_of_a_round_can_be_fetched(rig, round_id: str, filename: str) -> None:
    directory = rig.captures_dir / "cyclic" / "cyc_20260930_120000_000_abcdef"
    directory.mkdir(parents=True)
    (directory / "record.json").write_text("{}", encoding="utf-8")

    with pytest.raises(NotFoundException):
        rig.service.image_path(round_id, filename)


# ------------------------------------------------------------------------------------------------- API


@pytest_asyncio.fixture
async def api(rig):
    """The routes on the same event loop as the tracking task (a TestClient call gets a loop of its own)."""
    app.dependency_overrides[get_cyclic_controller] = lambda: CyclicController(rig.service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_the_api_starts_tracking_reports_rounds_and_stops(rig, api) -> None:
    rig.obs.frames = frames_of([None, GAME_PAYS, LINE_1], [None])

    status = (await api.get(f"{URL}/status")).json()["data"]
    assert (status["tracking"], status["phase"], status["game"], status["mode"]) == (False, "stopped", GAME, "simulator")

    started = await api.post(f"{URL}/tracking/start", params={"game": GAME, "mode": "simulator"})
    assert started.status_code == 200
    assert (started.json()["data"]["tracking"], started.json()["data"]["phase"]) == (True, "waiting")

    rig.send(*SPIN, result_line())()
    await until(lambda: rig.obs.shots > 5)
    current = (await api.get(f"{URL}/status")).json()["data"]
    assert current["phase"] == "capturing"
    assert current["current"]["won"] is True

    stopped = (await api.post(f"{URL}/tracking/stop")).json()["data"]
    assert (stopped["tracking"], stopped["phase"]) == (False, "stopped")

    rounds = (await api.get(f"{URL}/rounds", params={"limit": 5})).json()["data"]
    assert [r["end_reason"] for r in rounds] == ["stopped"]
    image = await api.get(f"/api/v1{rounds[0]['regions'][0]['messages'][0]['url']}")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert json.loads((rig.captures_dir / "cyclic" / rounds[0]["id"] / "record.json").read_text(encoding="utf-8"))["id"] == rounds[0]["id"]


@pytest.mark.asyncio
async def test_the_api_reports_why_tracking_cannot_start(rig, api) -> None:
    await rig.obs_service.disconnect()

    response = await api.post(f"{URL}/tracking/start")

    assert response.status_code == 503
    assert response.json()["success"] is False
    assert "Connect first" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_the_api_refuses_an_image_that_is_not_there(rig, api) -> None:
    response = await api.get(f"{URL}/rounds/cyc_20260930_120000_000_abcdef/images/cyclic_message-0.png")

    assert response.status_code == 404
