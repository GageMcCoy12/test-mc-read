from __future__ import annotations

import numpy
from minecraft_model_reader.api.mesh.block.block_mesh import Transparency
from minecraft_model_reader.api.mesh.block.cube import get_unit_cube
from PIL import Image

from conftest import FakeChunk
from mcread.atlas import build_atlas
from mcread.mesh import BlockGrid, IdentityAtlas, concat_meshes, mesh_chunk
from mcread.resolve import SKIP_EMPTY, ResolvedBlock


def _cube(
    *,
    opaque: bool,
    fluid: bool = False,
    texture: str = "dummy.png",
    transparency: Transparency | None = None,
) -> ResolvedBlock:
    if transparency is None:
        transparency = Transparency.FullOpaque if opaque else Transparency.FullTranslucent
    mesh = get_unit_cube(
        texture, texture, texture, texture, texture, texture, transparency
    )
    return ResolvedBlock(
        java_block=None,
        mesh=mesh,
        is_opaque=opaque,
        transparency=transparency,
        is_fluid=fluid,
        is_missing=False,
        is_empty=False,
        extra_needed=False,
        skip=False,
    )


def _grid(section: numpy.ndarray, resolved: list[ResolvedBlock], *, cy: int = 0) -> BlockGrid:
    chunk = FakeChunk(cx=0, cz=0, sections={cy: section})
    grid = BlockGrid()
    grid.add_chunk(chunk, resolved)
    return grid


def test_concat_meshes_shifts_indices():
    first = _mesh(
        positions=[0, 0, 0, 1, 0, 0, 0, 1, 0],
        indices=[0, 1, 2],
    )
    second = _mesh(
        positions=[2, 0, 0, 3, 0, 0, 2, 1, 0],
        indices=[0, 1, 2],
    )
    merged = concat_meshes([first, second])
    assert merged.vertex_count == 6
    assert list(merged.indices) == [0, 1, 2, 3, 4, 5]


def _mesh(*, positions, indices):
    from mcread.mesh import BakedMesh

    n = len(positions) // 3
    return BakedMesh(
        positions=numpy.array(positions, dtype=numpy.float32),
        uvs=numpy.zeros(n * 2, dtype=numpy.float32),
        colors=numpy.ones(n * 3, dtype=numpy.float32),
        indices=numpy.array(indices, dtype=numpy.uint32),
    )


def test_unit_cube_is_0_1_triangles():
    mesh = get_unit_cube("a", "a", "a", "a", "a", "a")
    assert mesh.face_mode == 3
    for verts in mesh.verts.values():
        points = verts.reshape(-1, 3)
        assert points.min() >= 0.0
        assert points.max() <= 1.0
        assert points.shape[0] % 1 == 0
    for faces in mesh.faces.values():
        assert faces.size % 3 == 0


def test_single_stone_emits_six_faces():
    section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    section[0, 0, 0] = 1
    grid = _grid(section, [SKIP_EMPTY, _cube(opaque=True)])
    bake = mesh_chunk(grid, 0, 0, IdentityAtlas())
    assert bake.opaque.triangle_count == 12
    assert bake.translucent.empty()


def test_two_by_two_stone_emits_only_outer_faces():
    section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    for x in range(2):
        for y in range(2):
            for z in range(2):
                section[x, y, z] = 1
    grid = _grid(section, [SKIP_EMPTY, _cube(opaque=True)])
    bake = mesh_chunk(grid, 0, 0, IdentityAtlas())
    assert bake.opaque.triangle_count == 48
    assert bake.translucent.empty()


def test_water_against_water_drops_shared_face():
    section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    section[0, 0, 0] = 1
    section[1, 0, 0] = 1
    grid = _grid(section, [SKIP_EMPTY, _cube(opaque=False, fluid=True)])
    bake = mesh_chunk(grid, 0, 0, IdentityAtlas())
    assert bake.opaque.empty()
    assert bake.translucent.triangle_count == 20


def test_stone_face_against_water_is_kept():
    section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    section[0, 0, 0] = 1
    section[1, 0, 0] = 2
    grid = _grid(
        section,
        [
            SKIP_EMPTY,
            _cube(opaque=False, fluid=True, texture="water.png"),
            _cube(opaque=True, texture="stone.png"),
        ],
    )
    bake = mesh_chunk(grid, 0, 0, IdentityAtlas())
    assert bake.opaque.triangle_count == 12
    assert bake.translucent.triangle_count == 10


def test_partial_blocks_go_to_opaque_pass():
    """Stairs, slabs, and walls are Partial, not see-through."""
    section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    section[0, 0, 0] = 1
    grid = _grid(
        section,
        [
            SKIP_EMPTY,
            _cube(
                opaque=False,
                transparency=Transparency.Partial,
                texture="stair.png",
            ),
        ],
    )
    bake = mesh_chunk(grid, 0, 0, IdentityAtlas())
    assert bake.opaque.triangle_count == 12
    assert bake.translucent.empty()


def test_hidden_neighbor_chunk_does_not_cull_edge_faces():
    section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    section[15, 0, 0] = 1
    target = FakeChunk(cx=0, cz=0, sections={0: section})
    neighbor_section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    neighbor_section[0, 0, 0] = 1
    neighbor = FakeChunk(cx=1, cz=0, sections={0: neighbor_section})
    stone = _cube(opaque=True)
    grid = BlockGrid()
    grid.add_chunk(target, [SKIP_EMPTY, stone], visible=True)
    grid.add_chunk(neighbor, [SKIP_EMPTY, stone], visible=False)

    bake = mesh_chunk(grid, 0, 0, IdentityAtlas())
    assert bake.opaque.triangle_count == 12


def test_visible_neighbor_chunk_still_culls_shared_face():
    section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    section[15, 0, 0] = 1
    target = FakeChunk(cx=0, cz=0, sections={0: section})
    neighbor_section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    neighbor_section[0, 0, 0] = 1
    neighbor = FakeChunk(cx=1, cz=0, sections={0: neighbor_section})
    stone = _cube(opaque=True)
    grid = BlockGrid()
    grid.add_chunk(target, [SKIP_EMPTY, stone], visible=True)
    grid.add_chunk(neighbor, [SKIP_EMPTY, stone], visible=True)

    bake = mesh_chunk(grid, 0, 0, IdentityAtlas())
    assert bake.opaque.triangle_count == 10


def test_cutout_neighbor_does_not_hide_stone_face():
    """Leaves look solid to the pack reader but must not occlude."""
    section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    section[0, 0, 0] = 1
    section[1, 0, 0] = 2
    grid = _grid(
        section,
        [
            SKIP_EMPTY,
            _cube(opaque=True, texture="stone.png"),
            _cube(
                opaque=False,
                transparency=Transparency.FullOpaque,
                texture="leaves.png",
            ),
        ],
    )
    bake = mesh_chunk(grid, 0, 0, IdentityAtlas())
    # stone keeps the shared face; the leaf face against stone is still culled
    assert bake.opaque.triangle_count == 22


def test_min_y_skips_below_and_keeps_floor_faces():
    section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    section[0, 4, 0] = 1
    section[0, 5, 0] = 1
    grid = _grid(section, [SKIP_EMPTY, _cube(opaque=True)])
    bake = mesh_chunk(grid, 0, 0, IdentityAtlas(), min_y=5)
    assert bake.opaque.triangle_count == 12
    assert bake.y_range[0] == 5
    ys = bake.opaque.positions.reshape(-1, 3)[:, 1]
    assert ys.min() >= 5.0


def test_banner_cloth_override_uses_painted_atlas_tile(tmp_path):
    cloth = tmp_path / "banner_white.png"
    Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(cloth)
    section = numpy.zeros((16, 16, 16), dtype=numpy.uint32)
    section[0, 0, 0] = 1
    grid = _grid(
        section,
        [
            SKIP_EMPTY,
            _cube(
                opaque=False,
                transparency=Transparency.Partial,
                texture=str(cloth),
            ),
        ],
    )
    painted = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    grid.set_banner_cloth((0, 0, 0), "banner-cloth:flag")
    grid.set_banner_images({"banner-cloth:flag": painted})
    atlas = build_atlas(grid.textures_for_visible(), extras=grid.banner_extras())
    bake = mesh_chunk(grid, 0, 0, atlas)
    uvs = bake.opaque.uvs.reshape(-1, 2)
    x = int(uvs[0, 0] * atlas.width)
    y = int(uvs[0, 1] * atlas.height)
    assert atlas.image.getpixel((x, y))[0] == 255
    assert atlas.image.getpixel((x, y))[1] == 0
