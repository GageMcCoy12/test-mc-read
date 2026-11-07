from __future__ import annotations

from amulet.api.block import Block
from amulet_nbt import StringTag
from conftest import FakeChunk, filled_section, section_from

from mcread.blocks import blockstate_key
from mcread.census import PaletteCensus, describe_properties


def test_blockstate_key_sorts_properties():
    block = Block(
        "universal_minecraft",
        "trapdoor",
        {"open": StringTag("true"), "facing": StringTag("west")},
    )
    assert blockstate_key(block) == (
        "universal_minecraft:trapdoor[facing=west,open=true]"
    )


def test_blockstate_key_omits_brackets_without_properties():
    assert blockstate_key(Block("universal_minecraft", "stone")) == (
        "universal_minecraft:stone"
    )


def test_census_counts_every_block_in_the_section():
    air = Block("universal_minecraft", "air")
    stone = Block("universal_minecraft", "stone")
    chunk = FakeChunk(
        cx=2,
        cz=3,
        palette=(air, stone),
        sections={0: section_from({1: 100})},
    )

    census = PaletteCensus()
    census.add_chunk(chunk)

    assert census.counts["universal_minecraft:stone"] == 100
    assert census.counts["universal_minecraft:air"] == 4096 - 100
    assert census.blocks_counted == 4096
    assert census.chunks_scanned == 1
    assert census.sub_chunks_scanned == 1


def test_census_skips_palette_entries_that_never_appear():
    air = Block("universal_minecraft", "air")
    stone = Block("universal_minecraft", "stone")
    unused = Block("universal_minecraft", "diamond_block")
    chunk = FakeChunk(palette=(air, stone, unused), sections={0: filled_section(1)})

    census = PaletteCensus()
    census.add_chunk(chunk)

    assert "universal_minecraft:diamond_block" not in census.counts
    assert census.counts["universal_minecraft:stone"] == 4096


def test_census_accumulates_across_chunks_and_tracks_chunk_counts():
    stone = Block("universal_minecraft", "stone")
    chunks = [
        FakeChunk(cx=cx, palette=(stone,), sections={0: filled_section(0)})
        for cx in range(3)
    ]

    census = PaletteCensus()
    census.add_chunks(chunks)

    assert census.counts["universal_minecraft:stone"] == 3 * 4096
    assert census.chunk_counts["universal_minecraft:stone"] == 3
    assert census.chunks_scanned == 3


def test_census_handles_empty_palette():
    census = PaletteCensus()
    census.add_chunk(FakeChunk(palette=(), sections={}))
    assert census.chunks_scanned == 0
    assert not census.counts


def test_records_flag_air_and_are_ordered_by_count():
    air = Block("universal_minecraft", "air")
    stone = Block("universal_minecraft", "stone")
    chunk = FakeChunk(palette=(air, stone), sections={0: section_from({1: 10})})

    census = PaletteCensus()
    census.add_chunk(chunk)
    records = census.records()

    assert [record.key for record in records][0] == "universal_minecraft:air"
    assert records[0].is_air is True
    assert records[1].is_air is False
    assert [r.key for r in census.records(include_air=False)] == [
        "universal_minecraft:stone"
    ]


def test_iter_blocks_excludes_air_by_default():
    air = Block("universal_minecraft", "air")
    stone = Block("universal_minecraft", "stone")
    chunk = FakeChunk(palette=(air, stone), sections={0: section_from({1: 10})})

    census = PaletteCensus()
    census.add_chunk(chunk)

    assert [key for key, _ in census.iter_blocks()] == ["universal_minecraft:stone"]
    assert len(list(census.iter_blocks(include_air=True))) == 2


def test_summary_counts_extra_blocks():
    water = Block("universal_minecraft", "water")
    seagrass = Block("universal_minecraft", "seagrass") + water
    chunk = FakeChunk(palette=(seagrass,), sections={0: filled_section(0)})

    census = PaletteCensus()
    census.add_chunk(chunk)
    summary = census.summary()

    assert summary["blockstates_with_extra_blocks"] == 1
    assert census.records()[0].extra_block_keys == ("universal_minecraft:water",)


def test_describe_properties_reports_values_and_tag_types():
    block = Block("universal_minecraft", "trapdoor", {"open": StringTag("true")})
    values, types = describe_properties(block)
    assert values == {"open": "true"}
    assert types == {"open": "StringTag"}
