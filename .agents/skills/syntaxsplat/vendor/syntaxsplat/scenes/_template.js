// Starting point for a new scene: copy this file to scenes/<id>.js and replace the
// contents. It shows one of everything: a ground, a static part, an animated child
// part, an emissive accent, a sun with shadows, a point light, a palette and a camera.
// docs/AUTHORING.md explains each option used here.
//
// This file runs on the page AND in every bake worker, so it must be deterministic:
// seeded mulberry32 for randomness, never Math.random, and nothing that touches the DOM.
import { prim, sphere, ellipsoid, box, cylinder, addPart, noise, fbm, mix3, hex, smooth } from '../engine.js';

export default function build() {
  // The pixel pass snaps every pixel to the nearest palette colour, so the palette has
  // to hold the lit results (ramps from shadow to highlight), not only the albedos.
  const C = {
    skyTop: hex(0x5f9fd6), skyMid: hex(0x9ccae4), skyLow: hex(0xcfe6f0), // three steps, or the gradient shows a dithered band
    grass0: hex(0x2c5a2e), grass1: hex(0x4a8a3a), grass2: hex(0x7cb548), grass3: hex(0xb8d96a),
    dirt0: hex(0x4a3425), dirt1: hex(0x7a5a3a), dirt2: hex(0xb08a5c),
    wood0: hex(0x3a2418), wood1: hex(0x6b4528), wood2: hex(0x9a6a3c),
    sign0: hex(0xb99a62), sign1: hex(0xe8d9a8),
    lamp0: hex(0xf08a30), lamp1: hex(0xffd36a),
    shade: hex(0x1e2f4a), // darkest entry: shadowed areas snap to it
  };

  const LAMP = [0.9, 2.8, 0];

  // Ground: one flattened ellipsoid, top face only. `filter` drops splats but not their
  // share of the budget, so `areaFrac` says how much of the surface is kept (about half).
  addPart({
    name: 'ground', size: 0.05, coverage: 3, areaFrac: 0.5, caster: false, pickable: false,
    prims: [prim(ellipsoid(4.5, 0.9, 4.5), { pos: [0, -0.8, 0] })],
    filter: (p, n) => n[1] > 0.2,
    colorFn: (p) => {
      const g = fbm(p[0] * 0.8, 0, p[2] * 0.8);
      if (Math.hypot(p[0], p[2]) < 0.9 + 0.5 * noise(p[0] * 3, 0, p[2] * 3)) return mix3(C.dirt1, C.dirt2, g); // worn patch under the post
      return mix3(mix3(C.grass0, C.grass1, smooth(0.3, 0.6, g)), C.grass3, smooth(0.6, 0.85, noise(p[0] * 5, 1, p[2] * 5)));
    },
  });

  // Static part: the post and its lantern arm. A part is one smooth union of prims
  // (k = blend radius) and moves rigidly. The lantern is emissive, so it is not baked.
  const post = addPart({
    name: 'post', k: 0.05, size: 0.02, band: 0.03, coverage: 4,
    prims: [
      prim(box(0.12, 1.5, 0.12, 0.03), { pos: [0, 1.5, 0], tag: 'wood' }),
      prim(box(1.1, 0.07, 0.07, 0.02), { pos: [0, 2.9, 0], tag: 'wood' }),
      prim(sphere(0.2), { pos: LAMP, color: C.lamp1, emissive: 1, tag: 'lamp' }),
      prim(cylinder(0.2, 0.04), { pos: [0.9, 3.08, 0], tag: 'wood' }),
    ],
    colorFn: (p, n, q) => (q.tag === 'lamp' ? q.color : mix3(C.wood0, C.wood2, noise(p[0] * 6, p[1] * 2, p[2] * 6))),
  });

  // Animated child part: `parent` makes its matrix relative to the post, `local` rewrites
  // that matrix every frame. The prims are built around the hinge at the part's origin.
  // `dynamic` keeps it out of the baked shadows of everything else, since it moves.
  addPart({
    name: 'sign', parent: post, dynamic: true, size: 0.02, band: 0.03, coverage: 4,
    prims: [prim(box(0.45, 0.32, 0.035, 0.01), { pos: [0, -0.42, 0] })],
    colorFn: (p) => (Math.floor(p[1] * 9) % 3 === 0 ? C.sign0 : C.sign1),
    local: (t, M) => M.makeRotationX(Math.sin(t * 1.3) * 0.18).setPosition(-0.65, 2.88, 0),
  });

  const sun = [-0.55, 0.7, 0.45], sl = Math.hypot(...sun);
  return {
    palette: Object.values(C),
    bgTop: C.skyTop, bgBottom: C.skyLow,
    // sun.dir points from the scene toward the sun and must be normalised.
    sun: { dir: sun.map((v) => v / sl), col: [0.9, 0.78, 0.6], reach: 10 },
    // Ambient is sky (up-facing) to ground (down-facing). Keep it around 0.3-0.5 so
    // shadows stay readable instead of black.
    sky: [0.4, 0.47, 0.58], ground: [0.22, 0.18, 0.12], aoMin: 0.4,
    lights: [{ pos: LAMP, col: [1.0, 0.68, 0.3], power: 2.2, k: 0.9 }],
    fog: { col: C.skyLow, density: 0.006, start: 7 },
    rim: [0, 0, 0],
    camera: { pos: [8.5, 5.5, 11], target: [0, 1.6, 0] },
  };
}
