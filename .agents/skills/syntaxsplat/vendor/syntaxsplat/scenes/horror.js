// Horrorscape: a watching eye in a biomechanical idol, caged by a ring of great
// ribs under an eclipse. Bone, iron and ribbed hose; ichor, tentacles and cultists.
import {
  THREE, prim, sphere, ellipsoid, box, cylinder, cone, torus, limb, curve, catmull, rawPrim,
  addPart, noise, fbm, mix3, hex, lerp, smooth, clamp, mulberry32,
} from '../engine.js';

const TAU = Math.PI * 2;
const add = (a, b, s = 1) => [a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const norm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

export default function build() {
  // Palette: cold iron greys, stained bone, bruise purples, ichor teal to acid green, blood, flesh.
  const C = {
    k0: hex(0x07060b), k1: hex(0x100e18), k2: hex(0x1b1926), k3: hex(0x2a2836), k4: hex(0x3f3d4e), k5: hex(0x5d5b6b), k6: hex(0x86848f), k7: hex(0xb5b2b3),
    s0: hex(0x231e15), s1: hex(0x3d3626), s2: hex(0x5f553c), s3: hex(0x897c5a), bone: hex(0xb9ab82), boneHi: hex(0xe0d8c0),
    p0: hex(0x180d2a), p1: hex(0x2e1a47), p2: hex(0x4d2b69), p3: hex(0x7c4a93), p4: hex(0xb48ac4),
    t0: hex(0x051d1b), t1: hex(0x0b3a34), t2: hex(0x146653), t3: hex(0x2aa374), acid: hex(0x79e08a), acidHi: hex(0xd6ffb2),
    c0: hex(0x24090f), c1: hex(0x521220), c2: hex(0x8f1f27), c3: hex(0xcf4a38), orange: hex(0xf29a4e),
    f1: hex(0x6f444d), f2: hex(0xb07f7c),
  };
  const rnd = mulberry32(1337);
  const e = new THREE.Euler();
  const EYE = [0, 4.5, 0];
  const eyePose = (t, eu) => eu.set(0.2 + 0.12 * Math.sin(t * 0.47), 0.35 + 0.6 * Math.sin(t * 0.31) + 0.25 * Math.sin(t * 0.83 + 1), 0, 'YXZ');
  const emitters = [];   // embers from the idol's vents
  const lights = [{ pos: EYE, col: [0.5, 1.0, 0.32], power: 7, k: 0.16, shadow: true, radius: 1.5 }];

  // Ichor glow: low teal uplights around the moat.
  for (let i = 0; i < 3; i++) lights.push({ pos: [2.4 * Math.cos(i * TAU / 3 + 1), 0.3, 2.4 * Math.sin(i * TAU / 3 + 1)], col: [0.15, 0.7, 0.6], power: 1.3, k: 0.6 });

  // ---------------------------------------------------------------- ground
  // Raised dais, a moat of ichor around it, rippled basalt out to a crumbling rim.
  const G = 257, EXT = 10.5, hm = new Float32Array(G * G);
  const hRaw = (x, z) => {
    const r = Math.hypot(x, z);
    let h = 0.16 * (fbm(x * 0.45 + 3, 0, z * 0.45 - 7) - 0.5) * smooth(2.5, 6, r);
    h += 0.28 * (1 - smooth(1.45, 1.95, r));
    h -= 0.34 * smooth(1.75, 2.15, r) * (1 - smooth(2.95, 3.45, r));
    h += 0.03 * Math.sin(r * 13) * smooth(3.4, 3.9, r) * (1 - smooth(6.2, 7.6, r));
    return h - 1.7 * smooth(7.4, 9.6, r);
  };
  for (let j = 0; j < G; j++) for (let i = 0; i < G; i++) hm[j * G + i] = hRaw(-EXT + i / (G - 1) * 2 * EXT, -EXT + j / (G - 1) * 2 * EXT);
  const gh = (x, z) => {
    const u = clamp((x + EXT) / (2 * EXT) * (G - 1), 0, G - 1.001), v = clamp((z + EXT) / (2 * EXT) * (G - 1), 0, G - 1.001);
    const i = u | 0, j = v | 0, o = j * G + i;
    return lerp(lerp(hm[o], hm[o + 1], u - i), lerp(hm[o + G], hm[o + G + 1], u - i), v - j);
  };

  addPart({
    name: 'ground', size: 0.055, coverage: 2,
    prims: [rawPrim((x, y, z) => Math.max((y - gh(x, z)) * 0.75, Math.hypot(x, z) - 9.6), [-9.6, -2.2, -9.6], [9.6, 0.5, 9.6])],
    filter: (p, n) => n[1] > 0.25,
    colorFn: (p) => {
      const x = p[0], z = p[2], r = Math.hypot(x, z), a = Math.atan2(z, x);
      const grain = noise(x * 3, 1, z * 3);
      let c;
      if (r < 1.9) {                                   // dais: bone plates with dark seams
        const sector = (a / TAU * 12 % 1 + 1) % 1;
        c = Math.abs(sector - 0.5) > 0.455 || Math.abs(r - 1.22) < 0.035 ? C.k1 : mix3(C.s1, C.s3, grain);
      } else if (r < 3.45) {                           // moat walls: slick and stained
        c = mix3(C.t0, C.k3, grain);
      } else {
        const crest = Math.sin(r * 13) * smooth(3.4, 3.9, r) * (1 - smooth(6.2, 7.6, r));
        c = crest > 0.35 ? mix3(C.k4, C.k5, grain) : mix3(C.k1, C.k3, fbm(x * 1.4, 2, z * 1.4));
        if (noise(x * 0.9 - 4, 5, z * 0.9) > 0.72) c = mix3(c, C.t1, 0.7);                       // lichen
        if (Math.abs(noise(x * 1.7 + 9, 2, z * 1.7) - 0.5) < 0.016) c = mix3(C.c1, C.c2, grain); // veins
      }
      return c;
    },
  });

  addPart({
    name: 'ichor', size: 0.05, band: 0.03, coverage: 3, caster: false, pickable: false, wobble: 0.012, rim: 0.9, areaFrac: 0.5,
    prims: [prim(cylinder(3.5, 0.015), { pos: [0, -0.17, 0] })],
    filter: (p, n) => n[1] > 0.5 && gh(p[0], p[2]) < -0.15,
    colorFn: (p) => {
      if (gh(p[0], p[2]) > -0.22) return mix3(C.s1, C.s2, noise(p[0] * 9, 0, p[2] * 9));            // scum at the edge
      const swirl = noise(p[0] * 1.3 + 2, 0, p[2] * 1.3);
      if (Math.abs(swirl - 0.5) < 0.03) return C.t2;
      return mix3(C.k0, C.t0, swirl);
    },
  });

  // ---------------------------------------------------------------- idol
  // Stacked ribbed column, pipes and struts, and claws that grip the eye.
  {
    const R = (y) => 0.5 + 0.7 * (1 - smooth(0.3, 1.7, y)) + 0.5 * smooth(2.3, 3.3, y);
    const prims = [];
    for (let y = 0.15; y < 3.3; y += 0.31) prims.push(limb([0, y, 0], [0, y + 0.31, 0], R(y) - 0.03, R(y + 0.31) - 0.03, { tag: 'core' }));
    for (let y = 0.34, i = 0; y < 3.3; y += 0.19, i++) prims.push(prim(torus(R(y), i % 3 === 0 ? 0.11 : 0.07), { pos: [0, y, 0], tag: 'ring' }));
    for (let j = 0; j < 6; j++) {
      const th = j / 6 * TAU, pts = [];
      for (let y = 0.2; y <= 3.3; y += 0.44) { const a = th + 0.28 * Math.sin(y * 1.3 + j); pts.push([(R(y) + 0.1) * Math.cos(a), y, (R(y) + 0.1) * Math.sin(a)]); }
      prims.push(...curve(catmull(pts, 2), 0.065, 0.055, { rib: 0.25, freq: 38, tag: 'pipe' }));
    }
    for (let j = 0; j < 3; j++) {
      const th = j / 3 * TAU + 0.5, a = [1.7 * Math.cos(th), 0.25, 1.7 * Math.sin(th)], b = [0.62 * Math.cos(th), 2.35, 0.62 * Math.sin(th)];
      prims.push(limb(a, b, 0.06, 0.045, { tag: 'pipe' }), limb(add(a, sub(b, a), 0.3), add(a, sub(b, a), 0.62), 0.09, 0.09, { tag: 'ring' }));
      prims.push(prim(sphere(0.12), { pos: a, tag: 'ring' }), prim(sphere(0.1), { pos: b, tag: 'ring' }));
    }
    for (let j = 0; j < 6; j++) {                      // furnace vents glowing at the waist
      const th = (j + 0.5) / 6 * TAU, v = [(R(1.9) + 0.02) * Math.cos(th), 1.9, (R(1.9) + 0.02) * Math.sin(th)];
      prims.push(prim(ellipsoid(0.05, 0.12, 0.05), { pos: v, color: [1.0, 0.55, 0.2], emissive: 1.5, tag: 'vent' }));
      emitters.push({ part: 'idol', pos: v, rate: 5, life: 2.5, velocity: [0.15 * Math.cos(th), 0.5, 0.15 * Math.sin(th)], spread: 0.08, size: 0.018, colour: [1.0, 0.55, 0.2], emissive: 1.5 });
      if (j % 2 === 0) lights.push({ pos: [1.25 * Math.cos(th), 1.9, 1.25 * Math.sin(th)], col: [1.0, 0.55, 0.2], power: 1.0, k: 1.1 });
    }
    prims.push(prim(sphere(0.8), { pos: [0, 3.45, 0], tag: 'core' }), prim(torus(1.02, 0.11, { n: 22, amp: 0.25 }), { pos: [0, 3.4, 0], tag: 'ring' }));
    for (let j = 0; j < 6; j++) {
      const th = j / 6 * TAU + 0.2;
      const pts = [[1.0, 3.4], [1.32, 3.9], [1.36, 4.6], [1.12, 5.2], [0.72, 5.52]].map(([r, y]) => [r * Math.cos(th), y, r * Math.sin(th)]);
      prims.push(...curve(catmull(pts, 2), 0.13, 0.02, { rib: 0.1, freq: 16, tag: 'claw' }));
    }
    addPart({
      name: 'idol', k: 0.05, size: 0.026, coverage: 2.5, rim: 0.5, prims,
      colorFn: (p, n, q) => {
        const g = noise(p[0] * 5, p[1] * 5, p[2] * 5), stain = smooth(0.45, 0.8, noise(p[0] * 2, p[1] * 1.1, p[2] * 2));
        if (q.tag === 'vent') return q.color;
        if (q.tag === 'pipe') return mix3(C.k4, C.k6, g);
        if (q.tag === 'core') return mix3(C.k1, C.k3, g);
        if (q.tag === 'claw') return mix3(mix3(C.s2, C.boneHi, smooth(3.4, 5.5, p[1])), C.c1, stain * 0.35);
        return mix3(mix3(C.s1, C.bone, smooth(0.2, 3.3, p[1]) * 0.6 + g * 0.4), C.k2, stain * 0.6);
      },
    });
  }

  // The eye turns slowly and looks around. Iris and pupil are part of the rigid ball.
  addPart({
    name: 'eye', dynamic: true, size: 0.024, coverage: 4, pulse: 0.1, rim: 0.7,
    prims: [
      prim(sphere(0.95), { tag: 'sclera', emissive: 0.75 }),
      prim(sphere(0.56), { pos: [0, 0, 0.49], tag: 'iris', emissive: 1.3 }),
      prim(ellipsoid(0.11, 0.42, 0.16), { pos: [0, 0, 0.99], color: C.k0, emissive: 1 }),
    ],
    colorFn: (p, n, q) => {
      if (q.tag === 'iris') {
        const t = Math.hypot(p[0], p[1]) / 0.5, streak = noise(Math.atan2(p[1], p[0]) * 5, t * 3, 0);
        if (t > 0.93) return C.k1;
        const c = t < 0.45 ? mix3(C.acidHi, C.acid, t / 0.45) : mix3(C.acid, C.t2, (t - 0.45) / 0.55);
        return mix3(c, C.t1, streak * 0.45);
      }
      if (q.tag === 'sclera') {
        const back = smooth(0.55, -0.8, p[2]);
        if (Math.abs(noise(p[0] * 3.5, p[1] * 3.5, p[2] * 3.5) - 0.5) < 0.012 + 0.04 * back) return mix3(C.c2, C.c3, noise(p[0] * 20, p[1] * 20, p[2] * 20));
        const rho = Math.hypot(p[0], p[1]);
        let c = mix3(C.f1, C.boneHi, smooth(-0.6, 0.6, p[2] / 0.95) * (0.8 + 0.2 * noise(p[0] * 2, p[1] * 2, p[2] * 2)));
        if (p[2] > 0 && rho < 0.74) c = mix3(c, C.c3, 0.55 * smooth(0.74, 0.58, rho));   // bloodshot rim round the iris
        return c;
      }
      return q.color;
    },
    local: (t, M) => {
      eyePose(t, e);
      M.makeRotationFromEuler(e).setPosition(...EYE);
    },
  });

  // ---------------------------------------------------------------- great ribs
  // Nine claws curving over the idol. Each carries spines, a ribbed hose on its
  // underside, a floor conduit back to the moat and a cable to its neighbour.
  const NR = 9, PROFILE = [[4.55, 0], [5.05, 1.1], [5.2, 2.4], [4.95, 3.6], [4.3, 4.7], [3.3, 5.5], [2.35, 5.95], [1.7, 5.8], [1.45, 5.4]];
  const ribs = [];
  for (let i = 0; i < NR; i++) {
    const th = i / NR * TAU + 0.17, s = 0.9 + 0.22 * rnd(), twist = (rnd() - 0.5) * 0.35, broken = i === 6;
    const ctl = (broken ? PROFILE.slice(0, 5) : PROFILE).map(([r, y], k) => {
      const a = th + twist * k / 8, x = r * Math.cos(a), z = r * Math.sin(a);
      return [x, k === 0 ? gh(x, z) - 0.15 : y * s * 1.12, z];
    });
    ribs.push({ th, s, broken, pts: catmull(ctl, 2) });
  }
  const ribColor = (p, n, q) => {
    const g = noise(p[0] * 5, p[1] * 5, p[2] * 5);
    if (q.tag === 'hose') return mix3(C.k3, C.k5, g);
    if (q.tag === 'spine') return mix3(C.s3, C.boneHi, g);
    if (q.tag === 'collar') return mix3(C.k2, C.s2, g);
    const t = clamp(p[1] / 6.2, 0, 1);
    let c = t < 0.35 ? mix3(C.k2, C.s1, t / 0.35) : mix3(C.s2, C.bone, (t - 0.35) / 0.65);
    c = mix3(c, C.k2, smooth(0.4, 0.8, noise(p[0] * 2.2, p[1] * 2.2, p[2] * 2.2)) * 0.55);       // grime
    if (noise(p[0] * 7, p[1] * 0.7, p[2] * 7) > 0.72) c = mix3(c, C.c1, 0.65);                   // old blood runs
    return c;
  };
  ribs.forEach((rib, i) => {
    const { th, s, broken, pts } = rib, last = pts.length - 1;
    const r1 = 0.26 * s, r2 = broken ? 0.15 : 0.035;
    const prims = curve(pts, r1, r2, { rib: 0.13, freq: 8.5, tag: 'rib' });
    const B = [-Math.sin(th), 0, Math.cos(th)], out = [Math.cos(th), 0.4, Math.sin(th)], hose = [];
    for (let k = 1; k < last; k++) {
      const T = norm(sub(pts[k + 1], pts[k - 1]));
      let N = cross(T, B);
      if (dot(N, out) < 0) N = [-N[0], -N[1], -N[2]];
      const rk = lerp(r1, r2, k / last);
      if (k <= 12) hose.push(add(pts[k], N, -(rk + 0.07)));
      if (k % 2 === 0) {
        prims.push(limb(add(pts[k], N, rk * 0.5), add(add(pts[k], N, rk + 0.36 * s * (1 - 0.5 * k / last)), T, 0.12), 0.055, 0.005, { tag: 'spine' }));
        if (k <= 12) prims.push(prim(sphere(0.08), { pos: add(pts[k], N, -(rk + 0.05)), tag: 'collar' }));
      }
    }
    prims.push(...curve(hose, 0.05, 0.032, { rib: 0.28, freq: 42, tag: 'hose' }));
    prims.push(prim(torus(0.42, 0.11, { n: 14, amp: 0.2 }), { pos: [pts[0][0], pts[0][1] + 0.2, pts[0][2]], tag: 'collar' }));

    const conduit = [];
    for (let k = 0; k <= 6; k++) {
      const r = lerp(4.25, 3.3, k / 6), a = th + 0.06 * Math.sin(k * 1.4 + i);
      conduit.push([r * Math.cos(a), gh(r * Math.cos(a), r * Math.sin(a)) + 0.04, r * Math.sin(a)]);
    }
    prims.push(...curve(conduit, 0.08, 0.06, { rib: 0.22, freq: 30, tag: 'hose' }));

    const next = ribs[(i + 1) % NR], cable = [];
    if (!broken && !next.broken) {
      for (let k = 0; k <= 6; k++) { const t = k / 6, p = add(pts[7], sub(next.pts[7], pts[7]), t); cable.push([p[0], p[1] - 2.6 * t * (1 - t), p[2]]); }
    } else if (!broken) {                              // its neighbour snapped: the cable hangs
      for (let k = 0; k <= 4; k++) cable.push([pts[7][0] + 0.05 * k * B[0], pts[7][1] - 0.45 * k, pts[7][2] + 0.05 * k * B[2]]);
    }
    if (cable.length) prims.push(...curve(cable, 0.035, 0.035, { rib: 0.3, freq: 50, tag: 'hose' }));

    if (broken) {                                      // jagged stump, and the fallen length beyond the ring
      const T = norm(sub(pts[last], pts[last - 1]));
      for (let j = 0; j < 4; j++) prims.push(limb(pts[last], add(add(pts[last], T, 0.25 + 0.2 * rnd()), [rnd() - 0.5, rnd() - 0.5, rnd() - 0.5], 0.3), 0.07, 0.005, { tag: 'spine' }));
      const fallen = [];
      for (let k = 0; k <= 4; k++) { const a = th + 0.08 + 0.1 * k, r = 6.1 + 0.25 * Math.sin(k * 1.3); fallen.push([r * Math.cos(a), gh(r * Math.cos(a), r * Math.sin(a)) + 0.1, r * Math.sin(a)]); }
      prims.push(...curve(catmull(fallen, 2), 0.15, 0.04, { rib: 0.13, freq: 8.5, tag: 'rib' }));
    }
    addPart({ name: 'rib' + i, k: 0.03, size: 0.032, coverage: 2.5, rim: 0.45, prims, colorFn: ribColor });
  });

  // ---------------------------------------------------------------- tentacles
  // Seven chains of eight rigid segments rising from the ichor. Each segment is a
  // child of the one below, so a travelling wave of joint angles makes them writhe.
  const NT = 7, NS = 8;
  for (let i = 0; i < NT; i++) {
    const th = i / NT * TAU + 0.35, phi = Math.PI / 2 - th, dir = i % 3 === 1 ? -1 : 1;
    const ph = rnd() * TAU, ph2 = rnd() * TAU, sc = 0.85 + 0.3 * rnd();
    const bx = 2.5 * Math.cos(th), bz = 2.5 * Math.sin(th);
    const R = (k) => sc * (0.2 * Math.pow(1 - k / NS, 0.85) + 0.028);
    let parent = null, below = 0;
    for (let k = 0; k < NS; k++) {
      const L = sc * 0.52 * Math.pow(0.9, k), r1 = R(k), r2 = R(k + 1);
      const rest = dir * (k < 2 ? -0.1 : 0.14 + 0.07 * k), amp = 0.07 + 0.035 * k, up = below, root = k === 0;
      const prims = [limb([0, 0, 0], [0, L, 0], r1, r2, { rib: 0.07, freq: 36, tag: 'skin' })];
      if (k < NS - 2) for (const [sx, f] of [[1, 0.3], [-1, 0.72]]) prims.push(prim(sphere(r1 * 0.3), { pos: [sx * r1 * 0.3, L * f, dir * lerp(r1, r2, f) * 0.86], tag: 'sucker' }));
      parent = addPart({
        name: `tentacle${i}_${k}`, group: 'tentacle' + i, parent, dynamic: true, size: 0.022, band: 0.03, coverage: 3, rim: 1, prims,
        colorFn: (p, n, q) => {
          if (q.tag === 'sucker') return mix3(C.f2, C.c3, noise(p[0] * 40, p[1] * 40, p[2] * 40));
          let top = mix3(C.t1, C.p2, noise(p[0] * 9 + i * 3, p[1] * 5 + k, p[2] * 9));
          if (noise(p[0] * 22, p[1] * 22 + k * 7, p[2] * 22) > 0.78) top = C.t3;                 // glowing spots
          return mix3(top, mix3(C.f1, C.f2, noise(p[0] * 12, p[1] * 6, p[2] * 12)), smooth(0.1, 0.55, n[2] * dir));
        },
        local: (t, M) => {
          const bend = rest + amp * Math.sin(t * 0.9 + ph - k * 0.75), sway = 0.09 * Math.sin(t * 0.6 + ph2 + k * 1.1);
          if (root) { e.set(bend, phi, sway, 'YXZ'); M.makeRotationFromEuler(e).setPosition(bx, -0.32, bz); }
          else { e.set(bend, 0, sway, 'XYZ'); M.makeRotationFromEuler(e).setPosition(0, up, 0); }
        },
      });
      below = L;
    }
  }

  // ---------------------------------------------------------------- cultists
  // Hooded figures bowing toward the eye. Every other one carries a lantern.
  const liveLights = [];
  for (let i = 0; i < 8; i++) {
    const th = (i + 0.5) / 8 * TAU, x = 3.85 * Math.cos(th), z = 3.85 * Math.sin(th), y = gh(x, z) - 0.02;
    const phi = Math.atan2(-Math.cos(th), -Math.sin(th)), s = 0.9 + 0.25 * rnd(), ph = rnd() * TAU, lantern = i % 2 === 0;
    const v = (a) => a.map((c) => c * s);
    const prims = [
      prim(cone(0.2 * s, 0.17 * s, 0.07 * s), { pos: v([0, 0.2, 0]), tag: 'robe' }),
      prim(sphere(0.085 * s), { pos: v([0, 0.4, 0.01]), tag: 'robe' }),
      prim(sphere(0.075 * s), { pos: v([0, 0.5, 0.02]), tag: 'hood' }),
      limb(v([0, 0.52, 0]), v([0, 0.61, -0.05]), 0.05 * s, 0.012 * s, { tag: 'hood' }),
      prim(sphere(0.045 * s), { pos: v([0, 0.49, 0.065]), color: C.k0, emissive: 1 }),
      limb(v([-0.08, 0.42, 0.02]), v([-0.14, 0.57, 0.14]), 0.028 * s, 0.02 * s, { tag: 'robe' }),
      prim(sphere(0.023 * s), { pos: v([-0.14, 0.58, 0.15]), color: C.f2 }),
    ];
    if (lantern) {
      prims.push(limb(v([0.08, 0.42, 0.02]), v([0.16, 0.44, 0.12]), 0.028 * s, 0.02 * s, { tag: 'robe' }));
      prims.push(limb(v([0.16, 0, 0.12]), v([0.16, 0.8, 0.12]), 0.012 * s, 0.012 * s, { color: C.s2 }));
      prims.push(prim(sphere(0.04 * s), { pos: v([0.16, 0.84, 0.12]), color: [1.0, 0.6, 0.25], emissive: 1.6 }));
    } else {
      prims.push(limb(v([0.08, 0.42, 0.02]), v([0.14, 0.57, 0.14]), 0.028 * s, 0.02 * s, { tag: 'robe' }));
      prims.push(prim(sphere(0.023 * s), { pos: v([0.14, 0.58, 0.15]), color: C.f2 }));
    }
    const pose = (t, M) => { e.set(0.16 + 0.15 * Math.sin(t * 0.8 + ph), phi, 0, 'YXZ'); return M.makeRotationFromEuler(e).setPosition(x, y, z); };
    addPart({
      name: 'cultist' + i, k: 0.015, size: 0.013, band: 0.014, coverage: 3.5, prims, local: pose,
      colorFn: (p, n, q) => {
        if (q.tag === 'hood') return mix3(C.c0, C.c1, noise(p[0] * 30, p[1] * 30, p[2] * 30) * 0.6);
        if (q.tag === 'robe') return p[1] < 0.06 * s ? C.c3 : mix3(C.c1, C.c2, noise(p[0] * 25, p[1] * 8, p[2] * 25));
        return q.color;
      },
    });
    if (lantern) {
      const w = new THREE.Vector3(...v([0.16, 0.84, 0.12])).applyMatrix4(pose(0, new THREE.Matrix4()));
      lights.push({ pos: [w.x, w.y, w.z], col: [1.0, 0.42, 0.14], power: 1.1, k: 3 });
      if (liveLights.length < 3) {                     // live lights are capped at four; the eye takes the last
        liveLights.push({ pos: [w.x, w.y, w.z], col: [1.0, 0.42, 0.14], power: 0.5, k: 3, update: (t, l) => { l.power = 0.5 * (0.4 + 1.2 * noise(t * 7 + i * 5, 0, 0)); } });
      }
    }
  }

  // ---------------------------------------------------------------- polyps
  // Stalked bulbs with glowing caps, clustered between the ribs.
  [0, 2, 3, 5, 7, 8].forEach((slot, i) => {
    const th = (slot + 0.5) / NR * TAU + 0.17, cx = 5.9 * Math.cos(th), cz = 5.9 * Math.sin(th), prims = [];
    for (let j = 0; j < 6; j++) {
      const x = cx + (rnd() - 0.5) * 0.7, z = cz + (rnd() - 0.5) * 0.7, y = gh(x, z), h = 0.22 + 0.45 * rnd(), rb = 0.07 + 0.07 * rnd();
      const top = [x + (rnd() - 0.5) * 0.2, y + h, z + (rnd() - 0.5) * 0.2];
      prims.push(limb([x, y - 0.05, z], top, 0.04, 0.022, { tag: 'stalk' }));
      prims.push(prim(sphere(rb), { pos: top, tag: 'bulb' }));
      prims.push(prim(sphere(rb * 0.62), { pos: [top[0], top[1] + rb * 0.55, top[2]], color: [0.45, 1.0, 0.8], emissive: 1.4 }));
    }
    addPart({
      name: 'polyps' + i, k: 0.02, size: 0.016, band: 0.02, coverage: 3, pulse: 0.3, rim: 0.6, prims,
      colorFn: (p, n, q) => (q.tag === 'stalk' ? mix3(C.t0, C.t1, noise(p[0] * 20, p[1] * 20, p[2] * 20)) : q.tag === 'bulb' ? mix3(C.t1, C.p2, noise(p[0] * 14, p[1] * 14, p[2] * 14)) : q.color),
    });
    lights.push({ pos: [cx, gh(cx, cz) + 0.6, cz], col: [0.25, 1.0, 0.75], power: 0.8, k: 2.2 });
  });

  // ---------------------------------------------------------------- obelisks
  // Leaning stones cut with glowing script on both faces.
  function obelisk(i, r, th, h, leanX, leanZ, runeCol, sink) {
    const x = r * Math.cos(th), z = r * Math.sin(th);
    const M = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(leanX, Math.atan2(-Math.cos(th), -Math.sin(th)), leanZ, 'YXZ')).setPosition(x, gh(x, z) - sink, z);
    const prims = [
      prim(box(0.5, 0.09, 0.44, 0.02), { pos: [0, sink + 0.02, 0] }),
      prim(box(0.34, h / 2, 0.28, 0.025), { pos: [0, h / 2, 0] }),
      prim(box(0.27, 0.1, 0.22, 0.02), { pos: [0, h + 0.1, 0] }),
      prim(box(0.17, 0.09, 0.14, 0.02), { pos: [0, h + 0.29, 0] }),
    ];
    const node = () => [((rnd() * 3 | 0) - 1) * 0.17, (rnd() * 3 | 0) * 0.11];
    for (const face of [1, -1]) {
      for (let y0 = 0.75; y0 < h - 0.35; y0 += 0.42) {
        for (let k = 0; k < 3; k++) {
          const a = node(), b = node();
          if (a[0] === b[0] && a[1] === b[1]) continue;
          prims.push(limb([a[0], y0 + a[1], face * 0.288], [b[0], y0 + b[1], face * 0.288], 0.022, 0.022, { tag: 'rune', color: runeCol, emissive: 1.5 }));
        }
      }
    }
    addPart({
      name: 'obelisk' + i, matrix: M, size: 0.028, coverage: 2.5, prims,
      colorFn: (p, n, q) => {
        if (q.tag === 'rune') return q.color;
        let c = mix3(C.k1, C.k4, noise(p[0] * 3, p[1] * 3, p[2] * 3) * 0.6 + smooth(0, h, p[1]) * 0.4);
        if (p[1] < h * 0.6 && noise(p[0] * 2 + i, p[1] * 1.3, p[2] * 2) > 0.66) c = mix3(c, C.t2, 0.6);
        return c;
      },
    });
    for (const face of [1, -1]) {
      const w = new THREE.Vector3(0, h * 0.55, face * 0.8).applyMatrix4(M);
      lights.push({ pos: [w.x, w.y, w.z], col: runeCol, power: 0.6, k: 1.6 });
    }
  }
  obelisk(0, 7.0, 0.2, 2.7, 0.1, -0.08, [0.45, 1.0, 0.5], 0.25);
  obelisk(1, 7.1, 1.9, 3.4, -0.06, 0.12, [1.0, 0.3, 0.22], 0.25);
  obelisk(2, 6.9, 3.5, 2.9, -1.3, 0.2, [0.7, 0.45, 1.0], 0.12);   // toppled
  obelisk(3, 7.0, 5.0, 2.3, 0.14, 0.05, [0.45, 1.0, 0.5], 0.25);

  // ---------------------------------------------------------------- small things
  {
    const prims = [];
    for (let i = 0; i < 44; i++) {
      const a = rnd() * TAU, r = 3.6 + 3.7 * rnd(), x = r * Math.cos(a), z = r * Math.sin(a), s = 0.05 + 0.09 * rnd(), isBone = rnd() < 0.3;
      prims.push(prim(ellipsoid(s * (0.8 + 0.6 * rnd()), s * 0.6, s), { pos: [x, gh(x, z) + s * 0.25, z], rot: [0, rnd() * 3, 0], color: isBone ? C.s3 : C.k4 }));
    }
    addPart({ name: 'debris', size: 0.018, band: 0.02, coverage: 3, prims, colorFn: (p, n, q) => mix3(q.color, C.k2, noise(p[0] * 20, p[1] * 20, p[2] * 20) * 0.5) });
  }

  {
    const prims = [];
    for (let i = 0; i < 11; i++) {
      const a = rnd() * TAU, r = 1.4 + 1.3 * rnd();
      prims.push(prim(box(0.05 + 0.09 * rnd(), 0.15 + 0.3 * rnd(), 0.04 + 0.06 * rnd(), 0.012), { pos: [r * Math.cos(a), (rnd() - 0.5) * 0.9, r * Math.sin(a)], rot: [rnd() * 3, rnd() * 3, rnd() * 3] }));
    }
    addPart({
      name: 'shards', dynamic: true, size: 0.02, band: 0.02, coverage: 3, rim: 1, prims,
      colorFn: (p) => mix3(C.k3, C.p3, noise(p[0] * 6, p[1] * 6, p[2] * 6)),
      local: (t, M) => M.makeRotationY(t * 0.12).setPosition(0, 7.9 + 0.15 * Math.sin(t * 0.5), 0),
    });
  }

  {
    const prims = [];
    for (let i = 0; i < 9; i++) {
      const a = rnd() * TAU, r = 2.6 + 4.4 * rnd(), x = r * Math.cos(a), z = r * Math.sin(a);
      prims.push(prim(ellipsoid(1.2 + 1.2 * rnd(), 0.07, 1.2 + 1.2 * rnd()), { pos: [x, gh(x, z) + 0.25 + 0.3 * rnd(), z] }));
    }
    addPart({
      name: 'mist', dynamic: true, caster: false, pickable: false, size: 0.3, count: 1300, opacity: 0.08, wobble: 0.04, wind: 0.4, prims,
      filter: (p, n) => n[1] > 0.3,
      colorFn: (p) => mix3([0.8, 0.75, 1.1], [1.1, 1.1, 1.3], noise(p[0], 0, p[2])),
      local: (t, M) => M.makeRotationY(t * 0.02),
    });
  }

  // ---------------------------------------------------------------- sky
  const ECLIPSE = [-10.5, 9.0, -14.5];
  {
    const toScene = new THREE.Vector3(...ECLIPSE).negate().normalize();
    const M = new THREE.Matrix4().compose(new THREE.Vector3(...ECLIPSE), new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), toScene), new THREE.Vector3(1, 1, 1));
    const prims = [prim(cylinder(2.95, 0.02), { color: C.k0, emissive: 1 }), prim(torus(3.0, 0.11), { tag: 'ring', emissive: 1.2 })];
    for (let j = 0; j < 18; j++) {
      const a = j / 18 * TAU + rnd() * 0.2, len = 0.4 + 1.4 * rnd();
      prims.push(limb([3.1 * Math.cos(a), 0, 3.1 * Math.sin(a)], [(3.1 + len) * Math.cos(a), 0, (3.1 + len) * Math.sin(a)], 0.06, 0.004, { tag: 'ray', emissive: 0.9 }));
    }
    addPart({
      name: 'eclipse', matrix: M, caster: false, pickable: false, fog: 0, size: 0.08, band: 0.04, coverage: 3, pulse: 0.06, prims,
      filter: (p, n) => n[1] > -0.2,
      colorFn: (p, n, q) => {
        if (q.tag === 'ring') { const t = 0.5 + 0.5 * Math.cos(Math.atan2(p[2], p[0]) - 0.9); return mix3(C.p3, [1.0, 0.95, 1.0], t * t); }
        if (q.tag === 'ray') return mix3(C.p4, C.p1, smooth(3.1, 4.3, Math.hypot(p[0], p[2])));
        return q.color;
      },
    });
  }

  addPart({
    name: 'stars', caster: false, pickable: false, fog: 0, size: 0.04, count: 900,
    prims: [rawPrim((x, y, z) => 60 - Math.hypot(x, y, z), [-60, 4, -60], [60, 60, 60], { emissive: 1 })],
    colorFn: (p, n, q, rng) => { const r = rng(), b = 0.35 + 0.65 * rng(); return mix3(C.k0, r < 0.6 ? C.k7 : r < 0.8 ? C.p4 : C.acid, b); },
  });

  // A slow green glow follows the eye's gaze, 3.2 units out along the look direction.
  const gaze = new THREE.Euler(), look = new THREE.Vector3();
  liveLights.push({
    pos: [...EYE], col: [0.5, 1.0, 0.32], power: 0.8, k: 0.22,
    update: (t, l) => { look.set(0, 0, 1).applyEuler(eyePose(t, gaze)); l.pos = [EYE[0] + look.x * 3.2, EYE[1] + look.y * 3.2, EYE[2] + look.z * 3.2]; },
  });

  const sunLen = Math.hypot(...ECLIPSE);
  return {
    palette: Object.values(C),
    bgTop: C.k0, bgBottom: [0.085, 0.05, 0.14],
    sun: { dir: ECLIPSE.map((v) => v / sunLen), col: [0.55, 0.52, 0.9], reach: 12 },
    sky: [0.3, 0.26, 0.46], ground: [0.1, 0.16, 0.14], aoMin: 0.25,
    lights, liveLights, emitters,
    wind: { dir: [1, 0, 0.4], strength: 1, speed: 0.8 },
    fog: { col: [0.05, 0.035, 0.08], density: 0.03, start: 10 }, rim: [0.35, 0.55, 0.6],
    camera: { pos: [5.7, 3.0, 15.6], target: [0, 3.9, 0] },
  };
}
