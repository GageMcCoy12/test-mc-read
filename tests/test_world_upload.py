from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from mcread.world_upload import WorldUploadError, find_world_root, unpack_mcworld


def _write_save(root: Path, name: str = "Demo") -> None:
    (root / "db").mkdir(parents=True)
    (root / "db" / "CURRENT").write_text("1")
    (root / "level.dat").write_bytes(b"level")
    (root / "levelname.txt").write_text(name)


def test_find_world_root_nested(tmp_path: Path) -> None:
    save = tmp_path / "My World"
    _write_save(save)
    assert find_world_root(tmp_path) == save


def test_unpack_rejects_zip_slip(tmp_path: Path) -> None:
    archive = tmp_path / "evil.mcworld"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", "nope")
    with pytest.raises(WorldUploadError, match="escapes"):
        unpack_mcworld(archive, tmp_path / "out")
    assert not (tmp_path / "outside.txt").exists()


def test_unpack_mcworld_nested_folder(tmp_path: Path) -> None:
    source = tmp_path / "src"
    _write_save(source / "FV-Test-File", "FV-Test-File")
    archive = tmp_path / "world.mcworld"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in (source / "FV-Test-File").rglob("*"):
            zf.write(path, path.relative_to(source).as_posix())
    live = unpack_mcworld(archive, tmp_path / "out")
    assert (live / "level.dat").is_file()
    assert (live / "db" / "CURRENT").is_file()
    assert (live / "levelname.txt").read_text() == "FV-Test-File"
