import math

import pytest
from PIL import Image

from app.utils.image_crop import CropBox, InvalidCropError, crop_fraction, grid_boxes, split_grid

# Portrait phone, landscape monitor, square, ultra-wide, and sizes that do not divide evenly.
SIZES = [(1080, 1920), (1920, 1080), (500, 500), (3440, 1440), (766, 1101), (97, 61)]


def gradient(width: int, height: int) -> Image.Image:
    """Every pixel is unique-ish: red follows x, green follows y."""
    image = Image.new("RGB", (width, height))
    image.putdata([(x % 256, y % 256, (x * 7 + y * 13) % 256) for y in range(height) for x in range(width)])
    return image


@pytest.mark.parametrize("width,height", SIZES)
def test_crop_size_follows_the_fractions_on_any_aspect_ratio(width: int, height: int) -> None:
    image = Image.new("RGB", (width, height))

    crop = crop_fraction(image, [0.25, 0.1, 0.75, 0.6])

    assert crop.size == (round(0.75 * width) - round(0.25 * width), round(0.6 * height) - round(0.1 * height))


@pytest.mark.parametrize("width,height", SIZES)
def test_crop_takes_the_pixels_from_the_right_place(width: int, height: int) -> None:
    image = gradient(width, height)
    box = CropBox(0.2, 0.3, 0.9, 0.8)
    left, top, right, bottom = box.to_pixels(width, height)

    crop = crop_fraction(image, box)

    assert crop.getpixel((0, 0)) == image.getpixel((left, top))
    assert crop.getpixel((crop.width - 1, crop.height - 1)) == image.getpixel((right - 1, bottom - 1))


def test_horizontal_and_vertical_fractions_are_independent() -> None:
    # The same fractions on a wide and a tall image cut the same relative area.
    wide = crop_fraction(Image.new("RGB", (2000, 500)), [0.0, 0.0, 0.5, 1.0])
    tall = crop_fraction(Image.new("RGB", (500, 2000)), [0.0, 0.0, 0.5, 1.0])

    assert wide.size == (1000, 500)
    assert tall.size == (250, 2000)


def test_full_image_box_returns_every_pixel() -> None:
    image = gradient(97, 61)

    crop = crop_fraction(image, [0.0, 0.0, 1.0, 1.0])

    assert crop.size == image.size
    assert crop.tobytes() == image.tobytes()


def test_crop_is_a_copy_and_leaves_the_source_untouched() -> None:
    image = Image.new("RGB", (10, 10), "red")

    crop = crop_fraction(image, [0.0, 0.0, 0.5, 0.5])
    crop.putpixel((0, 0), (0, 0, 255))

    assert image.getpixel((0, 0)) == (255, 0, 0)


def test_crop_keeps_the_image_mode() -> None:
    assert crop_fraction(Image.new("RGBA", (10, 10)), [0, 0, 0.5, 0.5]).mode == "RGBA"
    assert crop_fraction(Image.new("L", (10, 10)), [0, 0, 0.5, 0.5]).mode == "L"


def test_a_sliver_thinner_than_a_pixel_still_yields_one_pixel() -> None:
    crop = crop_fraction(Image.new("RGB", (100, 100)), [0.500, 0.500, 0.501, 0.501])

    assert crop.size == (1, 1)


def test_box_touching_the_far_edge_stays_inside_the_image() -> None:
    left, top, right, bottom = CropBox(0.999, 0.999, 1.0, 1.0).to_pixels(100, 50)

    assert (left, top, right, bottom) == (99, 49, 100, 50)


def test_accepts_a_tuple_and_a_crop_box() -> None:
    image = Image.new("RGB", (100, 100))

    assert crop_fraction(image, (0.0, 0.0, 0.5, 0.5)).size == (50, 50)
    assert crop_fraction(image, CropBox(0.0, 0.0, 0.5, 0.5)).size == (50, 50)


@pytest.mark.parametrize(
    "box",
    [
        [],
        [0.0, 0.0, 1.0],  # too short
        [0.0, 0.0, 1.0, 1.0, 1.0],  # too long
        [0.5, 0.0, 0.5, 1.0],  # no width
        [0.0, 0.7, 1.0, 0.3],  # upside down
        [-0.1, 0.0, 1.0, 1.0],  # outside the image
        [0.0, 0.0, 1.5, 1.0],
        [0.0, 0.0, math.nan, 1.0],
        [0.0, 0.0, math.inf, 1.0],
        [0.0, 0.0, "1.0", 1.0],
        [0.0, 0.0, None, 1.0],
        [False, 0.0, True, 1.0],
        "0.0 0.0 1.0 1.0",
        None,
    ],
)
def test_invalid_boxes_are_rejected(box) -> None:
    with pytest.raises(InvalidCropError):
        crop_fraction(Image.new("RGB", (100, 100)), box)


def test_crop_box_rejects_a_pixel_box_of_an_empty_image() -> None:
    with pytest.raises(InvalidCropError):
        CropBox(0.0, 0.0, 1.0, 1.0).to_pixels(0, 100)


# ------------------------------------------------------------------------------ grids


@pytest.mark.parametrize("width,height", SIZES)
@pytest.mark.parametrize("rows,columns", [(3, 5), (1, 1), (4, 4), (2, 7)])
def test_cells_tile_the_image_exactly_with_no_gap_or_overlap(
    width: int, height: int, rows: int, columns: int
) -> None:
    if width < columns or height < rows:
        pytest.skip("image smaller than the grid")
    boxes = grid_boxes(rows, columns)

    pixels = [[box.to_pixels(width, height) for box in row] for row in boxes]

    assert pixels[0][0][:2] == (0, 0)
    assert pixels[-1][-1][2:] == (width, height)
    for row in pixels:
        for left, right in zip(row, row[1:]):
            assert left[2] == right[0]  # touching horizontally
    for upper, lower in zip(pixels, pixels[1:]):
        for above, below in zip(upper, lower):
            assert above[3] == below[1]  # touching vertically
    assert sum((r - l) * (b - t) for row in pixels for l, t, r, b in row) == width * height


def test_split_grid_returns_rows_of_columns() -> None:
    cells = split_grid(Image.new("RGB", (500, 300)), rows=3, columns=5)

    assert len(cells) == 3
    assert all(len(row) == 5 for row in cells)
    assert all(cell.size == (100, 100) for row in cells for cell in row)


def test_split_grid_cells_come_from_their_own_position() -> None:
    image = Image.new("RGB", (40, 20))
    for column in range(4):
        for row in range(2):
            image.paste((column * 50, row * 100, 0), (column * 10, row * 10, column * 10 + 10, row * 10 + 10))

    cells = split_grid(image, rows=2, columns=4)

    for row in range(2):
        for column in range(4):
            assert cells[row][column].getpixel((0, 0)) == (column * 50, row * 100, 0)


def test_inset_trims_each_cell_by_a_fraction_of_the_cell() -> None:
    cells = split_grid(Image.new("RGB", (500, 300)), rows=3, columns=5, inset=0.1)

    assert all(cell.size == (80, 80) for row in cells for cell in row)


def test_inset_pair_is_horizontal_then_vertical() -> None:
    cells = split_grid(Image.new("RGB", (500, 300)), rows=3, columns=5, inset=[0.25, 0.0])

    assert all(cell.size == (50, 100) for row in cells for cell in row)


def test_inset_on_a_non_square_grid_follows_each_axis_separately() -> None:
    cells = split_grid(Image.new("RGB", (1000, 100)), rows=1, columns=2, inset=0.1)

    assert cells[0][0].size == (400, 80)


@pytest.mark.parametrize("inset", [-0.1, 0.5, 0.9, [0.1], [0.1, 0.2, 0.3], math.nan, "0.1", [0.1, 0.6]])
def test_invalid_insets_are_rejected(inset) -> None:
    with pytest.raises(InvalidCropError):
        grid_boxes(3, 5, inset)


@pytest.mark.parametrize("rows,columns", [(0, 5), (3, 0), (-1, 5), (3, 2.5), (True, 5), ("3", 5)])
def test_invalid_grid_sizes_are_rejected(rows, columns) -> None:
    with pytest.raises(InvalidCropError):
        grid_boxes(rows, columns)


def test_an_image_smaller_than_the_grid_is_rejected() -> None:
    with pytest.raises(InvalidCropError):
        split_grid(Image.new("RGB", (4, 100)), rows=3, columns=5)
