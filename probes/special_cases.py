"""Probe: what genuinely needs custom code, and why?

Takes every blockstate with no mesh and asks the pack whether Minecraft itself
ships geometry for it. If the pack has no elements anywhere in the model chain,
the gap is Minecraft's own design and needs a custom renderer. If the pack does
have elements and we still got nothing, that is a bug on our side.

Run: .venv/bin/python probes/special_cases.py --radius 4
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Iterable

from _common import add_region_args, walk_region, write_report

from mcread.blocks import FLUID_BASE_NAMES, blockstate_key, is_empty_block
from mcread.census import PaletteCensus
from mcread.inventory import NonBlockInventory
from mcread.models import describe_block_mesh, java_model_manager
from mcread.pack_inspect import geometry_source
from mcread.translate import JavaTranslator

CATEGORY_NOTES = {
    "fluid": "engine fluid renderer: level/falling drive geometry, model has no elements",
    "block_entity_model": "drawn from models/entity assets by a block entity renderer",
    "no_java_equivalent": "no Java block exists, so no blockstate to look up",
    "pack_has_geometry_but_we_got_none": "our bug: the pack defines elements we failed to use",
    "runtime_tinted": (
        "geometry resolves, but at least one face carries tintindex, so its colour "
        "comes from a runtime tint source: the biome for foliage, power level for "
        "redstone wire, water colour for cauldrons"
    ),
    "needs_neighbours": "final blockstate depends on adjacent blocks",
}


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_region_args(parser)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    inventory = NonBlockInventory()
    census = PaletteCensus()
    skipped = 0
    for _cx, _cz, chunk, _error in walk_region(args):
        if chunk is None:
            skipped += 1
            continue
        census.add_chunk(chunk)
        inventory.add_chunk(chunk)

    translator = JavaTranslator()
    manager = java_model_manager()
    pack_roots = manager.pack_paths
    block_entity_names = {
        name.split(":")[-1] for name in inventory.block_entity_counts
    }

    categories: dict[str, list[dict]] = {key: [] for key in CATEGORY_NOTES}
    resolved_count = 0

    for key, block in census.iter_blocks():
        count = census.counts[key]
        result = translator.translate(block)

        if not result.ok or result.block is None:
            categories["no_java_equivalent"].append(
                {"universal": key, "count": count, "reason": result.error or "entity"}
            )
            continue

        java_block = result.block
        java_key = blockstate_key(java_block)

        if is_empty_block(java_block):
            categories["no_java_equivalent"].append(
                {
                    "universal": key,
                    "count": count,
                    "java": java_key,
                    "reason": "translated to air",
                }
            )
            continue

        _mesh, summary = describe_block_mesh(manager, java_block)
        source = geometry_source(pack_roots, java_block.namespace, java_block.base_name)

        entry = {
            "universal": key,
            "java": java_key,
            "count": count,
            "blockstate_json_found": source.blockstate_found,
            "models_referenced": list(source.models),
            "element_source": source.element_source,
        }

        if summary.is_missing:
            if source.has_geometry:
                categories["pack_has_geometry_but_we_got_none"].append(entry)
            elif java_block.base_name in FLUID_BASE_NAMES:
                categories["fluid"].append(entry)
            elif java_block.base_name in block_entity_names or _looks_like_block_entity(
                java_block.base_name, block_entity_names
            ):
                categories["block_entity_model"].append(entry)
            else:
                categories["block_entity_model"].append(
                    {**entry, "note": "no elements in pack, no matching block entity"}
                )
            continue

        resolved_count += 1
        if summary.is_tinted or source.has_tintindex:
            categories["runtime_tinted"].append(
                {
                    **entry,
                    "mesh_reports_tint": summary.is_tinted,
                    "model_json_has_tintindex": source.has_tintindex,
                }
            )
        if result.extra_needed:
            categories["needs_neighbours"].append(entry)

    payload = {
        "scan": {
            "world": str(args.world),
            "dimension": args.dimension,
            "radius_chunks": args.radius,
            "chunks_skipped": skipped,
        },
        "category_notes": CATEGORY_NOTES,
        "summary": {
            "distinct_blockstates": len(list(census.iter_blocks())),
            "rendered_from_block_models": resolved_count,
            **{
                f"{name}_blockstates": len(rows) for name, rows in categories.items()
            },
        },
        "block_instance_totals": {
            name: sum(row["count"] for row in rows) for name, rows in categories.items()
        },
        "categories": categories,
    }
    path = write_report("special_cases", payload, args.output)

    summary = payload["summary"]
    totals = payload["block_instance_totals"]
    print(
        f"{summary['rendered_from_block_models']}/"
        f"{summary['distinct_blockstates']} distinct blockstates render straight "
        f"from block model JSON"
    )
    print("\nwhat needs custom code:")
    for name, rows in categories.items():
        if not rows:
            print(f"  {name}: none")
            continue
        base_names = Counter(row.get("java", "?").split("[")[0] for row in rows)
        print(
            f"  {name}: {len(rows)} blockstates, {totals[name]:,} block instances"
        )
        print(f"      {CATEGORY_NOTES[name]}")
        print(f"      {', '.join(sorted(base_names))}")

    bug_rows = categories["pack_has_geometry_but_we_got_none"]
    if bug_rows:
        print(f"\nWARNING: {len(bug_rows)} blockstate(s) should have worked:")
        for row in bug_rows[:10]:
            print(f"  {row['java']} elements from {row['element_source']}")
    else:
        print("\nno gaps that the pack could have filled: every miss is by design")

    print(f"\nreport: {path}")
    return 0


def _looks_like_block_entity(base_name: str, block_entity_names: set[str]) -> bool:
    """Colour-prefixed Java names like `lime_shulker_box` share a base entity."""
    return any(base_name.endswith(f"_{name}") or name in base_name for name in block_entity_names)


if __name__ == "__main__":
    raise SystemExit(main())
