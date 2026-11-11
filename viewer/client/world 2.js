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

function isInternalLevelDbFile(fileName) {
  return fileName.startsWith("MANIFEST") || fileName.endsWith(".ldb") || fileName.endsWith(".log");
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
      this.content = null;
      this.isContentLoaded = false;
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
    } else if (file.name.endsWith(".ldb")) {
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
  const unzipped = unzipSync(zipBytes, { filter: (file) => keepZipEntry(file.name) });
  const names = Object.keys(unzipped);
  const currentPath = names.find((name) => zipBasename(name) === "CURRENT");
  const dbRoot = currentPath ? zipDirname(currentPath) : null;
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
    const inDb =
      dbRoot != null
        ? normalized.startsWith(dbRoot) && isInternalLevelDbFile(base)
        : normalized.split("/").includes("db") && isInternalLevelDbFile(base);
    if (inDb) {
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
    throw new Error("not a bedrock save — need a db/ folder inside the zip");
  }
  onProgress?.("opening leveldb");
  const db = openLevelDb(dbFiles, SILENT);
  await db.initLazy({ maxKeysInMemory: 80000 });
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

export async function loadChunk(db, cx, cz, dimension = null) {
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
