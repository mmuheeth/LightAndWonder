"""A lane's process for tests: the real protocol (`serve`) and the real box/line reading, with stub models.
What a stub model does depends on the colour of the image it is given (the engine scales and pads what it
is sent, which keeps a solid colour), so a test picks a behaviour by choosing the image:
    FAILS  -> fails like a Paddle kernel that does not exist
    DIES   -> the process dies
    HANGS  -> hangs
A box or a line says how big the image it was shown was ("HxW"), and the box recognizer's confidence is
OCR_STUB_MOBILE_SCORE (default 0.95), so a test can tell the scaling and the second opinion.
The environment (inherited by the process when it starts) sets OCR_STUB_SECONDS, how long a read takes, and
OCR_STUB_FAIL=load, which fails the loading of the models."""

import os
import time

import numpy as np

from app.utils.ocr_engine import OcrEngineError, _Models, serve

# RGB fill colours of the image a test sends.
FAILS, DIES, HANGS = (1, 2, 3), (4, 5, 6), (7, 8, 9)


class _Predictor:
    def __init__(self, kind: str) -> None:
        self._kind = kind

    def predict(self, pixels: np.ndarray) -> list[dict]:
        started = time.time()
        time.sleep(float(os.environ.get("OCR_STUB_SECONDS", "0")))
        height, width = pixels.shape[:2]
        colour = tuple(int(v) for v in pixels[0, 0][::-1])  # the engine hands over blue, green, red
        if colour == FAILS:
            raise NotImplementedError("a kernel that does not exist")
        if colour == DIES:
            os._exit(1)
        if colour == HANGS:
            time.sleep(60)
        if self._kind == "detector":  # one piece of text, nearly the whole image
            return [{"dt_polys": [np.array([[2, 2], [width - 2, 2], [width - 2, height - 2], [2, height - 2]])]}]
        size = f"{height}x{width}"
        if self._kind == "box":
            return [{"rec_text": f" {size} ", "rec_score": float(os.environ.get("OCR_STUB_MOBILE_SCORE", "0.95"))}]
        # A line says which process read it and when, so a test can see reads overlap.
        return [{"rec_text": f" {os.getpid()}:{started}:{time.time()}:{size} ", "rec_score": 0.9}]


def _load() -> _Models:
    if os.environ.get("OCR_STUB_FAIL") == "load":
        raise OcrEngineError("Could not load the OCR models: no network")
    return _Models(
        detector=_Predictor("detector"), box_recognizer=_Predictor("box"), line_recognizer=_Predictor("line")
    )


def stub_lane(connection) -> None:
    serve(connection, _load)
