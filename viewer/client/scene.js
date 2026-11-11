const TRAPDOOR_LANDMARK = [296, 80, 76];

function passInfo(mesh, filename) {
  const vertexCount = mesh.positions.length / 3;
  const indexCount = mesh.indices.length;
  return {
    file: filename,
    vertex_count: vertexCount,
    index_count: indexCount,
    triangle_count: Math.floor(indexCount / 3),
  };
}

export function encodeMesh(mesh) {
  const verts = mesh.positions.length / 3;
  const positions = mesh.positions;
  const uvs = mesh.uvs;
  const colors = mesh.colors;
  const emit = mesh.emit.length === verts * 3 ? mesh.emit : new Float32Array(verts * 3);
  const light = mesh.light.length === verts * 2 ? mesh.light : new Float32Array(verts * 2);
  const indices = mesh.indices;
  const buffer = new ArrayBuffer(
    verts * 3 * 4 + verts * 2 * 4 + verts * 3 * 4 + verts * 3 * 4 + verts * 2 * 4 + indices.length * 4
  );
  const bytes = new Uint8Array(buffer);
  let offset = 0;
  const write = (array) => {
    bytes.set(new Uint8Array(array.buffer, array.byteOffset, array.byteLength), offset);
    offset += array.byteLength;
  };
  write(positions);
  write(uvs);
  write(colors);
  write(emit);
  write(light);
  write(indices);
  return buffer;
}

export function cameraTargetFor(bake, blockX, blockZ) {
  const [lx, ly, lz] = TRAPDOOR_LANDMARK;
  if (Math.abs(blockX - lx) <= 16 && Math.abs(blockZ - lz) <= 16 && bake.yRange[0] <= ly && ly <= bake.yRange[1]) {
    return TRAPDOOR_LANDMARK;
  }
  let lookY = 80;
  if (lookY < bake.yRange[0]) {
    lookY = bake.yRange[0] + 8;
  }
  if (lookY > bake.yRange[1]) {
    lookY = bake.yRange[1];
  }
  return [blockX, lookY, blockZ];
}

export function buildScenePayload(bake, atlas, view, blockX, blockZ) {
  const cameraTarget = cameraTargetFor(bake, blockX, blockZ);
  return {
    scene: {
      chunk: bake.chunk,
      origin: bake.origin,
      y_range: bake.yRange,
      camera_target: cameraTarget,
      view: view || {},
      attributes: ["position", "uv", "color", "emit", "light"],
      opaque: passInfo(bake.opaque, "opaque.bin"),
      translucent: passInfo(bake.translucent, "translucent.bin"),
      atlas: {
        file: "atlas.png",
        width: atlas.width,
        height: atlas.height,
        tile: atlas.tileSize,
        padding: atlas.padding,
      },
    },
    opaque: encodeMesh(bake.opaque),
    translucent: encodeMesh(bake.translucent),
    atlas: atlas.blob,
  };
}
