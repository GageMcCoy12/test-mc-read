"""Unpack a Bedrock .mcworld / zip into a writable save folder."""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_UNPACKED_BYTES = 1_500_000_000
MAX_CHUNK_BYTES = 4 * 1024 * 1024


class WorldUploadError(ValueError):
    """User-facing upload / unpack failure."""


def _safe_join(root: Path, name: str) -> Path:
    dest = (root / name).resolve()
    if dest != root.resolve() and root.resolve() not in dest.parents:
        raise WorldUploadError("zip path escapes the world folder")
    return dest


def find_world_root(extracted: Path) -> Path:
    """Return the folder that contains level.dat + db/."""
    direct = extracted / "level.dat"
    if direct.is_file() and (extracted / "db").is_dir():
        return extracted
    matches = [
        path.parent
        for path in extracted.rglob("level.dat")
        if path.is_file() and (path.parent / "db").is_dir()
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise WorldUploadError("not a bedrock save — need level.dat and a db/ folder")
    raise WorldUploadError("zip contains more than one bedrock world")


def read_world_name(world: Path) -> str:
    path = world / "levelname.txt"
    if not path.is_file():
        return world.name
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-16", "utf-16-le"):
        try:
            name = raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
        if name:
            return name
    return world.name


def read_spawn_xz(world: Path) -> tuple[int, int]:
    dat = world / "level.dat"
    if not dat.is_file():
        return 0, 0
    try:
        from amulet_nbt import load as load_nbt
    except ImportError:
        return 0, 0
    try:
        with dat.open("rb") as handle:
            handle.read(8)
            tag = load_nbt(handle, compressed=False, little_endian=True)
        compound = getattr(tag, "compound", tag)
        spawn_x = int(compound.get("SpawnX", 0))
        spawn_z = int(compound.get("SpawnZ", 0))
        return spawn_x, spawn_z
    except Exception:
        return 0, 0


def unpack_mcworld(archive: Path, dest: Path) -> Path:
    """Extract a .mcworld/.zip into dest/world and return that save root."""
    dest.mkdir(parents=True, exist_ok=True)
    staging = dest / "_extract"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    unpacked = 0
    try:
        try:
            zf_ctx = zipfile.ZipFile(archive)
        except zipfile.BadZipFile as exc:
            raise WorldUploadError("not a zip / .mcworld") from exc
        with zf_ctx as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or name.startswith("\\"):
                    raise WorldUploadError("zip path escapes the world folder")
                if ".." in Path(name).parts:
                    raise WorldUploadError("zip path escapes the world folder")
                unpacked += max(info.file_size, 0)
                if unpacked > MAX_UNPACKED_BYTES:
                    raise WorldUploadError("world is too large unpacked")
                target = _safe_join(staging, name)
                if info.is_dir() or name.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
        root = find_world_root(staging)
        live = dest / "world"
        if live.exists():
            shutil.rmtree(live)
        shutil.copytree(root, live)
        return live
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def session_dir(root: Path, session_id: str) -> Path:
    path = root / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_tmp_root() -> Path:
    return Path(os.environ.get("MCREAD_TMP", "/tmp/mcread"))
