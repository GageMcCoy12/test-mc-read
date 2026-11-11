from __future__ import annotations

import json
from pathlib import Path

TABLES = Path(__file__).resolve().parent.parent / "viewer" / "client" / "data" / "biome-tints.json"


def test_biome_tints_cover_plains_taiga_and_swamp():
    payload = json.loads(TABLES.read_text(encoding="utf-8"))
    ids = payload["ids"]
    plains = ids["1"]
    taiga = ids["5"]
    swamp = ids["6"]
    assert plains == [0x3F76E4, 0x91BD59, 0x77AB2F]
    assert taiga[0] == 0x3F76E4
    assert taiga[1] == 0x86B783
    assert taiga[2] == 0x68A464
    assert swamp[0] == 0x617B64
    assert swamp[1] == 0x6A7039
    assert payload["fallback"] == [0x3F76E4, 0x91BD59, 0x77AB2F]
    assert payload["meta"]["count"] >= 80
    assert len({row[0] for row in ids.values()}) > 1
