"""Dump Bedrock → Java blockstate tables for the browser baker.

The worker cannot run PyMCTranslate (amulet-nbt is a C extension). This writes
the finite lookup that bake actually needs: every vanilla Bedrock spec combo
for the newest translate version, plus a name-only fallback.
"""

from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amulet.api.block import Block
from mcread.blocks import blockstate_key
from mcread.translate import JavaTranslator, translation_manager

OUT_PATH = PROJECT_ROOT / "viewer" / "client" / "data" / "bedrock-to-java.json"


def _java_key(block: Block | None) -> str | None:
    if block is None:
        return None
    if block.namespace.startswith("universal"):
        return None
    return blockstate_key(block)


def _translate(bedrock_version, java: JavaTranslator, block: Block) -> dict | None:
    try:
        universal, _entity, extra_needed = bedrock_version.block.to_universal(block)
    except Exception:
        return None
    result = java.translate(universal)
    key = _java_key(result.block)
    if key is None:
        return None
    return {
        "java": key,
        "extra_needed": bool(extra_needed or result.extra_needed),
    }


def export_tables(path: Path = OUT_PATH) -> dict:
    manager = translation_manager()
    bedrock_num = max(manager.version_numbers("bedrock"))
    java_num = max(manager.version_numbers("java"))
    bedrock = manager.get_version("bedrock", bedrock_num)
    java = JavaTranslator(java_num)

    mapping: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    skipped = 0

    for namespace in bedrock.block.namespaces():
        for base_name in bedrock.block.base_names(namespace):
            spec = bedrock.block.get_specification(namespace, base_name)
            namespaced = f"{namespace}:{base_name}"
            keys = list(spec.valid_properties)
            values = [spec.valid_properties[key] for key in keys]
            combos = [dict(zip(keys, combo)) for combo in product(*values)] if keys else [{}]
            default_props = dict(spec.default_properties)
            default_block = Block(namespace, base_name, default_props)
            default_row = _translate(bedrock, java, default_block)
            if default_row is not None:
                by_name[namespaced] = default_row
                mapping[blockstate_key(default_block)] = default_row
            for props in combos:
                block = Block(namespace, base_name, props)
                row = _translate(bedrock, java, block)
                if row is None:
                    skipped += 1
                    continue
                mapping[blockstate_key(block)] = row

    payload = {
        "meta": {
            "bedrock": list(bedrock_num),
            "java": list(java_num),
            "count": len(mapping),
            "names": len(by_name),
            "skipped": skipped,
        },
        "map": mapping,
        "by_name": by_name,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def main() -> None:
    payload = export_tables()
    meta = payload["meta"]
    print(
        f"wrote {OUT_PATH.relative_to(PROJECT_ROOT)} "
        f"({meta['count']} states, {meta['names']} names, "
        f"skipped {meta['skipped']}) "
        f"bedrock {tuple(meta['bedrock'])} → java {tuple(meta['java'])}"
    )


if __name__ == "__main__":
    main()
