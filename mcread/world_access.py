"""Open a Bedrock save and hand out chunks.

Importing this module applies the chunk-version patch, so every consumer gets a
readable level without repeating the setup.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import amulet
from amulet.api.chunk import Chunk
from amulet.api.errors import ChunkDoesNotExist, ChunkLoadError
from amulet.api.level import BaseLevel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORLD = PROJECT_ROOT / "world"
OVERWORLD = "minecraft:overworld"
NETHER = "minecraft:the_nether"
THE_END = "minecraft:the_end"
DIMENSIONS = (OVERWORLD, NETHER, THE_END)

_AMULET_V42_PATCHED = False


def patch_amulet_chunk_v42() -> None:
    """amulet-core 1.9.30 stops at chunk version 41. this world is 42."""
    global _AMULET_V42_PATCHED
    if _AMULET_V42_PATCHED:
        return

    from amulet.level.formats.leveldb_world.interface.chunk import (
        leveldb_41,
        leveldb_chunk_versions,
    )
    from amulet.level.formats.leveldb_world.interface import chunk as chunk_pkg

    versions = leveldb_chunk_versions.chunk_version_to_max_version
    versions[41] = ((1, 21, 40, 0), (1, 21, 139, 999))
    versions[42] = ((1, 21, 120, 0), (999, 999, 999, 999))

    chunk_pkg.get_interface(41)

    class LevelDB42Interface(leveldb_41.LevelDB41Interface):
        chunk_version = 42

    chunk_pkg._interfaces[42] = LevelDB42Interface()
    _AMULET_V42_PATCHED = True


patch_amulet_chunk_v42()


def block_to_chunk_coords(block_x: int, block_z: int) -> tuple[int, int]:
    return math.floor(block_x / 16), math.floor(block_z / 16)


@contextmanager
def open_level(world_path: Path | str) -> Iterator[BaseLevel]:
    """Hold one level handle open. Use this when reading many chunks."""
    level = amulet.load_level(str(world_path))
    try:
        yield level
    finally:
        level.close()


@contextmanager
def open_chunk(
    world_path: Path, chunk_x: int, chunk_z: int, dimension: str
) -> Iterator[Chunk]:
    """Open a level for a single chunk. Prefer `open_level` for bulk reads."""
    with open_level(world_path) as level:
        if not level.has_chunk(chunk_x, chunk_z, dimension):
            raise ChunkDoesNotExist(
                f"chunk ({chunk_x}, {chunk_z}) does not exist in {dimension}"
            )
        yield level.get_chunk(chunk_x, chunk_z, dimension)


def iter_region_coords(
    center_cx: int, center_cz: int, radius: int
) -> Iterator[tuple[int, int]]:
    """Chunk coords in a square region, centre first then outward."""
    for cz in range(center_cz - radius, center_cz + radius + 1):
        for cx in range(center_cx - radius, center_cx + radius + 1):
            yield cx, cz


def iter_chunks(
    level: BaseLevel,
    coords: Iterator[tuple[int, int]],
    dimension: str,
) -> Iterator[tuple[int, int, Chunk | None, str | None]]:
    """Yield (cx, cz, chunk, error) so callers can report gaps instead of dying."""
    for cx, cz in coords:
        if not level.has_chunk(cx, cz, dimension):
            yield cx, cz, None, "missing"
            continue
        try:
            yield cx, cz, level.get_chunk(cx, cz, dimension), None
        except ChunkDoesNotExist:
            yield cx, cz, None, "missing"
        except ChunkLoadError as exc:
            yield cx, cz, None, f"load error: {exc}"
