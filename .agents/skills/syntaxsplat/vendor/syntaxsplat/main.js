// SyntaxSplat renderer. Scenes are written as SDF primitives (see scenes/), workers
// lay Gaussian splats on their surfaces with lighting baked in (engine.js), and
// this file draws them: depth-sorted splats that follow their part's matrix,
// then a palette post-process for the pixel-art look.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { parts, state, updateParts, finalizeRest, planTasks, lerp, hex, SPLAT_FLOATS } from './engine.js';
import { buildPly, download } from './export.js';
import { buildParticles, particleCenters, WORLD_PART } from './particles.js';
import { bakeKey, loadBake, saveBake, clearBake } from './cache.js';

const ui = Object.fromEntries(['scene', 'pixel', 'rows', 'size', 'explode', 'anim', 'orbit', 'palette', 'brush', 'outline', 'dof', 'focus', 'live', 'particles', 'exportPly', 'rebake', 'hud', 'load'].map((id) => [id, document.getElementById(id)]));
// The manifest is the only source of scene ids, so ?scene= cannot name an arbitrary module path.
const manifest = await fetch('./scenes/index.json').then((r) => {
  if (!r.ok) throw new Error(`scenes/index.json: HTTP ${r.status}`);
  return r.json();
}).catch((e) => { ui.load.textContent = 'Cannot read scenes/index.json: ' + e.message; throw e; });
const query = new URLSearchParams(location.search), wanted = query.get('scene');
if (query.get('ui') === '0') document.getElementById('ui').hidden = true;   // clean frame for screenshots
const sceneName = (manifest.find((s) => s.id === wanted) || manifest[0]).id;
ui.scene.replaceChildren(...manifest.map((s) => new Option(s.title, s.id)));
ui.scene.value = sceneName;
ui.scene.addEventListener('change', () => { location.search = '?scene=' + ui.scene.value; });
ui.exportPly.addEventListener('click', () => { if (baked) download(buildPly(baked, +ui.size.value), sceneName + '.ply'); });
ui.rebake.addEventListener('click', async () => { await clearBake(sceneName); location.reload(); });

// Hash the scene sources before importing the scene, see bakeKey().
const cacheKey = await bakeKey(sceneName);
const cfg = state.cfg = (await import(`./scenes/${sceneName}.js`)).default();
finalizeRest();
const particleData = buildParticles(cfg.emitters || [], parts);

// ---------------------------------------------------------------- renderer
const MAX_PARTS = 128, PART_W = 8; // part texture: 4 texels matrix, 1 fx, 1 fx2, 2 spare
const DATA_W = 2048;               // splat texture width; SPLAT_FLOATS / 4 texels per splat
const STROKE = [1.8, 0.6];         // long-stroke brush: tangent and bitangent stretch
const MAX_LIVE = 4;                // live point lights evaluated per splat
THREE.ColorManagement.enabled = false;
const renderer = new THREE.WebGLRenderer({ antialias: false });
renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
document.body.appendChild(renderer.domElement);

const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 200);
camera.position.set(...cfg.camera.pos);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(...cfg.camera.target);
controls.enableDamping = true;
controls.autoRotateSpeed = 1.2;

const partBuf = new Float32Array(PART_W * MAX_PARTS * 4);
const partTex = new THREE.DataTexture(partBuf, PART_W, MAX_PARTS, THREE.RGBAFormat, THREE.FloatType);

const splatUniforms = {
  uData: { value: null }, uTexW: { value: DATA_W }, uParts: { value: partTex },
  uTime: { value: 0 }, uSize: { value: 1 }, uExplode: { value: 0 },
  uFog: { value: new THREE.Vector4(...cfg.fog.col, cfg.fog.density) }, uFogStart: { value: cfg.fog.start },
  uRim: { value: new THREE.Vector3(...cfg.rim) },
  uLLPos: { value: Array.from({ length: MAX_LIVE }, () => new THREE.Vector4()) },
  uLLCol: { value: Array.from({ length: MAX_LIVE }, () => new THREE.Vector4()) }, uLLN: { value: 0 },
  uWind: { value: new THREE.Vector4() }, uBrush: { value: 0 }, uAniso: { value: new THREE.Vector2(1, 1) }, uDof: { value: new THREE.Vector2(0, 10) },
};

const splatVertex = /* glsl */`
    uniform sampler2D uData, uParts;
    uniform float uTexW, uTime, uSize, uExplode, uFogStart;
    uniform vec4 uFog; uniform vec3 uRim;
    uniform vec4 uLLPos[4], uLLCol[4]; uniform int uLLN;   // live lights: xyz world pos + power, rgb + k
    uniform vec2 uAniso;                                   // brush stretch along tangent and bitangent
    uniform vec4 uWind;                                    // xyz: direction * strength, w: speed
    uniform vec2 uDof;                                     // depth of field: on/off, focus distance
    attribute float aIndex;
    varying vec2 vQ; varying vec3 vCol; varying float vA, vId, vDepth;
    vec3 hash3(float n) { return fract(sin(vec3(n * 12.9898, n * 78.233, n * 37.719)) * 43758.5453); }
    void main() {
      // five texels per splat do not divide the texture width, so each is addressed on its own
      int base = int(aIndex) * 5, w = int(uTexW);
      vec4 d0 = texelFetch(uData, ivec2(base % w, base / w), 0), d1 = texelFetch(uData, ivec2((base + 1) % w, (base + 1) / w), 0);
      vec4 d2 = texelFetch(uData, ivec2((base + 2) % w, (base + 2) / w), 0), d3 = texelFetch(uData, ivec2((base + 3) % w, (base + 3) / w), 0);
      vec4 d4 = texelFetch(uData, ivec2((base + 4) % w, (base + 4) / w), 0);
      int pi = int(d0.w + 0.5);
      bool isP = d4.w > 1.5, world = pi >= 255;   // particle records; part 255 means world space
      int pr = world ? 0 : pi;
      mat4 M = world ? mat4(1.0) : mat4(texelFetch(uParts, ivec2(0, pr), 0), texelFetch(uParts, ivec2(1, pr), 0),
                                        texelFetch(uParts, ivec2(2, pr), 0), texelFetch(uParts, ivec2(3, pr), 0));
      vec4 fx = world ? vec4(0.0, 0.0, 1.0, 0.0) : texelFetch(uParts, ivec2(4, pr), 0);   // dissolve, wobble, opacity, pulse
      vec4 fx2 = world ? vec4(1.0, 0.0, 0.0, 0.0) : texelFetch(uParts, ivec2(5, pr), 0);  // fog amount, rim amount, wind, outline flag
      vec3 local = d0.xyz;
      float age01 = 0.0;
      if (isP) {   // closed-form flight, mirrored by particleCenters() for the depth sort
        age01 = fract(uTime / d2.z + d2.y);
        float age = age01 * d2.z;
        local += d1.xyz * age;
        local.y -= 0.5 * d2.x * age * age;
      }
      vec3 c = (M * vec4(local, 1.0)).xyz;
      mat3 R = mat3(M);
      vec3 n = normalize(R * d1.xyz), t = normalize(R * d2.xyz), b = cross(n, t);
      if (isP) {   // camera-facing billboard
        t = vec3(viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0]);
        b = vec3(viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1]);
        n = normalize(cameraPosition - c);
      }
      vec3 rnd = hash3(d1.w);

      // wind leans a part downwind in proportion to the splat's height above the part origin
      float gust = 0.6 + 0.4 * sin(uTime * uWind.w + dot(c.xz, vec2(0.9, 0.7)));
      c += uWind.xyz * fx2.z * max(d0.y, 0.0) * gust;

      c.y += fx.y * sin(uTime * 1.4 + c.x * 1.3 + c.z * 1.9);      // liquid swell

      vec3 lightPos = c;
      float dis = isP ? 0.0 : clamp(fx.x + uExplode, 0.0, 1.0), e = dis * dis;  // dissolve
      c += normalize(n + (rnd - 0.5) * 1.6) * e * (1.2 + 2.0 * rnd.x);
      c.y += e * 1.2 * rnd.z - e * e * 1.6;
      float size = uSize * (1.0 - smoothstep(0.55, 1.0, dis)) * (1.0 - 0.6 * age01);

      vec3 toCam = cameraPosition - c;
      float camDist = length(toCam);
      float facing = dot(n, normalize(toCam));
      float cull = mix(smoothstep(-0.15, 0.1, facing), 1.0, min(1.0, dis * 4.0));

      // splats away from the focus distance grow and thin out
      float blur = uDof.x * min(abs(camDist - uDof.y) / (0.35 * uDof.y), 3.0);
      size *= 1.0 + 0.8 * blur;
    #ifdef ID_PASS
      size *= 1.3;   // fills the gaps between sparse splats so only real silhouettes read as edges
    #endif

      vec3 col = d3.rgb * (1.0 + fx.w * sin(uTime * 2.3 + float(pi) * 1.7));
      // live lights add albedo * light on top of the baked colour; emissive splats are already full bright
      if (d4.w < 0.5) {
        vec3 live = vec3(0.0);
        for (int i = 0; i < 4; i++) {
          if (i >= uLLN) break;
          vec3 L = uLLPos[i].xyz - lightPos; float dist = max(length(L), 1e-3);
          live += uLLCol[i].rgb * (uLLPos[i].w * max(0.0, dot(n, L) / dist) / (1.0 + uLLCol[i].w * dist * dist));
        }
        col += d4.rgb * live;
      }
      float lum = dot(col, vec3(0.3, 0.59, 0.11));
      col += uRim * fx2.y * pow(1.0 - clamp(facing, 0.0, 1.0), 3.0) * (0.15 + 1.5 * lum);  // wet sheen
      float fog = (1.0 - exp(-uFog.w * max(0.0, camDist - uFogStart))) * fx2.x;
      col = mix(col, uFog.rgb, fog);

      vec3 wp = c + (t * position.x * d2.w * uAniso.x + b * position.y * d3.w * uAniso.y) * size;
      vQ = position.xy; vCol = col; vA = cull * fx.z / (1.0 + 0.6 * blur) * (isP ? smoothstep(0.0, 0.08, age01) * (1.0 - age01) : 1.0);
      vId = fx2.w > 0.5 && !isP ? float(pi) + 1.0 : 0.0;
      vDepth = -(viewMatrix * vec4(c, 1.0)).z;
      gl_Position = cull < 0.01 ? vec4(2.0, 2.0, 2.0, 1.0) : projectionMatrix * viewMatrix * vec4(wp, 1.0);
    }`;

// Brush: 0 soft dab, 1 hard disc, 2 square, 3 long stroke (soft dab, stretched in the vertex shader).
// With ID_PASS the same coverage is alpha-tested into a part id + view depth buffer for outlines.
const splatFragment = /* glsl */`
    uniform float uBrush;
    varying vec2 vQ; varying vec3 vCol; varying float vA, vId, vDepth;
    void main() {
      float r2 = dot(vQ, vQ), a;
      if (uBrush < 0.5 || uBrush > 2.5) {
        if (r2 > 1.0) discard;
        a = min(1.0, 1.7 * exp(-3.2 * r2)) * (1.0 - smoothstep(0.7, 1.0, r2));
      } else if (uBrush < 1.5) {
        if (r2 > 0.64) discard;
        a = 1.0;
      } else {
        if (max(abs(vQ.x), abs(vQ.y)) > 0.8) discard;
        a = 1.0;
      }
      a *= vA;
    #ifdef ID_PASS
      if (a < 0.15 || vId < 0.5) discard;
      gl_FragColor = vec4(vId, vDepth, 0.0, 1.0);
    #else
      gl_FragColor = vec4(vCol * a, a);
    #endif
    }`;

const splatMaterial = new THREE.ShaderMaterial({
  uniforms: splatUniforms, vertexShader: splatVertex, fragmentShader: splatFragment,
  transparent: true, premultipliedAlpha: true, depthTest: false, depthWrite: false, side: THREE.DoubleSide,
});
// Same sorted splats, opaque and unblended: the nearest one is drawn last, so each pixel keeps its id and depth.
const idMaterial = new THREE.ShaderMaterial({
  uniforms: splatUniforms, vertexShader: splatVertex, fragmentShader: splatFragment, defines: { ID_PASS: 1 },
  transparent: false, blending: THREE.NoBlending, depthTest: false, depthWrite: false, side: THREE.DoubleSide,
});

const scene = new THREE.Scene();
const quadVertex = 'varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }';

const sky = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
  uniforms: { uTop: { value: new THREE.Vector3(...cfg.bgTop) }, uBottom: { value: new THREE.Vector3(...cfg.bgBottom) } },
  depthTest: false, depthWrite: false, vertexShader: quadVertex,
  fragmentShader: 'uniform vec3 uTop, uBottom; varying vec2 vUv; void main() { gl_FragColor = vec4(mix(uBottom, uTop, smoothstep(0.1, 0.75, vUv.y)), 1.0); }',
}));
sky.frustumCulled = false;
sky.renderOrder = -1;
scene.add(sky);

const geometry = new THREE.InstancedBufferGeometry();
geometry.setAttribute('position', new THREE.Float32BufferAttribute([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0], 3));
geometry.setIndex([0, 1, 2, 0, 2, 3]);
const splatMesh = new THREE.Mesh(geometry, splatMaterial);
splatMesh.frustumCulled = false;
scene.add(splatMesh);
const idScene = new THREE.Scene(), idMesh = new THREE.Mesh(geometry, idMaterial);
idMesh.frustumCulled = false;
idScene.add(idMesh);

// pixel-art pass: low-res target, ordered dither, nearest palette colour
const MAX_PAL = 64;
const target = new THREE.WebGLRenderTarget(4, 4, { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: false });
// part id (0 = none) and view depth per pixel, only rendered while Outline is on
const idTarget = new THREE.WebGLRenderTarget(4, 4, { type: THREE.HalfFloatType, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: false });
const postUniforms = {
  tDiffuse: { value: target.texture }, tId: { value: idTarget.texture }, uRes: { value: new THREE.Vector2(4, 4) },
  uPal: { value: Array.from({ length: MAX_PAL }, () => new THREE.Vector3()) }, uPalN: { value: 0 },
  uDither: { value: 0.07 }, uOutline: { value: 0 },
};
const postScene = new THREE.Scene();
const postCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
postScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
  uniforms: postUniforms, depthTest: false, depthWrite: false, vertexShader: quadVertex,
  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse, tId; uniform vec2 uRes; uniform vec3 uPal[${MAX_PAL}]; uniform int uPalN;
    uniform float uDither, uOutline;
    varying vec2 vUv;
    float bayer(vec2 p) {
      float m[16] = float[16](0., 8., 2., 10., 12., 4., 14., 6., 3., 11., 1., 9., 15., 7., 13., 5.);
      return m[int(mod(p.x, 4.0)) + int(mod(p.y, 4.0)) * 4] / 16.0;
    }
    // 1 when a neighbouring pixel is a different part or clearly farther away: the line goes on the nearer pixel
    float edge(vec2 px) {
      vec2 me = texture2D(tId, (px + 0.5) / uRes).rg;
      if (me.x < 0.5) return 0.0;
      for (int i = 0; i < 4; i++) {
        vec2 off = i == 0 ? vec2(1., 0.) : i == 1 ? vec2(-1., 0.) : i == 2 ? vec2(0., 1.) : vec2(0., -1.);
        vec2 o = texture2D(tId, (px + 0.5 + off) / uRes).rg;
        if (o.x < 0.5) return 1.0;
        if (o.x != me.x && me.y <= o.y) return 1.0;
        if (o.y - me.y > 0.06 * me.y + 0.05) return 1.0;
      }
      return 0.0;
    }
    void main() {
      vec2 px = floor(vUv * uRes);
      vec3 c = texture2D(tDiffuse, (px + 0.5) / uRes).rgb + (bayer(px) - 0.5) * uDither;
      if (uOutline > 0.5) c *= 1.0 - 0.65 * edge(px);
      float best = 1e9; vec3 o = c;
      for (int i = 0; i < ${MAX_PAL}; i++) {
        if (i >= uPalN) break;
        vec3 d = c - uPal[i];
        float dd = dot(d * d, vec3(0.3, 0.59, 0.11));
        if (dd < best) { best = dd; o = uPal[i]; }
      }
      gl_FragColor = vec4(o, 1.0);
    }`,
})));

// Palettes: the scene's own, plus presets for a quick restyle.
const PALETTES = {
  scene: { title: 'Scene palette', colors: cfg.palette },
  handheld: { title: '4-shade green handheld', colors: [0x0f380f, 0x306230, 0x8bac0f, 0x9bbc0f].map(hex) },
  mono: { title: 'Black and white', colors: [0x000000, 0xffffff].map(hex) },
  sepia: { title: 'Sepia ramp', colors: [0x1a0f08, 0x3b2616, 0x6b4a2b, 0x9b7448, 0xcfa96f, 0xf2e0b8].map(hex) },
  amber: { title: 'Amber terminal', colors: [0x0a0500, 0x4a2a00, 0xa86400, 0xffb000].map(hex) },
  pico: { title: '16 colours', colors: [0x000000, 0x1d2b53, 0x7e2553, 0x008751, 0xab5236, 0x5f574f, 0xc2c3c7, 0xfff1e8, 0xff004d, 0xffa300, 0xffec27, 0x00e436, 0x29adff, 0x83769c, 0xff77a8, 0xffccaa].map(hex) },
};
if (cfg.palette.length > MAX_PAL) console.warn(`scene palette has ${cfg.palette.length} colours, only the first ${MAX_PAL} are used`);
ui.palette.replaceChildren(...Object.entries(PALETTES).map(([id, p]) => new Option(p.title, id)));
function applyPalette() {
  const list = PALETTES[ui.palette.value].colors.slice(0, MAX_PAL);
  list.forEach((c, i) => postUniforms.uPal.value[i].set(c[0], c[1], c[2]));
  postUniforms.uPalN.value = list.length;
}
ui.palette.addEventListener('change', applyPalette);
applyPalette();

// ---------------------------------------------------------------- build
let N = 0, NP = 0, centers, partOf, depth, keys, order, buildMs = 0, fromCache = false, baked;
const counts = new Uint32Array(65537);

// Farm the surface sampling and light bake out to workers. Returns the splats as one
// packed Float32Array of SPLAT_FLOATS per splat.
async function bake() {
  const tasks = planTasks(), results = new Array(tasks.length);
  const total = tasks.reduce((s, t) => s + t.count, 0);
  const workers = Math.max(2, Math.min(12, (navigator.hardwareConcurrency || 4) - 2));
  let next = 0, done = 0, made = 0;
  await new Promise((resolve, reject) => {
    for (let i = 0; i < workers; i++) {
      const w = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });
      const feed = () => { if (next < tasks.length) w.postMessage({ task: tasks[next++] }); else w.terminate(); };
      w.onerror = (e) => reject(new Error(e.message || 'bake worker failed'));
      w.onmessage = (e) => {
        if (!e.data.ready) {
          results[e.data.id] = e.data.buf;
          made += e.data.buf.length / SPLAT_FLOATS;
          ui.load.textContent = `Painting splats… ${Math.round(made / total * 100)}%`;
          if (++done === tasks.length) { w.terminate(); resolve(); return; }
        }
        feed();
      };
      w.postMessage({ scene: sceneName });
    }
  });
  const packed = new Float32Array(results.reduce((s, b) => s + b.length, 0));
  let off = 0;
  for (const b of results) { packed.set(b, off); off += b.length; }
  console.log(`baked on ${workers} workers`);
  return packed;
}

// Splats come from the bake cache when the scene and engine are unchanged, else from the workers.
async function build() {
  const t0 = performance.now();
  const hit = await loadBake(cacheKey);
  fromCache = !!hit;
  const packed = baked = hit ? hit.buf : await bake();
  if (!hit) saveBake(cacheKey, sceneName, { buf: packed });

  N = packed.length / SPLAT_FLOATS;
  NP = particleData.length / SPLAT_FLOATS;
  const texH = Math.ceil((N + NP) * SPLAT_FLOATS / 4 / DATA_W);
  const buf = new Float32Array(DATA_W * texH * 4);
  buf.set(packed);
  buf.set(particleData, packed.length);
  const tex = new THREE.DataTexture(buf, DATA_W, texH, THREE.RGBAFormat, THREE.FloatType);
  tex.needsUpdate = true;
  splatUniforms.uData.value = tex;

  centers = new Float32Array((N + NP) * 3); partOf = new Uint8Array(N + NP);
  for (let i = 0; i < N + NP; i++) {
    centers[i * 3] = buf[i * SPLAT_FLOATS]; centers[i * 3 + 1] = buf[i * SPLAT_FLOATS + 1]; centers[i * 3 + 2] = buf[i * SPLAT_FLOATS + 2];
    partOf[i] = buf[i * SPLAT_FLOATS + 3];
  }
  depth = new Float32Array(N + NP); keys = new Uint16Array(N + NP); order = new Float32Array(N + NP);
  const attr = new THREE.InstancedBufferAttribute(order, 1);
  attr.setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute('aIndex', attr);
  ui.load.remove();
  buildMs = Math.round(performance.now() - t0);
  console.log(fromCache ? `cache hit: ${N} splats in ${buildMs} ms` : `built ${N} splats in ${buildMs} ms`);
}

// back-to-front counting sort on view depth, taking each part's current pose into account
const rowX = new Float32Array(256), rowY = new Float32Array(256), rowZ = new Float32Array(256), rowW = new Float32Array(256);
function sortSplats() {
  const V = camera.matrixWorldInverse.elements;
  for (const p of parts) {
    const m = p.world.elements, i = p.index;
    rowX[i] = V[2] * m[0] + V[6] * m[1] + V[10] * m[2];
    rowY[i] = V[2] * m[4] + V[6] * m[5] + V[10] * m[6];
    rowZ[i] = V[2] * m[8] + V[6] * m[9] + V[10] * m[10];
    rowW[i] = V[2] * m[12] + V[6] * m[13] + V[10] * m[14] + V[14];
  }
  rowX[WORLD_PART] = V[2]; rowY[WORLD_PART] = V[6]; rowZ[WORLD_PART] = V[10]; rowW[WORLD_PART] = V[14];   // world-space particles
  const count = geometry.instanceCount = ui.particles.checked ? N + NP : N;
  if (count > N) particleCenters(particleData, centers, N, time);
  let lo = 1e9, hi = -1e9;
  for (let i = 0, j = 0; i < count; i++, j += 3) {
    const p = partOf[i], z = rowX[p] * centers[j] + rowY[p] * centers[j + 1] + rowZ[p] * centers[j + 2] + rowW[p];
    depth[i] = z;
    if (z < lo) lo = z;
    if (z > hi) hi = z;
  }
  const scale = 65535 / (hi - lo || 1);
  counts.fill(0);
  for (let i = 0; i < count; i++) { const k = ((depth[i] - lo) * scale) | 0; keys[i] = k; counts[k + 1]++; }
  for (let i = 1; i <= 65536; i++) counts[i] += counts[i - 1];
  for (let i = 0; i < count; i++) order[counts[keys[i]]++] = i;
  geometry.attributes.aIndex.needsUpdate = true;
}

// ---------------------------------------------------------------- click to dissolve
const raycaster = new THREE.Raycaster(), inv = new THREE.Matrix4();
function pick(ndcX, ndcY) {
  raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);
  const o = raycaster.ray.origin, d = raycaster.ray.direction;
  const live = parts.filter((p) => p.pickable && p.prims.length).map((p) => ({ p, m: inv.copy(p.world).invert().elements.slice() }));
  for (let t = 0, i = 0; i < 160 && t < 80; i++) {
    const x = o.x + d.x * t, y = o.y + d.y * t, z = o.z + d.z * t;
    let best = 1e9, hit = null;
    for (const { p, m } of live) {
      const dd = p.sdf(m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]);
      if (dd < best) { best = dd; hit = p; }
    }
    if (best < 0.01) return hit;
    t += best;
  }
  return null;
}

let downAt = null;
renderer.domElement.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  const hit = pick(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  if (hit) for (const p of parts) if (p.group === hit.group) p.dissolveStart = performance.now() / 1000;
});

// 1 s burst, 0.8 s apart, 1.2 s reform
function dissolveAmount(now, start) {
  const u = now - start;
  if (u < 0 || u > 3) return 0;
  if (u < 1) return u;
  if (u < 1.8) return 1;
  return 1 - (u - 1.8) / 1.2;
}

// Scene wind: direction is normalised here, strength scales the lean of every part that has wind > 0.
if (cfg.wind) {
  const w = new THREE.Vector3(...cfg.wind.dir).normalize().multiplyScalar(cfg.wind.strength ?? 1);
  splatUniforms.uWind.value.set(w.x, w.y, w.z, cfg.wind.speed ?? 1);
}

// ---------------------------------------------------------------- live lights
// The scene's update(t, light) may move or recolour a light each frame. No lights are
// uploaded while the checkbox is off, and those beyond MAX_LIVE are never used.
const liveLights = (cfg.liveLights || []).slice(0, MAX_LIVE);
if ((cfg.liveLights || []).length > MAX_LIVE) console.warn(`scene has ${cfg.liveLights.length} liveLights, only the first ${MAX_LIVE} are used`);
function updateLiveLights() {
  const on = ui.live.checked;
  splatUniforms.uLLN.value = on ? liveLights.length : 0;
  if (!on) return;
  liveLights.forEach((L, i) => {
    if (L.update) L.update(time, L);
    splatUniforms.uLLPos.value[i].set(L.pos[0], L.pos[1], L.pos[2], L.power);
    splatUniforms.uLLCol.value[i].set(L.col[0], L.col[1], L.col[2], L.k);
  });
}

// ---------------------------------------------------------------- loop
function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  const rows = +ui.rows.value, cols = Math.round(rows * w / h);
  target.setSize(cols, rows);
  idTarget.setSize(cols, rows);
  postUniforms.uRes.value.set(cols, rows);
}
addEventListener('resize', resize);
ui.rows.addEventListener('input', resize);

let time = 0, last = performance.now(), fps = 60, frames = 0;
function frame(nowMs) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.1, (nowMs - last) / 1000);
  last = nowMs;
  if (ui.anim.checked) time += dt;
  fps = lerp(fps, 1 / Math.max(dt, 1e-3), 0.05);

  controls.autoRotate = ui.orbit.checked;
  controls.update();
  camera.updateMatrixWorld();
  updateParts(time);
  for (const p of parts) {
    const o = p.index * PART_W * 4;
    partBuf.set(p.world.elements, o);
    partBuf[o + 16] = dissolveAmount(nowMs / 1000, p.dissolveStart);
    partBuf[o + 17] = p.wobble; partBuf[o + 18] = p.opacity; partBuf[o + 19] = p.pulse;
    partBuf[o + 20] = p.fog; partBuf[o + 21] = p.rim; partBuf[o + 22] = p.wind; partBuf[o + 23] = p.outline ? 1 : 0;
  }
  partTex.needsUpdate = true;
  splatUniforms.uTime.value = time;
  updateLiveLights();
  splatUniforms.uSize.value = +ui.size.value;
  splatUniforms.uExplode.value = +ui.explode.value;
  splatUniforms.uBrush.value = +ui.brush.value;
  splatUniforms.uAniso.value.set(...(+ui.brush.value === 3 ? STROKE : [1, 1]));
  splatUniforms.uDof.value.set(ui.dof.checked ? 1 : 0, +ui.focus.value);
  sortSplats();

  if (ui.pixel.checked) {
    const outline = ui.outline.checked;
    postUniforms.uOutline.value = outline ? 1 : 0;
    if (outline) {
      renderer.setRenderTarget(idTarget);
      renderer.render(idScene, camera);
    }
    renderer.setRenderTarget(target);
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    renderer.render(postScene, postCamera);
  } else {
    renderer.render(scene, camera);
  }
  if (frames++ % 20 === 0) ui.hud.textContent = `${N.toLocaleString()} splats${NP ? ` + ${NP} particles` : ''} · ${parts.length} SDF parts\n${fps.toFixed(0)} fps · ${fromCache ? `cached, loaded in ${buildMs} ms` : `built in ${(buildMs / 1000).toFixed(1)} s`}\nDrag to orbit. Click an object to dissolve it.`;
}

if (parts.length > MAX_PARTS) throw new Error(`scene has ${parts.length} parts, limit is ${MAX_PARTS}`);
ui.focus.value = Math.round(camera.position.distanceTo(controls.target));
resize();
await build();
requestAnimationFrame(frame);
