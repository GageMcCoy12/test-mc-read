import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const placeForm = document.getElementById("place");
const statusEl = document.getElementById("status");
const rebakeBtn = document.getElementById("rebake");
const inputX = document.getElementById("center-x");
const inputZ = document.getElementById("center-z");
const inputRadius = document.getElementById("radius");
const inputMinY = document.getElementById("min-y");
const resetBtn = document.getElementById("reset-orbit");
const dock = document.getElementById("dock");
const menuBtn = document.getElementById("menu");
const lightingNowBtn = document.getElementById("lighting-now");
const lightingNextBtn = document.getElementById("lighting-next");
const brightnessInput = document.getElementById("brightness");
const brightnessValue = document.getElementById("brightness-value");

let lightingMode = "now";

const LIGHTMAP_SIZE = 16;
const lightmapPixels = new Uint8Array(LIGHTMAP_SIZE * LIGHTMAP_SIZE * 4);

function setLightingMode(mode) {
  lightingMode = mode === "next" ? "next" : "now";
  lightingNowBtn.setAttribute("aria-pressed", lightingMode === "now" ? "true" : "false");
  lightingNextBtn.setAttribute("aria-pressed", lightingMode === "next" ? "true" : "false");
  applyTerrainLighting();
  schedulePersist();
}

function setBrightness(value) {
  clock.brightness = THREE.MathUtils.clamp(value, 0, 1);
  const pct = Math.round(clock.brightness * 100);
  brightnessInput.value = String(pct);
  brightnessValue.textContent = `${pct}%`;
  if (lightingMode === "next") {
    writeLightmap();
  }
  schedulePersist();
}

const DAY_SECONDS = 48;

const clock = {
  time: 0.5,
  playing: false,
  speed: 1 / DAY_SECONDS,
  fog: 1,
  brightness: 0.5,
};

const PREFS_KEY = "mcread-viewer";
const PREFS_SAVE_MS = 250;
let persistEnabled = false;
let persistTimer = 0;

function readPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (!raw) {
      return null;
    }
    const data = JSON.parse(raw);
    return data && typeof data === "object" ? data : null;
  } catch {
    return null;
  }
}

function finite3(value) {
  return (
    value &&
    Number.isFinite(value.x) &&
    Number.isFinite(value.y) &&
    Number.isFinite(value.z)
  );
}

function collectPrefs() {
  const prefs = {
    time: clock.time,
    playing: clock.playing,
    lightingMode,
    brightness: clock.brightness,
  };
  if (world.camera) {
    prefs.camera = {
      x: world.camera.position.x,
      y: world.camera.position.y,
      z: world.camera.position.z,
    };
  }
  if (world.controls) {
    prefs.target = {
      x: world.controls.target.x,
      y: world.controls.target.y,
      z: world.controls.target.z,
    };
  }
  return prefs;
}

function writePrefs(prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // private mode / quota
  }
}

function flushPrefs() {
  if (persistTimer) {
    clearTimeout(persistTimer);
    persistTimer = 0;
  }
  if (!persistEnabled) {
    return;
  }
  writePrefs(collectPrefs());
}

function schedulePersist() {
  if (!persistEnabled || persistTimer) {
    return;
  }
  persistTimer = setTimeout(() => {
    persistTimer = 0;
    writePrefs(collectPrefs());
  }, PREFS_SAVE_MS);
}

function applySavedPrefs(prefs) {
  if (!prefs) {
    return;
  }
  if (Number.isFinite(prefs.time)) {
    setTime(prefs.time);
  }
  if (typeof prefs.playing === "boolean") {
    setPlaying(prefs.playing);
  }
  if (prefs.lightingMode === "now" || prefs.lightingMode === "next") {
    setLightingMode(prefs.lightingMode);
  }
  if (Number.isFinite(prefs.brightness)) {
    setBrightness(prefs.brightness);
  }
}

function restoreCamera(prefs) {
  if (!prefs || !world.camera || !world.controls || !finite3(prefs.camera)) {
    return false;
  }
  world.camera.position.set(prefs.camera.x, prefs.camera.y, prefs.camera.z);
  if (finite3(prefs.target)) {
    world.controls.target.set(prefs.target.x, prefs.target.y, prefs.target.z);
  }
  world.camera.lookAt(world.controls.target);
  world.camera.updateMatrixWorld();
  world.controls.update();
  return true;
}

const WALK_SPEED = 24;
const walkKeys = new Set();
const walkForward = new THREE.Vector3();
const walkRight = new THREE.Vector3();
const walkMove = new THREE.Vector3();

const world = {
  renderer: null,
  scene: null,
  camera: null,
  controls: null,
  ambient: null,
  hemi: null,
  sun: null,
  fill: null,
  sky: null,
  sunBody: null,
  moonBody: null,
  fog: null,
  sceneInfo: null,
  meshes: [],
  texture: null,
  lightmap: null,
};

const MOON_ORBIT = 40;
const CELESTIAL_SIZE = 120;
const CELESTIAL_DISTANCE = 1600;
const SUN_BODY_COLOR = "#ffe8a0";
const MOON_BODY_COLOR = "#dce8ff";

const orrery = {
  root: null,
  moon: null,
  dragging: false,
};

const SKY_VERT = /* glsl */ `
varying vec3 vWorldDir;
void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vWorldDir = world.xyz - cameraPosition;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const SKY_FRAG = /* glsl */ `
varying vec3 vWorldDir;
uniform vec3 uZenith;
uniform vec3 uHorizon;
uniform vec3 uGround;
uniform float uStars;

float hash13(vec3 p) {
  p = fract(p * vec3(443.897, 397.297, 491.187));
  p += dot(p, p.yxz + 19.19);
  return fract((p.x + p.y) * p.z);
}

void main() {
  vec3 dir = normalize(vWorldDir);
  float h = dir.y;

  float groundT = smoothstep(-0.28, 0.04, h);
  float skyT = smoothstep(0.0, 0.72, h);
  vec3 col = mix(uGround, uHorizon, groundT);
  col = mix(col, uZenith, skyT);

  float band = exp(-h * h * 32.0);
  col += uHorizon * band * 0.22;

  if (uStars > 0.01 && h > 0.02) {
    float n = hash13(floor(dir * 88.0));
    float star = step(0.93, n) * smoothstep(0.93, 1.0, n);
    col += vec3(0.82, 0.88, 1.0) * star * uStars;
  }

  gl_FragColor = vec4(col, 1.0);
}
`;

function hex(color) {
  return new THREE.Color(color);
}

const STOPS = [
  {
    t: 0,
    name: "night",
    zenith: "#070b16",
    horizon: "#141c38",
    ground: "#08090e",
    sun: "#ffd0a0",
    moon: "#b8c6e8",
    hemiSky: "#4a5a86",
    hemiGround: "#3a3644",
    fill: "#5a6a98",
    ambient: "#7a88aa",
    paper: "#e8eaf0",
    edge: "#c8ccd6",
    accent: "#8a96b0",
    sunI: 0.06,
    moonI: 0.42,
    hemiI: 0.48,
    fillI: 0.22,
    ambientI: 0.28,
    fogD: 0.0036,
    exposure: 1.02,
    stars: 1,
  },
  {
    t: 0.2,
    name: "dawn",
    zenith: "#5a7aa8",
    horizon: "#f2b07a",
    ground: "#3d2e2c",
    sun: "#ffc090",
    moon: "#c8d4f0",
    hemiSky: "#c4b8a8",
    hemiGround: "#8a6a58",
    fill: "#8aa4c4",
    ambient: "#d4c4b0",
    paper: "#f3eadc",
    edge: "#d8cbb6",
    accent: "#c4a06a",
    sunI: 0.85,
    moonI: 0.05,
    hemiI: 0.55,
    fillI: 0.28,
    ambientI: 0.3,
    fogD: 0.0052,
    exposure: 1.1,
    stars: 0.12,
  },
  {
    t: 0.32,
    name: "morning",
    zenith: "#6aa0d0",
    horizon: "#c5d8ea",
    ground: "#6e7a82",
    sun: "#ffe2b8",
    moon: "#c8d4f0",
    hemiSky: "#c8d8e8",
    hemiGround: "#8a7a64",
    fill: "#98b4cc",
    ambient: "#e8e4dc",
    paper: "#f4efe4",
    edge: "#d4cbb8",
    accent: "#c4a06a",
    sunI: 1.05,
    moonI: 0,
    hemiI: 0.62,
    fillI: 0.3,
    ambientI: 0.32,
    fogD: 0.0058,
    exposure: 1.14,
    stars: 0,
  },
  {
    t: 0.5,
    name: "noon",
    zenith: "#5ea4d8",
    horizon: "#b4d0e4",
    ground: "#7a8a8c",
    sun: "#ffe8b8",
    moon: "#c8d4f0",
    hemiSky: "#c4daf0",
    hemiGround: "#9a8a6e",
    fill: "#9ab4cc",
    ambient: "#f0ece4",
    paper: "#f4efe4",
    edge: "#d4cbb8",
    accent: "#c4a06a",
    sunI: 1.2,
    moonI: 0,
    hemiI: 0.65,
    fillI: 0.32,
    ambientI: 0.34,
    fogD: 0.0056,
    exposure: 1.16,
    stars: 0,
  },
  {
    t: 0.68,
    name: "golden hour",
    zenith: "#3d5478",
    horizon: "#f0a060",
    ground: "#4a3020",
    sun: "#ff9a48",
    moon: "#c8d4f0",
    hemiSky: "#e0a878",
    hemiGround: "#8a6040",
    fill: "#7a88b0",
    ambient: "#e8c8a0",
    paper: "#f6ead4",
    edge: "#dcc6a8",
    accent: "#c48448",
    sunI: 1.0,
    moonI: 0.04,
    hemiI: 0.55,
    fillI: 0.26,
    ambientI: 0.3,
    fogD: 0.0052,
    exposure: 1.1,
    stars: 0.05,
  },
  {
    t: 0.78,
    name: "dusk",
    zenith: "#2a3868",
    horizon: "#e06038",
    ground: "#2e1c18",
    sun: "#ff6a30",
    moon: "#c8d4f0",
    hemiSky: "#c07060",
    hemiGround: "#6a4038",
    fill: "#5a6a98",
    ambient: "#c09078",
    paper: "#f3e2d4",
    edge: "#d8b8a4",
    accent: "#c46a40",
    sunI: 0.7,
    moonI: 0.1,
    hemiI: 0.48,
    fillI: 0.22,
    ambientI: 0.28,
    fogD: 0.0046,
    exposure: 1.06,
    stars: 0.4,
  },
  {
    t: 0.9,
    name: "night",
    zenith: "#0a1020",
    horizon: "#181f3a",
    ground: "#08090e",
    sun: "#ffd0a0",
    moon: "#b8c6e8",
    hemiSky: "#4a5a86",
    hemiGround: "#3a3644",
    fill: "#5a6a98",
    ambient: "#7a88aa",
    paper: "#e8eaf0",
    edge: "#c8ccd6",
    accent: "#8a96b0",
    sunI: 0.06,
    moonI: 0.4,
    hemiI: 0.48,
    fillI: 0.22,
    ambientI: 0.28,
    fogD: 0.0036,
    exposure: 1.02,
    stars: 1,
  },
  {
    t: 1,
    name: "night",
    zenith: "#070b16",
    horizon: "#141c38",
    ground: "#08090e",
    sun: "#ffd0a0",
    moon: "#b8c6e8",
    hemiSky: "#4a5a86",
    hemiGround: "#3a3644",
    fill: "#5a6a98",
    ambient: "#7a88aa",
    paper: "#e8eaf0",
    edge: "#c8ccd6",
    accent: "#8a96b0",
    sunI: 0.06,
    moonI: 0.42,
    hemiI: 0.48,
    fillI: 0.22,
    ambientI: 0.28,
    fogD: 0.0036,
    exposure: 1.02,
    stars: 1,
  },
];

function wrap01(t) {
  return ((t % 1) + 1) % 1;
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function smooth(t) {
  return t * t * (3 - 2 * t);
}

function mixStop(a, b, u) {
  const s = smooth(u);
  const mixHex = (key) => hex(a[key]).lerp(hex(b[key]), s);
  return {
    name: u < 0.5 ? a.name : b.name,
    zenith: mixHex("zenith"),
    horizon: mixHex("horizon"),
    ground: mixHex("ground"),
    sun: mixHex("sun"),
    moon: mixHex("moon"),
    hemiSky: mixHex("hemiSky"),
    hemiGround: mixHex("hemiGround"),
    fill: mixHex("fill"),
    ambient: mixHex("ambient"),
    paper: mixHex("paper"),
    edge: mixHex("edge"),
    accent: mixHex("accent"),
    sunI: lerp(a.sunI, b.sunI, s),
    moonI: lerp(a.moonI, b.moonI, s),
    hemiI: lerp(a.hemiI, b.hemiI, s),
    fillI: lerp(a.fillI, b.fillI, s),
    ambientI: lerp(a.ambientI, b.ambientI, s),
    fogD: lerp(a.fogD, b.fogD, s),
    exposure: lerp(a.exposure, b.exposure, s),
    stars: lerp(a.stars, b.stars, s),
  };
}

function sampleLook(time) {
  const t = wrap01(time);
  let i = 0;
  while (i + 1 < STOPS.length && STOPS[i + 1].t <= t) {
    i += 1;
  }
  const a = STOPS[i];
  const b = STOPS[Math.min(i + 1, STOPS.length - 1)];
  const span = b.t - a.t;
  const u = span <= 0 ? 0 : (t - a.t) / span;
  return mixStop(a, b, u);
}

function sunDirection(time) {
  const a = (wrap01(time) - 0.25) * Math.PI * 2;
  return new THREE.Vector3(Math.cos(a), Math.sin(a), 0);
}

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.dataset.state = state || "idle";
}

function setPlaying(playing) {
  clock.playing = playing;
  orrery.root?.classList.toggle("playing", playing);
  schedulePersist();
}

function setMenu(open) {
  dock.classList.toggle("open", open);
  menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
  menuBtn.setAttribute("aria-label", open ? "close controls" : "controls");
}

function placeOrrery() {
  if (!orrery.moon) {
    return;
  }
  const a = wrap01(clock.time) * Math.PI * 2;
  const x = Math.sin(a) * MOON_ORBIT;
  const y = -Math.cos(a) * MOON_ORBIT;
  orrery.moon.setAttribute("transform", `translate(${x} ${y})`);
}

function setTime(t) {
  clock.time = wrap01(t);
  applyLook();
  placeOrrery();
  schedulePersist();
}

function orreryPoint(event) {
  const rect = orrery.root.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * 100 - 50,
    y: ((event.clientY - rect.top) / rect.height) * 100 - 50,
  };
}

function timeFromOrreryEvent(event) {
  const { x, y } = orreryPoint(event);
  return wrap01(Math.atan2(x, -y) / (Math.PI * 2));
}

function hitEarth(event) {
  const { x, y } = orreryPoint(event);
  return x * x + y * y <= 15 * 15;
}

function isoPoint(x, y, z, size) {
  const X = (x - 0.5) * size;
  const Y = (y - 0.5) * size;
  const Z = (z - 0.5) * size;
  return [
    (X - Z) * Math.cos(Math.PI / 6),
    -Y + (X + Z) * Math.sin(Math.PI / 6),
  ];
}

function cubePath(size) {
  const p = (x, y, z) => isoPoint(x, y, z, size).map((n) => n.toFixed(2)).join(" ");
  return [
    `M ${p(0, 1, 0)} L ${p(1, 1, 0)} L ${p(1, 1, 1)} L ${p(0, 1, 1)} Z`,
    `M ${p(1, 1, 0)} L ${p(1, 0, 0)} L ${p(1, 0, 1)} L ${p(1, 1, 1)}`,
    `M ${p(0, 1, 1)} L ${p(0, 0, 1)} L ${p(1, 0, 1)}`,
  ].join(" ");
}

function drawCube(parent, size) {
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("class", "cube");
  path.setAttribute("d", cubePath(size));
  parent.appendChild(path);
}

function crescentPath(radius) {
  const outer = radius;
  const inner = radius * 0.74;
  const shift = radius * 0.4;
  const x = (outer * outer - inner * inner + shift * shift) / (2 * shift);
  const y = Math.sqrt(Math.max(0, outer * outer - x * x));
  const cx = (-shift * inner * inner) / (outer * outer - inner * inner);
  const tip = x - cx;
  return [
    `M ${tip.toFixed(3)} ${y.toFixed(3)}`,
    `A ${outer} ${outer} 0 1 1 ${tip.toFixed(3)} ${(-y).toFixed(3)}`,
    `A ${inner} ${inner} 0 1 0 ${tip.toFixed(3)} ${y.toFixed(3)}`,
    "Z",
  ].join(" ");
}

function drawMoon(parent, radius) {
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("class", "moon");
  path.setAttribute("d", crescentPath(radius));
  parent.appendChild(path);
}

function ensureOrrery() {
  if (orrery.root) {
    return;
  }
  const root = document.getElementById("orrery");
  const earth = document.getElementById("orrery-earth");
  const moon = document.getElementById("orrery-moon");
  drawCube(earth, 16);
  drawMoon(moon, 5);

  orrery.root = root;
  orrery.moon = moon;

  const endDrag = () => {
    orrery.dragging = false;
    root.classList.remove("dragging");
  };
  root.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    if (hitEarth(event)) {
      setPlaying(!clock.playing);
      return;
    }
    orrery.dragging = true;
    root.classList.add("dragging");
    root.setPointerCapture(event.pointerId);
    setTime(timeFromOrreryEvent(event));
  });
  root.addEventListener("pointermove", (event) => {
    if (!orrery.dragging) {
      return;
    }
    setTime(timeFromOrreryEvent(event));
  });
  root.addEventListener("pointerup", endDrag);
  root.addEventListener("pointercancel", endDrag);

  placeOrrery();
}

function applyLook() {
  if (!world.scene) {
    return;
  }
  const look = sampleLook(clock.time);
  const sunDir = sunDirection(clock.time);
  const moonDir = sunDir.clone().negate();

  world.ambient.color.copy(look.ambient);
  world.ambient.intensity = look.ambientI;
  world.hemi.color.copy(look.hemiSky);
  world.hemi.groundColor.copy(look.hemiGround);
  world.hemi.intensity = look.hemiI;

  if (sunDir.y > 0) {
    world.sun.position.copy(sunDir).multiplyScalar(220);
    world.sun.color.copy(look.sun);
    world.sun.intensity = look.sunI * Math.max(sunDir.y, 0.18);
  } else {
    world.sun.position.copy(moonDir).multiplyScalar(220);
    world.sun.color.copy(look.moon);
    world.sun.intensity = look.moonI;
  }

  world.fill.position.copy(sunDir).negate();
  world.fill.position.y = Math.max(0.28, -sunDir.y * 0.25 + 0.38);
  world.fill.position.normalize().multiplyScalar(180);
  world.fill.color.copy(look.fill);
  world.fill.intensity = look.fillI;

  world.fog.color.copy(look.horizon);
  world.fog.density = look.fogD * clock.fog;
  world.scene.background = look.horizon.clone();
  world.renderer.setClearColor(look.horizon, 1);
  world.renderer.toneMappingExposure = look.exposure;

  if (lightingMode === "next") {
    world.ambient.intensity = 0;
    world.hemi.intensity = 0;
    world.sun.intensity = 0;
    world.fill.intensity = 0;
    writeLightmap();
  }

  if (world.sky) {
    const u = world.sky.material.uniforms;
    u.uZenith.value.copy(look.zenith);
    u.uHorizon.value.copy(look.horizon);
    u.uGround.value.copy(look.ground);
    u.uStars.value = look.stars;
  }

  placeCelestials();

  const paper = `#${look.paper.getHexString()}`;
  const edge = `#${look.edge.getHexString()}`;
  const accent = `#${look.accent.getHexString()}`;
  const root = document.documentElement.style;
  root.setProperty("--paper", paper);
  root.setProperty("--paper-edge", edge);
  root.setProperty("--accent", accent);
  placeOrrery();
}

function resetOrbit() {
  if (!world.controls || !world.sceneInfo) {
    return;
  }
  const target = new THREE.Vector3(...world.sceneInfo.camera_target);
  world.controls.target.copy(target);
  world.camera.position.set(target.x - 12, target.y + 8, target.z - 16);
  world.controls.update();
  schedulePersist();
}

function getBrightness(level) {
  return level / (4.0 - 3.0 * level);
}

function notGamma(r, g, b) {
  const lift = (x) => 1 - (1 - x) ** 4;
  return [lift(r), lift(g), lift(b)];
}

function ensureLightmap() {
  if (world.lightmap) {
    return world.lightmap;
  }
  const tex = new THREE.DataTexture(
    lightmapPixels,
    LIGHTMAP_SIZE,
    LIGHTMAP_SIZE,
    THREE.RGBAFormat
  );
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearFilter;
  tex.generateMipmaps = false;
  tex.wrapS = THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.flipY = false;
  tex.colorSpace = THREE.LinearSRGBColorSpace;
  tex.needsUpdate = true;
  world.lightmap = tex;
  return tex;
}

function vanillaSkyFactor(time) {
  // ClientLevel.getSkyDarken: 1.0 at noon, 0.2 at midnight.
  // cos(celestial * 2π) tracks sun height, which is sunDirection().y for us.
  const elev = sunDirection(time).y;
  let f = 1 - (elev * 2 + 0.2);
  f = THREE.MathUtils.clamp(f, 0, 1);
  f = 1 - f;
  return f * 0.8 + 0.2;
}

function writeLightmap() {
  const tex = ensureLightmap();
  // Terrain is Color * lightmap(block, sky). Night scales the sky axis only.
  const skyFactor = vanillaSkyFactor(clock.time);
  const blockFactor = 1.0;
  const brightnessFactor = clock.brightness;
  for (let sky = 0; sky < LIGHTMAP_SIZE; sky++) {
    for (let block = 0; block < LIGHTMAP_SIZE; block++) {
      const blockB = getBrightness(block / 15) * blockFactor;
      const skyB = getBrightness(sky / 15) * skyFactor;
      let r = blockB;
      let g = blockB * ((blockB * 0.6 + 0.4) * 0.6 + 0.4);
      let b = blockB * (blockB * blockB * 0.6 + 0.4);
      r += skyB;
      g += skyB;
      b += skyB;
      r = r * 0.96 + 0.75 * 0.04;
      g = g * 0.96 + 0.75 * 0.04;
      b = b * 0.96 + 0.75 * 0.04;
      const lifted = notGamma(Math.min(r, 1), Math.min(g, 1), Math.min(b, 1));
      r = r * (1 - brightnessFactor) + lifted[0] * brightnessFactor;
      g = g * (1 - brightnessFactor) + lifted[1] * brightnessFactor;
      b = b * (1 - brightnessFactor) + lifted[2] * brightnessFactor;
      r = r * 0.96 + 0.75 * 0.04;
      g = g * 0.96 + 0.75 * 0.04;
      b = b * 0.96 + 0.75 * 0.04;
      const i = (sky * LIGHTMAP_SIZE + block) * 4;
      lightmapPixels[i] = Math.round(THREE.MathUtils.clamp(r, 0, 1) * 255);
      lightmapPixels[i + 1] = Math.round(THREE.MathUtils.clamp(g, 0, 1) * 255);
      lightmapPixels[i + 2] = Math.round(THREE.MathUtils.clamp(b, 0, 1) * 255);
      lightmapPixels[i + 3] = 255;
    }
  }
  tex.needsUpdate = true;
  syncFancyUniforms();
}

function faceShadeArray(geometry) {
  const normals = geometry.getAttribute("normal");
  const shade = new Float32Array(normals.count);
  for (let i = 0; i < normals.count; i++) {
    const x = normals.getX(i);
    const y = normals.getY(i);
    const z = normals.getZ(i);
    const ax = Math.abs(x);
    const ay = Math.abs(y);
    const az = Math.abs(z);
    if (ay >= ax && ay >= az) {
      shade[i] = y >= 0 ? 1 : 0.5;
    } else if (az >= ax) {
      shade[i] = 0.8;
    } else {
      shade[i] = 0.6;
    }
  }
  return shade;
}

function passHasLight(pass) {
  const light = pass.light;
  for (let i = 0; i < light.length; i++) {
    if (light[i] > 0) {
      return true;
    }
  }
  return false;
}

function parsePass(buffer, info) {
  const verts = info.vertex_count;
  const indices = info.index_count;
  const posBytes = verts * 3 * 4;
  const uvBytes = verts * 2 * 4;
  const colorBytes = verts * 3 * 4;
  const emitBytes = verts * 3 * 4;
  const lightBytes = verts * 2 * 4;
  const indexBytes = indices * 4;
  const withLight = posBytes + uvBytes + colorBytes + emitBytes + lightBytes + indexBytes;
  const withEmit = posBytes + uvBytes + colorBytes + emitBytes + indexBytes;
  const hasLight = buffer.byteLength >= withLight;
  const hasEmit = buffer.byteLength >= withEmit;
  const emitOff = posBytes + uvBytes + colorBytes;
  const lightOff = emitOff + emitBytes;
  let indexOff = emitOff;
  if (hasLight) {
    indexOff = lightOff + lightBytes;
  } else if (hasEmit) {
    indexOff = emitOff + emitBytes;
  }
  return {
    positions: new Float32Array(buffer, 0, verts * 3),
    uvs: new Float32Array(buffer, posBytes, verts * 2),
    colors: new Float32Array(buffer, posBytes + uvBytes, verts * 3),
    emit: hasEmit
      ? new Float32Array(buffer, emitOff, verts * 3)
      : new Float32Array(verts * 3),
    light: hasLight
      ? new Float32Array(buffer, lightOff, verts * 2)
      : new Float32Array(verts * 2),
    indices: new Uint32Array(buffer, indexOff, indices),
  };
}

function geometryFromPass(pass) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(pass.positions, 3));
  geometry.setAttribute("uv", new THREE.BufferAttribute(pass.uvs, 2));
  geometry.setAttribute("lightUv", new THREE.BufferAttribute(pass.light, 2));
  geometry.setAttribute("color", new THREE.BufferAttribute(pass.colors, 3));
  geometry.setAttribute("emit", new THREE.BufferAttribute(pass.emit, 3));
  geometry.setIndex(new THREE.BufferAttribute(pass.indices, 1));
  geometry.computeVertexNormals();
  geometry.setAttribute("shade", new THREE.BufferAttribute(faceShadeArray(geometry), 1));
  return geometry;
}

function blockMaterial(params) {
  const material = new THREE.MeshLambertMaterial(params);
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        "#include <common>\nattribute vec3 emit;\nvarying vec3 vEmit;"
      )
      .replace("#include <color_vertex>", "#include <color_vertex>\nvEmit = emit;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vEmit;")
      .replace(
        "#include <opaque_fragment>",
        "outgoingLight += vEmit * diffuseColor.rgb;\n#include <opaque_fragment>"
      );
  };
  material.customProgramCacheKey = () => "block-emit";
  return material;
}

function fancyMaterial(params) {
  // Do not use MeshBasicMaterial.lightMap — in r170 it samples atlas `uv`
  // (texture.channel defaults to 0). Vanilla does Color * lightmap(block, sky)
  // in rendertype_solid.vsh via minecraft_sample_lightmap.
  const material = new THREE.MeshBasicMaterial(params);
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uLightmap = { value: ensureLightmap() };
    shader.uniforms.uSkyFactor = { value: vanillaSkyFactor(clock.time) };
    material.userData.shader = shader;
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        "#include <common>\nattribute vec2 lightUv;\nattribute vec3 emit;\nattribute float shade;\nvarying vec2 vLightUv;\nvarying vec3 vEmit;\nvarying float vShade;"
      )
      .replace(
        "#include <color_vertex>",
        "#include <color_vertex>\nvLightUv = lightUv;\nvEmit = emit;\nvShade = shade;"
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        "#include <common>\nuniform sampler2D uLightmap;\nuniform float uSkyFactor;\nvarying vec2 vLightUv;\nvarying vec3 vEmit;\nvarying float vShade;"
      )
      .replace(
        "#include <opaque_fragment>",
        [
          "outgoingLight *= texture2D(uLightmap, vLightUv).rgb * vShade;",
          "outgoingLight += vEmit * diffuseColor.rgb * (0.2 + 0.55 * (1.0 - uSkyFactor));",
          "#include <opaque_fragment>",
        ].join("\n")
      );
  };
  material.customProgramCacheKey = () => "block-fancy";
  return material;
}

function syncFancyUniforms() {
  const sky = vanillaSkyFactor(clock.time);
  for (const mesh of world.meshes) {
    const shader = mesh.material.userData.shader;
    if (shader?.uniforms?.uSkyFactor) {
      shader.uniforms.uSkyFactor.value = sky;
    }
  }
}

function passMaterial(kind, params) {
  if (lightingMode === "next") {
    return fancyMaterial(params);
  }
  return blockMaterial(params);
}

function applyTerrainLighting() {
  if (!world.scene) {
    return;
  }
  applyLook();
  if (!world.texture || world.meshes.length === 0) {
    return;
  }
  for (const mesh of world.meshes) {
    const prev = mesh.material;
    const translucent = mesh.userData.pass === "translucent";
    mesh.material = passMaterial(
      mesh.userData.pass,
      translucent
        ? {
            map: world.texture,
            vertexColors: true,
            transparent: true,
            depthWrite: false,
            side: THREE.DoubleSide,
          }
        : {
            map: world.texture,
            vertexColors: true,
            alphaTest: 0.5,
          }
    );
    prev.dispose();
  }
  if (lightingMode === "next" && world.meshes.every((mesh) => !mesh.userData.hasLight)) {
    setStatus("rebake to fill the fancy lightmap", "idle");
  }
}

async function loadBin(name, info, bust) {
  if (!info.vertex_count) {
    return null;
  }
  const response = await fetch(`generated/${name}?t=${bust}`);
  if (!response.ok) {
    throw new Error(`failed to fetch ${name}`);
  }
  return parsePass(await response.arrayBuffer(), info);
}

function clearMeshes() {
  for (const mesh of world.meshes) {
    world.scene.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
  }
  world.meshes = [];
  if (world.texture) {
    world.texture.dispose();
    world.texture = null;
  }
}

function applyView(sceneInfo) {
  const view = sceneInfo.view || {};
  if (view.block_x != null) inputX.value = view.block_x;
  if (view.block_z != null) inputZ.value = view.block_z;
  if (view.radius != null) inputRadius.value = view.radius;
  if (view.min_y != null) inputMinY.value = view.min_y;
}

async function mountScene(sceneInfo, { retarget } = { retarget: true }) {
  const bust = Date.now();
  const [opaquePass, translucentPass] = await Promise.all([
    loadBin(sceneInfo.opaque.file, sceneInfo.opaque, bust),
    loadBin(sceneInfo.translucent.file, sceneInfo.translucent, bust),
  ]);

  clearMeshes();
  const texture = await new THREE.TextureLoader().loadAsync(
    `generated/${sceneInfo.atlas.file}?t=${bust}`
  );
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.generateMipmaps = false;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.flipY = false;
  world.texture = texture;

  if (opaquePass) {
    const material = passMaterial("opaque", {
      map: texture,
      vertexColors: true,
      alphaTest: 0.5,
    });
    const mesh = new THREE.Mesh(geometryFromPass(opaquePass), material);
    mesh.userData.pass = "opaque";
    mesh.userData.hasLight = passHasLight(opaquePass);
    world.scene.add(mesh);
    world.meshes.push(mesh);
  }
  if (translucentPass) {
    const material = passMaterial("translucent", {
      map: texture,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(geometryFromPass(translucentPass), material);
    mesh.userData.pass = "translucent";
    mesh.userData.hasLight = passHasLight(translucentPass);
    mesh.renderOrder = 1;
    world.scene.add(mesh);
    world.meshes.push(mesh);
  }

  world.sceneInfo = sceneInfo;
  if (retarget) {
    resetOrbit();
  }
  applyView(sceneInfo);
  applyLook();
}

function makeSky() {
  const material = new THREE.ShaderMaterial({
    uniforms: {
      uZenith: { value: hex("#7eb6e8") },
      uHorizon: { value: hex("#c8dff0") },
      uGround: { value: hex("#8a9aaa") },
      uStars: { value: 0 },
    },
    vertexShader: SKY_VERT,
    fragmentShader: SKY_FRAG,
    side: THREE.BackSide,
    depthWrite: false,
    fog: false,
  });
  const sky = new THREE.Mesh(new THREE.SphereGeometry(3600, 32, 16), material);
  sky.frustumCulled = false;
  sky.renderOrder = -1;
  return sky;
}

function makeCelestialBody(color) {
  const material = new THREE.MeshBasicMaterial({
    color: hex(color),
    fog: false,
    depthWrite: false,
    toneMapped: false,
    side: THREE.DoubleSide,
  });
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(CELESTIAL_SIZE, CELESTIAL_SIZE),
    material
  );
  mesh.frustumCulled = false;
  return mesh;
}

function placeCelestials() {
  if (!world.sunBody || !world.moonBody || !world.camera) {
    return;
  }
  const sunDir = sunDirection(clock.time);
  const moonDir = sunDir.clone().negate();
  const cam = world.camera.position;

  world.sunBody.visible = sunDir.y >= 0;
  world.moonBody.visible = moonDir.y >= 0;
  world.sunBody.position.copy(cam).addScaledVector(sunDir, CELESTIAL_DISTANCE);
  world.moonBody.position.copy(cam).addScaledVector(moonDir, CELESTIAL_DISTANCE);
  world.sunBody.lookAt(cam);
  world.moonBody.lookAt(cam);
}

function ensureRenderer(prefs) {
  if (world.renderer) {
    return false;
  }
  const renderer = new THREE.WebGLRenderer({ antialias: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1;
  renderer.setClearColor(0xc8dff0, 1);
  document.body.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const fog = new THREE.FogExp2(0xc8dff0, 0.0076);
  scene.fog = fog;
  scene.background = new THREE.Color(0xc8dff0);

  const ambient = new THREE.AmbientLight(0xf0ece4, 0.34);
  const hemi = new THREE.HemisphereLight(0xc4daf0, 0x9a8a6e, 0.65);
  const sun = new THREE.DirectionalLight(0xffe8b8, 1.2);
  sun.position.set(40, 80, -20);
  const fill = new THREE.DirectionalLight(0x9ab4cc, 0.32);
  fill.position.set(-50, 40, 30);
  const sky = makeSky();
  const sunBody = makeCelestialBody(SUN_BODY_COLOR);
  const moonBody = makeCelestialBody(MOON_BODY_COLOR);
  scene.add(ambient);
  scene.add(hemi);
  scene.add(sun);
  scene.add(fill);
  scene.add(sky);
  scene.add(sunBody);
  scene.add(moonBody);

  const camera = new THREE.PerspectiveCamera(
    60,
    window.innerWidth / window.innerHeight,
    0.1,
    8000
  );
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.addEventListener("change", schedulePersist);

  world.renderer = renderer;
  world.scene = scene;
  world.camera = camera;
  world.controls = controls;
  world.ambient = ambient;
  world.hemi = hemi;
  world.sun = sun;
  world.fill = fill;
  world.sky = sky;
  world.sunBody = sunBody;
  world.moonBody = moonBody;
  world.fog = fog;

  applyLook();
  ensureOrrery();
  placeOrrery();

  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  const restored = restoreCamera(prefs);

  let last = performance.now();
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (clock.playing && !orrery.dragging) {
      setTime(clock.time + dt * clock.speed);
    }
    applyWalk(dt);
    sky.position.copy(camera.position);
    placeCelestials();
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  frame(last);
  return restored;
}

async function fetchScene() {
  const response = await fetch(`generated/scene.json?t=${Date.now()}`);
  if (!response.ok) {
    throw new Error("no generated/scene.json — bake once, or use serve_viewer.py");
  }
  return response.json();
}

async function checkBakeApi() {
  try {
    const response = await fetch("api/health");
    if (!response.ok) {
      return null;
    }
    return response.json();
  } catch {
    return null;
  }
}

async function rebake(event) {
  event.preventDefault();
  const health = await checkBakeApi();
  if (!health) {
    setStatus("start tools/serve_viewer.py to rebake from here", "error");
    return;
  }
  const body = {
    x: Number(inputX.value),
    z: Number(inputZ.value),
    radius: Number(inputRadius.value),
    min_y: Number(inputMinY.value),
  };
  rebakeBtn.disabled = true;
  setStatus("baking… this can take a bit", "baking");
  try {
    const response = await fetch("api/bake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `bake failed (${response.status})`);
    }
    ensureRenderer();
    await mountScene(payload.scene, { retarget: true });
    setStatus("done", "done");
  } catch (error) {
    setStatus(String(error.message || error), "error");
  } finally {
    rebakeBtn.disabled = false;
  }
}

function isTyping(target) {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable;
}

function applyWalk(dt) {
  if (!world.camera || !world.controls || walkKeys.size === 0) {
    return;
  }
  if (isTyping(document.activeElement)) {
    return;
  }
  world.camera.getWorldDirection(walkForward);
  walkForward.y = 0;
  if (walkForward.lengthSq() < 1e-6) {
    return;
  }
  walkForward.normalize();
  walkRight.crossVectors(walkForward, world.camera.up).normalize();
  walkMove.set(0, 0, 0);
  if (walkKeys.has("KeyW")) {
    walkMove.add(walkForward);
  }
  if (walkKeys.has("KeyS")) {
    walkMove.sub(walkForward);
  }
  if (walkKeys.has("KeyD")) {
    walkMove.add(walkRight);
  }
  if (walkKeys.has("KeyA")) {
    walkMove.sub(walkRight);
  }
  if (walkMove.lengthSq() === 0) {
    return;
  }
  walkMove.normalize().multiplyScalar(WALK_SPEED * dt);
  world.camera.position.add(walkMove);
  world.controls.target.add(walkMove);
  schedulePersist();
}

function onKey(event) {
  if (event.key === "Escape" && dock.classList.contains("open")) {
    event.preventDefault();
    setMenu(false);
    return;
  }
  if (event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) {
    return;
  }
  if (event.code === "KeyW" || event.code === "KeyA" || event.code === "KeyS" || event.code === "KeyD") {
    event.preventDefault();
    walkKeys.add(event.code);
    return;
  }
  if (event.key === " " || event.code === "Space") {
    event.preventDefault();
    setPlaying(!clock.playing);
    return;
  }
  if (event.key === "r" || event.key === "R") {
    event.preventDefault();
    resetOrbit();
  }
}

function onKeyUp(event) {
  walkKeys.delete(event.code);
}

async function main() {
  ensureOrrery();
  const prefs = readPrefs();
  applySavedPrefs(prefs);
  persistEnabled = true;
  placeForm.addEventListener("submit", rebake);
  menuBtn.addEventListener("click", () => setMenu(!dock.classList.contains("open")));
  lightingNowBtn.addEventListener("click", () => setLightingMode("now"));
  lightingNextBtn.addEventListener("click", () => setLightingMode("next"));
  brightnessInput.addEventListener("input", () => {
    setBrightness(Number(brightnessInput.value) / 100);
  });
  resetBtn.addEventListener("click", resetOrbit);
  window.addEventListener("keydown", onKey);
  window.addEventListener("keyup", onKeyUp);
  window.addEventListener("blur", () => walkKeys.clear());
  window.addEventListener("pagehide", flushPrefs);

  const health = await checkBakeApi();
  if (!health) {
    placeForm.classList.add("offline");
    setStatus("static demo — look around, time of day, and lighting all work here", "idle");
  } else {
    inputRadius.max = String(health.max_radius ?? 4);
  }

  try {
    const sceneInfo = await fetchScene();
    const restored = ensureRenderer(prefs);
    await mountScene(sceneInfo, { retarget: !restored });
  } catch (error) {
    const missing = /scene\.json/.test(String(error.message || error));
    if (health && missing) {
      setStatus("no bake yet — hit rebake", "idle");
    } else {
      setStatus(String(error.message || error), "error");
    }
    setMenu(true);
    console.error(error);
  }
}

main().catch((error) => {
  setStatus(String(error), "error");
  setMenu(true);
  console.error(error);
});
