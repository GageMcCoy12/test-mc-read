"""Probe: does every translated blockstate resolve to real geometry?

`get_block_model` never raises. It returns a missingno mesh instead, so the
only way to find gaps is to compare the result against `missing_block`.
Also collects the exact set of textures this world needs.

Run: .venv/bin/python probes/asset_coverage.py --radius 4
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Iterable

from _common import add_region_args, collect_census, write_report

from mcread.blocks import blockstate_key
from mcread.models import describe_block_mesh, java_model_manager
from mcread.translate import JavaTranslator


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_region_args(parser)
    parser.add_argument("--top", type=int, default=15, help="how many rows to print")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    census, scan = collect_census(args)
    translator = JavaTranslator()
    manager = java_model_manager()

    resolved: list[dict] = []
    missing: list[dict] = []
    untranslatable: list[dict] = []
    tinted: list[dict] = []
    textures_needed: Counter[str] = Counter()
    cull_direction_usage: Counter[str] = Counter()

    for key, block in census.iter_blocks():
        count = census.counts[key]
        result = translator.translate(block)
        if not result.ok or result.block is None:
            untranslatable.append(
                {"universal": key, "count": count, "error": result.error}
            )
            continue

        java_key = blockstate_key(result.block)
        _mesh, summary = describe_block_mesh(manager, result.block)
        entry = {
            "universal": key,
            "java": java_key,
            "count": count,
            "vert_count": summary.vert_count,
            "face_count": summary.face_count,
            "cull_directions": [
                "none" if d is None else d for d in summary.cull_directions
            ],
            "textures": [Path(t).name for t in summary.textures],
            "is_opaque": summary.is_opaque,
            "transparency": summary.transparency,
            "tinted_vert_count": summary.tinted_vert_count,
        }

        if summary.is_missing:
            missing.append(entry)
            continue

        resolved.append(entry)
        for texture in summary.textures:
            textures_needed[texture] += 1
        for direction in summary.cull_directions:
            cull_direction_usage["none" if direction is None else direction] += 1
        if summary.is_tinted:
            tinted.append(entry)

    total = len(resolved) + len(missing) + len(untranslatable)
    coverage = (len(resolved) / total * 100) if total else 0.0
    blocks_missing_geometry = sum(row["count"] for row in missing)

    payload = {
        "scan": scan,
        "resource_packs": list(manager.pack_paths),
        "summary": {
            "distinct_blockstates": total,
            "resolved_to_geometry": len(resolved),
            "coverage_percent": round(coverage, 2),
            "fell_back_to_missingno": len(missing),
            "untranslatable": len(untranslatable),
            "block_instances_missing_geometry": blocks_missing_geometry,
            "distinct_textures_needed": len(textures_needed),
            "biome_tinted_blockstates": len(tinted),
        },
        "cull_direction_usage": dict(cull_direction_usage.most_common()),
        "fell_back_to_missingno": missing,
        "untranslatable": untranslatable,
        "biome_tinted": tinted,
        "textures_needed": sorted(Path(t).name for t in textures_needed),
        "resolved": resolved,
    }
    path = write_report("asset_coverage", payload, args.output)

    summary = payload["summary"]
    print(f"resource packs: {len(manager.pack_paths)}")
    print(
        f"\nresolved {summary['resolved_to_geometry']}/"
        f"{summary['distinct_blockstates']} distinct blockstates to real geometry "
        f"({summary['coverage_percent']}%)"
    )
    print(f"  fell back to missingno: {summary['fell_back_to_missingno']}")
    print(f"  untranslatable:         {summary['untranslatable']}")
    print(
        f"  block instances with no geometry: "
        f"{summary['block_instances_missing_geometry']:,}"
    )
    print(f"  distinct textures needed: {summary['distinct_textures_needed']}")
    print(f"  biome-tinted blockstates: {summary['biome_tinted_blockstates']}")
    print(f"\ncull direction usage: {payload['cull_direction_usage']}")

    if missing:
        print("\nno geometry in the pack (would render as missingno):")
        for row in sorted(missing, key=lambda r: -r["count"])[: args.top]:
            print(f"  {row['count']:9,}  {row['universal']} -> {row['java']}")

    if untranslatable:
        print("\ncould not translate, so never reached the pack:")
        for row in sorted(untranslatable, key=lambda r: -r["count"])[: args.top]:
            print(f"  {row['count']:9,}  {row['universal']}")

    if tinted:
        print("\nbiome-tinted (needs chunk.biomes to colour correctly):")
        for row in sorted(tinted, key=lambda r: -r["count"])[: args.top]:
            print(f"  {row['count']:9,}  {row['java']}")

    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
