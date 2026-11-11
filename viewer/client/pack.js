/** Vanilla Java pack from mcmeta (CORS-friendly) plus the local Amulet fix pack. */

const MCMETA_SOURCES = [
  "https://assets.mcasset.cloud/26.2/assets",
  "https://cdn.jsdelivr.net/gh/misode/mcmeta@assets/assets",
  "https://raw.githubusercontent.com/misode/mcmeta/assets/assets",
];
const FETCH_MS = 8000;
const cache = new Map();
const jsonCache = new Map();
const imageCache = new Map();
let fixPackIndexPromise = null;

function fixUrl(path) {
  return new URL(`./fix-pack/assets/${path}`, import.meta.url).href;
}

function loadFixPackIndex() {
  if (!fixPackIndexPromise) {
    fixPackIndexPromise = (async () => {
      try {
        const response = await fetch(new URL("./fix-pack/index.json", import.meta.url), {
          signal: AbortSignal.timeout(FETCH_MS),
        });
        if (!response.ok) {
          return new Set();
        }
        const paths = await response.json();
        return new Set(paths);
      } catch {
        return new Set();
      }
    })();
  }
  return fixPackIndexPromise;
}

async function fetchOk(url) {
  try {
    const response = await fetch(url, {
      signal: AbortSignal.timeout(FETCH_MS),
      cache: "force-cache",
    });
    if (response.ok) {
      return response;
    }
  } catch {
    // timeout / network / blocked CDN
  }
  return null;
}

async function fetchAsset(path) {
  if (cache.has(path)) {
    return cache.get(path);
  }
  const pending = (async () => {
    const index = await loadFixPackIndex();
    if (index.has(path)) {
      const local = await fetchOk(fixUrl(path));
      if (local) {
        return local;
      }
    }
    for (const base of MCMETA_SOURCES) {
      const remote = await fetchOk(`${base}/${path}`);
      if (remote) {
        return remote;
      }
    }
    return null;
  })();
  cache.set(path, pending);
  return pending;
}

export function splitId(identifier, fallback = "minecraft") {
  if (!identifier) {
    return [fallback, ""];
  }
  const cleaned = identifier.startsWith("#") ? identifier.slice(1) : identifier;
  const parts = cleaned.split(":");
  if (parts.length === 1) {
    return [fallback, parts[0]];
  }
  return [parts[0], parts.slice(1).join(":")];
}

export async function loadJsonAsset(kind, identifier) {
  const [namespace, relative] = splitId(identifier);
  const rel = relative.replace(/^\/+/, "");
  const cacheKey = `${kind}:${namespace}:${rel}`;
  if (jsonCache.has(cacheKey)) {
    return jsonCache.get(cacheKey);
  }
  const path = `${namespace}/${kind}/${rel}.json`;
  const pending = (async () => {
    const response = await fetchAsset(path);
    if (!response) {
      return null;
    }
    return response.json();
  })();
  jsonCache.set(cacheKey, pending);
  return pending;
}

export async function loadBlockstate(namespace, name) {
  return loadJsonAsset("blockstates", `${namespace}:${name}`);
}

export async function loadModel(identifier) {
  let id = identifier;
  if (!id.includes("/")) {
    id = `${id.startsWith("minecraft:") || id.includes(":") ? "" : "minecraft:"}${id}`;
  }
  const [namespace, relative] = splitId(id);
  const modelPath = relative.startsWith("block/") || relative.startsWith("item/")
    ? relative
    : `block/${relative}`;
  return loadJsonAsset("models", `${namespace}:${modelPath}`);
}

function firstFrame(bitmap) {
  const { width, height } = bitmap;
  if (height > width && height % width === 0) {
    return { sx: 0, sy: 0, sw: width, sh: width };
  }
  if (width > height && width % height === 0) {
    return { sx: 0, sy: 0, sw: height, sh: height };
  }
  return { sx: 0, sy: 0, sw: width, sh: height };
}

export async function loadTexture(identifier) {
  const [namespace, relative] = splitId(identifier);
  const rel = relative.replace(/^\/+/, "");
  const cacheKey = `${namespace}:${rel}`;
  if (imageCache.has(cacheKey)) {
    return imageCache.get(cacheKey);
  }
  const path = `${namespace}/textures/${rel}.png`;
  const pending = (async () => {
    const response = await fetchAsset(path);
    if (!response) {
      return missingTexture(cacheKey);
    }
    const blob = await response.blob();
    const bitmap = await createImageBitmap(blob);
    const frame = firstFrame(bitmap);
    const canvas = new OffscreenCanvas(frame.sw, frame.sh);
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(bitmap, frame.sx, frame.sy, frame.sw, frame.sh, 0, 0, frame.sw, frame.sh);
    const imageData = ctx.getImageData(0, 0, frame.sw, frame.sh);
    let cutout = false;
    const pixels = imageData.data;
    for (let i = 3; i < pixels.length; i += 4) {
      if (pixels[i] < 255) {
        cutout = true;
        break;
      }
    }
    return {
      id: cacheKey,
      identifier: `${namespace}:${rel}`,
      bitmap: await createImageBitmap(canvas),
      width: frame.sw,
      height: frame.sh,
      cutout,
    };
  })();
  imageCache.set(cacheKey, pending);
  return pending;
}

function missingTexture(id) {
  const canvas = new OffscreenCanvas(16, 16);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#f800f8";
  ctx.fillRect(0, 0, 16, 16);
  ctx.fillStyle = "#000";
  ctx.fillRect(8, 0, 8, 8);
  ctx.fillRect(0, 8, 8, 8);
  return createImageBitmap(canvas).then((bitmap) => ({
    id,
    identifier: "minecraft:missingno",
    bitmap,
    width: 16,
    height: 16,
    cutout: false,
    missing: true,
  }));
}

export function textureHasCutout(texture) {
  return Boolean(texture?.cutout);
}
