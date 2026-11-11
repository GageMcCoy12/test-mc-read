import { loadTexture } from "./pack.js";

const TILE = 16;
const PADDING = 1;

function nativeSize(texture) {
  return Math.max(texture.width, texture.height, TILE);
}

export async function buildAtlas(paths) {
  const unique = [...new Set(paths.filter(Boolean))];
  const textures = [];
  let tileSize = TILE;
  for (const path of unique) {
    const texture = await loadTexture(path);
    textures.push({ path, texture });
    tileSize = Math.max(tileSize, nativeSize(texture));
  }
  if (!textures.length) {
    textures.push({ path: "minecraft:missingno", texture: await loadTexture("minecraft:missingno") });
  }
  const count = textures.length;
  const columns = Math.ceil(Math.sqrt(count));
  const rows = Math.ceil(count / columns);
  const cell = tileSize + 2 * PADDING;
  const width = Math.max(columns * cell, cell);
  const height = Math.max(rows * cell, cell);
  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, width, height);
  const rects = new Map();

  textures.forEach((entry, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const x = column * cell + PADDING;
    const y = row * cell + PADDING;
    const bitmap = entry.texture.bitmap;
    ctx.drawImage(bitmap, 0, 0, bitmap.width, bitmap.height, x, y, tileSize, tileSize);
    if (PADDING > 0) {
      ctx.drawImage(canvas, x, y, 1, tileSize, x - PADDING, y, PADDING, tileSize);
      ctx.drawImage(canvas, x + tileSize - 1, y, 1, tileSize, x + tileSize, y, PADDING, tileSize);
      ctx.drawImage(canvas, x, y, tileSize, 1, x, y - PADDING, tileSize, PADDING);
      ctx.drawImage(canvas, x, y + tileSize - 1, tileSize, 1, x, y + tileSize, tileSize, PADDING);
    }
    rects.set(entry.path, {
      u0: x / width,
      v0: y / height,
      u1: (x + tileSize) / width,
      v1: (y + tileSize) / height,
    });
  });

  const blob = await canvas.convertToBlob({ type: "image/png" });
  return {
    blob,
    width,
    height,
    tileSize,
    padding: PADDING,
    remap(u, v, texture) {
      const rect = rects.get(texture);
      if (!rect) {
        return [u, v];
      }
      return [rect.u0 + u * (rect.u1 - rect.u0), rect.v0 + v * (rect.v1 - rect.v0)];
    },
  };
}
