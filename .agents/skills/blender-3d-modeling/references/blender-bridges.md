# Blender Bridges: Detecting, Executing, Returning Data, Screenshots

An agent can reach Blender four ways: MCP tools in its tool list, a raw socket to an add-on inside a running Blender, a headless `blender -b` subprocess, or not at all. This file covers how to find out which one you have, what each can do, and how to run skill scripts, get data back and see images through each. `scripts/bridge_client.py` automates detection, socket exec and CLI runs. `scripts/viewport_capture.py` captures review images in any mode.

## Contents
1. Decision flow
2. The two socket protocols
3. Capability matrix
4. Returning data
5. Running skill scripts per mode
6. Timeouts and long operations
7. Screenshots per mode
8. Safety in a user's live session
9. Executable paths per OS
10. Common failures

## 1. Decision flow

| Step | Check | If yes |
|---|---|---|
| 1 | Tool list contains `execute_blender_code` or `execute_code` (with any client prefix: `Blender:`, `mcp__blender__`, …) | Use the tools. Identify the flavour from the companion tools (§3) and run `python scripts/bridge_client.py detect --no-exe --tools "<comma list>"` |
| 2 | No tools, but a Blender may be running | `python scripts/bridge_client.py detect [--ports 9876,…]`: probes each port within `--timeout` (3 s), identifies the protocol, then sends a read-only probe (version, background, `is_dirty`, VIEW_3D count) |
| 3 | No bridge answers | Same `detect` lists Blender executables (env `BLENDER_PATH`, PATH, known install folders) → headless only: `bridge_client.py run-cli` |
| 4 | Nothing found | Ask the user for the executable path, or ask them to enable the MCP add-on/extension. Don't guess |

- The official extension reads `BLENDER_MCP_HOST/PORT`. The community server reads `BLENDER_HOST/PORT`. `detect` also probes those ports.
- Several bridges can coexist: MCP tools for the user's session plus a CLI for heavy jobs. **One agent owns the live session** (`parallel-work-with-subagents.md` §1).
- Subagents never connect to the user's port. Test against your own instance on another port (§2, last row).

## 2. The two socket protocols

Both default to `localhost:9876`, and only one can own the port. Sending one protocol to the other server **hangs silently**: nothing is wrong on the wire, the server just waits.

| | Official "MCP" extension (Blender Lab, Blender 5.1+) | Community `blender-mcp` add-on (ahujasid) |
|---|---|---|
| Install | Extensions repo `lab.blender.org` → "MCP". Separate MCP server `blmcp` (`pip install git+https://projects.blender.org/lab/blender_mcp.git#subdirectory=mcp`) | `addon.py` installed as a legacy add-on + `uvx blender-mcp` |
| Framing | UTF-8 JSON + `\0`, **one request per connection** (the server closes after replying) | Bare JSON, no delimiter, persistent connection. The reader accumulates bytes until they parse |
| Request | `{"type":"execute","code":"…","strict_json":false}` (`strict_json` bool is required) | `{"type":"execute_code","params":{"code":"…"}}`. Also `get_scene_info`, `get_object_info`, `get_viewport_screenshot`, `ping` |
| Reply | `{"status":"ok","result":{…},"stdout":"…","stderr":"…"}` + `\0`; errors: `{"status":"error","message":"<traceback>"}` | `{"status":"success","result":{"executed":true,"result":"<captured stdout>"}}`; errors: `{"status":"error","message":"Code execution error: <str(e)>"}` (no traceback) |
| Return data | `result` must be a **dict** (anything else is an error) | Only stdout comes back |
| Main thread | `bpy.app.timers` poll, 0.05 s active → 1 s idle interval (add-on prefs) | Socket threads queue commands; a 0.05 s timer drains them |
| Limits | Request ≤ 10 MiB; a client that doesn't finish sending within ~10 s is evicted; `sys.exit`, `wm.quit_blender`, `wm.read_factory_settings/userpref` blocked | MCP-side socket timeout 180 s |
| Headless variant | `blender -b file.blend --online-mode --command blender_mcp --port N` (extension must be enabled, so no `--factory-startup`) | None: refuses to start in background mode |
| Wrong protocol sent | Waits for `\0`, evicts after ~10 s with "Client timed out" | Trailing `\0` never parses, so it waits forever |

**Dual probe** (what `detect` does, one harmless connection): send `{"type":"ping","params":{}}` without NUL. The community add-on answers within ~0.05 s. Otherwise, after ~40 % of the budget, send `\0` and the official server answers `Unknown request type: 'ping'`. Silence means an unknown listener (measured 3.0 s at a 3 s budget). A refused connection is reported as closed.

**Own test instance** (for lanes and script tests): start a GUI `blender --factory-startup --python runner.py` whose timer imports a copy of the extension's `mcp_to_blender_server.py` and calls `start("localhost", 9901)` + `poll()` every 0.05 s. For the community protocol, instantiate `BlenderMCPServer(port=9902)` from `addon.py`. Don't call its `register()`: that auto-starts on 9876. Register the `Scene.blendermcp_use_*` bool props it reads.

## 3. Capability matrix

| Bridge | How to recognise it | Live UI context | Screenshots | Long jobs | Return values |
|---|---|---|---|---|---|
| Official MCP tools | `execute_blender_code`, `execute_blender_code_for_cli`, `get_screenshot_of_area_as_image`, `render_viewport_to_path`, `render_thumbnail_to_path`, `get_objects_summary`, `search_api_docs` | yes | area screenshot tool (PNG, downscaled to fit 1 MB), or code (§7) | deferred `check_is_finished` (interactive only, 1 h cap); CLI tool 120 s | `result` dict |
| Community MCP tools | `execute_blender_code` + `get_scene_info`, `get_object_info`, `get_viewport_screenshot`, `search_polyhaven_assets` | yes | `get_viewport_screenshot` (offscreen draw of the viewport) | blocks; 180 s socket timeout | tool returns `"Code executed successfully: <stdout>"` → print JSON |
| Raw socket (either) | `bridge_client.py detect` | yes (not with `--command blender_mcp`) | code (§7) | blocks UI | per protocol; `bridge_client exec` normalises both to `result` |
| Headless CLI | executable only | **no**: sculpt/paint strokes, gestures and mask/filter ops fail poll or crash (`sculpting.md` §6) | render to file | yes | tagged stdout line |

- The official tool `render_viewport_to_path` renders the **scene camera**, not the viewport, despite its name (details and output path: §7).
- `execute_blender_code_for_cli(blend_file, code)` runs `blender --background <file> --python-expr` from `BLENDER_PATH` (default `blender` on PATH). If the live session has that file open with unsaved changes, it first saves a numbered copy `<file>_mcp_0001.blend`, then deletes it.

## 4. Returning data

- **Convention for all modes:** leave a JSON-serialisable dict in the global `result`. Every `scripts/*.py` in this skill does. Put numbers and paths in it, not Blender objects. With `strict_json=false` the official server `repr`s them, but you can't use a repr.
- **Stdout-only bridges** (community add-on, CLI): end with `print("MYTAG " + json.dumps(result))` and parse the **last** line that starts with the tag. Other prints and Blender's own log lines share stdout. `bridge_client.py` appends `print("__BRIDGE_RESULT__" + json.dumps(result, default=repr))` automatically on those bridges.
- Large payloads: 3 MB strings round-tripped on both protocols (tested). MCP tool results are capped near 1 MB, so write big data (vertex dumps, images) to a file and return the path.
- Errors: official replies carry the full traceback. Community replies carry only `str(e)`, so catch the exception yourself and put `traceback.format_exc()` in `result` when you need line numbers.

## 5. Running skill scripts per mode

| Mode | How |
|---|---|
| MCP tool / socket exec | Send the file text with the options global set first: `VIEWPORT_CAPTURE_OPTS = {...}` + file source → `result`. Without the `*_OPTS` global, scripts only define functions (`result = {"defined": [...]}`) |
| `bridge_client.py exec` | `python scripts/bridge_client.py exec --port 9876 --file scripts/mesh_report.py --opts '{"k": 1}'`. It sets `X_OPTS` (stem upper + `_OPTS`, override with `--opts-name`) and `__file__`, compiles under the real filename so tracebacks show `x.py, line N`, and returns `BRIDGE_CLIENT {"ok", "protocol", "result", "stdout", "elapsed_s"}` |
| Headless script CLI | `blender -b [file.blend] --python scripts/mesh_report.py -- --args` → the last `X <json>` line. Or `python scripts/bridge_client.py run-cli --blend f.blend --script scripts/mesh_report.py -- --args`, which parses the tag for you |
| Headless code snippet | `bridge_client.py run-cli [--factory-startup] --code "import bpy; result = {...}"` (measured 1.3 s for a trivial snippet) |

`--factory-startup` gives a clean, reproducible session (default cube/camera/light when no file is given) but **skips user add-ons and extensions**. Omit it when the job needs them, and never save over the user's file.

## 6. Timeouts and long operations

- Every socket exec runs **on Blender's main thread**. A 10-minute bake freezes the user's UI for 10 minutes, and the MCP client may time out first (community: 180 s) while Blender keeps working. Once the client times out you have lost the result, not the work.
- Rule: interactive exec for anything that finishes in seconds. Bakes, final renders, simulations, big exports and batch audits run as a CLI subprocess on a **saved copy** (`bpy.ops.wm.save_as_mainfile(filepath=copy, copy=True)` from the live session, then `run-cli --blend copy`). Results come back as files.
- Official interactive server: code can start a modal job (`bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)`) and define a global `check_is_finished()` that returns `None` while pending and a dict when done. The reply is deferred up to 1 h. Rejected in background mode.
- Client budgets in `bridge_client.py`: probe 3 s; exec 120 s (`--timeout`); run-cli 600 s. Measured locally: exec round trip ≈ 0.05 s; wrong protocol fails at 3.0 s; silent listener 3.0 s; closed port 1.0 s.

## 7. Screenshots per mode

| Mode | Method | Notes |
|---|---|---|
| UI session, framed review views | `scripts/viewport_capture.py` mode `opengl`: temporary camera per view (front/right/back/left/top/bottom/persp) framed on the target's world bbox; viewport set to camera view, overlays off; `bpy.ops.render.opengl(write_still=True, view_context=True)` inside `temp_override(window, area, region)` of the largest VIEW_3D | SOLID/MATERIAL/WIREFRAME/RENDERED use the viewport shading. Restores camera, view, shading, overlays and render settings (verified equal before/after). Selected objects draw orange in WIREFRAME |
| UI session, "what the user sees" | `screen.screenshot_area(filepath=)` in a VIEW_3D override (`viewport_capture` mode `screen`), or the official `get_screenshot_of_area_as_image("VIEW_3D")` | Grabs the window framebuffer: **all black when the window isn't composited** (covered/minimised/remote). Measured: a fully black image; `viewport_capture` flags it |
| UI session, pixels without a file (5.2+) | `window.screenshot(region=None, use_alpha=False)` | Returns a read-only `memoryview` of shape `(height, width, 4)`, 8-bit RGBA, rows bottom to top; `region=((min_x, min_y), (max_x, max_y))` crops. It reads the window like the row above, so expect the same black frame when the window isn't composited `[unverified]` |
| Community tool | `get_viewport_screenshot(max_size)` | `GPUOffScreen.draw_view3d` of the current view; independent of compositing |
| Headless | `viewport_capture.py` mode `workbench`: Workbench render of the temporary camera | `render.opengl` refuses in background ("no opengl context"). Workbench final render has no MATERIAL shading type (uses `color_type='MATERIAL'`) and draws **nothing** for WIREFRAME (the script adds temporary Wireframe modifiers). RENDERED is approximated, so use EEVEE/Cycles for look-dev |
| Official tool `render_viewport_to_path` | Renders the **scene camera** with the current render settings — despite its name, not the viewport | Its toolcode writes to `bpy.app.tempdir/blender_mcp/<basename of output_path>`, so read the returned `filepath`. For framed review views use `viewport_capture.py` |
| Any | Render to a path, then open the PNG with the agent's image reader | Keep ≤ 400–512 px for review |

Each image has a framing check: fill fraction, foreground bbox extent and centre offset. Warnings fire for an empty frame or more than 8 % off-centre. Use `isolate=True` to hide non-targets; background objects otherwise count as foreground. Then compare views as in `review-and-comparison.md` §1.

## 8. Safety in a user's live session

- Before editing, read `bpy.data.filepath` and `bpy.data.is_dirty` (the `detect` probe returns both). Never `save_mainfile` over the user's file unasked. Save copies with `copy=True` for CLI work.
- Probing operators in the live file dirties it, leaves datablocks behind, and pushes undo steps. Experiment in a temporary scene (`bpy.data.scenes.new`, removed afterwards) or in your own instance.
- Clean up what you add: temporary cameras, modifiers and images (`bpy.data.images.remove`); brush libraries linked by `brush.asset_activate` (`sculpt_ops.py` `close()` unlinks Essentials libraries it added).
- Restore viewport state you change (shading, view, local camera, overlays, mode, active object). `viewport_capture` and `sculpt_ops` do.
- Snapshot only values when saving state: `.copy()` on an ID (`scene.camera`) **duplicates the object**. Copy only mathutils types (found and fixed in testing).
- bpy is main-thread only. Never call bpy from your own threads inside Blender. Use `bpy.app.timers.register` to hop to the main thread.

## 9. Executable paths per OS

| OS | Typical locations (checked by `bridge_client.py detect`) |
|---|---|
| Windows | `C:\Program Files\Blender Foundation\Blender X.Y\blender.exe`; Steam `…\steamapps\common\Blender\blender.exe` [unverified]; `%LOCALAPPDATA%\Programs\Blender Foundation\…` [unverified] |
| macOS | `/Applications/Blender.app/Contents/MacOS/Blender` (also `~/Applications`) [unverified here] |
| Linux | `/usr/bin/blender`, `/snap/bin/blender`, `/opt/blender*/blender`, `~/blender*/blender`, Flatpak `/var/lib/flatpak/exports/bin/org.blender.Blender` [unverified here] |
| Any | env `BLENDER_PATH` (also used by the official MCP server), `BLENDER_EXE`, `BLENDER`, `blender` on PATH |

`--exe-version` runs `blender -b --factory-startup --version` per candidate (slow). Otherwise the version comes from the folder name. User extensions live in `<config>/X.Y/extensions/user_default/`.

## 10. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Exec hangs forever, no error | Wrong protocol: official request (with `\0`) to the community add-on, or bare JSON to the official server | `bridge_client.py detect`; always set a client timeout |
| Official server replies "Client timed out" | Request sent without the trailing `\0` (or it took > 10 s to send) | Append `\0`; one request per connection |
| "requires 'strict_json' boolean key" | Hand-written official request missing `strict_json` | Add `"strict_json": false` |
| `The result variable must be a dict` | `result = 42` or a list | Wrap it: `result = {"value": 42}` |
| Every socket call takes ~2 s extra on Windows | `localhost` tries `::1` first; the servers bind IPv4 | Connect to `127.0.0.1` (bridge_client does) |
| JSON decode error on the client | Hand-built JSON with unescaped quotes/backslashes/newlines in code | Build requests with `json.dumps`. Unicode and `\x00` inside strings round-trip (tested) |
| Community tool result is only "Code executed successfully:" | Code set `result` but printed nothing | Print JSON or use bridge_client exec |
| `RuntimeError: Operator ... poll() failed, context is incorrect` | Timer/socket context has no area/region | `with bpy.context.temp_override(window=w, area=a, region=r):` using `window_manager.windows` → VIEW_3D |
| Blender crashes on a mask/filter/face-set op | Run headless | Use a UI session (`sculpt_ops.py`) |
| `Cannot use OpenGL render in background mode` | `render.opengl` under `-b` | Workbench/EEVEE render (`viewport_capture` workbench mode) |
| Screenshot is completely black | `screenshot_area` on a non-composited window | opengl mode or offscreen draw |
| Headless WIREFRAME capture is blank | Workbench final render ignores WIREFRAME shading | Temporary Wireframe modifiers (viewport_capture does) |
| "Rendered viewport" image shows the camera view, or lands in a temp folder | Official `render_viewport_to_path` renders the scene camera into `bpy.app.tempdir/blender_mcp/` (§7) | Read the returned `filepath`; use viewport_capture for framed views |
| User add-on operator missing in CLI run | `--factory-startup` skips extensions | Drop the flag; open a copy, never the original |
| UI frozen, client timed out, Blender still busy | Long bake/render over the live socket | CLI subprocess on a saved copy (§6) |
| Stray `Object.001` after a helper "restored" state | `.copy()` of an ID while snapshotting | Store ID references as-is |
| `'Context' object has no attribute 'active_object'` from `bpy.ops.mesh.primitive_*_add` | Called in the same exec right after `wm.read_homefile` or a file switch: the exec's context is stale | Build geometry with bmesh + `bpy.data` (context-free), or send the rest of the code as a new exec |
| An unexpected `Cylinder`/`Cube` shows up in later renders | A failed exec created the primitive before raising | After any failed exec, list mesh objects outside the expected collections and delete strays before review or export |
