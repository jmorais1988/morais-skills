// Sunlit shallow coral reef: a bright, saturated diorama slice, the opposite of the
// horror scene. Warm key light with shadows, turquoise ambient, rippled sand, brain
// and staghorn corals, tube sponges, swaying fans and kelp, an anemone, a giant clam,
// a school of fish and a turtle on a loop, with bubbles, motes and light shafts.
import {
  THREE, prim, sphere, ellipsoid, box, cone, limb, rawPrim,
  addPart, noise, fbm, mix3, hex, lerp, smooth, clamp, mulberry32,
} from '../engine.js';

const TAU = Math.PI * 2;
const add = (a, b, s = 1) => [a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s];
const norm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

export default function build() {
  // Ramps: water, sand, pink, orange/yellow, purple, green, brain-coral teal, shadow
  // blue and fish blue, turtle brown, then the exact emissive colours.
  const C = {
    w0: hex(0x06323f), w1: hex(0x0d5a6e), w2: hex(0x1b8fa0), w25: hex(0x2aa8b4), w3: hex(0x3cc4c4), w4: hex(0x9ff0e2),
    s0: hex(0x3b4b5c), s1: hex(0x8f8a76), s15: hex(0xb8a982), s2: hex(0xd6c18e), s25: hex(0xeadaa4), s3: hex(0xf6e8b8),
    p0: hex(0x6e1c4f), p05: hex(0x93385f), p1: hex(0xc03c78), p2: hex(0xff6f96), p25: hex(0xd68fa4), p3: hex(0xffb4c0),
    o0: hex(0xb84a1e), o1: hex(0xff8a2a), o2: hex(0xffc84c), y1: hex(0xfff06a),
    u0: hex(0x35286b), u1: hex(0x7b52c8), u15: hex(0x9c86c4), u2: hex(0xb890f0),
    g0: hex(0x174f3a), g1: hex(0x35974a), g2: hex(0x8fd24e),
    c0: hex(0x24605a), c1: hex(0x58b58e),
    b0: hex(0x12284a), f0: hex(0x2d62dc), f1: hex(0x56b4ff), t0: hex(0x6a4a28),
    white: hex(0xfff3dc), glow: hex(0x5affd6), glow2: hex(0xff5ed0),
  };
  // Albedos that never survive lighting as themselves; the palette holds their lit results instead.
  const ALBEDO_ONLY = new Set(['w1', 'p1', 'p2', 'o0', 'f0']);
  const e = new THREE.Euler();
  // Small critters are lit at about 0.6, so their albedo goes above 1 to stay bright.
  const hot = (c, k = 1.6) => [c[0] * k, c[1] * k, c[2] * k];

  // ---------------------------------------------------------------- sand
  // Ripples plus broad mounds, dipping away at the rim so the diorama has an edge.
  const R_SAND = 9.4, G = 257, EXT = 9.6, hm = new Float32Array(G * G);
  const ripple = (x, z) => Math.sin(x * 2.1 + z * 1.3 + 2.2 * fbm(x * 0.4 + 5, 0, z * 0.4));
  const hRaw = (x, z) => 0.045 * ripple(x, z) + 0.4 * (fbm(x * 0.3 + 2, 3, z * 0.3 - 4) - 0.5) - 1.4 * smooth(7.2, R_SAND, Math.hypot(x, z));
  for (let j = 0; j < G; j++) for (let i = 0; i < G; i++) hm[j * G + i] = hRaw(-EXT + i / (G - 1) * 2 * EXT, -EXT + j / (G - 1) * 2 * EXT);
  const gh = (x, z) => {
    const u = clamp((x + EXT) / (2 * EXT) * (G - 1), 0, G - 1.001), v = clamp((z + EXT) / (2 * EXT) * (G - 1), 0, G - 1.001);
    const i = u | 0, j = v | 0, o = j * G + i;
    return lerp(lerp(hm[o], hm[o + 1], u - i), lerp(hm[o + G], hm[o + G + 1], u - i), v - j);
  };
  const at = (x, z, yaw = 0, dy = 0) => new THREE.Matrix4().makeRotationY(yaw).setPosition(x, gh(x, z) + dy, z);

  addPart({
    // Seen at a low angle, so it needs coverage 3.5: at 2 the background shows through as specks.
    name: 'sand', size: 0.07, coverage: 3.5, caster: false,
    prims: [rawPrim((x, y, z) => Math.max((y - gh(x, z)) * 0.75, Math.hypot(x, z) - R_SAND), [-R_SAND, -2.5, -R_SAND], [R_SAND, 1, R_SAND])],
    filter: (p, n) => n[1] > 0.25,
    colorFn: (p) => {
      const grain = noise(p[0] * 7, 0, p[2] * 7);
      const crest = ripple(p[0], p[2]) * 0.5 + 0.5;
      let c = mix3(mix3(C.s1, C.s2, 0.25 + 0.5 * crest), C.s3, smooth(0.7, 0.95, crest * 0.6 + grain * 0.4));
      // Caustic web: bright where two noise fields cross zero.
      const web = Math.abs(noise(p[0] * 1.5, 1, p[2] * 1.5) - 0.5) + Math.abs(noise(p[0] * 1.5 + 9, 2, p[2] * 1.5) - 0.5);
      c = mix3(c, C.s3, smooth(0.09, 0.0, web) * 0.8);
      // Darken toward the rim instead of blending to a blue: midtones between sand and
      // blue snap to teal and speckle the floor.
      const f = 0.92 * (1 - 0.45 * smooth(6.3, 8.8, Math.hypot(p[0], p[2])));
      return [c[0] * f, c[1] * f, c[2] * f];
    },
  });

  // ---------------------------------------------------------------- brain corals
  // Domes cut with winding grooves: the groove field is noise near its 0.5 contour.
  [
    { x: -4.2, z: 1.2, R: 0.95, h: 0.6, dark: C.c0, light: C.c1, seed: 1.3 },
    { x: -2.4, z: 3.3, R: 0.8, h: 0.5, dark: C.o0, light: C.o1, seed: 7.9 },
    { x: 1.7, z: -0.9, R: 0.85, h: 0.55, dark: C.u0, light: C.u2, seed: 4.1 },
  ].forEach((b, i) => {
    const dome = ellipsoid(b.R, b.h, b.R);
    const ridge = (x, y, z) => smooth(0.07, 0, Math.abs(noise(x * 3.4 + b.seed, y * 3.4, z * 3.4) - 0.5));
    addPart({
      name: 'brain' + i, matrix: at(b.x, b.z, 0, -0.12), k: 0.02, size: 0.028, band: 0.03, coverage: 3, areaFrac: 0.6,
      prims: [rawPrim((x, y, z) => dome.base(x, y, z) + 0.032 * ridge(x, y, z), [-b.R, -b.h, -b.R], [b.R, b.h + 0.05, b.R])],
      filter: (p) => p[1] > 0.02,
      colorFn: (p) => {
        const r = ridge(p[0], p[1], p[2]);
        return mix3(b.light, b.dark, r * 0.9);
      },
    });
  });

  // ---------------------------------------------------------------- staghorn coral
  // Three trunks, each branching four levels deep with seeded randomness.
  function staghorn(name, x, z, scale, seed, lo, mid, tipA, tipB) {
    const r = mulberry32(seed), prims = [];
    const grow = (base, dir, len, rad, depth) => {
      prims.push(limb(base, add(base, dir, len), rad, rad * 0.8, { tag: depth >= 3 ? 'tip' : 'br' }));
      if (depth >= 3) return;
      for (let k = 0; k < (depth === 0 ? 4 : 2); k++) {
        const from = add(base, dir, len * (k === 0 ? 1 : 0.5 + 0.4 * r())), s = depth === 0 ? 0.55 : 0.8;
        grow(from, norm([dir[0] + (r() - 0.5) * 2 * s, dir[1] + 0.35, dir[2] + (r() - 0.5) * 2 * s]), len * 0.74, rad * 0.74, depth + 1);
      }
    };
    for (let b = 0; b < 3; b++) {
      const a = b / 3 * TAU + seed;
      grow([0.25 * scale * Math.cos(a), -0.05, 0.25 * scale * Math.sin(a)], norm([Math.cos(a) * 0.5, 1, Math.sin(a) * 0.5]), 0.9 * scale, 0.14 * scale, 0);
    }
    addPart({
      name, matrix: at(x, z, seed), k: 0.05, size: 0.022, band: 0.025, coverage: 2.5, prims,
      colorFn: (p, n, q) => {
        const g = noise(p[0] * 9, p[1] * 9, p[2] * 9);
        if (q.tag === 'tip') return mix3(tipA, tipB, g);
        return hot(mix3(lo, mid, clamp(p[1] / (2.2 * scale) + 0.35 * g, 0, 1)), 1.25);
      },
    });
  }
  staghorn('stag0', -2.6, -0.6, 1.3, 11, C.o0, C.o1, C.o2, C.y1);
  staghorn('stag1', 4.9, -2.7, 0.7, 23, C.u0, C.u1, C.u2, C.p3);
  staghorn('stag2', -1.3, 4.7, 0.42, 31, C.p0, C.p2, C.p25, C.p3);
  staghorn('stag3', 3.3, 4.3, 0.38, 41, C.o0, C.o1, C.o2, C.y1);

  // ---------------------------------------------------------------- tube sponges
  // Open-topped tubes: a cylinder minus a bore from the top.
  const tubeSdf = (cx, cy, cz, r, hh) => (x, y, z) => {
    const q = Math.hypot(x - cx, z - cz);
    const outer = Math.max(q - r, Math.abs(y - cy) - hh);
    const bore = Math.max(q - r * 0.62, (cy + hh - 0.7) - y);
    return Math.max(outer, -bore);
  };
  function sponges(name, x, z, list, lo, mid, hi) {
    const prims = list.map(([dx, dz, h, r]) => rawPrim(tubeSdf(dx, (h - 0.15) / 2, dz, r, (h + 0.15) / 2), [dx - r - 0.05, -0.2, dz - r - 0.05], [dx + r + 0.05, h + 0.05, dz + r + 0.05]));
    addPart({
      name, matrix: at(x, z, 0, -0.05), size: 0.02, band: 0.03, coverage: 2.5, prims,
      colorFn: (p) => {
        const g = noise(p[0] * 10, p[1] * 6, p[2] * 10);
        for (const [dx, dz, h, r] of list) {
          if (Math.hypot(p[0] - dx, p[2] - dz) < r * 0.7 && p[1] > h - 0.66) return mix3(C.b0, lo, g * 0.6);
          if (p[1] > h - 0.06 && Math.hypot(p[0] - dx, p[2] - dz) < r * 1.05) return mix3(mid, hi, g);
        }
        return mix3(mix3(lo, mid, g), hi, smooth(0.5, 1.3, p[1]) * 0.5);
      },
    });
  }
  sponges('sponge0', -5.4, 0.1, [[0, 0, 1.5, 0.3], [0.55, 0.2, 1.0, 0.26], [-0.45, 0.35, 0.75, 0.22], [0.2, -0.5, 1.2, 0.24], [0.9, -0.3, 0.55, 0.18]], C.u0, C.u1, C.u2);
  sponges('sponge1', 0.9, -2.8, [[0, 0, 1.1, 0.27], [0.5, 0.1, 0.8, 0.22], [-0.45, 0.15, 0.6, 0.2]], C.p0, C.p1, C.p3);

  // ---------------------------------------------------------------- fan corals
  // A thin elliptical plate with a lattice of holes; it sways on its stalk.
  [
    { x: -0.6, z: -4.2, w: 1.1, h: 1.7, yaw: 0.25, lo: C.p1, hi: C.p3, ph: 0.0 },
    { x: 2.9, z: -4.4, w: 0.85, h: 1.4, yaw: -0.3, lo: C.u1, hi: C.u2, ph: 1.9 },
    { x: -4.6, z: -3.4, w: 0.95, h: 1.5, yaw: 0.5, lo: C.u1, hi: C.p2, ph: 3.4 },
    { x: 5.6, z: -3.5, w: 0.8, h: 1.3, yaw: -0.5, lo: C.p1, hi: C.o2, ph: 5.0 },
  ].forEach((f, i) => {
    const plate = ellipsoid(f.w, f.h * 0.5, 0.045), M = at(f.x, f.z, f.yaw, -0.08), base = M.clone();
    addPart({
      name: 'fan' + i, dynamic: true, size: 0.02, band: 0.012, coverage: 3,
      prims: [
        rawPrim((x, y, z) => Math.max(plate.base(x, y - f.h * 0.55, z), (Math.abs(Math.sin(x * 12) * Math.sin(y * 12)) - 0.42) * 0.05), [-f.w, 0, -0.06], [f.w, f.h * 1.05, 0.06]),
        limb([0, -0.05, 0], [0, f.h * 0.15, 0], 0.07, 0.05),
      ],
      colorFn: (p) => mix3(f.lo, f.hi, smooth(0.1, f.h, p[1]) * 0.8 + 0.2 * noise(p[0] * 8, p[1] * 8, 0)),
      local: (t, m) => {
        e.set(0.03 * Math.sin(t * 0.9 + f.ph), f.yaw, 0.09 * Math.sin(t * 0.7 + f.ph * 1.3), 'YXZ');
        m.makeRotationFromEuler(e).setPosition(base.elements[12], base.elements[13], base.elements[14]);
      },
    });
  });

  // ---------------------------------------------------------------- anemone
  // A stout column and crown, with a ring of tentacles: chains of three rigid segments,
  // each a child of the one below, waving on travelling sine waves. Glowing tips.
  const AX = 3.3, AZ = 0.9, AY = gh(AX, AZ), CROWN = [AX, AY + 0.62, AZ];
  addPart({
    name: 'anemone', matrix: at(AX, AZ, 0, -0.05), k: 0.1, size: 0.02, band: 0.03, coverage: 3,
    prims: [
      prim(ellipsoid(0.42, 0.55, 0.42), { pos: [0, 0.35, 0], tag: 'col' }),
      prim(ellipsoid(0.62, 0.14, 0.62), { pos: [0, 0.7, 0], tag: 'crown' }),
      prim(ellipsoid(0.2, 0.08, 0.2), { pos: [0, 0.8, 0], tag: 'mouth' }),
    ],
    colorFn: (p, n, q) => (q.tag === 'mouth' ? C.p0 : mix3(C.o1, C.p2, smooth(0.0, 0.8, p[1]) * 0.8 + 0.2 * noise(p[0] * 9, p[1] * 9, p[2] * 9))),
  });
  for (let i = 0; i < 9; i++) {
    const th = i / 9 * TAU, phi = Math.PI / 2 - th, ph = i * 0.9, root = [AX + 0.46 * Math.cos(th), CROWN[1] + 0.02, AZ + 0.46 * Math.sin(th)];
    let parent = null, below = 0;
    for (let k = 0; k < 3; k++) {
      const L = 0.42 - 0.07 * k, r1 = 0.07 - 0.015 * k, r2 = r1 - 0.012, up = below, top = k === 2;
      const prims = [limb([0, 0, 0], [0, L, 0], r1, r2, { rib: 0.1, freq: 40 })];
      if (top) prims.push(prim(sphere(0.055), { pos: [0, L + 0.03, 0], color: i % 2 ? C.glow : C.glow2, emissive: 1, tag: 'tip' }));
      parent = addPart({
        name: `anem${i}_${k}`, group: 'anem' + i, parent, dynamic: true, size: 0.014, band: 0.016, coverage: 3, rim: 0.6, prims,
        colorFn: (p, n, q) => (q.tag === 'tip' ? q.color : mix3(C.p2, C.p3, smooth(0, 0.4, p[1]) * 0.6 + 0.4 * noise(p[0] * 30, p[1] * 12, p[2] * 30))),
        local: (t, m) => {
          const bend = (k === 0 ? 0.55 : 0.28) + 0.28 * Math.sin(t * 1.1 + ph - k * 0.8), sway = 0.22 * Math.sin(t * 0.8 + ph * 1.7 + k);
          if (k === 0) { e.set(bend, phi, sway, 'YXZ'); m.makeRotationFromEuler(e).setPosition(...root); } else { e.set(bend, 0, sway, 'XYZ'); m.makeRotationFromEuler(e).setPosition(0, up, 0); }
        },
      });
      below = L;
    }
  }

  // ---------------------------------------------------------------- giant clam
  // Fluted shells and a glossy mantle. The upper shell is a dynamic child on a hinge.
  const CX = 0.1, CZ = 1.9, CY = gh(CX, CZ) + 0.32;
  const shell = ellipsoid(1.15, 0.6, 0.85);
  const flute = (x, z) => 0.045 * Math.sin(Math.atan2(z, x) * 11);
  const lower = addPart({
    name: 'clam', matrix: at(CX, CZ, 0.35, 0.32), k: 0.06, size: 0.022, band: 0.03, coverage: 2.5,
    prims: [
      rawPrim((x, y, z) => Math.max(shell.base(x, y, z) + flute(x, z), -(shell.base(x / 0.88, (y - 0.12) / 0.88, z / 0.85)) * 0.85, y - 0.34), [-1.2, -0.65, -0.9], [1.2, 0.4, 0.9], { tag: 'shell' }),
      prim(ellipsoid(0.95, 0.13, 0.66), { pos: [0, 0.2, 0.02], tag: 'mantle' }),
    ],
    colorFn: (p, n, q) => {
      const g = noise(p[0] * 5, p[1] * 5, p[2] * 5);
      if (q.tag === 'mantle') return noise(p[0] * 9, 3, p[2] * 9) > 0.66 ? C.glow : mix3(C.f1, mix3(C.u1, C.c1, g), smooth(0.2, 0.8, g));
      return mix3(mix3(C.s1, C.white, g), C.s0, smooth(0.05, -0.5, p[1]) * 0.6);
    },
  });
  addPart({
    name: 'clamTop', parent: lower, dynamic: true, k: 0.06, size: 0.022, band: 0.03, coverage: 2.5,
    prims: [rawPrim((x, y, z) => Math.max(shell.base(x, y, z - 0.78) + flute(x, z - 0.78), -(shell.base(x / 0.88, y / 0.88, (z - 0.78) / 0.85)) * 0.85, -y), [-1.2, -0.05, -0.1], [1.2, 0.65, 1.7])],
    colorFn: (p, n) => {
      const g = noise(p[0] * 5, p[1] * 5, p[2] * 5);
      return n[1] < -0.2 ? (noise(p[0] * 8, 5, p[2] * 8) > 0.7 ? C.glow : mix3(C.u2, C.white, smooth(0.3, 0.7, g))) : mix3(mix3(C.s1, C.white, g), C.c0, smooth(0.15, 0.6, noise(p[0] * 3, 8, p[2] * 3)) * 0.5);
    },
    local: (t, m) => m.makeRotationX(-(0.42 + 0.34 * Math.sin(t * 0.5))).setPosition(0, 0.34, -0.78),
  });

  // ---------------------------------------------------------------- fish school
  // Twelve rigid fish on tilted circles, heading along their path.
  for (let i = 0; i < 12; i++) {
    const r = mulberry32(300 + i), a0 = i / 12 * TAU, rad = 1.3 + 0.4 * r(), y0 = 3.6 + 0.5 * r(), spd = 0.55 + 0.08 * r(), blue = i % 6 === 5, bob = r() * TAU;
    const [lo, hi, st] = (blue ? [C.f1, C.w4, C.white] : [C.o1, C.o2, C.white]).map((c) => hot(c, 1.3));
    addPart({
      name: 'fish' + i, dynamic: true, size: 0.013, band: 0.012, coverage: 3, rim: 0.4,
      prims: [
        prim(ellipsoid(0.09, 0.13, 0.29), { tag: 'body' }),
        prim(box(0.016, 0.1, 0.07, 0.01), { pos: [0, 0, -0.33], tag: 'fin' }),
        prim(box(0.016, 0.06, 0.08, 0.01), { pos: [0, 0.14, -0.05], tag: 'fin' }),
      ],
      colorFn: (p, n, q) => {
        if (q.tag === 'fin') return hot(C.o2, 1.5);
        if (!blue && Math.sin(p[2] * 26) > 0.7) return st;
        return mix3(lo, hi, smooth(-0.08, 0.08, -p[1] + 0.02));
      },
      local: (t, m) => {
        const a = a0 + t * spd;
        e.set(0.06 * Math.sin(t * 3 + bob), -a, 0, 'YXZ');
        m.makeRotationFromEuler(e).setPosition(4.6 + rad * Math.cos(a), y0 + 0.25 * Math.sin(a * 2 + bob), 0.2 + rad * Math.sin(a));
      },
    });
  }

  // ---------------------------------------------------------------- turtle
  // Loops round the reef on a wide ellipse; four flippers flap as child parts.
  {
    const T = 1.5, small = { dynamic: true, size: 0.02, band: 0.025, coverage: 3, rim: 0.3 }, PX = 5, PZ = 3.2;
    const body = addPart({
      name: 'turtle', ...small, k: 0.05,
      prims: [
        prim(ellipsoid(0.5 * T, 0.2 * T, 0.68 * T), { tag: 'shell' }),
        prim(ellipsoid(0.38 * T, 0.1 * T, 0.58 * T), { pos: [0, -0.12 * T, 0], tag: 'belly' }),
        prim(sphere(0.14 * T), { pos: [0, 0, 0.84 * T], tag: 'skin' }),
        limb([0, 0, 0.55 * T], [0, 0, 0.8 * T], 0.1 * T, 0.09 * T, { tag: 'skin' }),
        prim(cone(0.14 * T, 0.07 * T, 0.01), { pos: [0, -0.02 * T, -0.82 * T], rot: [-Math.PI / 2, 0, 0], tag: 'skin' }),
      ],
      colorFn: (p, n, q) => {
        if (q.tag === 'belly') return mix3(C.s2, C.s3, noise(p[0] * 6, 0, p[2] * 6));
        if (q.tag === 'skin') return hot(mix3(C.g1, C.t0, noise(p[0] * 12, p[1] * 12, p[2] * 12)), 1.4);
        const cell = noise(Math.floor(p[0] * 4.2), 0, Math.floor(p[2] * 4.2));
        return hot(cell > 0.6 ? C.g2 : cell > 0.3 ? C.g1 : C.t0, 1.3);
      },
      local: (t, m) => {
        const a = t * 0.26 + 1.2, y = 3.3 + 0.3 * Math.sin(t * 0.8);
        e.set(0.1 * Math.sin(t * 0.8), Math.atan2(-PX * Math.sin(a), PZ * Math.cos(a)), 0.12 * Math.sin(t * 0.8 + 1), 'YXZ');
        m.makeRotationFromEuler(e).setPosition(PX * Math.cos(a), y, 0.2 + PZ * Math.sin(a));
      },
    });
    [[1, 0, 0.8, 0.12, 0.3], [-1, 0, 0.8, 0.12, 0.3], [1, 1, 0.45, 0.09, -0.45], [-1, 1, 0.45, 0.09, -0.45]].forEach(([s, rear, len0, w0, pz]) => {
      const len = len0 * T, w = w0 * T;
      addPart({
        name: `flipper${s}${rear}`, ...small, parent: body, group: 'turtle', size: 0.018, band: 0.014,
        prims: [limb([0, 0, 0], [s * len, -0.06, -0.2 * len], 0.07 * T, 0.035 * T, { tag: 'fl' }), prim(ellipsoid(len * 0.4, 0.018, w), { pos: [s * len * 0.7, -0.07, -0.15 * len], rot: [0, 0.3 * s, 0], tag: 'fl' })],
        colorFn: (p) => hot(mix3(C.g1, C.t0, noise(p[0] * 10, p[1] * 10, p[2] * 10)), 1.4),
        local: (t, m) => m.makeRotationZ(-s * 0.5 * Math.sin(t * 2.4 + rear * 1.2)).setPosition(s * 0.4 * T, -0.04 * T, pz * T),
      });
    });
  }

  // ---------------------------------------------------------------- kelp and sea grass
  [[-6.3, -2.4, 0.0], [-5.6, -3.6, 1.4], [6.2, -3.0, 2.8], [6.8, -1.2, 4.2]].forEach(([x, z, ph], i) => {
    const y = gh(x, z) - 0.05;
    let parent = null, below = 0;
    for (let k = 0; k < 3; k++) {
      const L = 1.15, up = below;
      parent = addPart({
        name: `kelp${i}_${k}`, group: 'kelp' + i, parent, dynamic: true, size: 0.02, band: 0.02, coverage: 3,
        prims: [
          limb([0, 0, 0], [0, L, 0], 0.075, 0.06, { tag: 'stalk' }),
          prim(ellipsoid(0.3, 0.025, 0.1), { pos: [0.24, L * 0.45, 0], rot: [0, 0, 0.5], tag: 'leaf' }),
          prim(ellipsoid(0.3, 0.025, 0.1), { pos: [-0.24, L * 0.8, 0], rot: [0, 0, -0.5], tag: 'leaf' }),
        ],
        colorFn: (p, n, q) => mix3(q.tag === 'leaf' ? C.g2 : C.g1, C.g0, noise(p[0] * 7, p[1] * 7, p[2] * 7) * 0.7),
        local: (t, m) => {
          const bend = 0.12 + 0.16 * Math.sin(t * 0.8 + ph - k * 0.9), sway = 0.12 * Math.sin(t * 0.6 + ph + k);
          if (k === 0) { e.set(bend, 0, sway, 'XYZ'); m.makeRotationFromEuler(e).setPosition(x, y, z); } else { e.set(bend, 0, sway, 'XYZ'); m.makeRotationFromEuler(e).setPosition(0, up, 0); }
        },
      });
      below = L;
    }
  });
  [[-3.6, 4.3, 0.5], [4.4, 3.6, 2.3], [-6.4, 3.1, 4.0]].forEach(([x, z, ph], i) => {
    const r = mulberry32(900 + i), y = gh(x, z), prims = [];
    for (let j = 0; j < 22; j++) {
      const bx = (r() - 0.5) * 0.9, bz = (r() - 0.5) * 0.9, h = 0.6 + 0.6 * r();
      prims.push(limb([bx, -0.05, bz], [bx + (r() - 0.5) * 0.4, h, bz + (r() - 0.5) * 0.4], 0.032, 0.014));
    }
    addPart({
      name: 'grass' + i, dynamic: true, size: 0.019, band: 0.012, coverage: 3, prims,
      colorFn: (p) => mix3(C.g0, C.g2, smooth(0, 1.1, p[1]) * 0.9 + 0.1 * noise(p[0] * 20, 0, p[2] * 20)),
      local: (t, m) => m.makeRotationZ(0.07 * Math.sin(t * 1.2 + ph)).setPosition(x, y, z),
    });
  });

  // ---------------------------------------------------------------- rocks, urchins, starfish
  {
    const r = mulberry32(555), prims = [];
    for (let i = 0; i < 14; i++) {
      const a = Math.PI * (0.08 + 0.84 * r()) + Math.PI, rr = 5.5 + 2.6 * r(), x = rr * Math.cos(a) * 1.1, z = rr * Math.sin(a) * 0.9, s = 0.35 + 0.6 * r();
      prims.push(prim(ellipsoid(s, s * 0.7, s * 0.9), { pos: [x, gh(x, z) + s * 0.25, z], rot: [r() * 2, r() * 6, 0] }));
    }
    addPart({
      name: 'rocks', k: 0.08, size: 0.04, band: 0.04, coverage: 2, count: 8000, prims,
      filter: (p, n) => n[1] > -0.2,
      colorFn: (p) => {
        const g = noise(p[0] * 4, p[1] * 4, p[2] * 4);
        return noise(p[0] * 2 + 3, p[1] * 2, p[2] * 2) > 0.58 ? mix3(C.g0, C.g1, g) : mix3(C.b0, C.s0, g);
      },
    });
  }
  {
    const prims = [];
    [[-3.3, 2.5, 0.2], [1.5, 3.4, 0.17], [-0.5, 0.3, 0.14]].forEach(([x, z, rr], i) => {
      const c = [x, gh(x, z) + rr * 0.8, z], r = mulberry32(70 + i);
      prims.push(prim(sphere(rr), { pos: c, tag: 'body' }));
      for (let j = 0; j < 16; j++) {
        const th = r() * TAU, ph = Math.acos(0.15 + 0.85 * r()), d = [Math.sin(ph) * Math.cos(th), Math.cos(ph), Math.sin(ph) * Math.sin(th)];
        prims.push(limb(add(c, d, rr * 0.8), add(c, d, rr * 2.1), 0.016, 0.004, { tag: 'spike' }));
      }
    });
    addPart({ name: 'urchins', size: 0.014, band: 0.012, coverage: 2.5, prims, colorFn: (p, n, q) => mix3(C.u0, q.tag === 'spike' ? C.u1 : C.b0, noise(p[0] * 30, p[1] * 30, p[2] * 30)) });
  }
  {
    const prims = [];
    [[1.7, 0.7, 0.2], [-1.1, 4.7, 1.3], [-4.6, 3.2, 2.6]].forEach(([x, z, rot]) => {
      const c = [x, gh(x, z) + 0.05, z];
      prims.push(prim(sphere(0.12), { pos: c, tag: 'star' }));
      for (let j = 0; j < 5; j++) { const a = rot + j / 5 * TAU; prims.push(limb(c, [c[0] + 0.42 * Math.cos(a), c[1] - 0.01, c[2] + 0.42 * Math.sin(a)], 0.09, 0.022, { tag: 'star' })); }
    });
    addPart({ name: 'starfish', size: 0.014, band: 0.012, coverage: 3, prims, colorFn: (p) => mix3(C.o0, C.o1, 0.3 + 0.6 * noise(p[0] * 25, p[1] * 25, p[2] * 25)) });
  }

  {
    const r = mulberry32(808), prims = [];
    for (let i = 0; i < 46; i++) {
      const x = (r() - 0.5) * 14, z = 2.6 + 4 * r(), s = 0.05 + 0.09 * r();
      if (Math.hypot(x, z) > 8.2) continue;
      prims.push(prim(ellipsoid(s * 1.3, s * 0.6, s), { pos: [x, gh(x, z) + s * 0.1, z], rot: [0, r() * 3, 0], color: [C.s1, C.white, C.p3, C.s0][i % 4] }));
    }
    addPart({ name: 'pebbles', size: 0.02, band: 0.02, coverage: 2.5, prims });
  }

  // ---------------------------------------------------------------- bioluminescent accents
  {
    const r = mulberry32(1212), prims = [];
    for (let i = 0; i < 20; i++) {
      const a = r() * TAU, rr = 1 + 4.2 * r(), x = rr * Math.cos(a), z = rr * Math.sin(a) * 0.8 - 0.5;
      prims.push(prim(sphere(0.045 + 0.03 * r()), { pos: [x, gh(x, z) + 0.05 + 0.5 * r() * r(), z], color: i % 3 ? C.glow : C.glow2, emissive: 1 }));
    }
    addPart({ name: 'lumens', caster: false, pickable: false, size: 0.016, band: 0.02, coverage: 3, pulse: 0.25, prims });
  }

  // ---------------------------------------------------------------- bubbles, motes, light shafts
  [[-1.0, 0.0], [3.9, 0.6], [-4.6, 0.3]].forEach(([x, z], i) => {
    const bx = x, bz = z, by = gh(x, z) + 0.2, prims = [];
    for (let j = 0; j < 5; j++) prims.push(prim(sphere(0.06 + 0.012 * j), { pos: [0.05 * Math.sin(j * 2.1), j * 1.0, 0.05 * Math.cos(j * 1.7)], color: C.w4, emissive: 0.85 }));
    addPart({
      name: 'bubbles' + i, dynamic: true, caster: false, pickable: false, size: 0.016, band: 0.02, coverage: 4, opacity: 0.6, rim: 1, prims,
      local: (t, m) => m.makeTranslation(bx + 0.12 * Math.sin(t * 1.3 + i), by + (t * 0.45 + i * 0.37) % 1, bz + 0.12 * Math.cos(t * 1.1 + i)),
    });
  });
  {
    const r = mulberry32(77), prims = [];
    for (let i = 0; i < 90; i++) prims.push(prim(sphere(0.03), { pos: [(r() - 0.5) * 14, 2.2 + 4 * r(), -7 + 10 * r()], color: C.w4, emissive: 0.8 }));
    addPart({
      name: 'motes', dynamic: true, caster: false, pickable: false, size: 0.03, count: 900, opacity: 0.5, prims,
      local: (t, m) => m.makeRotationY(t * 0.015).setPosition(0, 0.2 * Math.sin(t * 0.3), 0),
    });
  }
  // sun.dir is shared with the config below; the shafts run along it onto the sand.
  const sunRaw = [-0.55, 0.62, 0.35], sl = Math.hypot(...sunRaw), SUN = sunRaw.map((v) => v / sl);
  [[-1.5, -1.5], [2.0, 0.5], [-5.5, -0.5], [4.5, -2.5]].forEach(([x, z], i) => {
    const foot = [x, gh(x, z), z];
    addPart({
      name: 'shaft' + i, caster: false, pickable: false, size: 0.18, count: 1500, opacity: 0.06,
      prims: [limb(foot, add(foot, SUN, 12), 0.35 + 0.08 * i, 0.9, { color: C.w4, emissive: 1 })],
    });
  });

  return {
    palette: Object.entries(C).filter(([k]) => !ALBEDO_ONLY.has(k)).map(([, c]) => c),
    bgTop: C.w2, bgBottom: C.w3,
    sun: { dir: SUN, col: [1.05, 0.92, 0.7], reach: 14 },
    sky: [0.6, 0.76, 0.82], ground: [0.36, 0.5, 0.56], aoMin: 0.5,
    lights: [
      { pos: [CROWN[0], CROWN[1] + 0.8, CROWN[2]], col: [1.0, 0.35, 0.8], power: 1.1, k: 1.6 },
      { pos: [-5.0, gh(-5, 0) + 1.7, 0.1], col: [0.3, 0.9, 1.0], power: 0.9, k: 2 },
      { pos: [CX, CY + 0.7, CZ], col: [0.45, 0.4, 1.0], power: 0.9, k: 1.5 },
    ],
    fog: { col: C.w25, density: 0.03, start: 9 }, rim: [0.5, 0.9, 0.9],
    camera: { pos: [3.2, 3.3, 13.0], target: [0, 1.7, -0.6] },
  };
}
