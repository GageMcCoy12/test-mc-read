/** Bedrock LevelDB chunk keys. Overworld is <x i32><z i32><tag>[<cy i8>]. */

export const TAG = {
  DATA_3D: 0x2b,
  VERSION_NEW: 0x2c,
  SUBCHUNK: 0x2f,
  BLOCK_ENTITY: 0x31,
  ENTITY: 0x32,
  FINALIZED: 0x36,
  VERSION: 0x76,
};

export function bytesToKey(bytes) {
  let text = "";
  for (let i = 0; i < bytes.length; i += 1) {
    text += String.fromCharCode(bytes[i]);
  }
  return text;
}

export function keyToBytes(key) {
  const bytes = new Uint8Array(key.length);
  for (let i = 0; i < key.length; i += 1) {
    bytes[i] = key.charCodeAt(i) & 0xff;
  }
  return bytes;
}

export function chunkPrefix(cx, cz, dimension = null) {
  const size = dimension == null ? 8 : 12;
  const bytes = new Uint8Array(size);
  const view = new DataView(bytes.buffer);
  view.setInt32(0, cx, true);
  view.setInt32(4, cz, true);
  if (dimension != null) {
    view.setInt32(8, dimension, true);
  }
  return bytes;
}

export function concatBytes(...parts) {
  const length = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

export function tagKey(cx, cz, tag, extra = null, dimension = null) {
  const prefix = chunkPrefix(cx, cz, dimension);
  const extraBytes = extra == null ? 0 : extra.length;
  const out = new Uint8Array(prefix.length + 1 + extraBytes);
  out.set(prefix);
  out[prefix.length] = tag;
  if (extra) {
    out.set(extra, prefix.length + 1);
  }
  return bytesToKey(out);
}

export function data3dKey(cx, cz, dimension = null) {
  return tagKey(cx, cz, TAG.DATA_3D, null, dimension);
}

export function subchunkKey(cx, cz, cy, dimension = null) {
  return tagKey(cx, cz, TAG.SUBCHUNK, Uint8Array.of(cy & 0xff), dimension);
}

export function versionKey(cx, cz, dimension = null) {
  return tagKey(cx, cz, TAG.VERSION, null, dimension);
}

export function versionKeyNew(cx, cz, dimension = null) {
  return tagKey(cx, cz, TAG.VERSION_NEW, null, dimension);
}

export function blockEntityKey(cx, cz, dimension = null) {
  return tagKey(cx, cz, TAG.BLOCK_ENTITY, null, dimension);
}

export function blockToChunk(x, z) {
  return [Math.floor(x / 16), Math.floor(z / 16)];
}

export function regionCoords(cx, cz, radius) {
  const coords = [];
  for (let z = cz - radius; z <= cz + radius; z += 1) {
    for (let x = cx - radius; x <= cx + radius; x += 1) {
      coords.push([x, z]);
    }
  }
  return coords;
}
