"""Polls a game client log (often on an SMB share) for paytable changes and spin starts/ends.
Files are opened per pass with delete-sharing so the game can rotate them, on a thread per log."""

import logging
import os
import re
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

_PAYTABLE = (
    rb"\[WagerGameApp\.UpdatePayTable\] current denom\[(?P<denom>[\d.]+)\]"
    rb" current paytableId\[(?P<paytable>[^\]]+)\]"
    rb"(?: current supported denoms\[(?P<supported>[^\]]*)\])?"
)
# Any state machine (base game, free spins, feature respins) entering these GDK states:
# reels start spinning / reels have stopped.
_SPIN = (
    rb"StateMachine\[(?P<machine>\w+)\] transitioned from \[\w+\]"
    rb" to \[(?P<state>stateSpin|stateReelSpinDone)\] on event"
)
_PAYTABLE_RE = re.compile(_PAYTABLE)
_EVENT_RE = re.compile(_PAYTABLE + b"|" + _SPIN)

_TIME_LENGTH = 21  # "09/01/26 15:20:44.848" at the start of every log line
_TIME_FORMAT = "%m/%d/%y %H:%M:%S.%f"

_FILE_SHARE_ALL = 0x1 | 0x2 | 0x4  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE

_MAX_READ = 1024 * 1024  # bytes read per step, so catching up on a big backlog stays bounded
_HISTORY_CHUNK = 256 * 1024
_HISTORY_OVERLAP = 1024  # longer than any paytable line, so a line cut by a chunk edge is seen whole


class LogEventType(str, Enum):
    PAYTABLE = "paytable"
    SPIN_START = "spin_start"
    SPIN_END = "spin_end"


@dataclass(frozen=True, slots=True)
class LogEvent:
    type: LogEventType
    # Game machine's clock, as written in the log; None if the line has an unexpected format.
    log_time: datetime | None
    # PAYTABLE events:
    paytable_id: str | None = None
    denom: float | None = None
    supported_denoms: tuple[float, ...] = ()
    # SPIN_START / SPIN_END events: which state machine spun (base game, free spins, ...).
    state_machine: str | None = None


@dataclass(frozen=True, slots=True)
class LogState:
    """What the log has shown so far. Replaced, never mutated, so a read is always consistent."""

    paytable_id: str | None = None
    denom: float | None = None
    supported_denoms: tuple[float, ...] = ()
    spinning: bool = False


class LogWatcher:
    """Follows the log `path_provider` returns (asked every pass; `state` restarts when it changes).
    Listeners run on a reader thread and get live events only; earlier paytables are in `state`."""

    def __init__(
        self,
        path_provider: Callable[[], Path | None],
        *,
        poll_interval: float = 0.25,
        history_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self._path_provider = path_provider
        self._poll_interval = poll_interval
        self._history_bytes = history_bytes
        self._listeners: tuple[Callable[[LogEvent], None], ...] = ()
        self._state = LogState()
        self._lock = threading.Lock()  # guards switching logs against late events of the old one
        self._path: Path | None = None
        self._tail: _Tail | None = None
        self._follower: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_error: str | None = None

    # ------------------------------------------------------------------ public

    @property
    def state(self) -> LogState:
        return self._state

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def unreadable(self) -> bool:
        """True while the last attempt to read the current log failed (missing file, dead share)."""
        tail = self._tail
        return tail is not None and tail.unreadable

    def subscribe(self, listener: Callable[[LogEvent], None]) -> Callable[[], None]:
        """Registers `listener` for every event; returns a function that removes it again."""
        self._listeners += (listener,)

        def unsubscribe() -> None:
            self._listeners = tuple(item for item in self._listeners if item is not listener)

        return unsubscribe

    def start(self) -> None:
        if self._follower is not None and self._follower.is_alive():
            return
        self._stop = threading.Event()
        self._follower = threading.Thread(
            target=self._follow_loop, args=(self._stop,), name="log-watcher", daemon=True
        )
        self._follower.start()

    def stop(self) -> None:
        """Stops watching. No event is delivered once this returns."""
        self._stop.set()
        if self._follower is not None:
            self._follower.join(timeout=self._poll_interval + 2)
            self._follower = None
        self._switch(None)

    def poll(self) -> None:
        """Runs one pass on the calling thread; for tests and scripts that don't `start()`."""
        self._follow()
        if self._tail is not None:
            self._tail.poll()

    # ---------------------------------------------------------------- internals

    def _follow_loop(self, stop: threading.Event) -> None:
        while True:
            self._attempt(self._follow)
            if stop.wait(self._poll_interval):
                return

    def _read_loop(self, tail: "_Tail") -> None:
        while not tail.cancelled.is_set():
            self._attempt(tail.poll)
            if tail.cancelled.wait(self._poll_interval):
                return

    def _attempt(self, step: Callable[[], None]) -> None:
        try:
            step()
        except Exception as exc:  # keep watching; log a repeating failure only once
            if repr(exc) != self._last_error:
                logger.exception("Log watcher pass failed")
                self._last_error = repr(exc)
        else:
            self._last_error = None

    def _follow(self) -> None:
        path = self._path_provider()
        if path != self._path:
            self._switch(path)

    def _switch(self, path: Path | None) -> None:
        """Moves to another log: the old reader is abandoned and nothing is known yet."""
        if path != self._path:
            logger.info("Watching game log: %s", path)
        tail = _Tail(self, path, self._history_bytes) if path is not None else None
        with self._lock:
            if self._tail is not None:
                self._tail.cancelled.set()
            self._path, self._tail, self._state = path, tail, LogState()
        if tail is not None and not self._stop.is_set() and self._follower is not None:
            threading.Thread(target=self._read_loop, args=(tail,), name="log-tail", daemon=True).start()

    def _on_event(self, tail: "_Tail", event: LogEvent, *, live: bool) -> None:
        with self._lock:
            if tail.cancelled.is_set():
                return
            if event.type is LogEventType.PAYTABLE:
                self._state = replace(
                    self._state,
                    paytable_id=event.paytable_id,
                    denom=event.denom,
                    supported_denoms=event.supported_denoms,
                )
            else:
                self._state = replace(self._state, spinning=event.type is LogEventType.SPIN_START)
        if live:
            for listener in self._listeners:
                try:
                    listener(event)
                except Exception:
                    logger.exception("Log watcher listener failed")

    def _on_restart(self, tail: "_Tail") -> None:
        with self._lock:
            if not tail.cancelled.is_set():
                self._state = replace(self._state, spinning=False)


class _Tail:
    """Reads one log file incrementally. Only one thread runs `poll` at a time."""

    def __init__(self, owner: LogWatcher, path: Path, history_bytes: int) -> None:
        self.cancelled = threading.Event()
        self._owner = owner
        self._path = path
        self._history_bytes = history_bytes
        self._offset: int | None = None  # None: this file has not been looked at yet
        self._file_id: tuple[int, int] | None = None
        self.unreadable = False  # the last attempt to open or read the file failed

    def poll(self) -> None:
        try:
            with _open_shared(self._path) as file:
                if not self.cancelled.is_set():  # the open may have hung until long after a switch
                    self._read_new(file)
        except OSError as exc:
            if self.cancelled.is_set():
                return
            if not self.unreadable:
                self.unreadable = True
                logger.warning("Cannot read game log %s: %s", self._path, exc)
            if isinstance(exc, FileNotFoundError) and self._offset is None:
                self._offset = 0  # not created yet: read it from the start once the game makes it
        else:
            self.unreadable = False

    def _read_new(self, file: BinaryIO) -> None:
        info = os.fstat(file.fileno())
        size = info.st_size
        file_id = (info.st_dev, info.st_ino) if info.st_ino else None

        if self._offset is None:
            # First look at an existing log: what is in it is history, only new lines count.
            self._offset, self._file_id = size, file_id
            found = _last_paytable(file, size, self._history_bytes)
            if found is not None:
                self._owner._on_event(self, found, live=False)
            return

        if file_id != self._file_id or size < self._offset:
            logger.info("Game log was replaced or truncated; reading it from the start")
            self._offset, self._file_id = 0, file_id
            self._owner._on_restart(self)

        while self._offset < size:
            file.seek(self._offset)
            data = file.read(min(size - self._offset, _MAX_READ))
            end = data.rfind(b"\n") + 1  # only whole lines; a half-written one is re-read next pass
            if end == 0:
                if len(data) < _MAX_READ:
                    return
                end = len(data)  # a "line" longer than the read window: skip it, don't stall
            for match in _EVENT_RE.finditer(data, 0, end):
                self._owner._on_event(self, _make_event(data, match), live=True)
            self._offset += end


def _open_shared(path: Path) -> BinaryIO:
    """Opens `path` for reading without ever getting in the way of the process writing it."""
    if sys.platform != "win32":
        return open(path, "rb", buffering=0)
    import _winapi
    import msvcrt

    handle = _winapi.CreateFile(
        str(path),
        _winapi.GENERIC_READ,
        _FILE_SHARE_ALL,
        0,
        _winapi.OPEN_EXISTING,
        0,
        0,
    )
    return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), "rb", buffering=0)


def _last_paytable(file: BinaryIO, size: int, limit: int) -> LogEvent | None:
    """Finds the most recent paytable line by reading backwards from the end, at most `limit` bytes."""
    floor = max(0, size - limit)
    end = size
    while True:
        start = max(floor, end - _HISTORY_CHUNK)
        file.seek(start)
        data = file.read(end - start)
        match = None
        for match in _PAYTABLE_RE.finditer(data):
            pass  # keep the last one
        if match is not None:
            return _make_event(data, match)
        if start <= floor:
            return None
        end = start + _HISTORY_OVERLAP


def _make_event(data: bytes, match: re.Match[bytes]) -> LogEvent:
    line_start = data.rfind(b"\n", 0, match.start()) + 1
    log_time = _parse_time(data[line_start : line_start + _TIME_LENGTH])

    paytable = match["paytable"]
    if paytable is not None:
        supported = (_to_float(item) for item in (match["supported"] or b"").split(b","))
        return LogEvent(
            LogEventType.PAYTABLE,
            log_time,
            paytable_id=paytable.decode(errors="replace"),
            denom=_to_float(match["denom"]),
            supported_denoms=tuple(item for item in supported if item is not None),
        )
    kind = LogEventType.SPIN_START if match["state"] == b"stateSpin" else LogEventType.SPIN_END
    return LogEvent(kind, log_time, state_machine=match["machine"].decode())


def _parse_time(raw: bytes) -> datetime | None:
    try:
        return datetime.strptime(raw.decode("ascii"), _TIME_FORMAT)
    except ValueError:  # includes UnicodeDecodeError
        return None


def _to_float(raw: bytes) -> float | None:
    try:
        return float(raw)
    except ValueError:
        return None
