"""Read the resource pack's own JSON to explain why a block has no geometry.

A gap is only irreducible if Minecraft itself ships no geometry for the block.
If the pack does define elements and we still got nothing, that is our bug.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

MAX_PARENT_DEPTH = 16


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open() as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def split_identifier(identifier: str) -> tuple[str, str]:
    if ":" in identifier:
        namespace, name = identifier.split(":", 1)
        return namespace, name
    return "minecraft", identifier


def asset_path(pack_roots: Iterable[Path], namespace: str, relative: str) -> Optional[Path]:
    """Later packs win, matching how the pack manager stacks overrides."""
    found: Optional[Path] = None
    for root in pack_roots:
        candidate = Path(root) / "assets" / namespace / relative
        if candidate.is_file():
            found = candidate
    return found


def blockstate_json(
    pack_roots: Iterable[Path], namespace: str, base_name: str
) -> Optional[dict]:
    path = asset_path(pack_roots, namespace, f"blockstates/{base_name}.json")
    return _load_json(path) if path else None


def referenced_models(blockstate: Optional[dict]) -> list[str]:
    """Every model any variant or multipart case could use."""
    if not blockstate:
        return []
    models: list[str] = []

    def collect(entry) -> None:
        if isinstance(entry, dict):
            model = entry.get("model")
            if isinstance(model, str):
                models.append(model)
        elif isinstance(entry, list):
            for item in entry:
                collect(item)

    for entry in (blockstate.get("variants") or {}).values():
        collect(entry)
    for case in blockstate.get("multipart") or []:
        collect(case.get("apply"))
    return list(dict.fromkeys(models))


def model_chain(
    pack_roots: Iterable[Path], model_identifier: str
) -> list[tuple[str, dict]]:
    """Follow `parent` up the inheritance chain."""
    chain: list[tuple[str, dict]] = []
    current: Optional[str] = model_identifier
    seen: set[str] = set()
    roots = list(pack_roots)
    for _ in range(MAX_PARENT_DEPTH):
        if not current or current in seen:
            break
        seen.add(current)
        namespace, name = split_identifier(current)
        path = asset_path(roots, namespace, f"models/{name}.json")
        if path is None:
            break
        data = _load_json(path)
        if data is None:
            break
        chain.append((current, data))
        parent = data.get("parent")
        current = parent if isinstance(parent, str) else None
    return chain


def _resolve_texture_refs(table: dict[str, str]) -> dict[str, str]:
    """Follow `#side` style aliases. Drop keys that never resolve."""
    current = dict(table)
    for _ in range(8):
        changed = False
        for key, value in list(current.items()):
            if not value.startswith("#"):
                continue
            target = current.get(value[1:])
            if target and not target.startswith("#"):
                current[key] = target
                changed = True
        if not changed:
            break
    return {
        key: value for key, value in current.items() if not value.startswith("#")
    }


def _texture_table_for_models(
    pack_roots: list[Path], models: tuple[str, ...]
) -> dict[str, str]:
    merged: dict[str, str] = {}
    for model in models:
        chain = model_chain(pack_roots, model)
        layer: dict[str, str] = {}
        for _identifier, data in reversed(chain):
            textures = data.get("textures") or {}
            for key, value in textures.items():
                if isinstance(value, str):
                    layer[key] = value
        merged.update(_resolve_texture_refs(layer))
    return merged


@dataclass(frozen=True)
class GeometrySource:
    """Where a block's geometry comes from, according to the pack."""

    blockstate_found: bool
    models: tuple[str, ...]
    models_resolved: tuple[str, ...]
    element_source: Optional[str]
    """The model in the chain that actually defines elements."""
    has_tintindex: bool
    particle: Optional[str]
    """Resolved particle (or `all`) texture identifier, if the model has one."""

    @property
    def has_geometry(self) -> bool:
        return self.element_source is not None


@lru_cache(maxsize=4096)
def _cached_geometry_source(
    roots: tuple[str, ...], namespace: str, base_name: str
) -> GeometrySource:
    paths = [Path(root) for root in roots]
    blockstate = blockstate_json(paths, namespace, base_name)
    models = tuple(referenced_models(blockstate))
    resolved: list[str] = []
    element_source: Optional[str] = None
    has_tint = False

    for model in models:
        chain = model_chain(paths, model)
        if chain:
            resolved.append(model)
        for identifier, data in chain:
            elements = data.get("elements")
            if elements:
                if element_source is None:
                    element_source = identifier
                for element in elements:
                    for face in (element.get("faces") or {}).values():
                        if isinstance(face, dict) and "tintindex" in face:
                            has_tint = True

    textures = _texture_table_for_models(paths, models)
    particle = textures.get("particle") or textures.get("all")
    return GeometrySource(
        blockstate_found=blockstate is not None,
        models=models,
        models_resolved=tuple(resolved),
        element_source=element_source,
        has_tintindex=has_tint,
        particle=particle,
    )


def geometry_source(
    pack_roots: Iterable[Path | str], namespace: str, base_name: str
) -> GeometrySource:
    roots = tuple(str(root) for root in pack_roots)
    return _cached_geometry_source(roots, namespace, base_name)
