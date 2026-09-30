from functools import lru_cache

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LightAndWonder"
    app_env: str = "development"
    app_version: str = "0.1.0"
    debug: bool = True

    host: str = "0.0.0.0"
    port: int = 8000

    log_level: str = "INFO"

    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"

    # Where the selected game/mode is saved so it survives restarts.
    game_context_file: str = "data/game_context.json"

    # OBS Studio, controlled over its built-in obs-websocket server.
    # Host/port are only defaults: the server can be changed from the UI and is then
    # saved to obs_config_file, which takes precedence over these.
    obs_host: str = "localhost"
    obs_port: int = 4455
    obs_password: str = ""
    obs_exe_path: str = r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"
    # Seconds to wait for OBS to launch and its websocket server to accept connections.
    obs_launch_timeout: float = 30.0
    # Screenshots go to <dir>/screenshots and recordings to <dir>/recordings.
    obs_captures_dir: str = "obs-captures/obs"
    obs_config_file: str = "data/obs_config.json"
    # The window chosen for capture; re-applied to OBS on every connect.
    obs_window_file: str = "data/obs_window.json"
    # Default screenshot format: "bmp" (fastest, lossless) or "png" (lossless, ~3x slower).
    obs_screenshot_format: Literal["bmp", "png"] = "bmp"
    # "scene" captures the composed scene at canvas size (constant image size); "native"
    # captures the scene's single source at its own pixel size, which follows the source
    # (e.g. the game window) if it is resized. See ObsService.
    obs_screenshot_mode: Literal["native", "scene"] = "scene"

    # GAF: the game is driven through NRobot.Server.exe (part of the AGF image), which hosts the
    # Robot Framework keyword libraries and talks Thrift to the game. This is only where NRobot
    # listens; the game's own host/port come from its config. Nothing here starts NRobot.
    gaf_nrobot_host: str = "127.0.0.1"
    gaf_nrobot_port: int = 8270
    # Seconds one keyword may take. Connecting to a game that is not there fails after ~20s.
    gaf_keyword_timeout: float = 30.0
    # Seconds the status probe may take; the UI polls it, so it must answer inside the browser's timeout.
    gaf_probe_timeout: float = 4.0
    # Seconds a spin may keep playing before it is reported as "timeout" (e.g. a long bonus).
    gaf_settle_timeout: float = 120.0
    # A freshly launched game takes a while to accept the connection.
    gaf_connect_attempts: int = 3
    gaf_connect_retry_delay: float = 2.0

    # Symbols: a ResNet34 fitted to each game's artwork (app/games/<game>/symbols/<code>/*.png); the
    # trained model of a game is kept under symbol_models_dir.
    symbol_models_dir: str = "data/symbol_models"
    # Percent a tile's best guess must reach for the Symbol tab to name it. Only the tab's starting
    # value: it can be changed there.
    symbol_min_confidence: float = Field(90.0, ge=0, le=100)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
