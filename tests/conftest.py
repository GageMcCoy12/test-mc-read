"""Fake chunks, so probe logic can be tested without opening a save."""

from __future__ import annotations

import numpy
import pytest
from amulet.api.block import Block


class FakePalette:
    """Stands in for amulet's BlockManager."""

    def __init__(self, blocks):
        self._blocks = tuple(blocks)

    def values(self):
        return self._blocks

    def __len__(self):
        return len(self._blocks)

    def __getitem__(self, index):
        return self._blocks[index]

    def __iter__(self):
        return iter(self._blocks)


class FakeBlocks:
    """Stands in for amulet's Blocks: palette indices per sub-chunk."""

    def __init__(self, sections: dict[int, numpy.ndarray]):
        self._sections = sections

    @property
    def sub_chunks(self):
        return set(self._sections)

    def get_sub_chunk(self, cy):
        return self._sections[cy]


class FakeBiomes:
    def __init__(self, sections: dict[int, numpy.ndarray] | None):
        self._sections = sections

    def to_raw(self):
        if self._sections is None:
            raise RuntimeError("no biome data")
        return ("shape", None, self._sections)


class FakeBlockEntity:
    def __init__(self, namespaced_name, x, y, z, nbt):
        self.namespaced_name = namespaced_name
        self.x = x
        self.y = y
        self.z = z
        self.nbt = nbt


class FakeChunk:
    def __init__(
        self,
        cx=0,
        cz=0,
        palette=(),
        sections=None,
        block_entities=(),
        entities=(),
        biome_palette=(),
        biome_sections=None,
        misc=None,
    ):
        self.cx = cx
        self.cz = cz
        self.block_palette = FakePalette(palette)
        self.blocks = FakeBlocks(sections or {})
        self.block_entities = list(block_entities)
        self.entities = list(entities)
        self.biome_palette = FakePalette(biome_palette)
        self.biomes = FakeBiomes(biome_sections)
        self.misc = misc or {}


def filled_section(value: int, shape=(16, 16, 16)) -> numpy.ndarray:
    return numpy.full(shape, value, dtype=numpy.uint32)


def section_from(counts: dict[int, int], size: int = 4096) -> numpy.ndarray:
    """A flat section where palette index i appears counts[i] times."""
    values: list[int] = []
    for index, count in counts.items():
        values.extend([index] * count)
    if len(values) > size:
        raise ValueError("counts exceed section size")
    values.extend([0] * (size - len(values)))
    return numpy.array(values, dtype=numpy.uint32)


@pytest.fixture
def stone():
    return Block("universal_minecraft", "stone")


@pytest.fixture
def air():
    return Block("universal_minecraft", "air")
