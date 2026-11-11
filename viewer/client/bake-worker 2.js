import { bakeWorld } from "./bake.js";
import { openWorldFile } from "./world.js";

let world = null;

function progress(message) {
  self.postMessage({ type: "progress", message });
}

self.onmessage = async (event) => {
  const data = event.data || {};
  try {
    if (data.type === "open") {
      world = await openWorldFile(data.file, progress);
      self.postMessage({
        type: "ready",
        name: world.name,
        spawn: world.spawn,
      });
      return;
    }
    if (data.type === "bake") {
      if (!world) {
        throw new Error("pick a .mcworld first");
      }
      const payload = await bakeWorld(world.db, data, progress);
      const atlasBuffer = await payload.atlas.arrayBuffer();
      self.postMessage(
        {
          type: "done",
          scene: payload.scene,
          opaque: payload.opaque,
          translucent: payload.translucent,
          atlas: atlasBuffer,
        },
        [payload.opaque, payload.translucent, atlasBuffer]
      );
      return;
    }
    throw new Error(`unknown worker message ${data.type}`);
  } catch (error) {
    self.postMessage({
      type: "error",
      message: String(error && error.message ? error.message : error),
    });
  }
};
