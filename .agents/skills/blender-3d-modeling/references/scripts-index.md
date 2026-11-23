# Scripts Index

Every bundled script with where it runs and what it measures or builds. `SKILL.md` lists the same scripts grouped by workflow stage; read this file when you need the run mode, the options a script exposes, or which gate a script implements. Each script's module docstring is the authority for its flags — read it before the first run.

## Contents
1. Run modes and conventions
2. Reference, planning and review
3. Bridges, capture and rendering
4. Geometry gates and repair
5. Sculpting and painting (live UI)
6. Characters, animation and simulation
7. Materials, UVs and baking
8. Stylized / NPR
9. Environments, kits and archviz
10. Delivery and interchange
11. Parametric builders
12. Skill maintenance

## 1. Run modes and conventions

Paths are relative to the skill folder; `blender` is the Blender executable (Windows: `"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"`; macOS: `/Applications/Blender.app/Contents/MacOS/Blender`; Linux: `blender`).

| Mode | How | Notes |
|---|---|---|
| Headless (CLI) | `blender -b [file.blend] --python scripts/<script>.py -- <args>` | Prints exactly one tagged line `<SCRIPTNAME_UPPER> <json>` (a few older scripts use another tag — noted below). Add `--factory-startup` for tests; never call `bpy.ops.wm.read_factory_settings()` from Python. |
| Live session (MCP / socket) | exec the file with its options global set first; the script leaves a dict in `result` | The global's name is in each script's docstring — usually a short form (`BAKE_OPTS`, `UV_OPTS`, `RIG_OPTS`, `SHOT_OPTS`…; `REF_CONFIG` for setup_reference_images, `PAINT_OPS` for paint_ops; `archviz_setup.py` exposes functions instead). `python scripts/bridge_client.py exec --file scripts/<script>.py --opts '{...}'` reads the name from the file and sets it for you. |
| Plain Python | `python scripts/<script>.py …` | No Blender needed; PIL/requests where stated. |

Long jobs (bakes, sims, renders, big round-trips) run as headless subprocesses on a saved copy, never over a live bridge (`blender-bridges.md`). UI-only scripts need a live Blender window.

## 2. Reference, planning and review

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/gather_references.py` | plain Python (requests, PIL) | Download image URLs into organized `references/` folders with manifest + notes template |
| `scripts/measure_reference.py` | plain Python (PIL) | Foreground bbox, labelled grid overlay for reading landmark pixels, median colors per region; `--json` prints one tagged line |
| `scripts/setup_reference_images.py` | bpy, headless ok (`REF_CONFIG`) | Import front/side/top/back images as aligned reference empties sized to real-world height |
| `scripts/silhouette_compare.py` | plain Python (PIL) | Aligned silhouette IoU, proportion, symmetry parity, banded interior difference + comparison sheet (advisory); `--json` prints one tagged line |
| `scripts/project_state.py` | plain Python | Project checklist with evidence, per-profile steps (`profiles` lists them), bounded correction loops (`init/next/mark/loop`), `--json` |

## 3. Bridges, capture and rendering

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/bridge_client.py` | plain Python | Detect bridges (official MCP vs community blender-mcp socket protocols within 3 s, Blender executables, tool names); exec code/file + OPTS on a live socket; run-cli with tagged-JSON parsing |
| `scripts/viewport_capture.py` | bpy; UI session or headless | Framed review captures per view × shading (OpenGL in UI, Workbench headless), framing check, `--frames` playblast sequence, full state restore |
| `scripts/shot_setup.py` | bpy, headless ok | Cameras fitted to a target (hero 3/4, true iso/dimetric, ortho views), frame-margin gate, calibrated key/fill/rim rig + cyc backdrop/shadow catcher, loop-safe turntable + `--turntable-margin` check |
| `scripts/render_cli.py` | plain Python (+ bpy modes) | Build/run chunked background renders; check output folders (missing/0-byte/black/constant/duplicate frames); EXR info; passes + File Output setup |

## 4. Geometry gates and repair

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/mesh_report.py` | bpy, headless ok | Topology & hygiene audit (numpy path, size-relative tolerances; ~6 s for 8M tris); JSON + summary |
| `scripts/scene_gates.py` | bpy, headless ok | Attachment/floating parts, `.L/.R` chirality, sibling intersections, part coverage, orbit projected-area collapse, explode preview |
| `scripts/mesh_repair.py` | bpy, headless ok | Analyze & repair imported meshes (weld, floaters, holes, normals, inner shells, voxel, symmetrize, decimate to budget) with before/after and deviation gates; `--import/--export`, `--json-out` |
| `scripts/naming_lint.py` | bpy, headless ok | Naming/file-hygiene lint (profiles working/archviz/game_export or JSON rules; duplicates, L/R pairs, orphans, missing/absolute paths, libraries) with safe `--fix` |

## 5. Sculpting and painting (live UI)

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/sculpt_ops.py` | UI session only | Scripted sculpting: brush activation, world-radius surface strokes, grab, procedural masks, filters, trim, extract, remesh/multires, cleanup |
| `scripts/paint_ops.py` | UI session for strokes (`PAINT_OPS` global; no CLI) | Texture-paint strokes along surface paths (m or px radius), fill, save; changed-pixel stats |
| `scripts/ucupaint_ops.py` | Ucupaint installed; headless ok, bake UI only | Ucupaint detection/consent, setup, layers, masks, blend/opacity, bake, flatten; JSON layer stack |

## 6. Characters, animation and simulation

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/rig_check.py` | bpy, headless ok | Bone scale/symmetry, weights, rigidity, pose sweep (on by default, `--no-sweep`), action-moves (slot auto-assign), loop with optional root motion, foot slide (world or in-place) |
| `scripts/ik_rig.py` | bpy, headless ok | Two-bone IK + pole + foot roll + stretch; knee-flip check; bake controls to deform bones or a Rigify export skeleton with max bake error |
| `scripts/scalp_exposure.py` | bpy, headless ok | Geometric bald-patch check: scalp samples with no hair geometry outside the skull |
| `scripts/shapekey_check.py` | bpy, headless ok | Per shape key: moved vertices, max displacement, region confinement, L/R symmetry, lid-through-eyeball check |
| `scripts/lipsync_keys.py` | bpy, headless ok | Rhubarb/Papagayo-Moho/phoneme timings → ARKit/Oculus/Preston viseme shape-key keys, jaw, blinks, audio strip; overlap/exclusivity/missing-key gates |
| `scripts/export_actions.py` | bpy, headless ok | Export multiple actions (and shape keys; meshes without an armature supported) to FBX/glTF with engine presets; re-import and report actions, frame ranges, bones, keys, shape-key curves |
| `scripts/sim_check.py` | bpy, headless ok | Optional bake + gates: setup lint, cloth penetration/poke-through/settle, rigid topple/still/broken constraints, liquid mesh/volume/fill-inside, smoke near emitters |

## 7. Materials, UVs and baking

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/uv_tools.py` | bpy+numpy, headless ok | Unwrap with sharp/angle seams + disk cuts, pack with px margins/UDIM tiles, set texel density; check overlaps/mirrors/stretch/padding/density/tiles |
| `scripts/bake_maps.py` | bpy, headless ok | Bake BASECOLOR/ROUGHNESS/NORMAL (GL/DX)/AO/METALLIC/EMIT + ORM pack; high→low with cage/ray distance; `--uv-map`, `--ao-samples`, `--ao-distance`, `--margin-type`; 8/16-bit PNG or EXR; UDIM tiles; GPU; requires UVs unless `--auto-uv` |
| `scripts/atlas_bake.py` | bpy, headless ok; Cycles | Merge props, pack atlas UVs with px margin, bake BASECOLOR/ROUGHNESS/METALLIC/NORMAL or ORM into one MAT_Atlas; draw calls before/after, texel density, per-material colour error, bleed |
| `scripts/pbr_from_image.py` | bpy+numpy, headless ok (tag `PBR_REPORT`) | Albedo → tileable de-lit basecolor + height/normal/roughness/AO + seam metrics; DX↔GL normals; `--delight-atlas` for scan/AI UV atlases |
| `scripts/build_pbr_material.py` | bpy, headless ok | Node PBR material from a map folder (generic/Poly Haven/ambientCG/Substance names), color spaces, GL/DX normal convention, ORM, displacement, UDIM tile sets as tiled images |

## 8. Stylized / NPR

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/normal_transfer.py` | bpy, headless ok | Proxy (ellipsoid/sphere/object) custom normals via Data Transfer or Normal Edit in a vertex-group mask; inside/outside/posed deviation; stack-order, mask and rig-parenting checks |
| `scripts/lineart_setup.py` | bpy, headless ok | Grease Pencil v3 Line Art for scene/collection/object, bake frame or range, stroke counts, Workbench ID-mask alignment check (precision/recall px) |
| `scripts/face_sdf.py` | bpy, headless ok; EEVEE/Cycles for render checks | SDF face-shadow material + drivers (object or head bone), `--assign-faces`, colour flags, mask → threshold-map builder, NPR_AngelRing hair group; light-orbit and multi-view gates; render checks restore scene settings |

## 9. Environments, kits and archviz

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/scatter_on_surface.py` | bpy, headless ok | Geometry Nodes scatter: Poisson spacing, density attribute, slope/height masks, random transforms |
| `scripts/tile_sockets.py` | bpy, headless ok | Modular kit validation + border-profile sockets, rotation variants and WFC adjacency JSON |
| `scripts/asset_library.py` | bpy, headless ok (tag `ASSET_LIBRARY_RESULT`) | Asset catalogs/tags, kit consistency audit, linked collection instances, socket snapping |
| `scripts/plan_to_rooms.py` | bpy, headless ok | JSON floor plan → mitred walls, live openings (frames, Thin Wall glass, doors), sealed slabs, room floors, world-scale UVs; ray-verified openings |
| `scripts/archviz_setup.py` | bpy, headless ok (functions, no OPTS global) | Units, level two-point cameras, sun angles, Sky + matched Sun or HDRI, window portals, Cycles presets + AgX looks, exposure probe, batch render |
| `scripts/archviz_gates.py` | bpy, headless ok | Light leaks, wall/slab closure, visible z-fighting, furniture contact & dimensions, glass, camera verticals, render sanity, UV scale |

## 10. Delivery and interchange

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/lod_collision.py` | bpy, headless ok | LOD chain with tris and silhouette deviation per level (`--object`, or batch `--objects` / `--source-collection`, output in `--out-collection`); convex-hull/box/sphere collision named for engines |
| `scripts/export_check.py` | bpy, headless ok; `--inspect` plain Python | FBX/glTF/OBJ export with presets → re-import → compare objects, tris, bbox (scale/axis), materials, UVs, normals, animation, shape keys, file size; glTF JSON gate for extensions, material variants, morph targets, Draco/meshopt, texture MIME |
| `scripts/scene_perf_report.py` | bpy, headless ok | Real-time performance: draw-call estimate (gated on the naive count; `--max-draw-calls/--max-tris/--max-texture-mb` overrides), materials, texture memory, visible tris, transparency classes and ray-cast overdraw, budgets, largest offenders |
| `scripts/interchange_check.py` | bpy, headless ok | USD & Alembic round-trips (counts, tris, bbox/vertex deviation, units/axis diagnosis, materials, UVs, frames); library/override integrity, relocate, resync (self-test runs in a child process) |
| `scripts/export_print.py` | bpy, headless ok | Print gate (manifold, self-intersection, ray wall thickness, part clearance, volume/bbox in mm) and STL/OBJ/PLY export at the right scale with re-import bbox proof |

## 11. Parametric builders

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/svg_to_solid.py` | bpy, headless ok | SVG → sized, bevelled, merged logo solid with automatic bevel clamp; gates width ±0.1 mm, holes, manifold, self-intersection |
| `scripts/voxelize.py` | bpy, headless ok | Mesh → grid-aligned culled/greedy voxel mesh with palette texture; voxel-mesh gate; UV texel snap, Closest, pixel-art render settings; shared palettes (`--palette-in/--palette-out`) |
| `scripts/ring_builder.py` | bpy, headless ok | Parametric solitaire ring: band from size, brilliant proxy, seat cutter, prongs; gates bore, prong/wall width, seat after shrink, stone interference, print gate |
| `scripts/cad_enclosure_template.py` | plain Python + build123d | Parametric PCB enclosure (bosses, snap lid, connector cut-outs via `--cutouts` JSON) → STEP + welded STL + params JSON |

## 12. Skill maintenance

| Script | Runs in | Purpose |
|---|---|---|
| `scripts/skill_lint.py` | plain Python | After editing the skill: registration, paths, section pointers, SKILL.md size, Contents lists, script syntax, frontmatter size, caches, leak scan (`--deny` job terms) |
| `scripts/addon_template.py` | bpy | Minimal operator + panel skeleton for task-specific helper tools |
