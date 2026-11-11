import { loadTexture, textureHasCutout } from "./pack.js";
import { Transparency, mergeModels, meshForJava, unitCube } from "./models.js";
import { translateStack } from "./translate.js";

export const AIR = new Set(["air", "cave_air", "void_air", "empty"]);
export const FLUIDS = new Set(["water", "lava", "flowing_water", "flowing_lava"]);

const GRASS_TINT = new Set([
  "minecraft:grass_block",
  "minecraft:short_grass",
  "minecraft:tall_grass",
  "minecraft:fern",
  "minecraft:large_fern",
  "minecraft:sugar_cane",
  "minecraft:bush",
]);
const FOLIAGE_TINT = new Set([
  "minecraft:oak_leaves",
  "minecraft:jungle_leaves",
  "minecraft:acacia_leaves",
  "minecraft:dark_oak_leaves",
  "minecraft:mangrove_leaves",
  "minecraft:vine",
]);
const WATER_TINT = new Set(["water", "flowing_water"]);

function tintKindFor(java) {
  if (!java) {
    return null;
  }
  if (WATER_TINT.has(java.baseName) || java.namespaced === "minecraft:water_cauldron") {
    return "water";
  }
  if (GRASS_TINT.has(java.namespaced)) {
    return "grass";
  }
  if (FOLIAGE_TINT.has(java.namespaced)) {
    return "foliage";
  }
  return null;
}

const SKIP_EMPTY = {
  skip: true,
  isEmpty: true,
  isOpaque: false,
  isFluid: false,
  isMissing: false,
  transparency: Transparency.Partial,
  tintKind: null,
  mesh: null,
  java: null,
};

const SKIP_MISSING = {
  ...SKIP_EMPTY,
  isEmpty: false,
  isMissing: true,
};

const cache = new Map();

function cacheKey(stack) {
  return stack
    .map((block) => {
      const props = Object.entries(block.properties || {})
        .sort()
        .map(([k, v]) => `${k}=${v}`)
        .join(",");
      return props ? `${block.namespaced}[${props}]` : block.namespaced;
    })
    .join("+");
}

function isEmpty(block) {
  return !block || AIR.has(block.baseName);
}

function isFluid(block) {
  return Boolean(block) && FLUIDS.has(block.baseName);
}

async function meshOccludes(mesh) {
  if (!mesh || mesh.transparency !== Transparency.FullOpaque) {
    return false;
  }
  const textures = await Promise.all(mesh.textures.map((path) => loadTexture(path)));
  return textures.every((texture) => !textureHasCutout(texture));
}

async function resolveLayer(java) {
  if (isEmpty(java)) {
    return SKIP_EMPTY;
  }
  if (isFluid(java) || (java.baseName && FLUIDS.has(java.baseName))) {
    const lava = java.baseName.includes("lava");
    const texture = lava ? "minecraft:block/lava_still" : "minecraft:block/water_still";
    const tint = lava ? [1, 1, 1] : [0x3f / 255, 0x76 / 255, 0xe4 / 255];
    const mesh = await unitCube(texture, Transparency.FullTranslucent, tint);
    return {
      skip: false,
      isEmpty: false,
      isOpaque: false,
      isFluid: true,
      isMissing: false,
      extraNeeded: Boolean(java.extraNeeded),
      transparency: Transparency.FullTranslucent,
      tintKind: lava ? null : "water",
      mesh,
      java,
    };
  }
  const mesh = await meshForJava(java);
  if (!mesh) {
    return {
      ...SKIP_MISSING,
      extraNeeded: Boolean(java.extraNeeded),
      tintKind: null,
      java,
    };
  }
  return {
    skip: false,
    isEmpty: false,
    isOpaque: await meshOccludes(mesh),
    isFluid: false,
    isMissing: false,
    extraNeeded: Boolean(java.extraNeeded),
    transparency: mesh.transparency,
    tintKind: tintKindFor(java),
    mesh,
    java,
  };
}

export async function resolveStack(stack) {
  const key = cacheKey(stack);
  if (cache.has(key)) {
    return cache.get(key);
  }
  const pending = (async () => {
    const translated = translateStack(stack);
    const primary = translated[0];
    if (isEmpty(primary) && translated.length === 1) {
      return SKIP_EMPTY;
    }
    const layers = [];
    for (const java of translated) {
      const resolved = await resolveLayer(java);
      if (!resolved.skip && resolved.mesh) {
        layers.push(resolved);
      }
    }
    if (!layers.length) {
      return SKIP_MISSING;
    }
    if (layers.length === 1) {
      return layers[0];
    }
    const mesh = mergeModels(layers.map((layer) => layer.mesh));
    return {
      skip: false,
      isEmpty: false,
      isOpaque: await meshOccludes(mesh),
      isFluid: layers[0].isFluid,
      isMissing: false,
      extraNeeded: layers.some((layer) => layer.extraNeeded),
      transparency: mesh.transparency,
      tintKind: layers.find((layer) => layer.tintKind)?.tintKind || null,
      mesh,
      java: layers[0].java,
    };
  })();
  cache.set(key, pending);
  return pending;
}

async function mapPool(items, limit, fn) {
  const out = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const index = next;
      next += 1;
      out[index] = await fn(items[index], index);
    }
  }
  const workers = Math.min(Math.max(1, limit), items.length);
  await Promise.all(Array.from({ length: workers }, () => worker()));
  return out;
}

export async function resolvePalette(palette, onProgress) {
  let done = 0;
  return mapPool(palette, 8, async (stack) => {
    const resolved = await resolveStack(Array.isArray(stack) ? stack : [stack]);
    done += 1;
    if (onProgress && (done === 1 || done === palette.length || done % 4 === 0)) {
      onProgress(done, palette.length);
    }
    return resolved;
  });
}

export function usesTranslucentPass(entry) {
  return Boolean(entry.isFluid || entry.transparency === Transparency.FullTranslucent);
}
