/** Little-endian NBT used by Bedrock palettes and level.dat. */

const TAG_END = 0;
const TAG_BYTE = 1;
const TAG_SHORT = 2;
const TAG_INT = 3;
const TAG_LONG = 4;
const TAG_FLOAT = 5;
const TAG_DOUBLE = 6;
const TAG_BYTE_ARRAY = 7;
const TAG_STRING = 8;
const TAG_LIST = 9;
const TAG_COMPOUND = 10;
const TAG_INT_ARRAY = 11;
const TAG_LONG_ARRAY = 12;

const decoder = new TextDecoder("utf-8");

export class NbtReader {
  constructor(bytes, offset = 0) {
    this.bytes = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    this.view = new DataView(this.bytes.buffer, this.bytes.byteOffset, this.bytes.byteLength);
    this.offset = offset;
  }

  remaining() {
    return this.bytes.length - this.offset;
  }

  u8() {
    return this.view.getUint8(this.offset++);
  }

  i8() {
    const value = this.view.getInt8(this.offset);
    this.offset += 1;
    return value;
  }

  i16() {
    const value = this.view.getInt16(this.offset, true);
    this.offset += 2;
    return value;
  }

  u16() {
    const value = this.view.getUint16(this.offset, true);
    this.offset += 2;
    return value;
  }

  i32() {
    const value = this.view.getInt32(this.offset, true);
    this.offset += 4;
    return value;
  }

  i64() {
    const value = this.view.getBigInt64(this.offset, true);
    this.offset += 8;
    return value;
  }

  f32() {
    const value = this.view.getFloat32(this.offset, true);
    this.offset += 4;
    return value;
  }

  f64() {
    const value = this.view.getFloat64(this.offset, true);
    this.offset += 8;
    return value;
  }

  string() {
    const length = this.u16();
    const slice = this.bytes.subarray(this.offset, this.offset + length);
    this.offset += length;
    return decoder.decode(slice);
  }

  payload(type) {
    switch (type) {
      case TAG_BYTE:
        return this.i8();
      case TAG_SHORT:
        return this.i16();
      case TAG_INT:
        return this.i32();
      case TAG_LONG:
        return this.i64();
      case TAG_FLOAT:
        return this.f32();
      case TAG_DOUBLE:
        return this.f64();
      case TAG_BYTE_ARRAY: {
        const n = this.i32();
        const value = this.bytes.subarray(this.offset, this.offset + n);
        this.offset += n;
        return value;
      }
      case TAG_STRING:
        return this.string();
      case TAG_LIST:
        return this.list();
      case TAG_COMPOUND:
        return this.compound();
      case TAG_INT_ARRAY: {
        const n = this.i32();
        const out = new Int32Array(n);
        for (let i = 0; i < n; i += 1) {
          out[i] = this.i32();
        }
        return out;
      }
      case TAG_LONG_ARRAY: {
        const n = this.i32();
        const out = new BigInt64Array(n);
        for (let i = 0; i < n; i += 1) {
          out[i] = this.i64();
        }
        return out;
      }
      default:
        throw new Error(`unknown nbt tag ${type}`);
    }
  }

  list() {
    const type = this.u8();
    const count = this.i32();
    const items = [];
    for (let i = 0; i < count; i += 1) {
      items.push(this.payload(type));
    }
    return items;
  }

  compound() {
    const out = {};
    while (this.remaining() > 0) {
      const type = this.u8();
      if (type === TAG_END) {
        break;
      }
      const name = this.string();
      out[name] = this.payload(type);
    }
    return out;
  }

  named() {
    const type = this.u8();
    const name = this.string();
    return { name, value: this.payload(type) };
  }
}

export function readUnnamedCompound(bytes, offset = 0) {
  const reader = new NbtReader(bytes, offset);
  const value = reader.compound();
  return { value, offset: reader.offset };
}

export function readNamed(bytes, offset = 0) {
  const reader = new NbtReader(bytes, offset);
  const tag = reader.named();
  return { ...tag, offset: reader.offset };
}

export function readLevelDat(bytes) {
  const raw = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  // Bedrock level.dat: 8-byte header then uncompressed little-endian NBT.
  const body = raw.length > 8 ? raw.subarray(8) : raw;
  try {
    return readNamed(body).value;
  } catch {
    return readUnnamedCompound(body).value;
  }
}

export function nbtValue(value) {
  if (value == null) {
    return "";
  }
  if (typeof value === "bigint") {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? "1" : "0";
  }
  return String(value);
}
