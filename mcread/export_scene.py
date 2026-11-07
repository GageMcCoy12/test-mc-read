"""Write a BakedMesh as JSON + binary buffers the browser can fetch.

Layout of each *.bin, all little-endian:
  positions: float32[vertex_count * 3]
  uvs:       float32[vertex_count * 2]
  colors:    float32[vertex_count * 3]
  emit:      float32[vertex_count * 3]
  light:     float32[vertex_count * 2]
  indices:   uint32[index_count]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy

from mcread.atlas import TextureAtlas, save_atlas
from mcread.mesh import BakedMesh, ChunkBake

TRAPDOOR_LANDMARK = (296, 80, 76)


def write_mesh_bin(path: Path, mesh: BakedMesh) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    positions = numpy.asarray(mesh.positions, dtype=numpy.float32).ravel()
    uvs = numpy.asarray(mesh.uvs, dtype=numpy.float32).ravel()
    colors = numpy.asarray(mesh.colors, dtype=numpy.float32).ravel()
    emit = numpy.asarray(mesh.emit, dtype=numpy.float32).ravel()
    if emit.size != mesh.vertex_count * 3:
        emit = numpy.zeros(mesh.vertex_count * 3, dtype=numpy.float32)
    light = numpy.asarray(mesh.light, dtype=numpy.float32).ravel()
    if light.size != mesh.vertex_count * 2:
        light = numpy.zeros(mesh.vertex_count * 2, dtype=numpy.float32)
    indices = numpy.asarray(mesh.indices, dtype=numpy.uint32).ravel()
    with path.open("wb") as handle:
        handle.write(positions.tobytes())
        handle.write(uvs.tobytes())
        handle.write(colors.tobytes())
        handle.write(emit.tobytes())
        handle.write(light.tobytes())
        handle.write(indices.tobytes())


def _pass_info(mesh: BakedMesh, filename: str) -> dict[str, Any]:
    return {
        "file": filename,
        "vertex_count": mesh.vertex_count,
        "index_count": mesh.index_count,
        "triangle_count": mesh.triangle_count,
    }


def write_scene(
    out_dir: Path,
    bake: ChunkBake,
    atlas: TextureAtlas,
    *,
    camera_target: tuple[int, int, int] = TRAPDOOR_LANDMARK,
    view: dict[str, Any] | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_mesh_bin(out_dir / "opaque.bin", bake.opaque)
    write_mesh_bin(out_dir / "translucent.bin", bake.translucent)
    save_atlas(atlas, out_dir / "atlas.png")

    payload = {
        "chunk": list(bake.chunk),
        "origin": list(bake.origin),
        "y_range": list(bake.y_range),
        "camera_target": list(camera_target),
        "view": view or {},
        "attributes": ["position", "uv", "color", "emit", "light"],
        "opaque": _pass_info(bake.opaque, "opaque.bin"),
        "translucent": _pass_info(bake.translucent, "translucent.bin"),
        "atlas": {
            "file": "atlas.png",
            "width": atlas.width,
            "height": atlas.height,
            "tile": atlas.tile_size,
            "padding": atlas.padding,
        },
    }
    scene_path = out_dir / "scene.json"
    scene_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return scene_path
