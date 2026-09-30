from functools import lru_cache
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.controllers.cyclic_controller import CyclicController
from app.controllers.game_config_controller import GameConfigController
from app.controllers.gaf_controller import GafController
from app.controllers.game_context_controller import GameContextController
from app.controllers.health_controller import HealthController
from app.controllers.obs_controller import ObsController
from app.controllers.ocr_controller import OcrController
from app.controllers.payline_controller import PaylineController
from app.controllers.roi_controller import RoiController
from app.controllers.symbol_controller import SymbolController
from app.services.cyclic_service import CyclicMessageService
from app.services.gaf_service import GafService
from app.services.game_config_service import GameConfigService
from app.services.game_context_service import GameContextService
from app.services.health_service import HealthService
from app.services.obs_service import ObsService
from app.services.ocr_service import OcrService
from app.services.payline_service import PaylineService
from app.services.roi_service import RoiService
from app.services.symbol_service import SymbolService
from app.utils.game_config import active_log_path
from app.utils.log_watcher import LogWatcher
from app.utils.nrobot import NRobot
from app.utils.ocr_engine import PaddleOcrEngine
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


@lru_cache
def get_ocr_engine() -> PaddleOcrEngine:
    """Shared, because every lane holds ~650 MB of models: the OCR tab and the cyclic message tracking read
    through the same ones."""
    return PaddleOcrEngine(lanes=get_settings().ocr_lanes)


@lru_cache
def get_ocr_controller() -> OcrController:
    """Shared, because the service keeps the OCR models loaded, and is built on the same OBS connection and
    GAF session as their tabs."""
    settings = get_settings()
    return OcrController(
        ocr_service=OcrService(
            obs=get_obs_service(),
            gaf=get_gaf_controller().gaf_service,
            game_context=get_game_context_service(),
            engine=get_ocr_engine(),
            captures_dir=_backend_path(settings.obs_captures_dir),
        )
    )


@lru_cache
def get_cyclic_controller() -> CyclicController:
    """Shared, because tracking is one task following the game's log, on the same OBS connection, log watcher
    and OCR engine as the tabs it builds on."""
    settings = get_settings()
    return CyclicController(
        cyclic_service=CyclicMessageService(
            obs=get_obs_service(),
            log=get_log_watcher(),
            game_context=get_game_context_service(),
            engine=get_ocr_engine(),
            captures_dir=_backend_path(settings.obs_captures_dir),
            capture_interval=settings.cyclic_capture_interval,
        )
    )


@lru_cache
def get_symbol_controller() -> SymbolController:
    """Shared, because only one model may train at a time and the service keeps the loaded models."""
    settings = get_settings()
    return SymbolController(
        symbol_service=SymbolService(
            roi=get_roi_controller().roi_service,
            game_context=get_game_context_service(),
            games_dir=BACKEND_DIR / "app" / "games",
            models_dir=_backend_path(settings.symbol_models_dir),
            readings_dir=_backend_path(settings.obs_captures_dir) / "symbols",
            min_confidence=settings.symbol_min_confidence,
        )
    )


@lru_cache
def get_payline_controller() -> PaylineController:
    """Built on the shared symbol and game config services: the symbols it reads are the Symbol tab's,
    and the paytable it scores with is the one the Game Config tab follows."""
    return PaylineController(
        payline_service=PaylineService(
            symbols=get_symbol_controller().symbol_service,
            game_config=get_game_config_controller().game_config_service,
            min_confidence=get_settings().symbol_min_confidence,
        )
    )


@lru_cache
def get_gaf_controller() -> GafController:
    """Shared, because the service remembers which game its session was opened for."""
    settings = get_settings()
    nrobot = NRobot(
        f"http://{settings.gaf_nrobot_host}:{settings.gaf_nrobot_port}",
        timeout=settings.gaf_keyword_timeout,
    )
    probe_nrobot = NRobot(nrobot.base_url, timeout=settings.gaf_probe_timeout)
    return GafController(
        gaf_service=GafService(
            nrobot=nrobot,
            probe_nrobot=probe_nrobot,
            game_context=get_game_context_service(),
            base_dir=BACKEND_DIR,
            settle_timeout=settings.gaf_settle_timeout,
            connect_attempts=settings.gaf_connect_attempts,
            connect_retry_delay=settings.gaf_connect_retry_delay,
        )
    )
