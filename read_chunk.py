"""Read one Bedrock chunk and print random non-air blocks in english."""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from amulet.api.block import Block
from amulet.api.chunk import Chunk
from amulet.api.errors import ChunkDoesNotExist, ChunkLoadError

from mcread.blocks import (
    AIR_BASE_NAMES,
    format_block_english,
    format_property_value,
    is_empty_block,
)
from mcread.world_access import (
    DEFAULT_WORLD,
    OVERWORLD,
    block_to_chunk_coords,
    open_chunk,
    patch_amulet_chunk_v42,
)

DEFAULT_BLOCK_X = 300
DEFAULT_BLOCK_Z = 70
DEFAULT_COUNT = 10
DEFAULT_SEED = 30070
MAX_SAMPLE_ATTEMPTS_MULTIPLIER = 200

__all__ = [
    "AIR_BASE_NAMES",
    "DEFAULT_WORLD",
    "OVERWORLD",
    "SampledBlock",
    "block_to_chunk_coords",
    "format_block_english",
    "format_property_value",
    "is_empty_block",
    "main",
    "open_chunk",
    "patch_amulet_chunk_v42",
    "sample_non_air_blocks",
]


@dataclass(frozen=True)
class SampledBlock:
    x: int
    y: int
    z: int
    block: Block

    def as_english(self) -> str:
        return f"{format_block_english(self.block)} at ({self.x}, {self.y}, {self.z})"


def _y_range_for_chunk(
    chunk: Chunk,
    *,
    min_y: int | None = None,
    max_y: int | None = None,
) -> Sequence[int]:
    subchunks = sorted(chunk.blocks.sub_chunks)
    if not subchunks:
        return []
    ys: list[int] = []
    for cy in subchunks:
        ys.extend(range(cy * 16, cy * 16 + 16))
    if min_y is not None:
        ys = [y for y in ys if y >= min_y]
    if max_y is not None:
        ys = [y for y in ys if y <= max_y]
    return ys


def sample_non_air_blocks(
    chunk: Chunk,
    count: int,
    *,
    rng: random.Random,
    min_y: int | None = None,
    max_y: int | None = None,
) -> list[SampledBlock]:
    """Pick random in-chunk positions until we have `count` non-air blocks."""
    ys = _y_range_for_chunk(chunk, min_y=min_y, max_y=max_y)
    if not ys:
        raise ValueError(
            "no stored subchunk heights match the requested y range, "
            "so there is nothing to sample"
        )

    found: list[SampledBlock] = []
    seen: set[tuple[int, int, int]] = set()
    max_attempts = max(count * MAX_SAMPLE_ATTEMPTS_MULTIPLIER, 500)

    for _ in range(max_attempts):
        if len(found) >= count:
            break
        dx = rng.randrange(16)
        dz = rng.randrange(16)
        y = rng.choice(ys)
        key = (dx, y, dz)
        if key in seen:
            continue
        seen.add(key)
        block = chunk.get_block(dx, y, dz)
        if is_empty_block(block):
            continue
        world_x = chunk.cx * 16 + dx
        world_z = chunk.cz * 16 + dz
        found.append(SampledBlock(world_x, y, world_z, block))

    if len(found) < count:
        raise ValueError(
            f"only found {len(found)} non-air block(s) after {max_attempts} random tries"
        )
    return found


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print random non-air blocks from a Bedrock chunk."
    )
    parser.add_argument("--world", type=Path, default=DEFAULT_WORLD)
    parser.add_argument("--x", type=int, default=DEFAULT_BLOCK_X, help="block x")
    parser.add_argument("--z", type=int, default=DEFAULT_BLOCK_Z, help="block z")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--dimension", default=OVERWORLD)
    parser.add_argument("--min-y", type=int, default=None, help="inclusive lowest y")
    parser.add_argument("--max-y", type=int, default=None, help="inclusive highest y")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.min_y is not None and args.max_y is not None and args.min_y > args.max_y:
        parser.error("--min-y cannot be greater than --max-y")
    return args


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    chunk_x, chunk_z = block_to_chunk_coords(args.x, args.z)
    y_range = ""
    if args.min_y is not None or args.max_y is not None:
        low = args.min_y if args.min_y is not None else "world bottom"
        high = args.max_y if args.max_y is not None else "world top"
        y_range = f", y {low} to {high}"
    print(
        f"reading chunk ({chunk_x}, {chunk_z}) from block ({args.x}, {args.z}) "
        f"in {args.dimension}{y_range}"
    )
    try:
        with open_chunk(args.world, chunk_x, chunk_z, args.dimension) as chunk:
            samples = sample_non_air_blocks(
                chunk,
                args.count,
                rng=random.Random(args.seed),
                min_y=args.min_y,
                max_y=args.max_y,
            )
    except ChunkDoesNotExist as exc:
        print(exc)
        return 1
    except ChunkLoadError as exc:
        print(f"could not load chunk: {exc}")
        return 1
    except ValueError as exc:
        print(exc)
        return 1

    for i, sample in enumerate(samples, start=1):
        print(f"{i}. {sample.as_english()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
