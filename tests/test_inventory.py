from __future__ import annotations

import numpy
from amulet.api.block import Block
from amulet_nbt import ByteTag, CompoundTag, IntTag, ListTag, NamedTag, StringTag
from conftest import FakeBlockEntity, FakeChunk, filled_section

from mcread.inventory import NonBlockInventory, nbt_shape


def sign_nbt():
    return NamedTag(
        CompoundTag(
            {
                "utags": CompoundTag(
                    {
                        "front_text": CompoundTag({"bedrock_string": StringTag("hi")}),
                        "is_waxed": ByteTag(0),
                    }
                ),
                "BlockEntityVersion": IntTag(0),
            }
        )
    )


def test_nbt_shape_reports_types_not_values():
    shape = nbt_shape(sign_nbt())
    assert shape["BlockEntityVersion"] == "IntTag"
    assert shape["utags"]["is_waxed"] == "ByteTag"
    assert shape["utags"]["front_text"] == {"bedrock_string": "StringTag"}


def test_nbt_shape_summarises_lists_by_first_item_and_length():
    tag = NamedTag(
        CompoundTag(
            {
                "Items": ListTag(
                    [
                        CompoundTag({"Name": StringTag("stone")}),
                        CompoundTag({"Name": StringTag("dirt")}),
                    ]
                ),
                "Empty": ListTag([]),
            }
        )
    )
    shape = nbt_shape(tag)
    assert shape["Items"] == [{"Name": "StringTag"}, "x2"]
    assert shape["Empty"] == "ListTag[empty]"


def test_inventory_counts_block_entities_and_keeps_example_locations():
    chunk = FakeChunk(
        palette=(Block("universal_minecraft", "stone"),),
        sections={0: filled_section(0)},
        block_entities=[
            FakeBlockEntity("universal_minecraft:sign", 1, 2, 3, sign_nbt()),
            FakeBlockEntity("universal_minecraft:sign", 4, 5, 6, sign_nbt()),
            FakeBlockEntity("universal_minecraft:chest", 7, 8, 9, sign_nbt()),
        ],
    )

    inventory = NonBlockInventory()
    inventory.add_chunk(chunk)

    assert inventory.block_entity_counts["universal_minecraft:sign"] == 2
    assert inventory.block_entity_counts["universal_minecraft:chest"] == 1
    assert inventory.block_entity_locations["universal_minecraft:sign"] == [
        [1, 2, 3],
        [4, 5, 6],
    ]
    assert "universal_minecraft:sign" in inventory.block_entity_nbt_shapes


def test_inventory_caps_example_locations_at_three():
    entities = [
        FakeBlockEntity("universal_minecraft:sign", i, i, i, sign_nbt())
        for i in range(10)
    ]
    chunk = FakeChunk(
        palette=(Block("universal_minecraft", "stone"),),
        sections={0: filled_section(0)},
        block_entities=entities,
    )

    inventory = NonBlockInventory()
    inventory.add_chunk(chunk)

    assert len(inventory.block_entity_locations["universal_minecraft:sign"]) == 3
    assert inventory.block_entity_counts["universal_minecraft:sign"] == 10


def test_inventory_counts_biomes_from_the_palette_indices():
    chunk = FakeChunk(
        palette=(Block("universal_minecraft", "stone"),),
        sections={0: filled_section(0)},
        biome_palette=("universal_minecraft:plains", "universal_minecraft:taiga"),
        biome_sections={
            0: numpy.array([0, 0, 1, 1, 1], dtype=numpy.uint32),
        },
    )

    inventory = NonBlockInventory()
    inventory.add_chunk(chunk)

    assert inventory.biome_counts["universal_minecraft:plains"] == 2
    assert inventory.biome_counts["universal_minecraft:taiga"] == 3


def test_inventory_survives_chunks_with_no_biome_data():
    chunk = FakeChunk(
        palette=(Block("universal_minecraft", "stone"),),
        sections={0: filled_section(0)},
        biome_palette=("universal_minecraft:plains",),
        biome_sections=None,
    )

    inventory = NonBlockInventory()
    inventory.add_chunk(chunk)

    assert inventory.chunks_scanned == 1


def test_inventory_reports_y_extent_from_sub_chunk_ids():
    chunk = FakeChunk(
        cx=1,
        cz=2,
        palette=(Block("universal_minecraft", "stone"),),
        sections={-4: filled_section(0), 0: filled_section(0), 5: filled_section(0)},
    )

    inventory = NonBlockInventory()
    inventory.add_chunk(chunk)

    assert inventory.world_y_extent == [-64, 95]
    assert inventory.chunk_y_extents["1,2"] == [-64, 95]


def test_inventory_records_misc_keys_and_serialises():
    chunk = FakeChunk(
        palette=(Block("universal_minecraft", "stone"),),
        sections={0: filled_section(0)},
        misc={"bedrock_chunk_data": b"", "height": None},
    )

    inventory = NonBlockInventory()
    inventory.add_chunk(chunk)
    payload = inventory.as_dict()

    assert set(payload["misc_keys"]) == {"bedrock_chunk_data", "height"}
    assert payload["block_entities"]["total"] == 0
    assert payload["chunks_scanned"] == 1
