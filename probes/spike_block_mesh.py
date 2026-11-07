"""Spike: prove one sampled block reaches real geometry with no per-block code.

Answers the three integration questions:
  1. is minecraft_model_reader's Block the same type amulet hands us?
  2. does the vanilla Java pack download and load?
  3. how are BlockMesh verts/faces keyed?

Run: .venv/bin/python probes/spike_block_mesh.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from amulet.api.block import Block
from amulet_nbt import StringTag

from mcread.blocks import blockstate_key
from mcread.models import describe_block_mesh, java_model_manager
from mcread.translate import JavaTranslator

# the birch trapdoor this project sampled out of the real save
SPIKE_BLOCK = Block(
    "universal_minecraft",
    "trapdoor",
    {
        "facing": StringTag("west"),
        "half": StringTag("bottom"),
        "material": StringTag("birch"),
        "open": StringTag("true"),
        "powered": StringTag("false"),
    },
)


def main() -> int:
    import minecraft_model_reader
    from minecraft_model_reader.api import Block as MMRBlock

    print("== question 1: block type compatibility ==")
    print(f"minecraft_model_reader {minecraft_model_reader.__version__}")
    print(f"mmr Block is amulet Block: {MMRBlock is Block}")

    print("\n== question 2: resource pack ==")
    manager = java_model_manager()
    for path in manager.pack_paths:
        print(f"  pack: {path}")
    print(f"  textures available: {len(manager.textures)}")

    print("\n== translation ==")
    translator = JavaTranslator()
    print(f"  java target version: {translator.version_number}")
    print(f"  universal in:  {blockstate_key(SPIKE_BLOCK)}")
    result = translator.translate(SPIKE_BLOCK)
    if not result.ok:
        print(f"  translation failed: {result.error}")
        return 1
    java_block = result.block
    assert java_block is not None
    print(f"  java out:      {blockstate_key(java_block)}")
    print(f"  extra_needed:  {result.extra_needed}")

    print("\n== question 3: mesh structure ==")
    _mesh, summary = describe_block_mesh(manager, java_block)
    print(f"  fell back to missingno: {summary.is_missing}")
    print(f"  verts: {summary.vert_count}   faces: {summary.face_count}")
    print(f"  cull directions: {summary.cull_directions}")
    print(f"  textures: {summary.textures}")
    print(f"  opaque: {summary.is_opaque}   transparency: {summary.transparency}")
    print(f"  tinted verts: {summary.tinted_vert_count}")

    if summary.is_missing:
        print("\nspike FAILED: the pack has no model for this block")
        return 1
    print("\nspike passed: save data reached real geometry with no per-block code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
