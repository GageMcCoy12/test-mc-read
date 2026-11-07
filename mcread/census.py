"""Count every distinct blockstate in a set of chunks.

Reads each chunk's palette and sub-chunk index arrays, so the result is an
exhaustive census rather than a random sample.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Mapping

import numpy
from amulet.api.block import Block

from mcread.blocks import blockstate_key, format_property_value, is_empty_block


@dataclass(frozen=True)
class BlockstateRecord:
    key: str
    namespace: str
    base_name: str
    properties: Mapping[str, str]
    property_types: Mapping[str, str]
    count: int
    chunk_count: int
    is_air: bool
    extra_block_keys: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "namespace": self.namespace,
            "base_name": self.base_name,
            "properties": dict(self.properties),
            "property_types": dict(self.property_types),
            "count": self.count,
            "chunk_count": self.chunk_count,
            "is_air": self.is_air,
            "extra_block_keys": list(self.extra_block_keys),
        }


def describe_properties(block: Block) -> tuple[dict[str, str], dict[str, str]]:
    values = {
        name: format_property_value(value)
        for name, value in sorted(block.properties.items())
    }
    types = {
        name: type(value).__name__ for name, value in sorted(block.properties.items())
    }
    return values, types


@dataclass
class PaletteCensus:
    """Accumulate blockstate counts across many chunks."""

    counts: Counter[str] = field(default_factory=Counter)
    chunk_counts: Counter[str] = field(default_factory=Counter)
    blocks: dict[str, Block] = field(default_factory=dict)
    chunks_scanned: int = 0
    sub_chunks_scanned: int = 0
    blocks_counted: int = 0

    def add_chunk(self, chunk) -> None:
        palette: tuple[Block, ...] = tuple(chunk.block_palette.values())
        if not palette:
            return

        totals = numpy.zeros(len(palette), dtype=numpy.int64)
        sub_chunk_ids = sorted(chunk.blocks.sub_chunks)
        for cy in sub_chunk_ids:
            indices = numpy.asarray(chunk.blocks.get_sub_chunk(cy)).ravel()
            counted = numpy.bincount(indices, minlength=len(palette))
            totals += counted[: len(palette)]

        self.chunks_scanned += 1
        self.sub_chunks_scanned += len(sub_chunk_ids)
        self.blocks_counted += int(totals.sum())

        for index, total in enumerate(totals.tolist()):
            if total <= 0:
                continue
            block = palette[index]
            key = blockstate_key(block)
            self.counts[key] += total
            self.chunk_counts[key] += 1
            self.blocks.setdefault(key, block)

    def add_chunks(self, chunks: Iterable) -> None:
        for chunk in chunks:
            self.add_chunk(chunk)

    def records(self, *, include_air: bool = True) -> list[BlockstateRecord]:
        out: list[BlockstateRecord] = []
        for key, count in self.counts.most_common():
            block = self.blocks[key]
            air = is_empty_block(block)
            if air and not include_air:
                continue
            values, types = describe_properties(block)
            out.append(
                BlockstateRecord(
                    key=key,
                    namespace=block.namespace,
                    base_name=block.base_name,
                    properties=values,
                    property_types=types,
                    count=count,
                    chunk_count=self.chunk_counts[key],
                    is_air=air,
                    extra_block_keys=tuple(
                        blockstate_key(extra) for extra in block.extra_blocks
                    ),
                )
            )
        return out

    def iter_blocks(self, *, include_air: bool = False) -> Iterator[tuple[str, Block]]:
        """Distinct blocks, most common first."""
        for key, _count in self.counts.most_common():
            block = self.blocks[key]
            if not include_air and is_empty_block(block):
                continue
            yield key, block

    def summary(self) -> dict:
        records = self.records()
        non_air = [r for r in records if not r.is_air]
        return {
            "chunks_scanned": self.chunks_scanned,
            "sub_chunks_scanned": self.sub_chunks_scanned,
            "blocks_counted": self.blocks_counted,
            "distinct_blockstates": len(records),
            "distinct_blockstates_excluding_air": len(non_air),
            "distinct_base_names": len({r.base_name for r in non_air}),
            "blockstates_with_extra_blocks": len(
                [r for r in non_air if r.extra_block_keys]
            ),
        }
