"""Serve the chunk viewer and rebake on demand.

The browser stays a thin client. This process opens a Bedrock save, runs the
same bake pipeline as tools/bake_chunk.py, and writes viewer/generated/.

On Cloud Run, users upload a .mcworld (chunked, so we stay under the 32MB
request cap). Sessions live in $MCREAD_TMP and die with the instance.

Run: .venv/bin/python tools/serve_viewer.py
Then open http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import threading
import uuid
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amulet.api.errors import ChunkDoesNotExist, ChunkLoadError

import mcread.bake
import mcread.emit
import mcread.light
from mcread.bake import DEFAULT_MIN_Y, DEFAULT_RADIUS, MAX_RADIUS
from mcread.resolve import PaletteResolver
from mcread.world_access import DEFAULT_WORLD, OVERWORLD, open_level
from mcread.world_upload import (
    MAX_CHUNK_BYTES,
    MAX_UPLOAD_BYTES,
    WorldUploadError,
    default_tmp_root,
    read_spawn_xz,
    read_world_name,
    session_dir,
    unpack_mcworld,
)

VIEWER_DIR = PROJECT_ROOT / "viewer"
GENERATED_DIR = VIEWER_DIR / "generated"
DEFAULT_PORT = 8765
SESSION_COOKIE = "mcread_sid"

_bake_lock = threading.Lock()
_upload_lock = threading.Lock()
_resolver: PaletteResolver | None = None
_uploads: dict[str, dict[str, Any]] = {}


def _get_resolver() -> PaletteResolver:
    global _resolver
    if _resolver is None:
        _resolver = PaletteResolver()
    return _resolver


def _reload_lighting_modules() -> None:
    """Pick up emit/light/bake edits without restarting the process.

    A long-lived server otherwise keeps the functions it imported at boot,
    so page rebake would skip a newly wired flood fill.
    """
    importlib.reload(mcread.emit)
    importlib.reload(mcread.light)
    importlib.reload(mcread.bake)


def run_bake(
    *,
    world: Path,
    block_x: int,
    block_z: int,
    radius: int,
    min_y: int | None,
    max_y: int | None,
    dimension: str,
) -> dict[str, Any]:
    if radius < 0 or radius > MAX_RADIUS:
        raise ValueError(f"radius must be 0..{MAX_RADIUS}")
    _reload_lighting_modules()
    bake_and_write = mcread.bake.bake_and_write
    print(
        f"rebake lighting at ({block_x}, {block_z}) r={radius} "
        f"via {mcread.bake.apply_emit.__module__}+{mcread.bake.apply_light.__module__}",
        flush=True,
    )
    with open_level(world) as level:
        bake, atlas, scene = bake_and_write(
            level,
            block_x,
            block_z,
            GENERATED_DIR,
            dimension=dimension,
            resolver=_get_resolver(),
            min_y=min_y,
            max_y=max_y,
            radius=radius,
        )
    payload = json.loads(scene.read_text())
    payload["stats"] = {
        "opaque_triangles": bake.opaque.triangle_count,
        "translucent_triangles": bake.translucent.triangle_count,
        "atlas": [atlas.width, atlas.height],
    }
    return payload


class ViewerHandler(SimpleHTTPRequestHandler):
    bundled_world: Path = DEFAULT_WORLD
    dimension: str = OVERWORLD
    tmp_root: Path = default_tmp_root()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _session_id(self) -> str:
        cookie = SimpleCookie()
        raw = self.headers.get("Cookie", "")
        if raw:
            cookie.load(raw)
        morsel = cookie.get(SESSION_COOKIE)
        if morsel and morsel.value:
            return morsel.value
        sid = uuid.uuid4().hex
        self._pending_cookie = sid
        return sid

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        sid = getattr(self, "_pending_cookie", None)
        if sid:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={sid}; Path=/; HttpOnly; SameSite=Lax",
            )
        super().end_headers()
        self.wfile.write(data)

    def _session_world(self, sid: str) -> Path | None:
        live = session_dir(self.tmp_root, sid) / "world"
        if (live / "level.dat").is_file() and (live / "db").is_dir():
            return live
        bundled = self.bundled_world
        if bundled.is_dir() and (bundled / "level.dat").is_file():
            return bundled
        return None

    def _world_info(self, world: Path | None) -> dict[str, Any]:
        if world is None:
            return {"has_world": False, "world_name": None, "spawn": None}
        spawn_x, spawn_z = read_spawn_xz(world)
        return {
            "has_world": True,
            "world_name": read_world_name(world),
            "spawn": {"x": spawn_x, "z": spawn_z},
        }

    def _read_json_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid json"})
            return None
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "error": "invalid json"})
            return None
        return body

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            sid = self._session_id()
            world = self._session_world(sid)
            info = self._world_info(world)
            defaults = {
                "x": 300,
                "z": 73,
                "radius": DEFAULT_RADIUS,
                "min_y": DEFAULT_MIN_Y,
            }
            if info["spawn"]:
                defaults["x"] = info["spawn"]["x"]
                defaults["z"] = info["spawn"]["z"]
            self._json(
                200,
                {
                    "ok": True,
                    "can_bake": bool(info["has_world"]),
                    "can_upload": True,
                    "max_radius": MAX_RADIUS,
                    "max_upload_bytes": MAX_UPLOAD_BYTES,
                    "chunk_bytes": MAX_CHUNK_BYTES,
                    "defaults": defaults,
                    **info,
                },
            )
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/bake":
            self._handle_bake()
            return
        if path == "/api/world/start":
            self._handle_world_start()
            return
        if path == "/api/world/chunk":
            self._handle_world_chunk()
            return
        if path == "/api/world/finish":
            self._handle_world_finish()
            return
        self.send_error(404)

    def _handle_world_start(self) -> None:
        body = self._read_json_body()
        if body is None:
            return
        try:
            size = int(body.get("size", 0))
        except (TypeError, ValueError):
            self._json(400, {"ok": False, "error": "size must be an int"})
            return
        if size <= 0 or size > MAX_UPLOAD_BYTES:
            self._json(
                400,
                {
                    "ok": False,
                    "error": f"world zip must be 1..{MAX_UPLOAD_BYTES} bytes",
                },
            )
            return
        sid = self._session_id()
        folder = session_dir(self.tmp_root, sid)
        archive = folder / "upload.bin"
        with _upload_lock:
            archive.write_bytes(b"")
            _uploads[sid] = {"size": size, "received": 0, "path": archive}
        self._json(
            200,
            {
                "ok": True,
                "upload_id": sid,
                "chunk_bytes": MAX_CHUNK_BYTES,
            },
        )

    def _handle_world_chunk(self) -> None:
        sid = self._session_id()
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_CHUNK_BYTES:
            self._json(400, {"ok": False, "error": "chunk is empty or too large"})
            return
        data = self.rfile.read(length)
        with _upload_lock:
            job = _uploads.get(sid)
            if job is None:
                self._json(409, {"ok": False, "error": "call /api/world/start first"})
                return
            if job["received"] + len(data) > job["size"]:
                self._json(400, {"ok": False, "error": "upload exceeded declared size"})
                return
            with job["path"].open("ab") as handle:
                handle.write(data)
            job["received"] += len(data)
            received = job["received"]
            total = job["size"]
        self._json(200, {"ok": True, "received": received, "size": total})

    def _handle_world_finish(self) -> None:
        sid = self._session_id()
        with _upload_lock:
            job = _uploads.pop(sid, None)
        if job is None:
            self._json(409, {"ok": False, "error": "call /api/world/start first"})
            return
        if job["received"] != job["size"]:
            self._json(
                400,
                {
                    "ok": False,
                    "error": f"upload incomplete ({job['received']}/{job['size']})",
                },
            )
            return
        folder = session_dir(self.tmp_root, sid)
        try:
            live = unpack_mcworld(job["path"], folder)
        except WorldUploadError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        finally:
            try:
                job["path"].unlink(missing_ok=True)
            except OSError:
                pass
        info = self._world_info(live)
        self._json(200, {"ok": True, **info})

    def _handle_bake(self) -> None:
        body = self._read_json_body()
        if body is None:
            return
        sid = self._session_id()
        world = self._session_world(sid)
        if world is None:
            self._json(400, {"ok": False, "error": "upload a .mcworld first"})
            return
        try:
            spawn = read_spawn_xz(world)
            block_x = int(body.get("x", spawn[0]))
            block_z = int(body.get("z", body.get("y", spawn[1])))
            radius = int(body.get("radius", DEFAULT_RADIUS))
            min_y = body.get("min_y", DEFAULT_MIN_Y)
            min_y = int(min_y) if min_y is not None else None
            max_y = body.get("max_y")
            max_y = int(max_y) if max_y is not None else None
        except (TypeError, ValueError):
            self._json(400, {"ok": False, "error": "x, z, radius, min_y must be ints"})
            return

        if not _bake_lock.acquire(blocking=False):
            self._json(409, {"ok": False, "error": "a bake is already running"})
            return
        try:
            payload = run_bake(
                world=world,
                block_x=block_x,
                block_z=block_z,
                radius=radius,
                min_y=min_y,
                max_y=max_y,
                dimension=self.dimension,
            )
            self._json(200, {"ok": True, "scene": payload})
        except ChunkDoesNotExist as exc:
            self._json(404, {"ok": False, "error": str(exc)})
        except (ChunkLoadError, ValueError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            _bake_lock.release()


def parse_args(argv=None) -> argparse.Namespace:
    default_port = int(os.environ.get("PORT", DEFAULT_PORT))
    default_host = os.environ.get("HOST")
    if not default_host:
        default_host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=Path, default=DEFAULT_WORLD)
    parser.add_argument("--dimension", default=OVERWORLD)
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--host", default=default_host)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv=None) -> int:
    args = parse_args(argv)
    ViewerHandler.bundled_world = args.world
    ViewerHandler.dimension = args.dimension
    ViewerHandler.tmp_root = default_tmp_root()
    ViewerHandler.tmp_root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    print(f"viewer: http://{args.host}:{args.port}", flush=True)
    print("upload a .mcworld, then rebake from the page", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
