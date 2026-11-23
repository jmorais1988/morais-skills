# Blender Version Changes (5.1 → 5.3)

What changed in Blender after 5.0 that breaks or improves bpy code written from memory. Read it when a script raises `AttributeError`, `TypeError` or "enum not found" on a name you were sure of, when a default behaves differently than expected, or before running this skill on a Blender newer than 5.2. Changes up to 5.0 (slotted actions, compositor node group, `BLENDER_EEVEE`, boolean `FLOAT`, brush diameters, Grease Pencil renames, `use_nodes`) are fixed in place in the topic references and not repeated here.

- **Checked**: 2026-11-12.
- **Covers**: 5.1 (2026-03-17), 5.2 LTS (2026-07-14, the version this skill targets and tests against), 5.3 (2026-11-10, not installed when checked).
- **Source marks**: `RN` = official release notes (`https://developer.blender.org/docs/release_notes/<version>/`); `API` = confirmed in a 5.2.0 install (RNA introspection in `blender -b --factory-startup`, `blender --help`, or the 5.2 API reference and manual). An entry marked only `RN` was read, not run.
- Each row points to the reference that holds the working guidance; this file only says what changed.

## Contents
1. Changes that break scripts (5.1, 5.2)
2. New and useful for game assets (5.1, 5.2)
3. After upgrading to 5.3
4. Where sources disagree
5. Re-checking after a new release

## 1. Changes that break scripts (5.1, 5.2)

| Since | Old | Now | Source | Guidance |
|---|---|---|---|---|
| 5.2 | `mod["<identifier>"] = v`, `mod["<identifier>_use_attribute"]`, `mod["<identifier>_attribute_name"]` on a Geometry Nodes modifier | `mod.properties.inputs.<identifier>.value`, `.type = 'ATTRIBUTE'`, `.attribute_name`; `mod.properties.outputs.<identifier>.attribute_name` | RN, API | `modifiers-and-curves.md` §6 |
| 5.2 | Socket identifiers of the Compare and Random Value nodes as they were up to 5.1 | Changed; in 5.2 the enabled sockets' identifiers equal their names (`A`, `B`, `Result`; `Min`, `Max`, `ID`, `Seed`, `Value`) | RN, API | `modifiers-and-curves.md` §6 |
| 5.2 | A mesh generated from scratch by Geometry Nodes kept the original mesh's name | It no longer does | RN | `modifiers-and-curves.md` §6 |
| 5.1, 5.2 | Node-tool assets saved by an older version | Must be opened and re-saved in 5.1, and again in 5.2; each node tool needs a globally unique idname | RN | — |
| 5.2 | `brush.use_automasking_topology`, `brush.automasking_cavity_factor`, … (same on `tool_settings.sculpt`) | `brush.mesh_automasking_settings.use_automasking_topology`, `.cavity_factor`, `.cavity_blur_steps`, `.start_normal_limit`, `.view_normal_limit`, … (the `automasking_` prefix is dropped from the non-boolean names) | RN, API | `sculpting.md` §4 |
| 5.2 | `paint.eraser_brush`, `paint.eraser_brush_asset_reference` | Removed | RN | — |
| 5.1 | `brush.use_airbrush`, `use_anchor`, `use_space`, `use_line`, `use_curve`, `use_restore_mesh` | One enum `brush.stroke_method`: `AIRBRUSH`, `ANCHORED`, `SPACE`, `LINE`, `CURVE`, `DRAG_DOT` (plus `DOTS`) | RN, API | `sculpting.md` §3 |
| 5.1 | `sculpt.brush_stroke(mode='SMOOTH')`, `'MASK'`, `'ERASE'` (also `paint.image_paint`) | `mode` takes `NORMAL`/`INVERT`; the rest moved to `brush_toggle='SMOOTH'`, `'MASK'`, `'ERASE'` | RN, API | `sculpting.md` §6 |
| 5.1 | `bpy.ops.sculpt.sample_color` | `bpy.ops.paint.sample_color` | RN, API | — |
| 5.1 | `anim.convert_legacy_action` | Removed (every action is layered since 4.4) | RN | `animation.md` §1 |
| 5.1 | Sequencer strip `frame_final_duration`, `frame_final_start`, `frame_final_end`, `frame_start`, `frame_duration`, `frame_offset_start`, `frame_offset_end` | `duration`, `left_handle`, `right_handle`, `content_start`, `content_duration`, `left_handle_offset`, `right_handle_offset`. The old names still work in 5.2 and go away in 6.0; `scripts/lipsync_keys.py` reads `frame_final_duration` | RN, API | — |
| 5.1 | `object.transform_apply(scale=True)` on a negatively scaled object left the normals inverted | New `corrective_flip_normals` option, default True, flips them | RN, API | `game-engine-delivery.md` §3 |
| 5.1 | User site-packages loaded into Blender's Python | Python 3.13; user site-packages ignored unless Blender starts with `--python-use-user-env` | RN, API | `addons-and-scripting.md` §7 |
| 5.2 | `preferences.filepaths.active_asset_library` indexed `asset_libraries` directly | The Preferences list starts with "All Libraries" and "Essentials", so the index is offset by two | RN | `kitbashing.md` §5 |
| 5.2 | EEVEE Fast GI "Far Thickness" | Removed (only `fast_gi_thickness_near` remains); Fast GI, the AO pass and the AO node look different, and some scenes render darker than 5.1 | RN, API | `archviz-lighting-and-rendering.md` §5 |
| 5.2 | Subsurface `RANDOM_WALK` radius scaling | Rescaled to match other renderers; files from older versions are switched to `RANDOM_WALK_LEGACY` on load | RN, API | — |
| 5.1 | Grease Pencil fill came from the material | Fill is the `fill_id` curve attribute (0 = no fill) and `hide_stroke` hides the stroke; a Geometry Nodes *Set Material* no longer fills strokes. From 5.2.4 frame duration is disabled | RN | `outlines-and-line-art.md` §6 |
| 5.1, 5.2 | `UILayout.template_list(columns=)`; `UILayout.template_palette(color=)` | `columns` deprecated (no effect since 5.0); `color` removed | RN | — |
| 5.2 | Preference "Only Insert Available" off | On by default; effect on operator-based keying from scripts not tested | RN | `animation.md` §2 |

## 2. New and useful for game assets (5.1, 5.2)

| Area | Since | What | Source | Guidance |
|---|---|---|---|---|
| Modeling | 5.2 | Three Loop Tools operators are built in: `mesh.circularize`, `mesh.space_edge_loops_evenly`, `mesh.flatten` | RN, API | `addons-and-scripting.md` §1 |
| Modeling | 5.1 | Boolean Exact solver over 35 % faster on meshes with many attributes; edge-loop/ring selection delimiters (seam, sharp, material) | RN | `hard-surface-modeling.md` §2 |
| Modeling | 5.2 | Merging vertices interpolates their custom data; the Array node-group modifier aligns rotation better | RN | `modifiers-and-curves.md` §6 |
| UV | 5.1, 5.2 | `uv.select_tile` (5.1); `uv.select_by_winding`, `uv.unwrap(use_original_bounds=)`, `uv.select_linked(delimit=)`, island support in `uv.select_overlap` (5.2) | RN, API | `uv-unwrapping.md` §3 |
| Geometry Nodes | 5.2 | Mesh Bevel, Merge Points with Cluster by Distance / Connected, Transfer Attributes, Rename Attribute, Get Attribute Names, lists (`GeometryNodeFieldToList`, `GeometryNodeListGetItem`, `GeometryNodeFilterList`, `GeometryNodeSortList`), `GeometryNodeCollectionChildren`, geometry bundles, modifiers on Empties | RN, API | `modifiers-and-curves.md` §6 |
| Geometry Nodes | 5.1 | `GeometryNodeBoneInfo`, `NodeGetBundleItem` / `NodeStoreBundleItem`, `FunctionNodeMatrixSVD`, UV Unwrap Minimum Stretch + No Flip, Pack UV Islands custom region | RN, API | `modifiers-and-curves.md` §6 |
| Materials | 5.1 | Normal Map node `convention` (`OPENGL`/`DIRECTX`) and `base` (`ORIGINAL`/`DISPLACED`; EEVEE honours `base` from 5.2) | RN, API | `shader-nodes.md` §2 |
| Materials | 5.1, 5.2 | `ShaderNodeRaycast` (5.1); attribute outputs at the hit, Cycles only (5.2); `Object.visible_raycast` | RN, API | `stylized-npr.md` §5 |
| Materials | 5.2 | Principled BSDF **Thin Wall** input; a Time node in shader trees | RN, API (Thin Wall) | `shader-nodes.md` §2 |
| EEVEE | 5.1, 5.2 | `scene.eevee.direct_light_intensity` / `indirect_light_intensity` (5.1); `ray_tracing_options.use_backface_hit`, larger `shadow_pool_size` options, camera-ray visibility for lights, faster instancing (5.2) | RN, API | `archviz-lighting-and-rendering.md` §5 |
| Cycles | 5.2 | Texture cache (`.tx` files, `blender scene.blend --command maketx`), Simplify texture resolution, world Cast Shadows | RN | `rendering-and-lighting.md` §1 |
| FBX | 5.1 | Shape-key normals are exported when mesh normals are | RN | `shape-keys-and-visemes.md` §6 |
| glTF | 5.2 | Meshopt compression (`export_meshopt_compression_enable`, `export_meshopt_extension`), point clouds, `KHR_materials_iridescence` and `KHR_materials_dispersion`, hooks can stop an export | RN, API (options) | `web-and-mobile-delivery.md` §4 |
| USD | 5.1, 5.2 | Indexed UVs and `get_prim_map` in export hooks (5.1); color-space tags, NURBS surfaces exported as meshes (5.2) | RN | `usd-and-alembic.md` §1 |
| STL, Alembic | 5.2 | `wm.stl_export(evaluation_mode='DAG_EVAL_RENDER'\|'DAG_EVAL_VIEWPORT')`; Alembic imports animated visibility and camera data as F-curves | RN, API (STL) | `3d-printing.md`, `usd-and-alembic.md` §3 |
| Images | 5.1 | AVIF read/write; OpenEXR HTJ2K lossless compression | RN | — |
| Animation | 5.1 | Faster action and shape-key evaluation; `anim.replace_action`, `anim.replace_action_new`; F-curve modifier type `SMOOTH` (Gaussian, must be first in the stack); `object.shape_key_apply_to_basis` | RN, API | `animation.md` §2, `shape-keys-and-visemes.md` §1 |
| Animation | 5.2 | `screen.animation_pause`, `armature.duplicate_rename`, `action.select_by_type`, playback loop modes | RN, API (first two) | `animation.md` §3 |
| Sculpt | 5.1, 5.2 | Blur brush, `sculpt.face_set_change_visibility(active_face_set=)` (5.1); Scene Project brush, voxel remesh interpolates attributes (5.2) | RN | `sculpting.md` §3 |
| Physics | 5.2 | Experimental Cloth Dynamics and Hair Dynamics node-group modifiers on an XPBD solver node | RN, API (`GeometryNodeXPBDSolver`) | `simulation.md` §4 |
| Assets | 5.2 | Online asset libraries and Online Essentials; per-asset preferred import method | RN | `kitbashing.md` §5 |
| Python | 5.1 | `bpy.app.cachedir`, `bpy.app.handlers.exit_pre`, `mesh.validate()` repairs non-finite multires data | RN, API (first two) | — |
| Python | 5.2 | `bpy.data.all_ids`, `Window.screenshot()`, `gpu.init()` for background mode, `bpy.ops.wm.save_auto_save`, `render.save_output`, `file_path_foreach` flags `EXPAND_TOKENS` / `EXPAND_SEQUENCES` / `EXPAND_CACHES`, slice steps on `mathutils` types and RNA arrays | RN, API (first five) | `blender-bridges.md` §7, `render-farm-and-compositing.md` §3 |

## 3. After upgrading to 5.3

Release notes only: nothing here was run. Re-test the affected script on 5.3 before trusting a row.

| Area | Change in 5.3 | Affects |
|---|---|---|
| GPU | Vulkan is the default backend on Windows (not ARM) and Linux; `--gpu-backend opengl` selects the old one | Viewport screenshots and EEVEE renders: `blender-bridges.md` §7, `rendering-and-lighting.md` §1 |
| Python | The default `name` of a `PropertyGroup` is read-only (a `name` property declared on the subclass is fine); `bpy.data.all_ids` order changed and is unspecified | Custom add-ons: `addons-and-scripting.md` §5 |
| Compositor | An effects stack replaces the single scene node group; the default tree is Group Input → Group Output with no Render Layers node; File Output's default name is `{blend_name}`; rendering no longer writes viewer images | `render-farm-and-compositing.md` §4 |
| EEVEE | A Sky Texture with Sun Disc enabled now lights the scene, so older scenes look different; panoramic cameras; Material Lighting nodes (Light Accumulation, Light Info, Light Evaluation, Shadow Raycast) for toon shading | `archviz-lighting-and-rendering.md` §2, `stylized-npr.md` §3 |
| Cycles | Principled BSDF gains Dispersion (Transmission panel); Glass and Principled transmission get roughness anisotropy; better bake quality on thin triangles and near margins | `rendering-and-lighting.md` §4, `baking-maps.md` |
| Paint | The brush *Falloff* panel is renamed *Shape* in Sculpt, Vertex, Weight and Texture Paint; unified-setting toggles (size, strength, color) are stored per brush, not per scene; Weight Paint's default brush is "Add Weight", "Paint" is renamed "Set Weight", and Multi-Paint, Auto-Normalize and Mirror Vertex Groups default to on; Front Face Falloff is deprecated in Vertex/Weight Paint in favour of automasking | `sculpting.md` §6, `texture-painting.md` §3, `rigging-and-weights.md` §1 |
| Geometry Nodes | The Import PLY node's output socket is renamed `Geometry`; Curve to Mesh gains Miter Scale; Realize Instances gains Preserve Normals; new Construct Curves, Combine List, Get Vector Component and Geometry Materials nodes | `modifiers-and-curves.md` §6 |
| Modeling | Quad-Sphere mesh primitive; the remaining Loop Tools operators (Relax, Curve, Gstretch) are built in; origin snapping; editable selection dimensions in Edit Mode | `topology.md`, `addons-and-scripting.md` §1 |
| Animation | New `anim.rotation_mode_convert` (the Rigify `pose.convert_rotation` is deprecated) and `convert_rotation_mode` on `Object` and `PoseBone`; `constraints.new(type, name)` accepts a name; `context.markers`; shape-key Duplicate copies every selected key | `animation.md` §2, `rigging-and-weights.md` §4 |
| glTF | KTX2 textures (`KHR_texture_basisu`) on import and export; import presets; an instance collection exports with one level less; Animation Pointer for custom properties; many exporter fixes (loose edges, vertex colors, light strength) | `web-and-mobile-delivery.md` §4, `game-engine-delivery.md` §2 |
| USD, Alembic | USD collection importer and normals written in Blender's original representation; Alembic subdivision parameters, arbitrary attributes and point clouds | `usd-and-alembic.md` §1, §3 |
| Color | `colorspace_settings.interop_id` (for example `'data'`, `'srgb_rec709_display'`) beside `name`; sRGB images are saved with an ICC profile; `OpenEXR` and `opentimelineio` modules are bundled | `shader-nodes.md` §2 |
| Core | Optional project system (`.blender_project` directory, `{project_root}` in path templates, per-project OpenColorIO config) | `project-files-and-naming.md` |
| Grease Pencil | Frame duration disabled (as in 5.2.4); selection and a Carver tool in Draw Mode | `outlines-and-line-art.md` §6 |

## 4. Where sources disagree

The installed version's documentation wins.

| Topic | Release notes | Installed 5.2 | Used in this skill |
|---|---|---|---|
| Grease Pencil layer masks | 5.2 notes name `layer.layer_masks.add` / `.remove` | The API reference has `GreasePencilLayer.mask_layers` (`GreasePencilLayerMasks.add`) | `layer.mask_layers` |

## 5. Re-checking after a new release

1. Read the raw release notes per page: `https://projects.blender.org/blender/blender-developer-docs/raw/branch/main/docs/release_notes/<version>/<page>.md` (pages: `index`, `python_api`, `modeling`, `geometry_nodes`, `animation_rigging`, `pipeline_io`, `eevee`, `cycles`, `rendering`, `sculpt`, `compositor`, `grease_pencil`, `assets`, `core`, `physics`). The raw files keep identifiers exact; a summarised fetch does not.
2. Grep this skill (`*.md` and `scripts/*.py`) for every removed or renamed identifier in those pages.
3. Check what the skill names against the install without opening a file: in `blender -b --factory-startup --python <script>`, test each `bpy.ops.<module>.<name>` with `get_rna_type()`, compare call keywords with its `properties`, and test `bpy.types.<Name>` and node idnames with `hasattr`.
4. Fix facts where their guidance lives, then update this file's dates, range and rows, and add a `CHANGELOG.md` line.
