// Scene description (SDF primitives grouped into rigid parts), surface sampling
// and light baking. No DOM here: this file runs on the page and in bake workers.
import * as THREE from './three.js';
export { THREE };

// ---------------------------------------------------------------- helpers
export const clamp = (x, a, b) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, t) => a + (b - a) * t;
export const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
export const hex = (h) => [(h >> 16 & 255) / 255, (h >> 8 & 255) / 255, (h & 255) / 255];
export const mix3 = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];

export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashCell(ix, iy, iz) {
  let n = Math.imul(ix, 374761393) ^ Math.imul(iy, 668265263) ^ Math.imul(iz, 1274126177);
  n = Math.imul(n ^ (n >>> 13), 1274126177);
  return ((n ^ (n >>> 16)) >>> 0) / 4294967295;
}

export function noise(x, y, z) {
  const ix = Math.floor(x), iy = Math.floor(y), iz = Math.floor(z);
  let fx = x - ix, fy = y - iy, fz = z - iz;
  fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy); fz = fz * fz * (3 - 2 * fz);
  const c = (a, b, d) => hashCell(ix + a, iy + b, iz + d);
  const x00 = lerp(c(0, 0, 0), c(1, 0, 0), fx), x10 = lerp(c(0, 1, 0), c(1, 1, 0), fx);
  const x01 = lerp(c(0, 0, 1), c(1, 0, 1), fx), x11 = lerp(c(0, 1, 1), c(1, 1, 1), fx);
  return lerp(lerp(x00, x10, fy), lerp(x01, x11, fy), fz);
}

export function fbm(x, y, z, octaves = 3) {
  let amp = 0.5, sum = 0, norm = 0;
  for (let i = 0; i < octaves; i++) {
    sum += amp * noise(x, y, z); norm += amp;
    x *= 2.03; y *= 2.03; z *= 2.03; amp *= 0.5;
  }
  return sum / norm;
}

// ---------------------------------------------------------------- SDF shapes
// Each returns { base(x,y,z), half:[hx,hy,hz] } in the shape's own space.
export const sphere = (r) => ({ base: (x, y, z) => Math.hypot(x, y, z) - r, half: [r, r, r] });

export const ellipsoid = (rx, ry, rz) => ({
  base: (x, y, z) => {
    const k0 = Math.hypot(x / rx, y / ry, z / rz);
    const k1 = Math.hypot(x / (rx * rx), y / (ry * ry), z / (rz * rz));
    return k1 < 1e-9 ? -Math.min(rx, ry, rz) : k0 * (k0 - 1) / k1;
  },
  half: [rx, ry, rz],
});

export const box = (hx, hy, hz, r = 0) => ({
  base: (x, y, z) => {
    const qx = Math.abs(x) - hx + r, qy = Math.abs(y) - hy + r, qz = Math.abs(z) - hz + r;
    return Math.hypot(Math.max(qx, 0), Math.max(qy, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qy, qz), 0) - r;
  },
  half: [hx, hy, hz],
});

export const cylinder = (r, h) => ({
  base: (x, y, z) => {
    const dx = Math.hypot(x, z) - r, dy = Math.abs(y) - h;
    return Math.min(Math.max(dx, dy), 0) + Math.hypot(Math.max(dx, 0), Math.max(dy, 0));
  },
  half: [r, h, r],
});

export const capsule = (r, h) => ({
  base: (x, y, z) => Math.hypot(x, y - clamp(y, -h, h), z) - r,
  half: [r, h + r, r],
});

// h = half height, r1 = bottom radius, r2 = top radius
export const cone = (h, r1, r2) => ({
  base: (x, y, z) => {
    const qx = Math.hypot(x, z);
    const k2x = r2 - r1, k2y = 2 * h;
    const cax = qx - Math.min(qx, y < 0 ? r1 : r2), cay = Math.abs(y) - h;
    const f = clamp(((r2 - qx) * k2x + (h - y) * k2y) / (k2x * k2x + k2y * k2y), 0, 1);
    const cbx = qx - r2 + k2x * f, cby = y - h + k2y * f;
    const s = cbx < 0 && cay < 0 ? -1 : 1;
    return s * Math.sqrt(Math.min(cax * cax + cay * cay, cbx * cbx + cby * cby));
  },
  half: [Math.max(r1, r2), h, Math.max(r1, r2)],
});

// Ring around the y axis. o.n / o.amp ribs the tube around its circumference.
export const torus = (R, r, o = {}) => {
  const n = o.n || 0, amp = o.amp || 0, big = r * (1 + amp);
  return {
    base: (x, y, z) => Math.hypot(Math.hypot(x, z) - R, y) - (n ? r * (1 + amp * Math.sin(n * Math.atan2(z, x))) : r),
    half: [R + big, big, R + big],
  };
};

// ---------------------------------------------------------------- primitives
function finish(sdf, min, max, o) {
  return {
    sdf, min, max,
    color: o.color || [1, 1, 1], colorFn: o.colorFn || null, tag: o.tag || '',
    emissive: o.emissive === true ? 1 : o.emissive || 0, // multiplier; emissive splats skip the light bake
  };
}

// Place a shape: o = { pos, rot:[x,y,z] euler, color, emissive, colorFn, tag }
export function prim(shape, o = {}) {
  const [px, py, pz] = o.pos || [0, 0, 0];
  const base = shape.base;
  let sdf, half = shape.half;
  if (o.rot) {
    const R = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(...o.rot)).elements;
    sdf = (x, y, z) => {
      x -= px; y -= py; z -= pz;
      return base(R[0] * x + R[1] * y + R[2] * z, R[4] * x + R[5] * y + R[6] * z, R[8] * x + R[9] * y + R[10] * z);
    };
    const r = Math.hypot(...half);
    half = [r, r, r];
  } else {
    sdf = (x, y, z) => base(x - px, y - py, z - pz);
  }
  return finish(sdf, [px - half[0], py - half[1], pz - half[2]], [px + half[0], py + half[1], pz + half[2]], o);
}

export const rawPrim = (sdf, min, max, o = {}) => finish(sdf, min, max, o);

// Tapered capsule from a to b. o.rib / o.freq / o.phase add rings along its length.
export function limb(a, b, r1, r2, o = {}) {
  const ax = a[0], ay = a[1], az = a[2], bx = b[0] - ax, by = b[1] - ay, bz = b[2] - az;
  const L2 = bx * bx + by * by + bz * bz || 1e-9, L = Math.sqrt(L2);
  const amp = o.rib || 0, freq = o.freq || 0, phase = o.phase || 0;
  const sdf = (x, y, z) => {
    const px = x - ax, py = y - ay, pz = z - az;
    const h = clamp((px * bx + py * by + pz * bz) / L2, 0, 1);
    let r = r1 + (r2 - r1) * h;
    if (amp) r *= 1 + amp * Math.sin((phase + h * L) * freq);
    return Math.hypot(px - bx * h, py - by * h, pz - bz * h) - r;
  };
  const R = Math.max(r1, r2) * (1 + Math.abs(amp));
  return finish(sdf,
    [Math.min(ax, b[0]) - R, Math.min(ay, b[1]) - R, Math.min(az, b[2]) - R],
    [Math.max(ax, b[0]) + R, Math.max(ay, b[1]) + R, Math.max(az, b[2]) + R], o);
}

// Chain of limbs through points, radius r1 -> r2 by arc length, rib phase continuous.
export function curve(pts, r1, r2, o = {}) {
  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1], pts[i][2] - pts[i - 1][2]));
  const total = cum[cum.length - 1] || 1, out = [];
  for (let i = 0; i < pts.length - 1; i++) {
    out.push(limb(pts[i], pts[i + 1], lerp(r1, r2, cum[i] / total), lerp(r1, r2, cum[i + 1] / total), { ...o, phase: cum[i] }));
  }
  return out;
}

// Catmull-Rom subdivision of a control polyline.
export function catmull(pts, sub = 2) {
  const out = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || pts[i + 1];
    for (let s = 0; s < sub; s++) {
      const t = s / sub, t2 = t * t, t3 = t2 * t;
      out.push([0, 1, 2].map((k) => 0.5 * (2 * p1[k] + (p2[k] - p0[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 + (3 * p1[k] - p0[k] - 3 * p2[k] + p3[k]) * t3)));
    }
  }
  out.push(pts[pts.length - 1]);
  return out;
}

// ---------------------------------------------------------------- parts (the rig)
export const SPLAT_FLOATS = 20;     // floats per baked splat, see sampleChunk
const SIZE = 0.026;               // default splat half-extent in world units
const STRETCH = [1.5, 0.75];        // brush stroke anisotropy
export const parts = [];
export const state = { cfg: null }; // scene config: lights, palette, camera...
let HIT = 0;                        // index of nearest primitive from the last part.sdf() call

export function addPart(o) {
  const p = {
    name: o.name, group: o.group || o.name, parent: o.parent || null,
    prims: o.prims, k: o.k || 0,
    size: o.size || SIZE, band: o.band || 0.05, coverage: o.coverage || 6,
    areaFrac: o.areaFrac || 1, count: o.count || 0, filter: o.filter || null, colorFn: o.colorFn || null,
    dynamic: !!o.dynamic, caster: o.caster !== false, pickable: o.pickable !== false,
    outline: o.outline ?? (o.fog ?? 1) !== 0, // fog 0 marks sky-like parts, which get no outline
    wind: o.wind || 0,
    wobble: o.wobble || 0, opacity: o.opacity ?? 1, pulse: o.pulse || 0, fog: o.fog ?? 1, rim: o.rim || 0,
    local: o.local || null,
    localM: new THREE.Matrix4(), world: new THREE.Matrix4(),
    index: parts.length, dissolveStart: -1e9,
  };
  if (o.matrix) p.localM.copy(o.matrix);

  const prims = p.prims, k = p.k, n = prims.length;
  const cx = new Float64Array(n), cy = new Float64Array(n), cz = new Float64Array(n), cr = new Float64Array(n);
  const pad = p.band + p.k;
  p.min = [1e9, 1e9, 1e9]; p.max = [-1e9, -1e9, -1e9];
  prims.forEach((q, i) => {
    cx[i] = (q.min[0] + q.max[0]) / 2; cy[i] = (q.min[1] + q.max[1]) / 2; cz[i] = (q.min[2] + q.max[2]) / 2;
    cr[i] = Math.hypot(q.max[0] - q.min[0], q.max[1] - q.min[1], q.max[2] - q.min[2]) / 2;
    for (let a = 0; a < 3; a++) {
      p.min[a] = Math.min(p.min[a], q.min[a] - pad);
      p.max[a] = Math.max(p.max[a], q.max[a] + pad);
    }
  });
  // Smooth union of the primitives, skipping any whose bounding sphere is too far to matter.
  p.sdf = (x, y, z) => {
    let d = 1e9, raw = 1e9, hit = 0;
    for (let i = 0; i < n; i++) {
      const ex = x - cx[i], ey = y - cy[i], ez = z - cz[i];
      if (Math.sqrt(ex * ex + ey * ey + ez * ez) - cr[i] > d + k) continue;
      const di = prims[i].sdf(x, y, z);
      if (di < raw) { raw = di; hit = i; }
      if (k > 0) {
        const h = clamp(0.5 + 0.5 * (d - di) / k, 0, 1);
        d = lerp(d, di, h) - k * h * (1 - h);
      } else if (di < d) d = di;
    }
    HIT = hit;
    return d;
  };
  p.center = [0, 1, 2].map((a) => (p.min[a] + p.max[a]) / 2);
  p.radius = Math.hypot(...[0, 1, 2].map((a) => (p.max[a] - p.min[a]) / 2));
  parts.push(p);
  return p;
}

export function updateParts(t) {
  for (const p of parts) {
    if (p.local) p.local(t, p.localM);
    if (p.parent) p.world.multiplyMatrices(p.parent.world, p.localM);
    else p.world.copy(p.localM);
  }
}

// ---------------------------------------------------------------- bake
let staticCasters = [];
const groupCasters = new Map();

// Freeze the t=0 pose. Baked light and shadows are computed against it.
export function finalizeRest() {
  // A light with no falloff or power bakes NaN into every splat it reaches.
  for (const L of state.cfg.lights) {
    if (!Number.isFinite(L.k) || !Number.isFinite(L.power)) throw new Error('Scene light needs numeric power and k');
  }
  updateParts(0);
  staticCasters = [];
  groupCasters.clear();
  for (const p of parts) {
    p.rest = p.world.clone();
    p.restInv = p.world.clone().invert().elements;
    if (!p.caster || !p.prims.length) continue;
    if (!p.dynamic) staticCasters.push(p);
    else {
      if (!groupCasters.has(p.group)) groupCasters.set(p.group, []);
      groupCasters.get(p.group).push(p);
    }
  }
}

function nearest(list, x, y, z, best) {
  for (let i = 0; i < list.length; i++) {
    const p = list[i], m = p.restInv;
    const lx = m[0] * x + m[4] * y + m[8] * z + m[12];
    const ly = m[1] * x + m[5] * y + m[9] * z + m[13];
    const lz = m[2] * x + m[6] * y + m[10] * z + m[14];
    if (Math.hypot(lx - p.center[0], ly - p.center[1], lz - p.center[2]) - p.radius > best) continue;
    const d = p.sdf(lx, ly, lz);
    if (d < best) best = d;
  }
  return best;
}

// Distance to the rest-pose scene. Moving groups only shade themselves.
function sceneSDF(x, y, z, group) {
  const best = nearest(staticCasters, x, y, z, 1e9);
  const own = groupCasters.get(group);
  return own ? nearest(own, x, y, z, best) : best;
}

function softShadow(x, y, z, dx, dy, dz, maxT, group) {
  let res = 1, t = 0.06;
  for (let i = 0; i < 28 && t < maxT; i++) {
    const h = sceneSDF(x + dx * t, y + dy * t, z + dz * t, group);
    if (h < 0.003) return 0;
    res = Math.min(res, 9 * h / t);
    t += clamp(h, 0.04, 0.7);
  }
  return res;
}

function randomIn(p, rng) {
  return [lerp(p.min[0], p.max[0], rng()), lerp(p.min[1], p.max[1], rng()), lerp(p.min[2], p.max[2], rng())];
}

// How many splats a part gets: surface area (estimated from the fraction of
// its box lying in a thin shell around the surface) times coverage.
function planPart(p) {
  if (!p.prims.length) return 0;
  if (p.count) return p.count;
  const rng = mulberry32(1000 + p.index), probes = 4000;
  let inShell = 0;
  for (let i = 0; i < probes; i++) { const q = randomIn(p, rng); if (Math.abs(p.sdf(q[0], q[1], q[2])) < p.band) inShell++; }
  const vol = (p.max[0] - p.min[0]) * (p.max[1] - p.min[1]) * (p.max[2] - p.min[2]);
  const area = Math.max(inShell, 1) / probes * vol / (2 * p.band) * p.areaFrac;
  return Math.round(p.coverage * area / (4 * p.size * p.size * STRETCH[0] * STRETCH[1]));
}

export function planTasks(chunk = 3000) {
  const tasks = [];
  for (const p of parts) {
    for (let c = 0, left = planPart(p); left > 0; c++, left -= chunk) {
      tasks.push({ id: tasks.length, part: p.index, count: Math.min(chunk, left), seed: (p.index + 1) * 7919 + c * 104729 });
    }
  }
  return tasks;
}

// Generate `count` splats on a part's surface, SPLAT_FLOATS each, appended to out:
// centre.xyz part | normal.xyz seed | tangent.xyz sizeX | colour.rgb sizeY | albedo.rgb kind
// colour is the baked lit colour; albedo is the same surface before lighting, so live
// lights can add to it. kind: 0 lit surface, 1 emissive (never live-lit).
export function sampleChunk(p, count, rng, out) {
  const { sun, sky, ground: gnd, lights, aoMin } = state.cfg;
  const W = p.rest.elements, e = 0.0015, g = [0, 0, 0], band = p.band;
  const grad = (x, y, z) => {
    g[0] = p.sdf(x + e, y, z) - p.sdf(x - e, y, z);
    g[1] = p.sdf(x, y + e, z) - p.sdf(x, y - e, z);
    g[2] = p.sdf(x, y, z + e) - p.sdf(x, y, z - e);
    const l = Math.hypot(g[0], g[1], g[2]) || 1;
    g[0] /= l; g[1] /= l; g[2] /= l;
  };

  for (let made = 0, tries = 0; made < count && tries < count * 3000; tries++) {
    let [x, y, z] = randomIn(p, rng);
    let d = p.sdf(x, y, z);
    if (Math.abs(d) >= band) continue;
    for (let i = 0; i < 4; i++) { grad(x, y, z); x -= g[0] * d; y -= g[1] * d; z -= g[2] * d; d = p.sdf(x, y, z); }
    if (Math.abs(d) > 0.003) continue;
    const q = p.prims[HIT];
    grad(x, y, z);
    const n = [g[0], g[1], g[2]], lp = [x, y, z];
    if (p.filter && !p.filter(lp, n)) continue;

    // brush direction: roughly horizontal along the surface, with jitter
    let tx, ty, tz;
    if (Math.abs(n[1]) < 0.95) { tx = n[2]; ty = 0; tz = -n[0]; } else { tx = 0; ty = n[2]; tz = -n[1]; }
    const l = Math.hypot(tx, ty, tz); tx /= l; ty /= l; tz /= l;
    const bx = n[1] * tz - n[2] * ty, by = n[2] * tx - n[0] * tz, bz = n[0] * ty - n[1] * tx;
    const a = (rng() - 0.5) * 1.2, ca = Math.cos(a), sa = Math.sin(a);
    tx = tx * ca + bx * sa; ty = ty * ca + by * sa; tz = tz * ca + bz * sa;

    let col = p.colorFn ? p.colorFn(lp, n, q, rng) : q.colorFn ? q.colorFn(lp, n, q, rng) : q.color;
    let albedo = col, kind = 0;
    if (q.emissive) {
      col = albedo = [col[0] * q.emissive, col[1] * q.emissive, col[2] * q.emissive];
      kind = 1;
    } else {
      const wx = W[0] * x + W[4] * y + W[8] * z + W[12], wy = W[1] * x + W[5] * y + W[9] * z + W[13], wz = W[2] * x + W[6] * y + W[10] * z + W[14];
      const nx = W[0] * n[0] + W[4] * n[1] + W[8] * n[2], ny = W[1] * n[0] + W[5] * n[1] + W[9] * n[2], nz = W[2] * n[0] + W[6] * n[1] + W[10] * n[2];
      const ox = wx + nx * 0.02, oy = wy + ny * 0.02, oz = wz + nz * 0.02;
      const ao = aoMin + (1 - aoMin) * clamp(sceneSDF(wx + nx * 0.15, wy + ny * 0.15, wz + nz * 0.15, p.group) / 0.15, 0, 1);
      const hemi = (0.5 + 0.5 * ny);
      let lr = lerp(gnd[0], sky[0], hemi) * ao, lg = lerp(gnd[1], sky[1], hemi) * ao, lb = lerp(gnd[2], sky[2], hemi) * ao;

      const ndl = nx * sun.dir[0] + ny * sun.dir[1] + nz * sun.dir[2];
      if (ndl > 0) {
        const s = ndl * softShadow(ox, oy, oz, sun.dir[0], sun.dir[1], sun.dir[2], sun.reach, p.group);
        lr += sun.col[0] * s; lg += sun.col[1] * s; lb += sun.col[2] * s;
      }
      for (const L of lights) {
        const dx = L.pos[0] - wx, dy = L.pos[1] - wy, dz = L.pos[2] - wz, dist = Math.hypot(dx, dy, dz);
        let s = L.power * Math.max(0, (nx * dx + ny * dy + nz * dz) / dist) / (1 + L.k * dist * dist);
        if (s < 0.004) continue;
        if (L.shadow) s *= softShadow(ox, oy, oz, dx / dist, dy / dist, dz / dist, dist - (L.radius || 0), p.group);
        lr += L.col[0] * s; lg += L.col[1] * s; lb += L.col[2] * s;
      }
      const j = 0.88 + 0.24 * rng();
      albedo = [col[0] * j, col[1] * j, col[2] * j];
      col = [albedo[0] * lr, albedo[1] * lg, albedo[2] * lb];
    }
    const s = p.size * (0.8 + 0.4 * rng());
    out.push(x, y, z, p.index, n[0], n[1], n[2], rng() * 1000, tx, ty, tz, s * STRETCH[0], col[0], col[1], col[2], s * STRETCH[1], albedo[0], albedo[1], albedo[2], kind);
    made++;
  }
}
