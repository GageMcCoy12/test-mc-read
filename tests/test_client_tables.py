from __future__ import annotations

import json
from pathlib import Path

TABLES = Path(__file__).resolve().parent.parent / "viewer" / "client" / "data" / "bedrock-to-java.json"


def test_client_tables_cover_the_birch_trapdoor_spike():
    payload = json.loads(TABLES.read_text(encoding="utf-8"))
    row = payload["map"]["minecraft:birch_trapdoor[direction=0,open_bit=1,upside_down_bit=0]"]
    assert row["java"].startswith("minecraft:birch_trapdoor[")
    assert "facing=east" in row["java"]
    assert "open=true" in row["java"]


def test_client_tables_map_stone_and_logs():
    payload = json.loads(TABLES.read_text(encoding="utf-8"))
    assert payload["map"]["minecraft:stone"]["java"] == "minecraft:stone"
    oak = payload["map"]["minecraft:oak_log[pillar_axis=y]"]["java"]
    assert oak == "minecraft:oak_log[axis=y]"
    assert payload["meta"]["count"] > 10_000
