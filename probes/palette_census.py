"""Probe: how many distinct blockstates does this world actually contain?

Answers the "do we have to hardcode hundreds of variants" question with a real
number, by counting every palette entry in a region of the save.

Run: .venv/bin/python probes/palette_census.py --radius 4
"""

from __future__ import annotations

import argparse
from typing import Iterable

from _common import add_region_args, collect_census, world_version, write_report

TOP_N = 25


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_region_args(parser)
    parser.add_argument(
        "--top", type=int, default=TOP_N, help="how many rows to print"
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    census, scan = collect_census(args)
    records = census.records()
    summary = census.summary()

    payload = {
        "scan": scan,
        "world_last_opened_with_version": world_version(args.world),
        "summary": summary,
        "blockstates": [record.as_dict() for record in records],
    }
    path = write_report("palette_census", payload, args.output)

    print(
        f"scanned {summary['chunks_scanned']} chunks "
        f"({summary['sub_chunks_scanned']} sub-chunks, "
        f"{summary['blocks_counted']:,} blocks) in {scan['seconds']}s"
    )
    if scan["chunks_skipped"]:
        print(f"skipped {len(scan['chunks_skipped'])} chunk(s) with no data")
    print(
        f"distinct blockstates: {summary['distinct_blockstates']} "
        f"({summary['distinct_blockstates_excluding_air']} excluding air) "
        f"across {summary['distinct_base_names']} base names"
    )
    print(
        f"blockstates carrying extra_blocks: "
        f"{summary['blockstates_with_extra_blocks']}"
    )

    print(f"\ntop {args.top} by count:")
    for record in records[: args.top]:
        print(f"  {record.count:9,}  {record.key}")

    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
