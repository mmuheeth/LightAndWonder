from pathlib import Path

from app.services.obs_service import ObsService
from tests.fake_obs import FakeObs


def make_service(fake_obs: FakeObs, captures_dir: Path, config_file: Path) -> ObsService:
    return ObsService(
        host="localhost",
        port=4455,
        password="",
        exe_path=Path("obs64.exe"),
        launch_timeout=1,
        captures_dir=captures_dir,
        config_file=config_file,
        client_factory=fake_obs.make_client,
    )
