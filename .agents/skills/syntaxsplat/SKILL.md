---
name: syntaxsplat
description: Write procedural Gaussian-splat scenes as code with SyntaxSplat — SDF primitives grouped into rigid, animated parts, sampled into brush-stroke splats with baked lighting, drawn in the browser with an optional pixel-art palette pass, and exported as standard 3DGS .ply files. Use when the person wants a splat scene, diorama or animated vignette made from a prompt, a stylised pixel-art or painterly 3D scene without meshes or textures, a procedural .ply Gaussian splat, or to edit or debug a SyntaxSplat scene. Not for splats captured from photos or video, mesh modeling (use blender-3d-modeling), or image-to-3D (use image-to-sculpt).
---

# SyntaxSplat

Vendored from [iamvillain/SyntaxSplat](https://github.com/iamvillain/SyntaxSplat) (MIT, see [vendor/LICENSE](vendor/LICENSE)). It's a small browser app (plain ES modules, no build step), not a library: a scene is one JS module in `scenes/`.

## Read first

1. [vendor/syntaxsplat/UPSTREAM-CLAUDE.md](vendor/syntaxsplat/UPSTREAM-CLAUDE.md): upstream's rules for an agent working on scenes (stored under this name so it isn't loaded as this repo's CLAUDE.md).
2. [vendor/syntaxsplat/docs/AUTHORING.md](vendor/syntaxsplat/docs/AUTHORING.md): API, art direction, pitfalls, the 10-step workflow and the screenshot checklist. Follow it.
3. [vendor/syntaxsplat/docs/RENDERER_FEATURES.md](vendor/syntaxsplat/docs/RENDERER_FEATURES.md): live lights, wind, particles, `.ply` export, look controls. Only once the baked scene is right.

`scenes/_template.js` is the starter; `scenes/reef.js` is the finished example to learn from.

## Setting up a working copy

Never author scenes inside `vendor/` (it is overwritten by the sync). Copy the app to a folder outside this repo, for example the person's project folder:

```
cp -R .agents/skills/syntaxsplat/vendor/syntaxsplat <dest>/syntaxsplat
mv <dest>/syntaxsplat/UPSTREAM-CLAUDE.md <dest>/syntaxsplat/CLAUDE.md
```

Then work from `<dest>/syntaxsplat`, where every upstream path (`scenes/`, `tools/shoot.mjs`, `docs/`) resolves as written. If a working copy already exists, reuse it; don't overwrite the person's scenes.

- Serve: `python -m http.server 8137` in that folder, as a background command. It can't run from `file://`.
- Screenshots: `cd tools && npm install` once, then `node tools/shoot.mjs --scene <id> --out shots/<id>-pixel.png --budget`. Needs Node 18+ and Microsoft Edge (Playwright drives the installed Edge, no browser download). It opens a visible Edge window; tell the person not to touch it while it runs.
- The page loads three.js 0.160.0 from jsdelivr, so it needs internet. Browser needs WebGL2, float textures and module workers.
- Upstream's `screenshots/` folder (4.6 MB of README images) isn't vendored, so the README's image links don't resolve here. Write shots to your own folder (`shots/` above).

## Local overrides

- **Look at every shot.** Open the PNG with the Read tool and judge it against the AUTHORING checklist before calling a scene done; exit code 0 only means it loaded. Show the final pixel and soft shots to the person.
- Don't change `engine.js`, `main.js`, `worker.js` or `index.html` to make a scene work. If a scene needs an engine change, say so and ask first.
- Scene files run in bake workers too: no `Math.random`, no DOM, use `mulberry32`. Add the scene to `scenes/index.json` before the first shot.
- Stop the background http server when done.
- For `.ply` export: it's +Y up; most capture-style viewers expect +Y down, so warn the person it may appear upside down until rotated 180° about X.

## Trust

`vendor/` is synced daily from upstream through a reviewed pull request (see README). Don't edit it here. Put local notes in this file.
