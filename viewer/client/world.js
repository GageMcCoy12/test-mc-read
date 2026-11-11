import { unzipSync } from "./vendor/fflate.js";
import LevelDb from "./vendor/leveldb/LevelDb.js";

import { decodeData3D } from "./biomes.js";
import {
  blockEntityKey,
  blockToChunk,
  data3dKey,
  regionCoords,
  subchunkKey,
  versionKey,
  versionKeyNew,
} from "./keys.js";
import { nbtValue, readLevelDat } from "./nbt.js";
import { combineLayers, decodeSubchunk } from "./subchunk.js";

const SILENT = {};

function zipBasename(name) {
  const normalized = name.replace(/\\/g, "/");
  return normalized.split("/").pop() || "";
}

function zipDirname(name) {
  const normalized = name.replace(/\\/g, "/");
  const index = normalized.lastIndexOf("/");
  return index === -1 ? "" : normalized.slice(0, index + 1);
}

function isTableFile(fileName) {
  return fileName.endsWith(".ldb") || fileName.endsWith(".sst");
}

function isInternalLevelDbFile(fileName) {
  return (
    fileName.startsWith("MANIFEST") ||
    fileName === "CURRENT" ||
    isTableFile(fileName) ||
    fileName.endsWith(".log")
  );
}

function looksLikeJavaSave(names) {
  return names.some((name) => {
    const normalized = name.replace(/\\/g, "/").toLowerCase();
    return /(?:^|\/)region\/r\.-?\d+\.-?\d+\.mca$/.test(normalized);
  });
}

function manifestNumber(name) {
  const match = zipBasename(name).match(/^MANIFEST-(\d+)$/i);
  return match ? Number(match[1]) : -1;
}

function readCurrentManifestName(bytes) {
  if (!bytes || !bytes.length) {
    return null;
  }
  const text = new TextDecoder("utf-8", { fatal: false }).decode(bytes).replace(/\0/g, "").trim();
  const base = zipBasename(text.replace(/\\/g, "/"));
  return base.startsWith("MANIFEST") ? base : null;
}

function pickDbRoot(names, unzipped) {
  const byDir = new Map();
  for (const name of names) {
    const normalized = name.replace(/\\/g, "/");
    const base = zipBasename(normalized);
    if (!isInternalLevelDbFile(base)) {
      continue;
    }
    const dir = zipDirname(normalized);
    const bucket = byDir.get(dir) || { current: null, manifests: [], tables: 0 };
    if (base === "CURRENT") {
      bucket.current = normalized;
    } else if (base.startsWith("MANIFEST")) {
      bucket.manifests.push(normalized);
    } else if (isTableFile(base) || base.endsWith(".log")) {
      bucket.tables += 1;
    }
    byDir.set(dir, bucket);
  }
  const roots = [...byDir.entries()].filter(([, info]) => info.tables || info.manifests.length);
  roots.sort((a, b) => b[1].tables - a[1].tables);
  const chosen = roots.find(([, info]) => info.current) || roots[0];
  if (!chosen) {
    return { dbRoot: null, manifestName: null };
  }
  const [dbRoot, info] = chosen;
  let manifestName = info.current ? readCurrentManifestName(unzipped[info.current]) : null;
  if (manifestName && !info.manifests.some((path) => zipBasename(path) === manifestName)) {
    manifestName = null;
  }
  if (!manifestName && info.manifests.length) {
    const ordered = info.manifests.slice().sort((a, b) => manifestNumber(a) - manifestNumber(b));
    manifestName = zipBasename(ordered[ordered.length - 1]);
  }
  return { dbRoot, manifestName };
}

function keepZipEntry(name) {
  const base = zipBasename(name);
  return (
    base === "CURRENT" ||
    base === "level.dat" ||
    base === "levelname.txt" ||
    isInternalLevelDbFile(base)
  );
}

function wrapDbFile(name, bytes) {
  return {
    content: bytes,
    name,
    storageRelativePath: name,
    fullPath: name,
    isContentLoaded: true,
    unload() {
      // in-memory zip entries cannot be reloaded from disk, so keep the bytes
      this.isContentLoaded = true;
    },
  };
}

function openLevelDb(files, logger) {
  const logFileArr = [];
  const ldbFileArr = [];
  const manifestFileArr = [];
  for (const file of files) {
    if (file.name.startsWith("MANIFEST")) {
      manifestFileArr.push(file);
    } else if (file.name.endsWith(".ldb") || file.name.endsWith(".sst")) {
      ldbFileArr.push(file);
    } else if (file.name.endsWith(".log")) {
      logFileArr.push(file);
    }
  }
  return new LevelDb(ldbFileArr, logFileArr, manifestFileArr, "mcread", logger);
}

export async function openWorldFile(blob, onProgress) {
  onProgress?.("unzipping world");
  const zipBytes = new Uint8Array(await blob.arrayBuffer());
  let sawJava = false;
  const unzipped = unzipSync(zipBytes, {
    filter: (file) => {
      if (looksLikeJavaSave([file.name])) {
        sawJava = true;
      }
      return keepZipEntry(file.name);
    },
  });
  const names = Object.keys(unzipped);
  const { dbRoot, manifestName } = pickDbRoot(names, unzipped);
  const dbFiles = [];
  let levelDat = null;
  let levelName = blob.name || "world";
  for (const name of names) {
    const normalized = name.replace(/\\/g, "/");
    const base = zipBasename(normalized);
    const bytes = unzipped[name];
    if (!bytes || !bytes.length) {
      continue;
    }
    const inChosenDb = dbRoot != null ? zipDirname(normalized) === dbRoot : normalized.split("/").includes("db");
    if (inChosenDb && isTableFile(base)) {
      dbFiles.push(wrapDbFile(base, bytes));
    } else if (inChosenDb && base.endsWith(".log")) {
      dbFiles.push(wrapDbFile(base, bytes));
    } else if (inChosenDb && base.startsWith("MANIFEST") && (!manifestName || base === manifestName)) {
      dbFiles.push(wrapDbFile(base, bytes));
    } else if (base === "level.dat" && !levelDat) {
      levelDat = bytes;
    } else if (base === "levelname.txt") {
      const text = new TextDecoder("utf-8", { fatal: false }).decode(bytes).replace(/\0/g, "").trim();
      if (text) {
        levelName = text;
      }
    }
  }
  if (!dbFiles.length) {
    if (sawJava) {
      throw new Error("that's a java save — this viewer reads bedrock .mcworld files (need a db/ folder)");
    }
    throw new Error("not a bedrock save — need a db/ folder inside the zip");
  }
  onProgress?.("opening leveldb");
  const db = openLevelDb(dbFiles, SILENT);
  await db.initLazy({ maxKeysInMemory: 2_000_000 });
  const spawn = { x: 0, z: 0 };
  if (levelDat) {
    try {
      const root = readLevelDat(levelDat);
      if (root.SpawnX != null) {
        spawn.x = Number(nbtValue(root.SpawnX));
      }
      if (root.SpawnZ != null) {
        spawn.z = Number(nbtValue(root.SpawnZ));
      }
      if (root.LevelName) {
        const named = nbtValue(root.LevelName).trim();
        if (named) {
          levelName = named;
        }
      }
    } catch (error) {
      console.warn("level.dat parse failed", error);
    }
  }
  return { db, name: levelName, spawn };
}

async function getValue(db, key) {
  const entry = await db.getKey(key);
  if (!entry || entry === false) {
    return null;
  }
  return entry.value || null;
}

async function loadChunkAt(db, cx, cz, dimension) {
  const version =
    (await getValue(db, versionKey(cx, cz, dimension))) ||
    (await getValue(db, versionKeyNew(cx, cz, dimension)));
  let biomes = new Map();
  try {
    const raw3d = await getValue(db, data3dKey(cx, cz, dimension));
    if (raw3d) {
      biomes = decodeData3D(raw3d);
    }
  } catch {
    biomes = new Map();
  }
  const subchunks = new Map();
  for (let cy = -4; cy <= 20; cy += 1) {
    const raw = await getValue(db, subchunkKey(cx, cz, cy, dimension));
    if (!raw) {
      continue;
    }
    const decoded = decodeSubchunk(raw);
    if (!decoded) {
      continue;
    }
    const y = decoded.cy == null ? cy : decoded.cy;
    const combined = combineLayers(decoded.layers);
    subchunks.set(y, combined);
  }
  if (!subchunks.size) {
    return null;
  }
  return {
    cx,
    cz,
    version: version ? version[0] : null,
    subchunks,
    biomes,
  };
}

export async function loadChunk(db, cx, cz, dimension = undefined) {
  if (dimension !== undefined) {
    return loadChunkAt(db, cx, cz, dimension);
  }
  return (await loadChunkAt(db, cx, cz, null)) || loadChunkAt(db, cx, cz, 0);
}

export async function loadRegion(db, cx, cz, radius, halo = 1, onProgress) {
  const chunks = new Map();
  const coords = regionCoords(cx, cz, radius + halo);
  let loaded = 0;
  for (const [ncx, ncz] of coords) {
    onProgress?.(`reading chunk ${loaded + 1}/${coords.length}`);
    const chunk = await loadChunk(db, ncx, ncz);
    loaded += 1;
    if (chunk) {
      chunk.visible = Math.abs(ncx - cx) <= radius && Math.abs(ncz - cz) <= radius;
      chunks.set(`${ncx},${ncz}`, chunk);
    }
  }
  return chunks;
}

export { blockToChunk, regionCoords, blockEntityKey };
