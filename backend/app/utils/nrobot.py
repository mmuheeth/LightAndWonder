"""The Robot Framework remote protocol, spoken to `NRobot.Server.exe` over XML-RPC.

NRobot hosts one keyword library per area of the game (`IDeck`, `GameMeter`, ...) and turns each
call into a Thrift request to the game. This module knows the protocol and nothing about slot games.
Everything here blocks, so async callers run it in a thread."""

import http.client
import socket
import xmlrpc.client
from typing import Any

# Every library is served at `<base>/RFTestCode.<Area>.<Area>Library`.
_NAMESPACE = "RFTestCode"


class NRobotError(Exception):
    """Base of everything this module raises."""


class NRobotUnreachable(NRobotError):
    """Nothing usable answered. Either nothing listens, or the wrong thing does: a server started
    from another directory answers but has none of the libraries loaded, which reads as a fault."""


class KeywordFailed(NRobotError):
    """The server ran the keyword and it failed. This is a normal-looking reply with status FAIL,
    not an XML-RPC fault, so it is only noticed by checking for it."""

    def __init__(self, library: str, keyword: str, error: str) -> None:
        self.library = library
        self.keyword = keyword
        self.error = error
        super().__init__(f"{keyword} failed: {error}")


class _TimeoutTransport(xmlrpc.client.Transport):
    """`ServerProxy` has no timeout of its own; without one a half-closed socket hangs a call forever."""

    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host: Any) -> http.client.HTTPConnection:
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        return connection


class NRobot:
    """Calls keywords by library area and name. Arguments are sent as strings, as the protocol does."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def base_url(self) -> str:
        return self._base_url

    def run(self, area: str, keyword: str, *args: object) -> Any:
        """Runs `keyword` of the `<area>.<area>Library` library and returns what it returned:
        a string, a number, a bool or a list, as the keyword decides.

        Raises `KeywordFailed` if the keyword ran and failed, `NRobotUnreachable` if it could not run."""
        library = f"{_NAMESPACE}.{area}.{area}Library"
        # One proxy per call: a proxy keeps one HTTP connection, which two threads must not share.
        proxy = xmlrpc.client.ServerProxy(
            f"{self._base_url}/{library}",
            transport=_TimeoutTransport(self._timeout),
            allow_none=True,
        )
        try:
            reply = proxy.run_keyword(keyword.upper(), [str(arg) for arg in args])
        except xmlrpc.client.Fault as exc:
            raise NRobotUnreachable(f"{library}.run_keyword faulted: {exc}") from exc
        except (OSError, socket.timeout, http.client.HTTPException, xmlrpc.client.ProtocolError) as exc:
            raise NRobotUnreachable(f"Cannot reach NRobot at {self._base_url}: {exc}") from exc
        except xmlrpc.client.ResponseError as exc:
            raise NRobotUnreachable(f"NRobot at {self._base_url} sent an unreadable reply: {exc}") from exc

        if not isinstance(reply, dict) or reply.get("status") != "PASS":
            error = reply.get("error") if isinstance(reply, dict) else None
            raise KeywordFailed(library, keyword, str(error or "no details given").strip())
        return reply.get("return")
