"""Bake one chunk or a square region to mesh IR + files.

Every chunk in the region is marked visible so shared faces cull and the
outer shell of the *region* stays. One extra ring of chunks is loaded
with ``visible=False`` so the light flood has a halo and sky 15 cannot
leak in at the mesh edge. Neighbours outside the halo stay air.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from amulet.api.errors import ChunkDoesNotExist, ChunkLoadError
from amulet.api.level import BaseLevel

from mcread.atlas import TextureAtlas, build_atlas
from mcread.banners import BannerPainter, apply_banner_patterns
from mcread.export_obj import write_obj
from mcread.export_scene import TRAPDOOR_LANDMARK, write_scene
from mcread.emit import apply_emit, collect_emitters
from mcread.light import apply_light, compute_light_field
from mcread.mesh import BlockGrid, ChunkBake, merge_bakes, mesh_chunk
from mcread.resolve import PaletteResolver
from mcread.world_access import OVERWORLD, block_to_chunk_coords, iter_region_coords

DEFAULT_MIN_Y = 60
DEFAULT_RADIUS = 0
MAX_RADIUS = 4
LIGHT_HALO = 1


def _palette_blocks(palette) -> list:
    if hasattr(palette, "values"):
        return list(palette.values())
    return list(palette)


def _try_get_chunk(level: BaseLevel, cx: int, cz: int, dimension: str):
    if not level.has_chunk(cx, cz, dimension):
        return None
    try:
        return level.get_chunk(cx, cz, dimension)
    except (ChunkDoesNotExist, ChunkLoadError):
        return None


def load_bake_grid(
    level: BaseLevel,
    cx: int,
    cz: int,
    dimension: str,
    resolver: PaletteResolver,
    *,
    radius: int = DEFAULT_RADIUS,
) -> BlockGrid:
    if radius < 0:
        raise ValueError("radius cannot be negative")
    grid = BlockGrid()
    for ncx, ncz in iter_region_coords(cx, cz, radius + LIGHT_HALO):
        chunk = _try_get_chunk(level, ncx, ncz, dimension)
        if chunk is None:
            continue
        visible = abs(ncx - cx) <= radius and abs(ncz - cz) <= radius
        grid.add_chunk(
            chunk,
            resolver.resolve_palette(_palette_blocks(chunk.block_palette)),
            visible=visible,
        )
    if grid.chunk_at(cx, cz) is None:
        raise ChunkDoesNotExist(f"chunk ({cx}, {cz}) does not exist in {dimension}")
    apply_banner_patterns(grid, BannerPainter(resolver.manager))
    return grid


def camera_target_for(
    bake: ChunkBake,
    *,
    block_x: int,
    block_z: int,
    landmark: tuple[int, int, int] = TRAPDOOR_LANDMARK,
) -> tuple[int, int, int]:
    lx, ly, lz = landmark
    if (
        abs(block_x - lx) <= 16
        and abs(block_z - lz) <= 16
        and bake.y_range[0] <= ly <= bake.y_range[1]
    ):
        return landmark
    look_y = 80
    if look_y < bake.y_range[0]:
        look_y = bake.y_range[0] + 8
    if look_y > bake.y_range[1]:
        look_y = bake.y_range[1]
    return (block_x, look_y, block_z)


def bake_chunk(
    level: BaseLevel,
    cx: int,
    cz: int,
    dimension: str = OVERWORLD,
    *,
    resolver: PaletteResolver | None = None,
    min_y: int | None = DEFAULT_MIN_Y,
    max_y: int | None = None,
    radius: int = DEFAULT_RADIUS,
) -> tuple[ChunkBake, TextureAtlas]:
    if radius > MAX_RADIUS:
        raise ValueError(f"radius {radius} is above the cap of {MAX_RADIUS}")
    resolver = resolver or PaletteResolver()
    grid = load_bake_grid(level, cx, cz, dimension, resolver, radius=radius)
    atlas = build_atlas(grid.textures_for_visible(), extras=grid.banner_extras())
    bakes = [
        mesh_chunk(grid, ncx, ncz, atlas, min_y=min_y, max_y=max_y)
        for ncx, ncz in grid.visible_chunks()
    ]
    merged = merge_bakes(bakes, center=(cx, cz))
    emitters = collect_emitters(grid, min_y=min_y, max_y=max_y)
    field = compute_light_field(grid)
    return apply_light(apply_emit(merged, emitters), field), atlas


def bake_and_write(
    level: BaseLevel,
    block_x: int,
    block_z: int,
    out_dir: Path,
    *,
    dimension: str = OVERWORLD,
    resolver: PaletteResolver | None = None,
    min_y: int | None = DEFAULT_MIN_Y,
    max_y: int | None = None,
    radius: int = DEFAULT_RADIUS,
) -> tuple[ChunkBake, TextureAtlas, Path]:
    cx, cz = block_to_chunk_coords(block_x, block_z)
    bake, atlas = bake_chunk(
        level,
        cx,
        cz,
        dimension,
        resolver=resolver,
        min_y=min_y,
        max_y=max_y,
        radius=radius,
    )
    view = {
        "block_x": block_x,
        "block_z": block_z,
        "radius": radius,
        "min_y": min_y,
        "max_y": max_y,
        "center_chunk": [cx, cz],
        "chunks_meshed": (2 * radius + 1) ** 2,
    }
    path = write_bake(
        out_dir,
        bake,
        atlas,
        block_x=block_x,
        block_z=block_z,
        view=view,
    )
    return bake, atlas, path


def write_bake(
    out_dir: Path,
    bake: ChunkBake,
    atlas: TextureAtlas,
    *,
    camera_target: tuple[int, int, int] | None = None,
    view: dict[str, Any] | None = None,
    block_x: int | None = None,
    block_z: int | None = None,
) -> Path:
    if camera_target is None:
        if block_x is not None and block_z is not None:
            camera_target = camera_target_for(bake, block_x=block_x, block_z=block_z)
        else:
            camera_target = TRAPDOOR_LANDMARK
    scene_path = write_scene(
        out_dir,
        bake,
        atlas,
        camera_target=camera_target,
        view=view,
    )
    write_obj(out_dir / "debug.obj", bake, atlas)
    return scene_path
