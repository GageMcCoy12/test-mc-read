# Handoff: Bedrock save reader + chunk viewer

Written 2026-09-03, updated later that night after the lightmap v1 revert.
Companion: [block-model-format.md](block-model-format.md).

**Do not start a new mesher.** Geometry is done.

**Lighting truth:** the live path is Lambert + per-vertex torch glow
(`now`). A flood-fill lightmap was tried, looked cursed, and was unhooked.
`next` on the viewer toggle is an empty hook. Do not wire `light.py` back
in until the quality stack below is actually built.

---

## What to do next

Build classic **Fancy** Minecraft lighting behind `next`. Keep `now` as
the passable Lambert path so we can flip. Quality order — skipping ahead
is how v1 happened:

1. **Correct 0–15 field** in [`mcread/light.py`](../mcread/light.py):
   6-connected flood, full emitter table (not five names), water extra
   opacity, lighting-only halo (`BlockGrid.add_chunk(..., visible=False)`).
2. **Vanilla 16×16 LUT** in the viewer. Rebuild `writeLightmap` from
   Java `lightmap.fsh` (`n/(4-3n)`, warm block mix, `SkyFactor` from the
   orrery). `writeLightmap` is **gone**, not parked. `MeshBasicMaterial`
   + `uv2`. Night darkens the sky axis only. No rebake for time of day.
3. **Face shade** 1.0 / 0.8 / 0.6 / 0.5 (up / NS / EW / down).
4. **Smooth lighting + AO**: 4-tap average on the *lit side* of the face.
   Replace `sample_vertex_levels` max-of-8. AO from `mesh_occludes`
   occupancy. Never to zero.

Still later, not the first `next` PR: directional opacity (slabs/stairs),
biome tint, real fluid surfaces, chests-as-entities, shulker lids, sign
text, item frames.

**Out of scope:** Vibrant Visuals / PBR / shadow maps, Three.js point
lights, a new mesher, rays from verts to lamps, reading Bedrock light
NBT (this save has none — `misc` is `bedrock_chunk_data` + `height`).

### Already done (do not re-do)

**Viewer** (`viewer/index.html`, `viewer/viewer.js`):

- Paper hamburger notebook: *place* only (x/z, radius 0–4, min-y, rebake,
  reset orbit). Time/fog sliders were removed from the panel.
- Top-left SVG orrery: isometric earth cube + crescent moon on a true circle.
  Drag the moon to set time of day. Click the earth to play/pause the cycle.
  `space` also toggles play, `escape` closes the notebook, `r` resets orbit.
- WASD walks the camera on the XZ plane (with orbit target). Ignores keys
  while typing in the form.
- Bottom-left paper chip: **now** / **next**. `lightingMode` updates
  `aria-pressed` only. Renderer always uses `now`.
- Look: orrery-driven sky / fog / ACES. Scene sun / hemi / fill **do**
  shade terrain. Material is `MeshLambertMaterial`. Shader adds
  `outgoingLight += vEmit * diffuseColor.rgb`.

**Emit (live)** (`mcread/emit.py`, applied in `bake_chunk` after merge):

- Distance falloff from torch / wall_torch / lantern / glowstone / lit
  redstone_lamp. `weight = (1 - dist/radius)² * strength`, plus self-glow
  inside 0.9 blocks, cap 2.4.
- `level` on the 4-tuple (14/15) is unused by emit. Flood can consume it.
- Last rebake on disk: block (300, 73), radius 4, min_y 60. Emit is live
  (max 2.4, ~243k lit verts). `light` in the bins is zeros.

**Lightmap (parked, not live)** (`mcread/light.py`):

- File exists. `bake_chunk` does **not** call `compute_light_field` /
  `apply_light`. No `tests/test_light.py`.
- 6-connected BFS, sky columns, max-of-8 vertex sample. That sample
  rule is wrong for Fancy — 4-tap average on the outside of the face.
- Bin contract already has `light f32[n*2]`. `parsePass` reads it.
  `geometryFromPass` does not bind it.

Serve with `.venv/bin/python tools/serve_viewer.py` then open
http://127.0.0.1:8765. Rebake from the page; do not use `python -m http.server`
or the API is missing. After Python bake-code changes, **restart the server**
— `PaletteResolver` and `java_model_manager()` are process-cached. Hard-refresh
the tab after a bake so `atlas.png` / `*.bin` are not stale.

---

## Part 1: What exists now

### The goal that was validated

Read a Minecraft Bedrock save and identify blocks well enough to render them,
**without hardcoding block variants**. That goal is met. A basic region viewer
is also met.

The decisive number from the audit: of Minecraft's 2657 Java block models,
**2314 contain no geometry at all**. They are pure `parent` + `textures` data
pointing at just 343 shared shapes. Shape families (slabs, stairs, doors,
fences, walls) are data, not code.

### Environment

| Component | Version | Notes |
| --- | --- | --- |
| Python | 3.13.2 | venv at `.venv/` |
| amulet-core | 1.9.30 | reads the leveldb save |
| amulet-nbt | 2.1.8 | NBT parsing |
| PyMCTranslate | 1.2.47 | universal to Java blockstate translation |
| minecraft-resource-pack | 1.4.12 | imports as `minecraft_model_reader` |
| Pillow | 12.3.0 | pulled in by the above |
| numpy | 1.26.4 | palette index arrays |
| pytest | 9.1.1 | **116 tests**, all passing |
| Three.js | via import map | `viewer/viewer.js` only |

Install with `pip install -r requirements.txt`.

### The world

`world/` is a 449 MB Bedrock save named `FV-Test-File`, seed `1000214037`, last
opened with Bedrock **`1.26.44.3`**. It uses **chunk version 42**, which
amulet-core 1.9.30 does not support (it stops at 41). `patch_amulet_chunk_v42()`
in `mcread/world_access.py` registers a v42 interface subclassing the v41 one.
This patch is applied at import time and is required for anything to work.

Default viewer target: block **(300, 73)** = chunk **(18, 4)**, `min_y=60`.
Landmark birch trapdoor at **(296, 80, 76)**. Same chunk also has:

- double chest at `(298–299, 75, 77)`
- wall banners on the line `y=85, z=75` (x 295–301), white cloth + red patterns
- decorated pots around `(294–303, 70, 71–75)`

### Code layout

`mcread/` is the reusable library. Almost nothing in it knows about specific
blocks. The two exceptions are fluids (still-texture cubes) and banners
(pattern codes + dye indices — Minecraft engine tables, not pack data).

| Module | Responsibility |
| --- | --- |
| `world_access.py` | v42 patch, `open_level()`, `open_chunk()`, region iteration |
| `blocks.py` | blockstate text formatting, `blockstate_key()`, air / fluid detection |
| `census.py` | `PaletteCensus`: exhaustive blockstate counting via palette + bincount |
| `properties.py` | `PropertyVocabulary`, schema comparison, shape-family grouping |
| `translate.py` | `JavaTranslator`: universal Block to Java Block, with failure modes |
| `models.py` | `java_model_manager()`, `describe_block_mesh()`, `MeshSummary` |
| `pack_inspect.py` | reads pack JSON to explain *why* a block has no geometry |
| `inventory.py` | `NonBlockInventory`: block entities, biomes, entities, y extent |
| `resolve.py` | `PaletteResolver`: cached palette → `ResolvedBlock` + mesh |
| `mesh.py` | `BlockGrid`, face culling, opaque / translucent `BakedMesh` |
| `atlas.py` | one PNG atlas; tile size grows to the largest native texture (64 for entities) |
| `banners.py` | NBT `Patterns` → painted cloth image, swapped per block position |
| `bake.py` | region load, banner apply, atlas, merge, `apply_emit`, write |
| `emit.py` | live: distance glow. also stores vanilla 0–15 levels |
| `light.py` | parked flood fill. not called from `bake_chunk` |
| `export_scene.py` | `scene.json` + `opaque.bin` / `translucent.bin` |
| `export_obj.py` | debug OBJ/MTL next to the scene |

`tools/bake_chunk.py` writes `viewer/generated/`. `tools/serve_viewer.py` serves
`viewer/` and `POST /api/bake`.

`probes/` are CLI audit scripts (`--world --x --z --radius --dimension --output`
→ JSON in `reports/`). Still valid; they describe the *pack*, not the viewer.

`read_chunk.py` is the original sampling CLI.

### Pack stacking (do not flip this)

`java_model_manager()` loads **vanilla first, then `java_vanilla_fix`**. Later
packs win.

Vanilla ships particle-only models for chests, banners, pots, shulkers. The
fix pack (inside minecraft-model-reader) replaces those with real elements and
points at `textures/entity/...`. Stacking the fix pack *under* vanilla was
why those blocks used to be missingno / oak-plank cubes.

Amulet originally documented fix-then-vanilla so the fix pack only filled
*missing files*. Vanilla *has* `blockstates/chest.json` (empty), so it won.
Fix-last is required for entity-block geometry.

`entity_placeholder_mesh()` remains as a last-resort particle cube if a model
is still missing.

### The verified pipeline

```
Bedrock leveldb
  -> amulet Chunk
  -> chunk.block_palette             (universal Block objects)
  -> PyMCTranslate from_universal    (Java blockstate)
  -> blockstates/NAME.json           (fix pack wins for chests / banners / pots)
  -> models/block/*.json + parents
  -> BlockMesh                       (verts 0-1, face_mode 3, cull buckets)
  -> PaletteResolver cache
  -> mesh_chunk + face cull
  -> banner cloth swap (instance NBT)
  -> TextureAtlas + scene.json / *.bin
  -> emit.py (distance falloff → vertex emit RGB)
  -> viewer.js (two Lambert passes + emit add + sky / day-night)
```

Worked translation example: `universal_minecraft:trapdoor[material=birch,
facing=west,half=bottom,open=true,powered=false]` becomes
`minecraft:birch_trapdoor[facing=west,half=bottom,open=true,powered=false]`.
`material` moves from a property into the block name.

**Confirmed mesh layout** (do not re-infer): verts are **0–1** block-local,
`face_mode == 3` (two triangles per quad). See `tests/test_resolve.py`.

### Audit results

Scope: 81 chunks (radius 4 around chunk `(18, 4)`), 767 sub-chunks, 3,141,632
blocks, about 3 seconds per probe. These numbers are from the morning audit
and were not re-run after the renderer.

| Measurement | Result |
| --- | --- |
| Distinct blockstates | 653 (652 excluding air) |
| Distinct base names | 183 |
| Distinct property signatures | 66 |
| Base names fully covered by declared schema | **183 of 183** |
| Properties or values observed that the schema lacks | **0** |
| Translate to a Java blockstate | 650 of 652 (**99.69%**) |
| Hard translation failures | 0 |
| Silent untranslated passthroughs | 0 |
| Resolve to real geometry (pack elements, pre-fix-stack) | 583 of 652 (**89.42%**) |
| Distinct textures the world needs (then) | 338 |
| **Gaps the pack could have filled but we missed** | **0** |

`special_cases.py` still classifies against `describe_block_mesh` + pack JSON.
After the pack-order flip, chests/banners/pots *do* resolve to elements via
the fix pack; the on-disk `reports/special_cases.json` is the pre-flip audit.
Re-run the probe if you need current buckets. The "our bug" bucket was empty.

### Special cases: what the renderer does today

| Category | Audit count | Renderer now |
| --- | --- | --- |
| Fluids | 38 / 50,564 | Full cube, `water_still` / `lava_still`, hardcoded water tint. Ignores `level`. |
| Block entities | 29 / 170 | Fix-pack models: chests (lid + latch, left/right), ender chests, decorated pots, banners. Shulkers are `cube_all` with the box texture (no lid). |
| Banner patterns | 16 banners in region | Painted. See below. |
| No Java equivalent | 2 / 4 | `item_frame_block` → air. Still skipped. |
| Runtime tint | 28 / 14,554 | Pack / model-reader tints only (grass green, water blue). No biome table. |
| Neighbours | 44 / 148 | Accept `from_universal` defaults. Chest `connection=left/right` already in the save. |
| `extra_blocks` | 5 | `BlockMesh.merge` in `PaletteResolver`. |

Not done, on purpose: chest/shulker inventory, shulker lid pose, sign text,
item frames, pottery sherds, skull skins, piston animation.

### Banner patterns

`mcread/banners.py`. Geometry stays on the block model. Patterns are
per-block-entity, so they cannot live on the palette cache.

- Bedrock NBT: `utags.Patterns[]` with `Pattern` (short code) and `Color` (0–15).
- Codes → Java mask names (`cr` → `cross`, `bo` → `border`, `cre` → `creeper`).
  Table from https://minecraft.wiki/w/Banner/Patterns. Unknown codes are skipped.
- Dye 0–15 is wool order (0 white … 14 red … 15 black). RGB is sampled from
  the fix pack's `block/banner/banner_{dye}.png`, not a hardcoded palette.
- Composite is 64×64 onto the existing cloth texture; the wooden crossbar
  (`banner_base`) is not replaced.
- `BlockGrid` maps `(x,y,z)` → synthetic atlas key `banner-cloth:…`.
  `mesh_chunk` swaps only `is_banner_cloth_texture` paths at that cell.
- Atlas accepts in-memory `extras` so painted cloths never hit disk / git.

Default chunk painted **6 unique cloths** for the y=85 banner row. 296 and
298 share a signature.

### Non-block data available (still unused except banners)

348 block entities across 27 types in the audited region, with full NBT: sign
`front_text`/`back_text`, banner `Patterns` (now drawn), chest `Items` /
`LootTable`, spawner config, piston progress. Biomes at 4×4×4 per sub-chunk;
5 biomes here (taiga dominant). Stored y extent -64 to 111. Zero mob entities
in that region. All three dimensions have data.

### Bake / viewer contract

`viewer/generated/` is produced, not hand-edited. Never commit `atlas.png`
(copyrighted Minecraft pixels).

Each `*.bin` is little-endian: `positions f32[n*3]`, `uvs f32[n*2]`,
`colors f32[n*3]`, `emit f32[n*3]` (torch glow, live), `light f32[n*2]`
(reserved, currently zeros), `indices u32[index_count]`. Two passes:
`opaque` then `translucent` (`Transparency.FullTranslucent` or fluids).
Atlas UVs are already remapped. `colors` stay tint multipliers. When
`next` ships, `light` is `(block+0.5)/16, (sky+0.5)/16`.

`ChunkBake` origin / y_range / camera_target go into `scene.json`. Radius cap
is **4**. Cache meshes by palette index (`PaletteResolver`); the inner loop is
an array lookup. Face culling skips whole cull buckets when the neighbour is
opaque (or fluid-against-fluid). Neighbour chunks outside the radius count as
air, so the region shell keeps its outer faces. Leaves do not occlude: the
pack marks them opaque, we check PNG alpha.

Atlas tile size is `max(16, largest first-frame)`. Entity sheets are 64×64;
16×16 block tiles are nearest-neighbour upscaled into the same grid.

### Known risks

- **Version skew.** Save is Bedrock `1.26.44.3`; PyMCTranslate stops at
  `26.30`. Harmless today. Same class of problem as the v42 patch.
- **Silent passthrough.** `from_universal` does not raise on an unknown
  block. It returns the input in `universal_minecraft`, which would render as
  missingno. `TranslationResult.passed_through` checks the output namespace.
- **leveldb writes on open.** Opening the save can rewrite `LOG`/`MANIFEST`.
  Run audits against a copy (`cp -R world /tmp/world_audit`).
- **Region scope.** Audit numbers are a 9×9 around (18, 4), not the world.
- **Stale viewer process.** Bake-code changes need a server restart. Generated
  files alone only need a hard refresh.
- **`grass.json` in the fix pack.** Harmless here (modern name is
  `short_grass`). Do not reverse pack order to "fix" it.

### How to reproduce

```
cp -R world /tmp/world_audit
.venv/bin/python probes/spike_block_mesh.py
.venv/bin/python probes/special_cases.py --world /tmp/world_audit --radius 4
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q -m integration
.venv/bin/python tools/bake_chunk.py --x 300 --z 73 --radius 0 --min-y 60
.venv/bin/python tools/serve_viewer.py
```

Vanilla Java pack downloads on first use to
`~/Library/Caches/AmuletTeam/resource_packs/java/vanilla` (release `26.2`).
`java_vanilla_fix` ships inside the library.

**Licensing:** Minecraft assets are copyrighted. Download-to-user-cache at
runtime is deliberate. Never commit extracted textures, atlas PNGs, or pack
JSON, and never ship them in a build.

---

## Part 2: Renderer internals (already built)

### What `BlockMesh` hands you

`java_model_manager().get_block_model(java_block)` returns a `BlockMesh` with
`verts` / `texture_coords` / `faces` / `texture_index` keyed by cull
direction (`None` = always draw), plus `textures`, `tint_verts`, `is_opaque`,
`is_transparent`, `face_mode`, `rotate`, `merge`.

The birch trapdoor spike had buckets
`(None, 'down', 'east', 'north', 'south', 'up')` — no `'west'`, flush against
the western neighbour.

`ResolvedBlock` is the mesher record: mesh, opacity (after cutout check),
fluid/missing/skip flags. `SKIP_EMPTY` / `SKIP_MISSING` are shared sentinels.

### Performance rules that still apply

Cache by palette, not by world position. A chunk has a few hundred palette
entries and tens of thousands of cells. Banner painting is the exception: it
is keyed by NBT signature, then instanced by position.

### Things that will bite (viewer work)

- **Transparency ordering.** Already two passes. Adding lights / a sky must
  not flatten them into one draw.
- **Texture paths are absolute** into the user cache, or synthetic
  `banner-cloth:…` keys. The browser only ever sees `atlas.png`.
- **Coordinate handedness.** Minecraft is right-handed Y-up. The trapdoor and
  the south-facing double chest are the check objects.
- **`uvlock` and variant rotation.** Model reader applies `x`/`y`. Wall-side
  cobblestone walls are the eyeball test.
- **Vertex colours.** Tint multipliers. Live shader is
  `atlas * tint * Lambert + emit`. Do not drop `color` or `emit`.
- **`now` is Lambert.** Scene lights shade blocks. That is why it looks
  passable. Do not “fix” this by deleting emit.
- **`next` is Fancy lightmap.** Terrain becomes `MeshBasicMaterial`.
  Scene lights must stop shading blocks on that path only. No Three.js
  point lights. No Vibrant Visuals.
- **Wall verts (when building `next`).** 4-tap average on the lit side
  of the face. Do not reuse max-of-8 `sample_vertex_levels`.
- **Region edge.** Neighbours outside radius are air. A lighting halo
  (`visible=False`) is required or sky 15 leaks in.

### Why lightmap v1 looked cursed (do not repeat)

- No AO, no face shade — cubes read as cardboard.
- Max-of-8 sample, not 4-tap average.
- Five emitters. Lava / fire / sea lanterns stayed black.
- LUT was a guess (`torch * 1.5 + skyTint`), not `lightmap.fsh`.
- Binary `is_opaque` only. Fine for leaves; wrong for water extra drop.
- Hard 16-step bands with no smooth filter.

### What to read next

- This file, then `mcread/emit.py` and `viewer/viewer.js` (`blockMaterial`,
  `setLightingMode`, `parsePass`).
- `mcread/light.py` — parked. Read before rewiring, do not call from
  `bake_chunk` until A–D in “What to do next” exist.
- `mcread/export_scene.py` — buffer layout (`light` is reserved).
- `mcread/bake.py` / `mcread/mesh.py` — emit runs after `merge_bakes`.
  `visible=False` is the halo hook. `mesh_occludes` is the AO bit.
- `docs/block-model-format.md` — if a mesh looks wrong; not for lighting.
- `reports/special_cases.json` — stale vs pack-order, still useful for fluids
  and tint classes.
