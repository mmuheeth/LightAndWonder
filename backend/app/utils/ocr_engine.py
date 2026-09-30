"""Reading text out of images with PaddleOCR, in worker processes.

Only the text detection and recognition models are used, driven directly, so the pipeline's document orientation
classifier, unwarping and visualization (use_doc_orientation_classify, use_doc_unwarping, visualize) are never
part of it: the crops are already upright and flat.

The engine is behind a small protocol, so what is built on it is tested with a fake: loading the real models
takes a minute."""

import logging
import multiprocessing
import os
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any, Protocol

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# The mobile recognizer reads a meter's big boxes as well as the medium one in a third of the time; only the
# medium one reads the tiny cyclic message lines.
DETECTION_MODEL = "PP-OCRv6_medium_det"
BOX_RECOGNITION_MODEL = "en_PP-OCRv5_mobile_rec"
LINE_RECOGNITION_MODEL = "PP-OCRv6_medium_rec"
# Pixels added around a detected box before it is recognized.
_CROP_PADDING = 2
# Threads a lane's predictions may use: these images are small, and 1, 2, 4 and 8 measured the same.
_CPU_THREADS = 2

# A meter crop under _NATIVE_MIN_HEIGHT px (a 766 px wide capture gives 44) is scaled up to about
# _METER_TARGET_HEIGHT before it is read: at its own size the ~9 px labels are never detected. Taller crops
# (1080 px wide captures give 74) read fine as they are, and scaling them only costs time.
_NATIVE_MIN_HEIGHT = 70
_METER_TARGET_HEIGHT = 130
_MAX_SCALE = 4
# A box the mobile recognizer is under _DOUBT sure of, and short enough to be a label, is read again by the
# medium one (~1 s a box) and the surer read kept: it turns "IET" into "BET".
_DOUBT = 0.9
_SECOND_OPINION_MAX_CHARS = 8
# A message line is padded and scaled up before it is read (unscaled, "Credits" came out as "Cred its").
_LINE_SCALE = 3
_LINE_PADDING = 4

# Seconds a lane may take to load its models, and to read one image; a lane that takes longer is replaced.
_START_TIMEOUT = 300.0
_READ_TIMEOUT = 120.0


class OcrEngineError(RuntimeError):
    """The engine is not installed, could not load its models, or failed to read an image."""


@dataclass(frozen=True)
class TextBox:
    """A piece of text and where it is in the image, in pixels from the top left."""

    text: str
    score: float  # 0..1: how sure the recognizer is
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True)
class TextLine:
    text: str
    score: float


class OcrEngine(Protocol):
    lanes: int  # how many images it can read at the same time

    @property
    def ready(self) -> bool:
        """Whether a read would start at once, without loading the models first."""

    def preload(self) -> None:
        """Starts loading the models in the background."""

    def read_boxes(self, image: Image.Image) -> list[TextBox]:
        """Every piece of text in an image that holds several, with its place."""

    def read_line(self, image: Image.Image) -> TextLine:
        """The one line of text an image is a crop of; empty text (score 0) when there is none."""


# ------------------------------------------------------------- inside a lane's process


@dataclass(frozen=True)
class _Models:
    detector: Any
    box_recognizer: Any
    line_recognizer: Any


def _load_models() -> _Models:
    # Without this PaddleX first checks the model hosts, which only delays (or, offline, fails) loading models
    # that are cached under ~/.paddlex.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    try:
        from paddleocr import TextDetection, TextRecognition
    except ImportError as exc:
        raise OcrEngineError(f"PaddleOCR is not installed ({exc}). Run: pip install -r requirements.txt") from exc
    try:
        # oneDNN is only for the mobile recognizer: with it the detector fails every read ("ConvertPirAttribute2
        # RuntimeAttribute not support pir::ArrayAttribute", paddlepaddle 3.3 on Windows) and the medium
        # recognizer gets slower. The mobile one reads 11 boxes in 1-2.5 s with it against 3.7 s.
        return _Models(
            detector=TextDetection(model_name=DETECTION_MODEL, enable_mkldnn=False, cpu_threads=_CPU_THREADS),
            box_recognizer=TextRecognition(model_name=BOX_RECOGNITION_MODEL, enable_mkldnn=True, cpu_threads=_CPU_THREADS),
            line_recognizer=TextRecognition(model_name=LINE_RECOGNITION_MODEL, enable_mkldnn=False, cpu_threads=_CPU_THREADS),
        )
    except Exception as exc:  # PaddleX raises plain Exceptions, e.g. for a model that cannot be downloaded
        raise OcrEngineError(f"Could not load the OCR models: {exc}") from exc


def serve(connection: Connection, load: Callable[[], _Models]) -> None:
    """A lane's process: loads the models, says so, then reads what it is sent until the connection closes.
    Replies are ("ready", None) once, then ("ok", result) or ("error", message) per request."""
    try:
        try:
            models = load()
        except OcrEngineError as exc:
            connection.send(("error", str(exc)))
            return
        connection.send(("ready", None))
        while (request := connection.recv()) is not None:
            kind, pixels = request
            try:
                connection.send(("ok", _read(models, kind, pixels)))
            except Exception as exc:  # Paddle raises whatever its kernels raise
                connection.send(("error", f"PaddleOCR failed to read the image: {exc}"))
    except (EOFError, OSError):
        return  # the server went away, taking its end of the pipe with it


def paddle_lane(connection: Connection) -> None:
    serve(connection, _load_models)


def _read(models: _Models, kind: str, pixels: np.ndarray) -> Any:
    import cv2  # only a lane needs it

    if kind == "line":
        pad = _LINE_PADDING
        padded = cv2.copyMakeBorder(pixels, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
        scaled = cv2.resize(padded, None, fx=_LINE_SCALE, fy=_LINE_SCALE, interpolation=cv2.INTER_CUBIC)
        result = models.line_recognizer.predict(np.ascontiguousarray(scaled))[0]
        return str(result["rec_text"]).strip(), float(result["rec_score"])

    height = pixels.shape[0]
    scale = 1 if height >= _NATIVE_MIN_HEIGHT else min(_MAX_SCALE, -(-_METER_TARGET_HEIGHT // height))
    work = pixels if scale == 1 else cv2.resize(pixels, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    rows = []
    for polygon in models.detector.predict(work)[0]["dt_polys"]:
        left, top, right, bottom = _bounds(polygon, work.shape)
        text, score = _read_box(models, work[top:bottom, left:right])
        if text:  # placed in the pixels of the image that was given, not of the scaled one
            rows.append((text, score, left / scale, top / scale, right / scale, bottom / scale))
    return rows


def _read_box(models: _Models, crop: np.ndarray) -> tuple[str, float]:
    result = models.box_recognizer.predict(crop)[0]
    text, score = str(result["rec_text"]).strip(), float(result["rec_score"])
    if score < _DOUBT and len(text) <= _SECOND_OPINION_MAX_CHARS:
        second = models.line_recognizer.predict(crop)[0]
        if float(second["rec_score"]) > score:
            text, score = str(second["rec_text"]).strip(), float(second["rec_score"])
    return text, score


def _bounds(polygon: Any, shape: tuple[int, ...]) -> tuple[int, int, int, int]:
    """The padded pixel rectangle around a detected polygon, within the image: (left, top, right, bottom)."""
    height, width = shape[:2]
    xs, ys = polygon[:, 0], polygon[:, 1]
    left = max(int(xs.min()) - _CROP_PADDING, 0)
    top = max(int(ys.min()) - _CROP_PADDING, 0)
    right = min(int(np.ceil(xs.max())) + _CROP_PADDING, width)
    bottom = min(int(np.ceil(ys.max())) + _CROP_PADDING, height)
    return left, top, max(right, left + 1), max(bottom, top + 1)


# ------------------------------------------------------------------------- the server's side


class _Lane:
    """A lane's process, as the server sees it. It starts loading at once; a request waits until it has."""

    def __init__(self, target: Callable[[Connection], None]) -> None:
        context = multiprocessing.get_context("spawn")
        self._connection, child_end = context.Pipe()
        self._process = context.Process(target=target, args=(child_end,), name="ocr-lane", daemon=True)
        self._process.start()
        child_end.close()
        self.broken = False
        self._failure: str | None = None
        self._settled = threading.Event()
        threading.Thread(target=self._await_ready, name="ocr-lane-start", daemon=True).start()

    @property
    def ready(self) -> bool:
        return self._settled.is_set() and self._failure is None

    def request(self, kind: str, pixels: np.ndarray) -> Any:
        self._settled.wait()
        if self._failure:
            self.broken = True
            raise OcrEngineError(self._failure)
        try:
            self._connection.send((kind, pixels))
            if not self._connection.poll(_READ_TIMEOUT):
                self.broken = True
                raise OcrEngineError(f"PaddleOCR did not answer within {_READ_TIMEOUT:g}s")
            status, payload = self._connection.recv()
        except (EOFError, OSError) as exc:
            self.broken = True
            raise OcrEngineError("The OCR process stopped unexpectedly") from exc
        if status != "ok":
            raise OcrEngineError(payload)  # the lane itself is fine
        return payload

    def close(self) -> None:
        try:
            self._connection.send(None)
        except OSError:
            pass
        self._process.join(2)
        self.kill()

    def kill(self) -> None:
        if self._process.is_alive():
            self._process.terminate()
        self._connection.close()

    def _await_ready(self) -> None:
        try:
            if not self._connection.poll(_START_TIMEOUT):
                self._failure = "The OCR models did not load in time"
            else:
                status, payload = self._connection.recv()
                self._failure = None if status == "ready" else str(payload)
        except Exception:  # the process died, or sent something unreadable
            self._failure = "The OCR process stopped while loading the models"
        self._settled.set()


class PaddleOcrEngine:
    """PP-OCR through PaddleOCR. Each lane is a worker process holding a full set of the models and reading one
    image at a time; a read takes whichever lane is free.

    Processes, not threads: predictions in threads of one process ran one at a time (two reads took twice as
    long as one), while two processes ran in parallel. A lane that dies or hangs is replaced by the next read,
    and lanes end with the server: the pipe to it closes."""

    def __init__(self, *, lanes: int = 2, target: Callable[[Connection], None] = paddle_lane) -> None:
        self.lanes = max(1, lanes)
        self._target = target
        self._free: queue.Queue[_Lane] = queue.Queue()
        self._all: set[_Lane] = set()
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        with self._lock:
            return any(lane.ready for lane in self._all)

    def preload(self) -> None:
        try:
            self._ensure_lanes()
        except OcrEngineError as exc:  # a read reports it again
            logger.warning("Could not start the OCR lanes: %s", exc)

    def read_boxes(self, image: Image.Image) -> list[TextBox]:
        rows = self._request("boxes", _to_bgr(image))
        return [TextBox(text, score, left, top, right, bottom) for text, score, left, top, right, bottom in rows]

    def read_line(self, image: Image.Image) -> TextLine:
        text, score = self._request("line", _to_bgr(image))
        return TextLine(text=text, score=score)

    def close(self) -> None:
        with self._lock:
            lanes, self._all = list(self._all), set()
        for lane in lanes:
            lane.close()
        self._free = queue.Queue()

    def _request(self, kind: str, pixels: np.ndarray) -> Any:
        self._ensure_lanes()
        try:
            lane = self._free.get(timeout=_START_TIMEOUT + _READ_TIMEOUT)
        except queue.Empty:
            raise OcrEngineError("No OCR process is available") from None
        try:
            return lane.request(kind, pixels)
        finally:
            self._give_back(lane)

    def _give_back(self, lane: _Lane) -> None:
        if not lane.broken:
            self._free.put(lane)
            return
        # Replaced by the next read, not now: a replacement started now would meet whatever broke this one.
        with self._lock:
            self._all.discard(lane)
        lane.kill()

    def _ensure_lanes(self) -> None:
        """Starts the lanes that are missing: all of them on first use, and any that broke since."""
        with self._lock:
            while len(self._all) < self.lanes:
                try:
                    lane = _Lane(self._target)
                except (OSError, RuntimeError) as exc:
                    raise OcrEngineError(f"Could not start an OCR process: {exc}") from exc
                self._all.add(lane)
                self._free.put(lane)


def _to_bgr(image: Image.Image) -> np.ndarray:
    """PaddleOCR takes OpenCV-style arrays: blue, green, red."""
    return np.ascontiguousarray(np.asarray(image.convert("RGB"))[:, :, ::-1])
