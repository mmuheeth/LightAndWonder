"""The NRobot client against a real XML-RPC server on loopback, answering the way NRobot.Server.exe does."""

import http.server
import threading
import time
import xmlrpc.client
from collections.abc import Iterator

import pytest

from app.utils.nrobot import KeywordFailed, NRobot, NRobotUnreachable

PASS = {"status": "PASS", "return": "", "output": "", "error": "", "traceback": ""}


class FakeNRobot:
    """Records every call and answers with whatever the test set up."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list]] = []  # (url path, keyword, arguments)
        self.replies: dict[str, dict] = {}  # by keyword; anything else passes with no return
        self.fault: str | None = None
        self.http_status = 200
        self.delay = 0.0
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if fake.http_status != 200:
                    self.send_error(fake.http_status)
                    return
                (keyword, arguments), _method = xmlrpc.client.loads(body)
                time.sleep(fake.delay)
                if fake.fault:
                    payload = xmlrpc.client.dumps(xmlrpc.client.Fault(1, fake.fault))
                else:
                    fake.calls.append((self.path, keyword, arguments))
                    reply = fake.replies.get(keyword, PASS)
                    payload = xmlrpc.client.dumps((reply,), methodresponse=True, allow_none=True)
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
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def fake() -> Iterator[FakeNRobot]:
    server = FakeNRobot()
    yield server
    server.close()


@pytest.fixture
def robot(fake: FakeNRobot) -> NRobot:
    return NRobot(fake.url, timeout=2.0)


def test_a_keyword_is_called_on_its_library_and_returns_what_it_returned(
    robot: NRobot, fake: FakeNRobot
) -> None:
    fake.replies["PRESSMECHANICALSPINBUTTON"] = {**PASS, "return": "True"}

    assert robot.run("IDeck", "PRESSMECHANICALSPINBUTTON") == "True"

    assert fake.calls == [("/RFTestCode.IDeck.IDeckLibrary", "PRESSMECHANICALSPINBUTTON", [])]


def test_the_keyword_name_is_sent_in_upper_case_and_arguments_as_strings(
    robot: NRobot, fake: FakeNRobot
) -> None:
    robot.run("GameMeter", "meterInfo", "CreditMeter", 3, True)

    assert fake.calls == [
        ("/RFTestCode.GameMeter.GameMeterLibrary", "METERINFO", ["CreditMeter", "3", "True"])
    ]


@pytest.mark.parametrize("returned", ["$995.80", 12, True, ["1.000", "2.000"], ""])
def test_the_return_value_keeps_its_type(robot: NRobot, fake: FakeNRobot, returned) -> None:
    fake.replies["X"] = {**PASS, "return": returned}

    assert robot.run("IDeck", "X") == returned


def test_a_failed_keyword_raises_with_its_error_although_the_call_itself_succeeded(
    robot: NRobot, fake: FakeNRobot
) -> None:
    fake.replies["GETCURRENTSTATE"] = {**PASS, "status": "FAIL", "error": " Game Client is NULL. \n"}

    with pytest.raises(KeywordFailed) as caught:
        robot.run("GameState", "GETCURRENTSTATE", "IdleStateMachine")

    assert caught.value.error == "Game Client is NULL."
    assert caught.value.keyword == "GETCURRENTSTATE"
    assert caught.value.library == "RFTestCode.GameState.GameStateLibrary"


def test_a_failure_without_an_error_still_says_something(robot: NRobot, fake: FakeNRobot) -> None:
    fake.replies["X"] = {**PASS, "status": "FAIL", "error": ""}

    with pytest.raises(KeywordFailed, match="no details given"):
        robot.run("IDeck", "X")


def test_a_library_that_is_not_loaded_reads_as_unreachable(robot: NRobot, fake: FakeNRobot) -> None:
    # A server started from the wrong directory answers, but has none of the libraries.
    fake.fault = "Type RFTestCode.ConnectGame.ConnectGameLibrary is not loaded"

    with pytest.raises(NRobotUnreachable, match="is not loaded"):
        robot.run("ConnectGame", "INIT")


def test_an_http_error_reads_as_unreachable(robot: NRobot, fake: FakeNRobot) -> None:
    fake.http_status = 404

    with pytest.raises(NRobotUnreachable, match="Cannot reach NRobot"):
        robot.run("IDeck", "X")


def test_nothing_listening_reads_as_unreachable(fake: FakeNRobot) -> None:
    url = fake.url
    fake.close()

    with pytest.raises(NRobotUnreachable, match="Cannot reach NRobot"):
        NRobot(url, timeout=2.0).run("IDeck", "X")


def test_a_server_that_never_answers_times_out_instead_of_hanging(fake: FakeNRobot) -> None:
    fake.delay = 2.0

    started = time.monotonic()
    with pytest.raises(NRobotUnreachable):
        NRobot(fake.url, timeout=0.2).run("IDeck", "X")

    assert time.monotonic() - started < 1.5


def test_a_trailing_slash_on_the_url_is_harmless(fake: FakeNRobot) -> None:
    NRobot(fake.url + "/", timeout=2.0).run("IDeck", "X")

    assert fake.calls[0][0] == "/RFTestCode.IDeck.IDeckLibrary"


def test_concurrent_calls_do_not_share_a_connection(robot: NRobot, fake: FakeNRobot) -> None:
    fake.delay = 0.05
    results: dict[int, str] = {}

    def call(number: int) -> None:
        fake.replies[f"K{number}"] = {**PASS, "return": f"r{number}"}
        results[number] = robot.run("IDeck", f"K{number}")

    threads = [threading.Thread(target=call, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == {n: f"r{n}" for n in range(8)}
