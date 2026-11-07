from __future__ import annotations

from amulet.api.block import Block
from amulet_nbt import StringTag

from mcread.blocks import blockstate_key
from mcread.translate import JavaTranslator, newest_version, specification_for


def universal_trapdoor(material="birch"):
    return Block(
        "universal_minecraft",
        "trapdoor",
        {
            "facing": StringTag("west"),
            "half": StringTag("bottom"),
            "material": StringTag(material),
            "open": StringTag("true"),
            "powered": StringTag("false"),
        },
    )


def test_material_property_becomes_part_of_the_java_block_name():
    """The whole no-hardcoding claim rests on this: one universal `trapdoor`
    plus a `material` property becomes 21 distinct Java block names."""
    translator = JavaTranslator()

    birch = translator.translate(universal_trapdoor("birch"))
    spruce = translator.translate(universal_trapdoor("spruce"))

    assert birch.ok and spruce.ok
    assert birch.block.base_name == "birch_trapdoor"
    assert spruce.block.base_name == "spruce_trapdoor"
    assert "material" not in birch.block.properties


def test_translated_key_matches_the_resource_pack_variant_format():
    translator = JavaTranslator()
    result = translator.translate(universal_trapdoor())
    assert blockstate_key(result.block) == (
        "minecraft:birch_trapdoor[facing=west,half=bottom,open=true,powered=false]"
    )


def test_unknown_blocks_pass_through_instead_of_raising():
    """`from_universal` does not raise on an unknown block, it returns the input
    unchanged. Without the namespace check that silently becomes a missing
    texture, so this is the guard against the next Bedrock update."""
    translator = JavaTranslator()
    result = translator.translate(Block("universal_minecraft", "not_a_real_block"))

    assert result.passed_through is True
    assert result.ok is False
    assert result.error is not None
    assert result.block.namespace == "universal_minecraft"


def test_a_real_translation_is_not_flagged_as_passed_through():
    translator = JavaTranslator()
    result = translator.translate(universal_trapdoor())
    assert result.passed_through is False
    assert result.ok is True


def test_chests_report_that_they_need_neighbouring_blocks():
    translator = JavaTranslator()
    result = translator.translate(
        Block(
            "universal_minecraft",
            "chest",
            {
                "connection": StringTag("left"),
                "facing": StringTag("east"),
                "material": StringTag("wood"),
            },
        )
    )
    assert result.ok
    assert result.extra_needed is True


def test_specification_is_none_for_an_unknown_block():
    translator = JavaTranslator()
    assert specification_for(translator.version, Block("minecraft", "nope")) is None


def test_specification_is_present_but_empty_for_a_propertyless_block():
    translator = JavaTranslator()
    spec = specification_for(translator.version, Block("minecraft", "cobblestone"))
    assert spec is not None
    assert not spec.get("properties")


def test_stairs_specification_declares_the_shape_property():
    translator = JavaTranslator()
    spec = specification_for(translator.version, Block("minecraft", "oak_stairs"))
    assert set(spec["properties"]) == {"facing", "half", "shape"}


def test_newest_version_is_available_for_each_platform():
    assert newest_version("java") >= (1, 0, 0)
    assert newest_version("bedrock") >= (1, 0, 0)
