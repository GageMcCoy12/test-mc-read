from __future__ import annotations

import numpy
import pytest
from amulet.api.block import Block
from amulet_nbt import StringTag
from minecraft_model_reader.api.mesh.block.block_mesh import Transparency
from minecraft_model_reader.api.mesh.block.cube import get_unit_cube

from conftest import FakeChunk
from mcread.light import (
    FACE_SHADE,
    apply_light,
    compute_light_field,
    encode_light,
    face_shade_from_normal,
    light_emission,
    sample_face_vertex,
)
from mcread.mesh import BakedMesh, BlockGrid, ChunkBake, IdentityAtlas, mesh_chunk
from mcread.resolve import SKIP_EMPTY, ResolvedBlock


def _entry(
    name: str | None,
    *,
    opaque: bool = False,
    fluid: bool = False,
    properties: dict | None = None,
    mesh=None,
) -> ResolvedBlock:
    block = None if name is None else Block("minecraft", name, properties or {})
    return ResolvedBlock(
        java_block=block,
        mesh=mesh,
        is_opaque=opaque,
        transparency=Transparency.FullOpaque if opaque else Transparency.Partial,
        is_fluid=fluid,
        is_missing=False,
        is_empty=name is None,
        extra_needed=False,
        skip=name is None,
    )


def _cube(name: str, *, opaque: bool, fluid: bool = False) -> ResolvedBlock:
    texture = f"{name}.png"
    mode = Transparency.FullOpaque if opaque else Transparency.FullTranslucent
    mesh = get_unit_cube(texture, texture, texture, texture, texture, texture, mode)
    return _entry(name, opaque=opaque, fluid=fluid, mesh=mesh)


def _grid(section: numpy.ndarray, resolved: list[ResolvedBlock], *, cx: int = 0, cz: int = 0) -> BlockGrid:
    chunk = FakeChunk(cx=cx, cz=cz, sections={0: section})
    grid = BlockGrid()
    grid.add_chunk(chunk, resolved, visible=True)
    return grid


def _air_section() -> numpy.ndarray:
    return numpy.zeros((16, 16, 16), dtype=numpy.uint32)


def test_emission_table_covers_more_than_five_names():
    assert light_emission(_entry("torch")) == 14
    assert light_emission(_entry("glowstone")) == 15
    assert light_emission(_entry("lava")) == 15
    assert light_emission(_entry("fire")) == 15
    assert light_emission(_entry("sea_lantern")) == 15
    assert light_emission(_entry("soul_lantern")) == 10
    assert light_emission(_entry("jack_o_lantern")) == 15
    assert light_emission(_entry("end_rod")) == 14
    assert light_emission(_entry("magma_block")) == 3
    assert light_emission(_entry("stone")) == 0


def test_emission_respects_lit_and_pickle_state():
    assert (
        light_emission(_entry("redstone_lamp", properties={"lit": StringTag("true")})) == 15
    )
    assert light_emission(_entry("redstone_lamp", properties={"lit": StringTag("false")})) == 0
    assert light_emission(_entry("furnace", properties={"lit": StringTag("true")})) == 13
    assert (
        light_emission(
            _entry(
                "sea_pickle",
                properties={"waterlogged": StringTag("true"), "pickles": StringTag("4")},
            )
        )
        == 15
    )
    assert (
        light_emission(
            _entry(
                "sea_pickle",
                properties={"waterlogged": StringTag("false"), "pickles": StringTag("4")},
            )
        )
        == 0
    )
    assert light_emission(_entry("candle", properties={"lit": StringTag("true"), "candles": StringTag("3")})) == 9


def test_face_shade_matches_vanilla_cardinal_faces():
    assert face_shade_from_normal(0, 1, 0) == FACE_SHADE["up"]
    assert face_shade_from_normal(0, -1, 0) == FACE_SHADE["down"]
    assert face_shade_from_normal(0, 0, 1) == FACE_SHADE["south"]
    assert face_shade_from_normal(0, 0, -1) == FACE_SHADE["north"]
    assert face_shade_from_normal(1, 0, 0) == FACE_SHADE["east"]
    assert face_shade_from_normal(-1, 0, 0) == FACE_SHADE["west"]


def test_encode_light_hits_texel_centers():
    assert encode_light(0, 15) == (0.5 / 16.0, 15.5 / 16.0)
    assert encode_light(14, 0) == (14.5 / 16.0, 0.5 / 16.0)


def test_torch_floods_six_connected_and_stops_at_stone():
    section = _air_section()
    section[4, 4, 4] = 1
    section[6, 4, 4] = 2
    grid = _grid(section, [SKIP_EMPTY, _entry("torch"), _entry("stone", opaque=True)])
    field = compute_light_field(grid)
    assert field.levels_at(4, 4, 4)[0] == 14
    assert field.levels_at(5, 4, 4)[0] == 13
    assert field.levels_at(4, 5, 4)[0] == 13
    assert field.levels_at(6, 4, 4)[0] == 0
    assert field.levels_at(7, 4, 4)[0] == 9


def test_water_drops_three_instead_of_one():
    section = _air_section()
    section[2, 2, 2] = 1
    section[3, 2, 2] = 2
    section[4, 2, 2] = 2
    grid = _grid(
        section,
        [
            SKIP_EMPTY,
            _entry("torch"),
            _entry("water", fluid=True),
        ],
    )
    field = compute_light_field(grid)
    assert field.levels_at(2, 2, 2)[0] == 14
    assert field.levels_at(3, 2, 2)[0] == 11
    assert field.levels_at(4, 2, 2)[0] == 8


def test_sky_stays_15_falling_through_air_and_drops_sideways():
    section = _air_section()
    for x in range(16):
        for z in range(16):
            section[x, 2, z] = 1
    section[8, 2, 8] = 0
    grid = _grid(section, [SKIP_EMPTY, _entry("stone", opaque=True)])
    field = compute_light_field(grid)
    assert field.levels_at(8, 8, 8)[1] == 15
    assert field.levels_at(8, 1, 8)[1] == 15
    assert field.levels_at(7, 1, 8)[1] == 14
    assert field.levels_at(8, 2, 8)[1] == 15
    assert field.levels_at(7, 2, 8)[1] == 0


def test_sky_pays_water_opacity():
    section = _air_section()
    section[:, 4, :] = 1
    grid = _grid(section, [SKIP_EMPTY, _entry("water", fluid=True)])
    field = compute_light_field(grid)
    assert field.levels_at(8, 5, 8)[1] == 15
    assert field.levels_at(8, 4, 8)[1] == 12
    assert field.levels_at(8, 3, 8)[1] == 11


def test_hidden_halo_chunk_blocks_sky_and_feeds_torch_light():
    neighbor_section = _air_section()
    neighbor_section[0, 4, 4] = 1
    neighbor_section[0, 8, 4] = 2
    visible = FakeChunk(cx=0, cz=0, sections={0: _air_section()})
    halo = FakeChunk(cx=1, cz=0, sections={0: neighbor_section})
    grid = BlockGrid()
    grid.add_chunk(visible, [SKIP_EMPTY], visible=True)
    grid.add_chunk(
        halo,
        [SKIP_EMPTY, _entry("torch"), _entry("stone", opaque=True)],
        visible=False,
    )
    field = compute_light_field(grid)
    assert field.levels_at(16, 4, 4)[0] == 14
    assert field.levels_at(15, 4, 4)[0] == 13
    assert field.is_opaque(16, 8, 4)
    assert field.levels_at(16, 8, 4)[1] == 0


def test_four_tap_averages_lit_side_not_max_of_eight():
    field = compute_light_field(_grid(_air_section(), [SKIP_EMPTY]))
    field.sky[:] = 0
    ox, oy, oz = field.origin
    field.block[3 - ox, 3 - oy, 3 - oz] = 12
    field.block[3 - ox, 4 - oy, 3 - oz] = 4
    field.block[3 - ox, 3 - oy, 4 - oz] = 4
    field.block[3 - ox, 4 - oy, 4 - oz] = 4
    block, sky, ao = sample_face_vertex(field, 3.0, 4.0, 4.0, (1.0, 0.0, 0.0))
    assert block == 6.0
    assert sky == 0.0
    assert ao == 1.0


def test_ao_darkens_corners_but_never_hits_zero():
    field = compute_light_field(_grid(_air_section(), [SKIP_EMPTY]))
    ox, oy, oz = field.origin
    field.opaque[3 - ox, 4 - oy, 3 - oz] = True
    field.opaque[3 - ox, 3 - oy, 4 - oz] = True
    field.opaque[3 - ox, 4 - oy, 4 - oz] = True
    _block, _sky, ao = sample_face_vertex(field, 3.0, 4.0, 4.0, (1.0, 0.0, 0.0))
    assert ao == pytest.approx(0.4)
    assert ao >= 0.2


def test_apply_light_writes_uvs_and_keeps_emit():
    section = _air_section()
    section[2, 2, 2] = 1
    section[4, 2, 2] = 2
    grid = _grid(
        section,
        [SKIP_EMPTY, _cube("stone", opaque=True), _cube("glowstone", opaque=True)],
    )
    bake = mesh_chunk(grid, 0, 0, IdentityAtlas())
    lit = apply_light(bake, compute_light_field(grid))
    light = lit.opaque.light.reshape(-1, 2)
    assert light.shape[0] == lit.opaque.vertex_count
    assert float(light[:, 0].max()) > 0.5 / 16.0
    assert lit.opaque.emit.size == lit.opaque.vertex_count * 3


def test_apply_light_ao_multiplies_vertex_color():
    positions = numpy.array(
        [
            1.0, 0.0, 0.0,
            1.0, 1.0, 0.0,
            1.0, 1.0, 1.0,
            1.0, 0.0, 1.0,
        ],
        dtype=numpy.float32,
    )
    mesh = BakedMesh(
        positions=positions,
        uvs=numpy.zeros(8, dtype=numpy.float32),
        colors=numpy.ones(12, dtype=numpy.float32),
        indices=numpy.array([0, 1, 2, 0, 2, 3], dtype=numpy.uint32),
        emit=numpy.zeros(12, dtype=numpy.float32),
    )
    section = _air_section()
    section[1, 1, 0] = 1
    section[1, 0, 1] = 1
    grid = _grid(section, [SKIP_EMPTY, _entry("stone", opaque=True)])
    lit = apply_light(
        ChunkBake(mesh, mesh, (0, 0), (0, 0, 0), (0, 15)),
        compute_light_field(grid),
    )
    colors = lit.opaque.colors.reshape(-1, 3)
    assert float(colors.min()) < 1.0
    assert float(colors.min()) >= 0.2
