// Screenshot a SyntaxSplat scene so an author (human or AI) can look at it.
// Serves nothing: start a static server in the project root first.
// Exit code is non-zero on console errors, page errors or a load timeout.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const HELP = `usage: node tools/shoot.mjs --scene <id> --out <file.png> [options]
  --url <base>     server base URL (default http://localhost:8137)
  --soft           untick "Pixel art"
  --size <n>       Splat size slider (default: page default)
  --rows <n>       Pixel rows slider (default: page default)
  --explode <n>    Explode slider, 0..1
  --orbit <deg>    rotate the camera around the target; positive = camera moves right
  --elev <deg>     raise (positive) or lower (negative) the camera
  --still          untick Animate so the shot shows the t=0 rest pose
  --noui           hide the control panel in the shot
  --budget         also print planned splats and prim count per part, largest first
  --wait <s>       seconds to wait after load and settings (default 2)
  --timeout <s>    seconds to wait for the bake (default 180)`;

const flags = new Set(['soft', 'still', 'noui', 'budget', 'help']);
const args = {};
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (!a.startsWith('--')) { console.error(`unexpected argument: ${a}\n${HELP}`); process.exit(2); }
  const key = a.slice(2);
  if (flags.has(key)) args[key] = true;
  else if (i + 1 < argv.length) args[key] = argv[++i];
  else { console.error(`--${key} needs a value\n${HELP}`); process.exit(2); }
}
if (args.help || !args.scene || !args.out) { console.log(HELP); process.exit(args.help ? 0 : 2); }

const num = (key, fallback) => {
  if (args[key] === undefined) return fallback;
  const v = Number(args[key]);
  if (!Number.isFinite(v)) { console.error(`--${key} must be a number, got "${args[key]}"`); process.exit(2); }
  return v;
};
const base = (args.url || 'http://localhost:8137').replace(/\/+$/, '');
const out = resolve(args.out);
const waitS = num('wait', 2), timeoutS = num('timeout', 180);
const orbit = num('orbit', 0), elev = num('elev', 0);
const W = 1920, H = 1080;

const errors = [], warnings = [];
let built = '';
const browser = await chromium.launch({
  channel: 'msedge', headless: false,
  args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', `--window-size=${W},${H + 120}`],
});

let loaded = false;
try {
  const page = await (await browser.newContext({ viewport: { width: W, height: H } })).newPage();
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(`console error: ${m.text()}`);
    else if (m.type() === 'warning') warnings.push(`console warning: ${m.text()}`);
    else if (m.text().startsWith('built ')) built = m.text();
  });
  page.on('pageerror', (e) => errors.push(`page error: ${e.message}`));

  await page.goto(`${base}/?scene=${encodeURIComponent(args.scene)}`);
  try {
    await page.waitForSelector('#load', { state: 'detached', timeout: timeoutS * 1000 });
    loaded = true;
  } catch {
    errors.push(`load timed out after ${timeoutS} s: #load never left the page (bake unfinished or the scene failed to build)`);
  }

  if (loaded) {
    const set = (id, value) => page.$eval(`#${id}`, (el, v) => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); }, String(value));
    if (args.soft) await page.uncheck('#pixel');
    if (args.still) await page.uncheck('#anim');
    if (args.size !== undefined) await set('size', num('size'));
    if (args.rows !== undefined) await set('rows', num('rows'));
    if (args.explode !== undefined) await set('explode', num('explode'));

    if (orbit || elev) {
      // OrbitControls turns a drag of the window height into 360 degrees. Dragging
      // right moves the camera to the left, dragging down raises it.
      const dx = -orbit / 360 * H, dy = elev / 360 * H;
      const x0 = W / 2 - dx / 2, y0 = H / 2 - dy / 2;
      await page.mouse.move(x0, y0);
      await page.mouse.down();
      await page.mouse.move(x0 + dx, y0 + dy, { steps: 20 });
      await page.mouse.up();
      // Damping applies the rotation over many frames; wait until it has settled.
      const fps = await page.evaluate(() => parseFloat((document.getElementById('hud').textContent.match(/([\d.]+) fps/) || [])[1]) || 30);
      await page.waitForTimeout(Math.max(3, 250 / Math.max(fps, 5)) * 1000);
    }
    await page.waitForTimeout(waitS * 1000);

    let budget = '';
    if (args.budget) {
      // Same module instance main.js uses, so the parts list is the loaded scene.
      const rows = await page.evaluate(async () => {
        const e = await import(new URL('./engine.js', location.href).href);
        const planned = new Map();
        for (const t of e.planTasks()) planned.set(t.part, (planned.get(t.part) || 0) + t.count);
        return e.parts.map((p) => ({ name: p.name, prims: p.prims.length, splats: planned.get(p.index) || 0 }));
      }).catch((err) => { errors.push(`--budget failed: ${err.message}`); return []; });
      rows.sort((a, b) => b.splats - a.splats);
      budget = ['planned splats / prims per part', ...rows.map((r) => `${String(r.splats).padStart(8)} ${String(r.prims).padStart(5)}  ${r.name}`)].join('\n');
    }

    const hud = await page.$eval('#hud', (el) => el.textContent);
    mkdirSync(dirname(out), { recursive: true });
    if (args.noui) await page.evaluate(() => { document.getElementById('ui').hidden = true; });
    await page.screenshot({ path: out });
    console.log(`saved ${out}`);
    if (built) console.log(built);
    console.log(hud.trim().split('\n').slice(0, 2).join('\n'));
    if (budget) console.log(budget);
  }
} finally {
  await browser.close();
}

for (const w of warnings) console.log(w);
for (const e of errors) console.log(e);
if (errors.length) { console.log(`FAILED: ${errors.length} error(s)`); process.exit(1); }
console.log('ok: no console or page errors');
