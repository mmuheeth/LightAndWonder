from functools import lru_cache
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.controllers.game_config_controller import GameConfigController
from app.controllers.game_context_controller import GameContextController
from app.controllers.health_controller import HealthController
from app.controllers.obs_controller import ObsController
from app.controllers.roi_controller import RoiController
from app.services.game_config_service import GameConfigService
from app.services.game_context_service import GameContextService
from app.services.health_service import HealthService
from app.services.obs_service import ObsService
from app.services.roi_service import RoiService
from app.utils.game_config import active_log_path
from app.utils.log_watcher import LogWatcher
from app.services.obs_window_service import ObsWindowService

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _backend_path(configured: str) -> Path:
    """Relative paths in settings are relative to the backend folder, not the cwd."""
    path = Path(configured)
    return path if path.is_absolute() else BACKEND_DIR / path


@lru_cache
def get_health_controller() -> HealthController:
    settings: Settings = get_settings()
    return HealthController(health_service=HealthService(settings=settings))


@lru_cache
def get_game_context_service() -> GameContextService:
    """Shared, because the log watcher and Game Config must follow the same selection as the UI."""
    state_file = _backend_path(get_settings().game_context_file)
    return GameContextService(state_file=state_file)


@lru_cache
def get_game_context_controller() -> GameContextController:
    return GameContextController(game_context_service=get_game_context_service())


@lru_cache
def get_log_watcher() -> LogWatcher:
    """Follows the log of the selected game and mode. Started and stopped by the app lifespan."""
    game_context = get_game_context_service()
    return LogWatcher(lambda: active_log_path(game_context))


@lru_cache
def get_game_config_controller() -> GameConfigController:
    return GameConfigController(
        game_config_service=GameConfigService(
            game_context=get_game_context_service(), log_watcher=get_log_watcher()
        )
    )


@lru_cache
def get_obs_service() -> ObsService:
    """Shared, because the OBS tab and ROI extraction talk to the same OBS connection."""
    settings = get_settings()
    return ObsService(
        host=settings.obs_host,
        port=settings.obs_port,
        password=settings.obs_password,
        exe_path=Path(settings.obs_exe_path),
        launch_timeout=settings.obs_launch_timeout,
        captures_dir=_backend_path(settings.obs_captures_dir),
        config_file=_backend_path(settings.obs_config_file),
        screenshot_format=settings.obs_screenshot_format,
        screenshot_mode=settings.obs_screenshot_mode,
    )


@lru_cache
def get_obs_controller() -> ObsController:
    obs_service = get_obs_service()
    window_service = ObsWindowService(
        obs=obs_service, state_file=_backend_path(get_settings().obs_window_file)
    )
    return ObsController(obs_service=obs_service, window_service=window_service)


@lru_cache
def get_roi_controller() -> RoiController:
    return RoiController(
        roi_service=RoiService(
            obs=get_obs_service(),
            game_context=get_game_context_service(),
            captures_dir=_backend_path(get_settings().obs_captures_dir),
        )
    )
