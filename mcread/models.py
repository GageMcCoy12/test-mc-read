"""Resolve Java blockstates to meshes via the vanilla resource pack.

Geometry comes from the Java resource pack because Bedrock ships no vanilla
block geometry, only textures. Nothing here knows about individual blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from amulet.api.block import Block
from minecraft_model_reader.api.mesh.block import BlockMesh
from minecraft_model_reader.api.resource_pack import load_resource_pack_manager
from minecraft_model_reader.api.resource_pack.java import download_resources
from minecraft_model_reader.api.resource_pack.java.resource_pack_manager import (
    JavaResourcePackManager,
)


@lru_cache(maxsize=1)
def java_model_manager() -> JavaResourcePackManager:
    """Vanilla first, then Amulet's fix pack.

    Later packs win. Vanilla ships particle-only models for chests, banners,
    pots and shulkers; the fix pack replaces those with real elements and
    entity textures. Stacking the fix pack last is what makes block entities
    render as blocks instead of missingno.
    """
    packs = [
        download_resources.get_java_vanilla_latest(),
        download_resources.get_java_vanilla_fix(),
    ]
    manager = load_resource_pack_manager(packs, load=True)
    assert isinstance(manager, JavaResourcePackManager)
    return manager


@dataclass(frozen=True)
class MeshSummary:
    """A structural description of a mesh, safe to write to JSON."""

    is_missing: bool
    vert_count: int
    face_count: int
    cull_directions: tuple[Optional[str], ...]
    textures: tuple[str, ...]
    tinted_vert_count: int
    is_opaque: bool
    transparency: str

    @property
    def is_tinted(self) -> bool:
        return self.tinted_vert_count > 0


def _int_or_zero(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def summarise_mesh(mesh: BlockMesh, *, is_missing: bool = False) -> MeshSummary:
    verts = mesh.verts
    faces = mesh.faces
    tint = mesh.tint_verts
    return MeshSummary(
        is_missing=is_missing,
        vert_count=sum(_int_or_zero(arr.size) for arr in verts.values()),
        face_count=sum(_int_or_zero(arr.size) for arr in faces.values()),
        cull_directions=tuple(sorted(verts.keys(), key=lambda k: (k is not None, k))),
        textures=tuple(mesh.textures),
        tinted_vert_count=sum(
            _int_or_zero((arr != 1).sum()) for arr in tint.values() if arr is not None
        ),
        is_opaque=bool(mesh.is_opaque),
        transparency=str(mesh.is_transparent),
    )


def describe_block_mesh(
    manager: JavaResourcePackManager, block: Block
) -> tuple[BlockMesh, MeshSummary]:
    """Look up a mesh and flag whether the pack silently fell back to missingno."""
    mesh = manager.get_block_model(block)
    missing_textures = set(manager.missing_block.textures)
    is_missing = bool(missing_textures) and set(mesh.textures) <= missing_textures
    return mesh, summarise_mesh(mesh, is_missing=is_missing)
