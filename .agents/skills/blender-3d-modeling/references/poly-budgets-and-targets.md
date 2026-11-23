# Poly Budgets & Targets

Poly count only matters relative to the target. Game budgets are counted in **triangles** (after triangulation) and, just as importantly, in **draw calls** and **texture memory**; film/archviz usually talk faces or "subdivision-ready"; CAD/print care about accuracy and manifoldness, not counts. Set the budget *before* modeling and report against it at the end (`scripts/mesh_report.py` gives tris per object, `scripts/scene_perf_report.py` gives draw calls and texture memory for a whole scene).

## Contents
1. Low poly vs high poly
2. Budget tables (LOD0, starting points — confirm with the user's engine/team)
3. Per-target checklists
4. LODs, baking and the hybrid pipeline
5. Reducing poly count without ruining a model

## 1. Low poly vs high poly

- **High poly**: the "truth" version — subdivided cages, sculpts, dense bevels. Used directly for renders/film, and as a **bake source** for games. Topology must be clean enough to subdivide (quads, support loops) but count is almost free.
- **Low poly**: the shipped real-time mesh. Silhouette preserved, detail moved into normal/AO/curvature maps baked from the high poly. Topology must be efficient: tris allowed, no support loops, no bevels beyond 1 segment where the silhouette needs it, hard edges split via smoothing/sharp marks matching UV seams.
- **Mid poly / "high-poly-as-low-poly"**: modern PC/console approach — beveled high-ish mesh (50–200k tris) with weighted normals and no bake; works with Nanite (UE5) / virtualized geometry. Only when the pipeline confirms it; never for mobile or standalone VR.
- **Stylized low poly (art style)**: deliberate faceting, flat shading, 100–5,000 tris, per-face colors; here quads vs tris is aesthetic — control triangle direction deliberately (Beauty vs Fixed triangulation changes the look). Palettes, flat shading and outlines: `stylized-npr.md` §4.

## 2. Budget tables (LOD0, starting points — confirm with the user's engine/team)

Per-asset rows are rules of thumb. The whole-frame rows for VR are Meta's published per-frame guidance (medium simulation load); treat them as ceilings for everything visible at once, not per asset.

| Asset | Mobile / AR (tris) | PC / Console (tris) | PC VR (tris) | Standalone VR, Quest-class (tris) |
|---|---|---|---|---|
| Hero character (body + clothing) | 3k–15k (up to 30k high-end) | 30k–100k+ | 20k–60k | 5k–20k |
| NPC / crowd character | 1k–5k | 5k–20k | 5k–20k | 1k–8k |
| First-person weapon | 3k–8k | 20k–60k | 15k–40k | 5k–15k |
| Hero prop (held/inspected) | 1k–5k | 5k–30k | 3k–20k | 2k–8k |
| Standard prop (crate, barrel, chair) | 100–800 | 500–5k | 300–3k | 200–1.5k |
| Vehicle (drivable, racing hero) | 5k–20k | 50k–150k | 30k–80k | 10k–30k |
| Modular building piece | 200–2k | 1k–10k | 500–8k | 300–3k |
| Foliage cluster (cards) | 50–500 | 500–5k | 200–3k | 100–1k |
| **Whole visible frame** | ~100k–300k | 1–5M+ (engine-dependent; Nanite changes this) | 1–2M | Quest 2/Pro 750k–1M; Quest 3/3S 1.3–1.8M |
| **Draw calls per frame** | 100–200 | 2k–5k (with batching) | 500–1,000 | Quest 2/Pro 200–300; Quest 3/3S 400–600 |
| **Frame rate** | 30–60 | 30–120 | 90 | 72 minimum (72/90/120 Hz) |

Standalone VR renders every frame twice on a phone-class GPU: draw calls, overdraw (alpha) and texture memory run out before triangles do. Mobile/VR delivery details (atlasing, ASTC, lightmaps) are in `web-and-mobile-delivery.md` §5.

Other targets:
- **Film / offline render**: no hard cap; hero characters 50k–500k base faces + Multires/subd to millions at render; keep base quad-clean.
- **Archviz**: furniture 10k–50k faces each; ornate elements 200k+; rooms often 1–10M total in Cycles. Real-time archviz (Unreal/Twinmotion) → use PC/console prop budgets; VR walkthroughs → the VR columns.
- **Web (three.js, model-viewer, Sketchfab-style viewers)**: target **≤ ~100k tris for the whole scene** (≤ 50k when mobile browsers matter; up to ~150k for a single desktop-first hero product), GLB ≤ 5–10 MB after mesh + texture compression, textures ≤ 2K. Details in `web-and-mobile-delivery.md` §4.
- **3D printing**: 100k–500k faces (FDM) / 0.5–1.5M (resin) is a comfortable range; more is just file size. What matters: watertight, wall thickness, no non-manifold edges (`3d-printing.md` §5).
- **Scans / photogrammetry / AI meshes**: decimate to the target budget of the delivery column after repair, gated by max deviation from the source (`mesh-repair.md`, `scripts/mesh_repair.py`).
- **CAD / engineering visualization**: tessellation driven by chord tolerance, not budget; often exported from CAD, then decimated for viz.

Micro-triangles (sub-pixel on screen) are waste on any real-time target; spend triangles on silhouette and on parts the camera gets close to.

## 3. Per-target checklists

### Game-ready (Unity / Unreal / Godot)
- [ ] Triangle count within budget per LOD; report it (`scripts/lod_collision.py` reports tris per LOD)
- [ ] Real-world scale (1 unit = 1 m); scale/rotation applied; origin at pivot (feet for characters, contact point for props)
- [ ] Single mesh per material group where possible; ≤ 2–4 material slots per asset (each used slot is a draw call)
- [ ] Naming: working file uses `MAT_` materials, role-prefixed objects and `T_<Asset>_<Map>` textures (`T_` is correct at every stage); only the engine mesh prefixes (`SM_`/`SK_`) and material prefixes (`M_`/`MI_`) are applied to the **export copy**, not the working file (`project-files-and-naming.md` §1); no spaces
- [ ] Clean triangulation (Triangulate modifier, Beauty) before baking, so the engine's triangulation matches the bake
- [ ] Hard edges = sharp marks/split normals = UV seams; smooth-by-angle set sensibly
- [ ] UVs: non-overlapping (except intentional mirroring), padding per resolution (`uv-unwrapping.md` §5), straightened shells, consistent texel density (e.g. 512 px/m props, 1024 px/m hero) — see `uv-unwrapping.md`; verify with `scripts/uv_tools.py check`
- [ ] Second UV channel for lightmaps if static lighting is baked (no overlap, padding)
- [ ] Normal map baked from high poly (tangent space; DirectX/Y− for Unreal, OpenGL/Y+ for Unity and Godot), AO, curvature
- [ ] LODs (`_LOD0`–`_LOD3`, ~50 % reduction each) or engine auto-LOD / Nanite
- [ ] Collision: simple convex hulls `UCX_<Mesh>_NN` (or `UBX_`/`USP_`), sockets `SOCKET_<Name>`; Godot uses `-col`/`-convcol` name suffixes instead
- [ ] Export: FBX or glTF with the per-engine settings in `game-engine-delivery.md` §2 (axis/scale presets differ per engine and FBX axis handling is the classic failure) — verify with `scripts/export_check.py` (round-trip: scale, axis, materials, UV sets, normals, animation)
- [ ] Animated exports: `scripts/export_actions.py` (leaf bones off, deform bones only, per-clip re-import verification) — `animation.md` §5
- [ ] Skinned meshes: bone influences per vertex **4 on mobile/standalone VR, 8 on PC/console, unlimited for film**; quad-dominant loops at joints

### Film / high-quality render
- [ ] All-quad cage where subdivided; no ngons under Subdivision; support loops or creases consistent
- [ ] Subdivision live (viewport 1–2, render 2–4) or Multires with displacement
- [ ] Real scale (SSS, DOF, physics depend on it)
- [ ] UDIM UVs if hero; clean seams hidden (`uv-unwrapping.md`)
- [ ] Separate objects per material where materials are complex
- [ ] Modifier stacks kept live; sculpt source saved in `_hp` collection
- [ ] Rig-ready loop flow if animated

### Archviz
- [ ] Real dimensions (mm-accurate for fixtures/joinery); scene in meters
- [ ] Walls/floors/ceilings as separate objects; no coplanar overlaps; interior faces removed
- [ ] Repeated fixtures as collection instances / linked data
- [ ] Furniture at reference dimensions, beveled edges (real edges are never sharp)
- [ ] UVs on visible surfaces (wood grain direction!), tileable material scale correct
- [ ] Hierarchy by level/room; naming as `scripts/plan_to_rooms.py` produces: `WALL_`, `SLAB_`, `FLR_`, `OPN_` (opening empties), `GLASS_`, `DOOR_`, `FURN_`; materials `MAT_`
- [ ] For real-time archviz: apply game checklist budgets; lightmap UVs only for baked/static lighting (not needed with Lumen)
- [ ] Shell sealed and shots checked with `scripts/archviz_gates.py` (leaks, closure, z-fighting, contact, dims, glass, camera, render); geometry gates: `archviz-modeling.md` §8; shot gates: `archviz-lighting-and-rendering.md` §6

### CAD-like / 3D printing
- [ ] One watertight manifold shell per printed part (3D Print Toolbox: 0 non-manifold, 0 intersecting, 0 zero faces)
- [ ] Normals outward everywhere
- [ ] Wall thickness per process (FDM 0.8 mm minimum, 1.2 recommended; resin 0.5 mm supported / 1.0 mm unsupported); FDM interlocking clearance 0.3–0.5 mm per side; small holes +0.2–0.3 mm oversize — full table and fits: `3d-printing.md` §3–4
- [ ] Dimensions typed, not eyeballed; tolerances noted
- [ ] Exported in mm: STL via `bpy.ops.wm.stl_export(global_scale=…)` (binary by default); 3MF has **no built-in exporter** — needs an extension/add-on; check volume/bounding box before export
- [ ] `scripts/export_print.py` passes (wall thickness, part clearance, manifold, re-import bbox in mm)
- [ ] If parametric/STEP needed → build123d/CadQuery (`scripts/cad_enclosure_template.py` as a starting point). Full workflow: `3d-printing.md`; CAD bridge and enclosure rules: `cad-and-enclosures.md` §1–3

### Web / AR (glTF/GLB, USDZ)
- [ ] Whole scene ≤ ~100k tris (see §2), textures ≤ 2K, PBR metallic-roughness
- [ ] Single GLB, Y-up (exporter default), meters, modifiers applied; mesh compression (Draco or meshopt, both built into the 5.2 exporter) and KTX2/WebP textures where the viewer supports them
- [ ] USDZ for iOS AR Quick Look: `bpy.ops.wm.usd_export(filepath="x.usdz")` writes the .usdz package directly (5.2 verified; `usdz_downscale_size` caps textures)
- [ ] Origin at base, facing the viewer's forward axis; test in a viewer (three.js editor / model-viewer) and run the glTF Validator — `web-and-mobile-delivery.md` §4

## 4. LODs, baking and the hybrid pipeline

The standard game pipeline is hybrid: **high poly (sculpt or subd/boolean) → retopo/low poly → UVs → bake → LODs → collision → export check**.
- Generate LODs with `scripts/lod_collision.py` (Decimate Collapse chain, ratio corrected to hit ~50 % per level, optional symmetry; Planar for hard-surface) — it reports tris, surface deviation and silhouette overlap per LOD, and builds `UCX_` hulls. By hand for characters (LOD1 removes finger loops etc.). Even quad topology produces far better auto-LODs than ngon soup.
- Bake with a cage 1–3 % of size; match tangent space to engine; bake at 2× final resolution and downsample (`baking-maps.md` §1 and `baking-maps.md` §3, `scripts/bake_maps.py`).
- Keep the high poly and cutters in the file — refinement passes need them.
- LOD naming, FBX LOD groups, collision/socket conventions per engine: `game-engine-delivery.md` §4–5.

## 5. Reducing poly count without ruining a model

Priority order:
1. Remove hidden/interior geometry and unseen faces (bottoms, insides).
2. Reduce cylinder segments where the silhouette allows (8–12 for small bolts, 16–24 mid, 32+ hero).
3. Dissolve edge loops on flat areas (Limited Dissolve, Un-Subdivide, `Dissolve Edges` on parallel loops).
4. Replace geometric bevels/support loops with normal-map detail.
5. Replace small parts with instanced low versions or decals.
6. Decimate (Planar for hard surface at 1–5° for cleanup, up to 10° only when building LODs — `game-engine-delivery.md` §4; Collapse for organic) — last resort, after saving a version, and never on rig-ready meshes without checking joints.
Always compare silhouette before/after from 3 angles (`scripts/lod_collision.py` measures it).
