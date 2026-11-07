"""Pack block textures into one atlas and remap UVs into atlas space.

Generated at bake time from the user's cached vanilla pack. Never commit the
PNG; Minecraft assets are not redistributable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy
from PIL import Image

TILE_SIZE = 16
PADDING = 1
MISSING = (248, 0, 248, 255)


@dataclass
class TextureAtlas:
    image: Image.Image
    rects: dict[str, tuple[float, float, float, float]]
    tile_size: int = TILE_SIZE
    padding: int = PADDING

    @property
    def width(self) -> int:
        return self.image.size[0]

    @property
    def height(self) -> int:
        return self.image.size[1]

    def remap_one(self, uv: numpy.ndarray, texture: str) -> numpy.ndarray:
        rect = self.rects.get(texture)
        if rect is None:
            return numpy.asarray(uv, dtype=numpy.float32)
        u0, v0, u1, v1 = rect
        u = float(uv[0])
        v = float(uv[1])
        return numpy.array(
            [u0 + u * (u1 - u0), v0 + v * (v1 - v0)], dtype=numpy.float32
        )


@lru_cache(maxsize=4096)
def texture_has_cutout(path: str) -> bool:
    """True when any pixel is not fully opaque. Those blocks must not hide faces."""
    try:
        image = Image.open(path).convert("RGBA")
    except (OSError, FileNotFoundError):
        return False
    alpha = first_frame(image).getchannel("A")
    return alpha.getextrema()[0] < 255


def first_frame(image: Image.Image) -> Image.Image:
    """Animated sheets are a vertical (or horizontal) strip of square frames."""
    width, height = image.size
    if height > width and height % width == 0:
        return image.crop((0, 0, width, width))
    if width > height and width % height == 0:
        return image.crop((0, 0, height, height))
    return image


def native_tile_size(path: str) -> int:
    """Longest side of the first frame, at least TILE_SIZE."""
    try:
        image = Image.open(path)
    except (OSError, FileNotFoundError):
        return TILE_SIZE
    width, height = first_frame(image).size
    return max(width, height, TILE_SIZE)


def _image_to_tile(image: Image.Image, tile_size: int) -> Image.Image:
    frame = first_frame(image.convert("RGBA"))
    if frame.size != (tile_size, tile_size):
        frame = frame.resize((tile_size, tile_size), Image.Resampling.NEAREST)
    return frame


def _load_tile(
    path: str, tile_size: int, extras: dict[str, Image.Image] | None = None
) -> Image.Image:
    if extras and path in extras:
        return _image_to_tile(extras[path], tile_size)
    try:
        image = Image.open(path).convert("RGBA")
    except (OSError, FileNotFoundError):
        return Image.new("RGBA", (tile_size, tile_size), MISSING)
    return _image_to_tile(image, tile_size)


def _paste_with_bleed(
    atlas: Image.Image, tile: Image.Image, x: int, y: int, padding: int
) -> None:
    width, height = tile.size
    if padding <= 0:
        atlas.paste(tile, (x, y))
        return
    left = tile.crop((0, 0, 1, height)).resize((padding, height), Image.Resampling.NEAREST)
    right = tile.crop((width - 1, 0, width, height)).resize(
        (padding, height), Image.Resampling.NEAREST
    )
    top = tile.crop((0, 0, width, 1)).resize((width, padding), Image.Resampling.NEAREST)
    bottom = tile.crop((0, height - 1, width, height)).resize(
        (width, padding), Image.Resampling.NEAREST
    )
    atlas.paste(left, (x - padding, y))
    atlas.paste(right, (x + width, y))
    atlas.paste(top, (x, y - padding))
    atlas.paste(bottom, (x, y + height))
    corner = tile.getpixel((0, 0))
    atlas.paste(
        Image.new("RGBA", (padding, padding), corner), (x - padding, y - padding)
    )
    corner = tile.getpixel((width - 1, 0))
    atlas.paste(
        Image.new("RGBA", (padding, padding), corner), (x + width, y - padding)
    )
    corner = tile.getpixel((0, height - 1))
    atlas.paste(
        Image.new("RGBA", (padding, padding), corner), (x - padding, y + height)
    )
    corner = tile.getpixel((width - 1, height - 1))
    atlas.paste(
        Image.new("RGBA", (padding, padding), corner), (x + width, y + height)
    )
    atlas.paste(tile, (x, y))


def build_atlas(
    paths: list[str],
    *,
    tile_size: int | None = None,
    padding: int = PADDING,
    extras: dict[str, Image.Image] | None = None,
) -> TextureAtlas:
    extras = extras or {}
    unique = list(dict.fromkeys([*paths, *extras]))
    if tile_size is None:
        tile_size = TILE_SIZE
        for path in unique:
            if path in extras:
                width, height = extras[path].size
                tile_size = max(tile_size, width, height)
            else:
                tile_size = max(tile_size, native_tile_size(path))
    count = max(len(unique), 1)
    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    cell = tile_size + 2 * padding
    width = max(columns * cell, cell)
    height = max(rows * cell, cell)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    rects: dict[str, tuple[float, float, float, float]] = {}

    for index, path in enumerate(unique):
        tile = _load_tile(path, tile_size, extras)
        column = index % columns
        row = index // columns
        x = column * cell + padding
        y = row * cell + padding
        _paste_with_bleed(image, tile, x, y, padding)
        rects[path] = (
            x / width,
            y / height,
            (x + tile_size) / width,
            (y + tile_size) / height,
        )

    return TextureAtlas(
        image=image, rects=rects, tile_size=tile_size, padding=padding
    )


def save_atlas(atlas: TextureAtlas, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atlas.image.save(path)
