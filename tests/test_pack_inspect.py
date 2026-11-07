from __future__ import annotations

import json
from pathlib import Path

from mcread.pack_inspect import (
    blockstate_json,
    geometry_source,
    model_chain,
    referenced_models,
    split_identifier,
)


def write_asset(root: Path, relative: str, payload: dict) -> None:
    path = root / "assets" / "minecraft" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_split_identifier_defaults_to_minecraft():
    assert split_identifier("minecraft:block/stone") == ("minecraft", "block/stone")
    assert split_identifier("block/stone") == ("minecraft", "block/stone")


def test_referenced_models_reads_variants():
    blockstate = {
        "variants": {
            "facing=east": {"model": "minecraft:block/a", "y": 90},
            "facing=north": {"model": "minecraft:block/a"},
            "facing=south": {"model": "minecraft:block/b"},
        }
    }
    assert referenced_models(blockstate) == ["minecraft:block/a", "minecraft:block/b"]


def test_referenced_models_reads_multipart_and_weighted_variants():
    blockstate = {
        "multipart": [
            {"apply": {"model": "minecraft:block/post"}},
            {
                "when": {"north": "true"},
                "apply": [
                    {"model": "minecraft:block/side", "weight": 1},
                    {"model": "minecraft:block/side_alt"},
                ],
            },
        ]
    }
    assert referenced_models(blockstate) == [
        "minecraft:block/post",
        "minecraft:block/side",
        "minecraft:block/side_alt",
    ]


def test_referenced_models_tolerates_missing_blockstate():
    assert referenced_models(None) == []
    assert referenced_models({}) == []


def test_model_chain_follows_parents(tmp_path):
    write_asset(tmp_path, "models/block/child.json", {"parent": "block/middle"})
    write_asset(tmp_path, "models/block/middle.json", {"parent": "block/root"})
    write_asset(tmp_path, "models/block/root.json", {"elements": [{"from": [0, 0, 0]}]})

    chain = model_chain([tmp_path], "minecraft:block/child")

    assert [identifier for identifier, _ in chain] == [
        "minecraft:block/child",
        "block/middle",
        "block/root",
    ]


def test_model_chain_stops_on_a_parent_cycle(tmp_path):
    write_asset(tmp_path, "models/block/a.json", {"parent": "block/b"})
    write_asset(tmp_path, "models/block/b.json", {"parent": "block/a"})

    chain = model_chain([tmp_path], "block/a")

    assert len(chain) == 2


def test_geometry_source_finds_elements_inherited_from_a_parent(tmp_path):
    write_asset(
        tmp_path,
        "blockstates/thing.json",
        {"variants": {"": {"model": "minecraft:block/thing"}}},
    )
    write_asset(tmp_path, "models/block/thing.json", {"parent": "block/cube_all"})
    write_asset(
        tmp_path,
        "models/block/cube_all.json",
        {"elements": [{"faces": {"up": {"texture": "#all"}}}]},
    )

    source = geometry_source([tmp_path], "minecraft", "thing")

    assert source.blockstate_found is True
    assert source.has_geometry is True
    assert source.element_source == "block/cube_all"
    assert source.has_tintindex is False


def test_geometry_source_reports_no_geometry_for_an_empty_model(tmp_path):
    """This is the water/chest case: a real model file with no elements."""
    write_asset(
        tmp_path,
        "blockstates/fluid.json",
        {"variants": {"": {"model": "minecraft:block/fluid"}}},
    )
    write_asset(
        tmp_path, "models/block/fluid.json", {"textures": {"particle": "block/water"}}
    )

    source = geometry_source([tmp_path], "minecraft", "fluid")

    assert source.blockstate_found is True
    assert source.models == ("minecraft:block/fluid",)
    assert source.has_geometry is False
    assert source.element_source is None
    assert source.particle == "block/water"


def test_geometry_source_detects_tintindex(tmp_path):
    write_asset(
        tmp_path,
        "blockstates/leaves.json",
        {"variants": {"": {"model": "minecraft:block/leaves"}}},
    )
    write_asset(
        tmp_path,
        "models/block/leaves.json",
        {"elements": [{"faces": {"up": {"texture": "#all", "tintindex": 0}}}]},
    )

    source = geometry_source([tmp_path], "minecraft", "leaves")

    assert source.has_geometry is True
    assert source.has_tintindex is True


def test_geometry_source_handles_a_block_with_no_blockstate_file(tmp_path):
    source = geometry_source([tmp_path], "minecraft", "nope")
    assert source.blockstate_found is False
    assert source.has_geometry is False


def test_later_packs_override_earlier_ones(tmp_path):
    base = tmp_path / "base"
    override = tmp_path / "override"
    write_asset(base, "blockstates/x.json", {"variants": {"": {"model": "block/base"}}})
    write_asset(
        override, "blockstates/x.json", {"variants": {"": {"model": "block/override"}}}
    )

    blockstate = blockstate_json([base, override], "minecraft", "x")

    assert referenced_models(blockstate) == ["block/override"]
