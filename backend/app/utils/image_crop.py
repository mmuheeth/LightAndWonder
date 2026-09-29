"""Cropping by fractions of an image (0.0 is the left/top edge, 1.0 the right/bottom edge),
so one definition fits any resolution or aspect ratio."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real

from PIL import Image

# Trimmed from both sides of a cell, so 0.5 would leave nothing of it.
_MAX_INSET = 0.5


class InvalidCropError(ValueError):
    """A crop that cannot be applied: malformed, out of range or empty."""


@dataclass(frozen=True)
class CropBox:
    """A rectangle as fractions of an image: `left`/`right` of its width, `top`/`bottom` of its height."""

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        for label, value in zip(("left", "top", "right", "bottom"), self.as_tuple()):
            # bool is an int, but a config that says `true` here is a mistake, not a fraction.
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise InvalidCropError(f"{label} must be a finite number, got {value!r}")
            if not 0.0 <= value <= 1.0:
                raise InvalidCropError(f"{label} must be between 0 and 1, got {value}")
        if self.left >= self.right:
            raise InvalidCropError(f"left ({self.left}) must be less than right ({self.right})")
        if self.top >= self.bottom:
            raise InvalidCropError(f"top ({self.top}) must be less than bottom ({self.bottom})")

    @classmethod
    def from_sequence(cls, values: Sequence[float]) -> "CropBox":
        """Builds a box from `[left, top, right, bottom]`, the form ROIs are configured in."""
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or len(values) != 4:
            raise InvalidCropError(f"expected [left, top, right, bottom], got {values!r}")
        return cls(*values)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self.left, self.top, self.right, self.bottom

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """The `(left, top, right, bottom)` pixel box in an image of this size.
        Edges are rounded so neighbouring boxes neither gap nor overlap; it is at least 1x1 pixel."""
        if width < 1 or height < 1:
            raise InvalidCropError(f"cannot crop an image of {width}x{height} pixels")
        left = min(round(self.left * width), width - 1)
        top = min(round(self.top * height), height - 1)
        right = min(max(round(self.right * width), left + 1), width)
        bottom = min(max(round(self.bottom * height), top + 1), height)
        return left, top, right, bottom


def crop_fraction(image: Image.Image, box: "CropBox | Sequence[float]") -> Image.Image:
    """The part of `image` inside `box`, as a new image; `image` itself is left untouched.
    `box` is a `CropBox` or `[left, top, right, bottom]` fractions of the image."""
    if not isinstance(box, CropBox):
        box = CropBox.from_sequence(box)
    return image.crop(box.to_pixels(*image.size))


def grid_boxes(
    rows: int, columns: int, inset: "float | Sequence[float]" = 0.0
) -> list[list[CropBox]]:
    """The cells of a `rows` x `columns` grid as boxes, indexed `[row][column]` from the top left.
    `inset` trims each cell on every side, as a fraction of the cell: a number or `[horizontal, vertical]`."""
    for label, count in (("rows", rows), ("columns", columns)):
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise InvalidCropError(f"{label} must be a positive whole number, got {count!r}")
    inset_x, inset_y = _inset_pair(inset)
    return [
        [
            CropBox(
                left=(column + inset_x) / columns,
                top=(row + inset_y) / rows,
                right=(column + 1 - inset_x) / columns,
                bottom=(row + 1 - inset_y) / rows,
            )
            for column in range(columns)
        ]
        for row in range(rows)
    ]


def split_grid(
    image: Image.Image, rows: int, columns: int, inset: "float | Sequence[float]" = 0.0
) -> list[list[Image.Image]]:
    """Cuts `image` into the cells of a `rows` x `columns` grid, indexed `[row][column]`."""
    boxes = grid_boxes(rows, columns, inset)
    width, height = image.size
    if width < columns or height < rows:
        raise InvalidCropError(
            f"a {width}x{height} image cannot be split into {columns} columns and {rows} rows"
        )
    return [[crop_fraction(image, box) for box in row] for row in boxes]


def _inset_pair(inset: "float | Sequence[float]") -> tuple[float, float]:
    if isinstance(inset, Sequence) and not isinstance(inset, (str, bytes)):
        if len(inset) != 2:
            raise InvalidCropError(f"inset must be one number or [horizontal, vertical], got {inset!r}")
        pair = tuple(inset)
    else:
        pair = (inset, inset)
    for value in pair:
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
            raise InvalidCropError(f"inset must be made of finite numbers, got {inset!r}")
        if not 0.0 <= value < _MAX_INSET:
            raise InvalidCropError(f"inset must be at least 0 and less than {_MAX_INSET}, got {value}")
    return pair
