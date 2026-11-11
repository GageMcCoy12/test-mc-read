import { cellIndex } from "./subchunk.js";

const SELF_GLOW = 0.9;
const SELF_RADIUS = 0.9;
const EMIT_CAP = 2.4;

const EMITTERS = {
  torch: [[1.0, 0.72, 0.32], 1.2, 8.0],
  wall_torch: [[1.0, 0.72, 0.32], 1.2, 8.0],
  lantern: [[1.0, 0.78, 0.38], 1.35, 10.0],
  glowstone: [[1.0, 0.86, 0.52], 1.45, 11.0],
  redstone_lamp: [[1.0, 0.82, 0.45], 1.4, 11.0],
};

function isLit(block) {
  if (!block?.properties || block.properties.lit == null) {
    return true;
  }
  const raw = String(block.properties.lit).toLowerCase();
  return raw === "true" || raw === "1";
}

function specFor(entry) {
  const name = entry?.java?.baseName;
  const spec = EMITTERS[name];
  if (!spec) {
    return null;
  }
  if (name === "redstone_lamp" && !isLit(entry.java)) {
    return null;
  }
  return spec;
}

export function collectEmitters(chunks, minY, maxY) {
  const found = [];
  for (const chunk of chunks.values()) {
    for (const [cy, sub] of chunk.subchunks) {
      const sectionLo = cy * 16;
      if (minY != null && sectionLo + 15 < minY) {
        continue;
      }
      if (maxY != null && sectionLo > maxY) {
        continue;
      }
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
            const spec = specFor(entry);
            if (!spec) {
              continue;
            }
            found.push({
              x: chunk.cx * 16 + dx + 0.5,
              y: wy + 0.5,
              z: chunk.cz * 16 + dz + 0.5,
              color: spec[0],
              strength: spec[1],
              radius: spec[2],
            });
          }
        }
      }
    }
  }
  return found;
}

function applyToPass(mesh, emitters) {
  if (!mesh.positions.length || !emitters.length) {
    return;
  }
  const emit = mesh.emit;
  const pos = mesh.positions;
  const verts = pos.length / 3;
  for (let i = 0; i < verts; i += 1) {
    const x = pos[i * 3];
    const y = pos[i * 3 + 1];
    const z = pos[i * 3 + 2];
    let r = 0;
    let g = 0;
    let b = 0;
    for (const lamp of emitters) {
      const dx = x - lamp.x;
      const dy = y - lamp.y;
      const dz = z - lamp.z;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (dist < SELF_RADIUS) {
        r += lamp.color[0] * SELF_GLOW;
        g += lamp.color[1] * SELF_GLOW;
        b += lamp.color[2] * SELF_GLOW;
      }
      if (dist < lamp.radius) {
        const weight = (1 - dist / lamp.radius) ** 2 * lamp.strength;
        r += lamp.color[0] * weight;
        g += lamp.color[1] * weight;
        b += lamp.color[2] * weight;
      }
    }
    emit[i * 3] = Math.min(r, EMIT_CAP);
    emit[i * 3 + 1] = Math.min(g, EMIT_CAP);
    emit[i * 3 + 2] = Math.min(b, EMIT_CAP);
  }
}

export function applyEmit(bake, emitters) {
  applyToPass(bake.opaque, emitters);
  applyToPass(bake.translucent, emitters);
  return bake;
}
