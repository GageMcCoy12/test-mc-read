/** Block + sky flood fill → per-vertex lightmap UVs. Port of mcread/light.py. */

import { cellIndex } from "./subchunk.js";

const WATER_OPACITY = 3;
const AO_STEP = 0.2;
const AO_FLOOR = 0.2;

const LIGHT_LEVELS = {
  beacon: 15,
  conduit: 15,
  end_gateway: 15,
  end_portal: 15,
  fire: 15,
  glowstone: 15,
  jack_o_lantern: 15,
  lantern: 15,
  lava: 15,
  lava_cauldron: 15,
  flowing_lava: 15,
  sea_lantern: 15,
  shroomlight: 15,
  ochre_froglight: 15,
  verdant_froglight: 15,
  pearlescent_froglight: 15,
  torch: 14,
  wall_torch: 14,
  end_rod: 14,
  torchflower: 14,
  nether_portal: 11,
  crying_obsidian: 10,
  soul_lantern: 10,
  soul_torch: 10,
  soul_wall_torch: 10,
  soul_fire: 10,
  enchanting_table: 7,
  ender_chest: 7,
  glow_lichen: 7,
  magma_block: 3,
  sculk_catalyst: 6,
  amethyst_cluster: 5,
  large_amethyst_bud: 4,
  medium_amethyst_bud: 2,
  small_amethyst_bud: 1,
  brewing_stand: 1,
  brown_mushroom: 1,
  dragon_egg: 1,
  end_portal_frame: 1,
  sculk: 1,
  lit_redstone_lamp: 15,
  lit_furnace: 13,
  lit_blast_furnace: 13,
  lit_smoker: 13,
  lit_redstone_torch: 7,
  unlit_redstone_torch: 0,
};

const LIT_ALWAYS = new Set([
  "redstone_lamp",
  "furnace",
  "blast_furnace",
  "smoker",
  "campfire",
  "soul_campfire",
  "redstone_torch",
  "redstone_wall_torch",
]);

const CAMPFIRE_LEVEL = { campfire: 15, soul_campfire: 10 };
const FURNACE_LEVEL = { furnace: 13, blast_furnace: 13, smoker: 13 };
const REDSTONE_TORCH_LEVEL = { redstone_torch: 7, redstone_wall_torch: 7 };

function javaOf(entry) {
  return entry?.java || null;
}

function prop(block, name, fallback = "") {
  if (!block?.properties || block.properties[name] == null) {
    return fallback;
  }
  return String(block.properties[name]).toLowerCase();
}

function isTrue(block, name, fallback = false) {
  const value = prop(block, name, fallback ? "true" : "false");
  return value === "true" || value === "1" || value === "yes";
}

function intProp(block, name, fallback = 0) {
  const value = Number(prop(block, name, String(fallback)));
  return Number.isFinite(value) ? value : fallback;
}

function copperBulbLevel(name) {
  if (name.includes("oxidized")) {
    return 4;
  }
  if (name.includes("weathered")) {
    return 8;
  }
  if (name.includes("exposed")) {
    return 12;
  }
  return 15;
}

export function lightEmission(entry) {
  const block = javaOf(entry);
  if (!block) {
    return 0;
  }
  const name = block.baseName;
  if (name in LIGHT_LEVELS) {
    return LIGHT_LEVELS[name];
  }
  if (LIT_ALWAYS.has(name)) {
    if (!isTrue(block, "lit", true)) {
      return 0;
    }
    if (name in CAMPFIRE_LEVEL) {
      return CAMPFIRE_LEVEL[name];
    }
    if (name in FURNACE_LEVEL) {
      return FURNACE_LEVEL[name];
    }
    if (name in REDSTONE_TORCH_LEVEL) {
      return REDSTONE_TORCH_LEVEL[name];
    }
    return 15;
  }
  if (name.endsWith("copper_bulb")) {
    return isTrue(block, "lit") ? copperBulbLevel(name) : 0;
  }
  if (name.endsWith("candle_cake")) {
    return isTrue(block, "lit") ? 3 : 0;
  }
  if (name.endsWith("candle")) {
    if (!isTrue(block, "lit")) {
      return 0;
    }
    return 3 * Math.max(1, Math.min(4, intProp(block, "candles", 1)));
  }
  if (name === "sea_pickle") {
    if (!isTrue(block, "waterlogged")) {
      return 0;
    }
    const pickles = Math.max(1, Math.min(4, intProp(block, "pickles", 1)));
    return { 1: 6, 2: 9, 3: 12, 4: 15 }[pickles];
  }
  if (name === "cave_vines" || name === "cave_vines_plant") {
    return isTrue(block, "berries") ? 14 : 0;
  }
  if (name === "respawn_anchor") {
    return { 0: 0, 1: 3, 2: 7, 3: 11, 4: 15 }[intProp(block, "charges", 0)] || 0;
  }
  if (name === "light") {
    return Math.max(0, Math.min(15, intProp(block, "level", 15)));
  }
  return 0;
}

function isWater(entry) {
  if (!entry?.isFluid) {
    return false;
  }
  const block = javaOf(entry);
  if (!block) {
    return true;
  }
  return !block.baseName.includes("lava");
}

export function encodeLight(block, sky) {
  return [(block + 0.5) / 16, (sky + 0.5) / 16];
}

function fieldIndex(field, x, y, z) {
  const ix = x - field.origin[0];
  const iy = y - field.origin[1];
  const iz = z - field.origin[2];
  if (ix < 0 || iy < 0 || iz < 0 || ix >= field.sx || iy >= field.sy || iz >= field.sz) {
    return -1;
  }
  return ix * field.sy * field.sz + iy * field.sz + iz;
}

function levelsAt(field, x, y, z) {
  const i = fieldIndex(field, x, y, z);
  if (i < 0 || !field.filled[i]) {
    return [0, 0];
  }
  return [field.block[i], field.sky[i]];
}

function isOpaqueAt(field, x, y, z) {
  const i = fieldIndex(field, x, y, z);
  return i >= 0 && field.opaque[i] !== 0;
}

function* iterCells(chunks) {
  for (const chunk of chunks.values()) {
    for (const [cy, sub] of chunk.subchunks) {
      const sectionLo = cy * 16;
      for (let dx = 0; dx < 16; dx += 1) {
        const wx = chunk.cx * 16 + dx;
        for (let dz = 0; dz < 16; dz += 1) {
          const wz = chunk.cz * 16 + dz;
          for (let dy = 0; dy < 16; dy += 1) {
            const wy = sectionLo + dy;
            const entry = chunk.resolved[sub.indices[cellIndex(dx, dy, dz)]] || null;
            yield [wx, wy, wz, entry];
          }
        }
      }
    }
  }
}

function allocate(chunks) {
  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;
  let any = false;
  for (const [x, y, z] of iterCells(chunks)) {
    any = true;
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (z < minZ) minZ = z;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
    if (z > maxZ) maxZ = z;
  }
  if (!any) {
    return null;
  }
  const sx = maxX - minX + 1;
  const sy = maxY - minY + 1;
  const sz = maxZ - minZ + 1;
  const n = sx * sy * sz;
  return {
    origin: [minX, minY, minZ],
    sx,
    sy,
    sz,
    block: new Uint8Array(n),
    sky: new Uint8Array(n),
    opaque: new Uint8Array(n),
    water: new Uint8Array(n),
    filled: new Uint8Array(n),
  };
}

function paintVolume(chunks, field) {
  const emit = new Uint8Array(field.block.length);
  for (const [x, y, z, entry] of iterCells(chunks)) {
    const i = fieldIndex(field, x, y, z);
    field.filled[i] = 1;
    if (!entry) {
      continue;
    }
    if (entry.isOpaque) {
      field.opaque[i] = 1;
    }
    if (isWater(entry)) {
      field.water[i] = 1;
    }
    const level = lightEmission(entry);
    if (level > emit[i]) {
      emit[i] = level;
    }
  }
  return emit;
}

function dilateBlock(emit, opaque, water, sx, sy, sz) {
  const n = emit.length;
  let work = new Int16Array(n);
  let out = new Int16Array(n);
  work.set(emit);
  const at = (x, y, z) => x * sy * sz + y * sz + z;
  for (let pass = 0; pass < 15; pass += 1) {
    for (let x = 0; x < sx; x += 1) {
      for (let y = 0; y < sy; y += 1) {
        for (let z = 0; z < sz; z += 1) {
          const i = at(x, y, z);
          if (opaque[i]) {
            out[i] = emit[i];
            continue;
          }
          const drop = water[i] ? WATER_OPACITY : 1;
          let incoming = 0;
          if (x > 0) incoming = Math.max(incoming, work[at(x - 1, y, z)]);
          if (x + 1 < sx) incoming = Math.max(incoming, work[at(x + 1, y, z)]);
          if (y > 0) incoming = Math.max(incoming, work[at(x, y - 1, z)]);
          if (y + 1 < sy) incoming = Math.max(incoming, work[at(x, y + 1, z)]);
          if (z > 0) incoming = Math.max(incoming, work[at(x, y, z - 1)]);
          if (z + 1 < sz) incoming = Math.max(incoming, work[at(x, y, z + 1)]);
          const nxt = Math.max(incoming - drop, 0);
          out[i] = Math.max(work[i], nxt, emit[i]);
        }
      }
    }
    const swap = work;
    work = out;
    out = swap;
  }
  const block = new Uint8Array(n);
  for (let i = 0; i < n; i += 1) {
    block[i] = work[i] < 0 ? 0 : work[i] > 15 ? 15 : work[i];
  }
  return block;
}

function seedSky(field) {
  const { sx, sy, sz } = field;
  const sky = new Int16Array(field.block.length);
  const at = (x, y, z) => x * sy * sz + y * sz + z;
  for (let ix = 0; ix < sx; ix += 1) {
    for (let iz = 0; iz < sz; iz += 1) {
      let exposed = true;
      for (let iy = sy - 1; iy >= 0; iy -= 1) {
        const i = at(ix, iy, iz);
        if (!field.filled[i]) {
          continue;
        }
        if (field.opaque[i] || field.water[i]) {
          exposed = false;
          continue;
        }
        if (exposed) {
          sky[i] = 15;
        }
      }
    }
  }
  return sky;
}

function dilateSky(seed, opaque, water, sx, sy, sz) {
  const n = seed.length;
  let work = new Int16Array(n);
  let out = new Int16Array(n);
  work.set(seed);
  const at = (x, y, z) => x * sy * sz + y * sz + z;
  for (let pass = 0; pass < 15; pass += 1) {
    for (let x = 0; x < sx; x += 1) {
      for (let y = 0; y < sy; y += 1) {
        for (let z = 0; z < sz; z += 1) {
          const i = at(x, y, z);
          if (opaque[i]) {
            out[i] = seed[i];
            continue;
          }
          const drop = water[i] ? WATER_OPACITY : 1;
          const fromUp = y + 1 < sy ? work[at(x, y + 1, z)] : 0;
          const fromAbove = fromUp === 15 && !water[i] ? 15 : Math.max(fromUp - drop, 0);
          let incoming = fromAbove;
          if (x > 0) incoming = Math.max(incoming, Math.max(work[at(x - 1, y, z)] - drop, 0));
          if (x + 1 < sx) incoming = Math.max(incoming, Math.max(work[at(x + 1, y, z)] - drop, 0));
          if (y > 0) incoming = Math.max(incoming, Math.max(work[at(x, y - 1, z)] - drop, 0));
          if (z > 0) incoming = Math.max(incoming, Math.max(work[at(x, y, z - 1)] - drop, 0));
          if (z + 1 < sz) incoming = Math.max(incoming, Math.max(work[at(x, y, z + 1)] - drop, 0));
          out[i] = Math.max(work[i], incoming, seed[i]);
        }
      }
    }
    const swap = work;
    work = out;
    out = swap;
  }
  const sky = new Uint8Array(n);
  for (let i = 0; i < n; i += 1) {
    sky[i] = work[i] < 0 ? 0 : work[i] > 15 ? 15 : work[i];
  }
  return sky;
}

export function computeLightField(chunks) {
  const field = allocate(chunks);
  if (!field) {
    return {
      origin: [0, 0, 0],
      sx: 1,
      sy: 1,
      sz: 1,
      block: new Uint8Array(1),
      sky: new Uint8Array(1),
      opaque: new Uint8Array(1),
      water: new Uint8Array(1),
      filled: new Uint8Array(1),
    };
  }
  const emit = paintVolume(chunks, field);
  field.block = dilateBlock(emit, field.opaque, field.water, field.sx, field.sy, field.sz);
  field.sky = dilateSky(seedSky(field), field.opaque, field.water, field.sx, field.sy, field.sz);
  return field;
}

function dominantAxis(nx, ny, nz) {
  const ax = Math.abs(nx);
  const ay = Math.abs(ny);
  const az = Math.abs(nz);
  if (ay >= ax && ay >= az) {
    return [1, ny >= 0 ? 1 : -1];
  }
  if (az >= ax) {
    return [2, nz >= 0 ? 1 : -1];
  }
  return [0, nx >= 0 ? 1 : -1];
}

export function sampleFaceVertex(field, x, y, z, normal) {
  const [nx, ny, nz] = normal;
  const [axis, sign] = dominantAxis(nx, ny, nz);
  const pos = [x, y, z];
  const nudged = [x, y, z];
  nudged[axis] += 1e-3 * sign;
  const cNorm = Math.floor(nudged[axis]);
  const tangents = [];
  for (let i = 0; i < 3; i += 1) {
    if (i !== axis) {
      tangents.push(i);
    }
  }
  const cells = [];
  for (const du of [0, -1]) {
    for (const dv of [0, -1]) {
      const cell = [0, 0, 0];
      cell[axis] = cNorm;
      cell[tangents[0]] = Math.floor(pos[tangents[0]] + 1e-6) + du;
      cell[tangents[1]] = Math.floor(pos[tangents[1]] + 1e-6) + dv;
      cells.push(cell);
    }
  }
  let blockSum = 0;
  let skySum = 0;
  for (const cell of cells) {
    const [block, sky] = levelsAt(field, cell[0], cell[1], cell[2]);
    blockSum += block;
    skySum += sky;
  }
  const side1 = isOpaqueAt(field, cells[1][0], cells[1][1], cells[1][2]);
  const side2 = isOpaqueAt(field, cells[2][0], cells[2][1], cells[2][2]);
  const corner =
    isOpaqueAt(field, cells[0][0], cells[0][1], cells[0][2]) || (side1 && side2);
  const occluded = Number(side1) + Number(side2) + Number(corner);
  const ao = Math.max(1 - occluded * AO_STEP, AO_FLOOR);
  return [blockSum / 4, skySum / 4, ao];
}

function triangleNormal(px0, py0, pz0, px1, py1, pz1, px2, py2, pz2) {
  const ux = px1 - px0;
  const uy = py1 - py0;
  const uz = pz1 - pz0;
  const vx = px2 - px0;
  const vy = py2 - py0;
  const vz = pz2 - pz0;
  const nx = uy * vz - uz * vy;
  const ny = uz * vx - ux * vz;
  const nz = ux * vy - uy * vx;
  const len = Math.hypot(nx, ny, nz);
  if (len < 1e-8) {
    return null;
  }
  return [nx / len, ny / len, nz / len];
}

function stamp(mesh, field) {
  const verts = mesh.positions.length / 3;
  if (!verts) {
    return mesh;
  }
  const pos = mesh.positions;
  const colors = new Float32Array(mesh.colors);
  const light = new Float32Array(verts * 2);
  const written = new Uint8Array(verts);
  const indices = mesh.indices;
  for (let i = 0; i < indices.length; i += 3) {
    const i0 = indices[i];
    const i1 = indices[i + 1];
    const i2 = indices[i + 2];
    if (i0 >= verts || i1 >= verts || i2 >= verts) {
      continue;
    }
    const normal =
      triangleNormal(
        pos[i0 * 3],
        pos[i0 * 3 + 1],
        pos[i0 * 3 + 2],
        pos[i1 * 3],
        pos[i1 * 3 + 1],
        pos[i1 * 3 + 2],
        pos[i2 * 3],
        pos[i2 * 3 + 1],
        pos[i2 * 3 + 2]
      ) || [0, 1, 0];
    for (const vi of [i0, i1, i2]) {
      if (written[vi]) {
        continue;
      }
      const [block, sky, ao] = sampleFaceVertex(
        field,
        pos[vi * 3],
        pos[vi * 3 + 1],
        pos[vi * 3 + 2],
        normal
      );
      const uv = encodeLight(block, sky);
      light[vi * 2] = uv[0];
      light[vi * 2 + 1] = uv[1];
      colors[vi * 3] *= ao;
      colors[vi * 3 + 1] *= ao;
      colors[vi * 3 + 2] *= ao;
      written[vi] = 1;
    }
  }
  for (let vi = 0; vi < verts; vi += 1) {
    if (written[vi]) {
      continue;
    }
    const [block, sky, ao] = sampleFaceVertex(
      field,
      pos[vi * 3],
      pos[vi * 3 + 1],
      pos[vi * 3 + 2],
      [0, 1, 0]
    );
    const uv = encodeLight(block, sky);
    light[vi * 2] = uv[0];
    light[vi * 2 + 1] = uv[1];
    colors[vi * 3] *= ao;
    colors[vi * 3 + 1] *= ao;
    colors[vi * 3 + 2] *= ao;
  }
  mesh.colors = colors;
  mesh.light = light;
  return mesh;
}

export function applyLight(bake, field) {
  stamp(bake.opaque, field);
  stamp(bake.translucent, field);
  return bake;
}
