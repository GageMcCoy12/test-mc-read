# chunk viewer

Bedrock save → Java block models → a browser chunk viewer.

**Live demo (no Python):** https://gagemccoy12.github.io/test-mc-read/

Look around, drag the moon to set time of day, and flip lighting. The hosted site is a static GitHub Pages snapshot of one pre-baked region. Rebake (pick a new x/z) is local-only.

Minecraft textures in `viewer/generated/atlas.png` are Mojang’s. This demo is for class / educational use, not a redistributable asset pack. The Bedrock world save is not in this repo.

## Controls

- drag to orbit, scroll to zoom
- wasd walks on the xz plane
- click the earth (or space) to play/pause the day
- drag the moon to set time
- `r` or **reset orbit** to jump back to the bake target
- bottom-left: brightness + `now` / `next` lighting

Time, graphics, and camera position persist in localStorage.

## Local rebake (optional)

Needs Python 3.13, a copy of the world save in `world/`, and the venv:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tools/bake_chunk.py --x 300 --z 73 --radius 4 --min-y 60
.venv/bin/python tools/serve_viewer.py
```

Then open http://127.0.0.1:8765 and rebake from the notebook. Do not use `python -m http.server` if you want the bake API.

After changing bake code, restart the server. After a bake, hard-refresh the tab so `atlas.png` / `*.bin` are not stale.
