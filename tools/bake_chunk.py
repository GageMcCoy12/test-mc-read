"""Bake a Bedrock region to viewer/generated for the browser prototype.

Run: .venv/bin/python tools/bake_chunk.py --x 300 --z 73 --radius 0
Serve with: .venv/bin/python tools/serve_viewer.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amulet.api.errors import ChunkDoesNotExist, ChunkLoadError

from mcread.bake import DEFAULT_MIN_Y, DEFAULT_RADIUS, MAX_RADIUS, bake_and_write
from mcread.world_access import DEFAULT_WORLD, OVERWORLD, block_to_chunk_coords, open_level

DEFAULT_BLOCK_X = 300
DEFAULT_BLOCK_Z = 73
DEFAULT_OUT = PROJECT_ROOT / "viewer" / "generated"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=Path, default=DEFAULT_WORLD)
    parser.add_argument("--x", type=int, default=DEFAULT_BLOCK_X, help="center block x")
    parser.add_argument("--z", type=int, default=DEFAULT_BLOCK_Z, help="center block z")
    parser.add_argument("--dimension", default=OVERWORLD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--min-y", type=int, default=DEFAULT_MIN_Y)
    parser.add_argument("--max-y", type=int, default=None)
    parser.add_argument(
        "--radius",
        type=int,
        default=DEFAULT_RADIUS,
        help=f"chunk radius around the centre (0=1 chunk, max {MAX_RADIUS})",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.radius < 0 or args.radius > MAX_RADIUS:
        print(f"radius must be 0..{MAX_RADIUS}")
        return 2
    cx, cz = block_to_chunk_coords(args.x, args.z)
    print(
        f"baking chunk ({cx}, {cz}) from block ({args.x}, {args.z}), "
        f"radius {args.radius}, y {args.min_y} to "
        f"{args.max_y if args.max_y is not None else 'top'}"
    )
    try:
        with open_level(args.world) as level:
            bake, atlas, scene = bake_and_write(
                level,
                args.x,
                args.z,
                args.output,
                dimension=args.dimension,
                min_y=args.min_y,
                max_y=args.max_y,
                radius=args.radius,
            )
    except ChunkDoesNotExist as exc:
        print(exc)
        return 1
    except ChunkLoadError as exc:
        print(f"could not load chunk: {exc}")
        return 1
    except ValueError as exc:
        print(exc)
        return 2

    print(
        f"opaque {bake.opaque.triangle_count} tris, "
        f"translucent {bake.translucent.triangle_count} tris, "
        f"atlas {atlas.width}x{atlas.height}"
    )
    print(f"wrote {scene}")
    print(f"serve with: .venv/bin/python tools/serve_viewer.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
