"""Block + sky flood fill → per-vertex lightmap UVs.

6-connected. Block light starts from the full vanilla emitter table. Sky
is 15 in open columns and does not drop going down through air. Water
takes an extra opacity hit. Opaque cells (``ResolvedBlock.is_opaque`` /
``mesh_occludes``) stop the flood and cast AO.

Verts sit on walls. Each vertex averages the 4 cells on the *lit* side of
the face, then AO from how many of those neighbours occlude. AO never
hits zero.

``light`` UVs are ``(block+0.5)/16, (sky+0.5)/16``. Face shade is applied
in the viewer from the geometric normal, not here — ``now`` already has
Lambert and must stay flippable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy

from mcread.blocks import format_property_value
from mcread.mesh import BakedMesh, BlockGrid, ChunkBake, _section_index
from mcread.resolve import ResolvedBlock

WATER_OPACITY = 3
AO_STEP = 0.2
AO_FLOOR = 0.2
FACE_SHADE = {
    "up": 1.0,
    "down": 0.5,
    "north": 0.8,
    "south": 0.8,
    "east": 0.6,
    "west": 0.6,
}

# Vanilla Java block-light levels for blocks that do not need extra state.
# Property-gated names (lit / candles / pickles / berries / charges) live
# in ``light_emission`` so a dark furnace does not seed the flood.
LIGHT_LEVELS: dict[str, int] = {
    "beacon": 15,
    "conduit": 15,
    "end_gateway": 15,
    "end_portal": 15,
    "fire": 15,
    "glowstone": 15,
    "jack_o_lantern": 15,
    "lantern": 15,
    "lava": 15,
    "lava_cauldron": 15,
    "flowing_lava": 15,
    "sea_lantern": 15,
    "shroomlight": 15,
    "ochre_froglight": 15,
    "verdant_froglight": 15,
    "pearlescent_froglight": 15,
    "torch": 14,
    "wall_torch": 14,
    "end_rod": 14,
    "torchflower": 14,
    "nether_portal": 11,
    "crying_obsidian": 10,
    "soul_lantern": 10,
    "soul_torch": 10,
    "soul_wall_torch": 10,
    "soul_fire": 10,
    "enchanting_table": 7,
    "ender_chest": 7,
    "glow_lichen": 7,
    "magma_block": 3,
    "sculk_catalyst": 6,
    "amethyst_cluster": 5,
    "large_amethyst_bud": 4,
    "medium_amethyst_bud": 2,
    "small_amethyst_bud": 1,
    "brewing_stand": 1,
    "brown_mushroom": 1,
    "dragon_egg": 1,
    "end_portal_frame": 1,
    "sculk": 1,
    "lit_redstone_lamp": 15,
    "lit_furnace": 13,
    "lit_blast_furnace": 13,
    "lit_smoker": 13,
    "lit_redstone_torch": 7,
    "unlit_redstone_torch": 0,
}

_LIT_ALWAYS = frozenset(
    {
        "redstone_lamp",
        "furnace",
        "blast_furnace",
        "smoker",
        "campfire",
        "soul_campfire",
        "redstone_torch",
        "redstone_wall_torch",
    }
)

_CAMPFIRE_LEVEL = {"campfire": 15, "soul_campfire": 10}
_FURNACE_LEVEL = {"furnace": 13, "blast_furnace": 13, "smoker": 13}
_REDSTONE_TORCH_LEVEL = {"redstone_torch": 7, "redstone_wall_torch": 7}


def _prop(block, name: str, default: str = "") -> str:
    raw = block.properties.get(name)
    if raw is None:
        return default
    return format_property_value(raw).lower()


def _is_true(block, name: str, default: bool = False) -> bool:
    value = _prop(block, name, "true" if default else "false")
    return value in {"true", "1", "yes"}


def _int_prop(block, name: str, default: int = 0) -> int:
    try:
        return int(_prop(block, name, str(default)))
    except ValueError:
        return default


def _copper_bulb_level(name: str) -> int:
    if "oxidized" in name:
        return 4
    if "weathered" in name:
        return 8
    if "exposed" in name:
        return 12
    return 15


def light_emission(entry: ResolvedBlock | None) -> int:
    """Vanilla 0–15 block-light contribution, or 0 if the cell does not emit."""
    if entry is None or entry.java_block is None:
        return 0
    block = entry.java_block
    name = block.base_name

    if name in LIGHT_LEVELS:
        return LIGHT_LEVELS[name]

    if name in _LIT_ALWAYS:
        if not _is_true(block, "lit", default=True):
            return 0
        if name in _CAMPFIRE_LEVEL:
            return _CAMPFIRE_LEVEL[name]
        if name in _FURNACE_LEVEL:
            return _FURNACE_LEVEL[name]
        if name in _REDSTONE_TORCH_LEVEL:
            return _REDSTONE_TORCH_LEVEL[name]
        return 15

    if name.endswith("copper_bulb"):
        return _copper_bulb_level(name) if _is_true(block, "lit") else 0

    if name.endswith("candle_cake"):
        return 3 if _is_true(block, "lit") else 0

    if name.endswith("candle"):
        if not _is_true(block, "lit"):
            return 0
        return 3 * max(1, min(4, _int_prop(block, "candles", 1)))

    if name == "sea_pickle":
        if not _is_true(block, "waterlogged"):
            return 0
        pickles = max(1, min(4, _int_prop(block, "pickles", 1)))
        return {1: 6, 2: 9, 3: 12, 4: 15}[pickles]

    if name in {"cave_vines", "cave_vines_plant"}:
        return 14 if _is_true(block, "berries") else 0

    if name == "respawn_anchor":
        return {0: 0, 1: 3, 2: 7, 3: 11, 4: 15}.get(_int_prop(block, "charges", 0), 0)

    if name == "light":
        return max(0, min(15, _int_prop(block, "level", 15)))

    return 0


def _is_water(entry: ResolvedBlock | None) -> bool:
    if entry is None or not entry.is_fluid:
        return False
    block = entry.java_block
    if block is None:
        return True
    return "lava" not in block.base_name


def face_shade_from_normal(nx: float, ny: float, nz: float) -> float:
    ax, ay, az = abs(nx), abs(ny), abs(nz)
    if ay >= ax and ay >= az:
        return FACE_SHADE["up"] if ny >= 0 else FACE_SHADE["down"]
    if az >= ax:
        return FACE_SHADE["north"]
    return FACE_SHADE["east"]


def encode_light(block: float, sky: float) -> tuple[float, float]:
    return (block + 0.5) / 16.0, (sky + 0.5) / 16.0


@dataclass
class LightField:
    """Integer block/sky levels plus the occupancy used while sampling."""

    origin: tuple[int, int, int]
    block: numpy.ndarray
    sky: numpy.ndarray
    opaque: numpy.ndarray
    water: numpy.ndarray
    filled: numpy.ndarray

    def _index(self, x: int, y: int, z: int) -> tuple[int, int, int] | None:
        ox, oy, oz = self.origin
        ix, iy, iz = x - ox, y - oy, z - oz
        sx, sy, sz = self.block.shape
        if not (0 <= ix < sx and 0 <= iy < sy and 0 <= iz < sz):
            return None
        return ix, iy, iz

    def in_volume(self, x: int, y: int, z: int) -> bool:
        idx = self._index(x, y, z)
        return idx is not None and bool(self.filled[idx])

    def is_opaque(self, x: int, y: int, z: int) -> bool:
        idx = self._index(x, y, z)
        if idx is None:
            return False
        return bool(self.opaque[idx])

    def is_water(self, x: int, y: int, z: int) -> bool:
        idx = self._index(x, y, z)
        if idx is None:
            return False
        return bool(self.water[idx])

    def levels_at(self, x: int, y: int, z: int) -> tuple[int, int]:
        idx = self._index(x, y, z)
        if idx is None or not self.filled[idx]:
            return 0, 0
        return int(self.block[idx]), int(self.sky[idx])


def _iter_cells(grid: BlockGrid):
    for cx, cz in grid.loaded_chunks():
        chunk = grid.chunk_at(cx, cz)
        resolved = grid.resolved_at(cx, cz)
        if chunk is None or resolved is None:
            continue
        for cy in chunk.blocks.sub_chunks:
            section = numpy.asarray(chunk.blocks.get_sub_chunk(cy))
            section_lo = cy * 16
            for dx in range(16):
                wx = cx * 16 + dx
                for dz in range(16):
                    wz = cz * 16 + dz
                    for dy in range(16):
                        wy = section_lo + dy
                        index = _section_index(section, dx, dy, dz)
                        if index < 0 or index >= len(resolved):
                            yield wx, wy, wz, None
                            continue
                        yield wx, wy, wz, resolved[index]


def _empty_field() -> LightField:
    z = numpy.zeros((1, 1, 1), dtype=numpy.uint8)
    f = numpy.zeros((1, 1, 1), dtype=bool)
    return LightField((0, 0, 0), z, z.copy(), f.copy(), f.copy(), f.copy())


def _allocate(grid: BlockGrid) -> LightField | None:
    min_x = min_y = min_z = None
    max_x = max_y = max_z = None
    for x, y, z, _entry in _iter_cells(grid):
        if min_x is None:
            min_x = max_x = x
            min_y = max_y = y
            min_z = max_z = z
            continue
        min_x = min(min_x, x)
        max_x = max(max_x, x)
        min_y = min(min_y, y)
        max_y = max(max_y, y)
        min_z = min(min_z, z)
        max_z = max(max_z, z)
    if min_x is None:
        return None
    shape = (max_x - min_x + 1, max_y - min_y + 1, max_z - min_z + 1)
    return LightField(
        origin=(min_x, min_y, min_z),
        block=numpy.zeros(shape, dtype=numpy.uint8),
        sky=numpy.zeros(shape, dtype=numpy.uint8),
        opaque=numpy.zeros(shape, dtype=bool),
        water=numpy.zeros(shape, dtype=bool),
        filled=numpy.zeros(shape, dtype=bool),
    )


def _paint_volume(grid: BlockGrid, field: LightField) -> numpy.ndarray:
    emit = numpy.zeros(field.block.shape, dtype=numpy.uint8)
    ox, oy, oz = field.origin
    for x, y, z, entry in _iter_cells(grid):
        idx = (x - ox, y - oy, z - oz)
        field.filled[idx] = True
        if entry is None:
            continue
        if entry.is_opaque:
            field.opaque[idx] = True
        if _is_water(entry):
            field.water[idx] = True
        level = light_emission(entry)
        if level:
            emit[idx] = max(int(emit[idx]), level)
    return emit


def _dilate_block(emit: numpy.ndarray, opaque: numpy.ndarray, water: numpy.ndarray) -> numpy.ndarray:
    work = emit.astype(numpy.int16, copy=True)
    air = ~opaque
    drop = numpy.where(water, WATER_OPACITY, 1).astype(numpy.int16)
    for _ in range(15):
        padded = numpy.pad(work, 1, mode="constant")
        incoming = numpy.maximum.reduce(
            [
                padded[2:, 1:-1, 1:-1],
                padded[:-2, 1:-1, 1:-1],
                padded[1:-1, 2:, 1:-1],
                padded[1:-1, :-2, 1:-1],
                padded[1:-1, 1:-1, 2:],
                padded[1:-1, 1:-1, :-2],
            ]
        )
        nxt = numpy.maximum(incoming - drop, 0)
        work = numpy.where(air, numpy.maximum(work, nxt), 0)
        work = numpy.maximum(work, emit)
    return numpy.clip(work, 0, 15).astype(numpy.uint8)


def _seed_sky(field: LightField) -> numpy.ndarray:
    sky = numpy.zeros(field.block.shape, dtype=numpy.int16)
    sx, sy, sz = field.block.shape
    for ix in range(sx):
        for iz in range(sz):
            exposed = True
            for iy in range(sy - 1, -1, -1):
                if not field.filled[ix, iy, iz]:
                    continue
                if field.opaque[ix, iy, iz] or field.water[ix, iy, iz]:
                    exposed = False
                    continue
                if exposed:
                    sky[ix, iy, iz] = 15
    return sky


def _dilate_sky(seed: numpy.ndarray, opaque: numpy.ndarray, water: numpy.ndarray) -> numpy.ndarray:
    work = seed.astype(numpy.int16, copy=True)
    air = ~opaque
    drop = numpy.where(water, WATER_OPACITY, 1).astype(numpy.int16)
    for _ in range(15):
        padded = numpy.pad(work, 1, mode="constant")
        from_x0 = padded[:-2, 1:-1, 1:-1]
        from_x1 = padded[2:, 1:-1, 1:-1]
        from_down = padded[1:-1, :-2, 1:-1]
        from_up = padded[1:-1, 2:, 1:-1]
        from_z0 = padded[1:-1, 1:-1, :-2]
        from_z1 = padded[1:-1, 1:-1, 2:]
        # Sky does not drop falling through air. Water still eats it.
        from_above = numpy.where((from_up == 15) & ~water, 15, numpy.maximum(from_up - drop, 0))
        incoming = numpy.maximum.reduce(
            [
                numpy.maximum(from_x0 - drop, 0),
                numpy.maximum(from_x1 - drop, 0),
                numpy.maximum(from_down - drop, 0),
                from_above,
                numpy.maximum(from_z0 - drop, 0),
                numpy.maximum(from_z1 - drop, 0),
            ]
        )
        work = numpy.where(air, numpy.maximum(work, incoming), 0)
        work = numpy.maximum(work, seed)
    return numpy.clip(work, 0, 15).astype(numpy.uint8)


def compute_light_field(grid: BlockGrid) -> LightField:
    field = _allocate(grid)
    if field is None:
        return _empty_field()
    emit = _paint_volume(grid, field)
    field.block = _dilate_block(emit, field.opaque, field.water)
    field.sky = _dilate_sky(_seed_sky(field), field.opaque, field.water)
    return field


def _dominant_axis(nx: float, ny: float, nz: float) -> tuple[int, int]:
    ax, ay, az = abs(nx), abs(ny), abs(nz)
    if ay >= ax and ay >= az:
        return 1, 1 if ny >= 0 else -1
    if az >= ax:
        return 2, 1 if nz >= 0 else -1
    return 0, 1 if nx >= 0 else -1


def sample_face_vertex(
    field: LightField, x: float, y: float, z: float, normal: tuple[float, float, float]
) -> tuple[float, float, float]:
    """4-tap average + AO on the lit side of the face.

    Returns ``(block, sky, ao)``. AO is 1.0 / 0.8 / 0.6 / 0.4, never zero.
    """
    nx, ny, nz = normal
    axis, sign = _dominant_axis(nx, ny, nz)
    pos = (x, y, z)
    nudged = [x, y, z]
    nudged[axis] += 1e-3 * sign
    c_norm = int(numpy.floor(nudged[axis]))
    tangents = tuple(i for i in (0, 1, 2) if i != axis)

    cells: list[tuple[int, int, int]] = []
    for du in (0, -1):
        for dv in (0, -1):
            cell = [0, 0, 0]
            cell[axis] = c_norm
            cell[tangents[0]] = int(numpy.floor(pos[tangents[0]] + 1e-6)) + du
            cell[tangents[1]] = int(numpy.floor(pos[tangents[1]] + 1e-6)) + dv
            cells.append((cell[0], cell[1], cell[2]))

    block_sum = 0.0
    sky_sum = 0.0
    for cx, cy, cz in cells:
        block, sky = field.levels_at(cx, cy, cz)
        block_sum += block
        sky_sum += sky

    # cells[0] is the corner at the vertex; [1]/[2] are the sides; [3] is
    # the face cell (not an AO occluder — that is the air the face looks into).
    side1 = field.is_opaque(*cells[1])
    side2 = field.is_opaque(*cells[2])
    corner = field.is_opaque(*cells[0]) or (side1 and side2)
    occluded = int(side1) + int(side2) + int(corner)
    ao = max(1.0 - occluded * AO_STEP, AO_FLOOR)
    return block_sum / 4.0, sky_sum / 4.0, ao


def _triangle_normal(
    p0: numpy.ndarray, p1: numpy.ndarray, p2: numpy.ndarray
) -> tuple[float, float, float] | None:
    normal = numpy.cross(p1 - p0, p2 - p0)
    length = float(numpy.linalg.norm(normal))
    if length < 1e-8:
        return None
    n = normal / length
    return float(n[0]), float(n[1]), float(n[2])


def _stamp(mesh: BakedMesh, field: LightField) -> BakedMesh:
    verts = mesh.vertex_count
    if verts == 0:
        return mesh
    positions = numpy.asarray(mesh.positions, dtype=numpy.float32).reshape(-1, 3)
    colors = numpy.asarray(mesh.colors, dtype=numpy.float32).reshape(-1, 3).copy()
    if colors.shape[0] != verts:
        colors = numpy.ones((verts, 3), dtype=numpy.float32)
    light = numpy.zeros((verts, 2), dtype=numpy.float32)
    ao_mul = numpy.ones(verts, dtype=numpy.float32)
    written = numpy.zeros(verts, dtype=bool)
    indices = numpy.asarray(mesh.indices, dtype=numpy.uint32).reshape(-1)

    for i in range(0, indices.size, 3):
        i0, i1, i2 = int(indices[i]), int(indices[i + 1]), int(indices[i + 2])
        if not (0 <= i0 < verts and 0 <= i1 < verts and 0 <= i2 < verts):
            continue
        normal = _triangle_normal(positions[i0], positions[i1], positions[i2])
        if normal is None:
            normal = (0.0, 1.0, 0.0)
        for vi in (i0, i1, i2):
            if written[vi]:
                continue
            x, y, z = (float(positions[vi, 0]), float(positions[vi, 1]), float(positions[vi, 2]))
            block, sky, ao = sample_face_vertex(field, x, y, z, normal)
            light[vi, 0], light[vi, 1] = encode_light(block, sky)
            ao_mul[vi] = ao
            written[vi] = True

    # Isolated verts (should not happen) still get a cell sample.
    for vi in range(verts):
        if written[vi]:
            continue
        x, y, z = (float(positions[vi, 0]), float(positions[vi, 1]), float(positions[vi, 2]))
        block, sky, ao = sample_face_vertex(field, x, y, z, (0.0, 1.0, 0.0))
        light[vi, 0], light[vi, 1] = encode_light(block, sky)
        ao_mul[vi] = ao

    colors *= ao_mul[:, None]
    return BakedMesh(
        positions=mesh.positions,
        uvs=mesh.uvs,
        colors=colors.ravel(),
        indices=mesh.indices,
        emit=mesh.emit,
        light=light.ravel(),
    )


def apply_light(bake: ChunkBake, field: LightField) -> ChunkBake:
    return ChunkBake(
        opaque=_stamp(bake.opaque, field),
        translucent=_stamp(bake.translucent, field),
        chunk=bake.chunk,
        origin=bake.origin,
        y_range=bake.y_range,
    )
