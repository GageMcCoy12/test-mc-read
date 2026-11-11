import { loadBlockstate, loadModel, splitId } from "./pack.js";

export const FACE_KEYS = ["down", "up", "north", "east", "south", "west", "none"];
export const CULL_OFFSETS = {
  down: [0, -1, 0],
  up: [0, 1, 0],
  north: [0, 0, -1],
  south: [0, 0, 1],
  west: [-1, 0, 0],
  east: [1, 0, 0],
};

export const Transparency = {
  FullOpaque: 0,
  FullTranslucent: 1,
  Partial: 2,
};

const CUBE_FACE_LUT = {
  down: [0, 4, 5, 1],
  up: [3, 7, 6, 2],
  north: [4, 0, 2, 6],
  east: [5, 4, 6, 7],
  south: [1, 5, 7, 3],
  west: [0, 1, 3, 2],
};

const UV_ROTATION_LUT = [0, 3, 2, 3, 2, 1, 0, 1];
const TRI_FACE = [0, 1, 2, 0, 2, 3];

const GRASS = [0x92 / 255, 0xbc / 255, 0x58 / 255];
const FOLIAGE = [0x77 / 255, 0xab / 255, 0x2f / 255];
const BLOCK_TINTS = {
  "minecraft:grass_block": GRASS,
  "minecraft:short_grass": GRASS,
  "minecraft:tall_grass": GRASS,
  "minecraft:fern": GRASS,
  "minecraft:large_fern": GRASS,
  "minecraft:oak_leaves": FOLIAGE,
  "minecraft:jungle_leaves": FOLIAGE,
  "minecraft:acacia_leaves": FOLIAGE,
  "minecraft:dark_oak_leaves": FOLIAGE,
  "minecraft:mangrove_leaves": FOLIAGE,
  "minecraft:vine": FOLIAGE,
  "minecraft:sugar_cane": GRASS,
  "minecraft:lily_pad": [0x20 / 255, 0x80 / 255, 0x30 / 255],
  "minecraft:water_cauldron": [0x3f / 255, 0x76 / 255, 0xe4 / 255],
  "minecraft:birch_leaves": [0x80 / 255, 0xa7 / 255, 0x55 / 255],
  "minecraft:spruce_leaves": [0x61 / 255, 0x99 / 255, 0x61 / 255],
};

function emptyBuckets() {
  const buckets = {};
  for (const key of FACE_KEYS) {
    buckets[key] = { verts: [], uvs: [], tints: [], faces: [], texIndex: [], count: 0 };
  }
  return buckets;
}

function rotate3d(verts, rx, ry, rz, dx, dy, dz) {
  const toRad = Math.PI / 180;
  const sx = Math.sin(rx * toRad);
  const sy = Math.sin(ry * toRad);
  const sz = Math.sin(rz * toRad);
  const cx = Math.cos(rx * toRad);
  const cy = Math.cos(ry * toRad);
  const cz = Math.cos(rz * toRad);
  const m00 = cz * cy;
  const m01 = sz * cy;
  const m02 = -sy;
  const m10 = cz * sy * sx - sz * cx;
  const m11 = sz * sy * sx + cz * cx;
  const m12 = cy * sx;
  const m20 = cz * sy * cx + sz * sx;
  const m21 = sz * sy * cx - cz * sx;
  const m22 = cy * cx;
  const out = new Float32Array(verts.length);
  for (let i = 0; i < verts.length; i += 3) {
    const x = verts[i] - dx;
    const y = verts[i + 1] - dy;
    const z = verts[i + 2] - dz;
    out[i] = x * m00 + y * m10 + z * m20 + dx;
    out[i + 1] = x * m01 + y * m11 + z * m21 + dy;
    out[i + 2] = x * m02 + y * m12 + z * m22 + dz;
  }
  return out;
}

function boxCorners(from, to) {
  const minx = Math.min(from[0], to[0]) / 16;
  const miny = Math.min(from[1], to[1]) / 16;
  const minz = Math.min(from[2], to[2]) / 16;
  const maxx = Math.max(from[0], to[0]) / 16;
  const maxy = Math.max(from[1], to[1]) / 16;
  const maxz = Math.max(from[2], to[2]) / 16;
  return [
    [minx, miny, minz],
    [minx, miny, maxz],
    [minx, maxy, minz],
    [minx, maxy, maxz],
    [maxx, miny, minz],
    [maxx, miny, maxz],
    [maxx, maxy, minz],
    [maxx, maxy, maxz],
  ];
}

function defaultUv(faceDir, from, to) {
  if (faceDir === "up" || faceDir === "down") {
    return [from[0] / 16, from[2] / 16, to[0] / 16, to[2] / 16];
  }
  if (faceDir === "west" || faceDir === "east") {
    return [from[2] / 16, (16 - to[1]) / 16, to[2] / 16, (16 - from[1]) / 16];
  }
  return [from[0] / 16, (16 - to[1]) / 16, to[0] / 16, (16 - from[1]) / 16];
}

function resolveTexture(textures, key) {
  let current = key;
  const seen = new Set();
  while (typeof current === "string") {
    if (current.startsWith("#")) {
      current = current.slice(1);
    }
    if (seen.has(current)) {
      break;
    }
    seen.add(current);
    const next = textures[current];
    if (next == null) {
      return current;
    }
    if (typeof next !== "string") {
      return next.sprite || current;
    }
    current = next;
  }
  return current;
}

function finishMesh(buckets, textures, transparency) {
  const verts = {};
  const uvs = {};
  const tints = {};
  const faces = {};
  const textureIndex = {};
  for (const key of FACE_KEYS) {
    const bucket = buckets[key];
    if (!bucket.verts.length) {
      continue;
    }
    verts[key] = Float32Array.from(bucket.verts);
    uvs[key] = Float32Array.from(bucket.uvs);
    tints[key] = Float32Array.from(bucket.tints);
    faces[key] = Uint32Array.from(bucket.faces);
    textureIndex[key] = Uint32Array.from(bucket.texIndex);
  }
  return {
    verts,
    uvs,
    tints,
    faces,
    textureIndex,
    textures,
    transparency,
  };
}

function mergeModels(models) {
  const nonempty = models.filter((model) => model && Object.keys(model.verts || {}).length);
  if (!nonempty.length) {
    return null;
  }
  if (nonempty.length === 1) {
    return nonempty[0];
  }
  const textures = [];
  const texMap = new Map();
  const buckets = emptyBuckets();
  let transparency = Transparency.Partial;
  let sawOpaque = false;
  let sawTranslucent = false;
  for (const model of nonempty) {
    if (model.transparency === Transparency.FullOpaque) {
      sawOpaque = true;
    } else if (model.transparency === Transparency.FullTranslucent) {
      sawTranslucent = true;
    }
    const remap = model.textures.map((path) => {
      let index = texMap.get(path);
      if (index == null) {
        index = textures.length;
        texMap.set(path, index);
        textures.push(path);
      }
      return index;
    });
    for (const key of FACE_KEYS) {
      if (!model.verts[key]) {
        continue;
      }
      const bucket = buckets[key];
      const vertOffset = bucket.count;
      for (const value of model.verts[key]) {
        bucket.verts.push(value);
      }
      for (const value of model.uvs[key]) {
        bucket.uvs.push(value);
      }
      for (const value of model.tints[key]) {
        bucket.tints.push(value);
      }
      for (const value of model.faces[key]) {
        bucket.faces.push(value + vertOffset);
      }
      for (const value of model.textureIndex[key]) {
        bucket.texIndex.push(remap[value] ?? 0);
      }
      bucket.count += model.verts[key].length / 3;
    }
  }
  if (sawOpaque && nonempty.length === 1) {
    transparency = Transparency.FullOpaque;
  } else if (sawTranslucent && !sawOpaque) {
    transparency = Transparency.FullTranslucent;
  }
  return finishMesh(buckets, textures, transparency);
}

function rotateMesh(mesh, rotx, roty) {
  if (!rotx && !roty) {
    return mesh;
  }
  const rotyMap = ["north", "east", "south", "west"];
  const rotatedY = rotyMap.slice(((roty % 4) + 4) % 4).concat(rotyMap.slice(0, ((roty % 4) + 4) % 4));
  const yRemap = Object.fromEntries(rotyMap.map((name, i) => [name, rotatedY[i]]));
  const rx = ((rotx % 4) + 4) % 4;
  const north = yRemap.north;
  const south = yRemap.south;
  const xCycle = [north, "down", south, "up"];
  const rotatedX = xCycle.slice(rx).concat(xCycle.slice(0, rx));
  const xRemap = Object.fromEntries(xCycle.map((name, i) => [name, rotatedX[i]]));
  const remapDir = (dir) => {
    if (!dir || dir === "none") {
      return "none";
    }
    return xRemap[yRemap[dir] || dir] || yRemap[dir] || dir;
  };
  const verts = {};
  const uvs = {};
  const tints = {};
  const faces = {};
  const textureIndex = {};
  for (const key of Object.keys(mesh.verts)) {
    const destKey = remapDir(key);
    verts[destKey] = rotate3d(
      rotate3d(mesh.verts[key], -rotx * 90, 0, 0, 0.5, 0.5, 0.5),
      0,
      -roty * 90,
      0,
      0.5,
      0.5,
      0.5
    );
    uvs[destKey] = mesh.uvs[key];
    tints[destKey] = mesh.tints[key];
    faces[destKey] = mesh.faces[key];
    textureIndex[destKey] = mesh.textureIndex[key];
  }
  return {
    verts,
    uvs,
    tints,
    faces,
    textureIndex,
    textures: mesh.textures,
    transparency: mesh.transparency,
  };
}

async function flattenModel(identifier, depth = 0) {
  if (!identifier || depth > 20) {
    return { textures: {}, elements: [] };
  }
  const json = await loadModel(identifier);
  if (!json) {
    return { textures: {}, elements: [] };
  }
  const parent = json.parent ? await flattenModel(json.parent, depth + 1) : { textures: {}, elements: [] };
  return {
    textures: { ...parent.textures, ...(json.textures || {}) },
    elements: json.elements || parent.elements || [],
  };
}

async function bakeElements(javaModel, tint) {
  const textures = [];
  const textureDict = new Map();
  const buckets = emptyBuckets();
  let transparency = Transparency.Partial;
  const elements = javaModel.elements || [];
  if (Object.keys(javaModel.textures || {}).some((key) => key !== "particle") && !elements.length) {
    return null;
  }

  for (const element of elements) {
    const from = element.from || [0, 0, 0];
    const to = element.to || [16, 16, 16];
    const corners = boxCorners(from, to);
    const faces = element.faces || {};
    const rotation = element.rotation;
    let rotationParams = null;
    if (rotation) {
      const origin = rotation.origin || [8, 8, 8];
      rotationParams = {
        x: rotation.axis === "x" ? rotation.angle || 0 : rotation.x || 0,
        y: rotation.axis === "y" ? rotation.angle || 0 : rotation.y || 0,
        z: rotation.axis === "z" ? rotation.angle || 0 : rotation.z || 0,
        ox: origin[0] / 16,
        oy: origin[1] / 16,
        oz: origin[2] / 16,
      };
    }
    const fullCube =
      !rotation &&
      from[0] === 0 &&
      from[1] === 0 &&
      from[2] === 0 &&
      to[0] === 16 &&
      to[1] === 16 &&
      to[2] === 16 &&
      Object.keys(faces).length >= 6;
    let opaqueFaces = 0;

    for (const [faceDir, face] of Object.entries(faces)) {
      if (!CUBE_FACE_LUT[faceDir]) {
        continue;
      }
      const cullDir = FACE_KEYS.includes(face.cullface) ? face.cullface : "none";
      let textureId = resolveTexture(javaModel.textures || {}, face.texture);
      if (typeof textureId !== "string") {
        continue;
      }
      const [namespace, relative] = splitId(textureId);
      const path = `${namespace}:${relative}`;
      if (!textureDict.has(path)) {
        textureDict.set(path, textures.length);
        textures.push(path);
      }
      const textureIndex = textureDict.get(path);
      const uv = Array.isArray(face.uv) ? face.uv.map((v) => v / 16) : defaultUv(faceDir, from, to);
      const rotationSteps = Math.floor((face.rotation || 0) / 90);
      const uvSlice = UV_ROTATION_LUT.slice(2 * rotationSteps).concat(UV_ROTATION_LUT.slice(0, 2 * rotationSteps));
      let faceVerts = [];
      for (const corner of CUBE_FACE_LUT[faceDir]) {
        faceVerts.push(corners[corner][0], corners[corner][1], corners[corner][2]);
      }
      if (rotationParams) {
        faceVerts = Array.from(
          rotate3d(
            Float32Array.from(faceVerts),
            rotationParams.x,
            rotationParams.y,
            rotationParams.z,
            rotationParams.ox,
            rotationParams.oy,
            rotationParams.oz
          )
        );
      }
      const bucket = buckets[cullDir];
      const vertOffset = bucket.count;
      bucket.verts.push(...faceVerts);
      for (let i = 0; i < 4; i += 1) {
        bucket.uvs.push(uv[uvSlice[i * 2]], uv[uvSlice[i * 2 + 1]]);
        if ("tintindex" in face) {
          bucket.tints.push(tint[0], tint[1], tint[2]);
        } else {
          bucket.tints.push(1, 1, 1);
        }
      }
      for (const index of TRI_FACE) {
        bucket.faces.push(index + vertOffset);
      }
      bucket.texIndex.push(textureIndex, textureIndex);
      bucket.count += 4;
      if (fullCube) {
        opaqueFaces += 1;
      }
    }
    if (fullCube && opaqueFaces === 6) {
      transparency = Transparency.FullOpaque;
    } else if (fullCube) {
      transparency = Transparency.FullTranslucent;
    }
  }
  if (!textures.length) {
    return null;
  }
  return finishMesh(buckets, textures, transparency);
}

function parseWhenValue(value) {
  if (typeof value === "boolean") {
    return [value ? "true" : "false"];
  }
  if (typeof value === "string") {
    return value.split("|");
  }
  return [String(value)];
}

function propertiesMatch(blockProps, when) {
  for (const [name, raw] of Object.entries(when)) {
    if (name === "OR" || name === "AND") {
      continue;
    }
    const have = blockProps[name];
    if (have == null || !parseWhenValue(raw).includes(String(have))) {
      return false;
    }
  }
  return true;
}

function multipartMatches(block, when) {
  if (!when) {
    return true;
  }
  if (when.OR) {
    return when.OR.some((entry) => propertiesMatch(block.properties, entry));
  }
  if (when.AND) {
    return when.AND.every((entry) => propertiesMatch(block.properties, entry));
  }
  return propertiesMatch(block.properties, when);
}

function variantMatches(block, variantKey) {
  if (variantKey === "") {
    return true;
  }
  for (const part of variantKey.split(",")) {
    const eq = part.indexOf("=");
    if (eq === -1) {
      continue;
    }
    const name = part.slice(0, eq);
    const value = part.slice(eq + 1);
    const have = block.properties[name];
    if (have == null) {
      continue;
    }
    if (String(have) !== value) {
      return false;
    }
  }
  return true;
}

async function loadVariant(value, tint) {
  const entry = Array.isArray(value) ? value[0] : value;
  if (!entry?.model) {
    return null;
  }
  const flat = await flattenModel(entry.model);
  const mesh = await bakeElements(flat, tint);
  if (!mesh) {
    return null;
  }
  const rotx = Math.floor((entry.x || 0) / 90);
  const roty = Math.floor((entry.y || 0) / 90);
  return rotateMesh(mesh, rotx, roty);
}

function tintFor(block) {
  if (block.namespaced === "minecraft:redstone_wire") {
    const power = Number(block.properties.power || 0);
    const t = power / 15;
    return [0.3 + 0.7 * t, 0, 0];
  }
  return BLOCK_TINTS[block.namespaced] || [1, 1, 1];
}

const meshCache = new Map();

export async function meshForJava(block) {
  const key = `${block.namespaced}[${Object.entries(block.properties)
    .sort()
    .map(([k, v]) => `${k}=${v}`)
    .join(",")}]`;
  if (meshCache.has(key)) {
    return meshCache.get(key);
  }
  const pending = (async () => {
    const blockstate = await loadBlockstate(block.namespace, block.baseName);
    const tint = tintFor(block);
    if (!blockstate) {
      return null;
    }
    if (blockstate.variants) {
      let fallback = null;
      for (const [variant, value] of Object.entries(blockstate.variants)) {
        if (variant === "") {
          fallback = value;
        }
        if (variantMatches(block, variant)) {
          return loadVariant(value, tint);
        }
      }
      if (fallback) {
        return loadVariant(fallback, tint);
      }
    }
    if (blockstate.multipart) {
      const parts = [];
      for (const entry of blockstate.multipart) {
        if (!multipartMatches(block, entry.when)) {
          continue;
        }
        if (entry.apply) {
          const mesh = await loadVariant(entry.apply, tint);
          if (mesh) {
            parts.push(mesh);
          }
        }
      }
      return mergeModels(parts);
    }
    return null;
  })();
  meshCache.set(key, pending);
  return pending;
}

export async function unitCube(texture, transparency, tint = [1, 1, 1]) {
  const javaModel = {
    textures: {
      down: texture,
      up: texture,
      north: texture,
      south: texture,
      west: texture,
      east: texture,
    },
    elements: [
      {
        from: [0, 0, 0],
        to: [16, 16, 16],
        faces: {
          down: { texture: "#down", cullface: "down", tintindex: 0 },
          up: { texture: "#up", cullface: "up", tintindex: 0 },
          north: { texture: "#north", cullface: "north", tintindex: 0 },
          south: { texture: "#south", cullface: "south", tintindex: 0 },
          west: { texture: "#west", cullface: "west", tintindex: 0 },
          east: { texture: "#east", cullface: "east", tintindex: 0 },
        },
      },
    ],
  };
  const mesh = await bakeElements(javaModel, tint);
  if (mesh) {
    mesh.transparency = transparency;
  }
  return mesh;
}

export { mergeModels };
