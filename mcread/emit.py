"""Bake torch glow into a per-vertex emit channel.

Torch, lantern, glowstone, and lit redstone lamps. Neighbours pick up a
distance falloff; the emitter itself gets an extra self-glow. The browser
adds this on top of Lambert so night still reads.

``level`` is leftover vanilla metadata. We do not flood-fill with it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy

from mcread.blocks import format_property_value
from mcread.mesh import BakedMesh, BlockGrid, ChunkBake, _section_index, empty_mesh
from mcread.resolve import ResolvedBlock

SELF_GLOW = 0.9
SELF_RADIUS = 0.9
EMIT_CAP = 2.4

# name -> (rgb, strength, radius in blocks, block-light level 0-15)
EMITTERS: dict[str, tuple[tuple[float, float, float], float, float, int]] = {
    "torch": ((1.0, 0.72, 0.32), 1.2, 8.0, 14),
    "wall_torch": ((1.0, 0.72, 0.32), 1.2, 8.0, 14),
    "lantern": ((1.0, 0.78, 0.38), 1.35, 10.0, 15),
    "glowstone": ((1.0, 0.86, 0.52), 1.45, 11.0, 15),
    "redstone_lamp": ((1.0, 0.82, 0.45), 1.4, 11.0, 15),
}


@dataclass(frozen=True)
class Emitter:
    x: float
    y: float
    z: float
    color: tuple[float, float, float]
    strength: float
    radius: float
    level: int


def _is_lit(block) -> bool:
    raw = block.properties.get("lit")
    if raw is None:
        return True
    return format_property_value(raw).lower() in {"true", "1"}


def emitter_spec(
    entry: ResolvedBlock,
) -> tuple[tuple[float, float, float], float, float, int] | None:
    block = entry.java_block
    if block is None:
        return None
    spec = EMITTERS.get(block.base_name)
    if spec is None:
        return None
    if block.base_name == "redstone_lamp" and not _is_lit(block):
        return None
    return spec


def collect_emitters(
    grid: BlockGrid,
    *,
    min_y: int | None = None,
    max_y: int | None = None,
) -> list[Emitter]:
    found: list[Emitter] = []
    for cx, cz in grid.loaded_chunks():
        chunk = grid.chunk_at(cx, cz)
        resolved = grid.resolved_at(cx, cz)
        if chunk is None or resolved is None:
            continue
        for cy in chunk.blocks.sub_chunks:
            section_lo = cy * 16
            section_hi = section_lo + 15
            if min_y is not None and section_hi < min_y:
                continue
            if max_y is not None and section_lo > max_y:
                continue
            section = numpy.asarray(chunk.blocks.get_sub_chunk(cy))
            for dx in range(16):
                for dy in range(16):
                    for dz in range(16):
                        wy = section_lo + dy
                        if min_y is not None and wy < min_y:
                            continue
                        if max_y is not None and wy > max_y:
                            continue
                        index = _section_index(section, dx, dy, dz)
                        if index < 0 or index >= len(resolved):
                            continue
                        spec = emitter_spec(resolved[index])
                        if spec is None:
                            continue
                        color, strength, radius, level = spec
                        found.append(
                            Emitter(
                                x=cx * 16 + dx + 0.5,
                                y=wy + 0.5,
                                z=cz * 16 + dz + 0.5,
                                color=color,
                                strength=strength,
                                radius=radius,
                                level=level,
                            )
                        )
    return found


def apply_emit_to_mesh(mesh: BakedMesh, emitters: list[Emitter]) -> BakedMesh:
    if mesh.empty():
        return empty_mesh()
    emit = numpy.zeros((mesh.vertex_count, 3), dtype=numpy.float32)
    if emitters:
        positions = numpy.asarray(mesh.positions, dtype=numpy.float32).reshape(-1, 3)
        for lamp in emitters:
            delta = positions - numpy.array((lamp.x, lamp.y, lamp.z), dtype=numpy.float32)
            dist = numpy.sqrt(numpy.sum(delta * delta, axis=1))
            falloff = numpy.clip(1.0 - dist / lamp.radius, 0.0, 1.0)
            weight = falloff * falloff * lamp.strength
            emit += weight[:, None] * numpy.array(lamp.color, dtype=numpy.float32)
            nearby = dist < SELF_RADIUS
            if numpy.any(nearby):
                emit[nearby] += numpy.array(lamp.color, dtype=numpy.float32) * SELF_GLOW
        emit = numpy.clip(emit, 0.0, EMIT_CAP)
    return BakedMesh(
        positions=mesh.positions,
        uvs=mesh.uvs,
        colors=mesh.colors,
        indices=mesh.indices,
        emit=emit.astype(numpy.float32).ravel(),
        light=mesh.light,
    )


def apply_emit(bake: ChunkBake, emitters: list[Emitter]) -> ChunkBake:
    return ChunkBake(
        opaque=apply_emit_to_mesh(bake.opaque, emitters),
        translucent=apply_emit_to_mesh(bake.translucent, emitters),
        chunk=bake.chunk,
        origin=bake.origin,
        y_range=bake.y_range,
    )
