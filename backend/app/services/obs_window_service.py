import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import AppException, BadRequestException
from app.schemas.obs import ObsCaptureSetup, ObsWindow
from app.services.obs_service import ObsService

logger = logging.getLogger(__name__)

_INPUT_KIND = "window_capture"
_INPUT_NAME = "Window Capture"
# What a newly created capture source starts with: Windows Graphics Capture, the window's
# client area only (no title bar), no mouse cursor drawn over the picture.
_NEW_INPUT_SETTINGS = {"method": 2, "client_area": True, "cursor": False}
_OBS_RESOURCE_ALREADY_EXISTS = 601

# A freshly selected window reports its size a moment later, and briefly still reports the
# previous window's. Its size is trusted once it has been the same for this many polls.
_SIZE_POLL_INTERVAL = 0.1
_SIZE_STABLE_POLLS = 3
_SIZE_TIMEOUT = 3.0

# While connected, the captured window's size is checked this often. OBS sends no event when
# a captured window is resized, so this is the only way to notice. A new size must be seen on
# two checks in a row before the canvas follows it, so dragging a window edge does not make
# OBS rebuild its video pipeline for every intermediate size.
_WATCH_INTERVAL = 0.5
# After OBS refuses a canvas change (e.g. while recording), wait this long before trying again.
_WATCH_RETRY_AFTER = 5.0


def _even(width: int, height: int) -> tuple[int, int]:
    """Video encoders need even dimensions; an odd size gets one spare row/column of black."""
    return width + width % 2, height + height % 2


@dataclass(frozen=True)
class _CaptureItem:
    scene: str
    item_id: int
    input_name: str


class ObsWindowService:
    """Chooses which window OBS captures and fits the canvas to its size, with the source placed 1:1.
    The choice is saved, re-applied whenever OBS connects, and the canvas follows window resizes."""

    def __init__(self, obs: ObsService, state_file: Path) -> None:
        self._obs = obs
        self._state_file = state_file
        self._selected: ObsWindow | None = None
        self._warning: str | None = None
        self._applied = False
        self._canvas: tuple[int, int] | None = None  # what the canvas was last fitted to
        self._watcher: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._load()
        obs.on_connected = self.apply_saved

    # ------------------------------------------------------------------- reads

    async def list_windows(self) -> list[ObsWindow]:
        """Windows OBS can capture right now. Creates the capture source if the scene has none."""
        target = await self._ensure_capture_item()
        data = await self._obs.request(
            "GetInputPropertiesListPropertyItems",
            {"inputName": target.input_name, "propertyName": "window"},
        )
        windows = [
            ObsWindow(value=item["itemValue"], name=item["itemName"])
            for item in data["propertyItems"]
            if item["itemValue"]  # the blank "no window" entry
        ]
        return sorted(windows, key=lambda window: window.name.lower())

    async def get_setup(self) -> ObsCaptureSetup:
        width = height = None
        if self._obs.connected:
            video = await self._obs.request("GetVideoSettings")
            width, height = video["baseWidth"], video["baseHeight"]
        return ObsCaptureSetup(
            window=self._selected,
            canvas_width=width,
            canvas_height=height,
            applied=self._applied,
            warning=self._warning,
        )

    # ----------------------------------------------------------------- changes

    async def select_window(self, window: ObsWindow) -> ObsCaptureSetup:
        """Captures `window` from now on. Nothing is saved unless it could be applied."""
        async with self._lock:
            await self._apply(window)
            self._selected = window
            self._save()
        self._start_watching()
        return await self.get_setup()

    async def apply_saved(self) -> None:
        """Connect hook: applies the saved window, turning failures into a warning."""
        if self._selected is None:
            return
        self._canvas = None  # forget the previous connection's layout
        async with self._lock:
            try:
                await self._apply(self._selected)
            except AppException as exc:
                logger.warning("Could not apply the saved capture window: %s", exc.message)
                self._applied, self._warning = False, exc.message
            except Exception:
                logger.exception("Unexpected error applying the saved capture window")
                self._applied, self._warning = False, "Could not apply the saved window."
        # Even if it could not be applied (e.g. the window is not open yet), keep watching so
        # the canvas is fitted as soon as the window shows up.
        self._start_watching()

    # ---------------------------------------------------------------- applying

    async def _apply(self, window: ObsWindow) -> None:
        target = await self._ensure_capture_item()
        await self._obs.request(
            "SetInputSettings",
            {"inputName": target.input_name, "inputSettings": {"window": window.value}},
        )
        size = await self._wait_for_window_size(target)
        if size is None:
            raise BadRequestException(
                "OBS cannot capture that window. Check that it is open and not minimised."
            )
        await self._fit_canvas(target, *size)
        self._applied, self._warning = True, None

    async def _find_capture_item(self) -> tuple[str, _CaptureItem | None]:
        """The current scene's name and its window capture, if it has one."""
        scene = (await self._obs.request("GetCurrentProgramScene"))["currentProgramSceneName"]
        items = (await self._obs.request("GetSceneItemList", {"sceneName": scene}))["sceneItems"]
        captures = [item for item in items if item.get("inputKind") == _INPUT_KIND]
        if not captures:
            return scene, None
        # Prefer a visible one; a hidden capture would produce an empty screenshot.
        item = next((i for i in captures if i["sceneItemEnabled"]), captures[0])
        return scene, _CaptureItem(scene, item["sceneItemId"], item["sourceName"])

    async def _ensure_capture_item(self) -> _CaptureItem:
        """The current scene's window capture, created if the scene has none."""
        scene, item = await self._find_capture_item()
        return item or await self._create_capture_item(scene)

    async def _create_capture_item(self, scene: str) -> _CaptureItem:
        logger.info("Scene '%s' has no window capture; creating '%s'", scene, _INPUT_NAME)
        try:
            data = await self._obs.request(
                "CreateInput",
                {
                    "sceneName": scene,
                    "inputName": _INPUT_NAME,
                    "inputKind": _INPUT_KIND,
                    "inputSettings": _NEW_INPUT_SETTINGS,
                    "sceneItemEnabled": True,
                },
            )
        except AppException as exc:
            if (exc.details or {}).get("obs_code") != _OBS_RESOURCE_ALREADY_EXISTS:
                raise
            # The source exists (in another scene): reuse it here instead.
            data = await self._obs.request(
                "CreateSceneItem",
                {"sceneName": scene, "sourceName": _INPUT_NAME, "sceneItemEnabled": True},
            )
        return _CaptureItem(scene, data["sceneItemId"], _INPUT_NAME)

    async def _wait_for_window_size(self, target: _CaptureItem) -> tuple[int, int] | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _SIZE_TIMEOUT
        last: tuple[int, int] | None = None
        stable = 0
        while loop.time() < deadline:
            size = await self._source_size(target)
            if size is None:
                stable = 0
            else:
                stable = stable + 1 if size == last else 1
                if stable >= _SIZE_STABLE_POLLS:
                    return size
            last = size
            await asyncio.sleep(_SIZE_POLL_INTERVAL)
        return None

    async def _fit_canvas(self, target: _CaptureItem, width: int, height: int) -> None:
        canvas = _even(width, height)
        video = await self._obs.request("GetVideoSettings")
        # OBS aligns the output width down to a multiple of 4 (766 becomes 764), so the output
        # is compared with some tolerance; rewriting it needlessly would also fail whenever
        # OBS is recording.
        fits = (
            (video["baseWidth"], video["baseHeight"]) == canvas
            and video["outputHeight"] == canvas[1]
            and 0 <= canvas[0] - video["outputWidth"] < 4
        )
        if not fits:
            await self._obs.request(
                "SetVideoSettings",
                {
                    "baseWidth": canvas[0],
                    "baseHeight": canvas[1],
                    "outputWidth": canvas[0],
                    "outputHeight": canvas[1],
                },
            )
        await self._obs.request(
            "SetSceneItemEnabled",
            {"sceneName": target.scene, "sceneItemId": target.item_id, "sceneItemEnabled": True},
        )
        await self._obs.request(
            "SetSceneItemTransform",
            {
                "sceneName": target.scene,
                "sceneItemId": target.item_id,
                "sceneItemTransform": {
                    "positionX": 0,
                    "positionY": 0,
                    "alignment": 5,  # top-left
                    "boundsType": "OBS_BOUNDS_NONE",
                    "scaleX": 1,
                    "scaleY": 1,
                    "rotation": 0,
                    "cropLeft": 0,
                    "cropRight": 0,
                    "cropTop": 0,
                    "cropBottom": 0,
                    "cropToBounds": False,
                },
            },
        )
        self._canvas = canvas

    # ---------------------------------------------------------------- watching

    def _start_watching(self) -> None:
        if self._watcher is None or self._watcher.done():
            self._watcher = asyncio.get_running_loop().create_task(self._watch())

    async def _watch(self) -> None:
        """Keeps the canvas fitted to the window until OBS disconnects."""
        loop = asyncio.get_running_loop()
        settling: tuple[int, int] | None = None
        retry_at = 0.0
        while self._obs.connected:
            await asyncio.sleep(_WATCH_INTERVAL)
            try:
                _, target = await self._find_capture_item()
                size = await self._source_size(target) if target else None
                if size is None or _even(*size) == self._canvas:
                    settling = None
                elif size != settling:
                    settling = size  # wait until it has stopped changing
                elif loop.time() >= retry_at:
                    async with self._lock:
                        await self._fit_canvas(target, *size)
                    self._applied, self._warning = True, None
                    settling = None
            except AppException as exc:
                # Either the connection dropped (the loop then ends) or OBS refused the change.
                if self._obs.connected:
                    logger.warning("Could not fit the canvas to the window: %s", exc.message)
                    self._applied, self._warning = False, exc.message
                    retry_at = loop.time() + _WATCH_RETRY_AFTER
            except Exception:
                logger.exception("Unexpected error while watching the capture window")
                retry_at = loop.time() + _WATCH_RETRY_AFTER

    async def _source_size(self, target: _CaptureItem) -> tuple[int, int] | None:
        """The captured window's size, or None if nothing is being captured right now."""
        data = await self._obs.request(
            "GetSceneItemTransform",
            {"sceneName": target.scene, "sceneItemId": target.item_id},
        )
        transform = data["sceneItemTransform"]
        size = (round(transform["sourceWidth"]), round(transform["sourceHeight"]))
        return size if size[0] > 0 and size[1] > 0 else None

    # ------------------------------------------------------------- persistence

    def _load(self) -> None:
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            self._selected = ObsWindow(value=data["value"], name=data.get("name", ""))
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("Ignoring unreadable capture window file: %s", self._state_file)

    def _save(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self._state_file.with_suffix(".tmp")
        tmp_file.write_text(self._selected.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_file, self._state_file)  # atomic: never leaves a half-written file
