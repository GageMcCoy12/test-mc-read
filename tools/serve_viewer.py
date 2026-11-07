"""Serve the chunk viewer and rebake on demand.

The browser stays a thin client. This process opens the save, runs the same
bake pipeline as tools/bake_chunk.py, and writes viewer/generated/.

Run: .venv/bin/python tools/serve_viewer.py
Then open http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import threading
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

VIEWER_DIR = PROJECT_ROOT / "viewer"
GENERATED_DIR = VIEWER_DIR / "generated"
DEFAULT_PORT = 8765

_bake_lock = threading.Lock()
_resolver: PaletteResolver | None = None


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
    world: Path = DEFAULT_WORLD
    dimension: str = OVERWORLD

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json(
                200,
                {
                    "ok": True,
                    "can_bake": True,
                    "max_radius": MAX_RADIUS,
                    "defaults": {
                        "x": 300,
                        "z": 73,
                        "radius": DEFAULT_RADIUS,
                        "min_y": DEFAULT_MIN_Y,
                    },
                },
            )
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/bake":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid json"})
            return

        try:
            block_x = int(body.get("x", 300))
            block_z = int(body.get("z", body.get("y", 73)))
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
                world=self.world,
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

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=Path, default=DEFAULT_WORLD)
    parser.add_argument("--dimension", default=OVERWORLD)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv=None) -> int:
    args = parse_args(argv)
    ViewerHandler.world = args.world
    ViewerHandler.dimension = args.dimension
    server = ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    print(f"viewer: http://{args.host}:{args.port}", flush=True)
    print("rebake from the page — do not use python -m http.server for that", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
