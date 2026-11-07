"""Compare the properties we actually see against the declared schema.

If observed properties always fall inside the schema, then shape families like
stairs, slabs and walls are data we can enumerate rather than special cases we
have to hand-write.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

from amulet.api.block import Block

from mcread.census import describe_properties


def normalise_spec_value(raw: object) -> str:
    """Spec values arrive JSON-encoded, e.g. '"north"' or 'true'."""
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw.strip('"')
        return str(decoded)
    return str(raw)


def spec_properties(spec: Optional[Mapping]) -> dict[str, list[str]]:
    if not spec:
        return {}
    raw = spec.get("properties") or {}
    return {
        name: [normalise_spec_value(value) for value in values]
        for name, values in raw.items()
    }


@dataclass
class BaseNameVocabulary:
    namespace: str
    base_name: str
    blockstate_count: int = 0
    observed: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    types: dict[str, str] = field(default_factory=dict)
    representative: Optional[Block] = None
    """Any one block with this name, for schema lookups."""

    @property
    def property_signature(self) -> tuple[str, ...]:
        return tuple(sorted(self.observed))

    def as_dict(self) -> dict:
        return {
            "namespace": self.namespace,
            "base_name": self.base_name,
            "blockstate_count": self.blockstate_count,
            "property_signature": list(self.property_signature),
            "observed_values": {
                name: sorted(values) for name, values in sorted(self.observed.items())
            },
            "property_types": dict(sorted(self.types.items())),
        }


@dataclass
class SpecComparison:
    """Mismatches in both directions between observation and schema."""

    base_name: str
    has_spec: bool
    properties_not_in_spec: list[str]
    values_not_in_spec: dict[str, list[str]]
    spec_properties_never_observed: list[str]
    spec_values_never_observed: dict[str, list[str]]

    @property
    def is_fully_covered(self) -> bool:
        return (
            self.has_spec
            and not self.properties_not_in_spec
            and not self.values_not_in_spec
        )

    def as_dict(self) -> dict:
        return {
            "base_name": self.base_name,
            "has_spec": self.has_spec,
            "fully_covered": self.is_fully_covered,
            "properties_not_in_spec": self.properties_not_in_spec,
            "values_not_in_spec": self.values_not_in_spec,
            "spec_properties_never_observed": self.spec_properties_never_observed,
            "spec_values_never_observed": self.spec_values_never_observed,
        }


class PropertyVocabulary:
    """Group blockstates by base name and collect their property domains."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], BaseNameVocabulary] = {}

    def add(self, block: Block) -> None:
        name = (block.namespace, block.base_name)
        entry = self._entries.get(name)
        if entry is None:
            entry = BaseNameVocabulary(
                block.namespace, block.base_name, representative=block
            )
            self._entries[name] = entry
        entry.blockstate_count += 1
        values, types = describe_properties(block)
        for prop, value in values.items():
            entry.observed[prop].add(value)
            entry.types.setdefault(prop, types[prop])

    def add_all(self, blocks: Iterable[Block]) -> None:
        for block in blocks:
            self.add(block)

    def records(self) -> list[BaseNameVocabulary]:
        return sorted(
            self._entries.values(),
            key=lambda entry: (-entry.blockstate_count, entry.base_name),
        )

    def shape_families(self) -> dict[tuple[str, ...], list[str]]:
        """Base names that share a property signature behave the same way."""
        families: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for entry in self.records():
            families[entry.property_signature].append(entry.base_name)
        return {
            signature: sorted(names)
            for signature, names in sorted(
                families.items(), key=lambda item: (-len(item[1]), item[0])
            )
        }


def compare_to_spec(
    entry: BaseNameVocabulary, spec: Optional[Mapping]
) -> SpecComparison:
    """`spec is None` means the version has never heard of this block. An empty
    spec is different: the block is known and simply has no properties."""
    if spec is None:
        return SpecComparison(
            base_name=entry.base_name,
            has_spec=False,
            properties_not_in_spec=sorted(entry.observed),
            values_not_in_spec={},
            spec_properties_never_observed=[],
            spec_values_never_observed={},
        )

    declared = spec_properties(spec)
    properties_not_in_spec = sorted(set(entry.observed) - set(declared))
    values_not_in_spec: dict[str, list[str]] = {}
    for prop, values in entry.observed.items():
        if prop not in declared:
            continue
        unexpected = sorted(values - set(declared[prop]))
        if unexpected:
            values_not_in_spec[prop] = unexpected

    never_observed_props = sorted(set(declared) - set(entry.observed))
    never_observed_values: dict[str, list[str]] = {}
    for prop, values in declared.items():
        if prop not in entry.observed:
            continue
        unused = sorted(set(values) - entry.observed[prop])
        if unused:
            never_observed_values[prop] = unused

    return SpecComparison(
        base_name=entry.base_name,
        has_spec=True,
        properties_not_in_spec=properties_not_in_spec,
        values_not_in_spec=values_not_in_spec,
        spec_properties_never_observed=never_observed_props,
        spec_values_never_observed=never_observed_values,
    )
