"""Describe amulet blocks as text."""

from __future__ import annotations

from amulet.api.block import Block

AIR_BASE_NAMES = frozenset({"air", "cave_air", "void_air", "empty"})
FLUID_BASE_NAMES = frozenset({"water", "lava", "flowing_water", "flowing_lava"})


def is_empty_block(block: Block) -> bool:
    return block.base_name in AIR_BASE_NAMES


def is_fluid_block(block: Block) -> bool:
    return block.base_name in FLUID_BASE_NAMES


def format_property_value(value: object) -> str:
    for attr in ("py_str", "py_int", "py_float"):
        if hasattr(value, attr):
            return str(getattr(value, attr))
    return str(value)


def blockstate_key(block: Block) -> str:
    """`namespace:name[prop=value,...]`, sorted so it is stable across runs."""
    key = block.namespaced_name
    if block.properties:
        props = ",".join(
            f"{name}={format_property_value(value)}"
            for name, value in sorted(block.properties.items())
        )
        key = f"{key}[{props}]"
    return key


def format_block_english(block: Block) -> str:
    pretty_name = block.base_name.replace("_", " ")
    namespaced = block.namespaced_name.removeprefix("universal_")
    parts = [pretty_name, f"({namespaced})"]
    if block.properties:
        props = ", ".join(
            f"{key}={format_property_value(value)}"
            for key, value in sorted(block.properties.items())
        )
        parts.append(f"with {props}")
    extras = [extra for extra in block.extra_blocks if not is_empty_block(extra)]
    if extras:
        extra_text = ", ".join(format_block_english(extra) for extra in extras)
        parts.append(f"plus {extra_text}")
    return " ".join(parts)
