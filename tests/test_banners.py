from __future__ import annotations

from pathlib import Path

import numpy
from amulet.api.block import Block
from amulet_nbt import CompoundTag, IntTag, ListTag, NamedTag, StringTag
from PIL import Image
from conftest import FakeBlockEntity, FakeChunk, filled_section

from mcread.banners import (
    BannerPainter,
    apply_banner_patterns,
    cloth_from_mesh,
    composite_cloth,
    is_banner_cloth_texture,
    layer_pattern,
    patterns_from_nbt,
    resolve_dye,
    resolve_pattern,
    sample_dye_rgb,
)
from mcread.mesh import BlockGrid
from mcread.resolve import SKIP_EMPTY, ResolvedBlock
from minecraft_model_reader.api.mesh.block.block_mesh import Transparency
from minecraft_model_reader.api.mesh.block.cube import get_unit_cube


def banner_nbt(*layers: tuple[str, int]) -> NamedTag:
    patterns = ListTag(
        [
            CompoundTag({"Pattern": StringTag(code), "Color": IntTag(color)})
            for code, color in layers
        ]
    )
    return NamedTag(CompoundTag({"utags": CompoundTag({"Patterns": patterns})}))


def test_resolve_pattern_reads_bedrock_codes_and_java_names():
    assert resolve_pattern("cr") == "cross"
    assert resolve_pattern("sc") == "straight_cross"
    assert resolve_pattern("cre") == "creeper"
    assert resolve_pattern("minecraft:border") == "border"
    assert resolve_pattern("nope") is None


def test_resolve_dye_uses_bedrock_wool_order():
    assert resolve_dye(0) == "white"
    assert resolve_dye(14) == "red"
    assert resolve_dye(15) == "black"
    assert resolve_dye("lime") == "lime"
    assert resolve_dye(99) is None


def test_patterns_from_nbt_keeps_draw_order_and_skips_junk():
    nbt = banner_nbt(("cr", 14), ("nope", 0), ("bo", 0))
    assert patterns_from_nbt(nbt) == (("cross", "red"), ("border", "white"))


def test_patterns_from_nbt_tolerates_missing_list():
    assert patterns_from_nbt(NamedTag(CompoundTag({}))) == ()
    assert patterns_from_nbt(None) == ()


def test_is_banner_cloth_skips_the_crossbar():
    assert is_banner_cloth_texture("/pack/banner_white.png")
    assert not is_banner_cloth_texture("/pack/banner_base.png")
    assert not is_banner_cloth_texture("/pack/stone.png")
    assert cloth_from_mesh(("banner_base.png", "banner_green.png")) == "banner_green.png"


def test_layer_pattern_tints_mask_and_keeps_empty_pixels():
    cloth = Image.new("RGBA", (8, 8), (240, 240, 240, 255))
    cloth.putpixel((0, 0), (0, 0, 0, 0))
    pattern = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    pattern.putpixel((4, 4), (255, 255, 255, 255))
    painted = layer_pattern(cloth, pattern, (200, 20, 20))
    assert painted.getpixel((4, 4))[0] > 150
    assert painted.getpixel((4, 4))[1] < 40
    assert painted.getpixel((0, 0))[3] == 0
    assert painted.getpixel((1, 1))[:3] == (240, 240, 240)


def test_composite_cloth_stacks_in_order():
    cloth = Image.new("RGBA", (4, 4), (255, 255, 255, 255))
    first = Image.new("RGBA", (4, 4), (255, 255, 255, 255))
    second = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    second.putpixel((0, 0), (255, 255, 255, 255))
    painted = composite_cloth(cloth, [(first, (0, 0, 200)), (second, (200, 0, 0))])
    assert painted.getpixel((0, 0))[0] > 150
    assert painted.getpixel((1, 1))[2] > 150


def test_sample_dye_rgb_ignores_clear_pixels():
    image = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    image.putpixel((0, 0), (10, 20, 30, 255))
    image.putpixel((1, 0), (10, 20, 30, 255))
    assert sample_dye_rgb(image) == (10, 20, 30)


class _Manager:
    def __init__(self, paths: dict[str, str]) -> None:
        self.paths = paths
        self.missing_no = "missing"

    def get_texture_path(self, namespace: str, relative: str) -> str:
        return self.paths.get(relative, self.missing_no)


def test_painter_and_grid_apply_one_banner(tmp_path):
    cloth = tmp_path / "banner_white.png"
    dye = tmp_path / "banner_red.png"
    pattern = tmp_path / "cross.png"
    Image.new("RGBA", (16, 16), (230, 230, 230, 255)).save(cloth)
    Image.new("RGBA", (16, 16), (180, 30, 30, 255)).save(dye)
    mask = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for x in range(16):
        mask.putpixel((x, 8), (255, 255, 255, 255))
    mask.save(pattern)

    manager = _Manager(
        {
            "entity/banner/cross": str(pattern),
            "block/banner/banner_red": str(dye),
        }
    )
    mesh = get_unit_cube(
        str(cloth), str(cloth), str(cloth), str(cloth), str(cloth), str(cloth),
        Transparency.Partial,
    )
    banner = ResolvedBlock(
        java_block=None,
        mesh=mesh,
        is_opaque=False,
        transparency=Transparency.Partial,
        is_fluid=False,
        is_missing=False,
        is_empty=False,
        extra_needed=False,
        skip=False,
    )
    chunk = FakeChunk(
        palette=(Block("universal_minecraft", "air"), Block("universal_minecraft", "wall_banner")),
        sections={0: filled_section(1)},
        block_entities=[
            FakeBlockEntity("universal_minecraft:banner", 0, 0, 0, banner_nbt(("cr", 14))),
        ],
    )
    grid = BlockGrid()
    grid.add_chunk(chunk, [SKIP_EMPTY, banner])
    painter = BannerPainter(manager)
    apply_banner_patterns(grid, painter)

    key = grid.banner_cloth_at(0, 0, 0)
    assert key is not None
    assert key in painter.images
    painted = numpy.asarray(painter.images[key])
    assert painted[8, 8, 0] > painted[8, 8, 1]
