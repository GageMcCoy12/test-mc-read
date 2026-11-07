"""Write a BakedMesh to Wavefront OBJ for a known-good viewer.

UVs are atlas-space with V=0 at the top (Pillow / PNG). OBJ expects V=0 at
the bottom, so V is flipped on write.
"""

from __future__ import annotations

from pathlib import Path

from mcread.atlas import TextureAtlas
from mcread.mesh import BakedMesh, ChunkBake


def write_obj(
    path: Path,
    bake: ChunkBake,
    atlas: TextureAtlas,
    *,
    atlas_name: str = "atlas.png",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mtl_path = path.with_suffix(".mtl")
    mtl_name = mtl_path.name

    mtl_path.write_text(
        f"newmtl atlas\nmap_Kd {atlas_name}\n",
        encoding="utf-8",
    )

    lines = [
        f"mtllib {mtl_name}",
        "usemtl atlas",
    ]
    _emit_pass(lines, bake.opaque)
    _emit_pass(lines, bake.translucent)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _emit_pass(lines: list[str], mesh: BakedMesh) -> None:
    if mesh.empty():
        return
    positions = mesh.positions.reshape(-1, 3)
    uvs = mesh.uvs.reshape(-1, 2)
    indices = mesh.indices
    vert_base = sum(1 for line in lines if line.startswith("v "))
    for x, y, z in positions:
        lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    for u, v in uvs:
        lines.append(f"vt {u:.6f} {1.0 - v:.6f}")
    for i in range(0, indices.size, 3):
        a = int(indices[i]) + vert_base + 1
        b = int(indices[i + 1]) + vert_base + 1
        c = int(indices[i + 2]) + vert_base + 1
        lines.append(f"f {a}/{a} {b}/{b} {c}/{c}")
