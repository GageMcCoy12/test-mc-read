"""Probe: can every blockstate in this world become a Java blockstate?

The resource pack is keyed by Java blockstate, so anything that fails here is
invisible to the renderer. This is also where version skew shows up: the save
was written by a newer Bedrock build than PyMCTranslate has definitions for.

Run: .venv/bin/python probes/translation_coverage.py --radius 4
"""

from __future__ import annotations

import argparse
from typing import Iterable

from _common import add_region_args, collect_census, world_version, write_report

from mcread.blocks import blockstate_key, is_empty_block
from mcread.translate import JavaTranslator, newest_version


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_region_args(parser)
    parser.add_argument("--top", type=int, default=15, help="how many rows to print")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    census, scan = collect_census(args)
    translator = JavaTranslator()

    translated: list[dict] = []
    failures: list[dict] = []
    passed_through: list[dict] = []
    collapsed_to_air: list[dict] = []
    became_entity: list[dict] = []
    needs_neighbours: list[dict] = []
    with_extra_blocks: list[dict] = []

    for key, block in census.iter_blocks():
        count = census.counts[key]
        result = translator.translate(block)
        entry = {
            "universal": key,
            "count": count,
            "java": blockstate_key(result.block) if result.block else None,
            "extra_needed": result.extra_needed,
            "error": result.error,
        }

        if block.extra_blocks:
            with_extra_blocks.append(
                {
                    **entry,
                    "extra_blocks": [
                        blockstate_key(extra) for extra in block.extra_blocks
                    ],
                }
            )

        if result.passed_through:
            passed_through.append(entry)
            continue
        if result.error is not None:
            failures.append(entry)
            continue
        if result.became_entity:
            became_entity.append(entry)
            continue
        assert result.block is not None
        if is_empty_block(result.block):
            collapsed_to_air.append(entry)
            continue
        if result.extra_needed:
            needs_neighbours.append(entry)
        translated.append(entry)

    total = (
        len(translated)
        + len(failures)
        + len(passed_through)
        + len(collapsed_to_air)
        + len(became_entity)
    )
    coverage = (len(translated) / total * 100) if total else 0.0

    payload = {
        "scan": scan,
        "world_last_opened_with_version": world_version(args.world),
        "java_target_version": list(translator.version_number),
        "newest_bedrock_definitions": list(newest_version("bedrock")),
        "summary": {
            "distinct_blockstates": total,
            "translated": len(translated),
            "coverage_percent": round(coverage, 2),
            "failures": len(failures),
            "passed_through_untranslated": len(passed_through),
            "collapsed_to_air": len(collapsed_to_air),
            "became_entity": len(became_entity),
            "needs_neighbouring_blocks": len(needs_neighbours),
            "carries_extra_blocks": len(with_extra_blocks),
        },
        "failures": failures,
        "passed_through_untranslated": passed_through,
        "collapsed_to_air": collapsed_to_air,
        "became_entity": became_entity,
        "needs_neighbouring_blocks": needs_neighbours,
        "carries_extra_blocks": with_extra_blocks,
        "translated": translated,
    }
    path = write_report("translation_coverage", payload, args.output)

    summary = payload["summary"]
    print(f"world written by bedrock {payload['world_last_opened_with_version']}")
    print(
        f"newest bedrock definitions available: "
        f"{payload['newest_bedrock_definitions']}"
    )
    print(f"java target: {payload['java_target_version']}")
    print(
        f"\ntranslated {summary['translated']}/{summary['distinct_blockstates']} "
        f"distinct blockstates ({summary['coverage_percent']}%)"
    )
    print(f"  hard failures:        {summary['failures']}")
    print(
        f"  passed through:       {summary['passed_through_untranslated']} "
        f"(no translation known, still in the universal namespace)"
    )
    print(f"  collapsed to air:     {summary['collapsed_to_air']}")
    print(f"  became an entity:     {summary['became_entity']}")
    print(f"  need neighbour data:  {summary['needs_neighbouring_blocks']}")
    print(f"  carry extra_blocks:   {summary['carries_extra_blocks']}")

    for label, rows in (
        ("hard failures", failures),
        ("passed through untranslated", passed_through),
        ("collapsed to air", collapsed_to_air),
        ("became an entity", became_entity),
    ):
        if not rows:
            continue
        print(f"\n{label}:")
        for row in sorted(rows, key=lambda r: -r["count"])[: args.top]:
            detail = row["error"] or row["java"] or ""
            print(f"  {row['count']:9,}  {row['universal']}  {detail}")

    if needs_neighbours:
        print("\nneed neighbouring blocks to be fully defined:")
        for row in sorted(needs_neighbours, key=lambda r: -r["count"])[: args.top]:
            print(f"  {row['count']:9,}  {row['universal']} -> {row['java']}")

    if with_extra_blocks:
        print("\ncarry extra_blocks (bedrock's second block layer):")
        for row in sorted(with_extra_blocks, key=lambda r: -r["count"])[: args.top]:
            print(f"  {row['count']:9,}  {row['universal']} + {row['extra_blocks']}")

    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
