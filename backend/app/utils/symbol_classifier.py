"""A ResNet34 image classifier for a game's symbol artwork.

The artwork is one folder per symbol code, `<symbols_dir>/<code>/*.png`. Training fits an
ImageNet-pretrained ResNet34 to it; the classifier then names the code shown in a tile cut out of a
screenshot. Much of the artwork is transparent while a tile has the reel background behind the symbol,
so every training image is put on a random backdrop, zoomed and colour-shifted the way captures vary."""

import colorsys
import logging
import math
import os
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn.functional as F
from PIL import Image, ImageEnhance, ImageFilter
from torchvision.models import ResNet34_Weights, resnet34
from torchvision.transforms.functional import pil_to_tensor

from app.utils.symbol_artwork import split_artwork

logger = logging.getLogger(__name__)

ARCHITECTURE = "ResNet34"

# Side of the square the network sees. Symbols are large, simple shapes, so this is plenty and keeps
# ResNet34 at a few minutes on a CPU.
INPUT_SIZE = 128
# Images are kept at this size while training and drawn from it with a zoom and a shift, so the
# drawing never has to shrink them by more than a little.
STORED_SIZE = 192
# The pretrained network has all but converged after four or five of these short epochs.
EPOCHS = 5
BATCH_SIZE = 32
# Every symbol is drawn this often per epoch, however many images it has: one with two images is seen
# as often as one with fifty.
SAMPLES_PER_CLASS = 16
LEARNING_RATE = 5e-4
WEIGHT_DECAY = 1e-4
SEED = 0

_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
_STD = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
_EVAL_BATCH = 64


class SymbolTrainingError(Exception):
    """Training cannot proceed, or a saved model cannot be used. The message is meant for the user."""


@dataclass(frozen=True)
class Prediction:
    code: str
    # Percent (0-100) the classifier puts on `code`; the other codes share the rest.
    confidence: float


@dataclass(frozen=True)
class TrainingReport:
    classes: list[str]
    image_count: int
    epochs: int
    # Percent of the held-out images named correctly, and the same for the worst symbol ("floor").
    # None when no symbol had enough images to hold any out.
    accuracy: float | None
    floor: float | None
    # Percent by code, for the symbols that had held-out images.
    per_class: dict[str, float]


ProgressCallback = Callable[[int, int, float], None]  # epoch, epochs, mean loss of that epoch


# ---------------------------------------------------------------------------- images


def prepare(image: Image.Image) -> Image.Image:
    """An image as the network sees every source, artwork or tile: RGBA, stretched to a square.
    Tiles are stretched alike whatever their shape, so the two meet at the same proportions."""
    return image.convert("RGBA").resize((STORED_SIZE, STORED_SIZE), Image.Resampling.LANCZOS)


def _random_color(rng: random.Random) -> tuple[int, int, int]:
    red, green, blue = colorsys.hsv_to_rgb(rng.random(), rng.uniform(0.0, 0.9), rng.uniform(0.05, 0.85))
    return round(red * 255), round(green * 255), round(blue * 255)


def _backdrop(rng: random.Random) -> Image.Image:
    """What the transparent parts of the artwork are seen against: a flat colour or a two-colour ramp."""
    size = INPUT_SIZE
    first = Image.new("RGB", (size, size), _random_color(rng))
    if rng.random() < 0.6:
        return first
    second = Image.new("RGB", (size, size), _random_color(rng))
    ramp = Image.linear_gradient("L").resize((size, size))
    if rng.random() < 0.5:
        ramp = ramp.transpose(Image.Transpose.ROTATE_90)
    return Image.composite(second, first, ramp)


def _render(prepared: Image.Image, rng: random.Random, *, vary: bool) -> Image.Image:
    """The `INPUT_SIZE` square RGB the network gets. With `vary` the symbol is zoomed, moved, stretched
    and recoloured a little; without it only the backdrop is chosen, so a check is repeatable."""
    size = INPUT_SIZE
    if vary:
        zoom = rng.uniform(0.55, 1.15)
        stretch = rng.uniform(0.87, 1.15)
        scale_x, scale_y = zoom * stretch, zoom / stretch
        shift_x, shift_y = rng.uniform(-0.08, 0.08) * size, rng.uniform(-0.08, 0.08) * size
    else:
        scale_x = scale_y = 1.0
        shift_x = shift_y = 0.0
    # Output pixel (u, v) samples the stored image at (a*u + c, e*v + f): scaled about the centre.
    to_stored = size / prepared.width
    a, e = 1.0 / (scale_x * to_stored), 1.0 / (scale_y * to_stored)
    c = prepared.width / 2 - (size / 2 + shift_x) * a
    f = prepared.height / 2 - (size / 2 + shift_y) * e
    # Premultiplied, so the colour of a transparent edge does not bleed into the symbol.
    moved = (
        prepared.convert("RGBa")
        .transform((size, size), Image.Transform.AFFINE, (a, 0, c, 0, e, f), Image.Resampling.BILINEAR)
        .convert("RGBA")
    )
    image = Image.alpha_composite(_backdrop(rng).convert("RGBA"), moved).convert("RGB")
    if vary:
        for enhancer in (ImageEnhance.Brightness, ImageEnhance.Contrast, ImageEnhance.Color):
            image = enhancer(image).enhance(rng.uniform(0.75, 1.25))
        if rng.random() < 0.4:
            image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.2)))
    return image


def _tensor(image: Image.Image) -> torch.Tensor:
    return (pil_to_tensor(image).float() / 255 - _MEAN) / _STD


def _load_prepared(path: Path) -> Image.Image:
    try:
        with Image.open(path) as image:
            return prepare(image)
    except (OSError, ValueError) as exc:  # Pillow's "cannot identify image" is an OSError
        raise SymbolTrainingError(f"Cannot read the artwork {path}: {exc}") from exc


# ---------------------------------------------------------------------------- model


def _build(class_count: int, *, pretrained: bool) -> torch.nn.Module:
    try:
        model = resnet34(weights=ResNet34_Weights.IMAGENET1K_V1 if pretrained else None)
    except Exception as exc:  # no cached weights and no network: URLError, OSError, RuntimeError, ...
        raise SymbolTrainingError(
            f"Could not load the pretrained {ARCHITECTURE} weights (they are downloaded once "
            f"and cached): {exc}"
        ) from exc
    model.fc = torch.nn.Linear(model.fc.in_features, class_count)
    return model


def default_threads() -> int:
    """Half the cores, so the rest of the machine stays responsive while training."""
    return max(1, (os.cpu_count() or 2) // 2)


def train(
    artwork: dict[str, list[Path]],
    weights_path: Path,
    *,
    epochs: int = EPOCHS,
    threads: int | None = None,
    pretrained: bool = True,
    on_progress: ProgressCallback | None = None,
) -> TrainingReport:
    """Fits the network to `artwork` (image paths by symbol code) and saves it to `weights_path` (replaced only once complete).
    Blocks for minutes: run it off the request thread."""
    classes = sorted(artwork)
    if len(classes) < 2:
        raise SymbolTrainingError(
            f"Need artwork for at least two symbols to tell them apart, found {len(classes)}."
        )
    train_files, held_out_files = split_artwork(artwork)
    train_images = {code: [_load_prepared(path) for path in train_files[code]] for code in classes}
    held_out = [
        (classes.index(code), _load_prepared(path))
        for code, paths in held_out_files.items()
        for path in paths
    ]

    torch.set_num_threads(threads or default_threads())
    torch.manual_seed(SEED)
    rng = random.Random(SEED)
    noise = torch.Generator().manual_seed(SEED)
    model = _build(len(classes), pretrained=pretrained)

    steps = math.ceil(len(classes) * SAMPLES_PER_CLASS / BATCH_SIZE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    schedule = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=LEARNING_RATE, total_steps=epochs * steps, pct_start=0.15
    )
    for epoch in range(1, epochs + 1):
        model.train()
        # Whole batches, every symbol equally often (to within one).
        labels = [i % len(classes) for i in range(steps * BATCH_SIZE)]
        rng.shuffle(labels)
        total_loss = 0.0
        for step in range(steps):
            batch = labels[step * BATCH_SIZE : (step + 1) * BATCH_SIZE]
            inputs = torch.stack(
                [_tensor(_render(rng.choice(train_images[classes[label]]), rng, vary=True)) for label in batch]
            )
            inputs += torch.randn(inputs.shape, generator=noise) * rng.uniform(0.0, 0.1)
            loss = F.cross_entropy(model(inputs), torch.tensor(batch))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            schedule.step()
            total_loss += loss.item()
        mean_loss = total_loss / steps
        logger.info("Symbol training epoch %d/%d, loss %.4f", epoch, epochs, mean_loss)
        if on_progress is not None:
            on_progress(epoch, epochs, mean_loss)

    accuracy, floor, per_class = _evaluate(model, classes, held_out, rng)
    _save(model, classes, weights_path)
    return TrainingReport(
        classes=classes,
        image_count=sum(len(images) for images in artwork.values()),
        epochs=epochs,
        accuracy=accuracy,
        floor=floor,
        per_class=per_class,
    )


def _evaluate(
    model: torch.nn.Module,
    classes: list[str],
    held_out: list[tuple[int, Image.Image]],
    rng: random.Random,
) -> tuple[float | None, float | None, dict[str, float]]:
    if not held_out:
        return None, None, {}
    model.eval()
    right = [0] * len(classes)
    total = [0] * len(classes)
    with torch.inference_mode():
        for start in range(0, len(held_out), _EVAL_BATCH):
            chunk = held_out[start : start + _EVAL_BATCH]
            inputs = torch.stack([_tensor(_render(image, rng, vary=False)) for _, image in chunk])
            guessed = model(inputs).argmax(dim=1).tolist()
            for (label, _), guess in zip(chunk, guessed):
                total[label] += 1
                right[label] += guess == label
    per_class = {classes[i]: 100.0 * right[i] / total[i] for i in range(len(classes)) if total[i]}
    accuracy = 100.0 * sum(right) / sum(total)
    return accuracy, min(per_class.values()), per_class


def _save(model: torch.nn.Module, classes: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = path.with_suffix(".tmp")
    torch.save({"classes": classes, "state_dict": model.state_dict()}, tmp_file)
    os.replace(tmp_file, path)  # atomic: a model being read is never half written


# ---------------------------------------------------------------------------- inference


class SymbolClassifier:
    """A trained network that names the symbol shown in an image."""

    def __init__(self, classes: Sequence[str], model: torch.nn.Module) -> None:
        self.classes = list(classes)
        self._model = model.eval()

    @classmethod
    def load(cls, weights_path: Path) -> "SymbolClassifier":
        try:
            saved = torch.load(weights_path, map_location="cpu", weights_only=True)
            classes = saved["classes"]
            model = _build(len(classes), pretrained=False)
            model.load_state_dict(saved["state_dict"])
        except SymbolTrainingError:
            raise
        except Exception as exc:  # unreadable, truncated or not ours
            raise SymbolTrainingError(f"Cannot load the trained model {weights_path}: {exc}") from exc
        return cls(classes, model)

    def classify(self, images: Sequence[Image.Image]) -> list[Prediction]:
        """One prediction per image, in order."""
        if not images:
            return []
        rng = random.Random(SEED)
        inputs = torch.stack([_tensor(_render(prepare(image), rng, vary=False)) for image in images])
        with torch.inference_mode():
            confidence, index = torch.softmax(self._model(inputs), dim=1).max(dim=1)
        return [
            Prediction(code=self.classes[i], confidence=100.0 * c)
            for c, i in zip(confidence.tolist(), index.tolist())
        ]
