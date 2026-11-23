---
name: blender-3d-modeling
description: Use when creating, fixing, texturing, rigging, animating, simulating, rendering or exporting 3D models and scenes in Blender (MCP, bpy or CLI) — characters, creatures, plants, terrain, cities, modular kits/WFC, kitbash, props, weapons, vehicles, furniture, buildings, interiors from floor plans, products, logos/text, voxel art. Triggers include mesh, topology, low/high poly, game-ready, LOD, sculpting, retopology, modifiers, curves, Geometry Nodes, scattering, materials, shader nodes, PBR, texture painting, Ucupaint, UV unwrap, UDIM, baking, rigging, shape keys, keyframes, visemes, lip sync, cloth/rigid body/fluid sims, toon/NPR, Line Art, Grease Pencil, Cycles/EEVEE, lighting, turntables, product renders, compositing, arch viz, FBX/glTF/USD/STL, Unity/Unreal/Godot, draw calls, 3D printing, jewelry, CAD, SVG logos, photogrammetry or AI-mesh cleanup, or any "model of X" request.
---

# Blender 3D Modeling

Build models the way a working artist does: gather and study references first, block out proportions, pick the technique that fits the subject and the target (game, film, archviz, product, print, web), then refine while auditing with deterministic gates and looking from several angles. Never start pushing vertices before you know what the thing actually looks like.

## Tools you have

- **Blender access** — detect the bridge first: `python scripts/bridge_client.py detect [--tools "<your tool names>"]`, then follow `references/blender-bridges.md` (MCP tools leave a dict in `result`; a socket without tools takes `bridge_client.py exec`; no live Blender means headless `bridge_client.py run-cli`, where sculpt/paint strokes are impossible).
- **See your work** after every meaningful change: the bridge's screenshot tool or `scripts/viewport_capture.py`. Numbers don't catch a lumpy silhouette.
- Web search / image search for references and current docs; image generation, if a tool offers it, for references the web can't supply and for texture albedos (`references/reference-gathering.md`, `references/texture-sources-and-pbr-sets.md`). Follow the tool's billing/consent rules.
- **Subagents** in non-overlapping lanes (*Parallel work* below).
- **Installed add-ons** (`bpy.context.preferences.addons.keys()`): Hard Ops → `references/hard-ops.md`, Ucupaint → `references/texture-painting.md`, others → `references/addons-and-scripting.md`. Ask before enabling anything.
- The bundled `scripts/` (grouped list at the end; run modes and purposes in `references/scripts-index.md`). Long operations (bakes, sims, renders) run as headless CLI subprocesses on a saved copy instead of blocking a live bridge.

## Workflow

### 1. Clarify the target before touching geometry

| Question | Why it changes everything |
|---|---|
| **Subject** — what is it, style (realistic/stylized), scale | Decides the toolset and the reference to route to (§3) |
| **Use case** — game (mobile/PC/console/VR), film/render, archviz, product shot, print/CAD, web/AR | Poly budget, topology strictness, units, export format |
| **Will it deform or move?** (rigged, animated, simulated, hinged) | Quad loops at joints, assemblies, pivots, cache/bake plan |
| **Deliverable** — .blend, stills/animation, FBX/glTF/USD/STL; textures? LODs? | Cleanup, UVs, naming, scale, export checks |

If the brief is clear, state assumptions in one line and proceed. Budgets and per-target checklists: `references/poly-budgets-and-targets.md`.

Open a project checklist so progress lives outside the conversation: `python scripts/project_state.py init --state <asset>/.model_state.json --asset "<name>" --profile <profile>` (`python scripts/project_state.py profiles` lists them). Run `next` at the start of every session and before every correction; `mark` steps only with evidence; `STOP` means correction limits were hit (`references/quality-gates.md`).

### 2. Gather references (new model, and again during refinement/fix passes)

Follow `references/reference-gathering.md`; short version:
1. Search the **whole subject** (front/side/top/three-quarter, real photos, blueprints) **and each major component**.
2. Download into `references/00_overall/`, `references/01_<component>/`… with `scripts/gather_references.py` (manifest + NOTES.md).
3. Web insufficient and an image generator available → generate orthographic views / component close-ups, marked `generated`.
4. **Study before modeling**: measured proportions (`scripts/measure_reference.py`), parts and attachments, a **surface class per part** (`references/topology.md` §0), sampled colors, a detail inventory (geometry vs texture), 3–5 **sensitivity ratios**, what the views hide.
5. Write the **quality contract** into NOTES.md (`references/quality-gates.md` §1). If it could describe many objects, the study isn't finished.
6. Load orthographic views as reference empties (`scripts/setup_reference_images.py`).

Most "this doesn't look right" problems are reference problems — re-run steps 1–4 for the component that looks wrong. Briefs built from drawings/dimensions (archviz, print, CAD) type numbers instead of tracing photos.

### 3. Decide the technique — route to the right reference

Start from the **surface class** of each part (`references/topology.md` §0): section × path, profile × revolution, unit × repetition, shell × thickness or height × surface are built live with `references/modifiers-and-curves.md` before any hand modeling. Most assets are **hybrid** (organic body + hard armor): one object per technique; anything that moves, breaks or gets picked is an **assembly** (`references/assembly-and-hierarchy.md`). Read only the rows that match the job; every reference starts with a Contents list.

| Subject / intent | Read | Key scripts |
|---|---|---|
| Organic forms, food, rocks, cloth shapes | `references/organic-modeling.md`, `references/sculpting.md` | `sculpt_ops.py` |
| Hard surface: tools, props, machines, booleans, bevels | `references/hard-surface-modeling.md` (+ `references/hard-ops.md` if installed) | `mesh_report.py` |
| Vehicles (exterior and interior), weapons, furniture, architecture specifics | `references/hard-surface-categories.md` | `mesh_report.py`, `scene_gates.py` |
| Characters: layer ontology, build order, hair | `references/character-modeling.md` | `scalp_exposure.py` |
| Armatures, weights, control rigs, pose checks | `references/rigging-and-weights.md` | `rig_check.py`, `ik_rig.py` |
| Creatures, animals, fur, feathers, scales | `references/fauna.md` | `rig_check.py` |
| Actions, NLA, walk/run cycles, root motion, clip export | `references/animation.md` | `export_actions.py`, `rig_check.py` |
| Shape keys, correctives, visemes, lip sync | `references/shape-keys-and-visemes.md` | `shapekey_check.py`, `lipsync_keys.py`, `export_actions.py` |
| Any simulation: setup, caches, solver choice, particles/hair dynamics | `references/simulation.md` | `sim_check.py` |
| Cloth and garments on rigs | `references/cloth-and-garments.md` | `sim_check.py` |
| Rigid bodies, destruction, constraints | `references/rigid-bodies-and-destruction.md` | `sim_check.py` |
| Liquids, smoke, fire, pours | `references/fluids-and-smoke.md` | `sim_check.py` |
| Plants and trees | `references/flora.md` | `scatter_on_surface.py` |
| Terrain, water, roads, scatter, atmosphere | `references/environment-modeling.md` | `scatter_on_surface.py` |
| Towns, cities, big levels, engine-side instancing | `references/large-sets-and-cities.md` | `asset_library.py` |
| Grid kits, tilesets, WFC | `references/modular-kits-and-wfc.md` | `tile_sockets.py`, `asset_library.py` |
| Kitbashing from part libraries | `references/kitbashing.md` | `asset_library.py` |
| Arch viz shell from plans, dimensions, furniture, exteriors | `references/archviz-modeling.md` | `plan_to_rooms.py`, `archviz_gates.py` |
| Arch viz cameras, sun/sky, exposure, materials, render presets | `references/archviz-lighting-and-rendering.md` | `archviz_setup.py`, `archviz_gates.py` |
| Scans, photogrammetry, AI-generated or downloaded meshes | `references/mesh-repair.md` | `mesh_repair.py`, `mesh_report.py` |
| 3D printing (FDM/resin/SLS), tolerances, STL | `references/3d-printing.md` | `export_print.py` |
| Jewelry, ring sizes, casting | `references/jewelry-and-casting.md` | `ring_builder.py`, `export_print.py` |
| CAD/STEP bridge, enclosures | `references/cad-and-enclosures.md` | `cad_enclosure_template.py` |
| SVG logos, text objects | `references/vector-and-text.md` | `svg_to_solid.py` |
| Voxel and pixel-art assets | `references/voxel-and-pixel-art.md` | `voxelize.py` |
| What a material must prove (albedo, roughness, relief, wear) | `references/materials-and-lookdev.md` | — |
| Node trees from code, API traps, verification | `references/shader-nodes.md` | `build_pbr_material.py` |
| Procedural material recipes (worn paint, car paint, …) | `references/procedural-materials.md` | — |
| Texture sources: libraries, generated images → PBR sets | `references/texture-sources-and-pbr-sets.md` | `pbr_from_image.py`, `build_pbr_material.py` |
| Texture painting, hand-painted textures, Ucupaint layers | `references/texture-painting.md` | `paint_ops.py`, `ucupaint_ops.py` |
| UV unwrapping, seams, texel density, packing, UDIMs | `references/uv-unwrapping.md` | `uv_tools.py` |
| Baking maps high→low, AO, ORM, Substance/Marmoset round-trip | `references/baking-maps.md` | `bake_maps.py`, `uv_tools.py` |
| Stylized, toon shading, flat palettes, toon water, isometric | `references/stylized-npr.md` | `normal_transfer.py` |
| Outlines, Line Art, Grease Pencil | `references/outlines-and-line-art.md` | `lineart_setup.py` |
| Anime face shadow, angel-ring hair, anime head topology | `references/anime-face-and-hair.md` | `face_sdf.py`, `normal_transfer.py` |
| Lighting, product/studio shots, glass, turntables, video output | `references/rendering-and-lighting.md` | `shot_setup.py`, `viewport_capture.py` |
| Command-line/farm renders, passes, the 5.x compositor | `references/render-farm-and-compositing.md` | `render_cli.py` |
| Game engines: FBX/glTF presets, LODs, collision, sockets, perf budgets | `references/game-engine-delivery.md` | `lod_collision.py`, `export_check.py`, `scene_perf_report.py`, `atlas_bake.py` |
| Web glTF (variants, Draco/meshopt), mobile and standalone VR | `references/web-and-mobile-delivery.md` | `export_check.py`, `export_actions.py`, `scene_perf_report.py` |
| Project layout, linking/overrides, versioning, naming | `references/project-files-and-naming.md` | `naming_lint.py` |
| USD and Alembic interchange, units/axes between DCCs | `references/usd-and-alembic.md` | `interchange_check.py` |
| Connecting to Blender: which MCP/socket/CLI bridge, returning data, screenshots, timeouts | `references/blender-bridges.md` | `bridge_client.py`, `viewport_capture.py` |
| A remembered bpy name raises `AttributeError`/`TypeError`/unknown enum, or Blender is newer than 5.2 | `references/blender-version-changes.md` | — |

All references live in `references/`, all scripts in `scripts/`.

### 4. Block out, then refine in passes

1. **Blockout** at real-world scale (1 unit = 1 m unless the target says otherwise) against the reference empties; screenshot front/side/top/perspective and compare before adding detail.
2. **Primary → secondary → tertiary.** Don't bevel or sculpt wrinkles before the silhouette reads at thumbnail size.
3. **Modifiers non-destructively** as long as possible (`references/modifiers-and-curves.md`); keep pre-apply copies in a hidden `_source` collection.
4. **Run the deterministic gates every pass, before looking**: `mesh_report.py` (topology/hygiene), `scene_gates.py` (floating parts, mirrored pairs, intersections, coverage, 2.5D slab), plus the domain gates from the §3 table. Fix against `references/topology.md` and `references/quality-gates.md`. A passing gate removes one defect class; it never means "done".
5. **Look from more than one angle** (`references/review-and-comparison.md`): turntable + top + cross-section, camera-matched screenshots next to the references, MatCap/wireframe/rendered, compared layer by layer. Name each discrepancy with a number, pick one action, and report "improved" rather than "done" until it is. Before claiming that parts are connected, clean or non-overlapping, run the **auditing-3d-geometry** skill (mesh-level penetration/containment audit and isolated junction shots) — `scene_gates.py` measures assemblies, that skill proves individual contacts.

### 5. Materials, UVs and look-dev (textured or rendered deliverables)

`references/materials-and-lookdev.md` says *what* a material must prove; `references/shader-nodes.md` (node trees), `references/procedural-materials.md` (recipes) and `references/texture-sources-and-pbr-sets.md` (libraries, generated images) say *how*. UVs: `references/uv-unwrapping.md`; baking: `references/baking-maps.md`; painting: `references/texture-painting.md`; stylized looks: `references/stylized-npr.md`; lighting, cameras and output: `references/rendering-and-lighting.md` (archviz: `references/archviz-lighting-and-rendering.md`).

### 6. Finalize for the target

Apply transforms, recalc normals, merge by a size-relative distance, name, set origins, UVs, LODs/collision for games, watertight for print. Use the target's checklist (`references/poly-budgets-and-targets.md`) and verify the export by re-importing (`export_check.py`, `interchange_check.py`, `export_print.py`). Report final counts vs budget, what each gate did and did not measure, and what remains approximate.

## Parallel work with subagents

Split jobs into lanes that **write to disjoint scopes**: reference gathering per component, texture generation per material, a helper script with its headless test, an independent asset in its own `.blend`, research, read-only review of a saved snapshot. **One agent owns the live Blender session**; other lanes work headless on their own files and deliver files + evidence the owner integrates. Never parallelize writes to the same scene/object/file, sequential stages, or consistency decisions (palette, scale, bevel standard, texel density). Recipe: `references/parallel-work-with-subagents.md`.

## Use the right tool — including tools you build

- Add-ons: `references/addons-and-scripting.md` (check what's installed first; ask before enabling).
- **Write your own helpers** when repeating a multi-step bpy sequence (`scripts/addon_template.py` for operators/panels) and tell the user — a reusable tool often outlives the model.
- **bmesh over bpy.ops** for geometry edits in scripts: faster, context-free, and it exposes topology directly.

## Improving this skill

When a job produces a reusable tool, exposes missing or wrong guidance, reveals an unlisted defect class, or yields a correction that applies beyond the job, add it once the user's deliverable is done: scripts in `scripts/` with a row in `references/scripts-index.md` and a mention in the grouped list below, techniques in the matching reference, failures in that file's Common failures, a `CHANGELOG.md` line each. Additive changes are applied and reported; removals or rewrites are proposed first. **Never let the user's work into the skill** — generalize, use synthetic tests, run `python scripts/skill_lint.py --deny "<job terms>"` (it also checks section pointers, Contents lists and this file's size). Protocol: `references/self-improvement.md`; best-practice sources: `references/sources.md`.

## Habits that separate good models from bad ones

- Real scale with applied transforms; bevels, booleans, sims and exports all misbehave otherwise.
- Symmetry first, asymmetry last. Edge density follows curvature.
- Hide unavoidable triangles/ngons on flat, non-deforming, hidden areas.
- Name as you go (`MAT_Steel_Brushed`, role prefixes per domain; engine names like `SM_`/`M_` only in the export copy — `references/project-files-and-naming.md`).
- Save incrementally (`asset_v001.blend`) before destructive operations (apply, remesh, decimate, join, bake).
- When something looks off and you can't say why: screenshot from the reference's angle and list the differences explicitly before changing anything.

## Scripts

Headless: `blender -b [file.blend] --python scripts/<script>.py -- <args>` prints one tagged JSON line; live session: exec the file with its options global set (each docstring shows how); a few are plain Python or UI-only. Run modes, tags and full purposes: `references/scripts-index.md`.

- **Reference & planning**: `scripts/gather_references.py`, `scripts/measure_reference.py`, `scripts/setup_reference_images.py`, `scripts/silhouette_compare.py`, `scripts/project_state.py`
- **Bridges, capture, rendering**: `scripts/bridge_client.py`, `scripts/viewport_capture.py`, `scripts/shot_setup.py`, `scripts/render_cli.py`
- **Geometry gates & repair**: `scripts/mesh_report.py`, `scripts/scene_gates.py`, `scripts/mesh_repair.py`, `scripts/naming_lint.py`
- **Sculpting & painting (live UI)**: `scripts/sculpt_ops.py`, `scripts/paint_ops.py`, `scripts/ucupaint_ops.py`
- **Characters, animation, simulation**: `scripts/rig_check.py`, `scripts/ik_rig.py`, `scripts/scalp_exposure.py`, `scripts/shapekey_check.py`, `scripts/lipsync_keys.py`, `scripts/export_actions.py`, `scripts/sim_check.py`
- **Materials, UVs, baking**: `scripts/uv_tools.py`, `scripts/bake_maps.py`, `scripts/atlas_bake.py`, `scripts/pbr_from_image.py`, `scripts/build_pbr_material.py`
- **Stylized / NPR**: `scripts/normal_transfer.py`, `scripts/lineart_setup.py`, `scripts/face_sdf.py`
- **Environments, kits, archviz**: `scripts/scatter_on_surface.py`, `scripts/tile_sockets.py`, `scripts/asset_library.py`, `scripts/plan_to_rooms.py`, `scripts/archviz_setup.py`, `scripts/archviz_gates.py`
- **Delivery & interchange**: `scripts/lod_collision.py`, `scripts/export_check.py`, `scripts/scene_perf_report.py`, `scripts/interchange_check.py`, `scripts/export_print.py`
- **Parametric builders**: `scripts/svg_to_solid.py`, `scripts/voxelize.py`, `scripts/ring_builder.py`, `scripts/cad_enclosure_template.py`
- **Skill maintenance**: `scripts/skill_lint.py`, `scripts/addon_template.py`
