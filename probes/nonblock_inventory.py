"""Probe: what does the save give us besides blocks?

Covers block entity NBT, biomes, entities, misc chunk data, the stored y
extent, and which dimensions have data in this region.

Run: .venv/bin/python probes/nonblock_inventory.py --radius 4
"""

from __future__ import annotations

import argparse
import json
from typing import Iterable

from _common import DIMENSIONS, add_region_args, region_of, walk_region, write_report

from mcread.inventory import NonBlockInventory


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_region_args(parser)
    parser.add_argument(
        "--all-dimensions",
        action="store_true",
        help="also check the same region in the nether and the end",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def scan_dimension(args: argparse.Namespace, dimension: str) -> tuple[dict, int, int]:
    inventory = NonBlockInventory()
    present = 0
    missing = 0
    for _cx, _cz, chunk, _error in walk_region(args, dimension):
        if chunk is None:
            missing += 1
            continue
        present += 1
        inventory.add_chunk(chunk)
    return inventory.as_dict(), present, missing


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    center_cx, center_cz, radius = region_of(args)

    primary, present, missing = scan_dimension(args, args.dimension)

    dimension_coverage = {
        args.dimension: {"chunks_with_data": present, "chunks_missing": missing}
    }
    if args.all_dimensions:
        for dimension in DIMENSIONS:
            if dimension == args.dimension:
                continue
            _data, other_present, other_missing = scan_dimension(args, dimension)
            dimension_coverage[dimension] = {
                "chunks_with_data": other_present,
                "chunks_missing": other_missing,
            }

    payload = {
        "scan": {
            "world": str(args.world),
            "dimension": args.dimension,
            "center_chunk": [center_cx, center_cz],
            "radius_chunks": radius,
        },
        "dimension_coverage": dimension_coverage,
        "inventory": primary,
    }
    path = write_report("nonblock_inventory", payload, args.output)

    block_entities = primary["block_entities"]
    biomes = primary["biomes"]
    print(f"chunks with data: {present} (missing {missing})")
    print(f"stored y extent: {primary['world_y_extent']}")
    print(f"misc chunk keys: {list(primary['misc_keys'])}")
    print(
        f"\nblock entities: {block_entities['total']} across "
        f"{block_entities['distinct_types']} types"
    )
    for name, count in block_entities["counts"].items():
        print(f"  {count:6d}  {name}")

    print(f"\nentities: {primary['entities']['total']}")
    for name, count in list(primary["entities"]["counts"].items())[:10]:
        print(f"  {count:6d}  {name}")

    print(
        f"\nbiomes: {biomes['distinct']} distinct, "
        f"stored as {list(biomes['storage_classes'])}"
    )
    for name, count in list(biomes["counts"].items())[:10]:
        print(f"  {count:6d}  {name}")

    print("\ndimension coverage for this region:")
    for dimension, counts in dimension_coverage.items():
        print(
            f"  {dimension}: {counts['chunks_with_data']} with data, "
            f"{counts['chunks_missing']} missing"
        )

    print("\nblock entity nbt shapes:")
    for name, shape in block_entities["nbt_shapes"].items():
        print(f"  {name}: {json.dumps(shape)}")

    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
