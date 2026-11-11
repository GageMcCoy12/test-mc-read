import { buildAtlas } from "./atlas.js";
import { loadBiomeTints } from "./biomes.js";
import { applyEmit, collectEmitters } from "./emit.js";
import { applyLight, computeLightField } from "./light.js";
import { mergeBakes, meshChunk } from "./mesh.js";
import { resolvePalette } from "./resolve.js";
import { buildScenePayload } from "./scene.js";
import { loadTranslateTables } from "./translate.js";
import { blockToChunk, loadRegion } from "./world.js";

const DEFAULT_MIN_Y = 60;
const DEFAULT_RADIUS = 0;
const MAX_RADIUS = 4;
const LIGHT_HALO = 1;

function visibleTextures(chunks) {
  const paths = [];
  const seen = new Set();
  for (const chunk of chunks.values()) {
    if (!chunk.visible) {
      continue;
    }
    for (const entry of chunk.resolved) {
      if (!entry?.mesh) {
        continue;
      }
      for (const path of entry.mesh.textures) {
        if (!seen.has(path)) {
          seen.add(path);
          paths.push(path);
        }
      }
    }
  }
  return paths;
}

export async function bakeWorld(db, options, onProgress) {
  const blockX = Number(options.x);
  const blockZ = Number(options.z);
  const radius = Math.max(0, Math.min(MAX_RADIUS, Number(options.radius ?? DEFAULT_RADIUS)));
  const minY = options.minY == null ? DEFAULT_MIN_Y : Number(options.minY);
  const maxY = options.maxY == null ? null : Number(options.maxY);
  const [cx, cz] = blockToChunk(blockX, blockZ);

  onProgress?.("loading translation tables");
  await Promise.all([loadTranslateTables(), loadBiomeTints()]);

  const chunks = await loadRegion(db, cx, cz, radius, LIGHT_HALO, onProgress);
  const center = chunks.get(`${cx},${cz}`);
  if (!center) {
    throw new Error(`chunk (${cx}, ${cz}) does not exist in this world`);
  }

  const unique = [];
  const uniqueKeys = new Set();
  for (const chunk of chunks.values()) {
    for (const sub of chunk.subchunks.values()) {
      for (const stack of sub.palette) {
        const key = JSON.stringify(stack);
        if (!uniqueKeys.has(key)) {
          uniqueKeys.add(key);
          unique.push(stack);
        }
      }
    }
  }
  onProgress?.(`resolving models 0/${unique.length}`);
  await resolvePalette(unique, (done, total) => {
    onProgress?.(`resolving models ${done}/${total}`);
  });

  let done = 0;
  const total = chunks.size;
  for (const chunk of chunks.values()) {
    done += 1;
    onProgress?.(`assigning models ${done}/${total}`);
    const palette = [];
    const seen = new Map();
    for (const sub of chunk.subchunks.values()) {
      for (const stack of sub.palette) {
        const key = JSON.stringify(stack);
        if (!seen.has(key)) {
          seen.set(key, palette.length);
          palette.push(stack);
        }
      }
    }
    // remap per-subchunk palettes onto a chunk-wide resolved list
    const resolved = await resolvePalette(palette);
    for (const sub of chunk.subchunks.values()) {
      const localToChunk = sub.palette.map((stack) => seen.get(JSON.stringify(stack)));
      const next = new Uint16Array(sub.indices.length);
      for (let cell = 0; cell < sub.indices.length; cell += 1) {
        next[cell] = localToChunk[sub.indices[cell]] ?? 0;
      }
      sub.indices = next;
    }
    chunk.resolved = resolved;
  }

  onProgress?.("packing atlas");
  const atlas = await buildAtlas(visibleTextures(chunks));
  onProgress?.("meshing");
  const bakes = [];
  for (const chunk of chunks.values()) {
    if (!chunk.visible) {
      continue;
    }
    bakes.push(meshChunk(chunks, chunk.cx, chunk.cz, atlas, minY, maxY));
  }
  const merged = mergeBakes(bakes, [cx, cz]);
  onProgress?.("flooding light");
  applyEmit(merged, collectEmitters(chunks, minY, maxY));
  applyLight(merged, computeLightField(chunks));
  const view = {
    block_x: blockX,
    block_z: blockZ,
    radius,
    min_y: minY,
    max_y: maxY,
    center_chunk: [cx, cz],
    chunks_meshed: (2 * radius + 1) ** 2,
  };
  return buildScenePayload(merged, atlas, view, blockX, blockZ);
}

export { DEFAULT_MIN_Y, DEFAULT_RADIUS, MAX_RADIUS };
