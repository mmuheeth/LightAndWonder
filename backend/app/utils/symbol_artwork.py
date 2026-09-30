"""A game's symbol artwork on disk: `app/games/<game>/symbols/<code>/*.png`, one folder per symbol code.
Kept apart from the classifier so that looking at the artwork never has to import torch."""

import os
from pathlib import Path

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp"})

# A symbol with at least this many images gives a fifth of them (the last ones) to the check after
# training; one with fewer is trained on whole, and is not part of the accuracy figures.
MIN_IMAGES_TO_HOLD_OUT = 5
HOLD_OUT_FRACTION = 0.2


def list_artwork(symbols_dir: Path) -> dict[str, list[Path]]:
    """The images by symbol code: each sub-folder that holds images, its images sorted by name."""
    artwork: dict[str, list[Path]] = {}
    try:
        with os.scandir(symbols_dir) as entries:
            folders = sorted(entry.path for entry in entries if entry.is_dir())
    except OSError:  # no such folder, or not a folder
        return artwork
    for folder in folders:
        with os.scandir(folder) as entries:
            images = sorted(
                Path(entry.path)
                for entry in entries
                if entry.is_file() and os.path.splitext(entry.name)[1].lower() in IMAGE_SUFFIXES
            )
        if images:
            artwork[os.path.basename(folder)] = images
    return artwork


def split_artwork(
    artwork: dict[str, list[Path]],
) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    """`(train, held_out)` by code. The held-out images are the last of each symbol, as one block:
    frames of one animation are near copies of their neighbours, so a scattered pick would test the
    model on images it has effectively seen."""
    train: dict[str, list[Path]] = {}
    held_out: dict[str, list[Path]] = {}
    for code, images in artwork.items():
        count = round(len(images) * HOLD_OUT_FRACTION) if len(images) >= MIN_IMAGES_TO_HOLD_OUT else 0
        train[code] = images[: len(images) - count]
        if count:
            held_out[code] = images[len(images) - count :]
    return train, held_out
