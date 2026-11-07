"""Paint Bedrock banner Patterns onto the cloth texture.

Geometry stays on the block model. Patterns are per-block-entity NBT, so we
composite a new 64x64 cloth and swap just that texture at that position.

Pattern codes and dye indices are Minecraft's own tables. The pack only
ships the mask PNGs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

import numpy
from PIL import Image

# Bedrock `Pattern` string -> Java `textures/entity/banner/{name}.png`
# https://minecraft.wiki/w/Banner/Patterns
PATTERN_BY_CODE: dict[str, str] = {
    "b": "base",
    "bs": "stripe_bottom",
    "ts": "stripe_top",
    "ls": "stripe_left",
    "rs": "stripe_right",
    "cs": "stripe_center",
    "ms": "stripe_middle",
    "drs": "stripe_downright",
    "dls": "stripe_downleft",
    "ss": "small_stripes",
    "cr": "cross",
    "sc": "straight_cross",
    "ld": "diagonal_left",
    "rud": "diagonal_right",
    "lud": "diagonal_up_left",
    "rd": "diagonal_up_right",
    "vh": "half_vertical",
    "vhr": "half_vertical_right",
    "hh": "half_horizontal",
    "hhb": "half_horizontal_bottom",
    "bl": "square_bottom_left",
    "br": "square_bottom_right",
    "tl": "square_top_left",
    "tr": "square_top_right",
    "bt": "triangle_bottom",
    "tt": "triangle_top",
    "bts": "triangles_bottom",
    "tts": "triangles_top",
    "mc": "circle",
    "mr": "rhombus",
    "bo": "border",
    "cbo": "curly_border",
    "bri": "bricks",
    "gra": "gradient",
    "gru": "gradient_up",
    "cre": "creeper",
    "sku": "skull",
    "flo": "flower",
    "moj": "mojang",
    "glb": "globe",
    "pig": "piglin",
    "flw": "flow",
    "gus": "guster",
}

# Bedrock banner Color / Base: 0 white ... 15 black, same as wool.
DYE_NAMES: tuple[str, ...] = (
    "white",
    "orange",
    "magenta",
    "light_blue",
    "yellow",
    "lime",
    "pink",
    "gray",
    "light_gray",
    "cyan",
    "purple",
    "blue",
    "brown",
    "green",
    "red",
    "black",
)

_PATTERN_NAMES = frozenset(PATTERN_BY_CODE.values())
_DYE_INDEX = {name: index for index, name in enumerate(DYE_NAMES)}


def is_banner_entity_name(name: str) -> bool:
    return name.rsplit(":", 1)[-1] in {"banner", "wall_banner"}


def is_banner_cloth_texture(path: str) -> bool:
    """The coloured sheet, not the wooden crossbar."""
    name = Path(path).name.lower()
    return name.startswith("banner_") and name != "banner_base.png"


def cloth_from_mesh(textures: Iterable[str]) -> Optional[str]:
    for texture in textures:
        if is_banner_cloth_texture(texture):
            return texture
    return None


def resolve_pattern(code: str) -> Optional[str]:
    raw = code.lower().split(":")[-1]
    if raw in PATTERN_BY_CODE:
        return PATTERN_BY_CODE[raw]
    if raw in _PATTERN_NAMES:
        return raw
    return None


def resolve_dye(value: object) -> Optional[str]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        if 0 <= value < len(DYE_NAMES):
            return DYE_NAMES[value]
        return None
    name = str(value).lower().split(":")[-1]
    if name in _DYE_INDEX:
        return name
    return None


def _as_compound(tag: Any) -> Optional[Any]:
    if tag is None:
        return None
    compound = getattr(tag, "compound", None)
    if compound is not None and hasattr(compound, "items"):
        return compound
    if hasattr(tag, "items") and not isinstance(tag, (str, bytes)):
        return tag
    return None


def _tag_int(tag: Any) -> Optional[int]:
    if tag is None:
        return None
    if isinstance(tag, bool):
        return None
    if isinstance(tag, int):
        return int(tag)
    for attr in ("py_int", "py_data"):
        if hasattr(tag, attr):
            try:
                return int(getattr(tag, attr))
            except (TypeError, ValueError):
                return None
    return None


def _tag_str(tag: Any) -> Optional[str]:
    if tag is None:
        return None
    if isinstance(tag, str):
        return tag
    for attr in ("py_str", "py_data"):
        if hasattr(tag, attr):
            value = getattr(tag, attr)
            if isinstance(value, str):
                return value
    return None


def patterns_from_nbt(nbt: Any) -> tuple[tuple[str, str], ...]:
    """Return ((pattern_name, dye_name), ...) in draw order. Skip unknowns."""
    root = _as_compound(nbt)
    if root is None:
        return ()
    utags = _as_compound(root.get("utags"))
    raw = None
    if utags is not None:
        raw = utags.get("Patterns")
    if raw is None:
        raw = root.get("Patterns")
    if raw is None:
        return ()
    try:
        items = list(raw)
    except TypeError:
        return ()

    layers: list[tuple[str, str]] = []
    for item in items:
        compound = _as_compound(item)
        if compound is None:
            continue
        pattern = resolve_pattern(_tag_str(compound.get("Pattern")) or "")
        dye = resolve_dye(_tag_int(compound.get("Color")))
        if dye is None:
            dye = resolve_dye(_tag_str(compound.get("Color")) or "")
        if pattern is None or dye is None:
            continue
        layers.append((pattern, dye))
    return tuple(layers)


def sample_dye_rgb(image: Image.Image) -> tuple[int, int, int]:
    """Median opaque pixel. Matches the cloth shade the pack already picked."""
    pixels = numpy.asarray(image.convert("RGBA"), dtype=numpy.uint8).reshape(-1, 4)
    opaque = pixels[pixels[:, 3] > 200]
    if opaque.size == 0:
        return (255, 255, 255)
    return tuple(int(v) for v in numpy.median(opaque[:, :3], axis=0))


def layer_pattern(
    cloth: Image.Image,
    pattern: Image.Image,
    dye: tuple[int, int, int],
) -> Image.Image:
    """Tint the mask with `dye` and alpha-composite it onto the cloth."""
    base = numpy.asarray(cloth.convert("RGBA"), dtype=numpy.float32)
    mask = numpy.asarray(pattern.convert("RGBA").resize(cloth.size, Image.Resampling.NEAREST), dtype=numpy.float32)
    luminance = mask[:, :, 0] / 255.0
    alpha = (mask[:, :, 3] / 255.0) * (base[:, :, 3] / 255.0)
    out = base.copy()
    out[:, :, 0] = luminance * dye[0] * alpha + base[:, :, 0] * (1.0 - alpha)
    out[:, :, 1] = luminance * dye[1] * alpha + base[:, :, 1] * (1.0 - alpha)
    out[:, :, 2] = luminance * dye[2] * alpha + base[:, :, 2] * (1.0 - alpha)
    return Image.fromarray(numpy.clip(out, 0, 255).astype(numpy.uint8), "RGBA")


def composite_cloth(
    cloth: Image.Image,
    layers: Iterable[tuple[Image.Image, tuple[int, int, int]]],
) -> Image.Image:
    painted = cloth.convert("RGBA")
    for pattern, dye in layers:
        painted = layer_pattern(painted, pattern, dye)
    return painted


def cloth_key(base_cloth: str, layers: tuple[tuple[str, str], ...]) -> str:
    pattern_part = ",".join(f"{name}={dye}" for name, dye in layers)
    return f"banner-cloth:{Path(base_cloth).name}:{pattern_part}"


class BannerPainter:
    """Composite unique banner cloths and keep them for the atlas."""

    def __init__(self, manager) -> None:
        self.manager = manager
        self.images: dict[str, Image.Image] = {}
        self._dye_rgb: dict[str, tuple[int, int, int]] = {}

    def paint(self, base_cloth: str, layers: tuple[tuple[str, str], ...]) -> Optional[str]:
        if not layers:
            return None
        key = cloth_key(base_cloth, layers)
        if key in self.images:
            return key
        try:
            cloth = Image.open(base_cloth)
        except (OSError, FileNotFoundError):
            return None
        painted_layers: list[tuple[Image.Image, tuple[int, int, int]]] = []
        for pattern_name, dye_name in layers:
            pattern = self._pattern_image(pattern_name)
            dye = self._dye_rgb_for(dye_name)
            if pattern is None or dye is None:
                continue
            painted_layers.append((pattern, dye))
        if not painted_layers:
            return None
        self.images[key] = composite_cloth(cloth, painted_layers)
        return key

    def _pattern_image(self, name: str) -> Optional[Image.Image]:
        path = self.manager.get_texture_path("minecraft", f"entity/banner/{name}")
        if not path or path == getattr(self.manager, "missing_no", None):
            return None
        try:
            return Image.open(path)
        except (OSError, FileNotFoundError):
            return None

    def _dye_rgb_for(self, name: str) -> Optional[tuple[int, int, int]]:
        cached = self._dye_rgb.get(name)
        if cached is not None:
            return cached
        path = self.manager.get_texture_path("minecraft", f"block/banner/banner_{name}")
        if not path or path == getattr(self.manager, "missing_no", None):
            return None
        try:
            image = Image.open(path)
        except (OSError, FileNotFoundError):
            return None
        rgb = sample_dye_rgb(image)
        self._dye_rgb[name] = rgb
        return rgb


def apply_banner_patterns(grid, painter: BannerPainter) -> None:
    """Read banner NBT on loaded chunks and register painted cloths."""
    for cx, cz in grid.visible_chunks():
        chunk = grid.chunk_at(cx, cz)
        if chunk is None:
            continue
        for entity in getattr(chunk, "block_entities", ()) or ():
            name = getattr(entity, "namespaced_name", "")
            if not is_banner_entity_name(str(name)):
                continue
            layers = patterns_from_nbt(getattr(entity, "nbt", None))
            if not layers:
                continue
            x, y, z = int(entity.x), int(entity.y), int(entity.z)
            entry = grid.entry_at(x, y, z)
            if entry is None or entry.mesh is None:
                continue
            cloth = cloth_from_mesh(entry.mesh.textures)
            if cloth is None:
                continue
            key = painter.paint(cloth, layers)
            if key is not None:
                grid.set_banner_cloth((x, y, z), key)
    grid.set_banner_images(painter.images)
