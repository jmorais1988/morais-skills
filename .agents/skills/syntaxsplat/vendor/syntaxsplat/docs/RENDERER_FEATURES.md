# Renderer features

New renderer options added on top of the base authoring API. Every field below is
optional and every default reproduces the previous look. Nothing existing was renamed.

## Scene manifest

`scenes/index.json` is the list of scenes: `[{ "id": "horror", "title": "Horrorscape" }, ...]`.
`id` is the file name in `scenes/` without `.js`. The dropdown is built from it, and
`?scene=<id>` only loads an id that is in the manifest (anything else falls back to the
first entry). A new scene file does nothing until it is listed here.

## Bake cache

The baked splat buffer is stored in IndexedDB under the key
`scene id | hash(scene file text) | hash(engine.js text) | SPLAT_FLOATS`. Editing the
scene file or `engine.js` therefore bakes again on the next load and replaces the old
entry. Files the scene imports besides `engine.js` (helpers, other modules) are not
part of the key: use **Rebake** after changing those.

- Panel: **Rebake** clears this scene's entry and reloads. The HUD shows
  `cached, loaded in N ms` or `built in N s`.
- Particles, live lights and wind are not cached; they cost nothing to rebuild.
- If IndexedDB is unavailable or full the scene is simply baked every time.

## Live lights

Up to 4 dynamic point lights, evaluated per splat in the vertex shader from the splat's
stored normal. No shadows. Baked light is untouched; a live light adds
`albedo * colour * power * max(0, n.l) / (1 + k * d^2)` on top of the baked colour.
Emissive splats are skipped, so they are never lit twice. The splat record now stores the
unlit albedo in a 5th texel (`SPLAT_FLOATS` is 20, was 16).

Scene config field:

```js
liveLights: [{
  pos: [x, y, z], col: [r, g, b], power: 0.5, k: 3,
  update: (t, light) => { light.power = 0.5 * (0.4 + 1.2 * noise(t * 7, 0, 0)); }, // optional
}]
```

`update(t, light)` runs every frame with the animation time and may change `pos`, `col`,
`power` or `k` in place. Entries beyond the fourth are ignored with a console warning.

Panel: **Live lights** checkbox (default on).

## Export to .ply

Panel: **Export .ply** downloads `<scene id>.ply`, a binary little-endian 3D Gaussian
Splatting file with the properties `x y z f_dc_0 f_dc_1 f_dc_2 opacity scale_0 scale_1
scale_2 rot_0 rot_1 rot_2 rot_3` (all float32; no normals or higher-order SH).

- Positions are in each part's current animated pose (its world matrix is applied).
  Dissolve and Explode are not applied. Particles are not exported.
- **Axis convention: right-handed, +Y up, exactly as in the scene.** Capture-style viewers
  assume +Y down and show it upside down until rotated 180 degrees about X.
- Colour is the baked lit colour, clamped to 0..1, `f_dc = (c - 0.5) / 0.28209479177387814`.
- Opacity is `logit(0.9 * part.opacity)`, clamped to 0.02..0.98.
- Scales are `log(sigma)`. The tangent and bitangent sigmas are the splat's half-extents
  times the current **Splat size** divided by 2.8. The normal-axis sigma is 15% of the
  smaller of the two, so each splat is a thin disc on the surface.
- Rotation is the quaternion (w, x, y, z) of the frame (tangent, bitangent, normal).

## Look controls

All are panel controls under **Look**. Pixel-pass options (palette, outline) only apply
while **Pixel art** is on.

- **Palette**: the scene's own palette (default) or a preset: 4-shade green handheld,
  black and white, sepia ramp, amber terminal, 16 colours. The shader takes up to 64
  colours; a scene palette longer than that is truncated with a console warning.
- **Brush**: Soft dab (default), Hard disc, Square, Long stroke (the soft dab stretched
  1.8 x 0.6 along tangent and bitangent). Shader only.
- **Outline**: darkens pixels at part-id and depth discontinuities. It costs a second
  low-resolution render of the sorted splats (alpha-tested, writing part id and view
  depth) and only runs while the box is ticked. Parts with `fog: 0` (sky-like parts such as
  stars) are excluded by default. Lines can look busy on sparse, grazing surfaces such as
  large ground splats, since depth is per splat centre.
- **Depth of field** + **Focus**: splats grow and thin out with distance from the focus
  distance (world units from the camera; the slider starts at the initial camera
  distance).

New `addPart` option:

| option | type | default | meaning |
|---|---|---|---|
| `outline` | boolean | `fog !== 0` | whether the part takes part in outlines |

## Wind

New `addPart` option `wind` (number, default 0): how strongly the scene wind leans the
part. Each splat moves downwind in proportion to its local height above the part origin
(`local y`, never negative), with a travelling gust. Splats of the same part move
together, so it suits tall or hanging parts, not per-primitive sway.

Scene config field:

```js
wind: { dir: [1, 0, 0.4], strength: 1, speed: 0.8 }   // dir normalised; strength default 1; speed default 1
```

Displacement is about `strength * wind * height * gust` world units, gust 0.2..1.
No `wind` field in the scene means no wind. Example: `addPart({ name: 'pine', wind: 0.05, ... })`.

## Particles

Scene config field `emitters`, an array. Each emitter owns a fixed pool of
`round(rate * life)` splats (at most 400 per emitter, with a warning). The pool is part of
the same sorted draw and is flown on the GPU from closed-form formulas, so there is no
per-frame upload.

```js
emitters: [{
  pos: [x, y, z],          // origin; default [0, 0, 0]
  part: 'idol',            // optional part (object or name): pos, velocity and gravity are then in that part's frame
  rate: 5,                 // particles per second
  life: 2.5,               // seconds
  velocity: [0, 0.5, 0],   // initial velocity, default [0, 0, 0]
  spread: 0.08,            // random +-spread added to each velocity axis, default 0
  gravity: 0,              // downward acceleration along -y, negative rises; default 0
  size: 0.03,              // splat half-extent before the Splat size slider
  colour: [1, 0.55, 0.2],  // default [1, 1, 1]
  emissive: 1.5,           // optional brightness multiplier on colour (true = 1)
}]
```

Particles are camera-facing, shrink and fade over their life, and are drawn with their
own colour: they are not baked-lit and not live-lit, and `emissive` only scales brightness.
They ignore Explode and dissolve, and are never outlined. Without `part` they live in
world space. Panel: **Particles** checkbox (default on). The animation time drives them,
so **Animate** off freezes them.

## Limits

- At most 128 parts per scene and 255 splat part indices (unchanged).
- At most 4 live lights, 64 palette colours, 400 particles per emitter.
- Live lights, particles and wind change only the live frame, not the cached bake.
