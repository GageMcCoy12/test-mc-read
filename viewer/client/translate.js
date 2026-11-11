import { blockKey } from "./subchunk.js";

let tables = null;

export async function loadTranslateTables() {
  if (tables) {
    return tables;
  }
  const url = new URL("./data/bedrock-to-java.json", import.meta.url);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error("missing client translation tables — run tools/export_client_tables.py");
  }
  tables = await response.json();
  return tables;
}

export function parseBlockstate(key) {
  if (!key) {
    return { namespace: "minecraft", baseName: "air", namespaced: "minecraft:air", properties: {} };
  }
  const bracket = key.indexOf("[");
  const namespaced = bracket === -1 ? key : key.slice(0, bracket);
  const [namespace, ...rest] = namespaced.split(":");
  const baseName = rest.join(":") || namespaced;
  const properties = {};
  if (bracket !== -1 && key.endsWith("]")) {
    const inner = key.slice(bracket + 1, -1);
    if (inner) {
      for (const part of inner.split(",")) {
        const eq = part.indexOf("=");
        if (eq === -1) {
          continue;
        }
        properties[part.slice(0, eq)] = part.slice(eq + 1);
      }
    }
  }
  return {
    namespace: namespace || "minecraft",
    baseName,
    namespaced,
    properties,
  };
}

export function translateStack(stack) {
  return stack.map((block) => translateBlock(block));
}

export function translateBlock(block) {
  const key = blockKey(block);
  const row = tables?.map?.[key] || tables?.by_name?.[block.namespaced];
  if (!row) {
    return {
      ...parseBlockstate(block.namespaced),
      extraNeeded: true,
      passedThrough: true,
    };
  }
  const parsed = parseBlockstate(row.java);
  parsed.extraNeeded = Boolean(row.extra_needed);
  parsed.passedThrough = false;
  return parsed;
}
