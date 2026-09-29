from app.schemas.health import HealthCheckResponse
from app.services.health_service import HealthService


class HealthController:
    def __init__(self, health_service: HealthService) -> None:
        self.health_service = health_service

    def check(self) -> HealthCheckResponse:
        return self.health_service.get_health()
