from __future__ import annotations

import numpy
from amulet.api.block import Block
from amulet_nbt import StringTag
from minecraft_model_reader.api.mesh.block.block_mesh import Transparency

from mcread.emit import Emitter, apply_emit_to_mesh, emitter_spec
from mcread.mesh import BakedMesh
from mcread.resolve import ResolvedBlock


def _entry(name: str | None, *, properties: dict | None = None) -> ResolvedBlock:
    block = None if name is None else Block("minecraft", name, properties or {})
    return ResolvedBlock(
        java_block=block,
        mesh=None,
        is_opaque=False,
        transparency=Transparency.Partial,
        is_fluid=False,
        is_missing=False,
        is_empty=False,
        extra_needed=False,
        skip=False,
    )


def test_only_known_emitters_glow():
    assert emitter_spec(_entry("torch")) is not None
    assert emitter_spec(_entry("wall_torch")) is not None
    assert emitter_spec(_entry("lantern")) is not None
    assert emitter_spec(_entry("glowstone")) is not None
    assert emitter_spec(_entry("redstone_lamp", properties={"lit": StringTag("true")})) is not None
    assert emitter_spec(_entry("redstone_lamp", properties={"lit": StringTag("false")})) is None
    assert emitter_spec(_entry("stone")) is None
    assert emitter_spec(_entry("soul_lantern")) is None
    assert emitter_spec(_entry(None)) is None


def test_emitter_levels_match_vanilla():
    assert emitter_spec(_entry("torch"))[3] == 14
    assert emitter_spec(_entry("wall_torch"))[3] == 14
    assert emitter_spec(_entry("lantern"))[3] == 15
    assert emitter_spec(_entry("glowstone"))[3] == 15
    assert emitter_spec(_entry("redstone_lamp", properties={"lit": StringTag("true")}))[3] == 15


def test_nearby_vertex_picks_up_torch_light():
    mesh = BakedMesh(
        positions=numpy.array([0.5, 0.5, 0.5, 8.0, 0.5, 0.5], dtype=numpy.float32),
        uvs=numpy.zeros(4, dtype=numpy.float32),
        colors=numpy.ones(6, dtype=numpy.float32),
        indices=numpy.array([0, 1, 0], dtype=numpy.uint32),
    )
    lit = apply_emit_to_mesh(
        mesh,
        [Emitter(0.5, 0.5, 0.5, (1.0, 0.7, 0.3), 1.2, 8.0, 14)],
    )
    emit = lit.emit.reshape(-1, 3)
    assert emit[0].sum() > emit[1].sum()
    assert emit[0, 0] > 1.0
    assert emit[1].sum() > 0.0
