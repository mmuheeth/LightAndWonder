import time

from app.config.settings import Settings
from app.schemas.health import HealthCheckResponse

_started_at = time.monotonic()


class HealthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_health(self) -> HealthCheckResponse:
        return HealthCheckResponse(
            status="ok",
            app_name=self.settings.app_name,
            app_version=self.settings.app_version,
            app_env=self.settings.app_env,
            uptime_seconds=round(time.monotonic() - _started_at, 3),
        )
