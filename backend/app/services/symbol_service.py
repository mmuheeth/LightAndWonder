import asyncio
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from PIL import Image

from app.core.exceptions import AppException, BadRequestException, NotFoundException
from app.schemas.game_context import GameMode
from app.schemas.roi import RoiImage, RoiRecord
from app.schemas.symbol import (
    SymbolModelInfo,
    SymbolModelStatus,
    SymbolReading,
    SymbolTile,
    TrainingProgress,
)
from app.services.game_context_service import GameContextService
from app.services.roi_service import RoiService
from app.utils import game_config as game_settings
from app.utils.symbol_artwork import list_artwork

if TYPE_CHECKING:  # torch is only imported once a model is trained or used: it is slow to load
    from app.utils.symbol_classifier import SymbolClassifier

logger = logging.getLogger(__name__)

# The ROI region that is the reel grid, which the tiles are cut from.
_GRID_CROP = "reels"
_WEIGHTS_FILE = "model.pt"
_INFO_FILE = "model.json"
# Starting with a word character rules out "." and "..".
_READING_ID = re.compile(r"^\w[\w.\-]*$")


@dataclass
class _Job:
    """A training of one game's model that is running, or that failed."""

    state: Literal["training", "failed"] = "training"
    epoch: int = 0
    epochs: int = 0
    loss: float | None = None
    error: str | None = None


class SymbolService:
    """Trains a ResNet34 on a game's symbol artwork and names the symbols on its reels with it.
    A model is kept as `<models_dir>/<game>/`, a reading as `<readings_dir>/<id>.json`; the screenshot
    and the tiles come from the ROI extraction."""

    def __init__(
        self,
        *,
        roi: RoiService,
        game_context: GameContextService,
        games_dir: Path,
        models_dir: Path,
        readings_dir: Path,
        min_confidence: float,
    ) -> None:
        self._roi = roi
        self._game_context = game_context
        self._games_dir = games_dir
        self._models_dir = models_dir
        self._readings_dir = readings_dir
        self._min_confidence = min_confidence
        self._lock = threading.Lock()
        # The latest training of each game; one that succeeded is not kept, its model is on disk.
        self._jobs: dict[str, _Job] = {}
        self._classifiers: dict[str, tuple[datetime, "SymbolClassifier"]] = {}

    # ------------------------------------------------------------------ model

    def model_status(self, game: str | None = None) -> SymbolModelStatus:
        game = self._game(game)
        with self._lock:
            job = self._jobs.get(game)
            job = _Job(**vars(job)) if job is not None else None  # a snapshot: the trainer keeps writing
        artwork = list_artwork(self._symbols_dir(game))
        info = self._read_info(game)
        state = job.state if job is not None else ("ready" if info is not None else "untrained")
        return SymbolModelStatus(
            game=game,
            state=state,
            dataset_classes=len(artwork),
            dataset_images=sum(len(images) for images in artwork.values()),
            min_confidence=self._min_confidence,
            model=info,
            progress=(
                TrainingProgress(epoch=job.epoch, epochs=job.epochs, loss=job.loss)
                if job is not None and job.state == "training"
                else None
            ),
            error=job.error if job is not None else None,
        )

    def start_training(self, game: str | None = None) -> SymbolModelStatus:
        """Starts fitting the game's model in the background and returns at once; poll `model_status`.
        Only one model trains at a time, because training takes half the machine's cores."""
        game = self._game(game)
        artwork = list_artwork(self._symbols_dir(game))
        if len(artwork) < 2:
            raise AppException(
                f"'{game}' needs artwork for at least two symbols in {self._symbols_dir(game)} "
                f"(a folder per symbol code holding its images); found {len(artwork)}.",
                status_code=422,
                error_code="SYMBOL_ARTWORK_MISSING",
            )
        with self._lock:
            if any(job.state == "training" for job in self._jobs.values()):
                raise AppException(
                    "A symbol model is already being trained; wait for it to finish.",
                    status_code=409,
                    error_code="TRAINING_BUSY",
                )
            self._jobs[game] = _Job()
        threading.Thread(
            target=self._train, args=(game, artwork), name=f"symbol-training-{game}", daemon=True
        ).start()
        return self.model_status(game)

    def _train(self, game: str, artwork: dict[str, list[Path]]) -> None:
        try:
            from app.utils import symbol_classifier  # imported here: it loads torch

            def progress(epoch: int, epochs: int, loss: float) -> None:
                with self._lock:
                    job = self._jobs[game]
                    job.epoch, job.epochs, job.loss = epoch, epochs, loss

            logger.info("Training the symbol model of %s on %d symbols", game, len(artwork))
            report = symbol_classifier.train(artwork, self._model_dir(game) / _WEIGHTS_FILE, on_progress=progress)
            info = SymbolModelInfo(
                architecture=symbol_classifier.ARCHITECTURE,
                trained_at=datetime.now().astimezone(),
                classes=report.classes,
                image_count=report.image_count,
                epochs=report.epochs,
                accuracy=report.accuracy,
                floor=report.floor,
                unchecked=[code for code in report.classes if code not in report.per_class],
            )
            self._write_info(game, info)
            with self._lock:
                del self._jobs[game]
                self._classifiers.pop(game, None)
            logger.info(
                "Trained the symbol model of %s: accuracy %s, floor %s", game, report.accuracy, report.floor
            )
        except Exception as exc:  # nobody awaits this thread: the failure is kept for the status
            logger.exception("Training the symbol model of %s failed", game)
            with self._lock:
                job = self._jobs[game]
                job.state = "failed"
                job.error = str(exc) or type(exc).__name__

    # --------------------------------------------------------------- identify

    async def identify(self, game: str | None = None, mode: GameMode | None = None) -> SymbolReading:
        """Takes a screenshot, cuts the reel grid into tiles (the ROI extraction) and names each tile's
        symbol with the game's model. Game and mode default to the selected ones. The model is checked
        first, so a game that has none never touches OBS."""
        selection = self._game_context.get_context().context
        game, mode = self._game(game), mode or selection.mode
        info = self._read_info(game)
        if info is None:
            raise AppException(
                f"'{game}' has no trained symbol model yet; train it first.",
                status_code=409,
                error_code="SYMBOL_MODEL_MISSING",
            )
        record = await self._roi.extract(game, mode)
        if not record.tiles:
            raise AppException(
                f"'{game}' has no reel grid configured for mode '{mode.value}', so there are no tiles to read.",
                status_code=422,
                error_code="SYMBOL_NO_TILES",
            )
        return await asyncio.to_thread(self._read, game, info, record)

    def get_reading(self, reading_id: str) -> SymbolReading:
        if not _READING_ID.match(reading_id):  # it becomes a file name, and comes from a URL
            raise BadRequestException(f"Invalid reading id '{reading_id}'")
        try:
            return SymbolReading.model_validate_json(
                (self._readings_dir / f"{reading_id}.json").read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            raise NotFoundException(f"No symbol reading '{reading_id}'") from None
        except (OSError, ValueError) as exc:
            raise AppException(
                f"The symbol reading '{reading_id}' cannot be read: {exc}", error_code="SYMBOL_READING_UNREADABLE"
            ) from exc

    def list_readings(self, limit: int) -> list[SymbolReading]:
        """Newest first."""
        try:
            with os.scandir(self._readings_dir) as entries:
                names = sorted((e.name for e in entries if e.name.endswith(".json")), reverse=True)
        except FileNotFoundError:
            return []
        readings: list[SymbolReading] = []
        for name in names:
            try:
                readings.append(
                    SymbolReading.model_validate_json((self._readings_dir / name).read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):  # unreadable: skipped, like an unfinished ROI record
                continue
            if len(readings) == limit:
                break
        return readings

    def _read(self, game: str, info: SymbolModelInfo, record: RoiRecord) -> SymbolReading:
        from app.utils.symbol_classifier import SymbolTrainingError

        try:
            classifier = self._classifier(game, info)
            images = []
            for tile in record.tiles:
                with Image.open(self._roi.image_path(record.id, Path(tile.url).name)) as image:
                    images.append(image.convert("RGB"))
            predictions = classifier.classify(images)
        except SymbolTrainingError as exc:
            raise AppException(str(exc), status_code=409, error_code="SYMBOL_MODEL_UNUSABLE") from exc
        except OSError as exc:
            raise AppException(f"Could not read the tiles of {record.id}: {exc}", error_code="SYMBOL_FAILED") from exc

        names = _symbol_names(game)
        reading = SymbolReading(
            id=record.id,
            created_at=datetime.now().astimezone(),
            game=game,
            mode=record.mode,
            rows=record.rows,
            columns=record.columns,
            reels=next(
                (RoiImage(url=c.url, width=c.width, height=c.height) for c in record.crops if c.name == _GRID_CROP),
                None,
            ),
            model=info,
            tiles=[
                SymbolTile(
                    row=tile.row,
                    column=tile.column,
                    code=prediction.code,
                    name=names.get(prediction.code),
                    confidence=round(prediction.confidence, 2),
                )
                for tile, prediction in zip(record.tiles, predictions)
            ],
        )
        self._save_reading(reading)
        logger.info("Read %d symbols off %s for %s", len(reading.tiles), record.id, game)
        return reading

    def _classifier(self, game: str, info: SymbolModelInfo) -> "SymbolClassifier":
        """The loaded model of the game, loaded again after it has been retrained."""
        from app.utils.symbol_classifier import SymbolClassifier

        with self._lock:
            cached = self._classifiers.get(game)
            if cached is not None and cached[0] == info.trained_at:
                return cached[1]
        classifier = SymbolClassifier.load(self._model_dir(game) / _WEIGHTS_FILE)
        with self._lock:
            self._classifiers[game] = (info.trained_at, classifier)
        return classifier

    # ------------------------------------------------------------------ files

    def _game(self, game: str | None) -> str:
        game = game or self._game_context.get_context().context.game
        if not game or game_settings.load_game_config(game) is None:
            raise NotFoundException(f"Game '{game}' has no config")
        return game

    def _symbols_dir(self, game: str) -> Path:
        return self._games_dir / game / "symbols"

    def _model_dir(self, game: str) -> Path:
        return self._models_dir / game

    def _read_info(self, game: str) -> SymbolModelInfo | None:
        """The finished model's info, or None. It is written after the weights, so a model without it is unfinished."""
        try:
            return SymbolModelInfo.model_validate_json(
                (self._model_dir(game) / _INFO_FILE).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def _write_info(self, game: str, info: SymbolModelInfo) -> None:
        self._atomic_write(self._model_dir(game) / _INFO_FILE, info.model_dump_json(indent=2))

    def _save_reading(self, reading: SymbolReading) -> None:
        self._atomic_write(self._readings_dir / f"{reading.id}.json", reading.model_dump_json(indent=2))

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = path.with_suffix(path.suffix + ".tmp")
        tmp_file.write_text(text, encoding="utf-8")
        os.replace(tmp_file, path)


def _symbol_names(game: str) -> dict[str, str]:
    """Symbol code to name, from the game config's `"symbols"`."""
    symbols: Any = (game_settings.load_game_config(game) or {}).get("symbols")
    return {str(code): str(name) for code, name in symbols.items()} if isinstance(symbols, dict) else {}
