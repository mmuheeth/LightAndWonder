"""A stand-in for NRobot.Server.exe with a slot game behind it, on a real loopback XML-RPC endpoint.

It models what was measured against the live FortuneOx, so tests exercise the service's order of
operations and not just its plumbing:
- `InitializeGameClient` rejects an incomplete object query ("The given key was not present ...").
- Keywords fail with "Game Client is NULL" until a session is initialised.
- A spin leaves `statePlaying` on its own; a win holds it there until it is taken.
- Pressing a button reports success even when there is nothing to press for or the game ignores input.
- NRobot shares one connection to the game between its callers, and two keywords on it at once corrupt it,
  so `max_active` records the most keywords that were ever in flight together: a caller that respects
  the connection keeps it at 1."""

import http.server
import json
import threading
import time
import xmlrpc.client
from collections import deque

# The top-level sections InitializeGameClient needs of a BallyStyle game. UnityRemoteClient.dll also names
# TrayButtonQuery, but the live FortuneOx connects without it (only tray-style games read it).
REQUIRED_SECTIONS = (
    "AutoCasionQuery",
    "DemoMenuNew",
    "DenomQuery",
    "FreeSpinButtonQuery",
    "FullGafferQuery",
    "IDeckWagerButtonQuery",
    "NonWagerIDeckButtonQuery",
    "PlayerInfoMeterQuery",
    "ReelSets",
    "SuitGambleIDeckButtonQuery",
    "SuitGambleQuery",
    "ThemeFrontPanelMsgQuery",
    "WagerSaverQuery",
)

NO_CLIENT = "Game Client is NULL. Connection to game not established."
LOSING_SPIN = ["stateIdleWithCredits", "statePlaying", "statePlaying", "stateIdleWithCredits"]


class _Fail(Exception):
    """A keyword that ran and failed: a normal reply with status FAIL."""


class FakeGaf:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []  # (keyword, arguments), in order
        self._lock = threading.Lock()

        # The session.
        self.server_connected = False
        self.client_ready = False
        self.generic_ready = False
        self.connect_failures = 0  # how many CONNECT attempts fail before one succeeds
        self.general: dict | None = None
        self.generic: dict | None = None
        self.game_type: str | None = None
        self.gdk_version: str | None = None

        # The game.
        self.idle_state = "stateIdleWithCredits"
        self.spin_script = list(LOSING_SPIN)  # the idle states successive reads see after a spin
        self._script: deque[str] = deque()
        self.states = {"SlotGameStateMachine": "stateIdle", "GameStateMachine": "stateIdle"}
        self.win_on_offer = False
        self.ignore_input = False  # like a suspended game: presses are accepted and do nothing
        self.credit_as_cash = True
        self.mapped_buttons = {"TakeWinButton", "GambleButton"}
        self.unmapped_meters: set[str] = set()
        self.win_meter = ""
        self.denom = "200.000"
        self.denoms = ["1.000", "2.000", "5.000", "10.000", "100.000", "200.000"]
        self.failing: dict[str, str] = {}  # keyword -> the error it fails with
        # Seconds a keyword takes to answer, like NRobot blocked reconnecting to a game that dropped its link.
        self.delay: dict[str, float] = {}
        self.active = 0
        self.max_active = 0
        self._count_lock = threading.Lock()
        # Front-panel messages: what each area shows now, what a watch of it collects, and the bet layout.
        self.messages: dict[str, list[str]] = {"MessageArea1": ["Game Over"]}
        self.unique_messages: dict[str, list[str]] = {"MessageArea1": ["Game Over", "Game Pays 0", "Play 880 Credits"]}
        self.bet_layout: list[str] = ["BetButtonPanelLayout", "3 rows"]

        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                (keyword, arguments), _method = xmlrpc.client.loads(body)
                library = self.path.rsplit("/", 1)[-1]
                payload = xmlrpc.client.dumps((fake.run(library, keyword, arguments),), methodresponse=True, allow_none=True)
                data = payload.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/xml")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:  # keeps the test output clean
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        # The default poll interval (0.5s) would be added to the teardown of every test.
        threading.Thread(target=lambda: self._server.serve_forever(poll_interval=0.01), daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def keywords(self, name: str) -> list[list[str]]:
        """The arguments of every call to a keyword."""
        return [args for keyword, args in self.calls if keyword == name]

    def keywords_with_args(self, name: str) -> list[list[str]]:
        """Same as `keywords`, for callers that read as "the calls, each with its arguments"."""
        return self.keywords(name)

    @property
    def session_open(self) -> bool:
        return self.client_ready

    def lose_session(self) -> None:
        """The game restarts under NRobot: the session is gone."""
        self.client_ready = self.generic_ready = self.server_connected = False

    # ------------------------------------------------------------------- protocol

    def run(self, library: str, keyword: str, args: list[str]) -> dict:
        with self._count_lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay.get(keyword, 0.0))  # outside the lock: only this caller waits
            with self._lock:
                self.calls.append((keyword, list(args)))
                try:
                    value = self._dispatch(library, keyword, args)
                except _Fail as exc:
                    return {"status": "FAIL", "return": "", "output": "", "error": str(exc), "traceback": ""}
                return {"status": "PASS", "return": value, "output": "", "error": "", "traceback": ""}
        finally:
            with self._count_lock:
                self.active -= 1

    def _dispatch(self, library: str, keyword: str, args: list[str]):
        if "ConnectGame" in library:
            return self._connect_game(keyword, args)
        if not self.client_ready:
            raise _Fail(NO_CLIENT)
        if keyword in self.failing:
            raise _Fail(self.failing[keyword])
        if "Denom" in library:
            if not self.generic_ready:
                raise _Fail("Generic Client is NULL. Connection to game not established.")
            return self.denom if keyword == "GETCURRENTACTIVEDENOM" else list(self.denoms)
        match keyword:
            case "GETCURRENTSTATE":
                return self._read_state(args[0])
            case "PRESSMECHANICALSPINBUTTON":
                if not self.ignore_input:
                    self._script = deque(self.spin_script)
                return "True"
            case "ISNONWAGERBUTTONINTERACTABLE":
                self._require_button(args[0])
                return str(self.win_on_offer)
            case "PRESSNONWAGERBUTTON":
                self._require_button(args[0])
                if self.win_on_offer and not self.ignore_input:
                    self.win_on_offer = False
                    self._script = deque(["stateIdleWithCredits"])
                return "True"  # even when there was nothing to take
            case "GETFRONTPANELGAMEMESSAGE":
                return list(self._area(self.messages, args[0]))
            case "GETALLUNIQUEFRONTPANELMESSAGES":
                return list(self._area(self.unique_messages, args[0]))
            case "GETACTIVEBETLAYOUT":
                return list(self.bet_layout)
            case "METERINFO":
                return self._meter(args[0], args[1])
            case "TOGGLEMETERVALUE":
                if not self.ignore_input:
                    self.credit_as_cash = not self.credit_as_cash
                return "True"
        raise _Fail(f"No keyword with name '{keyword}' found.")

    def _connect_game(self, keyword: str, args: list[str]):
        match keyword:
            case "INIT":
                return ""
            case "CONNECTGAMECLIENTTOSERVER":
                if self.connect_failures > 0:
                    self.connect_failures -= 1
                    raise _Fail("Game Client is unable to connect to Thrift server")
                self.server_connected = True
                return "True"
            case "INITIALIZEGAMECLIENT":
                if not self.server_connected:
                    raise _Fail("no session has been initialized")
                query = json.loads(args[1])
                if any(name not in query for name in REQUIRED_SECTIONS):
                    raise _Fail("The given key was not present in the dictionary.")
                self.game_type, self.general, self.client_ready = args[0], query, True
                return ""
            case "INITIALIZEGENERICGAMECLIENT":
                self.generic, self.gdk_version, self.generic_ready = json.loads(args[0]), args[2], True
                return ""
            case "DESTROYGAMECLIENT":
                self.client_ready = self.generic_ready = False
                return ""
            case "DISCONNECTGAMECLIENTFROMSERVER":
                self.server_connected = False
                return ""
        raise _Fail(f"No keyword with name '{keyword}' found.")

    def _read_state(self, machine: str) -> str:
        if machine == "IdleStateMachine":
            if self._script:
                self.idle_state = self._script.popleft()
            return self.idle_state
        if machine == "GambleOfferStateMachine":
            return "offerState" if self.win_on_offer else "idleState"
        # An unknown machine is a normal reply that carries the error.
        return self.states.get(machine, f"ERROR: StateMachineInfoDict does not contain stateMachineName key: {machine}")

    @staticmethod
    def _area(by_area: dict[str, list[str]], area: str) -> list[str]:
        if area not in by_area:
            raise _Fail(f"Error Message:<< Provided message area is not a valid value: {area} >>")
        return by_area[area]

    def _require_button(self, button: str) -> None:
        if button not in self.mapped_buttons:
            raise _Fail(f"Issue while fetching info of NonWager button info: {button}")

    def _meter(self, meter: str, value_type: str) -> str:
        if meter in self.unmapped_meters:
            raise _Fail(f"Component {meter} not present in the JSON file")
        values = {
            "CreditMeter": ("CASH", "$20,594.00") if self.credit_as_cash else ("CREDITS", "10297"),
            "BetMeter": ("BET", "$20.00"),
            "WinMeter": ("WIN", self.win_meter),
            "CollectMeter": ("COLLECT", ""),
        }
        name, value = values[meter]
        return name if value_type == "name" else value
