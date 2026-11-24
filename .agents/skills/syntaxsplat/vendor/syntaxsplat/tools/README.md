# tools

`shoot.mjs` loads a scene in a real browser and saves a full-window PNG, so an author
(human or AI) can look at the scene. It also prints the HUD line (splat count, part
count, fps, build time) and every console and page error, and exits non-zero when
there are any or the bake does not finish.

## Install

Needs Node 18 or newer and Microsoft Edge. Playwright drives the installed Edge, so
no browser download is needed.

```
cd tools
npm install
```

## Use

Serve the project root first, in a second terminal:

```
python -m http.server 8137
```

Then, from the project root:

```
node tools/shoot.mjs --scene reef --out screenshots/reef-pixel.png
```

| Flag | Meaning |
|---|---|
| `--scene <id>` | Scene id, as in `?scene=<id>`. Required. |
| `--out <file>` | PNG path. Parent folders are created. Required. |
| `--url <base>` | Server base URL. Default `http://localhost:8137`. |
| `--soft` | Untick "Pixel art". |
| `--size <n>` | Splat size slider. The page default is 1.8. |
| `--rows <n>` | Pixel rows slider, 90 to 540. The page default is 360. |
| `--explode <n>` | Explode slider, 0 to 1. |
| `--orbit <deg>` | Rotate the camera around the target. Positive moves the camera to the right. |
| `--elev <deg>` | Raise (positive) or lower (negative) the camera. |
| `--still` | Untick Animate, so the shot shows the t = 0 pose that the light was baked in. |
| `--noui` | Hide the control panel in the shot. |
| `--budget` | Also print the planned splat count and prim count of every part, largest first. |
| `--wait <s>` | Seconds to wait after the bake and settings. Default 2. |
| `--timeout <s>` | Seconds to wait for the bake. Default 180. |

`--orbit` and `--elev` drag the mouse on the canvas, so they need no change to the
project source. The camera is damped, so the script waits for the move to settle.

The viewport is 1920x1080 and the browser window is visible, because headless Chromium
can produce a blank canvas on this setup. Do not touch the window while it runs.

The script prints `ok: no console or page errors` and exits 0 on success. On failure it
prints each error, then `FAILED`, and exits 1. A scene id the page does not know loads
the default scene instead of failing, so check the part count in the HUD line.
