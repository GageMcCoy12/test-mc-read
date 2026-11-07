"""Probe: are block properties data we can enumerate, or surprises?

Groups every observed blockstate by base name, collects each property's value
domain, and checks it against the declared schema in both directions. Also
groups base names by property signature, which is what a "shape family" is.

Run: .venv/bin/python probes/property_vocabulary.py --radius 4
"""

from __future__ import annotations

import argparse
from typing import Iterable

from _common import add_region_args, collect_census, write_report

from mcread.properties import PropertyVocabulary, compare_to_spec
from mcread.translate import specification_for, universal_version


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_region_args(parser)
    parser.add_argument("--top", type=int, default=12, help="how many rows to print")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    census, scan = collect_census(args)

    vocabulary = PropertyVocabulary()
    vocabulary.add_all(block for _key, block in census.iter_blocks())
    records = vocabulary.records()

    version = universal_version()
    comparisons = [
        compare_to_spec(
            entry,
            specification_for(version, entry.representative)
            if entry.representative is not None
            else None,
        )
        for entry in records
    ]

    no_spec = [c for c in comparisons if not c.has_spec]
    unexpected_props = [c for c in comparisons if c.properties_not_in_spec]
    unexpected_values = [c for c in comparisons if c.values_not_in_spec]
    families = vocabulary.shape_families()

    payload = {
        "scan": scan,
        "summary": {
            "base_names": len(records),
            "distinct_property_signatures": len(families),
            "base_names_without_spec": len(no_spec),
            "base_names_with_unexpected_properties": len(unexpected_props),
            "base_names_with_unexpected_values": len(unexpected_values),
            "fully_covered_base_names": len(
                [c for c in comparisons if c.is_fully_covered]
            ),
        },
        "shape_families": [
            {"property_signature": list(signature), "base_names": names}
            for signature, names in families.items()
        ],
        "base_names": [entry.as_dict() for entry in records],
        "spec_comparison": [c.as_dict() for c in comparisons],
    }
    path = write_report("property_vocabulary", payload, args.output)

    summary = payload["summary"]
    print(
        f"{summary['base_names']} base names, "
        f"{summary['distinct_property_signatures']} distinct property signatures"
    )
    print(f"fully covered by schema: {summary['fully_covered_base_names']}")
    print(f"no schema at all: {summary['base_names_without_spec']}")
    print(f"observed a property the schema lacks: {len(unexpected_props)}")
    print(f"observed a value the schema lacks: {len(unexpected_values)}")

    if unexpected_props or unexpected_values:
        print("\nmismatches (these would need real handling):")
        for comparison in (unexpected_props + unexpected_values)[: args.top]:
            print(
                f"  {comparison.base_name}: "
                f"props={comparison.properties_not_in_spec} "
                f"values={comparison.values_not_in_spec}"
            )
    if no_spec:
        print("\nbase names with no schema:")
        for comparison in no_spec[: args.top]:
            print(f"  {comparison.base_name}")

    print(f"\nlargest shape families (base names sharing a property signature):")
    for signature, names in list(families.items())[: args.top]:
        shown = ", ".join(names[:6])
        more = f" (+{len(names) - 6} more)" if len(names) > 6 else ""
        signature_text = ", ".join(signature) if signature else "<no properties>"
        print(f"  [{signature_text}] -> {len(names)}: {shown}{more}")

    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
