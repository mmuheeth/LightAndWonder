from pydantic import BaseModel


class HealthCheckResponse(BaseModel):
    status: str
    app_name: str
    app_version: str
    app_env: str
    uptime_seconds: float
