"""Assemble world-space chunk meshes from resolved palette entries.

BlockMesh verts are 0-1 block-local, face_mode 3 (two triangles per quad),
keyed by cull direction. Face culling is free: skip a whole bucket when the
neighbour in that direction is opaque. Fluids also hide faces against fluids.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy
from minecraft_model_reader.api.mesh.block.block_mesh import Transparency

from mcread.banners import is_banner_cloth_texture
from mcread.resolve import ResolvedBlock

# Minecraft: +X east, +Y up, +Z south.
CULL_OFFSETS: dict[str, tuple[int, int, int]] = {
    "down": (0, -1, 0),
    "up": (0, 1, 0),
    "north": (0, 0, -1),
    "south": (0, 0, 1),
    "west": (-1, 0, 0),
    "east": (1, 0, 0),
}


class UVMap(Protocol):
    def remap_one(self, uv: numpy.ndarray, texture: str) -> numpy.ndarray: ...


class IdentityAtlas:
    """Leave UVs in per-texture 0-1 space. Used by tests and OBJ-before-atlas."""

    def remap_one(self, uv: numpy.ndarray, texture: str) -> numpy.ndarray:
        return uv


@dataclass
class BakedMesh:
    """Renderer-agnostic triangle mesh. No block names live here."""

    positions: numpy.ndarray
    uvs: numpy.ndarray
    colors: numpy.ndarray
    indices: numpy.ndarray
    emit: numpy.ndarray = field(default_factory=lambda: numpy.zeros(0, dtype=numpy.float32))
    light: numpy.ndarray = field(default_factory=lambda: numpy.zeros(0, dtype=numpy.float32))

    @property
    def vertex_count(self) -> int:
        return int(self.positions.size // 3)

    @property
    def index_count(self) -> int:
        return int(self.indices.size)

    @property
    def triangle_count(self) -> int:
        return self.index_count // 3

    def empty(self) -> bool:
        return self.index_count == 0


def _emit_array(mesh: BakedMesh) -> numpy.ndarray:
    verts = mesh.vertex_count
    raw = numpy.asarray(mesh.emit, dtype=numpy.float32).reshape(-1)
    if raw.size == verts * 3:
        return raw.reshape(-1, 3)
    return numpy.zeros((verts, 3), dtype=numpy.float32)


def _light_array(mesh: BakedMesh) -> numpy.ndarray:
    verts = mesh.vertex_count
    raw = numpy.asarray(mesh.light, dtype=numpy.float32).reshape(-1)
    if raw.size == verts * 2:
        return raw.reshape(-1, 2)
    return numpy.zeros((verts, 2), dtype=numpy.float32)


def empty_mesh() -> BakedMesh:
    return BakedMesh(
        positions=numpy.zeros(0, dtype=numpy.float32),
        uvs=numpy.zeros(0, dtype=numpy.float32),
        colors=numpy.zeros(0, dtype=numpy.float32),
        indices=numpy.zeros(0, dtype=numpy.uint32),
        emit=numpy.zeros(0, dtype=numpy.float32),
        light=numpy.zeros(0, dtype=numpy.float32),
    )


@dataclass
class ChunkBake:
    opaque: BakedMesh
    translucent: BakedMesh
    chunk: tuple[int, int]
    origin: tuple[int, int, int]
    y_range: tuple[int, int]


def _section_index(section: numpy.ndarray, dx: int, dy: int, dz: int) -> int:
    array = numpy.asarray(section)
    if array.ndim == 3:
        return int(array[dx, dy, dz])
    return int(array.reshape(16, 16, 16)[dx, dy, dz])


def uses_translucent_pass(entry: ResolvedBlock) -> bool:
    """Only real see-through blocks blend. Partial (stairs, slabs, walls) is opaque cutout."""
    return entry.is_fluid or entry.transparency == Transparency.FullTranslucent


class BlockGrid:
    """Look up a ResolvedBlock at world x/y/z. Missing cells are air.

    Chunks can be loaded without being visible. Culling only sees visible
    chunks, so a one-chunk bake keeps its outer faces even if neighbours exist.
    """

    def __init__(self) -> None:
        self._resolved: dict[tuple[int, int], list[ResolvedBlock]] = {}
        self._chunks: dict[tuple[int, int], Any] = {}
        self._visible: set[tuple[int, int]] = set()
        self._banner_cloth: dict[tuple[int, int, int], str] = {}
        self._banner_images: dict[str, Any] = {}

    def add_chunk(
        self, chunk, resolved: list[ResolvedBlock], *, visible: bool = True
    ) -> None:
        key = (chunk.cx, chunk.cz)
        self._chunks[key] = chunk
        self._resolved[key] = resolved
        if visible:
            self._visible.add(key)
        else:
            self._visible.discard(key)

    def chunk_at(self, cx: int, cz: int):
        return self._chunks.get((cx, cz))

    def resolved_at(self, cx: int, cz: int) -> list[ResolvedBlock] | None:
        return self._resolved.get((cx, cz))

    def is_visible(self, cx: int, cz: int) -> bool:
        return (cx, cz) in self._visible

    def set_banner_cloth(self, position: tuple[int, int, int], texture: str) -> None:
        self._banner_cloth[position] = texture

    def banner_cloth_at(self, x: int, y: int, z: int) -> str | None:
        return self._banner_cloth.get((x, y, z))

    def set_banner_images(self, images: dict[str, Any]) -> None:
        self._banner_images = images

    def banner_extras(self) -> dict[str, Any]:
        return self._banner_images

    def entry_at(self, x: int, y: int, z: int) -> ResolvedBlock | None:
        cx = math.floor(x / 16)
        cz = math.floor(z / 16)
        resolved = self._resolved.get((cx, cz))
        chunk = self._chunks.get((cx, cz))
        if resolved is None or chunk is None:
            return None
        dx = x - cx * 16
        dz = z - cz * 16
        cy = math.floor(y / 16)
        dy = y - cy * 16
        if cy not in chunk.blocks.sub_chunks:
            return None
        index = _section_index(chunk.blocks.get_sub_chunk(cy), dx, dy, dz)
        if index < 0 or index >= len(resolved):
            return None
        return resolved[index]

    def entry_for_cull(
        self,
        x: int,
        y: int,
        z: int,
        *,
        min_y: int | None = None,
        max_y: int | None = None,
    ) -> ResolvedBlock | None:
        """Like entry_at, but undrawn chunks or clipped y count as air."""
        if min_y is not None and y < min_y:
            return None
        if max_y is not None and y > max_y:
            return None
        cx = math.floor(x / 16)
        cz = math.floor(z / 16)
        if (cx, cz) not in self._visible:
            return None
        return self.entry_at(x, y, z)

    def visible_chunks(self) -> list[tuple[int, int]]:
        return sorted(self._visible)

    def loaded_chunks(self) -> list[tuple[int, int]]:
        """Visible mesh chunks plus any lighting-only halo."""
        return sorted(self._chunks)

    def textures_for_chunk(self, cx: int, cz: int) -> list[str]:
        resolved = self._resolved.get((cx, cz))
        if not resolved:
            return []
        paths: list[str] = []
        seen: set[str] = set()
        for entry in resolved:
            if entry.mesh is None:
                continue
            for texture in entry.mesh.textures:
                if texture not in seen:
                    seen.add(texture)
                    paths.append(texture)
        return paths

    def textures_for_visible(self) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for cx, cz in self.visible_chunks():
            for texture in self.textures_for_chunk(cx, cz):
                if texture not in seen:
                    seen.add(texture)
                    paths.append(texture)
        for texture in self._banner_cloth.values():
            if texture not in seen:
                seen.add(texture)
                paths.append(texture)
        return paths


def should_cull(
    entry: ResolvedBlock, neighbor: ResolvedBlock | None, direction: str | None
) -> bool:
    if direction is None:
        return False
    if neighbor is None or neighbor.is_empty:
        return False
    if neighbor.is_opaque:
        return True
    if entry.is_fluid and neighbor.is_fluid:
        return True
    return False


class _Accumulator:
    def __init__(self, atlas: UVMap) -> None:
        self.atlas = atlas
        self._positions: list[numpy.ndarray] = []
        self._uvs: list[numpy.ndarray] = []
        self._colors: list[numpy.ndarray] = []
        self._indices: list[numpy.ndarray] = []
        self._vert_offset = 0

    def append_bucket(
        self,
        verts: numpy.ndarray,
        uvs: numpy.ndarray,
        tints: numpy.ndarray,
        faces: numpy.ndarray,
        texture_index: numpy.ndarray,
        textures: tuple[str, ...],
        offset: tuple[int, int, int],
    ) -> None:
        if verts.size == 0 or faces.size == 0:
            return
        positions = numpy.asarray(verts, dtype=numpy.float32).reshape(-1, 3)
        positions = positions + numpy.array(offset, dtype=numpy.float32)
        raw_uvs = numpy.asarray(uvs, dtype=numpy.float32).reshape(-1, 2)
        raw_colors = numpy.asarray(tints, dtype=numpy.float32).reshape(-1, 3)
        if raw_colors.shape[0] != positions.shape[0]:
            raw_colors = numpy.ones((positions.shape[0], 3), dtype=numpy.float32)
        if raw_uvs.shape[0] != positions.shape[0]:
            raw_uvs = numpy.zeros((positions.shape[0], 2), dtype=numpy.float32)

        remapped = raw_uvs.copy()
        face_idx = numpy.asarray(faces, dtype=numpy.uint32).reshape(-1)
        tex_idx = numpy.asarray(texture_index, dtype=numpy.uint32).reshape(-1)
        triangle_count = face_idx.size // 3
        for i in range(min(triangle_count, tex_idx.size)):
            texture = textures[int(tex_idx[i])] if int(tex_idx[i]) < len(textures) else ""
            for k in range(3):
                vi = int(face_idx[i * 3 + k])
                if 0 <= vi < remapped.shape[0] and texture:
                    remapped[vi] = self.atlas.remap_one(raw_uvs[vi], texture)

        self._positions.append(positions)
        self._uvs.append(remapped)
        self._colors.append(raw_colors.astype(numpy.float32))
        self._indices.append(face_idx + numpy.uint32(self._vert_offset))
        self._vert_offset += positions.shape[0]

    def finish(self) -> BakedMesh:
        if not self._indices:
            return empty_mesh()
        positions = numpy.concatenate(self._positions, axis=0)
        return BakedMesh(
            positions=positions.ravel(),
            uvs=numpy.concatenate(self._uvs, axis=0).ravel(),
            colors=numpy.concatenate(self._colors, axis=0).ravel(),
            indices=numpy.concatenate(self._indices, axis=0),
            emit=numpy.zeros(positions.shape[0] * 3, dtype=numpy.float32),
            light=numpy.zeros(positions.shape[0] * 2, dtype=numpy.float32),
        )


def mesh_chunk(
    grid: BlockGrid,
    cx: int,
    cz: int,
    atlas: UVMap | None = None,
    *,
    min_y: int | None = None,
    max_y: int | None = None,
) -> ChunkBake:
    """Walk one chunk and emit opaque + translucent world-space meshes."""
    mapper: UVMap = atlas if atlas is not None else IdentityAtlas()
    chunk = grid.chunk_at(cx, cz)
    resolved = grid.resolved_at(cx, cz)
    if chunk is None or resolved is None:
        raise KeyError(f"chunk ({cx}, {cz}) is not in the grid")

    opaque = _Accumulator(mapper)
    translucent = _Accumulator(mapper)
    subchunks = sorted(chunk.blocks.sub_chunks)
    stored_min = subchunks[0] * 16 if subchunks else 0
    stored_max = subchunks[-1] * 16 + 15 if subchunks else 0
    emit_min = stored_min if min_y is None else max(stored_min, min_y)
    emit_max = stored_max if max_y is None else min(stored_max, max_y)

    for cy in subchunks:
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
                    entry = resolved[index]
                    if entry.skip or entry.mesh is None:
                        continue
                    wx = cx * 16 + dx
                    wz = cz * 16 + dz
                    acc = translucent if uses_translucent_pass(entry) else opaque
                    mesh = entry.mesh
                    textures = mesh.textures
                    override = grid.banner_cloth_at(wx, wy, wz)
                    if override:
                        textures = tuple(
                            override if is_banner_cloth_texture(path) else path
                            for path in textures
                        )
                    for cull_dir, verts in mesh.verts.items():
                        neighbor = None
                        if cull_dir is not None:
                            ox, oy, oz = CULL_OFFSETS[cull_dir]
                            neighbor = grid.entry_for_cull(
                                wx + ox,
                                wy + oy,
                                wz + oz,
                                min_y=min_y,
                                max_y=max_y,
                            )
                        if should_cull(entry, neighbor, cull_dir):
                            continue
                        acc.append_bucket(
                            verts,
                            mesh.texture_coords[cull_dir],
                            mesh.tint_verts[cull_dir],
                            mesh.faces[cull_dir],
                            mesh.texture_index[cull_dir],
                            textures,
                            (wx, wy, wz),
                        )

    return ChunkBake(
        opaque=opaque.finish(),
        translucent=translucent.finish(),
        chunk=(cx, cz),
        origin=(cx * 16, emit_min, cz * 16),
        y_range=(emit_min, emit_max),
    )


def concat_meshes(meshes: list[BakedMesh]) -> BakedMesh:
    nonempty = [mesh for mesh in meshes if not mesh.empty()]
    if not nonempty:
        return empty_mesh()
    positions = numpy.concatenate(
        [mesh.positions.reshape(-1, 3) for mesh in nonempty]
    )
    uvs = numpy.concatenate([mesh.uvs.reshape(-1, 2) for mesh in nonempty])
    colors = numpy.concatenate([mesh.colors.reshape(-1, 3) for mesh in nonempty])
    emit = numpy.concatenate([_emit_array(mesh) for mesh in nonempty])
    light = numpy.concatenate([_light_array(mesh) for mesh in nonempty])
    indices = []
    offset = 0
    for mesh in nonempty:
        indices.append(mesh.indices.astype(numpy.uint32) + numpy.uint32(offset))
        offset += mesh.vertex_count
    return BakedMesh(
        positions=positions.astype(numpy.float32).ravel(),
        uvs=uvs.astype(numpy.float32).ravel(),
        colors=colors.astype(numpy.float32).ravel(),
        indices=numpy.concatenate(indices),
        emit=emit.astype(numpy.float32).ravel(),
        light=light.astype(numpy.float32).ravel(),
    )


def merge_bakes(bakes: list[ChunkBake], *, center: tuple[int, int] | None = None) -> ChunkBake:
    if not bakes:
        raise ValueError("no chunk bakes to merge")
    head = bakes[0]
    if center is not None:
        for bake in bakes:
            if bake.chunk == center:
                head = bake
                break
    origins = numpy.array([bake.origin for bake in bakes], dtype=numpy.int32)
    y_lo = min(bake.y_range[0] for bake in bakes)
    y_hi = max(bake.y_range[1] for bake in bakes)
    return ChunkBake(
        opaque=concat_meshes([bake.opaque for bake in bakes]),
        translucent=concat_meshes([bake.translucent for bake in bakes]),
        chunk=head.chunk,
        origin=(int(origins[:, 0].min()), y_lo, int(origins[:, 2].min())),
        y_range=(y_lo, y_hi),
    )
