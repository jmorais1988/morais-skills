# SyntaxSplat

A browser tool that builds scenes procedurally out of Gaussian splats, with no
meshes or textures, and can export them as standard splat files. Each scene is written as code: signed distance field (SDF) shapes
grouped into rigid parts. The page covers those surfaces with small brush-stroke
splats, bakes the lighting into them, and draws them with an optional pixel-art
palette pass.

Three demo scenes are included: `horror` (a biomechanical idol under an eclipse, the
default), `island` (a lighthouse island at dusk) and `reef` (a sunlit coral reef), plus
`_template`, a small starter scene.

To write a new scene, by hand or by asking Claude for one from a prompt, read
[docs/AUTHORING.md](docs/AUTHORING.md). `tools/shoot.mjs` takes screenshots of a scene from
the command line so the author can check the result.

| | Pixel art | Soft |
|---|---|---|
| Horror | ![horror, pixel art](screenshots/horror-pixel.png) | ![horror, soft](screenshots/horror-soft.png) |
| Island | ![island, pixel art](screenshots/island-pixel.png) | ![island, soft](screenshots/island-soft.png) |
| Reef | ![reef, pixel art](screenshots/reef-pixel.png) | ![reef, soft](screenshots/reef-soft.png) |

Horror with Explode at 0.4:

![horror, explode 0.4](screenshots/horror-explode.png)

## Running it

The demo is plain ES modules, so any static file server will do. It cannot be opened
from `file://` because it uses module workers.

```
python -m http.server 8000
```

Run that in this folder, then open `http://localhost:8000/`. Add `?scene=<id>` to choose a
scene listed in `scenes/index.json`, and `&ui=0` to hide the control panel. three.js 0.160.0 loads from jsdelivr, so the page
needs internet access. The browser must support WebGL2, float textures and module
workers.

The splats are generated the first time a scene loads: about 20 s for horror, 14 s for
reef and 2 s for island, depending on the number of CPU cores. The result is cached in
the browser, so later loads take a fraction of a second until the scene file or
`engine.js` changes.

## Controls

- **Scene**: switch scene (reloads the page).
- **Pixel art**: toggle the low-resolution palette pass.
- **Pixel rows**: vertical resolution of the pixel-art pass.
- **Splat size**: scale every splat.
- **Explode**: push every part apart, as in the click dissolve.
- **Animate**: pause or resume the rig animation.
- **Auto orbit**: rotate the camera slowly round the target.
- **Palette**, **Brush**, **Outline**, **Depth of field**, **Focus**: change the look
  without re-baking.
- **Live lights**, **Particles**: toggle the scene's moving lights and particle emitters.
- **Export .ply**: download the scene in its current pose as a standard 3D Gaussian
  Splatting file.
- **Rebake**: discard the cached bake and build the scene again.
- **Mouse**: drag to orbit, scroll to zoom. A click on an object dissolves it and
  re-forms it about 3 s later.

## How it works

1. **SDF parts.** A scene module returns a config (lights, palette, camera, fog) and
   calls `addPart()` for each rigid piece. A part is a smooth union of SDF
   primitives (sphere, box, cone, limb, torus and so on). It has its own local
   matrix, an optional parent and an optional `local(t, M)` animation function. The
   parts form a rig: a tentacle is a chain of child parts and the sheep's legs are
   children of its body.
2. **Surface sampling.** Each part gets a splat budget from its estimated surface
   area. Random points in the part's bounding box are projected onto the surface
   along the SDF gradient. Each surviving point becomes one splat with a position,
   normal, brush direction, size and colour.
3. **Light bake.** Splat colour is lit once, in the rest pose (t = 0): sky/ground
   hemisphere light, SDF ambient occlusion, a sun with SDF soft shadows, and point
   lights. Emissive primitives skip the bake. The work is split into chunks and
   run in a pool of module workers. Each worker rebuilds the same scene from the
   same seeds.
4. **Splat renderer.** All splats are packed into one float data texture and drawn
   as instanced quads. Each splat stores the index of its part. Every frame, part
   matrices and per-part effects (dissolve, wobble, opacity, pulse, fog, rim) are
   written to a small texture, so parts move as rigid bodies without a re-bake. The
   splats are depth-sorted back to front every frame with a 16-bit counting sort on
   the CPU and alpha-blended.
5. **Pixel pass.** With Pixel art on, the scene is drawn into a low-resolution
   target. A full-screen pass then applies a 4x4 ordered dither and snaps each
   pixel to the nearest colour in the scene's palette.

Because the light is baked in the rest pose, moving parts keep their t = 0 shading
and shadows. Live lights, wind and particles run on top of the bake every frame; see
[docs/RENDERER_FEATURES.md](docs/RENDERER_FEATURES.md).

## Files

| File | Purpose |
|---|---|
| `index.html` | Page, control panel, import map for three.js. |
| `main.js` | Renderer: data-texture splats, per-frame sort, part-matrix texture, pixel pass, click-to-dissolve picking, bake worker pool. |
| `engine.js` | SDF primitives, parts and rig, surface sampling, light bake. No DOM; runs on the page and in workers. |
| `worker.js` | Bake worker: builds the scene, then samples the chunks it is given. |
| `three.js` | Re-exports three.js from its CDN URL, because workers cannot use the import map. |
| `cache.js` | Bake cache in IndexedDB. |
| `export.js` | Writes the `.ply` export. |
| `particles.js` | Particle emitter pools. |
| `scenes/index.json` | List of scenes shown in the dropdown. |
| `scenes/*.js` | The scenes, and `_template.js` to copy from. |
| `docs/AUTHORING.md` | How to write a scene: API, art direction, pitfalls, workflow. |
| `docs/RENDERER_FEATURES.md` | Live lights, wind, particles, export and look controls. |
| `tools/` | `shoot.mjs` screenshot tool (needs Node, Playwright and Edge). |
| `CLAUDE.md` | Instructions for a Claude session working in this folder. |
| `screenshots/` | Screenshots used in this README. |

## Licence

MIT. See [LICENSE](LICENSE).
