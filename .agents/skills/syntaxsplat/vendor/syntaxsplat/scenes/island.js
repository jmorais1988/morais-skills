// Lighthouse island at dusk.
import { THREE, prim, sphere, ellipsoid, box, cylinder, capsule, cone, addPart, noise, mix3, hex, smooth } from '../engine.js';

export default function build() {
  const C = {
    bg: hex(0x0d1226), deep: hex(0x1b2a4f), blue: hex(0x2e4a7d), midBlue: hex(0x4f77a8), lightBlue: hex(0x8fb4d9),
    pale: hex(0xd7e6f2), darkGreen: hex(0x1f3b2c), green: hex(0x3c6b3a), lightGreen: hex(0x7da043), lime: hex(0xc2c85a),
    darkBrown: hex(0x3a2622), brown: hex(0x6e4631), tan: hex(0xa8754a), sand: hex(0xd9b77a), cream: hex(0xf4e6b8),
    darkRed: hex(0x6b1f2a), red: hex(0xb53a35), orange: hex(0xe07b39), yellow: hex(0xf6c65b), white: hex(0xfbf7ea),
    darkGrey: hex(0x2b2d3a), grey: hex(0x5a5e6e), lightGrey: hex(0x9aa0ad), purple: hex(0x4a3460),
  };

  const WATER_Y = -0.55;
  const LH = [-0.8, -0.4];            // lighthouse x,z
  const LAMP = [LH[0], 3.32, LH[1]];  // lamp position, also a baked point light

  const island = addPart({
    name: 'island', k: 0.25, areaFrac: 0.55,
    prims: [
      prim(ellipsoid(3.6, 1.25, 3.2), { pos: [0, -1.0, 0] }),
      prim(ellipsoid(1.4, 0.55, 1.3), { pos: [LH[0], -0.1, LH[1]] }),
      prim(box(0.35, 0.28, 0.3, 0.1), { pos: [3.05, -0.5, -1.2], rot: [0.2, 0.5, 0.1], tag: 'rock' }),
      prim(sphere(0.34), { pos: [-3.2, -0.55, 1.0], tag: 'rock' }),
      prim(box(0.3, 0.22, 0.4, 0.1), { pos: [1.0, -0.55, 2.95], rot: [0.1, 1.1, 0.2], tag: 'rock' }),
      prim(sphere(0.25), { pos: [-1.6, -0.5, -2.75], tag: 'rock' }),
      prim(sphere(0.2), { pos: [0.6, 0.2, -1.6], tag: 'rock' }),
    ],
    filter: (p) => p[1] > WATER_Y - 0.12,
    colorFn: (p, n, q, rng) => {
      if (q.tag === 'rock') return mix3(C.grey, C.lightGrey, noise(p[0] * 4, p[1] * 4, p[2] * 4));
      if (p[1] < -0.36) return mix3(C.tan, C.sand, noise(p[0] * 3, 0, p[2] * 3));
      if (n[1] < 0.6) return mix3(C.brown, C.tan, noise(p[0] * 5, p[1] * 5, p[2] * 5));
      const r = rng();
      if (r < 0.006) return C.yellow;
      if (r < 0.012) return C.white;
      if (r < 0.016) return C.red;
      const g = noise(p[0] * 1.3, 3.7, p[2] * 1.3) * 0.7 + noise(p[0] * 6, 1.1, p[2] * 6) * 0.3;
      return g > 0.55 ? mix3(C.lightGreen, C.lime, (g - 0.55) * 1.5) : mix3(C.green, C.lightGreen, g * 1.4);
    },
  });

  function groundY(x, z) {
    let y = 1.5;
    for (let i = 0; i < 40; i++) {
      const d = island.sdf(x, y, z);
      if (d < 0.002) break;
      y -= d;
    }
    return y;
  }

  addPart({
    name: 'lighthouse',
    prims: [
      prim(cylinder(0.72, 0.14), { pos: [LH[0], 0.42, LH[1]], color: C.grey }),
      prim(cone(1.25, 0.52, 0.34), {
        pos: [LH[0], 1.75, LH[1]],
        colorFn: (p) => (Math.floor((p[1] - 0.5) / 0.5) % 2 === 0 ? C.red : C.white),
      }),
      prim(cylinder(0.5, 0.05), { pos: [LH[0], 3.05, LH[1]], color: C.darkGrey }),
      prim(cylinder(0.26, 0.22), { pos: LAMP, color: [1.0, 0.86, 0.45], emissive: true }),
      prim(cone(0.22, 0.36, 0.02), { pos: [LH[0], 3.76, LH[1]], color: C.darkRed }),
      prim(box(0.13, 0.21, 0.06, 0.02), { pos: [LH[0] + 0.35, 0.78, LH[1] + 0.35], rot: [0, Math.PI / 4, 0], color: C.darkBrown }),
      prim(box(0.07, 0.1, 0.05, 0.01), { pos: [LH[0] + 0.3, 2.05, LH[1] + 0.3], rot: [0, Math.PI / 4, 0], color: [1.0, 0.8, 0.4], emissive: true }),
    ],
  });

  function pine(name, x, z, s, phase) {
    const y = groundY(x, z) - 0.05;
    addPart({
      name, k: 0.04, wind: 0.05,
      prims: [
        prim(capsule(0.07 * s, 0.25 * s), { pos: [0, 0.25 * s, 0], color: C.brown }),
        prim(cone(0.4 * s, 0.5 * s, 0.05 * s), { pos: [0, 0.8 * s, 0], tag: 'leaf' }),
        prim(cone(0.35 * s, 0.4 * s, 0.04 * s), { pos: [0, 1.25 * s, 0], tag: 'leaf' }),
        prim(cone(0.3 * s, 0.28 * s, 0.02 * s), { pos: [0, 1.65 * s, 0], tag: 'leaf' }),
      ],
      colorFn: (p, n, q) => (q.tag === 'leaf' ? mix3(C.darkGreen, C.green, noise(p[0] * 7 + x, p[1] * 7, p[2] * 7)) : q.color),
      local: (t, M) => M.makeRotationZ(Math.sin(t * 0.9 + phase) * 0.04).setPosition(x, y, z),
    });
  }
  pine('pine1', 2.0, -1.3, 1.0, 0.0);
  pine('pine2', 2.5, 0.5, 0.8, 1.7);
  pine('pine3', -2.4, 1.1, 1.1, 3.1);
  pine('pine4', -1.9, -1.9, 0.75, 4.4);

  // Sheep: body is the root, head and legs are child parts.
  {
    const cx = 0.6, cz = 1.0, r = 0.9, small = { size: 0.016, band: 0.02, dynamic: true, group: 'sheep' };
    const body = addPart({
      name: 'sheepBody', ...small, k: 0.06,
      prims: [
        prim(ellipsoid(0.2, 0.17, 0.3), { color: C.cream }),
        prim(sphere(0.12), { pos: [0.08, 0.1, 0.12], color: C.white }),
        prim(sphere(0.12), { pos: [-0.08, 0.1, -0.1], color: C.white }),
        prim(sphere(0.11), { pos: [0.07, 0.09, -0.16], color: C.cream }),
        prim(sphere(0.06), { pos: [0, 0.05, -0.31], color: C.white }),
      ],
      local: (t, M) => {
        const a = t * 0.35, x = cx + r * Math.cos(a), z = cz + r * Math.sin(a);
        M.makeRotationY(-a).setPosition(x, groundY(x, z) + 0.31 + Math.abs(Math.sin(t * 6)) * 0.012, z);
      },
    });
    addPart({
      name: 'sheepHead', ...small, parent: body,
      prims: [
        prim(ellipsoid(0.085, 0.085, 0.12), { color: C.purple }),
        prim(sphere(0.035), { pos: [0.085, 0.04, -0.03], color: C.darkGrey }),
        prim(sphere(0.035), { pos: [-0.085, 0.04, -0.03], color: C.darkGrey }),
      ],
      local: (t, M) => M.makeRotationX(Math.sin(t * 3) * 0.12).setPosition(0, 0.09, 0.33),
    });
    [[0.11, 0.17, 0], [-0.11, 0.17, Math.PI], [0.11, -0.17, Math.PI], [-0.11, -0.17, 0]].forEach(([hx, hz, ph], i) => {
      addPart({
        name: 'sheepLeg' + i, ...small, parent: body,
        prims: [prim(capsule(0.035, 0.09), { pos: [0, -0.1, 0], color: C.darkGrey })],
        local: (t, M) => M.makeRotationX(Math.sin(t * 6 + ph) * 0.55).setPosition(hx, -0.1, hz),
      });
    });
  }

  // Boat
  {
    const hull = ellipsoid(0.3, 0.24, 0.62);
    const cut = { base: (x, y, z) => Math.max(hull.base(x, y, z), y - 0.04), half: hull.half };
    const e = new THREE.Euler();
    addPart({
      name: 'boat', size: 0.018, band: 0.025, dynamic: true,
      prims: [
        prim(cut, { color: C.brown }),
        prim(capsule(0.02, 0.4), { pos: [0, 0.42, 0], color: C.darkBrown }),
        prim(box(0.012, 0.3, 0.2, 0.01), { pos: [0, 0.5, 0.23], color: C.cream }),
      ],
      local: (t, M) => {
        e.set(Math.sin(t * 1.1) * 0.08, 0.7, Math.sin(t * 0.8 + 1) * 0.1);
        M.makeRotationFromEuler(e).setPosition(4.3, WATER_Y + 0.06 + Math.sin(t * 1.3) * 0.04, 1.7);
      },
    });
  }

  // Gull circling the lamp
  {
    const small = { size: 0.012, band: 0.015, dynamic: true, group: 'gull' };
    const e = new THREE.Euler(0, 0, 0, 'YXZ');
    const body = addPart({
      name: 'gullBody', ...small,
      prims: [prim(ellipsoid(0.07, 0.06, 0.17), { color: C.white }), prim(sphere(0.03), { pos: [0, 0.01, 0.18], color: C.orange })],
      local: (t, M) => {
        const a = t * 0.6;
        e.set(0, -a, 0.3);
        M.makeRotationFromEuler(e).setPosition(LH[0] + 1.5 * Math.cos(a), 4.1 + 0.2 * Math.sin(t * 0.7), LH[1] + 1.5 * Math.sin(a));
      },
    });
    for (const s of [1, -1]) {
      addPart({
        name: 'gullWing' + s, ...small, parent: body,
        prims: [prim(box(0.14, 0.012, 0.07, 0.01), { pos: [s * 0.15, 0, 0], color: C.pale })],
        local: (t, M) => M.makeRotationZ(s * Math.sin(t * 9) * 0.6).setPosition(s * 0.04, 0.02, 0),
      });
    }
  }

  addPart({
    name: 'water', size: 0.085, band: 0.03, caster: false, pickable: false, wobble: 0.03, areaFrac: 0.5,
    prims: [prim(cylinder(8, 0.02), { pos: [0, WATER_Y, 0] })],
    filter: (p, n) => n[1] > 0.5,
    colorFn: (p, n, q, rng) => {
      const d = island.sdf(p[0], p[1], p[2]);
      let c;
      if (d < 0.1 && rng() < 0.7) c = C.pale;
      else if (d < 0.45) c = mix3(C.lightBlue, C.midBlue, d / 0.45);
      else c = mix3(C.blue, C.midBlue, smooth(0.55, 0.8, noise(p[0] * 0.9, 0, p[2] * 2.4)));
      return mix3(c, C.bg, smooth(4.5, 8, Math.hypot(p[0], p[2])));
    },
  });

  // The lamp's beam: a warm light circling the lamp, brightening whatever it sweeps past.
  const beam = {
    pos: LAMP, col: [1.0, 0.8, 0.4], power: 1.4, k: 0.35,
    update: (t, l) => { const a = t * 0.5; l.pos = [LH[0] + 3.0 * Math.cos(a), 2.6, LH[1] + 3.0 * Math.sin(a)]; },
  };

  const sunDir = [-0.2, 0.45, 0.8], sl = Math.hypot(...sunDir);
  return {
    palette: Object.values(C),
    bgTop: C.bg, bgBottom: C.bg,
    sun: { dir: sunDir.map((v) => v / sl), col: [1.25, 0.86, 0.55], reach: 7 },
    sky: [0.3, 0.4, 0.62], ground: [0, 0, 0], aoMin: 0.35,
    lights: [{ pos: LAMP, col: [1.0, 0.75, 0.35], power: 1.8, k: 1.1 }],
    liveLights: [beam],
    wind: { dir: [1, 0, 0.3], strength: 1, speed: 1.2 },
    fog: { col: C.bg, density: 0, start: 0 }, rim: [0, 0, 0],
    camera: { pos: [9.5, 6.0, 11.0], target: [0, 1.0, 0] },
  };
}
