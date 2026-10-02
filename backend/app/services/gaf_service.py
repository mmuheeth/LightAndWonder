import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.exceptions import AppException, BadRequestException, NotFoundException
from app.schemas.gaf import GafActionInfo, GafActionParam, GafActionResult, GafStatus
from app.schemas.game_context import GameMode
from app.services.game_context_service import GameContextService
from app.utils import game_config as game_settings
from app.utils.gaf_objects import ObjectQueries, ObjectQueryError, load_object_queries
from app.utils.nrobot import KeywordFailed, NRobot, NRobotUnreachable

logger = logging.getLogger(__name__)

# The state machines the game exposes, and the states that matter (from the game's own config).
_IDLE_MACHINE = "IdleStateMachine"
_STATE_MACHINES = (_IDLE_MACHINE, "SlotGameStateMachine", "GambleOfferStateMachine", "GameStateMachine")
_PLAYING = "statePlaying"
_OFFER_MACHINE = "GambleOfferStateMachine"
_OFFER_STATE = "offerState"

# Names AGF itself fixes: the non-wager buttons and meters a game's object query can map.
_TAKE_WIN = "TakeWinButton"
_GAMBLE = "GambleButton"
_CREDIT_METER = "CreditMeter"
_BET_METER = "BetMeter"
_METERS = (_CREDIT_METER, _BET_METER, "WinMeter", "CollectMeter")

# What GAF says when there is no session. NRobot keeps its session for as long as NRobot lives, but
# the game can be restarted under it.
_NO_SESSION = "is NULL"

# Seconds. Module level so tests can shrink them.
_POLL_INTERVAL = 0.5
# After the spin button is pressed the game stays in its old state for a beat (~1.2s measured). Reading
# "idle" then would mistake a spin that is about to start for one that has finished.
_DEPARTURE_TIMEOUT = 5.0
_COLLECT_TIMEOUT = 10.0
# The meter's text updates a moment after the toggle (~0.5s), and never if the game ignores input.
_METER_TIMEOUT = 3.0

# Watching a message area for its unique messages blocks for as long as it is asked to, so the client
# gets that plus a margin; the range is what the UI offers.
_WATCH_DEFAULT_SECONDS = 15
_WATCH_MAX_SECONDS = 60
_WATCH_MARGIN = 15.0
# NRobot serves every request on its own thread but shares one Thrift connection to the game, and two
# keywords on it at once interleave their frames: the game then answers "Arithmetic operation resulted in
# an overflow" or OutOfMemoryException and drops the link (NRobot takes 10-25s to reconnect). So this
# backend runs one keyword at a time. A request that cannot get the connection within `_IO_WAIT` is refused
# as busy; the status poll only waits `_PROBE_WAIT` and then answers from what it last saw.
_IO_WAIT = 10.0
_PROBE_WAIT = 2.0
# The section of the object query that says where a game shows its front-panel messages.
_MESSAGE_SECTION = "ThemeFrontPanelMsgQuery"


@dataclass(frozen=True)
class _Target:
    game: str
    mode: GameMode
    host: str
    port: int
    game_type: str
    gdk_version: str
    object_query: Path | None
    actions: tuple[str, ...]
    # The object (named in the game's object query) that lays out the bet buttons; "" for the legacy layout.
    bet_layout_object: str


@dataclass(frozen=True)
class _Session:
    game: str
    mode: GameMode


@dataclass(frozen=True)
class _Outcome:
    message: str
    values: dict[str, str | list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class _Action:
    id: str
    label: str
    description: str
    scope: Literal["common", "game"]
    # A command changes the game or holds its connection for a while, so only one runs at a time
    # (and connect/disconnect wait for it); a read is short and only queues for the connection.
    command: bool
    # The inputs it takes, by name: "area" (a message area the game maps) and "seconds" (how long to watch).
    params: tuple[str, ...] = ()


# The catalog. A "common" action exists for every game; a "game" one is only offered where the game's
# config (`gaf.actions`) lists it, because it needs the game to have mapped that object.
_ACTIONS = (
    _Action("spin", "Spin", "Presses the spin button and waits until the spin settles or a win is offered.", "common", True),
    _Action("game_state", "Game state", "Reads the game's state machines.", "common", False),
    _Action("active_denom", "Active denom", "Reads the denomination the game is set to.", "common", False),
    _Action("available_denoms", "Available denoms", "Lists the denominations the game offers.", "common", False),
    _Action(
        "meters", "Meters",
        "Reads the label and value of the credit, bet, win and collect meters. The win meter is only final once "
        "the win is collected.",
        "common", False,
    ),
    _Action("bet", "Current bet", "Reads the bet meter: the amount the next spin is played for.", "game", False),
    _Action("take_win", "Take win", "Collects the win the game is offering.", "game", True),
    _Action("gamble", "Gamble", "Takes the gamble the game is offering.", "game", True),
    _Action("toggle_credit_meter", "Toggle credit meter", "Switches the credit meter between cash and credits.", "game", True),
    _Action(
        "front_panel_messages", "Front panel messages",
        "Reads the messages the game is showing right now in each of its front-panel message areas.",
        "game", False,
    ),
    _Action(
        "unique_front_panel_messages", "Watch messages",
        "Watches one message area for the given time and lists every different message it showed. "
        "Use it for cyclic messages, which show one at a time.",
        "game", True, ("area", "seconds"),
    ),
    _Action(
        "bet_layout", "Bet layout",
        "Reads the active bet layout, of the object the game's config names (bet_layout_object). Only for games "
        "that implement it: on others it fails, and a wrong object can make the game drop its GAF link for ~20s.",
        "game", False,
    ),
)

_Handler = Callable[["_Target", dict[str, Any]], _Outcome]


class GafService:
    """Drives the selected game through GAF: a session to the game is opened through NRobot, and then keywords
    press its buttons and read its state, meters and denominations.

    Everything blocks (keywords are HTTP calls, and a spin is polled until it settles), so the public
    coroutines run it in a thread. The session lives in NRobot; this only remembers which game it was opened for."""

    def __init__(
        self,
        *,
        nrobot: NRobot,
        game_context: GameContextService,
        base_dir: Path,
        settle_timeout: float,
        connect_attempts: int,
        connect_retry_delay: float,
        probe_nrobot: NRobot | None = None,
    ) -> None:
        self._nrobot = nrobot
        # Status is polled every few seconds by the UI and must answer well inside the browser's own
        # timeout, so its probe gets a short one of its own; a keyword that takes 30s is fine for a spin.
        self._probe_nrobot = probe_nrobot or nrobot
        self._game_context = game_context
        self._base_dir = base_dir
        self._settle_timeout = settle_timeout
        self._connect_attempts = max(1, connect_attempts)
        self._connect_retry_delay = connect_retry_delay
        self._session: _Session | None = None
        # One probe at a time: when NRobot stalls, polls that pile up behind it only make it worse.
        self._probe_lock = threading.Lock()
        self._probe_result: tuple[bool, str | None, str | None] = (False, None, None)
        self._probe_finished_at = 0.0
        # Held for the whole of every keyword call. The action running, if any, is only ever set by a
        # command or a connect (which hold `_lock`), so it is never contended.
        self._io = threading.Lock()
        self._activity: str | None = None
        self._last_state: str | None = None
        # What the game last said about a button being pressable, to tell "not on offer" from "not found".
        self._button_reply = ""
        # Held by connect/disconnect and, without waiting, by every command.
        self._lock = threading.Lock()
        self._handlers: dict[str, _Handler] = {
            "spin": lambda target, params: self._spin(),
            "game_state": lambda target, params: self._game_state(),
            "active_denom": lambda target, params: self._active_denom(),
            "available_denoms": lambda target, params: self._available_denoms(),
            "meters": lambda target, params: self._meters(),
            "bet": lambda target, params: self._bet(),
            "take_win": lambda target, params: self._press_offered(_TAKE_WIN, "Take win"),
            "gamble": lambda target, params: self._press_offered(_GAMBLE, "Gamble"),
            "toggle_credit_meter": lambda target, params: self._toggle_credit_meter(),
            "front_panel_messages": lambda target, params: self._front_panel_messages(target),
            "unique_front_panel_messages": lambda target, params: self._unique_front_panel_messages(params),
            "bet_layout": lambda target, params: self._bet_layout(target),
        }

    # ------------------------------------------------------------------ public

    # Every method answers for `game` and `mode`, which default to the selected ones. A caller that
    # changes the selection itself passes them, so its answer is for what it asked about.

    async def status(self, game: str | None = None, mode: GameMode | None = None) -> GafStatus:
        return await asyncio.to_thread(self._status, game, mode)

    async def connect(self, game: str | None = None, mode: GameMode | None = None) -> GafStatus:
        """Opens a session to the game, replacing any that is open."""
        await asyncio.to_thread(self._connect, game, mode)
        return await self.status(game, mode)

    async def disconnect(self, game: str | None = None, mode: GameMode | None = None) -> GafStatus:
        await asyncio.to_thread(self._disconnect)
        return await self.status(game, mode)

    def list_actions(self, game: str | None = None, mode: GameMode | None = None) -> list[GafActionInfo]:
        """The common actions and the game's own; none if the game has no GAF config."""
        try:
            target = self._target(game, mode)
        except NotFoundException:
            return []
        areas = self._message_areas(target)
        listed: list[GafActionInfo] = []
        for action in self._catalog(target).values():
            if action.id in _NEEDS_AREAS and not areas:
                continue  # the game lists it but maps no message area, so there is nothing to read
            listed.append(
                GafActionInfo(
                    id=action.id,
                    label=action.label,
                    description=action.description,
                    scope=action.scope,
                    params=_param_specs(action, areas),
                )
            )
        return listed

    async def run_action(
        self,
        action_id: str,
        params: dict[str, Any] | None = None,
        game: str | None = None,
        mode: GameMode | None = None,
    ) -> GafActionResult:
        return await asyncio.to_thread(self._run_action, action_id, params or {}, game, mode)

    # ------------------------------------------------------------------ status

    def _status(self, game: str | None, mode: GameMode | None) -> GafStatus:
        game, mode = self._resolve(game, mode)
        problem: str | None = None
        target: _Target | None = None
        try:
            target = self._target(game, mode)
        except AppException as exc:
            problem = exc.message

        reachable, state, detail = self._probe()
        session = self._session
        connected = False
        if reachable and state is None:
            self._session = None  # whatever it was, it is gone
            detail = problem
        elif reachable and session is None:
            detail = "The game has an open GAF session this backend did not start. Connect takes it over."
        elif reachable and session != _Session(game, mode):
            detail = (
                f"A session for {session.game} · {session.mode.value} is open. "
                f"Connect switches to {game} · {mode.value}."
            )
        elif reachable:
            connected = True
        return GafStatus(
            game=game,
            mode=mode,
            nrobot_url=self._nrobot.base_url,
            target=f"{target.host}:{target.port}" if target else None,
            reachable=reachable,
            connected=connected,
            state=state if connected else None,
            detail=None if connected else detail,
            busy=self._activity,
        )

    def _probe(self) -> tuple[bool, str | None, str | None]:
        """(NRobot answers, the game's idle state if a session is open, why NRobot does not answer).
        Polls that arrive while a probe is running wait for it and share its answer."""
        asked = time.monotonic()
        with self._probe_lock:
            if self._probe_finished_at >= asked:  # a probe finished after this poll began
                return self._probe_result
            self._probe_result = self._read_probe()
            self._probe_finished_at = time.monotonic()
            return self._probe_result

    def _read_probe(self) -> tuple[bool, str | None, str | None]:
        if not self._io.acquire(timeout=_PROBE_WAIT):
            # Something (a spin, a long watch) holds the game connection. Asking as well would collide with
            # it, and the session is evidently alive, so report what was last seen.
            return True, self._last_state or "unavailable", None
        try:
            state = str(self._probe_nrobot.run("GameState", "GETCURRENTSTATE", _IDLE_MACHINE)).strip()
            if state.startswith("ERROR:"):
                raise KeywordFailed("GameState", "GETCURRENTSTATE", state)
            self._last_state = state
            return True, state, None
        except NRobotUnreachable as exc:
            return False, None, _unreachable_message(exc)
        except KeywordFailed as exc:
            # A keyword that fails still proves NRobot is there: it just has no session to read. Only a
            # missing session means "not connected"; any other failure (a read that hiccups mid-spin)
            # must not drop the session this backend remembers.
            return True, None if _NO_SESSION in exc.error else "unavailable", None
        finally:
            self._io.release()

    # -------------------------------------------------------------- connection

    def _connect(self, game: str | None, mode: GameMode | None) -> None:
        target = self._target(game, mode)
        try:
            queries = load_object_queries(target.game_type, target.object_query)
        except ObjectQueryError as exc:
            raise AppException(str(exc), error_code="CONFIG_INVALID") from exc
        with self._lock:
            self._session = None
            self._activity = "Connecting"
            try:
                with self._translate_errors():
                    self._teardown(strict=True)  # a session left open would block this one
                    try:
                        self._open(target, queries)
                    except BaseException:
                        self._teardown()
                        raise
            finally:
                self._activity = None
            self._session = _Session(target.game, target.mode)
        logger.info("GAF connected to %s:%s (%s, %s)", target.host, target.port, target.game, target.mode.value)

    def _open(self, target: _Target, queries: ObjectQueries) -> None:
        host, port = target.host, str(target.port)
        self._run("ConnectGame", "INIT", host, port)
        self._connect_to_game(host, port)
        self._run("ConnectGame", "INITIALIZEGAMECLIENT", target.game_type, json.dumps(queries.general))
        # Both are needed: the denomination keywords use the generic client.
        self._run(
            "ConnectGame", "INITIALIZEGENERICGAMECLIENT", json.dumps(queries.generic), "", target.gdk_version
        )

    def _connect_to_game(self, host: str, port: str) -> None:
        error = ""
        for attempt in range(1, self._connect_attempts + 1):
            try:
                if _truthy(self._run("ConnectGame", "CONNECTGAMECLIENTTOSERVER", host, port)):
                    return
                error = "the game refused the connection"
            except KeywordFailed as exc:
                error = exc.error
            if attempt < self._connect_attempts:
                time.sleep(self._connect_retry_delay)
        raise AppException(
            f"Could not connect to the game at {host}:{port}: {error}",
            status_code=502,
            error_code="GAF_CONNECT_FAILED",
        )

    def _disconnect(self) -> None:
        with self._lock:
            self._activity = "Disconnecting"
            try:
                self._teardown()
            finally:
                self._activity = None
            self._session = None

    def _teardown(self, *, strict: bool = False) -> None:
        """Closes the session. A session that is not there is fine; NRobot not being there is only an
        error when `strict`, i.e. when the caller cannot go on without it (a refused connection takes
        ~2s to notice on Windows, so nothing is tried twice)."""
        for keyword in ("DESTROYGAMECLIENT", "DISCONNECTGAMECLIENTFROMSERVER"):
            try:
                self._run("ConnectGame", keyword)
            except NRobotUnreachable:
                if strict:
                    raise
                return
            except KeywordFailed as exc:
                logger.debug("GAF teardown: %s", exc)

    # ----------------------------------------------------------------- actions

    def _run_action(
        self, action_id: str, given: dict[str, Any], game: str | None, mode: GameMode | None
    ) -> GafActionResult:
        target = self._target(game, mode)
        action = self._catalog(target).get(action_id)
        if action is None:
            raise NotFoundException(f"'{target.game}' has no GAF action '{action_id}'")
        areas = self._message_areas(target) if action.id in _NEEDS_AREAS else []
        if action.id in _NEEDS_AREAS and not areas:
            raise NotFoundException(f"'{target.game}' maps no front-panel message area")
        params = _validated(_param_specs(action, areas), given)
        if self._session != _Session(target.game, target.mode):
            raise AppException(
                f"Not connected to {target.game} · {target.mode.value}. Connect first.",
                status_code=409,
                error_code="GAF_NOT_CONNECTED",
            )
        if action.command:
            if not self._lock.acquire(blocking=False):
                raise AppException("Another GAF command is still running.", status_code=409, error_code="GAF_BUSY")
            try:
                outcome = self._perform(action, target, params)
            finally:
                self._lock.release()
        else:
            outcome = self._perform(action, target, params)
        return GafActionResult(action=action.id, label=action.label, message=outcome.message, values=outcome.values)

    def _perform(self, action: _Action, target: _Target, params: dict[str, Any]) -> _Outcome:
        if action.command:
            self._activity = action.label
        try:
            with self._translate_errors():
                outcome = self._handlers[action.id](target, params)
        finally:
            if action.command:
                self._activity = None
        logger.info("GAF %s: %s", action.id, outcome.message)
        return outcome

    def _spin(self) -> _Outcome:
        before = self._state(_IDLE_MACHINE)
        if before == _PLAYING:
            # A win holds the game here until it is collected, so pressing again would land in that
            # win and its "result" would belong to the previous spin.
            raise AppException(
                "The game is still playing, or holding a win until it is collected. Wait for it or take the win.",
                status_code=409,
                error_code="GAF_NOT_IDLE",
            )
        self._run("IDeck", "PRESSMECHANICALSPINBUTTON")
        started = time.monotonic()
        if not self._wait_for(lambda: self._state(_IDLE_MACHINE) != before, _DEPARTURE_TIMEOUT):
            return _Outcome(
                f"The spin button was pressed but the game did not start a spin (still {before}). Are there credits?",
                {"outcome": "not_started", "state": before},
            )
        outcome, state = self._settle()
        seconds = f"{time.monotonic() - started:.1f}"
        message = {
            "settled": f"Spin settled after {seconds}s ({state}).",
            "win_offered": f"Spin finished after {seconds}s with a win on offer. Take it to collect.",
            "timeout": f"The game was still playing after {seconds}s (a bonus?).",
        }[outcome]
        return _Outcome(message, {"outcome": outcome, "state": state, "seconds": seconds})

    def _settle(self) -> tuple[str, str]:
        """Waits for the spin to end: a losing spin leaves `statePlaying` by itself, a win holds it there
        until it is collected, so a win being offered ends the wait too."""
        deadline = time.monotonic() + self._settle_timeout
        while True:
            state = self._state(_IDLE_MACHINE)
            if state != _PLAYING:
                return "settled", state
            if self._win_offered():
                return "win_offered", state
            if time.monotonic() >= deadline:
                return "timeout", state
            time.sleep(_POLL_INTERVAL)

    def _win_offered(self) -> bool:
        try:
            if self._state(_OFFER_MACHINE) == _OFFER_STATE:
                return True
        except KeywordFailed:
            pass  # a game without that machine
        return self._interactable(_TAKE_WIN)

    def _press_offered(self, button: str, label: str) -> _Outcome:
        # Pressing reports success even when there is nothing to press for, so ask first.
        if not self._interactable(button):
            raise AppException(
                f"{label} is not on offer right now ({self._button_reply}).",
                status_code=409,
                error_code="GAF_NOT_AVAILABLE",
            )
        self._run("IDeck", "PRESSNONWAGERBUTTON", button)
        taken = self._wait_for(lambda: not self._interactable(button), _COLLECT_TIMEOUT)
        state = self._state(_IDLE_MACHINE)
        if not taken:  # the press was delivered, but the game did not act on it
            return _Outcome(
                f"{label} was pressed but is still on offer after {_COLLECT_TIMEOUT:g}s ({state}).",
                {"outcome": "still_on_offer", "state": state},
            )
        return _Outcome(f"{label} pressed. The game is in {state}.", {"outcome": "done", "state": state})

    def _bet(self) -> _Outcome:
        """The bet meter, e.g. `BET: 100`. Unlike `meters`, a game that has not mapped it fails the action:
        this is all the action reads."""
        bet = self._meter_text(_BET_METER)
        return _Outcome(f"{bet}.", {"bet": bet})

    def _game_state(self) -> _Outcome:
        states = {machine: _or_unavailable(lambda m=machine: self._state(m)) for machine in _STATE_MACHINES}
        return _Outcome(f"The game is in {states[_IDLE_MACHINE]}.", dict(states))

    def _active_denom(self) -> _Outcome:
        denom = str(self._run("Denom", "GETCURRENTACTIVEDENOM")).strip()
        return _Outcome(f"The active denom is {_format_denom(denom)}.", {"active_denom": denom})

    def _available_denoms(self) -> _Outcome:
        denoms = _as_list(self._run("Denom", "GETCONFIGUREDDENOMBUTTONS"))
        shown = ", ".join(_format_denom(d) for d in denoms)
        return _Outcome(f"The game offers {len(denoms)} denoms: {shown}.", {"available_denoms": denoms})

    def _meters(self) -> _Outcome:
        """Each meter's label and value, e.g. `CASH: $997.20`. A meter the game has not mapped reads as unavailable."""

        values = {name: _or_unavailable(lambda n=name: self._meter_text(n)) for name in _METERS}
        return _Outcome("Read the meters.", dict(values))

    def _meter_text(self, meter: str) -> str:
        label, value = self._meter(meter, "name"), self._meter(meter, "value")
        return f"{label}: {value}" if value else f"{label}: (blank)"

    def _front_panel_messages(self, target: _Target) -> _Outcome:
        """What every message area is showing this instant. A cyclic area shows one message at a time,
        so use `_unique_front_panel_messages` to see them all."""
        values: dict[str, str | list[str]] = {}
        for area in self._message_areas(target):
            try:
                messages = [m for m in _as_list(self._run("GamePlay", "GETFRONTPANELGAMEMESSAGE", area)) if m.strip()]
            except KeywordFailed as exc:
                if _NO_SESSION in exc.error:
                    raise
                values[area] = "unavailable"
                continue
            values[area] = messages or "(none)"
        showing = sum(1 for value in values.values() if isinstance(value, list))
        return _Outcome(f"Read {len(values)} message area(s); {showing} showing text.", values)

    def _unique_front_panel_messages(self, params: dict[str, Any]) -> _Outcome:
        area, seconds = params["area"], params["seconds"]
        # The keyword blocks for the whole time, so this call gets a timeout that outlasts it.
        robot = NRobot(self._nrobot.base_url, timeout=seconds + _WATCH_MARGIN)
        with self._exclusive():
            reply = robot.run("GamePlay", "GETALLUNIQUEFRONTPANELMESSAGES", area, f"{seconds:g}")
        messages = [m for m in _as_list(reply) if m.strip()]
        return _Outcome(
            f"Watched {area} for {seconds:g}s and saw {len(messages)} different message(s).",
            {"area": area, "watched": f"{seconds:g}s", "messages": messages or "(none)"},
        )

    def _bet_layout(self, target: _Target) -> _Outcome:
        layout = _as_list(self._run("IDeck", "GETACTIVEBETLAYOUT", target.bet_layout_object))
        return _Outcome(
            "Read the active bet layout.",
            {"object": target.bet_layout_object or "(legacy server-side layout)", "layout": layout},
        )

    def _toggle_credit_meter(self) -> _Outcome:
        before = self._credit_meter()
        self._run("GameMeter", "TOGGLEMETERVALUE", _CREDIT_METER)
        after = before
        deadline = time.monotonic() + _METER_TIMEOUT
        while after == before and time.monotonic() < deadline:
            time.sleep(_POLL_INTERVAL)
            after = self._credit_meter()
        label, value = after
        if after == before:  # pressing reports success even when the game ignores it (e.g. it is disabled)
            return _Outcome(
                f"The toggle was pressed but the credit meter did not change (still {label}: {value}). "
                "Is the game disabled?",
                {"outcome": "unchanged", "label": label, "value": value},
            )
        return _Outcome(
            f"The credit meter now shows {label}: {value}.",
            {"outcome": "toggled", "label": label, "value": value},
        )

    def _credit_meter(self) -> tuple[str, str]:
        return self._meter(_CREDIT_METER, "name"), self._meter(_CREDIT_METER, "value")

    # ----------------------------------------------------------------- keywords

    def _run(self, area: str, keyword: str, *args: object) -> Any:
        with self._exclusive():
            return self._nrobot.run(area, keyword, *args)

    @contextmanager
    def _exclusive(self):
        """The game connection, alone: see `_IO_WAIT`."""
        if not self._io.acquire(timeout=_IO_WAIT):
            what = f" ({self._activity})" if self._activity else ""
            raise AppException(
                f"The game connection is busy{what}. Try again in a moment.",
                status_code=409,
                error_code="GAF_BUSY",
            )
        try:
            yield
        finally:
            self._io.release()

    def _state(self, machine: str) -> str:
        state = str(self._run("GameState", "GETCURRENTSTATE", machine)).strip()
        if state.startswith("ERROR:"):  # an unknown machine is a normal reply carrying the error
            raise KeywordFailed("GameState", "GETCURRENTSTATE", state)
        if machine == _IDLE_MACHINE:
            self._last_state = state
        return state

    def _meter(self, meter: str, value_type: str) -> str:
        return str(self._run("GameMeter", "METERINFO", meter, value_type)).strip()

    def _interactable(self, button: str) -> bool:
        try:
            reply = self._run("IDeck", "ISNONWAGERBUTTONINTERACTABLE", button)
        except KeywordFailed as exc:  # e.g. a game that has not mapped this button
            self._button_reply = f"the game could not check it: {exc.error}"
            return False
        self._button_reply = f"the game answered {str(reply).strip()!r}"
        return _truthy(reply)

    def _wait_for(self, condition: Callable[[], bool], timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() >= deadline:
                return False
            time.sleep(_POLL_INTERVAL)
        return True

    @contextmanager
    def _translate_errors(self):
        """NRobot's errors as the API's: no NRobot, a lost session, or a keyword that failed."""
        try:
            yield
        except NRobotUnreachable as exc:
            raise AppException(_unreachable_message(exc), status_code=503, error_code="GAF_UNREACHABLE") from exc
        except KeywordFailed as exc:
            if _NO_SESSION in exc.error:
                self._session = None
                raise AppException(
                    "The GAF session to the game was lost. Connect again.",
                    status_code=409,
                    error_code="GAF_NOT_CONNECTED",
                ) from exc
            raise AppException(
                f"{exc.keyword} failed: {exc.error}",
                status_code=502,
                error_code="GAF_KEYWORD_FAILED",
                details={"keyword": exc.keyword},
            ) from exc

    # ------------------------------------------------------------------ config

    def _catalog(self, target: _Target) -> dict[str, _Action]:
        listed = set(target.actions)
        unknown = listed - {a.id for a in _ACTIONS if a.scope == "game"}
        if unknown:
            logger.warning("'%s' lists GAF actions that do not exist: %s", target.game, sorted(unknown))
        return {a.id: a for a in _ACTIONS if a.scope == "common" or a.id in listed}

    def _message_areas(self, target: _Target) -> list[str]:
        """The message areas the game maps (the object query's base has some for every game of its type,
        and the game's own file replaces them), in the order they are listed."""
        try:
            queries = load_object_queries(target.game_type, target.object_query)
        except ObjectQueryError:
            return []
        section = queries.general.get(_MESSAGE_SECTION)
        return [name for name, spec in section.items() if spec] if isinstance(section, dict) else []

    def _resolve(self, game: str | None, mode: GameMode | None) -> tuple[str, GameMode]:
        selection = self._game_context.get_context().context
        return game or selection.game, mode or selection.mode

    def _target(self, game: str | None = None, mode: GameMode | None = None) -> _Target:
        """Where the game is and how to drive it, from its config."""
        game, mode = self._resolve(game, mode)
        config = game_settings.load_game_config(game) if game else None
        if config is None:
            raise NotFoundException(f"Game '{game}' has no config")
        gaf = config.get("gaf")
        if not isinstance(gaf, dict):
            raise NotFoundException(f"'{game}' has no GAF config")
        section = config.get(mode.value)
        section = section if isinstance(section, dict) else {}
        host, port = section.get("host"), section.get("port")
        game_type, gdk_version = gaf.get("game_type"), gaf.get("gdk_version")
        if not (isinstance(host, str) and host and isinstance(port, int)):
            raise _invalid_config(game, f"'{mode.value}' needs a host and a port")
        if not (isinstance(game_type, str) and game_type and gdk_version):
            raise _invalid_config(game, "'gaf' needs a game_type and a gdk_version")
        root = gaf.get("object_query_root")
        actions = gaf.get("actions", [])
        bet_layout = gaf.get("bet_layout_object")
        return _Target(
            game=game,
            mode=mode,
            host=host,
            port=port,
            game_type=game_type,
            gdk_version=str(gdk_version),
            object_query=self._base_dir / root if isinstance(root, str) and root else None,
            actions=tuple(a for a in actions if isinstance(a, str)) if isinstance(actions, list) else (),
            bet_layout_object=bet_layout if isinstance(bet_layout, str) else "",
        )


# ------------------------------------------------------------------ helpers


# The actions that read a message area, so need the game to map at least one.
_NEEDS_AREAS = frozenset({"front_panel_messages", "unique_front_panel_messages"})


def _param_specs(action: _Action, areas: list[str]) -> list[GafActionParam]:
    """The inputs of an action, described for the UI. `areas` are the game's message areas."""
    specs = {
        "area": lambda: GafActionParam(
            name="area", label="Message area", kind="choice", options=areas, default=areas[0]
        ),
        "seconds": lambda: GafActionParam(
            name="seconds",
            label="Seconds to watch",
            kind="number",
            default=_WATCH_DEFAULT_SECONDS,
            min=1,
            max=_WATCH_MAX_SECONDS,
        ),
    }
    return [specs[name]() for name in action.params]


def _validated(specs: list[GafActionParam], given: dict[str, Any]) -> dict[str, Any]:
    """The values to run an action with: what was given, else the default, and only if it is in range."""
    unknown = sorted(set(given) - {spec.name for spec in specs})
    if unknown:
        raise BadRequestException(
            f"Unknown parameter(s) {', '.join(unknown)}; this action takes: {', '.join(s.name for s in specs) or 'none'}"
        )
    values: dict[str, Any] = {}
    for spec in specs:
        value = given.get(spec.name, spec.default)
        if spec.kind == "choice":
            if value not in spec.options:
                raise BadRequestException(
                    f"{spec.label} must be one of {', '.join(spec.options)}, not {value!r}",
                    details={"parameter": spec.name},
                )
        else:
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise BadRequestException(f"{spec.label} must be a number, not {value!r}", details={"parameter": spec.name}) from None
            if not (spec.min <= number <= spec.max):  # also false for NaN
                raise BadRequestException(
                    f"{spec.label} must be between {spec.min:g} and {spec.max:g}, not {value!r}",
                    details={"parameter": spec.name},
                )
            value = number
        values[spec.name] = value
    return values


def _or_unavailable(read: Callable[[], str]) -> str:
    """A read that may legitimately not exist for this game; a lost session still fails the action."""
    try:
        return read()
    except KeywordFailed as exc:
        if _NO_SESSION in exc.error:
            raise
        return "unavailable"


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _as_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else [str(value)]


def _format_denom(raw: str) -> str:
    """GAF reports a denom as a number of cents ("200.000"); people read "$2.00" and "5¢"."""
    try:
        cents = float(raw)
    except ValueError:
        return raw
    return f"${cents / 100:.2f}" if cents >= 100 else f"{cents:g}¢"


def _unreachable_message(exc: NRobotUnreachable) -> str:
    if isinstance(exc.__cause__, TimeoutError):
        # NRobot took the request but did not answer: typically the game closed its Thrift link and NRobot
        # is blocked reconnecting (10-20s), not that NRobot is down.
        return (
            "NRobot did not answer in time. It is probably reconnecting to the game; this clears by itself, "
            "or press Connect if it does not."
        )
    return f"{exc}. Is NRobot.Server.exe running? The 'NRobot Server (AGF)' scheduled task starts it."


def _invalid_config(game: str, what: str) -> AppException:
    return AppException(f"The GAF config of '{game}' is invalid: {what}", error_code="CONFIG_INVALID")
