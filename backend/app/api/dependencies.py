from functools import lru_cache

from app.config.settings import Settings, get_settings
from app.controllers.health_controller import HealthController
from app.services.health_service import HealthService


@lru_cache
def get_health_controller() -> HealthController:
    settings: Settings = get_settings()
    return HealthController(health_service=HealthService(settings=settings))
