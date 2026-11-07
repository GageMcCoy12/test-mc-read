"""End-to-end checks that touch the real save and the downloaded pack."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from mcread.blocks import blockstate_key
from mcread.census import PaletteCensus
from mcread.world_access import DEFAULT_WORLD, OVERWORLD, open_chunk

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROBE_DIR = PROJECT_ROOT / "probes"
TOOLS_DIR = PROJECT_ROOT / "tools"
PROBES = [
    "palette_census.py",
    "property_vocabulary.py",
    "translation_coverage.py",
    "asset_coverage.py",
    "nonblock_inventory.py",
    "special_cases.py",
    "spike_block_mesh.py",
]


@pytest.mark.parametrize("script", PROBES)
def test_every_probe_script_imports_and_parses_args(script):
    """Cheap guard against a probe breaking when shared code changes."""
    result = subprocess.run(
        [sys.executable, str(PROBE_DIR / script), "--help"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr


def test_bake_chunk_script_parses_args():
    result = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "bake_chunk.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr


def test_serve_viewer_script_parses_args():
    result = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "serve_viewer.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr


def requires_world():
    if not (DEFAULT_WORLD / "db").is_dir():
        pytest.skip("world/db is missing")


@pytest.mark.integration
def test_census_of_a_real_chunk_finds_many_blockstates():
    requires_world()
    census = PaletteCensus()
    with open_chunk(DEFAULT_WORLD, 18, 4, OVERWORLD) as chunk:
        census.add_chunk(chunk)

    assert census.chunks_scanned == 1
    assert census.blocks_counted == census.sub_chunks_scanned * 4096
    assert len(census.records()) > 50


@pytest.mark.integration
def test_real_blocks_translate_and_resolve_to_geometry():
    """The pipeline claim, checked against real save data: everything that is
    not a fluid or a block entity gets geometry from the pack."""
    requires_world()
    from mcread.models import describe_block_mesh, java_model_manager
    from mcread.pack_inspect import geometry_source
    from mcread.translate import JavaTranslator

    census = PaletteCensus()
    with open_chunk(DEFAULT_WORLD, 18, 4, OVERWORLD) as chunk:
        census.add_chunk(chunk)

    translator = JavaTranslator()
    manager = java_model_manager()
    unexplained: list[str] = []

    for _key, block in census.iter_blocks():
        result = translator.translate(block)
        if not result.ok or result.block is None:
            continue
        _mesh, summary = describe_block_mesh(manager, result.block)
        if not summary.is_missing:
            continue
        source = geometry_source(
            manager.pack_paths, result.block.namespace, result.block.base_name
        )
        if source.has_geometry:
            unexplained.append(blockstate_key(result.block))

    assert unexplained == [], (
        "these blockstates have elements in the pack but produced no mesh"
    )


@pytest.mark.integration
def test_waterlogged_blocks_expose_their_second_layer():
    """Bedrock stores water as a second block layer; amulet surfaces it as
    extra_blocks, and the pack manager merges the meshes."""
    requires_world()
    census = PaletteCensus()
    with open_chunk(DEFAULT_WORLD, 18, 4, OVERWORLD) as chunk:
        census.add_chunk(chunk)

    layered = [
        block for _key, block in census.iter_blocks() if block.extra_blocks
    ]
    for block in layered:
        assert all(extra.base_name for extra in block.extra_blocks)


@pytest.mark.integration
def test_bake_known_chunk_writes_scene(tmp_path):
    requires_world()
    import json

    import numpy

    from mcread.bake import bake_chunk, write_bake
    from mcread.world_access import open_level

    with open_level(DEFAULT_WORLD) as level:
        bake, atlas = bake_chunk(level, 18, 4, OVERWORLD)

    assert bake.chunk == (18, 4)
    assert bake.opaque.triangle_count > 0
    assert bake.translucent.triangle_count > 0
    assert atlas.width > 0 and atlas.height > 0
    assert bake.y_range[0] >= 60

    positions = numpy.concatenate(
        [
            bake.opaque.positions.reshape(-1, 3),
            bake.translucent.positions.reshape(-1, 3),
        ]
    )
    assert float(positions[:, 1].min()) >= 60.0
    near_trapdoor = (
        (positions[:, 0] >= 296)
        & (positions[:, 0] <= 297)
        & (positions[:, 1] >= 80)
        & (positions[:, 1] <= 81)
        & (positions[:, 2] >= 76)
        & (positions[:, 2] <= 77)
    )
    assert bool(near_trapdoor.any()), "expected geometry at the birch trapdoor"

    scene = write_bake(tmp_path, bake, atlas)
    payload = json.loads(scene.read_text())
    assert payload["chunk"] == [18, 4]
    assert (tmp_path / "atlas.png").is_file()
    assert (tmp_path / "opaque.bin").is_file()
    assert (tmp_path / "debug.obj").is_file()
