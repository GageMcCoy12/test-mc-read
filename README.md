# chunk viewer

Bedrock save → Java block models → a browser chunk viewer.

Pick a `.mcworld` (or a zip of a Bedrock save folder). Bake runs in a web worker in this tab — the file never uploads. First bake fetches Java models/textures from [mcmeta](https://github.com/misode/mcmeta) via jsDelivr, then caches them.

Minecraft textures are Mojang’s. Educational / class use only, not a redistributable asset pack. The Python baker is still the reference implementation.

## Controls

- drag to orbit, scroll to zoom
- wasd walks on the xz plane
- click the earth (or space) to play/pause the day
- drag the moon to set time
- `r` or **reset orbit** to jump back to the bake target
- bottom-left: brightness + `now` / `next` lighting

Time, graphics, and camera position persist in localStorage.

## Local

Bake is client-side, so a static server is enough:

```
python3 -m http.server --directory viewer 8765
```

Open http://127.0.0.1:8765, pick a `.mcworld`, hit rebake. The file never leaves the tab. First bake fetches Java models from the public mcmeta CDNs.

Python is only for the reference baker and table dumps:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tools/export_client_tables.py
.venv/bin/python tools/export_biome_tints.py
.venv/bin/python tools/bake_chunk.py --x 300 --z 50 --radius 4 --min-y 60
```

## Cloud Run (static host)

The container is just `viewer/`. Visitors pick a `.mcworld` in the browser; nothing uploads, and the world is not in the image. Needs a GCP project with billing enabled. The always-free Cloud Run allowance is plenty.

```
gcloud run deploy mcread \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 256Mi \
  --cpu 1 \
  --timeout 30
```

Export from Minecraft: **Settings → Storage → worlds → export** yields a `.mcworld`.
