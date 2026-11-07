from __future__ import annotations

from pathlib import Path

import numpy
import pytest
from amulet.api.block import Block
from amulet_nbt import StringTag

from mcread.blocks import is_fluid_block
from mcread.models import describe_block_mesh, java_model_manager
from mcread.resolve import PaletteResolver
from mcread.translate import JavaTranslator

SPIKE_BLOCK = Block(
    "universal_minecraft",
    "trapdoor",
    {
        "facing": StringTag("west"),
        "half": StringTag("bottom"),
        "material": StringTag("birch"),
        "open": StringTag("true"),
        "powered": StringTag("false"),
    },
)


@pytest.fixture(scope="module")
def resolver() -> PaletteResolver:
    return PaletteResolver()


def test_air_is_skipped(resolver: PaletteResolver):
    resolved = resolver.resolve(Block("universal_minecraft", "air"))
    assert resolved.skip
    assert resolved.is_empty
    assert resolved.mesh is None


def test_leaves_do_not_occlude(resolver: PaletteResolver):
    leaves = Block(
        "universal_minecraft",
        "leaves",
        {"material": StringTag("oak")},
    )
    resolved = resolver.resolve(leaves)
    assert not resolved.skip
    assert not resolved.is_opaque


def test_stone_is_opaque(resolver: PaletteResolver):
    resolved = resolver.resolve(Block("universal_minecraft", "stone"))
    assert not resolved.skip
    assert resolved.is_opaque
    assert resolved.mesh is not None
    assert resolved.mesh.verts


def test_fix_pack_is_stacked_last():
    manager = java_model_manager()
    assert Path(manager.pack_paths[-1]).name == "java_vanilla_fix"


def test_chest_uses_entity_model(resolver: PaletteResolver):
    chest = Block(
        "universal_minecraft",
        "chest",
        {
            "connection": StringTag("none"),
            "facing": StringTag("north"),
            "material": StringTag("wood"),
        },
    )
    resolved = resolver.resolve(chest)
    assert not resolved.skip
    assert resolved.mesh is not None
    names = {Path(path).name for path in resolved.mesh.textures}
    assert "normal.png" in names
    points = numpy.concatenate(
        [numpy.asarray(verts).reshape(-1, 3) for verts in resolved.mesh.verts.values()]
    )
    assert points[:, 0].min() > 0.0
    assert points[:, 0].max() < 1.0
    assert points.shape[0] > 24


def test_shulker_and_pot_use_pack_meshes(resolver: PaletteResolver):
    shulker = Block(
        "universal_minecraft",
        "shulker_box",
        {"color": StringTag("default"), "facing": StringTag("up")},
    )
    pot = Block(
        "universal_minecraft",
        "decorated_pot",
        {"cracked": StringTag("false"), "facing": StringTag("south")},
    )
    shulker_resolved = resolver.resolve(shulker)
    pot_resolved = resolver.resolve(pot)
    assert not shulker_resolved.skip
    assert not pot_resolved.skip
    assert shulker_resolved.mesh is not None
    assert pot_resolved.mesh is not None
    shulker_names = {Path(path).name for path in shulker_resolved.mesh.textures}
    pot_names = {Path(path).name for path in pot_resolved.mesh.textures}
    assert "shulker_box.png" in shulker_names
    assert "decorated_pot_side.png" in pot_names or "decorated_pot_base.png" in pot_names


def test_wall_banner_uses_entity_model(resolver: PaletteResolver):
    banner = Block(
        "universal_minecraft",
        "wall_banner",
        {"color": StringTag("green"), "facing": StringTag("north")},
    )
    resolved = resolver.resolve(banner)
    assert not resolved.skip
    assert resolved.mesh is not None
    names = {Path(path).name for path in resolved.mesh.textures}
    assert "banner_base.png" in names or "banner_green.png" in names


def test_water_gets_placeholder_cube(resolver: PaletteResolver):
    water = Block(
        "universal_minecraft",
        "water",
        {
            "falling": StringTag("false"),
            "flowing": StringTag("false"),
            "level": StringTag("0"),
        },
    )
    assert is_fluid_block(water)
    resolved = resolver.resolve(water)
    assert resolved.is_fluid
    assert not resolved.skip
    assert not resolved.is_opaque
    assert resolved.mesh is not None
    assert set(resolved.mesh.verts) >= {"up", "down", "north", "south", "east", "west"}


def test_palette_resolve_is_index_aligned(resolver: PaletteResolver):
    air = Block("universal_minecraft", "air")
    stone = Block("universal_minecraft", "stone")
    water = Block(
        "universal_minecraft",
        "water",
        {
            "falling": StringTag("false"),
            "flowing": StringTag("false"),
            "level": StringTag("0"),
        },
    )
    palette = resolver.resolve_palette((air, stone, water))
    assert palette[0].skip
    assert palette[1].is_opaque
    assert palette[2].is_fluid


def test_trapdoor_mesh_is_unit_triangles():
    """Lock the BlockMesh layout we bake against. Do not re-infer this."""
    translator = JavaTranslator()
    manager = java_model_manager()
    result = translator.translate(SPIKE_BLOCK)
    assert result.ok and result.block is not None
    mesh, summary = describe_block_mesh(manager, result.block)
    assert not summary.is_missing
    assert mesh.face_mode == 3
    for verts in mesh.verts.values():
        points = numpy.asarray(verts).reshape(-1, 3)
        assert points.min() >= -0.01
        assert points.max() <= 1.01
    for faces in mesh.faces.values():
        assert numpy.asarray(faces).size % 3 == 0
