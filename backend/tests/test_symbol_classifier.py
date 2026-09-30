import random
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.utils import symbol_classifier as classifier
from app.utils.symbol_artwork import list_artwork, split_artwork


def touch_images(folder: Path, names: list[str]) -> None:
    folder.mkdir(parents=True)
    for name in names:
        if name.lower().endswith(".txt"):
            (folder / name).write_text("not artwork")
        else:
            Image.new("RGBA", (8, 8)).save(folder / name)


def symbol(shape: str, rng: random.Random, size: int = 60) -> Image.Image:
    """A transparent drawing of a coloured shape, a little different each time."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    jitter = rng.randint(-4, 4)
    box = (14 + jitter, 14 + jitter, 46 + jitter, 46 + jitter)
    if shape == "circle":
        draw.ellipse(box, fill=(220, 30, 30, 255))
    elif shape == "square":
        draw.rectangle(box, fill=(30, 200, 40, 255))
    else:
        draw.polygon([(box[0], box[3]), (box[2], box[3]), ((box[0] + box[2]) // 2, box[1])], fill=(40, 60, 230, 255))
    return image


@pytest.fixture
def artwork_dir(tmp_path: Path) -> Path:
    rng = random.Random(3)
    for shape in ("circle", "square", "triangle"):
        folder = tmp_path / shape
        folder.mkdir()
        for index in range(8):
            symbol(shape, rng).save(folder / f"{shape}_{index:03d}.png")
    return tmp_path


@pytest.fixture
def small_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Small images and few draws: the real network, but seconds instead of minutes."""
    monkeypatch.setattr(classifier, "INPUT_SIZE", 48)
    monkeypatch.setattr(classifier, "STORED_SIZE", 64)
    monkeypatch.setattr(classifier, "SAMPLES_PER_CLASS", 32)


# ------------------------------------------------------------------------- artwork


def test_artwork_is_listed_by_folder_with_its_images_sorted(tmp_path: Path) -> None:
    touch_images(tmp_path / "BB", ["BB_002.png", "BB_001.PNG", "notes.txt"])
    touch_images(tmp_path / "AA", ["AA_000.png"])
    touch_images(tmp_path / "empty", [])
    (tmp_path / "stray.png").write_bytes(b"")

    artwork = list_artwork(tmp_path)

    assert list(artwork) == ["AA", "BB"]
    assert [p.name for p in artwork["BB"]] == ["BB_001.PNG", "BB_002.png"]


def test_missing_artwork_folder_is_no_artwork(tmp_path: Path) -> None:
    assert list_artwork(tmp_path / "nothing") == {}


def test_the_last_fifth_of_a_symbol_is_held_out_as_one_block(tmp_path: Path) -> None:
    touch_images(tmp_path / "AA", [f"AA_{i:03d}.png" for i in range(10)])

    train, held_out = split_artwork(list_artwork(tmp_path))

    assert [p.name for p in held_out["AA"]] == ["AA_008.png", "AA_009.png"]
    assert [p.name for p in train["AA"]] == [f"AA_{i:03d}.png" for i in range(8)]


def test_a_symbol_with_few_images_is_trained_on_whole(tmp_path: Path) -> None:
    touch_images(tmp_path / "AA", [f"AA_{i}.png" for i in range(4)])

    train, held_out = split_artwork(list_artwork(tmp_path))

    assert len(train["AA"]) == 4
    assert held_out == {}


# ----------------------------------------------------------------------- the network


def test_training_fits_the_artwork_and_the_classifier_names_new_drawings(
    artwork_dir: Path, tmp_path: Path, small_network
) -> None:
    weights = tmp_path / "models" / "model.pt"
    progress: list[tuple[int, int]] = []

    report = classifier.train(
        list_artwork(artwork_dir),
        weights,
        epochs=5,
        threads=2,
        pretrained=False,
        on_progress=lambda epoch, epochs, loss: progress.append((epoch, epochs)),
    )

    assert report.classes == ["circle", "square", "triangle"]
    assert report.image_count == 24
    assert progress == [(n, 5) for n in range(1, 6)]
    # 8 images each: the last 2 of each were held out and named correctly.
    assert set(report.per_class) == {"circle", "square", "triangle"}
    assert report.floor == 100.0 and report.accuracy == 100.0
    rng = random.Random(99)
    loaded = classifier.SymbolClassifier.load(weights)
    # A tile is opaque and of another shape than the artwork: the symbol on a coloured backdrop.
    tiles = []
    for shape in ("triangle", "circle", "square"):
        tile = Image.new("RGBA", (70, 64), (60, 20, 90, 255))
        tile.alpha_composite(symbol(shape, rng), (5, 2))
        tiles.append(tile.convert("RGB"))
    predictions = loaded.classify(tiles)
    assert [p.code for p in predictions] == ["triangle", "circle", "square"]
    assert all(0.0 <= p.confidence <= 100.0 for p in predictions)


def test_training_needs_two_symbols(tmp_path: Path, small_network) -> None:
    touch_images(tmp_path / "AA", ["AA_0.png"])

    with pytest.raises(classifier.SymbolTrainingError, match="at least two"):
        classifier.train(list_artwork(tmp_path), tmp_path / "model.pt", pretrained=False)


def test_unreadable_artwork_is_named_in_the_error(tmp_path: Path, small_network) -> None:
    touch_images(tmp_path / "AA", ["AA_0.png"])
    touch_images(tmp_path / "BB", ["BB_0.png"])
    (tmp_path / "BB" / "BB_0.png").write_bytes(b"not an image")

    with pytest.raises(classifier.SymbolTrainingError, match="BB_0.png"):
        classifier.train(list_artwork(tmp_path), tmp_path / "model.pt", pretrained=False)


def test_a_file_that_is_not_a_model_is_reported(tmp_path: Path) -> None:
    junk = tmp_path / "model.pt"
    junk.write_bytes(b"junk")

    with pytest.raises(classifier.SymbolTrainingError, match="Cannot load"):
        classifier.SymbolClassifier.load(junk)


def test_no_images_no_predictions() -> None:
    network = classifier._build(2, pretrained=False)

    assert classifier.SymbolClassifier(["AA", "BB"], network).classify([]) == []
