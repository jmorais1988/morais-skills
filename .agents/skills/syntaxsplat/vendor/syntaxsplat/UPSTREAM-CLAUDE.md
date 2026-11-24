# SyntaxSplat

Browser tech demo: scenes are written as SDF primitives grouped into rigid parts. Workers
sample Gaussian splats on the surfaces and bake the lighting into them, and `main.js` draws
them with an optional palette pixel-art pass. No build step; plain ES modules.

## Making a scene from a prompt

Read `docs/AUTHORING.md` first and follow its workflow. Start from `scenes/_template.js`
and copy it to `scenes/<id>.js`. `scenes/reef.js` is a finished example.

## Serve and shoot

```
python -m http.server 8137                  # project root, in the background
(cd tools && npm install)                   # once; needs Microsoft Edge
node tools/shoot.mjs --scene <id> --out screenshots/<id>-pixel.png --budget
```

Useful flags: `--soft`, `--orbit <deg>`, `--elev <deg>`, `--still`, `--wait <s>`,
`--url <base>`. See `tools/README.md`. The script prints the HUD line and every console
error, and exits non-zero on errors or a bake that does not finish. If port 8137 is taken,
serve on another port and pass `--url`.

## Rules

- A scene is not done until its screenshot has been looked at (open the PNG with the Read
  tool) and judged against the checklist in `docs/AUTHORING.md`. A clean exit code only
  means it loaded.
- Scene files run in the bake workers as well as on the page: no `Math.random`, no DOM.
  Use `mulberry32`.
- Do not edit `engine.js`, `main.js`, `worker.js` or `index.html` to make a scene work
  without saying so in your reply. If a scene needs an engine change, report it.
- Add a new scene to `scenes/index.json` (`{ "id", "title" }`) before the first shot. A scene that is not listed does not load.
- Renderer options such as live lights, wind and particles are in
  `docs/RENDERER_FEATURES.md`, if that file exists.
