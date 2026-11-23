# Render Farm & Compositing

Read this when rendering from the command line or across several machines, checking an output folder for bad frames, and setting up render passes and the 5.x compositor (`scripts/render_cli.py`). Engine and GPU device selection, lighting, cameras, turntables and video encoding are in `rendering-and-lighting.md`. Facts marked *measured* come from synthetic tests in Blender 5.2.0 LTS.

## Contents
1. Command-line rendering
2. Chunks, runs & output checks
3. Preparing a file for the farm
4. The 5.x compositor tree
5. Render passes, light groups & multilayer EXR
6. Common failures

## 1. Command-line rendering

```
blender -b scene.blend -E CYCLES -o //renders/shot_#### -F OPEN_EXR -x 1 -s 1 -e 250 -a -- --cycles-device OPTIX --cycles-print-stats
blender -b scene.blend -o //renders/still_ -f 12            # one frame; -f 1,5,9 and -f 1..20 lists also work
```

- **Order matters** (left to right): the `.blend` first, then `-S scene`, `--python-expr`, `-E`, `-o`, `-F`, `-x`, `-t`, then `-s -e -a` or `-f`. Options after `-a` are ignored for that render. Cycles flags go after `--`. `#` sets frame padding; with no `#`, 4 digits are appended. Add `--python-exit-code 1` so script errors fail the job.
- **GPU in `-b`**: preferences are not saved in background mode, so the Cycles device must be set in the render script or with `-- --cycles-device OPTIX` (`+CPU` appends the CPU) — code in `rendering-and-lighting.md` §1. EEVEE needs a GPU context on the node (same section).
- 5.0 changed the log format (`render | Saved: '…'`); farm log parsers written for 4.x need updating. 5.2 can disable saving entirely (`render.save_output`). `bpy.ops.render.render(animation=True, frame_start=, frame_end=)` exists since 5.0.

## 2. Chunks, runs & output checks

`scripts/render_cli.py` (plain Python, no bpy needed) handles the rest:

| Mode | What it does |
|---|---|
| `build` | prints the commands; `--chunks K` or `--node-index i --node-count n` splits contiguous frame ranges per machine |
| `run` | executes chunks sequentially or in parallel (`--parallel N`, `--log-dir`, `--timeout`) with per-chunk logs, exit codes, `Saved:` counts and error markers. On one GPU, parallel processes share VRAM |
| `check --dir --pattern --start --end [--step]` | finds missing, zero-byte, black, constant, transparent-empty and identical-consecutive frames. The last is the typical "animation didn't play" symptom, e.g. an unassigned 5.x action slot |
| `exr-info FILE…` | reports parts/layers/compression of EXRs (see §5) |

- `--placeholders --no-overwrite` sets `use_placeholder` / `use_overwrite = False` so several nodes can share one output folder.
- *Measured*: 10 Workbench frames in 3 chunks × 2 processes, check clean. Planted defects detected: deleted frame 4 → `missing`, black frame 7 → `black` + `constant`, truncated frame 9 → `zero_byte`, copied frame 3 → `identical_to_previous`. A render killed at frame 2 left a **0-byte placeholder** (`zero_byte` [2]), frame 3 `missing`, exit code 3. EXR frames checked with `--check-with-blender` (bpy loader): a constant EXR was caught.

## 3. Preparing a file for the farm

- **Paths**: make them relative (File › External Data › Make Paths Relative) or pack; list every dependency with `bpy.data.file_path_foreach` (5.2 flags `EXPAND_SEQUENCES`, `EXPAND_CACHES`, `EXPAND_TOKENS` cover UDIMs, sequences and `.tx` caches).
- **Bake** simulations, Geometry Nodes bakes and particle caches to disk (`simulation.md`), because nodes otherwise re-simulate or diverge.
- Disable add-on dependencies the farm lacks. Apply the same Blender version everywhere.
- Render **image sequences, never video** on a farm (crash = one lost frame, parallel chunks, encode afterwards); masters and the encode line: `rendering-and-lighting.md` §5.
- **Flamenco** is Blender Studio's free farm manager (manager + workers, job types for chunked frames/video) [version compatibility with 5.2 unverified]. The chunk/placeholder logic above covers small ad-hoc farms.

## 4. The 5.x compositor tree

- **Tree API (5.0+)**: `scene.node_tree` is gone; `scene.use_nodes` is deprecated and always True (*measured* description "Enable the compositing node group").
  ```python
  tree = bpy.data.node_groups.new("COMP_Main", "CompositorNodeTree"); scene.compositing_node_group = tree
  rl = tree.nodes.new("CompositorNodeRLayers"); out = tree.nodes.new("NodeGroupOutput")
  tree.interface.new_socket(name="Image", in_out='OUTPUT', socket_type='NodeSocketColor')
  tree.links.new(rl.outputs["Image"], out.inputs["Image"])
  ```
  The **Composite node was removed**; the group output's first Color input is the result. Most node options became input sockets (Glare: `Type`, `Quality`, `Threshold`, `Strength`, `Size`…; Lens Distortion: `Type`, `Distortion`, `Dispersion`, `Jitter`, `Fit` — *measured*). Gamma-style nodes are shader nodes now (`ShaderNodeGamma`). 5.0 Glare gained Sun Beams and Kernel modes; asset shelf nodes include Chromatic Aberration, Vignette, Film Grain (5.2).
- **File Output node (5.0+)**: `node.directory`, `node.file_name`, `node.file_output_items.new(socket_type, name)` (`'FLOAT'`, `'RGBA'`, `'VECTOR'`), `node.format.media_type`. Frame numbers are appended only in animation renders (the command line always is); add `####` in the name for stills. 5.1 allows sub-directories in item names; 5.2 adds its own File Extension toggle.

## 5. Render passes, light groups & multilayer EXR

- `scripts/render_cli.py` in bpy mode enables passes and wires every enabled Render Layers output into `FO_Passes` (multilayer EXR):
  `blender -b scene.blend --python scripts/render_cli.py -- passes --engine CYCLES --passes mist,ao,normal,depth,crypto_object,denoise --lightgroups key=LGT_Key --out //passes/shot_` (also `--no-multilayer`, `--main-multilayer`, `--view-layer`, `--save`).
  Sockets exist only for passes the current engine supports; under Workbench only Image and Depth appear (*measured*) — set the engine first.
- Passes (view layer): `use_pass_z` (socket "Depth" in 5.x), `use_pass_mist` (World › Mist Pass start/depth), `use_pass_normal`, `use_pass_position`, `use_pass_vector`, `use_pass_ambient_occlusion`, `use_pass_object_index` / `material_index`, diffuse/glossy/transmission direct/indirect/color, `use_pass_cryptomatte_object|material|asset` (+ `pass_cryptomatte_depth`), Cycles `denoising_store_passes`, `use_pass_shadow_catcher`, `pass_render_time` (5.0), EEVEE `use_pass_bloom` / `use_pass_transparent`. 5.0 renamed passes (`Z` → `Depth`, `DiffCol` → `Diffuse Color`, `IndexMA` → `Material Index`).
- **Light groups**: `view_layer.lightgroups.add(name="key")`, `obj.lightgroup = "key"`, `world.lightgroup`. Each group becomes a pass, so key/fill/rim balance can be relit in comp without re-rendering.
- **Multilayer EXR** is multi-part since 5.0. *Measured* with `render_cli.py exr-info`: File Output multilayer with mist/AO/normal/depth/crypto/denoise + one light group → `multipart: True`, 15 parts, one per layer (`Image`, `Depth`, `Mist`, `CryptoObject00`…, `Combined_key`), ZIP. A plain EXR is single-part RGBA. Some older compositing apps expect single-part [unverified which].
- **View layers & holdout**: one view layer per element (product / shadow / background) with collection holdout or indirect-only, or per object `obj.is_holdout`. Render once, composite with Alpha Over. Cryptomatte (`CompositorNodeCryptomatteV2`) picks object/material mattes after the fact. Shadow-catcher setup: `rendering-and-lighting.md` §2.

## 6. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `scene.node_tree` AttributeError / black comp | 5.0 compositor API | `scene.compositing_node_group` + `NodeGroupOutput` |
| File Output wrote `name.exr` without frame number | Still render in 5.x | Animation render or `####` in the file name |
| Passes missing from the EXR | Engine without that pass (Workbench), sockets not linked | Set engine first, `render_cli.py passes --engine CYCLES` |
| GPU render silently on CPU in `-b` | Preferences device not set for this process | Set `compute_device_type` + `devices[].use` in script or `-- --cycles-device OPTIX` |
| Farm frames 0 bytes | Placeholder from a crashed/killed node | `render_cli.py check` → re-render `zero_byte` frames |
| Every frame identical | Action slot not assigned (5.x), or animation on a disabled object | Assign `animation_data.action_slot`; `identical_to_previous` flag |
| Options after `-a` ignored / wrong frame range | Command-line order | `.blend` first, `-E -o -F -x -t`, then `-s -e -a` or `-f`; Cycles flags after `--` |
| Farm job "succeeds" with a Python error in the log | Script errors don't fail the process | `--python-exit-code 1` |
| EEVEE render fails on the farm | No GPU context on the node | Cycles/Workbench on that node, or GPU workers |
