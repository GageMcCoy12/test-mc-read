"""Shared plumbing for the audit probes.

Probes are read-only, but opening a leveldb can rewrite LOG/MANIFEST during log
recovery, so run them against a copy of the save if the original matters:

    cp -R world /tmp/world_audit
    .venv/bin/python probes/palette_census.py --world /tmp/world_audit
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amulet.api.chunk import Chunk  # noqa: E402

from mcread.census import PaletteCensus  # noqa: E402
from mcread.world_access import (  # noqa: E402
    DEFAULT_WORLD,
    DIMENSIONS,
    OVERWORLD,
    block_to_chunk_coords,
    iter_chunks,
    iter_region_coords,
    open_level,
)

DEFAULT_BLOCK_X = 300
DEFAULT_BLOCK_Z = 70
DEFAULT_RADIUS = 4
REPORT_DIR = PROJECT_ROOT / "reports"


def add_region_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--world", type=Path, default=DEFAULT_WORLD)
    parser.add_argument("--x", type=int, default=DEFAULT_BLOCK_X, help="centre block x")
    parser.add_argument("--z", type=int, default=DEFAULT_BLOCK_Z, help="centre block z")
    parser.add_argument(
        "--radius", type=int, default=DEFAULT_RADIUS, help="chunk radius around centre"
    )
    parser.add_argument("--dimension", default=OVERWORLD)
    parser.add_argument(
        "--output", type=Path, default=None, help="report path (default reports/<name>)"
    )
    return parser


def region_of(args: argparse.Namespace) -> tuple[int, int, int]:
    center_cx, center_cz = block_to_chunk_coords(args.x, args.z)
    return center_cx, center_cz, args.radius


def walk_region(
    args: argparse.Namespace, dimension: str | None = None
) -> Iterator[tuple[int, int, Chunk | None, str | None]]:
    """Open the level once and yield every chunk in the requested region."""
    center_cx, center_cz, radius = region_of(args)
    target = dimension or args.dimension
    with open_level(args.world) as level:
        coords = iter_region_coords(center_cx, center_cz, radius)
        yield from iter_chunks(level, coords, target)


def collect_census(args: argparse.Namespace) -> tuple[PaletteCensus, dict]:
    """Walk the region once and census every blockstate in it."""
    census = PaletteCensus()
    skipped: dict[str, str] = {}
    started = time.monotonic()
    for cx, cz, chunk, error in walk_region(args):
        if chunk is None:
            skipped[f"{cx},{cz}"] = error or "unknown"
            continue
        census.add_chunk(chunk)
    elapsed = time.monotonic() - started

    center_cx, center_cz, radius = region_of(args)
    scan = {
        "world": str(args.world),
        "dimension": args.dimension,
        "center_chunk": [center_cx, center_cz],
        "radius_chunks": radius,
        "chunks_requested": (radius * 2 + 1) ** 2,
        "chunks_skipped": skipped,
        "seconds": round(elapsed, 2),
    }
    return census, scan


def environment() -> dict:
    """Version stamp, so a stale report is obvious."""
    import amulet
    import PyMCTranslate

    info = {
        "amulet_core": amulet.__version__,
        "pymctranslate": PyMCTranslate.__version__,
    }
    try:
        import minecraft_model_reader

        info["minecraft_model_reader"] = minecraft_model_reader.__version__
    except ImportError:
        info["minecraft_model_reader"] = None
    try:
        from mcread.translate import newest_version

        info["newest_bedrock_definitions"] = list(newest_version("bedrock"))
        info["newest_java_definitions"] = list(newest_version("java"))
    except Exception:
        pass
    return info


def write_report(name: str, payload: dict[str, Any], output: Path | None) -> Path:
    path = output or (REPORT_DIR / f"{name}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"probe": name, "environment": environment(), **payload}
    with path.open("w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
    return path


def world_version(world_path: Path) -> list[int] | None:
    """`lastOpenedWithVersion` from level.dat, past the 8-byte Bedrock header."""
    try:
        import amulet_nbt

        raw = (Path(world_path) / "level.dat").read_bytes()
        nbt = amulet_nbt.load(raw[8:], little_endian=True, compressed=False)
        version = nbt.compound.get("lastOpenedWithVersion")
        if version is None:
            return None
        return [int(part) for part in version]
    except Exception:
        return None


__all__ = [
    "DIMENSIONS",
    "add_region_args",
    "collect_census",
    "environment",
    "region_of",
    "walk_region",
    "world_version",
    "write_report",
]
