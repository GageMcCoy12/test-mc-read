import { biomeTintAt } from "./biomes.js";
import { CULL_OFFSETS } from "./models.js";
import { usesTranslucentPass } from "./resolve.js";
import { cellIndex } from "./subchunk.js";

function emptyMesh() {
  return {
    positions: new Float32Array(0),
    uvs: new Float32Array(0),
    colors: new Float32Array(0),
    indices: new Uint32Array(0),
    emit: new Float32Array(0),
    light: new Float32Array(0),
  };
}

class Accumulator {
  constructor(atlas) {
    this.atlas = atlas;
    this.positions = [];
    this.uvs = [];
    this.colors = [];
    this.indices = [];
    this.vertOffset = 0;
  }

  appendBucket(verts, uvs, tints, faces, textureIndex, textures, offset, tintKind, biomeTint) {
    if (!verts?.length || !faces?.length) {
      return;
    }
    const count = verts.length / 3;
    const remapped = new Float32Array(uvs.length);
    remapped.set(uvs);
    const triangleCount = Math.floor(faces.length / 3);
    const overlay = tintKind && biomeTint ? biomeTint[tintKind] : null;
    for (let i = 0; i < Math.min(triangleCount, textureIndex.length); i += 1) {
      const texture = textures[textureIndex[i]] || "";
      for (let k = 0; k < 3; k += 1) {
        const vi = faces[i * 3 + k];
        if (vi >= 0 && vi < count && texture) {
          const uv = this.atlas.remap(uvs[vi * 2], uvs[vi * 2 + 1], texture);
          remapped[vi * 2] = uv[0];
          remapped[vi * 2 + 1] = uv[1];
        }
      }
    }
    for (let i = 0; i < count; i += 1) {
      this.positions.push(verts[i * 3] + offset[0], verts[i * 3 + 1] + offset[1], verts[i * 3 + 2] + offset[2]);
      this.uvs.push(remapped[i * 2], remapped[i * 2 + 1]);
      const tr = tints && tints.length >= (i + 1) * 3 ? tints[i * 3] : 1;
      const tg = tints && tints.length >= (i + 1) * 3 ? tints[i * 3 + 1] : 1;
      const tb = tints && tints.length >= (i + 1) * 3 ? tints[i * 3 + 2] : 1;
      const tinted = tr <= 0.99 || tg <= 0.99 || tb <= 0.99;
      if (overlay && tinted) {
        this.colors.push(overlay[0], overlay[1], overlay[2]);
      } else {
        this.colors.push(tr, tg, tb);
      }
    }
    for (const index of faces) {
      this.indices.push(index + this.vertOffset);
    }
    this.vertOffset += count;
  }

  finish() {
    if (!this.indices.length) {
      return emptyMesh();
    }
    const verts = this.vertOffset;
    return {
      positions: Float32Array.from(this.positions),
      uvs: Float32Array.from(this.uvs),
      colors: Float32Array.from(this.colors),
      indices: Uint32Array.from(this.indices),
      emit: new Float32Array(verts * 3),
      light: new Float32Array(verts * 2),
    };
  }
}

export function entryAt(chunks, x, y, z) {
  const cx = Math.floor(x / 16);
  const cz = Math.floor(z / 16);
  const chunk = chunks.get(`${cx},${cz}`);
  if (!chunk) {
    return null;
  }
  const dx = x - cx * 16;
  const dz = z - cz * 16;
  const cy = Math.floor(y / 16);
  const dy = y - cy * 16;
  const sub = chunk.subchunks.get(cy);
  if (!sub) {
    return null;
  }
  const index = sub.indices[cellIndex(dx, dy, dz)];
  return chunk.resolved[index] || null;
}

export function entryForCull(chunks, x, y, z, minY, maxY) {
  if (minY != null && y < minY) {
    return null;
  }
  if (maxY != null && y > maxY) {
    return null;
  }
  const cx = Math.floor(x / 16);
  const cz = Math.floor(z / 16);
  const chunk = chunks.get(`${cx},${cz}`);
  if (!chunk?.visible) {
    return null;
  }
  return entryAt(chunks, x, y, z);
}

export function shouldCull(entry, neighbor, direction) {
  if (!direction || direction === "none") {
    return false;
  }
  if (!neighbor || neighbor.isEmpty) {
    return false;
  }
  if (neighbor.isOpaque) {
    return true;
  }
  if (entry.isFluid && neighbor.isFluid) {
    return true;
  }
  return false;
}

export function meshChunk(chunks, cx, cz, atlas, minY, maxY) {
  const chunk = chunks.get(`${cx},${cz}`);
  if (!chunk) {
    throw new Error(`chunk (${cx}, ${cz}) is not in the grid`);
  }
  const opaque = new Accumulator(atlas);
  const translucent = new Accumulator(atlas);
  const subYs = [...chunk.subchunks.keys()].sort((a, b) => a - b);
  const storedMin = subYs.length ? subYs[0] * 16 : 0;
  const storedMax = subYs.length ? subYs[subYs.length - 1] * 16 + 15 : 0;
  const emitMin = minY == null ? storedMin : Math.max(storedMin, minY);
  const emitMax = maxY == null ? storedMax : Math.min(storedMax, maxY);

  for (const cy of subYs) {
    const sectionLo = cy * 16;
    const sectionHi = sectionLo + 15;
    if (minY != null && sectionHi < minY) {
      continue;
    }
    if (maxY != null && sectionLo > maxY) {
      continue;
    }
    const sub = chunk.subchunks.get(cy);
    for (let dx = 0; dx < 16; dx += 1) {
      for (let dy = 0; dy < 16; dy += 1) {
        for (let dz = 0; dz < 16; dz += 1) {
          const wy = sectionLo + dy;
          if (minY != null && wy < minY) {
            continue;
          }
          if (maxY != null && wy > maxY) {
            continue;
          }
          const entry = chunk.resolved[sub.indices[cellIndex(dx, dy, dz)]];
          if (!entry || entry.skip || !entry.mesh) {
            continue;
          }
          const wx = cx * 16 + dx;
          const wz = cz * 16 + dz;
          const acc = usesTranslucentPass(entry) ? translucent : opaque;
          const mesh = entry.mesh;
          const biomeTint = entry.tintKind ? biomeTintAt(chunk, dx, wy, dz) : null;
          for (const cullDir of Object.keys(mesh.verts)) {
            let neighbor = null;
            if (cullDir !== "none") {
              const [ox, oy, oz] = CULL_OFFSETS[cullDir];
              neighbor = entryForCull(chunks, wx + ox, wy + oy, wz + oz, minY, maxY);
            }
            if (shouldCull(entry, neighbor, cullDir)) {
              continue;
            }
            acc.appendBucket(
              mesh.verts[cullDir],
              mesh.uvs[cullDir],
              mesh.tints[cullDir],
              mesh.faces[cullDir],
              mesh.textureIndex[cullDir],
              mesh.textures,
              [wx, wy, wz],
              entry.tintKind,
              biomeTint
            );
          }
        }
      }
    }
  }

  return {
    opaque: opaque.finish(),
    translucent: translucent.finish(),
    chunk: [cx, cz],
    origin: [cx * 16, emitMin, cz * 16],
    yRange: [emitMin, emitMax],
  };
}

function concatMeshes(meshes) {
  const nonempty = meshes.filter((mesh) => mesh.indices.length);
  if (!nonempty.length) {
    return emptyMesh();
  }
  let verts = 0;
  let indices = 0;
  for (const mesh of nonempty) {
    verts += mesh.positions.length / 3;
    indices += mesh.indices.length;
  }
  const positions = new Float32Array(verts * 3);
  const uvs = new Float32Array(verts * 2);
  const colors = new Float32Array(verts * 3);
  const emit = new Float32Array(verts * 3);
  const light = new Float32Array(verts * 2);
  const indexOut = new Uint32Array(indices);
  let vOff = 0;
  let iOff = 0;
  for (const mesh of nonempty) {
    positions.set(mesh.positions, vOff * 3);
    uvs.set(mesh.uvs, vOff * 2);
    colors.set(mesh.colors, vOff * 3);
    emit.set(mesh.emit, vOff * 3);
    light.set(mesh.light, vOff * 2);
    for (let i = 0; i < mesh.indices.length; i += 1) {
      indexOut[iOff + i] = mesh.indices[i] + vOff;
    }
    vOff += mesh.positions.length / 3;
    iOff += mesh.indices.length;
  }
  return { positions, uvs, colors, indices: indexOut, emit, light };
}

export function mergeBakes(bakes, center) {
  if (!bakes.length) {
    throw new Error("no chunk bakes to merge");
  }
  let head = bakes[0];
  if (center) {
    for (const bake of bakes) {
      if (bake.chunk[0] === center[0] && bake.chunk[1] === center[1]) {
        head = bake;
        break;
      }
    }
  }
  const yLo = Math.min(...bakes.map((bake) => bake.yRange[0]));
  const yHi = Math.max(...bakes.map((bake) => bake.yRange[1]));
  const originX = Math.min(...bakes.map((bake) => bake.origin[0]));
  const originZ = Math.min(...bakes.map((bake) => bake.origin[2]));
  return {
    opaque: concatMeshes(bakes.map((bake) => bake.opaque)),
    translucent: concatMeshes(bakes.map((bake) => bake.translucent)),
    chunk: head.chunk,
    origin: [originX, yLo, originZ],
    yRange: [yLo, yHi],
  };
}
