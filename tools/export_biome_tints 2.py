"""Dump Bedrock biome IDs → Java grass/water/foliage tints for the browser baker."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcread.translate import translation_manager

OUT_PATH = PROJECT_ROOT / "viewer" / "client" / "data" / "biome-tints.json"
JAVA_TAG = "26.2"
PLAINS_WATER = 0x3F76E4
PLAINS_GRASS = 0x91BD59
PLAINS_FOLIAGE = 0x77AB2F

DATA_BASES = (
    f"https://cdn.jsdelivr.net/gh/misode/mcmeta@{JAVA_TAG}-data/data/minecraft/worldgen/biome",
    f"https://raw.githubusercontent.com/misode/mcmeta/{JAVA_TAG}-data/data/minecraft/worldgen/biome",
    "https://cdn.jsdelivr.net/gh/misode/mcmeta@data/data/minecraft/worldgen/biome",
)
COLORMAP_URLS = {
    "grass": (
        f"https://assets.mcasset.cloud/{JAVA_TAG}/assets/minecraft/textures/colormap/grass.png",
        f"https://raw.githubusercontent.com/misode/mcmeta/{JAVA_TAG}-assets/assets/minecraft/textures/colormap/grass.png",
    ),
    "foliage": (
        f"https://assets.mcasset.cloud/{JAVA_TAG}/assets/minecraft/textures/colormap/foliage.png",
        f"https://raw.githubusercontent.com/misode/mcmeta/{JAVA_TAG}-assets/assets/minecraft/textures/colormap/foliage.png",
    ),
}


def _fetch(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": "mcread-biome-tints"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if getattr(response, "status", 200) >= 400:
                return None
            return response.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _fetch_first(urls: tuple[str, ...]) -> bytes:
    for url in urls:
        payload = _fetch(url)
        if payload:
            return payload
    raise RuntimeError(f"could not fetch any of {urls[0]}...")


def _pack_rgb(pixel: tuple[int, ...]) -> int:
    return (pixel[0] << 16) | (pixel[1] << 8) | pixel[2]


def _sample(image: Image.Image, temperature: float, downfall: float) -> int:
    temp = min(max(temperature, 0.0), 1.0)
    down = min(max(downfall, 0.0), 1.0) * temp
    x = int((1.0 - temp) * 255.0)
    y = int((1.0 - down) * 255.0)
    x = min(max(x, 0), image.width - 1)
    y = min(max(y, 0), image.height - 1)
    return _pack_rgb(image.getpixel((x, y)))


def _apply_grass_modifier(color: int, modifier: str | None) -> int:
    if modifier == "swamp":
        return 0x6A7039
    if modifier == "dark_forest":
        return ((color & 0xFEFEFE) + 0x28340A) >> 1
    return color


def _java_name(bedrock_version, java_version, biome_id: int) -> str:
    raw = bedrock_version.biome.unpack(biome_id)
    universal = bedrock_version.biome.to_universal(raw)
    java = java_version.biome.from_universal(universal)
    if java.startswith("minecraft:"):
        return java.split(":", 1)[1]
    return java or "plains"


def _effects_color(effects: dict, key: str) -> int | None:
    value = effects.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().removeprefix("#")
        if text:
            try:
                return int(text, 16)
            except ValueError:
                return None
    return None


def export_tints(path: Path = OUT_PATH) -> dict:
    manager = translation_manager()
    bedrock_num = max(manager.version_numbers("bedrock"))
    java_num = max(manager.version_numbers("java"))
    bedrock = manager.get_version("bedrock", bedrock_num)
    java = manager.get_version("java", java_num)

    grass_map = Image.open(io.BytesIO(_fetch_first(COLORMAP_URLS["grass"]))).convert("RGB")
    foliage_map = Image.open(io.BytesIO(_fetch_first(COLORMAP_URLS["foliage"]))).convert("RGB")

    biome_json: dict[str, dict] = {}
    ids: dict[str, list[int]] = {}
    missing: list[str] = []

    for name, biome_id in sorted(
        bedrock.biome._biome_str_to_int.items(), key=lambda item: item[1] if item[1] is not None else -1
    ):
        if biome_id is None:
            continue
        java_name = _java_name(bedrock, java, biome_id)
        if java_name not in biome_json:
            payload = None
            for base in DATA_BASES:
                payload = _fetch(f"{base}/{java_name}.json")
                if payload:
                    break
            if payload:
                biome_json[java_name] = json.loads(payload)
            else:
                missing.append(f"{name}->{java_name}")
                biome_json[java_name] = {}
        spec = biome_json[java_name]
        effects = spec.get("effects") or {}
        temperature = float(spec.get("temperature", 0.8))
        downfall = float(spec.get("downfall", 0.4))
        water = _effects_color(effects, "water_color") or PLAINS_WATER
        grass = _effects_color(effects, "grass_color")
        if grass is None:
            grass = _sample(grass_map, temperature, downfall)
        grass = _apply_grass_modifier(grass, effects.get("grass_color_modifier"))
        foliage = _effects_color(effects, "foliage_color")
        if foliage is None:
            foliage = _sample(foliage_map, temperature, downfall)
        ids[str(biome_id)] = [water, grass, foliage]

    payload = {
        "meta": {
            "bedrock": list(bedrock_num),
            "java": list(java_num),
            "tag": JAVA_TAG,
            "count": len(ids),
            "missing": missing,
        },
        "fallback": [PLAINS_WATER, PLAINS_GRASS, PLAINS_FOLIAGE],
        "ids": ids,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def main() -> None:
    payload = export_tints()
    meta = payload["meta"]
    plains = payload["ids"]["1"]
    print(
        f"wrote {OUT_PATH.relative_to(PROJECT_ROOT)} "
        f"({meta['count']} biomes, missing {len(meta['missing'])}) "
        f"plains water #{plains[0]:06x} grass #{plains[1]:06x} foliage #{plains[2]:06x}"
    )
    if meta["missing"]:
        print("missing java json:", ", ".join(meta["missing"][:12]))


if __name__ == "__main__":
    main()
