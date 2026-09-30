import asyncio
import logging
import os
import re
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from app.core.exceptions import AppException, NotFoundException
from app.schemas.game_context import GameMode
from app.schemas.obs import ScreenshotInfo
from app.schemas.ocr import OcrCrop, OcrEngineStatus, OcrReadings, OcrRecord, TextRead
from app.services.gaf_service import GafService
from app.services.game_context_service import GameContextService
from app.services.obs_service import ObsService
from app.utils import game_config as game_settings
from app.utils.image_crop import CropBox, InvalidCropError, crop_fraction
from app.utils.ocr_engine import OcrEngine, OcrEngineError
from app.utils.ocr_parse import MeterMode, parse_meter

logger = logging.getLogger(__name__)

# The game-config ROI that is the meter, whichever meter (cash or credits) the game shows in it.
_METER_REGION = "cash_meter"
_MESSAGE_REGIONS = ("cyclic_message", "cyclic_message_2")
# The GAF action that switches the meter between cash and credits.
_TOGGLE_ACTION = "toggle_credit_meter"

# The crops' names, which are also their file names. A meter is named for what it was showing, or "meter" when
# that was not known.
_CREDIT_METER = "credit_meter"
_CASH_METER = "cash_meter"
_METER_NAMES: dict[MeterMode | None, str] = {"credits": _CREDIT_METER, "cash": _CASH_METER, None: "meter"}
_CROP_ORDER = (_CREDIT_METER, _CASH_METER, "meter", *_MESSAGE_REGIONS)

# Seconds the game is given to draw the other meter once GAF reports the switch, before it is captured.
_SETTLE_SECONDS = 0.5
_ONE_METER = "Only the meter the game was showing was captured: "

# Sorts by time, like the screenshot names do.
_RECORD_ID = re.compile(r"^ocr_\d{8}_\d{6}_\d{3}_[0-9a-f]{6}$")
_RECORD_FILE = "record.json"
_IMAGE_SUFFIX = ".png"


@dataclass(frozen=True)
class _Plan:
    meter: CropBox
    messages: dict[str, CropBox]  # the message areas the game has, by config name


class OcrService:
    """Captures the game's meter and cyclic messages and reads them with OCR, in two steps: `extract` takes the
    screenshots and cuts the regions out, and `read` runs the OCR on those images. Each capture is a folder
    `<captures_dir>/ocr/<id>` with its images and a `record.json`, which `read` adds the readings to."""

    def __init__(
        self,
        *,
        obs: ObsService,
        gaf: GafService,
        game_context: GameContextService,
        engine: OcrEngine,
        captures_dir: Path,
    ) -> None:
        self._obs = obs
        self._gaf = gaf
        self._game_context = game_context
        self._engine = engine
        self._records_dir = captures_dir / "ocr"

    # ------------------------------------------------------------------ public

    async def extract(self, game: str | None = None, mode: GameMode | None = None) -> OcrRecord:
        """Screenshots the game and cuts the meter and message regions out (game and mode default to the
        selected). The config is checked first, so a game that cannot be extracted never touches OBS or GAF.

        When GAF can toggle the meter it is captured as found, toggled and captured again, then toggled back, so
        both meters are there and the game is left as it was. Otherwise only the meter on show is captured."""
        game, mode, plan = self._plan(game, mode)
        self._engine.preload()  # loading takes longer than the capture, so it starts now
        notes: list[str] = []
        shots, shown = [await self._obs.take_screenshot()], [None]

        toggled = await self._toggle(game, mode, notes)
        if toggled is not None:
            try:
                await asyncio.sleep(_SETTLE_SECONDS)
                shots.append(await self._obs.take_screenshot())
            finally:
                await self._toggle_back(game, mode, notes)
            shown = [_other(toggled), toggled]
        return await asyncio.to_thread(self._cut, game, mode, plan, shots, shown, notes)

    def warm_up(self) -> OcrEngineStatus:
        """Starts loading the OCR models in the background, for a caller that is about to read."""
        self._engine.preload()
        return OcrEngineStatus(ready=self._engine.ready)

    async def read(self, record_id: str) -> OcrRecord:
        """Runs the OCR on a capture's images and keeps the readings with it, replacing any earlier ones."""
        record = self._load(record_id)
        readings = await asyncio.to_thread(self._recognize, record)
        record = record.model_copy(update={"readings": readings})
        await asyncio.to_thread(self._save, record)
        return record

    def list_records(self, limit: int) -> list[OcrRecord]:
        """Newest first."""
        try:
            with os.scandir(self._records_dir) as entries:
                ids = sorted((e.name for e in entries if e.is_dir()), reverse=True)
        except FileNotFoundError:
            return []
        records: list[OcrRecord] = []
        for record_id in ids:
            record = self._read_record(record_id)
            if record is not None:  # a folder without a readable record is an unfinished one
                records.append(record)
                if len(records) == limit:
                    break
        return records

    def image_path(self, record_id: str, filename: str) -> Path:
        # Only ids and bare file names of ours are accepted, so a request can never leave the folder.
        path = self._records_dir / record_id / filename
        if (
            not _RECORD_ID.match(record_id)
            or Path(filename).name != filename
            or path.suffix != _IMAGE_SUFFIX
            or not path.is_file()
        ):
            raise NotFoundException("OCR image not found")
        return path

    # ---------------------------------------------------------------- planning

    def _plan(self, game: str | None, mode: GameMode | None) -> tuple[str, GameMode, _Plan]:
        selection = self._game_context.get_context().context
        game, mode = game or selection.game, mode or selection.mode
        config = game_settings.load_game_config(game) if game else None
        if config is None:
            raise NotFoundException(f"Game '{game}' has no config")

        section = config.get(mode.value)
        rois = section.get("roi") if isinstance(section, dict) else None
        rois = rois if isinstance(rois, dict) else {}
        if not rois.get(_METER_REGION):
            raise NotFoundException(f"'{game}' has no '{_METER_REGION}' ROI configured for mode '{mode.value}'")
        boxes: dict[str, CropBox] = {}
        for name in (_METER_REGION, *_MESSAGE_REGIONS):
            if not rois.get(name):  # e.g. "cyclic_message": [] for a game without that message
                continue
            try:
                boxes[name] = CropBox.from_sequence(rois[name])
            except InvalidCropError as exc:
                raise AppException(
                    f"ROI '{name}' of mode '{mode.value}' in the config of '{game}' is invalid: {exc}",
                    error_code="CONFIG_INVALID",
                ) from exc
        return game, mode, _Plan(meter=boxes.pop(_METER_REGION), messages=boxes)

    # ------------------------------------------------------------------ toggling

    async def _toggle(self, game: str, mode: GameMode, notes: list[str]) -> MeterMode | None:
        """Switches the meter through GAF. Returns the meter it shows now, or None (with a note) when the
        captures cannot be told apart: it could not be switched, or not to cash or credits."""
        try:
            result = await self._gaf.run_action(_TOGGLE_ACTION, game=game, mode=mode)
        except AppException as exc:
            notes.append(f"{_ONE_METER}GAF could not toggle it ({exc.message})")
            return None
        if result.values.get("outcome") != "toggled":
            notes.append(_ONE_METER + result.message)
            return None
        shows = _meter_of(result.values.get("label"))
        if shows is None:
            notes.append(f"{_ONE_METER}GAF reported the toggled meter as {result.values.get('label')!r}.")
            await self._toggle_back(game, mode, notes)
        return shows

    async def _toggle_back(self, game: str, mode: GameMode, notes: list[str]) -> None:
        """Puts the meter back as it was found. A failure is a note, not an error: the captures are good."""
        try:
            result = await self._gaf.run_action(_TOGGLE_ACTION, game=game, mode=mode)
            problem = None if result.values.get("outcome") == "toggled" else result.message
        except AppException as exc:
            problem = exc.message
        if problem is not None:
            logger.warning("Could not toggle the meter back: %s", problem)
            notes.append(f"The meter could not be switched back and was left as it is now: {problem}")

    # -------------------------------------------------------------- extraction

    def _cut(
        self,
        game: str,
        mode: GameMode,
        plan: _Plan,
        shots: list[ScreenshotInfo],
        shown: list[MeterMode | None],
        notes: list[str],
    ) -> OcrRecord:
        created_at = datetime.now().astimezone()
        record_id = f"ocr_{created_at:%Y%m%d_%H%M%S_%f}"[:-3] + f"_{uuid.uuid4().hex[:6]}"
        directory = self._records_dir / record_id
        directory.mkdir(parents=True)
        crops: dict[str, OcrCrop] = {}

        def save(full: Image.Image, name: str, box: CropBox) -> None:
            image = crop_fraction(full, box)
            filename = f"{name}{_IMAGE_SUFFIX}"
            image.save(directory / filename)
            crops[name] = OcrCrop(
                name=name,
                roi=list(box.as_tuple()),
                url=f"/ocr/records/{record_id}/images/{filename}",
                width=image.width,
                height=image.height,
            )

        try:
            for index, (shot, meter) in enumerate(zip(shots, shown)):
                with Image.open(self._obs.screenshot_path(shot.filename)) as full:
                    full.load()
                    save(full, _METER_NAMES[meter], plan.meter)
                    if index == 0:  # the messages cycle on their own, so one moment of them is as good as another
                        for name, box in plan.messages.items():
                            save(full, name, box)
            record = OcrRecord(
                id=record_id,
                created_at=created_at,
                game=game,
                mode=mode,
                screenshots=shots,
                crops=[crops[name] for name in _CROP_ORDER if name in crops],
                notes=notes,
            )
            self._save(record)
        except InvalidCropError as exc:
            shutil.rmtree(directory, ignore_errors=True)
            raise AppException(
                f"Could not cut the regions out of the screenshot: {exc}", status_code=422, error_code="OCR_INVALID"
            ) from exc
        except OSError as exc:  # includes an image Pillow cannot read
            shutil.rmtree(directory, ignore_errors=True)
            raise AppException(
                f"Could not read the screenshot or save its regions: {exc}", error_code="OCR_FAILED"
            ) from exc
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        logger.info("Saved OCR record %s (%d crops)", record_id, len(record.crops))
        return record

    # ----------------------------------------------------------------- reading

    def _recognize(self, record: OcrRecord) -> OcrReadings:
        """Reads every crop, as many at a time as the engine has lanes. The meters come first in the record, and
        are the slow ones, so the quick message lines fill the gaps behind them."""
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=max(1, min(len(record.crops), self._engine.lanes))) as pool:
            futures = [pool.submit(self._recognize_crop, record, crop) for crop in record.crops]
            results = [future.result() for future in futures]  # the first failure, in crop order
        fields: dict[str, Any] = {}
        issues: list[str] = []
        for crop_fields, crop_issues in results:
            fields.update(crop_fields)
            issues += crop_issues
        seconds = time.monotonic() - started
        logger.info("Read OCR record %s in %.1fs", record.id, seconds)
        return OcrReadings(read_at=datetime.now().astimezone(), seconds=round(seconds, 1), issues=issues, **fields)

    def _recognize_crop(self, record: OcrRecord, crop: OcrCrop) -> tuple[dict[str, Any], list[str]]:
        """What one crop reads as: the fields of `OcrReadings` it fills in, and issues that belong to no meter."""
        path = self._records_dir / record.id / f"{crop.name}{_IMAGE_SUFFIX}"
        try:
            with Image.open(path) as image:
                image.load()
                return self._read_image(crop.name, image)
        except OcrEngineError as exc:
            raise AppException(str(exc), status_code=503, error_code="OCR_UNAVAILABLE") from exc
        except OSError as exc:
            raise AppException(f"Could not read the image of '{crop.name}': {exc}", error_code="OCR_FAILED") from exc

    def _read_image(self, name: str, image: Image.Image) -> tuple[dict[str, Any], list[str]]:
        if name in _MESSAGE_REGIONS:
            line = self._engine.read_line(image)
            return {name: TextRead(text=line.text, confidence=round(line.score * 100, 1) if line.text else None)}, []
        if name == _CREDIT_METER:
            return {name: parse_meter(self._engine.read_boxes(image), "credits").as_credit_meter()}, []
        if name == _CASH_METER:
            return {name: parse_meter(self._engine.read_boxes(image), "cash").as_cash_meter()}, []
        # The meter of which nothing was known: its labels say which it is.
        parsed = parse_meter(self._engine.read_boxes(image))
        if parsed.shows == "credits":
            return {_CREDIT_METER: parsed.as_credit_meter()}, []
        if parsed.shows == "cash":
            return {_CASH_METER: parsed.as_cash_meter()}, []
        return {}, parsed.issues

    # ------------------------------------------------------------------ records

    def _load(self, record_id: str) -> OcrRecord:
        record = self._read_record(record_id) if _RECORD_ID.match(record_id) else None
        if record is None:
            raise NotFoundException("OCR record not found")
        return record

    def _read_record(self, record_id: str) -> OcrRecord | None:
        try:
            text = (self._records_dir / record_id / _RECORD_FILE).read_text(encoding="utf-8")
            return OcrRecord.model_validate_json(text)
        except (OSError, ValueError):
            return None

    def _save(self, record: OcrRecord) -> None:
        # Atomically: a reader, and a folder without a record, never see half a file.
        directory = self._records_dir / record.id
        tmp_file = directory / f"{_RECORD_FILE}.tmp"
        tmp_file.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_file, directory / _RECORD_FILE)


def _meter_of(label: object) -> MeterMode | None:
    """The meter a GAF label names: "CASH" or "CREDITS"."""
    text = str(label or "").upper()
    if "CASH" in text:
        return "cash"
    return "credits" if "CREDIT" in text else None


def _other(meter: MeterMode) -> MeterMode:
    return "cash" if meter == "credits" else "credits"
