from pathlib import Path

from app.schemas.obs import (
    ObsCaptureSetup,
    ObsConfig,
    ObsStatus,
    ObsWindow,
    RecordingResult,
    ScreenshotFormat,
    ScreenshotInfo,
    ScreenshotMode,
)
from app.services.obs_service import ObsService
from app.services.obs_window_service import ObsWindowService


class ObsController:
    def __init__(self, obs_service: ObsService, window_service: ObsWindowService) -> None:
        self.obs_service = obs_service
        self.window_service = window_service

    async def status(self) -> ObsStatus:
        return await self.obs_service.get_status()

    def get_config(self) -> ObsConfig:
        return self.obs_service.get_config()

    async def update_config(self, config: ObsConfig) -> ObsConfig:
        return await self.obs_service.update_config(config)

    async def connect(self) -> ObsStatus:
        return await self.obs_service.connect()

    async def disconnect(self) -> ObsStatus:
        return await self.obs_service.disconnect()

    async def take_screenshot(
        self,
        image_format: ScreenshotFormat | None = None,
        mode: ScreenshotMode | None = None,
    ) -> ScreenshotInfo:
        return await self.obs_service.take_screenshot(image_format, mode)

    def list_screenshots(self, limit: int) -> list[ScreenshotInfo]:
        return self.obs_service.list_screenshots(limit)

    def screenshot_path(self, filename: str) -> Path:
        return self.obs_service.screenshot_path(filename)

    async def start_recording(self) -> ObsStatus:
        return await self.obs_service.start_recording()

    async def stop_recording(self) -> RecordingResult:
        return await self.obs_service.stop_recording()

    async def list_windows(self) -> list[ObsWindow]:
        return await self.window_service.list_windows()

    async def capture_setup(self) -> ObsCaptureSetup:
        return await self.window_service.get_setup()

    async def select_window(self, window: ObsWindow) -> ObsCaptureSetup:
        return await self.window_service.select_window(window)
