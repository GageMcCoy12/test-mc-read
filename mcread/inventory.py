"""Inventory everything in a chunk that is not a block.

Block models cover geometry, but the renderer will also need biomes for tinting
and block entity NBT for things Minecraft draws with entity models.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy

MAX_NBT_DEPTH = 3


def nbt_shape(tag: Any, depth: int = 0) -> Any:
    """Describe an NBT tag by structure and type, never by payload size."""
    compound = getattr(tag, "compound", None)
    if compound is None and hasattr(tag, "items") and not isinstance(tag, (str, bytes)):
        compound = tag
    if compound is not None and hasattr(compound, "items"):
        if depth >= MAX_NBT_DEPTH:
            return f"{type(tag).__name__}[...]"
        return {
            str(key): nbt_shape(value, depth + 1) for key, value in compound.items()
        }
    if isinstance(tag, (list, tuple)) or type(tag).__name__.endswith("ListTag"):
        try:
            items = list(tag)
        except TypeError:
            return type(tag).__name__
        if not items:
            return f"{type(tag).__name__}[empty]"
        if depth >= MAX_NBT_DEPTH:
            return f"{type(tag).__name__}[...]"
        return [nbt_shape(items[0], depth + 1), f"x{len(items)}"]
    return type(tag).__name__


@dataclass
class NonBlockInventory:
    """Accumulate non-block chunk data across a region."""

    chunks_scanned: int = 0
    block_entity_counts: Counter[str] = field(default_factory=Counter)
    block_entity_nbt_shapes: dict[str, Any] = field(default_factory=dict)
    block_entity_locations: dict[str, list[list[int]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    entity_counts: Counter[str] = field(default_factory=Counter)
    biome_counts: Counter[str] = field(default_factory=Counter)
    biome_shapes: Counter[str] = field(default_factory=Counter)
    misc_keys: Counter[str] = field(default_factory=Counter)
    sub_chunk_ids: Counter[int] = field(default_factory=Counter)
    chunk_y_extents: dict[str, list[int]] = field(default_factory=dict)

    def add_chunk(self, chunk) -> None:
        self.chunks_scanned += 1
        self._add_block_entities(chunk)
        self._add_entities(chunk)
        self._add_biomes(chunk)
        self._add_extent(chunk)
        for key in getattr(chunk, "misc", {}) or {}:
            self.misc_keys[str(key)] += 1

    def _add_block_entities(self, chunk) -> None:
        for entity in chunk.block_entities:
            name = entity.namespaced_name
            self.block_entity_counts[name] += 1
            if len(self.block_entity_locations[name]) < 3:
                self.block_entity_locations[name].append(
                    [int(entity.x), int(entity.y), int(entity.z)]
                )
            if name not in self.block_entity_nbt_shapes:
                self.block_entity_nbt_shapes[name] = nbt_shape(entity.nbt)

    def _add_entities(self, chunk) -> None:
        for entity in chunk.entities:
            self.entity_counts[getattr(entity, "namespaced_name", "unknown")] += 1

    def _add_biomes(self, chunk) -> None:
        palette = tuple(chunk.biome_palette.values())
        if not palette:
            return
        biomes = chunk.biomes
        self.biome_shapes[type(biomes).__name__] += 1
        try:
            _shape, _two_d, sections = biomes.to_raw()
        except Exception:
            for biome in palette:
                self.biome_counts[str(biome)] += 0
            return
        if not sections:
            return
        for array in sections.values():
            indices = numpy.asarray(array).ravel()
            counted = numpy.bincount(indices, minlength=len(palette))
            for index, total in enumerate(counted[: len(palette)].tolist()):
                if total:
                    self.biome_counts[str(palette[index])] += total

    def _add_extent(self, chunk) -> None:
        ids = sorted(chunk.blocks.sub_chunks)
        if not ids:
            return
        for cy in ids:
            self.sub_chunk_ids[cy] += 1
        self.chunk_y_extents[f"{chunk.cx},{chunk.cz}"] = [
            min(ids) * 16,
            max(ids) * 16 + 15,
        ]

    @property
    def world_y_extent(self) -> Optional[list[int]]:
        if not self.sub_chunk_ids:
            return None
        ids = sorted(self.sub_chunk_ids)
        return [ids[0] * 16, ids[-1] * 16 + 15]

    def as_dict(self) -> dict:
        return {
            "chunks_scanned": self.chunks_scanned,
            "world_y_extent": self.world_y_extent,
            "sub_chunk_ids": dict(sorted(self.sub_chunk_ids.items())),
            "block_entities": {
                "total": sum(self.block_entity_counts.values()),
                "distinct_types": len(self.block_entity_counts),
                "counts": dict(self.block_entity_counts.most_common()),
                "nbt_shapes": self.block_entity_nbt_shapes,
                "example_locations": {
                    name: locations
                    for name, locations in sorted(self.block_entity_locations.items())
                },
            },
            "entities": {
                "total": sum(self.entity_counts.values()),
                "counts": dict(self.entity_counts.most_common()),
            },
            "biomes": {
                "storage_classes": dict(self.biome_shapes),
                "distinct": len(self.biome_counts),
                "counts": dict(self.biome_counts.most_common()),
            },
            "misc_keys": dict(self.misc_keys.most_common()),
            "chunk_y_extents": self.chunk_y_extents,
        }
