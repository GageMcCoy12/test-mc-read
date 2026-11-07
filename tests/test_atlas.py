from __future__ import annotations

import numpy
from PIL import Image

from mcread.atlas import PADDING, TILE_SIZE, build_atlas, first_frame, native_tile_size


def test_texture_has_cutout_reads_alpha(tmp_path):
    from mcread.atlas import texture_has_cutout

    solid = tmp_path / "solid.png"
    holes = tmp_path / "holes.png"
    Image.new("RGBA", (16, 16), (80, 80, 80, 255)).save(solid)
    cut = Image.new("RGBA", (16, 16), (0, 180, 0, 255))
    cut.putpixel((0, 0), (0, 180, 0, 0))
    cut.save(holes)
    texture_has_cutout.cache_clear()
    assert texture_has_cutout(str(solid)) is False
    assert texture_has_cutout(str(holes)) is True


def test_first_frame_crops_vertical_strip():
    sheet = Image.new("RGBA", (16, 32), (0, 0, 0, 255))
    sheet.paste(Image.new("RGBA", (16, 16), (255, 0, 0, 255)), (0, 0))
    frame = first_frame(sheet)
    assert frame.size == (16, 16)
    assert frame.getpixel((0, 0)) == (255, 0, 0, 255)


def test_atlas_remap_lands_inside_padded_rects(tmp_path):
    red_path = tmp_path / "red.png"
    blue_path = tmp_path / "blue.png"
    Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(red_path)
    Image.new("RGBA", (16, 16), (0, 0, 255, 255)).save(blue_path)

    atlas = build_atlas([str(red_path), str(blue_path)])
    assert atlas.tile_size == TILE_SIZE
    assert atlas.padding == PADDING
    assert atlas.width == 2 * (TILE_SIZE + 2 * PADDING)
    assert atlas.height == TILE_SIZE + 2 * PADDING

    red_rect = atlas.rects[str(red_path)]
    u0, v0, u1, v1 = red_rect
    origin = atlas.remap_one(numpy.array([0.0, 0.0]), str(red_path))
    corner = atlas.remap_one(numpy.array([1.0, 1.0]), str(red_path))
    numpy.testing.assert_allclose(origin, (u0, v0))
    numpy.testing.assert_allclose(corner, (u1, v1))

    inner_u = (PADDING + 0.5) / atlas.width
    inner_v = (PADDING + 0.5) / atlas.height
    assert u0 < inner_u < u1
    assert v0 < inner_v < v1

    pixel = atlas.image.getpixel((PADDING, PADDING))
    assert pixel[0] == 255
    assert pixel[2] == 0


def test_atlas_keeps_large_entity_textures(tmp_path):
    small = tmp_path / "stone.png"
    big = tmp_path / "chest.png"
    Image.new("RGBA", (16, 16), (80, 80, 80, 255)).save(small)
    sheet = Image.new("RGBA", (64, 64), (120, 80, 40, 255))
    sheet.putpixel((40, 12), (0, 255, 0, 255))
    sheet.save(big)

    assert native_tile_size(str(big)) == 64
    atlas = build_atlas([str(small), str(big)])
    assert atlas.tile_size == 64

    big_rect = atlas.rects[str(big)]
    u0, v0, u1, v1 = big_rect
    sample = atlas.remap_one(numpy.array([40.5 / 64, 12.5 / 64]), str(big))
    x = int(sample[0] * atlas.width)
    y = int(sample[1] * atlas.height)
    assert atlas.image.getpixel((x, y))[1] == 255
    assert u0 < sample[0] < u1
    assert v0 < sample[1] < v1


def test_atlas_accepts_in_memory_extra_tiles():
    extra = Image.new("RGBA", (32, 32), (0, 128, 0, 255))
    atlas = build_atlas([], extras={"banner-cloth:test": extra})
    assert atlas.tile_size == 32
    assert "banner-cloth:test" in atlas.rects
    pixel = atlas.image.getpixel((PADDING, PADDING))
    assert pixel[1] == 128
