from __future__ import annotations

from random import Random

import pytest
from amulet.api.block import Block
from amulet_nbt import StringTag

from read_chunk import (
    DEFAULT_WORLD,
    block_to_chunk_coords,
    format_block_english,
    is_empty_block,
    patch_amulet_chunk_v42,
    sample_non_air_blocks,
)


def test_v42_patch_is_idempotent():
    patch_amulet_chunk_v42()
    patch_amulet_chunk_v42()
    from amulet.level.formats.leveldb_world.interface.chunk import get_interface

    assert get_interface(42) is not None
    assert block_to_chunk_coords(300, 70) == (18, 4)


def test_block_to_chunk_coords_floors_negatives():
    assert block_to_chunk_coords(-1, -17) == (-1, -2)


def test_air_and_empty_are_skipped():
    assert is_empty_block(Block("minecraft", "air"))
    assert is_empty_block(Block("minecraft", "cave_air"))
    assert is_empty_block(Block("minecraft", "void_air"))
    assert not is_empty_block(Block("minecraft", "stone"))


def test_english_text_includes_name_id_and_properties():
    block = Block("minecraft", "oak_log", {"axis": StringTag("y")})
    text = format_block_english(block)
    assert "oak log" in text
    assert "minecraft:oak_log" in text
    assert "axis=y" in text


class _FakeBlocks:
    def __init__(self, subchunks):
        self.sub_chunks = subchunks


class _FakeChunk:
    def __init__(self, cx, cz, blocks_by_pos, subchunks=(0,)):
        self.cx = cx
        self.cz = cz
        self.blocks = _FakeBlocks(subchunks)
        self._blocks_by_pos = blocks_by_pos

    def get_block(self, dx, y, dz):
        return self._blocks_by_pos.get((dx, y, dz), Block("minecraft", "air"))


def test_sample_skips_air_until_solid_blocks_are_found():
    stone = Block("minecraft", "stone")
    dirt = Block("minecraft", "dirt")
    chunk = _FakeChunk(
        18,
        4,
        {
            (0, 0, 0): Block("minecraft", "air"),
            (1, 0, 1): stone,
            (2, 0, 2): dirt,
            (3, 0, 3): stone,
        },
    )

    def get_block(dx, y, dz):
        if (dx, y, dz) in chunk._blocks_by_pos:
            return chunk._blocks_by_pos[(dx, y, dz)]
        return stone

    chunk.get_block = get_block

    samples = sample_non_air_blocks(chunk, 2, rng=Random(1))

    assert len(samples) == 2
    assert all(not is_empty_block(sample.block) for sample in samples)
    assert (0, 0, 0) not in {
        (sample.x - chunk.cx * 16, sample.y, sample.z - chunk.cz * 16)
        for sample in samples
    }
    assert all(sample.x // 16 == 18 and sample.z // 16 == 4 for sample in samples)


def test_sample_errors_when_chunk_is_only_air():
    chunk = _FakeChunk(0, 0, {})
    with pytest.raises(ValueError, match="only found 0"):
        sample_non_air_blocks(chunk, 1, rng=Random(0))


@pytest.mark.integration
def test_real_world_chunk_has_ten_non_air_blocks():
    pytest.importorskip("amulet")
    if not (DEFAULT_WORLD / "db").is_dir():
        pytest.skip("world/db is missing")

    from read_chunk import open_chunk

    with open_chunk(DEFAULT_WORLD, 18, 4, "minecraft:overworld") as chunk:
        samples = sample_non_air_blocks(chunk, 10, rng=Random(30070))
    assert len(samples) == 10
    assert all(not is_empty_block(sample.block) for sample in samples)
