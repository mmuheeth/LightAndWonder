from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app.api.dependencies import get_ocr_controller
from app.controllers.ocr_controller import OcrController
from app.schemas.game_context import GameMode
from app.schemas.ocr import OcrEngineStatus, OcrRecord
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/ocr", tags=["OCR"])


@router.post("/engine/warmup", response_model=ApiResponse[OcrEngineStatus])
def warm_up_ocr(
    request: Request, controller: OcrController = Depends(get_ocr_controller)
) -> ApiResponse[OcrEngineStatus]:
    """Starts loading the OCR models in the background and returns at once, so a later read does not wait for
    them. Safe to call as often as wanted."""
    return ApiResponse.ok(data=controller.warm_up(), path=str(request.url.path))


@router.post("/records", response_model=ApiResponse[OcrRecord])
async def extract_ocr_regions(
    request: Request,
    game: str | None = Query(None, description="Defaults to the selected game."),
    mode: GameMode | None = Query(None, description="Defaults to the selected mode."),
    controller: OcrController = Depends(get_ocr_controller),
) -> ApiResponse[OcrRecord]:
    """Takes OBS screenshots and cuts the credit meter, cash meter and cyclic messages out of them. The meter is
    toggled through GAF to capture both (and toggled back); without GAF only the meter being shown is captured."""
    data = await controller.extract(game, mode)
    return ApiResponse.ok(data=data, path=str(request.url.path))


@router.post("/records/{record_id}/read", response_model=ApiResponse[OcrRecord])
async def read_ocr_record(
    request: Request, record_id: str, controller: OcrController = Depends(get_ocr_controller)
) -> ApiResponse[OcrRecord]:
    """Runs PaddleOCR on the images of a record and returns the record with its readings. The first read after
    the backend starts loads the OCR models, which takes a while."""
    return ApiResponse.ok(data=await controller.read(record_id), path=str(request.url.path))


@router.get("/records", response_model=ApiResponse[list[OcrRecord]])
def list_ocr_records(
    request: Request,
    limit: int = Query(1, ge=1, le=50),
    controller: OcrController = Depends(get_ocr_controller),
) -> ApiResponse[list[OcrRecord]]:
    return ApiResponse.ok(data=controller.list_records(limit), path=str(request.url.path))


@router.get("/records/{record_id}/images/{filename}")
def get_ocr_image(
    record_id: str, filename: str, controller: OcrController = Depends(get_ocr_controller)
) -> FileResponse:
    return FileResponse(controller.image_path(record_id, filename), media_type="image/png")
