/** Bedrock Data3D biomes (4×4×4) plus Java grass/water/foliage tints. */

import { decodePackedIndices, yzxToXyz, cellIndex } from "./subchunk.js";

const PLAINS_ID = 1;
const PLAINS_FALLBACK = unpackRgb(0x3f76e4, 0x91bd59, 0x77ab2f);

let table = null;

function rgb(packed) {
  return [((packed >> 16) & 255) / 255, ((packed >> 8) & 255) / 255, (packed & 255) / 255];
}

function unpackRgb(water, grass, foliage) {
  return { water: rgb(water), grass: rgb(grass), foliage: rgb(foliage) };
}

export async function loadBiomeTints() {
  if (table) {
    return table;
  }
  const url = new URL("./data/biome-tints.json", import.meta.url);
  try {
    const response = await fetch(url);
    if (!response.ok) {
      table = { fallback: PLAINS_FALLBACK, ids: new Map() };
      return table;
    }
    const json = await response.json();
    const ids = new Map();
    for (const [key, channels] of Object.entries(json.ids || {})) {
      ids.set(Number(key), unpackRgb(channels[0], channels[1], channels[2]));
    }
    const fallback = json.fallback || [];
    table = {
      fallback: unpackRgb(fallback[0] ?? 0x3f76e4, fallback[1] ?? 0x91bd59, fallback[2] ?? 0x77ab2f),
      ids,
    };
  } catch {
    table = { fallback: PLAINS_FALLBACK, ids: new Map() };
  }
  return table;
}

function fillSection(id) {
  return new Uint32Array(64).fill(id >>> 0);
}

function downsample(xyz, palette) {
  const cells = new Uint32Array(64);
  for (let bx = 0; bx < 4; bx += 1) {
    for (let by = 0; by < 4; by += 1) {
      for (let bz = 0; bz < 4; bz += 1) {
        const src = cellIndex(bx * 4, by * 4, bz * 4);
        const index = xyz[src];
        cells[bx + (by << 2) + (bz << 4)] = (palette[index] ?? PLAINS_ID) >>> 0;
      }
    }
  }
  return cells;
}

export function decodeData3D(bytes, floorCy = -4) {
  const biomes = new Map();
  if (!bytes || bytes.length <= 512) {
    return biomes;
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 512;
  let cy = floorCy;
  while (offset < bytes.length && cy <= 20) {
    const header = bytes[offset];
    if (header === 0xff) {
      offset += 1;
      cy += 1;
      continue;
    }
    const bits = header >> 1;
    if (bits > 16 || (bits > 0 && Math.floor(32 / bits) < 1)) {
      break;
    }
    let packed;
    try {
      packed = decodePackedIndices(bytes, offset);
    } catch {
      break;
    }
    offset = packed.offset;
    if (packed.bits === 0) {
      if (offset + 4 > bytes.length) {
        break;
      }
      biomes.set(cy, fillSection(view.getUint32(offset, true)));
      offset += 4;
    } else if (packed.indices) {
      if (offset + 4 > bytes.length) {
        break;
      }
      const paletteLen = view.getUint32(offset, true);
      offset += 4;
      if (paletteLen <= 0 || paletteLen > 256 || offset + paletteLen * 4 > bytes.length) {
        break;
      }
      const palette = new Int32Array(paletteLen);
      for (let i = 0; i < paletteLen; i += 1) {
        palette[i] = view.getInt32(offset, true);
        offset += 4;
      }
      biomes.set(cy, downsample(yzxToXyz(packed.indices), palette));
    } else {
      break;
    }
    cy += 1;
  }
  return biomes;
}

function biomeIdAt(chunk, dx, wy, dz) {
  const biomes = chunk?.biomes;
  if (!biomes || !biomes.size) {
    return PLAINS_ID;
  }
  const cy0 = Math.floor(wy / 16);
  const dy = wy - cy0 * 16;
  const cell = (dx >> 2) + ((dy >> 2) << 2) + ((dz >> 2) << 4);
  for (let cy = cy0; cy >= -4; cy -= 1) {
    const section = biomes.get(cy);
    if (section) {
      return section[cell];
    }
  }
  const first = biomes.values().next().value;
  return first ? first[cell] : PLAINS_ID;
}

export function tintForId(id) {
  return table?.ids.get(id) || table?.fallback || PLAINS_FALLBACK;
}

export function biomeTintAt(chunk, dx, wy, dz) {
  return tintForId(biomeIdAt(chunk, dx, wy, dz));
}
