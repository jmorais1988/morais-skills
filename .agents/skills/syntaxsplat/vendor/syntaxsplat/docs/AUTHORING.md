# Authoring scenes

How to write a scene file for SyntaxSplat. A scene is a JavaScript module in `scenes/` that
builds a list of SDF parts and returns a config. Everything here was read from
`engine.js`, `main.js` and `worker.js`; the numbers in the art-direction section come
from `scenes/horror.js` and `scenes/island.js`.

Start from `scenes/_template.js`. Look at the result with `tools/shoot.mjs`
(see [Workflow](#9-workflow)).

## 1. Mental model

1. **Primitives.** A shape (`sphere`, `box`, ...) is a signed distance function (SDF).
   `prim(shape, { pos, rot, color, ... })` places it. Units are world units; +y is up.
2. **Parts.** `addPart({ prims, ... })` takes the smooth union of a list of prims. A part
   is a rigid body with a 4x4 matrix, an optional parent and an optional per-frame
   `local(t, M)` function that rewrites that matrix. A scene is 20 to 100 parts.
3. **Splats.** At load, each part is covered with small oriented brush-stroke splats placed
   on its surface. The count comes from the part's surface area, `size` and `coverage`.
4. **Baked light.** Each splat is lit once, in the pose the rig has at `t = 0`: hemisphere
   ambient with ambient occlusion, a sun with soft shadows, and point lights. The result
   is stored in the splat's colour. Emissive prims skip this.
5. **Rig.** Every frame the page recomputes the part matrices from `local(t, M)` and the
   parent chain and draws the splats through them. Splats move rigidly with their part.
6. **Pixel pass.** With "Pixel art" on, the image is drawn at `rows` pixel rows, dithered,
   and every pixel is snapped to the nearest palette colour.

**Frozen at bake time:** colour, light, shadow, ambient occlusion, the surface itself.
**Changes at run time:** part matrices, and the per-part effects `wobble`, `opacity`,
`pulse`, `fog` and `rim`. Nothing deforms: a bending thing is a chain of rigid parts.

Scene code runs on the page **and in every bake worker**; each rebuilds the scene and
samples part chunks, so the parts must come out identical in all of them. See
[pitfall k](#8-pitfalls).

## 2. File shape

```js
import { prim, sphere, box, addPart, noise, mix3, hex } from '../engine.js';

export default function build() {
  const C = { /* palette entries as hex() colours */ };
  // ... addPart() calls ...
  return { palette, bgTop, bgBottom, sun, sky, ground, aoMin, lights, fog, rim, camera };
}
```

`engine.js` exports: the helpers, the shapes, `prim`, `rawPrim`, `limb`, `curve`,
`catmull`, `addPart`, and `THREE` (for `Matrix4`, `Euler`, `Vector3`). It exports no
vector maths; write small `add`/`sub`/`norm`/`cross` helpers in the scene file.

Draw order does not matter: all splats are depth-sorted together every frame. Parts
must be added **parents first**. The limit is **128 parts**; the page throws above
that.

## 3. API reference

Colours are `[r, g, b]` with channels 0 to 1 (values above 1 are allowed and brighten).
Colour management is off: there is no sRGB conversion, so `hex(0x4a8a3a)` is shown as
written when lit by exactly 1.

### 3.1 Helpers

| Function | Returns | Notes |
|---|---|---|
| `hex(0xRRGGBB)` | `[r,g,b]` | `hex(0x3c6b3a)` |
| `mix3(a, b, t)` | colour | linear blend, `t` not clamped |
| `lerp(a, b, t)` | number | |
| `clamp(x, lo, hi)` | number | |
| `smooth(a, b, x)` | 0..1 | smoothstep. `a > b` is allowed and reverses it: `smooth(0.55, -0.8, z)` |
| `noise(x, y, z)` | 0..1 | value noise, one feature per unit. Mean about 0.5. Scale the inputs: `noise(p[0]*4, p[1]*4, p[2]*4)` |
| `fbm(x, y, z, octaves = 3)` | 0..1 | sum of noise octaves, each at 2.03x frequency and half amplitude |
| `mulberry32(seed)` | `() => 0..1` | seeded generator. The only allowed source of randomness |

### 3.2 Shapes

Each returns an SDF in its own space, centred on the origin, y up.

| Shape | Arguments | Notes |
|---|---|---|
| `sphere(r)` | radius | |
| `ellipsoid(rx, ry, rz)` | radii | |
| `box(hx, hy, hz, r = 0)` | half extents, corner radius | `r` rounds the edges inside the half extents |
| `cylinder(r, h)` | radius, **half** height | axis is y |
| `capsule(r, h)` | radius, **half** length of the straight part | axis is y; total height `2h + 2r` |
| `cone(h, r1, r2)` | **half** height, bottom radius, top radius | `r2 = 0.02` for a point. Axis is y |
| `torus(R, r, { n, amp })` | ring radius, tube radius | ring lies in the xz plane. `n` ribs of relative depth `amp` around the tube |

### 3.3 `prim(shape, options)`

Places a shape. Returns a prim object to put in a part's `prims` list.

| Option | Default | Meaning |
|---|---|---|
| `pos` | `[0,0,0]` | position in the part's local space |
| `rot` | none | Euler angles in radians, `[x, y, z]`. A fourth entry sets the order: `[0.2, 1, 0, 'YXZ']`. A rotated prim gets a larger bounding sphere |
| `color` | `[1,1,1]` | albedo |
| `colorFn` | none | `(lp, n, q, rng) => colour`, see 3.6. Used when the part has no `colorFn` |
| `emissive` | 0 | `true` = 1, or a multiplier. Colour is multiplied by it and the light bake is skipped |
| `tag` | `''` | free label; read it back as `q.tag` in a `colorFn` or `filter` |

`prim(sphere(0.3), { pos: [0, 1, 0], color: C.red, tag: 'berry' })`

### 3.4 Free-form prims

| Function | Meaning |
|---|---|
| `rawPrim(sdf, min, max, options)` | Your own SDF `(x, y, z) => distance` in part-local space, with its bounding box corners `min` and `max`. Same options as `prim` except `pos`/`rot`. Use it for height-field terrain and domes. Keep the SDF close to a true distance (scale a height-field difference by about 0.75) |
| `limb(a, b, r1, r2, { rib, freq, phase, ...primOptions })` | Tapered capsule from point `a` to point `b`, radius `r1` to `r2`. `rib` is a relative ripple depth and `freq` its frequency in radians per unit length: rings along a hose or a bone |
| `curve(points, r1, r2, options)` | Returns an **array** of limbs along a polyline. Radius goes `r1` to `r2` by arc length and the ripple phase is continuous. Spread it: `prims.push(...curve(pts, 0.1, 0.02))` |
| `catmull(points, sub = 2)` | Smooth a control polyline: `sub` points per segment. Returns `(n-1)*sub + 1` points. Feed it to `curve` |

`limb([0,0,0], [0,1,0], 0.1, 0.02, { rib: 0.2, freq: 30, color: C.bone })`

`curve(catmull([[0,0,0],[1,1,0],[2,1.5,0.5]], 3), 0.12, 0.02, { tag: 'arm' })`

### 3.5 `addPart(options)`

Returns the part object (pass it as another part's `parent`; its `sdf(x,y,z)` is also
callable in the part's local space, for placing props on a surface).

| Option | Default | Meaning |
|---|---|---|
| `name` | none | label shown in tools; also the default `group` |
| `prims` | required | list of prim objects. May be `[]` for a pure transform node (an empty part gets no splats; it still moves its children) |
| `k` | 0 | smooth-union radius in world units. 0 = hard union. `0.03` to `0.25` blends prims into one organic form. Prims farther than `k` apart do not blend |
| `size` | 0.026 | splat half-extent in world units, before the 1.5 x 0.75 brush stretch and the page's Splat size slider (default 1.8). The drawn splat is about `size * 1.5 * 1.8` long |
| `coverage` | 6 | average number of overlapping splat footprints at slider 1. Higher = denser and more expensive. The engine default of 6 is high; the scenes use 2 to 4 |
| `band` | 0.05 | thickness of the shell, either side of the surface, in which candidate points are generated, and the scale of the area estimate. Must be smaller than the half-thickness of the thinnest prim, see [pitfall j](#8-pitfalls). Use about `1 x size` for small parts |
| `areaFrac` | 1 | multiplier on the estimated area. Set it to the fraction of the surface your `filter` keeps |
| `count` | 0 | fixed splat count. Overrides the area estimate. Use for huge thin shells (sky domes) and scattered parts |
| `filter` | none | `(lp, n) => boolean` in part-local space; false discards a splat. Discarded splats are replaced, so the budget stays the same and concentrates on the kept surface; reduce it with `areaFrac` |
| `colorFn` | none | `(lp, n, q, rng) => colour`, see 3.6 |
| `dynamic` | false | the part moves. It stops being a shadow caster for other parts, see 4.3 |
| `caster` | true | false = does not cast shadows or occlude ambient light on anything, itself included |
| `pickable` | true | false = a click does not dissolve it |
| `group` | `name` | click-dissolve and dynamic-shading group. Give every part of one moving object (a tentacle chain) the same group |
| `parent` | none | a part returned earlier by `addPart`; this part's matrix is relative to it |
| `matrix` | identity | `THREE.Matrix4` copied in as the starting local matrix: the usual way to place a static part |
| `local` | none | `(t, M) => void` called every frame with time in seconds and the part's local matrix `M`, which it must fully rewrite, see 4.1 |
| `wobble` | 0 | each splat bobs vertically by this many world units, with a phase from its world x and z. Liquid surfaces: 0.01 to 0.04 |
| `opacity` | 1 | alpha multiplier. Mist and haze: 0.05 to 0.1 |
| `pulse` | 0 | brightness oscillation of the whole part: colour times `1 + pulse * sin(...)`. Phase depends on the part index. 0.05 to 0.3 |
| `fog` | 1 | how much of the scene fog applies. 0 for sky objects |
| `rim` | 0 | strength of the rim sheen from `config.rim`. 0.5 to 1 on wet or glassy parts |

`addPart({ name: 'rock', k: 0.1, size: 0.03, coverage: 3, prims: [...], colorFn })`

### 3.6 Colour functions

`colorFn(lp, n, q, rng)` is called once per splat, at bake time.

- `lp`: `[x, y, z]` position in the part's local space.
- `n`: `[x, y, z]` unit surface normal in the part's local space (the SDF gradient).
- `q`: the prim nearest to the point (by its own un-blended distance). Read `q.tag`,
  `q.color`.
- `rng`: the seeded generator, deterministic per chunk. Use it, not `Math.random`.

Return a colour. A part-level `colorFn` wins over a prim-level one, which wins over
`color`. Use `q.tag` to colour parts of one part differently.

```js
colorFn: (p, n, q, rng) => {
  if (q.tag === 'lamp') return q.color;
  const g = noise(p[0] * 5, p[1] * 5, p[2] * 5);
  const base = mix3(C.wood0, C.wood2, g);
  return rng() < 0.01 ? C.sign1 : base;     // sparse specks
}
```

### 3.7 The config object

The default export returns:

| Field | Meaning |
|---|---|
| `palette` | array of colours for the pixel pass. Every colour the lit scene can show must be near an entry |
| `bgTop`, `bgBottom` | sky gradient colours. They are drawn into the same image, so they are snapped to the palette too |
| `sun` | `{ dir, col, reach }`. `dir` points **from the scene toward the sun** and must be normalised. `col` is the sun's light colour and brightness. `reach` is the maximum shadow-ray length |
| `sky` | ambient colour for surfaces facing up |
| `ground` | ambient colour for surfaces facing down. Ambient is `lerp(ground, sky, 0.5 + 0.5 * normal.y)` |
| `aoMin` | ambient-occlusion floor, 0..1. The ambient is multiplied by `aoMin + (1 - aoMin) * clamp(d / 0.15, 0, 1)`, where `d` is the scene distance 0.15 units out along the normal. 0.25 to 0.4 |
| `lights` | array of point lights, see below. May be `[]` |
| `fog` | `{ col, density, start }`. Fog fraction is `1 - exp(-density * max(0, distance - start))`. `density: 0` turns it off |
| `rim` | colour `[r, g, b]` of the rim sheen. `[0,0,0]` turns it off |
| `camera` | `{ pos, target }`. The field of view is fixed at 35 degrees, near 0.1, far 200 |

Point light: `{ pos, col, power, k, shadow, radius }`.

| Field | Meaning |
|---|---|
| `pos` | world position at the `t = 0` pose |
| `col` | colour |
| `power` | intensity. Contribution is `power * max(0, n.l) / (1 + k * dist^2)` times `col` |
| `k` | falloff. **Required.** Larger = tighter pool of light. `k = 1` gives half power at 1 unit |
| `shadow` | `true` = soft shadow-tested against the scene. Costs bake time |
| `radius` | shadow rays stop this far short of the light, see [pitfall a](#8-pitfalls). Only used when `shadow` is true |

Lights affect only baked splats. They do not light emissive prims.

## 4. Animation

### 4.1 `local(t, M)`

`t` is time in seconds since the page finished loading; the clock stops while Animate is off. `M` is the
part's own `THREE.Matrix4`. It is **kept between frames**, so set every component each
time. `makeRotationX/Y/Z`, `makeRotationFromEuler` and `makeTranslation` reset the whole
matrix; follow with `.setPosition(x, y, z)`.

The matrix places the part's local origin. For a hinge, build the prims around the hinge
point at the part's origin, and put the hinge's position in `setPosition`.

```js
// A sign that swings on its post. The rotation happens at the hinge (the part's origin).
const post = addPart({ name: 'post', prims: [prim(box(0.1, 1.5, 0.1), { pos: [0, 1.5, 0], color: C.wood })] });
addPart({
  name: 'sign', parent: post, dynamic: true,
  prims: [prim(box(0.45, 0.3, 0.03), { pos: [0, -0.4, 0], color: C.sand })],   // hangs below the hinge
  local: (t, M) => M.makeRotationX(Math.sin(t * 1.3) * 0.18).setPosition(-0.65, 2.9, 0),
});
```

### 4.2 Parent chains

World matrix = `parent.world * M`. A child's `setPosition` is in the parent's local
space. Chains of rigid segments make jointed things: each segment of a tentacle is a
child of the one below, placed at `(0, lengthOfParent, 0)` and rotated by an angle that
follows a travelling sine, e.g. `Math.sin(t * 0.9 + phase - k * 0.75)`. Use one `group`
for the whole chain.

### 4.3 What `dynamic` changes

Light is baked against the `t = 0` pose. A part can be:

- **static** (`dynamic: false`, the default): it is part of the baked scene. Its shadow
  and occlusion land on every other part, at its `t = 0` position. If the part later
  moves (`local` animates it), the shadow it cast stays behind where it started.
- **`dynamic: true`**: it does not cast shadows or occlusion onto other groups. It is
  shaded by the static scene and by the other dynamic parts of its own `group`.

Mark everything that moves `dynamic: true`. A dynamic part's colour is still the
`t = 0` light, so it keeps that brightness wherever it goes: start it in a lit place.
A part that is fixed in the world but animated only a little (a leaf, a swaying pine)
can stay static if the stale shadow does not matter.

## 5. Colour and the palette

The splat colour is `albedo * light * jitter`, where `light` is

```
ambient (sky/ground by normal.y, times AO)  +  sun.col * n.l * shadow  +  sum of point lights
```

and `jitter` is a random 0.88 to 1.12 per splat. A part's albedo comes from `colorFn`,
or the prim's `colorFn`, or `color`.

- **Emissive prims** (`emissive`) use `colorFn`/`color` times the multiplier and skip all
  of the above. Keep the colour at or under 1 per channel after the multiplier: a channel
  above 1 is clipped, so a hot yellow turns cream-white and then snaps to a pale palette
  entry instead of yellow.
- The final image is clipped to 1. A flat surface facing the sun can have `light` of
  1.0 to 1.5; an albedo above about 0.8 then clips toward white. Keep bright albedos
  out of the strongest light or put a clipped highlight colour in the palette.
- **The pixel pass compares colours with weights 0.3 / 0.59 / 0.11** (r/g/b, squared
  difference) after adding a small ordered dither. Each pixel takes the nearest palette
  entry. The palette therefore has to contain the **lit** colours: build each material as
  a ramp of 4 to 6 steps from shadow to highlight, in the hue that light and shadow
  actually produce. Palettes that list only the albedos give flat posterised blobs, or
  wrong hues where the nearest entry is some other material.
- The background gradient is snapped to the palette. Two palette entries give a dithered
  band; add intermediate sky colours.
- `palette` is just a list. A scene can keep an albedo in its colour table and leave it out of the
  palette when lighting never leaves it unchanged (`reef` filters five such entries out).
- In soft mode (Pixel art off) the palette is ignored and the true colours show.

## 6. Art direction

These are the working practices of the two existing scenes, with their numbers.

**Scale and camera.** Things sit within about 7 to 10 units of the origin (the island is
3.6 units in radius, the `horror` obelisks stand at 7). The camera is 15 to 17 units
from the target with fov 35: `horror` at `[5.7, 3, 15.6]` looking at `[0, 3.9, 0]`,
`island` at `[9.5, 6, 11]` looking at `[0, 1, 0]`. At 15 units the view is about 9.5
units tall, so the main subject should span about a third of that, 3 to 4 units.
The camera looks down 10 to 25 degrees.

**Splat budget.** `island`: 202,000 splats in 2 s. `horror`: 331,000 in 18 to 28 s. `reef`: 344,000
in 12 to 21 s, 89 parts.
Aim for 200,000 to 350,000. Count is about

```
splats = 0.222 * coverage * area / size^2        (area in square units)
```

so halving `size` quadruples the count and doubling `coverage` doubles it. Typical
`size` / `coverage` pairs read from the scenes:

| Kind of object | size | coverage | Example |
|---|---|---|---|
| Ground, water, big flat areas | 0.05 to 0.085 | 2 to 3 | horror ground 0.055 / 2, island water 0.085 / 6 |
| Large hero forms | 0.026 | 2.5 to 4 | horror idol and eye |
| Medium props, ribs, tentacle segments | 0.022 to 0.032 | 2.5 to 3 | |
| Small props and figures | 0.012 to 0.018 | 3 to 3.5 | cultists 0.013, sheep 0.016, gull 0.012 |
| Haze, mist | 0.3 | `count: 1300`, `opacity: 0.08` | horror mist |
| Star dome | 0.04 | `count: 900` | horror stars |
| Engine defaults | 0.026 | 6 | island pines, lighthouse |

Use `node tools/shoot.mjs --budget` to see the planned splats per part. One or two big
surfaces usually eat half the budget (horror: ground 55,000, idol 38,000, eye 18,000);
make them cheap with a larger `size` and look at the small parts last.

**Parts and prims.** `island` has 17 parts with 1 to 7 prims each. `horror` has 92
parts: a 179-prim idol, nine 53-prim ribs, 56 chain segments of 3 prims each, and
many small one-off parts. Bake time scales with the number of parts near each splat
and the prims in them, not only with the splat count. One part per object, and one
part per independently moving piece.

**Focal point and silhouette.** One hero object near the centre of the frame, lit
brighter and more saturated than the rest, with a readable outline against the
background. Surround it with a ring or arc of secondary forms that lead the eye in
(`horror`: ribs curving over the idol; `island`: the pines framing the lighthouse). Put
the brightest accent colour at the focal point (`horror`: a green eye; `island`: a
yellow lamp).

**Detail.** Large forms alone look like clay. Add, in this order: ribbing and rings
(`limb` with `rib`/`freq`, `torus` with `n`/`amp`), spines and fins (thin `limb`s),
hoses and cables (`curve` through `catmull` points), and scattered small props
(a few dozen small ellipsoids in one part). Add a repeated element with variation
from a seeded `mulberry32`: size, rotation and phase vary by 10 to 30 percent.

**Colour variation.** Never return one flat colour.
- Vary by `noise` at two scales: a low frequency for patches (`noise(x*1.3, ...)`) and a high one for grain (`noise(x*6, ...)`).
- Grade by height: `mix3(low, high, smooth(0, 3.3, p[1]))`.
- Stain and grime: `mix3(c, dark, smooth(0.45, 0.8, noise(...)) * 0.5)`.
- Rare specks with `rng()`: flowers on grass (`rng() < 0.006`).
- Use `q.tag` so each prim kind has its own ramp.

**Lighting recipe.**
- *Key light:* the sun, shadows on. `sun.col` around 0.9 to 1.3 per channel and
  colour-tinted (island `[1.25, 0.86, 0.55]`, horror `[0.55, 0.52, 0.9]`). Put it at
  30 to 60 degrees elevation, off to the side of the camera so shadows fall across the
  view, not directly behind objects (see [pitfall f](#8-pitfalls)). `reach` 7 to 12.
- *Ambient:* coloured, not grey. `sky` 0.3 to 0.62 per channel, a different hue from the
  sun (island `[0.3, 0.4, 0.62]` against warm sun). `ground` black for a dusk look
  (island) or a tint of the bounce colour (horror `[0.1, 0.16, 0.14]`). `aoMin` 0.25 to
  0.35.
- *Accent point lights:* a few coloured lights for local pools of light: `power` 0.6 to
  2, `k` 0.6 to 3 (island lamp: power 1.8, k 1.1; horror lanterns: power 1.1, k 3).
  Use a **complementary** hue to the sun (orange against blue, magenta against green).
- *One shadowed point light* at most (horror eye: `power: 7, k: 0.16, shadow: true,
  radius: 1.5`). Each shadowed light adds roughly a sun's worth of bake time.
- Place an emissive prim and a point light at the same spot for each glowing object.

**Fog, rim, mist, emissive, pulse.**
- `fog`: `horror` uses `density 0.03, start 10` with a dark violet colour, pulling the far
  rim into the background; `island` uses none. Set the fog colour to the background. Use
  `fog: 0` on skies.
- `rim`: a cool or pale colour (horror `[0.35, 0.55, 0.6]`) with `rim: 0.5` to `1` on wet
  or glassy parts gives a sheen at grazing angles.
- Mist: a flat ellipsoid part, `size 0.3`, `count` around 1,300, `opacity 0.08`,
  `caster: false`, `pickable: false`, slow `local` rotation.
- Emissive accents: tiny prims (an eye, a lamp, runes, vents) in saturated colours.
- `pulse` 0.06 on large glowing parts, 0.3 on small bulbs.

**Palette design.** 24 to 32 colours in 4 to 6 ramps (`island`: 27, `horror`: 32, `reef`: 33). Each
ramp has 4 to 6 steps: a very dark step (the shadow colour, hue-shifted toward the
ambient), two mids, a light, and for the main ramp a highlight. Include the sky and
background colours and every emissive colour as exact entries. Build the lighting first,
shoot with a generous palette, then trim.

## 7. Recipes

Patterns the existing scenes use. All are plain JavaScript on top of the API above.

**Terrain you can stand things on.** Build a height function, sample it once into a grid,
and use the grid for both the ground SDF and for placing props. Scale the height difference
by about 0.75 so the SDF stays a fair distance estimate.

```js
const G = 257, EXT = 9.6, hm = new Float32Array(G * G);
for (let j = 0; j < G; j++) for (let i = 0; i < G; i++) hm[j * G + i] = hRaw(-EXT + i / (G - 1) * 2 * EXT, -EXT + j / (G - 1) * 2 * EXT);
const gh = (x, z) => { /* bilinear lookup in hm, clamped to the grid */ };
addPart({ name: 'ground', prims: [rawPrim((x, y, z) => Math.max((y - gh(x, z)) * 0.75, Math.hypot(x, z) - 9.4), [-9.4, -2.5, -9.4], [9.4, 1, 9.4])], filter: (p, n) => n[1] > 0.25 });
```

Place a static prop with `matrix: new THREE.Matrix4().makeRotationY(yaw).setPosition(x, gh(x, z), z)`
and build its prims around its own origin. `hRaw` must use only `noise`/`fbm`/`Math`.

**Hollow shapes.** Subtract a bore with `rawPrim`: `Math.max(outer, -bore)`, where `outer` and
`bore` are SDFs that are negative inside. A tube with an open top:
`outer = max(hypot(x, z) - r, abs(y - cy) - hh)`, `bore = max(hypot(x, z) - 0.6 * r, topY - 0.7 - y)`.
Keep the wall thicker than `2 * band`.

**Lattice and holes in a thin plate.** `Math.max(plate, (Math.abs(Math.sin(x * 12) * Math.sin(y * 12)) - 0.4) * 0.05)`
removes material where the product is large. Keep the multiplier small so the SDF stays usable.

**Grooved or bumpy surfaces.** Add a noise term to an SDF: `dome.base(x, y, z) + 0.03 * smooth(0.07, 0, Math.abs(noise(x * 3.4, y * 3.4, z * 3.4) - 0.5))`
cuts winding grooves along the 0.5 contour of the noise. Use the same expression in `colorFn`
to darken the grooves. Keep the amplitude under about 0.04.

**Branching growth.** A recursive function that calls `limb` from a point along a direction, then
recurses 2 to 4 times with shorter length (x0.74), thinner radius (x0.74) and a random spread from a
seeded `mulberry32`. Stop at depth 3 or 4, tag the last level `'tip'`, and put all of it in one part
with `k: 0.05`.

**Jointed chain.** One part per segment, each `parent`ed to the one below, same `group`, `dynamic: true`.
A segment's prims run from its origin to `[0, L, 0]` and the next segment sits at `setPosition(0, L, 0)`.
Drive each joint with `rest + amp * Math.sin(t * w + phase - k * 0.8)`.

**Rising bubbles.** One part of 4 or 5 spheres stacked 1 unit apart, translated by
`(t * 0.45 + phase) % 1`. Each time the offset wraps, every sphere is the previous one, so the stack
rises forever. `emissive` colour, `opacity` 0.6, `rim: 1`, `caster: false`.

**Light shafts.** A long thin `limb` along `sun.dir` from the ground up toward the sun, emissive and
pale, `opacity: 0.06`, `caster: false`, `size: 0.18`, a fixed `count` of about 1,500. Four of them
give the underwater look in `reef`.

**Particles.** A part of many tiny emissive spheres with a fixed `count`, `opacity` 0.5, `dynamic: true`
and a slow `local` rotation. Keep them off the foreground floor: against sand they look like dirt.

**Self-bright small things.** A fish or a bead is lit at about 0.6, so its albedo can be above 1:
`[c[0] * 1.5, c[1] * 1.5, c[2] * 1.5]`. Without this, orange small creatures go brown.

## 8. Pitfalls

Each of these has caused a broken scene.

- **a. A shadow-casting point light inside or near geometry goes dark.** The shadow ray
  from a surface to the light ends at `distance - radius`, and any occluder it meets
  before that blocks the light. A light inside a lamp, an eye or a pot is blocked by
  that object. Set `radius` larger than the occluders around the light (horror: eye
  radius 0.95, light radius 1.5). Lights without `shadow: true` are never blocked.
- **b. Anything seen from inside needs an inverted SDF.** A splat is hidden when its
  normal faces away from the camera, and the normal is the SDF gradient, which points
  out of the surface. A sky dome built as `R - length(p)` (negative outside, so the
  gradient points inward) faces the camera; `length(p) - R` is culled away. Same for
  rooms and caves. `rawPrim((x, y, z) => 60 - Math.hypot(x, y, z), [-60, 4, -60], [60, 60, 60])`.
- **c. Scenes come out too dark when ambient is low.** Lit colour is albedo times the
  light, and the palette snap makes dark values go to the darkest entry. Start with
  `sky` of `[0.4, 0.45, 0.6]`, `ground` of about 0.2, `aoMin` 0.35 and a sun of about 1.0.
  A scene lit only by a dim sun and weak lights reads as black. Check the dark half of
  the first screenshot before anything else.
- **d. Splat counts explode and bake time follows.** Count goes with `coverage / size^2`,
  and bake time with `count * (1 + shadowed lights) * nearby parts`. Halving `size`
  quadruples the cost. Check `--budget` after adding any part with a `size` under 0.02.
- **e. Moving parts.** A part that moves but is not `dynamic` leaves its baked shadow
  on the ground where it started. A `dynamic` part casts no shadow on the rest of the
  scene at all. Choose per part: large things that move slowly and matter to the shading
  stay static; everything else that moves is `dynamic`. A dynamic part keeps its `t = 0`
  lighting, so do not start it in a shadow.
- **f. The camera can be blocked.** Foreground geometry can fill the frame, and it can
  sit between camera and subject. The default view is the one people see first. Check the
  shot, and shoot `--orbit 40` and `--orbit -40` too.
- **g. Tiny features vanish at 360 pixel rows.** One pixel is about
  `0.0017 * distance` world units (0.028 at 16 units). A feature must be 3 to 4 pixels
  across, about 0.1 units, to read; thin lines need 2 pixels. Make eyes, spines and
  whiskers thicker than they are in life, or accept that they only show in soft mode.
- **h. Dark albedo under dim light is black.** `albedo * light` multiplies: 0.2 times a
  0.3 shade is 0.06. Dark materials need either brighter light or a lighter albedo, and
  a palette entry near the result.
- **i. Huge thin shells need `count`.** The area estimate probes 4,000 random points in
  the part's bounding box. For a 120-unit star dome, almost none fall in the shell, so
  the estimate is near zero. Set `count` (horror stars: 900). The same holds for any
  part whose prims are scattered across a mostly empty box.
- **j. Thin parts need a small `band`.** The estimate treats a thickness of `2 * band`
  around the surface as the shell. A fin or leaf thinner than that fills the shell, so
  the estimated area is wrong and the part gets too few splats. Make `band` smaller than
  half the part's thinnest prim: 0.01 to 0.02 for small props.
- **k. Scene code runs in workers too.** Every worker calls your `build()` and must get
  exactly the same parts in the same order, or splats land on the wrong surfaces. Use only
  `mulberry32(seed)` for random numbers, never `Math.random`, `Date` or `performance.now`,
  and nothing from the DOM (`document`, `window`).
- **l. A `filter` does not remove its share of the budget.** Splats are generated until
  the count is reached, so a filter that keeps half the surface doubles the density
  there. Set `areaFrac` to the fraction kept.
- **m. `k` is required on every point light.** Without it the falloff is `NaN`, and every
  splat the light reaches gets a `NaN` colour.
- **n. A scene id the page does not list may load the default scene instead.** Check the
  part count in the HUD line that `shoot.mjs` prints.
- **o. A floor seen at a low angle needs more coverage.** A splat's alpha falls off toward
  its edge, so the effective coverage is well under the stated one, and a surface at a grazing
  angle shows gaps through which the background colour appears as specks. Raise `coverage` to
  about 3.5 (and `size` with it, to keep the count) for a floor that the camera sees at 10 to 20
  degrees. `reef` used 2 and showed cyan specks all over the sand.
- **p. A warm albedo under a strongly coloured ambient changes hue.** Orange under a turquoise
  ambient of `[0.3, 0.55, 0.62]` is olive-brown, not orange. Keep every channel of `sky` at 0.4
  or more, or put warm light on the subject. `reef` ended with `sky [0.6, 0.76, 0.82]`.
- **q. Mid-tones between two ramps snap to a third ramp.** A sand colour blended halfway to blue-grey,
  or a light pink under a warm sun, falls between palette entries and lands on teal or tan. Fade
  by darkening within the material's own ramp, and add a desaturated mid step for each hue.

## 9. Workflow

1. Read this guide.
2. Copy `scenes/_template.js` to `scenes/<id>.js`. Choose a short lowercase id, and add
   `{ "id": "<id>", "title": "<Title>" }` to `scenes/index.json`. A scene that is not in
   the manifest does not load: the page falls back to the first entry.
3. Block in the big forms (ground, hero object, 2 to 4 secondary forms) and the lighting
   (sun, sky, ambient, one accent light). Give it a first generous palette.
4. Serve and shoot:
   ```
   python -m http.server 8137          # in the project root, second terminal
   node tools/shoot.mjs --scene <id> --out screenshots/<id>-pixel.png --budget
   ```
5. **Read the PNG** (the Read tool shows images). Judge it with the checklist below.
6. Fix, in this order: errors printed by the script, darkness, framing and camera,
   splat budget and bake time. Then add detail and colour variation. Shoot after each
   change.
7. Add animation. Shoot twice, several seconds apart (`--wait`), to see motion, and
   once with `--still`.
8. Shoot two or three other angles (`--orbit 45`, `--orbit -45 --elev 15`) and soft mode
   (`--soft`). Fix what breaks.
9. Trim the palette to the colours that show. Shoot the final pixel and soft images.
10. Optional extras, once the baked scene is right: live lights, wind, particles and the
    per-part `outline` flag. Their config fields are in
    [RENDERER_FEATURES.md](RENDERER_FEATURES.md).

The page caches each bake in the browser, keyed on the scene file and `engine.js`, so an
edited scene bakes again by itself. Add `&ui=0` to the URL to hide the control panel.

**Checklist for every screenshot**

- Did the script exit 0 with no errors? Is the part count the one you expect?
- Is any quarter of the image black or mud-coloured? (Too dark: raise `sky`/`sun.col`.)
- Is there one clear focal point, brighter than its surroundings?
- Is anything big in the foreground blocking the subject, or cut by the frame edge?
- Do all of the palette ramps appear, or do some regions snap to the wrong hue?
- Are the shadows visible and falling across the view, not hidden behind objects?
- Are there empty areas of ground or water with no detail?
- Do small features read, or are they a pixel wide?
- Splat count in 200,000 to 350,000, bake under about 25 s?
- Do moving parts leave a ghost shadow, or start in shade?
- In soft mode, do hard edges and splat gaps show?
