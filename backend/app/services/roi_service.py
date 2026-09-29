import asyncio
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from app.core.exceptions import AppException, NotFoundException
from app.schemas.game_context import GameMode
from app.schemas.obs import ScreenshotInfo
from app.schemas.roi import RoiCrop, RoiRecord, RoiTile
from app.services.game_context_service import GameContextService
from app.services.obs_service import ObsService
from app.utils import game_config as game_settings
from app.utils.image_crop import CropBox, InvalidCropError, crop_fraction, grid_boxes, split_grid

logger = logging.getLogger(__name__)

# The region of the game config whose crop is the reel grid, and is split into tiles.
_GRID_REGION = "reels"
# Shown in this order; any other region the game configures follows, in config order.
_REGION_ORDER = (_GRID_REGION, "cash_meter", "cyclic_message", "cyclic_message_2")
# Region names become file names.
_REGION_NAME = re.compile(r"^[A-Za-z0-9_]+$")
# Sorts by time, like the screenshot names do.
_RECORD_ID = re.compile(r"^roi_\d{8}_\d{6}_\d{3}_[0-9a-f]{6}$")
_RECORD_FILE = "record.json"
_IMAGE_SUFFIX = ".png"


@dataclass(frozen=True)
class _Grid:
    rows: int
    columns: int
    inset: Any  # a number or [horizontal, vertical]; validated by `grid_boxes`


@dataclass(frozen=True)
class _Plan:
    regions: dict[str, CropBox]
    grid: _Grid | None


class RoiService:
    """Cuts the game's configured regions of interest, and the reel grid into tiles, out of a screenshot.
    Each extraction is kept as a folder `<captures_dir>/roi/<id>` with the images and a `record.json`."""

    def __init__(
        self, *, obs: ObsService, game_context: GameContextService, captures_dir: Path
    ) -> None:
        self._obs = obs
        self._game_context = game_context
        self._records_dir = captures_dir / "roi"

    # ------------------------------------------------------------------ public

    async def extract(self, game: str | None = None, mode: GameMode | None = None) -> RoiRecord:
        """Takes a screenshot and cuts the game's regions out of it (game and mode default to the selected).
        The config is checked first, so a game that cannot be extracted never touches OBS."""
        game, mode, plan = self._plan(game, mode)
        screenshot = await self._obs.take_screenshot()
        path = self._obs.screenshot_path(screenshot.filename)
        return await asyncio.to_thread(self._cut, game, mode, plan, screenshot, path)

    def list_records(self, limit: int) -> list[RoiRecord]:
        """Newest first."""
        try:
            with os.scandir(self._records_dir) as entries:
                ids = sorted((e.name for e in entries if e.is_dir()), reverse=True)
        except FileNotFoundError:
            return []
        records: list[RoiRecord] = []
        for record_id in ids:
            record = self._read(record_id)
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
            raise NotFoundException("ROI image not found")
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
        if not isinstance(rois, dict):
            rois = {}
        regions: dict[str, CropBox] = {}
        for name in sorted(rois, key=_region_rank):
            if not rois[name]:  # e.g. "cyclic_message": [] for a game without that message
                continue
            try:
                if not _REGION_NAME.match(name):
                    raise InvalidCropError("the name may only contain letters, digits and _")
                regions[name] = CropBox.from_sequence(rois[name])
            except InvalidCropError as exc:
                raise _invalid_config(game, f"ROI '{name}' of mode '{mode.value}'", exc) from exc
        if not regions:
            raise NotFoundException(f"'{game}' has no ROI configured for mode '{mode.value}'")

        grid = None
        if _GRID_REGION in regions and config.get("reel_bounds") is not None:
            try:
                grid = _parse_grid(config["reel_bounds"])
            except InvalidCropError as exc:
                raise _invalid_config(game, "reel_bounds", exc) from exc
        return game, mode, _Plan(regions=regions, grid=grid)

    # ------------------------------------------------------------- extraction

    def _cut(
        self, game: str, mode: GameMode, plan: _Plan, screenshot: ScreenshotInfo, path: Path
    ) -> RoiRecord:
        created_at = datetime.now().astimezone()
        record_id = f"roi_{created_at:%Y%m%d_%H%M%S_%f}"[:-3] + f"_{uuid.uuid4().hex[:6]}"
        directory = self._records_dir / record_id
        directory.mkdir(parents=True)
        try:
            record = self._write(record_id, directory, created_at, game, mode, plan, screenshot, path)
        except InvalidCropError as exc:
            shutil.rmtree(directory, ignore_errors=True)
            raise AppException(
                f"Could not cut the regions out of {screenshot.filename}: {exc}",
                status_code=422,
                error_code="ROI_INVALID",
            ) from exc
        except OSError as exc:  # includes an image Pillow cannot read
            shutil.rmtree(directory, ignore_errors=True)
            raise AppException(
                f"Could not read {screenshot.filename} or save its regions: {exc}",
                error_code="ROI_FAILED",
            ) from exc
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        logger.info("Saved ROI record %s (%d crops, %d tiles)", record_id, len(record.crops), len(record.tiles))
        return record

    def _write(
        self,
        record_id: str,
        directory: Path,
        created_at: datetime,
        game: str,
        mode: GameMode,
        plan: _Plan,
        screenshot: ScreenshotInfo,
        path: Path,
    ) -> RoiRecord:
        def save(image: Image.Image, filename: str) -> dict[str, Any]:
            """Writes the image and returns the fields every `RoiImage` has."""
            image.save(directory / filename)
            url = f"/roi/records/{record_id}/images/{filename}"
            return {"url": url, "width": image.width, "height": image.height}

        crops: list[RoiCrop] = []
        tiles: list[RoiTile] = []
        rows = columns = 0
        with Image.open(path) as full:
            full.load()  # decoded once, then every region is cut from memory
            for name, box in plan.regions.items():
                crop = crop_fraction(full, box)
                image = save(crop, f"{name}{_IMAGE_SUFFIX}")
                crops.append(RoiCrop(name=name, roi=list(box.as_tuple()), **image))
                if name == _GRID_REGION and plan.grid is not None:
                    rows, columns = plan.grid.rows, plan.grid.columns
                    cells = split_grid(crop, rows, columns, plan.grid.inset)
                    for row, cells_in_row in enumerate(cells):
                        for column, tile in enumerate(cells_in_row):
                            image = save(tile, f"tile_r{row}_c{column}{_IMAGE_SUFFIX}")
                            tiles.append(RoiTile(row=row, column=column, **image))

        record = RoiRecord(
            id=record_id,
            created_at=created_at,
            game=game,
            mode=mode,
            screenshot=screenshot,
            crops=crops,
            rows=rows,
            columns=columns,
            tiles=tiles,
        )
        # Written last and atomically: a folder without a record is never listed.
        tmp_file = directory / f"{_RECORD_FILE}.tmp"
        tmp_file.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_file, directory / _RECORD_FILE)
        return record

    def _read(self, record_id: str) -> RoiRecord | None:
        try:
            text = (self._records_dir / record_id / _RECORD_FILE).read_text(encoding="utf-8")
            return RoiRecord.model_validate_json(text)
        except (OSError, ValueError):
            return None


# ------------------------------------------------------------------ helpers


def _region_rank(name: str) -> int:
    return _REGION_ORDER.index(name) if name in _REGION_ORDER else len(_REGION_ORDER)


def _parse_grid(reel_bounds: Any) -> _Grid:
    if not isinstance(reel_bounds, dict):
        raise InvalidCropError(f"expected rows, columns and inset, got {reel_bounds!r}")
    grid = _Grid(
        rows=reel_bounds.get("rows"),
        columns=reel_bounds.get("columns"),
        inset=reel_bounds.get("inset", 0.0),
    )
    grid_boxes(grid.rows, grid.columns, grid.inset)  # raises if any of it is unusable
    return grid


def _invalid_config(game: str, what: str, exc: InvalidCropError) -> AppException:
    return AppException(f"{what} in the config of '{game}' is invalid: {exc}", error_code="CONFIG_INVALID")
