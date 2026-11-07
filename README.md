# chunk viewer

Bedrock save → Java block models → a browser chunk viewer.

Upload a `.mcworld` (or a zip of a Bedrock save folder), then rebake any x/z. Worlds stay in the server session — nothing ships a 449MB save in the image.

Minecraft textures written to `viewer/generated/atlas.png` are Mojang’s. Educational / class use only, not a redistributable asset pack.

## Controls

- drag to orbit, scroll to zoom
- wasd walks on the xz plane
- click the earth (or space) to play/pause the day
- drag the moon to set time
- `r` or **reset orbit** to jump back to the bake target
- bottom-left: brightness + `now` / `next` lighting

Time, graphics, and camera position persist in localStorage.

## Local

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tools/serve_viewer.py
```

Open http://127.0.0.1:8765, upload a `.mcworld`, hit rebake. If `world/` exists locally it is still used as a fallback so you can bake without uploading.

Do not use `python -m http.server` if you want the bake / upload API.

Optional one-shot bake without the server:

```
.venv/bin/python tools/bake_chunk.py --x 300 --z 73 --radius 4 --min-y 60
```

## Cloud Run (full backend, free-tier-ish)

The container does **not** include a world. Each visitor uploads their own `.mcworld` in 4MB chunks (Cloud Run’s request cap is 32MB). Sessions live in `/tmp` and vanish when the instance scales to zero — re-upload after idle.

Needs a GCP project with billing enabled. The always-free Cloud Run allowance is usually enough for a class demo.

The container uses **Python 3.12**. `amulet-leveldb` has no Linux wheels, so Cloud Build compiles it from source (needs `zlib` + Cython). First build can take 10–20 minutes. If pip dies on `amulet-leveldb`, check that the image is `python:3.12-slim-bookworm`, not 3.13.

```
gcloud run deploy mcread \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 4Gi \
  --cpu 2 \
  --timeout 300 \
  --max-instances 1 \
  --cpu-boost
```

`--max-instances 1` keeps uploads and bakes on the same instance (sessions are in-memory `/tmp`). `--timeout 300` covers a radius-4 bake.

Export from Minecraft: **Settings → Storage → worlds → export** yields a `.mcworld`.
