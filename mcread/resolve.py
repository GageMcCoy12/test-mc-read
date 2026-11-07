"""Turn a chunk palette into per-index render records.

Cache by blockstate, not by world position. A chunk has a few hundred palette
entries and tens of thousands of cells; translation and model lookup only
happen once per distinct block.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from amulet.api.block import Block
from minecraft_model_reader.api.mesh.block.block_mesh import BlockMesh, Transparency
from minecraft_model_reader.api.mesh.block.cube import get_unit_cube
from minecraft_model_reader.api.resource_pack.java.resource_pack_manager import (
    JavaResourcePackManager,
)

from mcread.atlas import texture_has_cutout
from mcread.blocks import blockstate_key, is_empty_block, is_fluid_block
from mcread.models import describe_block_mesh, java_model_manager
from mcread.pack_inspect import geometry_source, split_identifier
from mcread.translate import JavaTranslator

WATER_TINT = (0x44 / 255, 0xAF / 255, 0xF5 / 255)
LAVA_TINT = (1.0, 1.0, 1.0)


@dataclass(frozen=True)
class ResolvedBlock:
    """Everything the mesher needs for one palette entry."""

    java_block: Optional[Block]
    mesh: Optional[BlockMesh]
    is_opaque: bool
    transparency: Transparency
    is_fluid: bool
    is_missing: bool
    is_empty: bool
    extra_needed: bool
    skip: bool


SKIP_EMPTY = ResolvedBlock(
    java_block=None,
    mesh=None,
    is_opaque=False,
    transparency=Transparency.Partial,
    is_fluid=False,
    is_missing=False,
    is_empty=True,
    extra_needed=False,
    skip=True,
)

SKIP_MISSING = ResolvedBlock(
    java_block=None,
    mesh=None,
    is_opaque=False,
    transparency=Transparency.Partial,
    is_fluid=False,
    is_missing=True,
    is_empty=False,
    extra_needed=False,
    skip=True,
)


def _cache_key(block: Block) -> tuple[str, tuple[str, ...]]:
    extras = tuple(blockstate_key(extra) for extra in block.extra_blocks)
    return (blockstate_key(block), extras)


def _is_missing_mesh(manager: JavaResourcePackManager, mesh: BlockMesh) -> bool:
    missing = set(manager.missing_block.textures)
    return bool(missing) and set(mesh.textures) <= missing


def _texture_path(manager: JavaResourcePackManager, identifier: str) -> str | None:
    namespace, relative = split_identifier(identifier)
    path = manager.get_texture_path(namespace, relative)
    if not path or path == manager.missing_no:
        return None
    if path in set(manager.missing_block.textures):
        return None
    return path


def placeholder_cube(
    manager: JavaResourcePackManager, texture: str, *, translucent: bool = False
) -> BlockMesh:
    mode = Transparency.FullTranslucent if translucent else Transparency.FullOpaque
    return get_unit_cube(texture, texture, texture, texture, texture, texture, mode)


def fluid_placeholder_mesh(
    manager: JavaResourcePackManager, base_name: str
) -> BlockMesh:
    """Full cube using the still fluid texture. Surface height comes later."""
    lava = "lava" in base_name
    texture = manager.get_texture_path(
        "minecraft", "block/lava_still" if lava else "block/water_still"
    )
    tint = LAVA_TINT if lava else WATER_TINT
    return get_unit_cube(
        texture,
        texture,
        texture,
        texture,
        texture,
        texture,
        Transparency.FullTranslucent,
        tint,
    )


def mesh_occludes(mesh: BlockMesh) -> bool:
    """A block only hides neighbours if it is a full cube and has no cutout pixels.

    The pack reader marks leaves FullOpaque; the PNG still has holes, so we
    check the texture ourselves instead of trusting that flag.
    """
    if not mesh.is_opaque:
        return False
    return not any(texture_has_cutout(path) for path in mesh.textures)


def _mesh_for_java(
    manager: JavaResourcePackManager, java_block: Block
) -> tuple[Optional[BlockMesh], bool, bool]:
    """Return (mesh, is_missing, is_fluid). mesh is None when the block is skipped."""
    fluid = is_fluid_block(java_block)
    mesh, summary = describe_block_mesh(manager, java_block)
    missing = summary.is_missing or _is_missing_mesh(manager, mesh)
    if fluid:
        return fluid_placeholder_mesh(manager, java_block.base_name), False, True
    if missing:
        fallback = entity_placeholder_mesh(manager, java_block)
        if fallback is not None:
            return fallback, False, False
        return None, True, False
    return mesh, False, False


def entity_placeholder_mesh(
    manager: JavaResourcePackManager, java_block: Block
) -> BlockMesh | None:
    """Last-resort cube from the particle texture if the fix pack has no mesh."""
    source = geometry_source(
        manager.pack_paths, java_block.namespace, java_block.base_name
    )
    if source.has_geometry or not source.particle:
        return None
    path = _texture_path(manager, source.particle)
    if path is None:
        return None
    return placeholder_cube(manager, path)


class PaletteResolver:
    """Translate and look up meshes, cached across chunks."""

    def __init__(
        self,
        translator: JavaTranslator | None = None,
        manager: JavaResourcePackManager | None = None,
    ) -> None:
        self.translator = translator or JavaTranslator()
        self.manager = manager or java_model_manager()
        self._cache: dict[tuple[str, tuple[str, ...]], ResolvedBlock] = {}

    def resolve(self, block: Block) -> ResolvedBlock:
        key = _cache_key(block)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        resolved = self._resolve_uncached(block)
        self._cache[key] = resolved
        return resolved

    def resolve_palette(self, palette: Iterable[Block]) -> list[ResolvedBlock]:
        return [self.resolve(block) for block in palette]

    def _resolve_uncached(self, block: Block) -> ResolvedBlock:
        if is_empty_block(block):
            return SKIP_EMPTY

        extras = [extra for extra in block.extra_blocks if not is_empty_block(extra)]
        primary = self._resolve_one_layer(block)
        if not extras:
            return primary

        layers = []
        if primary.mesh is not None and not primary.skip:
            layers.append(primary.mesh)
        extra_needed = primary.extra_needed
        java_block = primary.java_block
        for extra in extras:
            extra_resolved = self._resolve_one_layer(extra)
            extra_needed = extra_needed or extra_resolved.extra_needed
            if extra_resolved.mesh is not None and not extra_resolved.skip:
                layers.append(extra_resolved.mesh)

        if not layers:
            return ResolvedBlock(
                java_block=java_block,
                mesh=None,
                is_opaque=False,
                transparency=Transparency.Partial,
                is_fluid=primary.is_fluid,
                is_missing=primary.is_missing,
                is_empty=False,
                extra_needed=extra_needed,
                skip=True,
            )

        merged = layers[0] if len(layers) == 1 else BlockMesh.merge(layers)
        return ResolvedBlock(
            java_block=java_block,
            mesh=merged,
            is_opaque=mesh_occludes(merged),
            transparency=merged.is_transparent,
            is_fluid=primary.is_fluid,
            is_missing=False,
            is_empty=False,
            extra_needed=extra_needed,
            skip=False,
        )

    def _resolve_one_layer(self, block: Block) -> ResolvedBlock:
        if is_empty_block(block):
            return SKIP_EMPTY
        if is_fluid_block(block):
            mesh = fluid_placeholder_mesh(self.manager, block.base_name)
            return ResolvedBlock(
                java_block=block,
                mesh=mesh,
                is_opaque=False,
                transparency=Transparency.FullTranslucent,
                is_fluid=True,
                is_missing=False,
                is_empty=False,
                extra_needed=False,
                skip=False,
            )

        result = self.translator.translate(block)
        if not result.ok or result.block is None:
            return SKIP_MISSING

        java_block = result.block
        if is_empty_block(java_block):
            return SKIP_EMPTY

        mesh, missing, fluid = _mesh_for_java(self.manager, java_block)
        if mesh is None:
            return ResolvedBlock(
                java_block=java_block,
                mesh=None,
                is_opaque=False,
                transparency=Transparency.Partial,
                is_fluid=False,
                is_missing=missing,
                is_empty=False,
                extra_needed=bool(result.extra_needed),
                skip=True,
            )
        return ResolvedBlock(
            java_block=java_block,
            mesh=mesh,
            is_opaque=mesh_occludes(mesh),
            transparency=mesh.is_transparent,
            is_fluid=fluid,
            is_missing=False,
            is_empty=False,
            extra_needed=bool(result.extra_needed),
            skip=False,
        )
