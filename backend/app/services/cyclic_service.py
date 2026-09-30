import asyncio
import logging
import os
import re
import shutil
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from app.core.exceptions import AppException, NotFoundException, ServiceUnavailableException
from app.schemas.cyclic import (
    CyclicEvent,
    CyclicMessage,
    CyclicRegion,
    CyclicRound,
    CyclicStatus,
    EndReason,
    EventType,
    Phase,
)
from app.schemas.game_context import GameMode
from app.schemas.obs import ScreenshotInfo
from app.services.game_context_service import GameContextService
from app.services.obs_service import ObsService
from app.utils import game_config as game_settings
from app.utils.cyclic_messages import CycleState, RegionTracker, ShownMessage
from app.utils.image_crop import CropBox, InvalidCropError, crop_fraction
from app.utils.log_watcher import LogEvent, LogEventType, LogWatcher
from app.utils.ocr_engine import OcrEngine, OcrEngineError

logger = logging.getLogger(__name__)

# The game-config ROIs that are the two cyclic message lines.
REGIONS = ("cyclic_message", "cyclic_message_2")

# Seconds between screenshots. FortuneOx shows each message for ~1.5 s with ~0.5 s of nothing between, so a
# screenshot every 0.3 s sees each one about five times.
CAPTURE_INTERVAL = 0.3
# A win is held until it is collected, which a person may take a while over, so a round waits this long (seconds
# after its reels stopped) for the game to go idle. Nothing is lost by waiting: the messages that matter most
# cycle once it has.
MAX_WAIT_FOR_IDLE_SECONDS = 600.0
# Once the game is idle every area should have been seen cycling or holding steady within this long. A win can pay
# on 40 lines, each shown for ~2 s, so its first line only comes round again after ~80 s.
MAX_IDLE_SECONDS = 300.0
# After the game goes idle, an area that shows the same for this long has a single message (or none). Messages
# change every ~2 s, so this is more than two of them.
STEADY_SECONDS = 5.0
# Seconds between screenshots while a win waits to be collected after the game has reported the first pass over its
# lines done: nothing more can change in them, and the lower line, blank until the win is collected, shows each
# message for ~1.5 s. The moment the win is collected the capture goes back to `capture_interval`.
HOLD_CAPTURE_INTERVAL = 1.0
# How often the game selection is looked at while waiting for something to happen.
_IDLE_WAKEUP = 1.0

_RECORD_ID = re.compile(r"^cyc_\d{8}_\d{6}_\d{3}_[0-9a-f]{6}$")
_RECORD_FILE = "record.json"
_IMAGE_SUFFIX = ".png"

_EVENT_TYPES: dict[LogEventType, EventType] = {
    LogEventType.RESULT: "result",
    LogEventType.CYCLE_FIRST_ITERATION_DONE: "first_cycle_done",
    LogEventType.CYCLE_STOPPED: "cycle_stopped",
    LogEventType.GAME_OVER: "game_over",
}


@dataclass(frozen=True)
class _Target:
    game: str
    mode: GameMode
    regions: dict[str, CropBox]  # the message areas the game has, by config name


class _Live:
    """A round being captured. Times are seconds since its reels stopped, on the monotonic clock."""

    def __init__(self, record: CyclicRound, regions: list[str], directory: Path) -> None:
        self.record = record
        self.directory = directory
        self.trackers = {name: RegionTracker() for name in regions}
        self.capture_started: float | None = None  # when the reels stopped; None while they spin
        self.game_over_at: float | None = None
        self.first_loop_done = False  # the game said the first pass over the winning lines has finished
        # The areas that showed the win's lines, known once it has: their first loop is over, so they are not
        # followed into a second one.
        self.win_regions: frozenset[str] = frozenset()
        self.ended = False

    def since(self) -> float:
        return 0.0 if self.capture_started is None else time.monotonic() - self.capture_started


class CyclicMessageService:
    """Watches the cyclic messages of every spin while tracking is on.

    The game's log says when a spin starts and its reels stop, whether it won, and when the game is idle again.
    From the moment the reels stop, the message areas are screenshotted every `capture_interval` seconds (only
    they are kept, cut out of the screenshot), the distinct messages are told apart by their pixels, and each new
    one is read with OCR in the background while the capture goes on. Every area is followed for one loop: the
    areas that showed the win's lines stop when the game's log says the first pass over them is done (whether or
    not the win has been collected), and the others once they have come round or held steady after the game went
    idle, which for the lower line only happens after the win is collected. A round ends when all of them have, or
    when the next spin starts.

    Each round is a folder `<captures_dir>/cyclic/<id>` with the image of each distinct message and a
    `record.json`, which is written as the round grows. Everything here runs on the event loop; only the
    screenshot cutting and the OCR run in threads."""

    def __init__(
        self,
        *,
        obs: ObsService,
        log: LogWatcher,
        game_context: GameContextService,
        engine: OcrEngine,
        captures_dir: Path,
        capture_interval: float = CAPTURE_INTERVAL,
        hold_capture_interval: float = HOLD_CAPTURE_INTERVAL,
        max_wait_for_idle_seconds: float = MAX_WAIT_FOR_IDLE_SECONDS,
        max_idle_seconds: float = MAX_IDLE_SECONDS,
        steady_seconds: float = STEADY_SECONDS,
    ) -> None:
        self._obs = obs
        self._log = log
        self._game_context = game_context
        self._engine = engine
        self._rounds_dir = captures_dir / "cyclic"
        self._interval = capture_interval
        self._hold_interval = max(capture_interval, hold_capture_interval)
        self._max_wait_for_idle = max_wait_for_idle_seconds
        self._max_idle = max_idle_seconds
        self._steady_seconds = steady_seconds
        self._pool = ThreadPoolExecutor(max_workers=max(1, engine.lanes), thread_name_prefix="cyclic-ocr")
        self._task: asyncio.Task | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._live: _Live | None = None
        # A spin was seen and the game has not gone idle since, so the win it left is the one being waited for.
        self._expecting_game_over = False
        self._rounds = 0
        self._problem: str | None = None
        self._last_problem: str | None = None
        self._next_tick = 0.0
        self._reads: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ public

    @property
    def tracking(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, game: str | None = None, mode: GameMode | None = None) -> CyclicStatus:
        """Starts tracking (game and mode default to the selected). Does nothing if it is already on. The config
        and OBS are checked first, so a game that cannot be tracked never starts."""
        if self.tracking:
            return self.status()
        target = self._plan(game, mode)
        if not self._obs.connected:
            raise ServiceUnavailableException("Not connected to OBS. Connect first.")
        if game_settings.game_log_path(target.game, target.mode.value) is None:
            raise NotFoundException(f"'{target.game}' has no log configured for mode '{target.mode.value}'")
        self._engine.preload()  # the models take a while to load, and the first message needs them
        self._problem = self._last_problem = None
        self._rounds = 0
        self._expecting_game_over = False
        # Following the log starts now, not when the task first runs, so no event between the two is missed.
        loop = asyncio.get_running_loop()
        events: asyncio.Queue[LogEvent] = asyncio.Queue()

        def on_event(event: LogEvent) -> None:  # the log watcher's thread
            try:
                loop.call_soon_threadsafe(events.put_nowait, event)
            except RuntimeError:  # the loop is gone: the server is shutting down
                pass

        self._unsubscribe = self._log.subscribe(on_event)
        self._task = loop.create_task(self._run(target, events), name="cyclic-tracking")
        return self.status()

    async def stop(self) -> CyclicStatus:
        """Stops tracking; the round being captured is ended and kept. Messages still being read are finished."""
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._stop_following()  # a task cancelled before it ever ran has not done it
        return self.status()

    def status(self) -> CyclicStatus:
        selection = self._game_context.get_context().context
        live = self._live
        phase: Phase = "stopped"
        if self.tracking:
            phase = "waiting" if live is None else "spinning" if live.capture_started is None else "capturing"
        log_path = game_settings.active_log_path(self._game_context)
        following = log_path is not None and self._log.path == log_path
        current = None
        if live is not None:
            self._sync(live)
            current = live.record.model_copy(deep=True)
        return CyclicStatus(
            tracking=self.tracking,
            game=selection.game,
            mode=selection.mode,
            phase=phase,
            rounds=self._rounds,
            current=current,
            log_path=str(log_path) if log_path else None,
            log_unreadable=following and self._log.unreadable,
            problem=self._problem,
            ocr_ready=self._engine.ready,
        )

    def list_rounds(self, limit: int) -> list[CyclicRound]:
        """Newest first, the one being captured included."""
        try:
            with os.scandir(self._rounds_dir) as entries:
                ids = sorted((e.name for e in entries if e.is_dir()), reverse=True)
        except FileNotFoundError:
            return []
        live_id = self._live.record.id if self._live else None
        rounds: list[CyclicRound] = []
        for round_id in ids:
            record = self._read_record(round_id)
            if record is None:  # a folder without a readable record is an unfinished one
                continue
            if record.end_reason is None and round_id != live_id:
                record.end_reason = "interrupted"  # the backend stopped while it was being captured
            rounds.append(record)
            if len(rounds) == limit:
                break
        return rounds

    def image_path(self, round_id: str, filename: str) -> Path:
        # Only ids and bare file names of ours are accepted, so a request can never leave the folder.
        path = self._rounds_dir / round_id / filename
        if (
            not _RECORD_ID.match(round_id)
            or Path(filename).name != filename
            or path.suffix != _IMAGE_SUFFIX
            or not path.is_file()
        ):
            raise NotFoundException("Cyclic message image not found")
        return path

    # ---------------------------------------------------------------- planning

    def _plan(self, game: str | None, mode: GameMode | None) -> _Target:
        selection = self._game_context.get_context().context
        game, mode = game or selection.game, mode or selection.mode
        config = game_settings.load_game_config(game) if game else None
        if config is None:
            raise NotFoundException(f"Game '{game}' has no config")
        section = config.get(mode.value)
        rois = section.get("roi") if isinstance(section, dict) else None
        rois = rois if isinstance(rois, dict) else {}
        regions: dict[str, CropBox] = {}
        for name in REGIONS:
            if not rois.get(name):  # e.g. "cyclic_message": [] for a game without that message
                continue
            try:
                regions[name] = CropBox.from_sequence(rois[name])
            except InvalidCropError as exc:
                raise AppException(
                    f"ROI '{name}' of mode '{mode.value}' in the config of '{game}' is invalid: {exc}",
                    error_code="CONFIG_INVALID",
                ) from exc
        if not regions:
            raise NotFoundException(f"'{game}' has no cyclic message ROI configured for mode '{mode.value}'")
        return _Target(game=game, mode=mode, regions=regions)

    def _still_selected(self, target: _Target) -> bool:
        selection = self._game_context.get_context().context
        return (selection.game, selection.mode) == (target.game, target.mode)

    # ----------------------------------------------------------------- tracking

    async def _run(self, target: _Target, events: asyncio.Queue[LogEvent]) -> None:
        try:
            while True:
                event = await self._next_event(events)
                if not self._still_selected(target):
                    self._problem = "Tracking stopped because the selected game or mode changed."
                    return
                if event is not None:
                    self._handle(target, event)
                live = self._live
                if live is not None and live.capture_started is not None:
                    self._check_end(live)  # the log may just have said the round is over: no more screenshots then
                    if self._live is live and time.monotonic() >= self._next_tick:
                        await self._capture(target, live)
                        self._next_tick = max(self._next_tick + self._interval_of(live), time.monotonic())
                        self._check_end(live)
        except Exception as exc:  # a bug or a full disk must not leave tracking looking alive
            logger.exception("Cyclic message tracking failed")
            self._problem = f"Tracking stopped: {exc}"
        finally:
            self._stop_following()
            self._end_round("stopped")

    def _interval_of(self, live: _Live) -> float:
        """Seconds to the next screenshot."""
        waiting_for_the_win = bool(live.win_regions) and live.game_over_at is None
        return self._hold_interval if waiting_for_the_win else self._interval

    def _stop_following(self) -> None:
        unsubscribe, self._unsubscribe = self._unsubscribe, None
        if unsubscribe is not None:
            unsubscribe()

    async def _next_event(self, events: asyncio.Queue[LogEvent]) -> LogEvent | None:
        """The next log event, or None once it is time to take a screenshot (or look around)."""
        try:
            return events.get_nowait()
        except asyncio.QueueEmpty:
            pass
        wait = _IDLE_WAKEUP
        live = self._live
        if live is not None and live.capture_started is not None:
            wait = min(wait, max(0.0, self._next_tick - time.monotonic()))
        if wait <= 0:
            await asyncio.sleep(0)  # let other requests run
            return None
        try:
            return await asyncio.wait_for(events.get(), wait)
        except TimeoutError:
            return None

    def _handle(self, target: _Target, event: LogEvent) -> None:
        kind, live = event.type, self._live
        if kind is LogEventType.SPIN_START:
            self._end_round("next_spin")
            self._open(target)
            self._expecting_game_over = True
        elif kind is LogEventType.SPIN_END:
            live = live or self._open(target)  # tracking began while the reels were already turning
            self._expecting_game_over = True
            if live.capture_started is None:
                live.capture_started = self._next_tick = time.monotonic()
        elif kind is LogEventType.GAME_OVER and live is None:
            # A round that finished (or gave up) on seeing the first pass over the lines is not started again by the
            # win being collected afterwards. One is started when no spin was seen: tracking began while a win was
            # waiting to be collected, and its messages cycle from here, so they are captured from here.
            if not self._expecting_game_over:
                live = self._open(target)
                live.capture_started = live.game_over_at = self._next_tick = time.monotonic()
                live.record.events.append(CyclicEvent(type="game_over", at=0.0, log_time=event.log_time))
                self._save_live(live)
            self._expecting_game_over = False
        elif live is not None and kind in _EVENT_TYPES:
            if kind is LogEventType.RESULT:
                live.record.won, live.record.win_amount = event.won, event.win_amount
            elif kind is LogEventType.CYCLE_FIRST_ITERATION_DONE and not live.first_loop_done:
                live.first_loop_done = True
                # The areas that changed at least once before the game went idle were cycling the win's lines; one that
                # showed a single message then (what is left over when the reels stop) was not.
                idle_since = self._idle_since(live)
                cutoff = float("inf") if idle_since is None else idle_since
                live.win_regions = frozenset(
                    name for name, tracker in live.trackers.items() if tracker.appearances_before(cutoff) >= 2
                )
            elif kind is LogEventType.GAME_OVER:
                self._expecting_game_over = False
                if live.game_over_at is None:
                    live.game_over_at = self._next_tick = time.monotonic()  # back to the fast pace at once
            live.record.events.append(
                CyclicEvent(type=_EVENT_TYPES[kind], at=round(live.since(), 2), log_time=event.log_time)
            )
            self._save_live(live)

    def _open(self, target: _Target) -> _Live:
        created = datetime.now().astimezone()
        round_id = f"cyc_{created:%Y%m%d_%H%M%S_%f}"[:-3] + f"_{uuid.uuid4().hex[:6]}"
        record = CyclicRound(
            id=round_id,
            created_at=created,
            game=target.game,
            mode=target.mode,
            regions=[CyclicRegion(name=name, roi=list(box.as_tuple())) for name, box in target.regions.items()],
        )
        live = _Live(record, list(target.regions), self._rounds_dir / round_id)
        live.directory.mkdir(parents=True, exist_ok=True)
        self._live = live
        self._rounds += 1
        return live

    # ---------------------------------------------------------------- capturing

    async def _capture(self, target: _Target, live: _Live) -> None:
        """One screenshot: the message areas cut out of it are shown to their trackers."""
        try:
            shot = await self._obs.take_screenshot()
        except AppException as exc:
            self._fail(exc.message)
            return
        at = time.monotonic() - live.capture_started
        try:
            crops = await asyncio.to_thread(self._cut, shot, target.regions)
        except (OSError, InvalidCropError, AppException) as exc:  # includes an image Pillow cannot read
            self._fail(f"Could not cut the message areas out of the screenshot: {exc}")
            return
        self._problem = self._last_problem = None
        live.record.frames += 1
        live.record.seconds = round(at, 1)
        found = False
        for name, image in crops.items():
            if name in live.win_regions:
                continue  # its first loop is over
            shown = live.trackers[name].add(at, image)
            if shown is not None:
                self._keep(live, name, shown, image)
                found = True
        if found:
            self._save_live(live)

    def _cut(self, shot: ScreenshotInfo, regions: dict[str, CropBox]) -> dict[str, Image.Image]:
        """The areas of a screenshot. The screenshot itself is deleted: they are all that is wanted of it, and
        one is taken every few tenths of a second."""
        path = self._obs.screenshot_path(shot.filename)
        try:
            with Image.open(path) as full:
                full.load()
                return {name: crop_fraction(full, box) for name, box in regions.items()}
        finally:
            try:
                path.unlink()
            except OSError:
                pass

    def _keep(self, live: _Live, region: str, shown: ShownMessage, image: Image.Image) -> None:
        """A message this area has not shown before: its image is saved and the OCR reads it."""
        filename = f"{region}-{shown.index}{_IMAGE_SUFFIX}"  # "-": cyclic_message_2-0 is not cyclic_message-2
        image.save(live.directory / filename)
        message = CyclicMessage(
            url=f"/cyclic/rounds/{live.record.id}/images/{filename}",
            width=image.width,
            height=image.height,
            index=shown.index,
            first_seen=round(shown.first_seen, 2),
            appearances=shown.appearances,
        )
        next(r for r in live.record.regions if r.name == region).messages.append(message)
        task = asyncio.get_running_loop().create_task(self._read(live, message, image))
        self._reads.add(task)
        task.add_done_callback(self._reads.discard)

    async def _read(self, live: _Live, message: CyclicMessage, image: Image.Image) -> None:
        """Reads one message in the OCR's own threads, so the capture goes on meanwhile."""
        try:
            line = await asyncio.get_running_loop().run_in_executor(self._pool, self._engine.read_line, image)
        except OcrEngineError as exc:
            message.read_error = str(exc)
        except Exception as exc:  # whatever the engine raises must not go unseen
            logger.exception("Reading a cyclic message failed")
            message.read_error = f"The OCR failed: {exc}"
        else:
            message.text = line.text
            message.confidence = round(line.score * 100, 1) if line.text else None
        self._save(live.record)

    def _fail(self, problem: str) -> None:
        self._problem = problem
        if problem != self._last_problem:  # a repeating failure is logged once
            logger.warning("Cyclic message capture: %s", problem)
            self._last_problem = problem

    # ------------------------------------------------------------------ rounds

    def _idle_since(self, live: _Live) -> float | None:
        """When the game went idle, on the round's clock; None while it has not (a win waits to be collected)."""
        return None if live.game_over_at is None else live.game_over_at - live.capture_started

    def _region_state(
        self, live: _Live, name: str, tracker: RegionTracker, now: float, idle_since: float | None
    ) -> CycleState | None:
        """How far one area's first loop is known: what the tracker can tell from the pictures, and for the areas that
        showed the win's lines the game's own report that the first pass over them is over."""
        if name in live.win_regions:
            return "closed"
        return tracker.state(now, idle_since, self._steady_seconds)

    def _check_end(self, live: _Live) -> None:
        now = live.since()
        idle_since = self._idle_since(live)
        # The lines of the win are done with once the game says so, but the lower line only starts when the win is
        # collected, and is waited for: the round goes on until it has had its loop.
        if all(self._region_state(live, name, t, now, idle_since) for name, t in live.trackers.items()):
            self._end_round("complete")
        elif idle_since is None:
            if now >= self._max_wait_for_idle:
                self._end_round("timeout")
        elif now - idle_since >= self._max_idle:
            self._end_round("timeout")

    def _end_round(self, reason: EndReason) -> None:
        live = self._live
        if live is None:
            return
        self._live = None
        if live.capture_started is None:  # the reels never stopped (the spin was cut short): nothing was captured
            shutil.rmtree(live.directory, ignore_errors=True)
            return
        self._sync(live)
        live.ended = True
        live.record.end_reason = reason
        if reason == "timeout" and live.game_over_at is None:
            self._expecting_game_over = False  # gave up waiting for the win: collecting it is captured as a round
        self._save(live.record)

    def _sync(self, live: _Live) -> None:
        """Brings the record up to what the trackers know. A round that has ended is left as it ended."""
        if live.ended or live.capture_started is None:
            return
        now = live.since()
        idle_since = self._idle_since(live)
        live.record.seconds = round(now, 1)
        for region in live.record.regions:
            tracker = live.trackers[region.name]
            region.sequence = list(tracker.sequence)
            region.cycle = self._region_state(live, region.name, tracker, now, idle_since) or "open"
            for message in region.messages:
                message.appearances = tracker.messages[message.index].appearances

    def _save_live(self, live: _Live) -> None:
        self._sync(live)
        self._save(live.record)

    # ----------------------------------------------------------------- records

    def _read_record(self, round_id: str) -> CyclicRound | None:
        try:
            text = (self._rounds_dir / round_id / _RECORD_FILE).read_text(encoding="utf-8")
            return CyclicRound.model_validate_json(text)
        except (OSError, ValueError):
            return None

    def _save(self, record: CyclicRound) -> None:
        # Atomically: a reader never sees half a file. A round that cannot be saved is reported, not fatal.
        directory = self._rounds_dir / record.id
        tmp_file = directory / f"{_RECORD_FILE}.tmp"
        try:
            tmp_file.write_text(record.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp_file, directory / _RECORD_FILE)
        except OSError as exc:
            self._fail(f"Could not save the round: {exc}")
