# Game Engine Delivery

How to get a finished Blender asset into Unity, Unreal 5 or Godot 4 without scale, axis, shading, material, LOD or collision surprises: export settings, naming, LODs, collision and sockets, the bake summary and the round-trip checks that prove the file is right. Read it when an asset leaves Blender for an engine; web viewers, mobile and standalone VR are in `web-and-mobile-delivery.md`, budgets in `poly-budgets-and-targets.md`, full bake settings in `baking-maps.md`. Exporter option names below were read from the Blender 5.2 operators (`export_scene.fbx`, `export_scene.gltf`, `wm.usd_export`, `wm.obj_export`).

## Contents
1. Choosing the delivery format
2. Per-engine export settings
3. Names, pivots, transforms and shading at export
4. LODs
5. Collision and sockets
6. Game bake pipeline (summary)
7. Verifying a delivery (scripts)
8. Common failures

## 1. Choosing the delivery format

| Target | First choice | Also works | Avoid |
|---|---|---|---|
| Unity | FBX | glTF via a package (glTFast) | OBJ (no hierarchy/anim, 1 UV set) |
| Unreal 5 | FBX | glTF / USD through the Interchange importer [unverified per UE version] | OBJ |
| Godot 4 | glTF/GLB | `.blend` directly (Godot runs Blender's glTF exporter; needs the Blender path set in editor settings) | FBX for rigs unless the pipeline is proven |
| three.js, model-viewer, Babylon | GLB | — | FBX/OBJ in production |
| iOS AR Quick Look | USDZ (`wm.usd_export`, filepath ending `.usdz` — writes the zip package directly, verified 5.2) | — | — |
| Film / DCC interchange | USD | Alembic (caches) | — |

Collada was removed in Blender 5.0. OBJ carries one UV set and no animation (verified by `scripts/export_check.py`: a second UV map is lost).

## 2. Per-engine export settings

Blender is Z-up, right-handed, 1 BU = 1 m. Unity and Godot are Y-up (1 unit = 1 m), Unreal is Z-up in centimetres. FBX stores axes and units as metadata that importers interpret differently, which is why FBX axis/scale is the classic failure; glTF is fixed by spec (Y-up, metres) and the exporter converts (`export_yup=True`, default).

| Setting (operator option) | Unity (FBX) | Unreal 5 (FBX) | Godot 4 (GLB) | Web (GLB) |
|---|---|---|---|---|
| Scope | `use_selection` / `collection` / `use_active_collection` | same | `use_selection` / `collection` | same |
| Scale | `apply_scale_options='FBX_SCALE_ALL'` (object scale 1 in Unity) | `'FBX_SCALE_NONE'` + `apply_unit_scale=True` (file in cm) | n/a (metres) | n/a |
| Axes | `axis_forward='-Z'`, `axis_up='Y'`, `bake_space_transform=True` ("Apply Transform": no −90° X root) | `-Z`/`Y` defaults; Unreal's importer converts [unverified per version] | `export_yup=True` | `export_yup=True` |
| Modifiers | `use_mesh_modifiers=True` | same | `export_apply=True` (shape-key assets: False, §3) | `export_apply=True`; `export_apply=False` when meshes carry shape keys — the glTF exporter drops them with Apply Modifiers (`shape-keys-and-visemes.md` §6) |
| Smoothing | `mesh_smooth_type='FACE'` (default `OFF` triggers "no smoothing groups" warnings) | `'FACE'` | normals always written (`export_normals`) | same |
| Tangents | engine recomputes (MikkTSpace); `use_tspace=True` only for quads/tris meshes | same | `export_tangents` usually off | off (three.js computes if needed) |
| Triangulation | `use_triangles` off; a real Triangulate (Beauty) modifier before baking, kept for export (`baking-maps.md` §1) | same | glTF is always triangles (same modifier rule) | same |
| Normal maps | OpenGL (Y+) | DirectX (Y−): `scripts/bake_maps.py --normal-convention DIRECTX` | OpenGL (Y+) | OpenGL (Y+, glTF spec) |
| Custom properties | `use_custom_props=True` → FBX user properties | same | `export_extras=True` → glTF `extras` (verified) | same |
| Rigs | `add_leaf_bones=False`, `use_armature_deform_only=True`, `primary_bone_axis`/`secondary_bone_axis` | same | `export_def_bones`, `export_influence_nb=4` (or `export_all_influences`) | 4 influences |
| Animation | `bake_anim`, `bake_anim_use_all_actions`, `bake_anim_use_nla_strips` | same | `export_animation_mode='ACTIONS'` (or `NLA_TRACKS`) | same |
| Textures | `path_mode='COPY'` + `embed_textures` for one file | same | embedded in GLB | `export_image_format` `AUTO`/`JPEG`/`WEBP` |

Validated round-trip presets for these columns are `PRESETS` in `scripts/export_check.py` (`unity`, `unreal`, `godot`, `web`). Animation-specific export (action slots, NLA, root motion) is in `animation.md`.

Engine-side notes:
- **Unity**: LOD groups are created from `_LOD0`… name suffixes on sibling meshes (max 8 levels). Normal maps OpenGL (Y+). Materials extract as Unity materials by slot name.
- **Unreal 5**: Normal maps DirectX (Y−) — flip green or bake with `scripts/bake_maps.py --normal-convention DIRECTX` (the same value goes to the script's `normal_convention` option in live mode). Collision/socket prefixes §5. Nanite meshes don't need LODs; skeletal meshes and translucent/masked foliage still do [check the project's Nanite settings].
- **Godot 4**: scene import generates mesh LODs automatically (meshoptimizer) for glTF/.blend/FBX scenes; name suffixes drive import: `-col` (mesh + trimesh collision), `-convcol` (convex), `-colonly` / `-convcolonly` (collision only), `-rigid`, `-vehicle`/`-wheel`, `-navmesh`, `-occ`/`-occonly`, `-noimp` (skip). Normal maps OpenGL.
- **three.js / model-viewer** loaders, decoders, colour space and tone mapping: `web-and-mobile-delivery.md` §1.

## 3. Names, pivots, transforms and shading at export

Control rigs (IK, Rigify): bake animation to the deform bones or an export skeleton before export — `rigging-and-weights.md` §4.4 (`scripts/ik_rig.py`).

- **Working file vs export copy**: the working file keeps `MAT_` materials and role-prefixed objects. Engine names (`SM_`/`SK_` meshes, `M_`/`MI_` materials, `T_` textures) are applied in an export collection or a duplicated scene just before export. `scripts/export_check.py` ignores these prefixes when matching materials, and its preflight accepts `M_`/`MI_` as well as `MAT_` material names on export copies (any other name is a naming warning, not a failure).
- **Pivot**: origin at `BOTTOM_CENTER` for props/characters, hinge for doors, wheel centre for wheels. Asset roots at world origin when exporting one asset per file (Unreal sockets and collision assume it).
- **Apply scale and rotation** on every mesh (Ctrl+A). An unapplied scale survives FBX and glTF as an object scale in the engine (physics, collision and lightmap density go wrong). Measured: a mesh with scale 2 exports with object scale `[2,2,2]` in both FBX and GLB.
- **Negative scale** (mirrored objects) flips normals in most engines — apply it. 5.1+: `object.transform_apply(scale=True)` flips the normals itself (`corrective_flip_normals`, default True; measured in 5.2 on a cube scaled −1 on X: 6 of 6 faces point outward after the apply, 0 of 6 with the option off). Recalculate normals on older builds or when the scale was applied another way, and confirm with `mesh_report.py`.
- **Shading**: Smooth by Angle (modifier, 4.1+) or sharp edges; hard edges must coincide with UV seams where a normal map is baked. Weighted normals / custom normals survive FBX and GLB (verified); `export_normals=False` loses them.
- **Material slots**: each used slot is a draw call per object; remove empty and unused slots before export.
- **Shape-key assets** (blend shapes, visemes): glTF `export_apply` must be **False** — the exporter drops shape keys when Apply Modifiers is on. Apply the other modifiers on the export copy first; recipe and checks in `shape-keys-and-visemes.md` §6.

## 4. LODs

| Step | Practice |
|---|---|
| Ratios | ~50 % tris per level: LOD0 1.0, LOD1 0.5, LOD2 0.25, LOD3 0.125; stop when the object covers < ~5 % of screen height |
| Method | Decimate **Collapse** for organic/curved (ratio; `use_symmetry` + `symmetry_axis` for mirrored assets), **Planar** (`decimate_type='DISSOLVE'`, angle 1–10°, delimit UV/seams/materials) for hard-surface, **Un-Subdivide** for subdivided grids |
| Quality | Check silhouette from front/side/top and the maximum surface deviation; UV seams and material borders must survive |
| Naming | `<Name>_LOD0`…`_LODn` siblings (Unity auto LOD group) |
| FBX LOD group | Parent the LODs to an empty with custom property `fbx_type = "LodGroup"`; Blender's binary FBX exporter writes that empty as an FBX LodGroup node (verified: the string is in the file). Unreal imports LODs from a LodGroup node when "Import Mesh LODs" is on [unverified in engine here]; the empty's name is free — `LOD_<Name>` is used by the script |
| Engine auto-LOD | Unreal (Nanite / auto LOD), Godot (import LODs), Unity (LOD Group + mesh simplifier packages) — prefer hand LODs for hero assets |

`scripts/lod_collision.py` builds the chain from the evaluated source (source untouched, re-runs replace), corrects the Decimate ratio until tris are within 5 % of target, and reports per LOD: tris, max/p95/mean surface deviation in mm (two-way closest-point sampling), deviation as % of the bbox diagonal, and orthographic silhouette IoU on X/Y/Z. Measured on a bevelled 3,308-tri test asset: LOD1 1,654 tris (0.054 % deviation, IoU 0.999), LOD2 826 (0.117 %), LOD3 412 (0.194 %, IoU 0.985); an over-decimated 12-tri level failed (13.2 %, IoU 0.69). Planar at the same 50 % target deviated more (IoU 0.946) on that curved asset — use it for flat hard-surface.

**Batch mode**: `--objects A,B,C` or `--source-collection NAME` runs the same pipeline per mesh (generated `_LODn` and `UCX_`/`UBX_`/`USP_` objects are skipped, so re-runs are idempotent) and returns per-object results plus an overall pass; `--out-collection NAME` receives the LODs, LodGroup and collision objects (`--collection` is a deprecated alias — note it names the *output* collection, unlike the other scripts of this skill where `--collection` is the input scope). Decimation does **not lock border (open-edge) vertices**: on kit pieces whose socket edges must stay aligned, COLLAPSE can move boundary vertices — mark the borders sharp/seam and use PLANAR (its SEAM/SHARP delimiters keep them), then re-run `scripts/tile_sockets.py` on the LODs.

**Re-validating kit sockets per LOD level**: `scripts/tile_sockets.py` treats an Empty with mesh children as one tile, so link the `_LODn` objects of one level into a temporary collection per level and run it there; every tile's socket IDs must equal the LOD0 rules file.

## 5. Collision and sockets

| Engine | Convex | Box | Sphere | Capsule | Triangle mesh | Sockets |
|---|---|---|---|---|---|---|
| Unreal (FBX names) | `UCX_<Mesh>_NN` | `UBX_<Mesh>_NN` | `USP_<Mesh>_NN` | `UCP_<Mesh>_NN` | complex-as-simple setting | `SOCKET_<Name>` empty parented to the mesh |
| Godot 4 (name suffix) | `-convcol` / `-convcolonly` | shapes set in import dock | same | same | `-col` / `-colonly` | `BoneAttachment3D` / child nodes |
| Unity | Mesh Collider "Convex" on a mesh | Box Collider component | Sphere Collider | Capsule Collider | Mesh Collider | child empties |

Rules: `<Mesh>` must match the **exported** render mesh name exactly (so apply `SM_` naming to collision too); several hulls of one mesh are numbered `_00`, `_01`; each hull must be convex (engines re-hull silently otherwise); keep hulls ≤ 255 triangles (Unity's convex Mesh Collider limit) — usually 8–64 are enough; build one hull per convex part (legs, seat, back) instead of one blob. Unreal accepts only one socket-carrying mesh per FBX. When a LodGroup empty exists (§4), `<Mesh>` is assumed to be the **LOD0 render-mesh name** `[unverified in engine]` — settle it with one engine import before naming a library of hulls.

`scripts/lod_collision.py --collision convex,box,sphere [--per-part] [--max-hull-tris N]` creates hulls with `bmesh.ops.convex_hull`, reduces them to the tri limit, inflates just enough to enclose every render vertex, and verifies convexity and enclosure; `--check-collision UCX_Name_` validates hand-made pieces as a set (every render vertex inside at least one piece). Planted defects caught: a hull shrunk 15 % (747 mm outside, 1,631 uncovered vertices) and a concave copy of the render mesh named `UCX_` (convexity violation 862 mm).

Collision hulls and LODs are **siblings** of the render mesh (same parent and world matrix), so export and check them **by collection** — `scripts/export_check.py --collection <ExportCollection>` — not with `--objects`, which pulls in the named objects and their children only and leaves the hulls out of the file.

**One FBX per kit piece**: keep each piece's `_LOD0..n` meshes, its `LOD_` empty and its `UCX_/UBX_` hulls in their own sub-collection and export that collection (`scripts/export_check.py --collection <piece>`); hulls are siblings of the render mesh, so `--objects` (children only) would drop them. Rename to `SM_` **before** generating collision — `lod_collision.py` batch mode names hulls after the source object and ignores `--render-name`.

## 6. Game bake pipeline (summary)

1. High poly (sculpt / subd / booleans) and low poly share scale, position and names (`_high`/`_low`).
2. Low poly: a real Triangulate (Beauty) modifier before baking, kept through export, so the engine's triangulation matches the bake (`baking-maps.md` §1); hard edges on UV seams.
3. UVs: non-overlapping, padding for the target resolution, consistent texel density; UV2 for lightmaps — `uv-unwrapping.md`, `scripts/uv_tools.py`.
4. Bake normal (tangent space; OpenGL for Unity/Godot, DirectX for Unreal — `--normal-convention DIRECTX`), AO, curvature, and material maps with `scripts/bake_maps.py` (cage extrusion 1–3 % of size, bake at 2× and downsample) — `baking-maps.md`. Procedural materials must be baked: FBX and glTF carry only Image Texture links.
5. Pack channels per engine (Unreal ORM: R=AO, G=Roughness, B=Metallic; Unity URP/HDRP mask maps differ; glTF metallicRoughness: G=Roughness, B=Metallic).
6. LODs and collision (§4–5), naming for export (§3), round-trip check (§7).

## 7. Verifying a delivery (scripts)

USD/Alembic hand-off and unit metadata: `usd-and-alembic.md` §1–§4 (`scripts/interchange_check.py`). glTF extensions, variants, compression and texture formats for viewers: `web-and-mobile-delivery.md` §6.

| Question | Script | Proven by test |
|---|---|---|
| Do the LODs hit targets without breaking the silhouette? Are hulls convex and enclosing? | `scripts/lod_collision.py` | chain within 1 tri of 50/25/12.5 %; 12-tri LOD and shrunk/concave hulls fail |
| Does the file come back with the same size, axes, materials, UVs, normals, animation? | `scripts/export_check.py --preset unity\|unreal\|godot\|web` (`--collection` for assets with collision, §5) | clean FBX/GLB pass; `axis_up='Z'` FBX and `export_yup=False` GLB → "axis error"; `global_scale=100` → "scale error x100"; unapplied scale 2 → "object scale [2,2,2] reaches the engine"; GLB without UVs/normals/materials/animation → each loss reported; file-size budget (`budget_mb`) enforced |
| Will the scene fit draw-call / texture / triangle budgets? | `scripts/scene_perf_report.py --budget quest3\|quest2\|pcvr\|mobile\|web\|pc [--max-draw-calls N] [--max-tris N] [--max-texture-mb N]` | 20-material vs atlased scene numbers in `web-and-mobile-delivery.md` §5; unused material slots listed |

`scene_perf_report.py` gates `draw_calls` on `totals.draw_calls_naive` (worst case: every instance drawn separately; the instanced count is reported beside it, not gated), `tris` on `totals.tris` and `texture_mb` on the block-compressed estimate; `--max-draw-calls` / `--max-tris` / `--max-texture-mb` override single limits of the chosen preset or, without `--budget`, form a custom budget of just those limits (`budget.gated_on` and `budget.overrides` name what was compared). When a **level** rather than an asset fails the draw-call gate, the fix is engine-side instancing, HLOD and streaming cells — `large-sets-and-cities.md` §10 — not more decimation.

A Blender round-trip proves self-consistency, not engine behaviour: import once into the target engine per pipeline change and look (scale against a 1.8 m capsule, normal-map lighting from two sides, LOD switch distances, collision debug view).

## 8. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Asset 100× too big/small in engine | FBX unit scale vs apply scale option mismatch | Unity `FBX_SCALE_ALL`; Unreal `FBX_SCALE_NONE` + unit scale; check with `export_check.py` |
| Asset lies on its back / −90° X root in Unity | FBX axis conversion kept as a root rotation | `bake_space_transform=True`, axes −Z/Y; apply rotation |
| Object scale ≠ 1 in engine, physics odd | Unapplied scale in Blender | Ctrl+A Scale before export |
| Faceted or wrongly smoothed shading | Smoothing not exported / custom normals dropped | `mesh_smooth_type='FACE'`; keep `export_normals`; triangulate before bake |
| Normal map lighting inverted on one axis | OpenGL vs DirectX green channel | Unreal DirectX (`--normal-convention DIRECTX`); Unity/Godot/glTF OpenGL |
| Seams visible in engine along hard edges | Hard edge not on a UV seam, or bake triangulation differs | Seams on hard edges; permanent Triangulate modifier before baking (`baking-maps.md` §1) |
| Unreal ignores collision | `UCX_` name doesn't match exported mesh name, or hull not convex | Rename to exported `SM_` name (LOD0 name when a LodGroup exists); `--check-collision` |
| Collision hulls missing from the exported file | Exported with `--objects` (children only); hulls are siblings | Export by collection (§5) |
| LODs import as separate meshes | No LodGroup / wrong suffix | `_LODn` suffix (Unity), `fbx_type=LodGroup` empty (Unreal) |
| Kit-piece LOD no longer meets its neighbour at the socket edge | COLLAPSE moved open-edge vertices | Borders sharp/seam + PLANAR; re-run `tile_sockets.py` (§4) |
| Shape keys missing after glTF export | `export_apply=True` | `export_apply=False`; `shape-keys-and-visemes.md` |
| Lightmap UV lost | OBJ export or UV2 not created | FBX/GLB; create UV2 before export |
| Animation missing after export | Action slot not assigned / not in NLA / export mode | `animation.md`; `export_animation_mode`; `export_check.py` animation count |
| Level fails the draw-call gate although each asset passes | Per-instance draw calls (`draw_calls_naive`) | Engine instancing / HLOD / streaming cells — `large-sets-and-cities.md` §10 |
| A floor/wall renders invisible in engine but every coverage audit passes | Faces point away from the viewer (flipped): top-down visibility rays and one-sided collider raycasts skip them, so the audit never samples the surface | Check orientation before export: count faces whose normal points to the expected side (up for floors, toward the interior for pit/room walls); render from inside with back-face culling on (Workbench/solid shows back faces) |
| Shading steps or lines along the borders between separately exported pieces of one surface (terrain tiles, chunks), worst under a low grazing light | Each object's normals are computed on its own, so the two sides of a border differ | Weld the pieces' positions, compute angle-weighted normals once on the union (skip zero-area triangles and needles with a corner under 5°), write them back per object as custom normals, and verify in the engine that coincident vertices agree (dot > 0.9999) |
| Short light or dark streaks on otherwise smooth terrain under a low light | A needle triangle (corner ~1°, ~180° opposite) tilted steeply, e.g. after height smoothing moved its vertices; angle-weighted vertex normals give its big corner a full vote, bending the neighbours' normals | Exclude needles (min corner < 5°) from the normal computation (or weight by area); prefer re-triangulating them away before export |
| Custom normals come out wrong, up to 90°, at a few vertices | `normals_split_custom_set_*` stores each normal in its corner's local frame, undefined at near-zero corner angles (slivers from bisect or decimation) | Blender 5.x "free" custom normals: a FLOAT_VECTOR `custom_normal` attribute on the POINT domain is used as-is; read `corner_normals` back and measure with atan2(|a×b|, a·b) (arccos near 1 is float noise) |
| Cracks or a shading line where two pieces meet after one was subdivided | Per-object subdivision put vertices in the middle of the neighbour's border edge (T-junctions) | Split the neighbour's border edge at those vertices; re-triangulate by fanning from the opposite corner (BEAUTY draws the diagonal across the collinear vertex: zero-area triangles); snap near-duplicate vertices (bisect leaves ~1e-8 m pairs) to one exact position |
