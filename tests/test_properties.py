from __future__ import annotations

from amulet.api.block import Block
from amulet_nbt import StringTag

from mcread.properties import (
    PropertyVocabulary,
    compare_to_spec,
    normalise_spec_value,
    spec_properties,
)


def stairs(facing="north", half="bottom", shape="straight"):
    return Block(
        "universal_minecraft",
        "oak_stairs",
        {
            "facing": StringTag(facing),
            "half": StringTag(half),
            "shape": StringTag(shape),
        },
    )


STAIRS_SPEC = {
    "properties": {
        "facing": ['"north"', '"south"', '"west"', '"east"'],
        "half": ['"top"', '"bottom"'],
        "shape": ['"straight"', '"inner_left"'],
    },
    "defaults": {"facing": '"north"'},
}


def test_normalise_spec_value_strips_json_quoting():
    assert normalise_spec_value('"north"') == "north"
    assert normalise_spec_value("true") == "True"
    assert normalise_spec_value('"7"') == "7"


def test_spec_properties_normalises_every_value():
    assert spec_properties(STAIRS_SPEC)["half"] == ["top", "bottom"]


def test_spec_properties_tolerates_missing_spec():
    assert spec_properties(None) == {}
    assert spec_properties({}) == {}


def test_vocabulary_collects_value_domains_per_base_name():
    vocabulary = PropertyVocabulary()
    vocabulary.add(stairs(facing="north"))
    vocabulary.add(stairs(facing="south"))
    vocabulary.add(stairs(facing="south", half="top"))

    record = vocabulary.records()[0]
    assert record.base_name == "oak_stairs"
    assert record.blockstate_count == 3
    assert record.observed["facing"] == {"north", "south"}
    assert record.observed["half"] == {"bottom", "top"}
    assert record.property_signature == ("facing", "half", "shape")
    assert record.representative is not None


def test_shape_families_group_base_names_by_signature():
    vocabulary = PropertyVocabulary()
    vocabulary.add(stairs())
    vocabulary.add(
        Block("universal_minecraft", "birch_stairs", {"facing": StringTag("north")})
    )
    vocabulary.add(
        Block("universal_minecraft", "ladder", {"facing": StringTag("north")})
    )

    families = vocabulary.shape_families()
    assert families[("facing",)] == ["birch_stairs", "ladder"]
    assert families[("facing", "half", "shape")] == ["oak_stairs"]


def test_comparison_is_clean_when_observation_fits_the_spec():
    vocabulary = PropertyVocabulary()
    vocabulary.add(stairs())
    comparison = compare_to_spec(vocabulary.records()[0], STAIRS_SPEC)

    assert comparison.has_spec is True
    assert comparison.is_fully_covered is True
    assert comparison.properties_not_in_spec == []
    assert comparison.values_not_in_spec == {}
    assert comparison.spec_values_never_observed["facing"] == [
        "east",
        "south",
        "west",
    ]


def test_comparison_flags_values_the_spec_does_not_declare():
    vocabulary = PropertyVocabulary()
    vocabulary.add(stairs(shape="outer_left"))
    comparison = compare_to_spec(vocabulary.records()[0], STAIRS_SPEC)

    assert comparison.is_fully_covered is False
    assert comparison.values_not_in_spec == {"shape": ["outer_left"]}


def test_comparison_flags_properties_the_spec_does_not_declare():
    vocabulary = PropertyVocabulary()
    vocabulary.add(
        Block(
            "universal_minecraft",
            "oak_stairs",
            {"facing": StringTag("north"), "waterlogged": StringTag("true")},
        )
    )
    comparison = compare_to_spec(vocabulary.records()[0], STAIRS_SPEC)

    assert comparison.properties_not_in_spec == ["waterlogged"]
    assert comparison.is_fully_covered is False


def test_empty_spec_means_known_block_with_no_properties():
    """An empty spec is not a missing spec: propertyless blocks return {}."""
    vocabulary = PropertyVocabulary()
    vocabulary.add(Block("universal_minecraft", "calcite"))
    comparison = compare_to_spec(vocabulary.records()[0], {})

    assert comparison.has_spec is True
    assert comparison.is_fully_covered is True


def test_missing_spec_is_reported_separately_from_empty_spec():
    vocabulary = PropertyVocabulary()
    vocabulary.add(Block("universal_minecraft", "made_up_block"))
    comparison = compare_to_spec(vocabulary.records()[0], None)

    assert comparison.has_spec is False
    assert comparison.is_fully_covered is False
