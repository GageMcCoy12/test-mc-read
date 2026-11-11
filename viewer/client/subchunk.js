/** Paletted Bedrock subchunks (versions 1, 8, 9) plus YZX packed indices. */

import { nbtValue, readNamed, readUnnamedCompound } from "./nbt.js";

export function decodePackedIndices(bytes, offset) {
  const header = bytes[offset];
  offset += 1;
  const bits = header >> 1;
  if (bits <= 0) {
    return { indices: null, offset, bits };
  }
  const valuesPerWord = Math.floor(32 / bits);
  const wordCount = Math.ceil(4096 / valuesPerWord);
  const indices = new Uint16Array(4096);
  const mask = bits === 32 ? 0xffffffff : (1 << bits) - 1;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let index = 0;
  for (let w = 0; w < wordCount; w += 1) {
    let word = view.getUint32(offset, true);
    offset += 4;
    for (let i = 0; i < valuesPerWord && index < 4096; i += 1) {
      indices[index] = word & mask;
      word >>>= bits;
      index += 1;
    }
  }
  return { indices, offset, bits };
}

/** Packed bits → [x,y,z] storage. Matches Amulet's reshape((16,16,16)).swapaxes(1, 2). */
export function yzxToXyz(indices) {
  const xyz = new Uint16Array(4096);
  if (!indices) {
    return xyz;
  }
  for (let x = 0; x < 16; x += 1) {
    for (let y = 0; y < 16; y += 1) {
      for (let z = 0; z < 16; z += 1) {
        const src = y + (z << 4) + (x << 8);
        const dst = x + (y << 4) + (z << 8);
        xyz[dst] = indices[src];
      }
    }
  }
  return xyz;
}

export function cellIndex(dx, dy, dz) {
  return dx + (dy << 4) + (dz << 8);
}

function readPaletteEntry(bytes, offset) {
  // Disk palettes are a named root compound: 0a 00 00 {name, states, version}.
  // Older layers sometimes store just the compound body.
  if (bytes[offset] === 10) {
    const parsed = readNamed(bytes, offset);
    return { value: parsed.value, offset: parsed.offset };
  }
  return readUnnamedCompound(bytes, offset);
}

function readPalette(bytes, offset, count) {
  const palette = [];
  let cursor = offset;
  for (let i = 0; i < count; i += 1) {
    const parsed = readPaletteEntry(bytes, cursor);
    palette.push(blockFromNbt(parsed.value));
    cursor = parsed.offset;
  }
  return { palette, offset: cursor };
}

export function blockFromNbt(compound) {
  const rawName = nbtValue(compound.name || "minecraft:air");
  const parts = rawName.split(":");
  const namespace = parts.length > 1 ? parts[0] : "minecraft";
  const baseName = parts.length > 1 ? parts.slice(1).join(":") : parts[0];
  const states = compound.states || {};
  const properties = {};
  for (const [key, value] of Object.entries(states)) {
    properties[key] = nbtValue(value);
  }
  if (compound.val != null && Object.keys(properties).length === 0) {
    properties.block_data = nbtValue(compound.val);
  }
  return { namespace, baseName, properties, namespaced: `${namespace}:${baseName}` };
}

function decodeLayer(bytes, offset) {
  const packed = decodePackedIndices(bytes, offset);
  let cursor = packed.offset;
  if (packed.indices == null) {
    const parsed = readPalette(bytes, cursor, 1);
    return {
      indices: new Uint16Array(4096),
      palette: parsed.palette.length
        ? parsed.palette
        : [blockFromNbt({ name: "minecraft:air", states: {} })],
      offset: parsed.offset,
    };
  }
  const count = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(
    cursor,
    true
  );
  if (count > 4096) {
    throw new Error(`palette count ${count} is too large`);
  }
  cursor += 4;
  const parsed = readPalette(bytes, cursor, count);
  return {
    indices: yzxToXyz(packed.indices),
    palette: parsed.palette,
    offset: parsed.offset,
  };
}

export function decodeSubchunk(bytes) {
  if (!bytes || bytes.length === 0) {
    return null;
  }
  const version = bytes[0];
  let offset = 1;
  let storageCount = 1;
  let cy = null;
  if (version === 1) {
    storageCount = 1;
  } else if (version === 8) {
    storageCount = bytes[1];
    offset = 2;
  } else if (version === 9) {
    storageCount = bytes[1];
    cy = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getInt8(2);
    offset = 3;
  } else if (version >= 0 && version <= 7) {
    return null;
  } else {
    throw new Error(`sub-chunk version ${version} is not known`);
  }

  const layers = [];
  for (let i = 0; i < storageCount; i += 1) {
    const layer = decodeLayer(bytes, offset);
    layers.push(layer);
    offset = layer.offset;
  }
  return { version, cy, layers };
}

export function combineLayers(layers) {
  if (!layers.length) {
    return { indices: new Uint16Array(4096), palette: [] };
  }
  if (layers.length === 1) {
    return { indices: layers[0].indices, palette: layers[0].palette.map((block) => [block]) };
  }
  const keyToIndex = new Map();
  const palette = [];
  const indices = new Uint16Array(4096);
  for (let i = 0; i < 4096; i += 1) {
    const stack = [];
    for (let layer = 0; layer < layers.length; layer += 1) {
      const block = layers[layer].palette[layers[layer].indices[i]] || {
        namespace: "minecraft",
        baseName: "air",
        properties: {},
        namespaced: "minecraft:air",
      };
      if (layer > 0 && block.baseName === "air") {
        continue;
      }
      stack.push(block);
    }
    const key = stack.map(blockKey).join("+");
    let paletteIndex = keyToIndex.get(key);
    if (paletteIndex == null) {
      paletteIndex = palette.length;
      keyToIndex.set(key, paletteIndex);
      palette.push(stack);
    }
    indices[i] = paletteIndex;
  }
  return { indices, palette };
}

export function blockKey(block) {
  const props = Object.keys(block.properties)
    .sort()
    .map((name) => `${name}=${block.properties[name]}`)
    .join(",");
  return props ? `${block.namespaced}[${props}]` : block.namespaced;
}
