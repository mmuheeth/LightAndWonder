import asyncio
import base64
import heapq
import json
import logging
import os
import uuid
import subprocess
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import simpleobsws

from app.core.exceptions import AppException, NotFoundException, ServiceUnavailableException
from app.schemas.obs import (
    ObsConfig,
    ObsStatus,
    RecordingResult,
    ScreenshotFormat,
    ScreenshotInfo,
    ScreenshotMode,
)

logger = logging.getLogger(__name__)

# Windows process-creation flags: keep OBS alive independently of this backend
# (e.g. when uvicorn --reload restarts it).
_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

_HANDSHAKE_TIMEOUT = 5
_RETRY_INTERVAL = 1.0
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SCREENSHOT_SUFFIXES = (".bmp", ".png")
# obs-websocket maps PNG "compression quality" 100 to no deflate at all. The pixels are
# identical, but encoding is ~8x faster than OBS's default (~0.25s vs ~2s for 1080x1920).
_PNG_UNCOMPRESSED = 100

ClientFactory = Callable[[], simpleobsws.WebSocketClient]


class ObsService:
    """Controls a local OBS Studio through its obs-websocket server; captures go under `captures_dir`.
    The server host/port start from the given defaults and, once changed, persist in `config_file`."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        password: str,
        exe_path: Path,
        launch_timeout: float,
        captures_dir: Path,
        config_file: Path,
        screenshot_format: ScreenshotFormat = "bmp",
        screenshot_mode: ScreenshotMode = "scene",
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._config = ObsConfig(host=host, port=port)
        self._screenshot_format = screenshot_format
        self._screenshot_mode = screenshot_mode
        self._password = password
        self._config_file = config_file
        self._exe_path = exe_path
        self._launch_timeout = launch_timeout
        self._screenshots_dir = captures_dir / "screenshots"
        self._recordings_dir = captures_dir / "recordings"
        self._client_factory = client_factory or self._new_client
        self._client: simpleobsws.WebSocketClient | None = None
        self._connect_lock = asyncio.Lock()
        # Awaited after every fresh connection, e.g. to re-apply the capture-window setup.
        # It must not raise: a failing hook must never fail the connection itself.
        self.on_connected: Callable[[], Awaitable[None]] | None = None
        self._load_config()

    # ------------------------------------------------------------------ config

    def get_config(self) -> ObsConfig:
        return self._config

    async def update_config(self, config: ObsConfig) -> ObsConfig:
        """Points the app at another OBS server; any current connection is dropped."""
        async with self._connect_lock:
            client, self._client = self._client, None
            if client is not None:
                await client.disconnect()
            self._config = config
            self._save_config()
        return config

    def _new_client(self) -> simpleobsws.WebSocketClient:
        url = f"ws://{self._config.host}:{self._config.port}"
        return simpleobsws.WebSocketClient(url=url, password=self._password)

    def _load_config(self) -> None:
        try:
            data = json.loads(self._config_file.read_text(encoding="utf-8"))
            self._config = ObsConfig(host=data["host"], port=data["port"])
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("Ignoring unreadable OBS config file: %s", self._config_file)

    def _save_config(self) -> None:
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self._config_file.with_suffix(".tmp")
        tmp_file.write_text(self._config.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_file, self._config_file)  # atomic: never leaves a half-written file

    # ------------------------------------------------------------------ status

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_identified()

    async def get_status(self) -> ObsStatus:
        if self.connected:
            try:
                record = await self.request("GetRecordStatus")
            except AppException:
                pass  # The connection dropped just now; report it as disconnected below.
            else:
                recording = bool(record.get("outputActive"))
                return ObsStatus(
                    obs_running=True,
                    connected=True,
                    recording=recording,
                    recording_path=record.get("outputPath") if recording else None,
                )
        return ObsStatus(
            obs_running=await asyncio.to_thread(self._is_obs_running),
            connected=False,
            recording=False,
        )

    # ------------------------------------------------------------- connection

    async def connect(self) -> ObsStatus:
        """Connects to OBS, launching it first if it is not running."""
        newly_connected = False
        async with self._connect_lock:
            if self.connected:
                pass
            elif await self._try_connect():
                newly_connected = True
            else:
                newly_connected = True
                if self._config.host.lower() in _LOCAL_HOSTS:
                    if not await asyncio.to_thread(self._is_obs_running):
                        self._launch_obs()
                    await self._connect_with_retry()
                else:
                    # A remote OBS cannot be launched from here and is not "starting up".
                    raise ServiceUnavailableException(
                        f"Could not connect to OBS at {self._config.host}:{self._config.port}. "
                        "Check that OBS is running there with its websocket server enabled."
                    )
        if newly_connected and self.on_connected is not None:
            await self.on_connected()
        return await self.get_status()

    async def disconnect(self) -> ObsStatus:
        async with self._connect_lock:
            client, self._client = self._client, None
            if client is not None:
                await client.disconnect()
        return await self.get_status()

    async def _connect_with_retry(self) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._launch_timeout
        while not await self._try_connect():
            if loop.time() >= deadline:
                raise ServiceUnavailableException(
                    f"Could not connect to the OBS websocket server at {self._config.host}:"
                    f"{self._config.port}. Check that OBS is running, that the server is "
                    "enabled (Tools > WebSocket Server Settings), and that the port and "
                    "OBS_PASSWORD match."
                )
            await asyncio.sleep(_RETRY_INTERVAL)

    async def _try_connect(self) -> bool:
        client = self._client_factory()
        try:
            await client.connect()
            if await client.wait_until_identified(timeout=_HANDSHAKE_TIMEOUT):
                self._client = client
                return True
        except OSError:
            pass  # Nothing listening yet (OBS not started, or its server still starting).
        except Exception:
            logger.exception("Unexpected error while connecting to OBS")
        await client.disconnect()
        return False

    def _is_obs_running(self) -> bool:
        image = self._exe_path.name
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            logger.warning("Could not query running processes", exc_info=True)
            return False
        return image.lower() in result.stdout.lower()

    def _launch_obs(self) -> None:
        if not self._exe_path.is_file():
            raise ServiceUnavailableException(
                f"OBS executable not found at {self._exe_path}. Set OBS_EXE_PATH in backend/.env."
            )
        logger.info("Launching OBS: %s", self._exe_path)
        # OBS must start from its own bin directory or it cannot find its data files.
        # --disable-shutdown-check skips the "OBS crashed, run in safe mode?" prompt.
        subprocess.Popen(
            [str(self._exe_path), "--disable-shutdown-check"],
            cwd=self._exe_path.parent,
            creationflags=_DETACHED,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    # ------------------------------------------------------------ screenshots

    async def take_screenshot(
        self,
        image_format: ScreenshotFormat | None = None,
        mode: ScreenshotMode | None = None,
    ) -> ScreenshotInfo:
        """Captures what OBS is showing and returns the saved, lossless image.
        A local OBS writes the file itself; a remote one sends a compressed PNG over the websocket (slower)."""
        image_format = image_format or self._screenshot_format
        source = await self._screenshot_source(mode or self._screenshot_mode)

        if self._config.host.lower() in _LOCAL_HOSTS:
            path = self._new_screenshot_path(image_format)
            path.parent.mkdir(parents=True, exist_ok=True)
            request = {"sourceName": source, "imageFormat": image_format, "imageFilePath": str(path)}
            if image_format == "png":
                request["imageCompressionQuality"] = _PNG_UNCOMPRESSED
            await self.request("SaveSourceScreenshot", request)
        else:
            path = self._new_screenshot_path("png")
            data = await self.request(
                "GetSourceScreenshot", {"sourceName": source, "imageFormat": "png"}
            )
            # imageData is a data URI: "data:image/png;base64,<payload>".
            image = base64.b64decode(data["imageData"].split(",", 1)[-1])
            await asyncio.to_thread(self._write_file, path, image)

        logger.info("Saved OBS screenshot: %s", path)
        return self._describe(path)

    async def _screenshot_source(self, mode: ScreenshotMode) -> str:
        """Name of the OBS source to capture."""
        scene = (await self.request("GetCurrentProgramScene"))["currentProgramSceneName"]
        if mode == "native":
            items = (await self.request("GetSceneItemList", {"sceneName": scene}))["sceneItems"]
            visible = [item for item in items if item.get("sceneItemEnabled")]
            if len(visible) == 1 and self._is_untouched_input(visible[0]):
                return visible[0]["sourceName"]
        return scene

    @staticmethod
    def _is_untouched_input(item: dict) -> bool:
        """True if capturing the source alone looks the same as the scene: a plain input with no crop,
        rotation or flip (a scene shot rescales the source to canvas size, which softens text)."""
        t = item["sceneItemTransform"]
        return (
            not item.get("isGroup")
            and item.get("sourceType") == "OBS_SOURCE_TYPE_INPUT"
            and t["sourceWidth"] > 0
            and t["sourceHeight"] > 0  # e.g. the captured window is minimised
            and not any(t[side] for side in ("cropLeft", "cropRight", "cropTop", "cropBottom"))
            and t["rotation"] == 0
            and t["scaleX"] > 0
            and t["scaleY"] > 0
        )

    def _new_screenshot_path(self, image_format: str) -> Path:
        # The random suffix keeps simultaneous captures from overwriting each other.
        stamp = f"{datetime.now():%Y%m%d_%H%M%S_%f}"[:-3]
        return self._screenshots_dir / f"screenshot_{stamp}_{uuid.uuid4().hex[:6]}.{image_format}"

    def list_screenshots(self, limit: int) -> list[ScreenshotInfo]:
        """Newest first. One directory scan, however many screenshots have piled up."""
        try:
            with os.scandir(self._screenshots_dir) as entries:
                newest = heapq.nlargest(
                    limit,
                    (e for e in entries if e.name.endswith(_SCREENSHOT_SUFFIXES)),
                    key=lambda e: e.stat().st_mtime,  # cached from the scan on Windows
                )
        except FileNotFoundError:
            return []
        return [self._describe(Path(entry.path)) for entry in newest]

    def screenshot_path(self, filename: str) -> Path:
        # Only bare file names are accepted, so a request can never leave the folder.
        path = self._screenshots_dir / filename
        if (
            Path(filename).name != filename
            or path.suffix not in _SCREENSHOT_SUFFIXES
            or not path.is_file()
        ):
            raise NotFoundException("Screenshot not found")
        return path

    def _describe(self, path: Path) -> ScreenshotInfo:
        stat = path.stat()
        return ScreenshotInfo(
            filename=path.name,
            created_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
            size_bytes=stat.st_size,
            url=f"/obs/screenshots/{path.name}",
        )

    @staticmethod
    def _write_file(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    # -------------------------------------------------------------- recording

    async def start_recording(self) -> ObsStatus:
        await asyncio.to_thread(self._recordings_dir.mkdir, parents=True, exist_ok=True)
        await self.request(
            "SetRecordDirectory", {"recordDirectory": str(self._recordings_dir.resolve())}
        )
        await self.request("StartRecord")
        # OBS only reports the output as active a moment after accepting the request,
        # so an immediate status read would still say "not recording".
        status = await self.get_status()
        return status.model_copy(update={"recording": True})

    async def stop_recording(self) -> RecordingResult:
        data = await self.request("StopRecord")
        return RecordingResult(output_path=data.get("outputPath"))

    # ---------------------------------------------------------------- requests

    async def request(self, request_type: str, data: dict[str, Any] | None = None) -> dict:
        """Sends one obs-websocket request and returns its response data."""
        if not self.connected:
            raise ServiceUnavailableException("Not connected to OBS. Connect first.")
        try:
            response = await self._client.call(simpleobsws.Request(request_type, data))
        except (simpleobsws.NotIdentifiedError, simpleobsws.MessageTimeout, OSError) as exc:
            raise ServiceUnavailableException(f"Lost the connection to OBS ({exc}).") from exc
        if not response.ok():
            comment = response.requestStatus.comment or "no details given"
            raise AppException(
                message=f"OBS rejected {request_type}: {comment}",
                status_code=502,
                error_code="OBS_REQUEST_FAILED",
                details={"obs_code": response.requestStatus.code},
            )
        return response.responseData or {}
