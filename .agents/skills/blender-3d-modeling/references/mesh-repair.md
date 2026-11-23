# Mesh Repair & Intake

Meshes you did not model — 3D scans, photogrammetry, AI image-to-3D output, CAD tessellations, downloaded game assets — arrive with wrong scale, floaters, holes, flipped or duplicated shells and absurd triangle counts. This file is the intake → triage → repair-or-rebuild → texture-transfer workflow. `scripts/mesh_repair.py` measures and repairs headlessly with thresholds relative to object size; `scripts/mesh_report.py` audits topology.

## Contents
1. Intake triage
2. Scale, orientation, ground, symmetry
3. Cleanup operations and thresholds
4. Remesh, decimate, QuadriFlow
5. Retopology decision
6. Texture transfer and delighting
7. AI-generated meshes
8. Photogrammetry and scans
9. Scripted pipeline (`mesh_repair.py`)
10. Common failures

## 1. Intake triage

Measure before touching anything: `BLENDER -b --python scripts/mesh_repair.py -- analyze --import in.ply` (or `--object NAME` in a .blend). It reports scale hints, weld/soup state, islands, holes, multi-face edges, duplicate faces, normal consistency, inner shells and per-axis symmetry.

| Source | Typical tris | Signature defects | Usually |
|---|---|---|---|
| Structured-light / LiDAR scan | 1–50 M | noise, holes at occlusions, floaters, open base, double walls from misaligned passes | repair → decimate/retopo → bake |
| Photogrammetry | 2–100 M | turntable/floor captured, baked lighting in the atlas, fused thin parts, blobby undersides | work on a proxy; rebuild topology; bake |
| AI image-to-3D | 50 k–2 M | triangle soup (split verts), hallucinated back/hidden sides, baked lighting, fake symmetry, internal shells | weld + repair for blockout; often rebuild |
| CAD tessellation (STEP→STL/OBJ) | 10 k–5 M | slivers, unwelded patches per face, huge ngon fans, mm units | weld; remesh or remodel for subdiv/deform |
| Downloaded game asset | 1 k–200 k | wrong units/axis, separate parts by design, duplicate LODs, flipped mirrors (negative scale) | normalize, don't "repair" intentional splits |

**Repair or rebuild?**

| Measurement | Repair | Rebuild (retopo / remodel) |
|---|---|---|
| Largest island share of total area | ≥ 90 % | many comparable islands that should be one surface |
| Holes | few, ≤ ~2 % of surface, on hidden/flat areas | holes on silhouette-defining curves |
| Symmetry score of a symmetric object | ≥ 0.9 within 0.2 % of size | < 0.8 (warped, hallucinated) |
| Downstream use | static render / prop / print | deformation, subdivision, UV-critical hero asset |
| Deviation after repair (orig→new max) | ≤ 0.5 % of diagonal | larger, or features lost |
| Topology | irrelevant (will be baked) | needs edge loops → quad retopo (`topology.md` §8) |

## 2. Scale, orientation, ground, symmetry

- **Units**: longest side > 50 m for a hand-held object = cm or mm data read as metres (×0.01 / ×0.001); < 1 cm for a large object = the reverse. Fix scale from one **known dimension** (a door is ~2.0 m, a mug ~10 cm; use `references/` measurements if you have them) — `repair --target-longest 0.5` or `--scale 0.01`. Apply rotation/scale before anything else (negative scale flips winding; `mesh_repair.py` applies it and flips normals back).
- **Orientation**: glTF/most AI tools are Y-up, Blender is Z-up; importers usually convert, raw PLY/OBJ may not. `analyze` lists the largest flat extreme face regions (`flat_extremes`); a flat base on `-Y` means rotate +90° about X.
- **Ground**: `--ground` moves the bbox bottom-centre to the world origin (origin at base, `BOTTOM_CENTER` pivot).
- **Symmetry detection**: `analyze` mirrors 2000 area-weighted surface samples across the bbox centre, area centroid and object origin per axis and reports the fraction within 0.2 % of the diagonal. Tested: sphere with a dent on +X scored X 0.925 vs Y/Z 1.0; after symmetrize X 1.0.
- **Symmetrize**: `bmesh.ops.symmetrize(direction='-X')` / `mesh.symmetrize(direction='NEGATIVE_X')` keeps the −X half and mirrors it to +X about the object origin (script: about bbox centre by default). Choose the half with fewer holes / better detail. Weld distance on the plane ≈ 1e-3 × diagonal for noisy scans. Symmetrize **before** decimation and enable Decimate `use_symmetry`.

## 3. Cleanup operations and thresholds

Order matters: weld → degenerate → loose/duplicates → islands → non-manifold → holes → normals → inner shells.

| Step | Operator (5.2, verified) | Threshold |
|---|---|---|
| Merge by distance | `bmesh.ops.remove_doubles(dist=)` / `mesh.remove_doubles(threshold=, use_sharp_edge_from_normals=)` | **diagonal × 1e-5** (absolute override only when you know the units) |
| Dissolve degenerate | `bmesh.ops.dissolve_degenerate(dist=)` / `mesh.dissolve_degenerate(threshold=)` | same as merge |
| Loose verts/edges | `mesh.delete_loose(use_verts, use_edges, use_faces)` | — |
| Floaters / small islands | `mesh.select_linked` + delete, or script `--min-island-pct` | area < 1 % of the largest island (0 for multi-part assets) |
| Duplicate faces / coincident shells | weld, then delete faces with identical corner sets (script) | — |
| Multi-face (3+) edges | `mesh.select_non_manifold(use_multi_face=True)` → delete faces → fill | — |
| Holes | `mesh.fill_holes(sides=N)` / `bmesh.ops.holes_fill(sides=N)` (0 = all), then triangulate caps (Beauty) | N ≈ 64 edges for automatic; larger holes by hand |
| Two-loop gaps / tubes | `mesh.bridge_edge_loops(number_cuts, interpolation='SURFACE')` | — |
| Rectangular holes | `mesh.fill_grid(span, offset)` (needs even loop) | — |
| Normals | `bmesh.ops.recalc_face_normals` / `mesh.normals_make_consistent(inside=False)` — only works after welding | — |
| Inner / double-wall shells | `mesh.select_interior_faces` (shared-edge interiors only) or script ray-parity test | island inside a larger closed island |

**Why relative thresholds**: the common "merge at 0.0001 m" advice destroys small parts. Tested on a 20 × 20 × 2 mm plate with 0.05 mm pitch and 0.05 mm ridges (321,602 verts): relative tolerance (0.28 µm) removed 0 verts, ridges intact, deviation 5.5e-5 mm; absolute 0.1 mm merged 293,153 verts, left non-manifold and inconsistent normals, deviation 0.156 mm. On a 100 m terrain scan the same absolute value would be far too small to weld split-vertex exports.

Split normals caution: hard-surface assets exported with split vertices for sharp edges look faceted-smooth after welding — re-enable sharp edges from angle (Smooth by Angle modifier) or weld with `use_sharp_edge_from_normals=True`.

## 4. Remesh, decimate, QuadriFlow

| Tool | Use for | Settings |
|---|---|---|
| Voxel remesh (Remesh modifier `mode='VOXEL'`, `voxel_size`; or `object.voxel_remesh` using `mesh.remesh_voxel_size`) | unify intersecting shells, close bowtie verts, make watertight for print/sculpt | voxel = diagonal × 0.002–0.005; vertices ≈ 1.35 × area / voxel² (measured, `sculpting.md` §1; ≈4× per halving); parts thinner than ~2 voxels vanish; UVs/attributes lost (`use_remesh_preserve_attributes` on the operator interpolates some) |
| Decimate `COLLAPSE` | tri budget for static props, LOD, proxies | `ratio = budget / tris`, `use_collapse_triangulate=True`, `use_symmetry` + `symmetry_axis`; re-run once if > 1 % over |
| Decimate `DISSOLVE` (planar) | CAD / hard-surface flats | `angle_limit` 1–5° for cleanup (up to 10° only when building LODs, `game-engine-delivery.md` §4), `delimit` {'NORMAL','SHARP','UV'} |
| Decimate `UNSUBDIV` | meshes that were subdivided grids | `iterations` 1–3 |
| QuadriFlow (`object.quadriflow_remesh`) | quick even quads for sculpt base / blockout retopo | argument list: `topology.md` §8. Prerequisites: a single welded **manifold** surface — run weld, fill holes, remove inner shells (or voxel remesh) first; it refuses non-manifold input [error text unverified] |

Budgets: `poly-budgets-and-targets.md`. For scans, decimate to 2–5× the final budget, bake, then LOD from that.

## 5. Retopology decision

| Target | Pipeline |
|---|---|
| Static prop, environment piece, archviz dressing, print | repair → (voxel remesh if multi-shell) → Decimate COLLAPSE to budget → triangulate → UV → bake color/normal/AO from the original (§6) |
| Background / mobile | as above at a lower budget; consider planar decimate on flat regions first |
| Deforming (character, cloth, hose), subdivision surfaces, hero close-ups | quad retopology over the repaired mesh (`topology.md` §8; sculpt cleanup in `sculpting.md` §8), then bake |
| Mechanical CAD part needing edits | remodel from measurements (`hard-surface-modeling.md`); use the tessellation only as a snap/reference target |

## 6. Texture transfer and delighting

New topology needs new UVs (`references/uv-unwrapping.md`), then bake the old surface onto it:

1. Keep the original (high) textured mesh; select it, then the new low mesh as active.
2. Cycles bake, `use_selected_to_active=True`; ray reach via `cage_extrusion` ≈ 1–3 % of object size plus `max_ray_distance` ≈ 2× that (or a cage object `use_cage=True`). DIFFUSE with pass_filter {'COLOR'} for albedo, NORMAL (tangent) for detail, `target='VERTEX_COLORS'` if the source carries vertex colors and you want them on the new mesh. `scripts/bake_maps.py --source High --cage-extrusion 0.02` wraps this.
3. Margin: `margin_type='ADJACENT_FACES'` continues texels across UV seams from the neighbouring face (no bleeding of unrelated islands); `EXTEND` just smears edge pixels outward. Use 8–16 px at 2K. Never blur a baked atlas as a whole — it averages across island borders; dilate/blur per island only.

**Delighting a scan / AI atlas** (`scripts/pbr_from_image.py albedo.png --delight-atlas --ao ao.png --uv-object SCAN --out maps/`, run on the .blend holding the mesh): albedo / max(AO^k, floor) → optional divide by a baked light proxy → low-frequency luminance flattening → gutter dilation per island (island texels untouched). Flattening in the **mesh** domain (default with `--uv-object`) splats texel luminance to vertices, low-passes on the vertex graph and interpolates back, so both sides of a UV seam get the same correction; the **uv** domain (`--island-mask` only) blurs inside each island separately — no bleeding, but steps at seams. Never blur the atlas as a whole (the old `--delight` is for tileable swatches).

Measured on a synthetic textured sphere on a floor under a sun (512², 21 Smart-UV islands, 1,344 seam sample pairs). Error = mean |g·Y − Y_gt| / mean Y_gt after best global gain; variance of log(Y/Y_gt) = residual lighting; seam step = mean |Δ log(Y/Y_gt)| across UV seams:

| Variant | Error | Var log | Seam step |
|---|---|---|---|
| lit input | 0.68 | 0.77 | 0.044 |
| whole-atlas blur divide (old `--delight`) | 0.30 | 0.43 | 0.36 |
| AO only, k 0.7 | 0.50 | 0.53 | 0.054 |
| AO + uv-island flatten σ 0.04 | 0.099 | 0.18 | 0.25 |
| AO + mesh flatten σ 0.04 (`--flatten 0.04`) | **0.096** | 0.20 | **0.042** |
| AO + mesh flatten σ 0.08 | 0.16 | 0.28 | 0.047 |
| baked DIFFUSE DIRECT+INDIRECT proxy, `--ao-k 0` | **0.011** | 0.10 | **0.008** |
| same proxy + AO k 0.7 (occlusion counted twice) | 0.52 | 0.32 | 0.022 |

- AO alone removes little: most baked light is directional (N·L), which only flattening or a light proxy removes.
- A proxy baked from the same geometry and a matched light (DIFFUSE with DIRECT+INDIRECT, no COLOR) is near exact, but it already contains occlusion → `--ao-k 0`. Scans rarely have a known light: use AO + mesh flatten.
- Flattening also erases real albedo variation larger than σ (texture sigma = `--flatten` × size): keep σ small (0.03–0.05); cast shadows and specular highlights still need painting.
- Roughness from albedo (inverted luminance) is a guess: dark ≠ rough (wet stone, lacquer); prefer a flat value per material plus hand-painted variation.

## 7. AI-generated meshes

- **Triangle soup**: every face its own island. `analyze` flags `soup_suspect` (tested: 5,120 raw islands, 12,798 coincident verts on a split 5,120-tri sphere → repair welds to 1 closed manifold island, deviation 3e-8 m).
- **Hallucinated hidden sides**: confidence is highest on the side facing the input image. Render the model from each reference view and compare silhouettes (`scripts/silhouette_compare.py`, `review-and-comparison.md`); rebuild low-confidence regions (back, underside, between limbs) rather than trusting them. If the object is symmetric, symmetrize from the better half.
- **Baked lighting**: generated textures bake the image's lighting; delight (§6) or re-texture.
- **Internal shells / intersecting parts**: voxel remesh to unify when a watertight mesh is needed.
- **Provenance**: record the generator, version, date, prompt/input image and license in `references/NOTES.md`; some services restrict commercial use or require attribution; inputs that are other people's images carry their rights into the output.

## 8. Photogrammetry and scans

- **Huge counts**: never edit the 50 M original interactively. Duplicate, Decimate COLLAPSE to ~1–2 M as a working proxy, run analysis/cleanup decisions on it, and bake from the untouched original at the end.
- **Floor / turntable**: bisect below the base plane (`bmesh.ops.bisect_plane` with `clear_inner=True`) or delete the largest flat island at the minimum Z; then remove what became floaters.
- **Open base**: after the cut the base is one big boundary loop — fill it (`--fill-max-edges 0` fills all), triangulate, and optionally planar-flatten it; for print, a flat base helps adhesion.
- **Double walls** from misaligned passes: inner-shell removal or voxel remesh.
- **Noise**: a light Smooth (Corrective Smooth / sculpt Smooth at low strength) before decimation reduces wasted triangles; don't smooth before measuring deviation.

## 9. Scripted pipeline (`mesh_repair.py`)

```
BLENDER -b --python scripts/mesh_repair.py -- repair --import scan.ply --target-longest 0.5 --ground \
    --fill-max-edges 0 --decimate-tris 250000 --export scan_fixed.glb --save scan_fixed.blend
```
Steps logged with seconds: transform/scale/ground → merge (diag × 1e-5) → degenerate → duplicate faces, small islands, loose → cut multi-face edges → fill holes → recalc normals → inner shells → optional voxel (`--voxel-rel`) → optional symmetrize → decimate (`collapse|planar|unsubdiv`) → optional triangulate. Output: `before`/`after` analyses, `deviation` (orig→new excluding deliberately removed floaters/shells; new→original-or-fill-cap, so filled holes don't read as error), `gates` (closed_manifold, normals_consistent, no_small_islands, within_budget, deviation_ok ≤ `--max-dev-rel` 0.005) and `pass`. A deliberate shape change (symmetrize removing a dent) correctly fails `deviation_ok` — read the number, then accept it knowingly.

Tested on a synthetic bad scan (1.32 M tris, built ×100 as cm-read-as-m, noise, 11 deleted patches, 12,415 flipped faces, 4,448 duplicate faces, 70 floaters, a 20 k-tri inner double wall): `analyze` (7 s) flagged all of these, including the units and the inner shell (21/21 parity votes). `repair --target-longest 0.5 --ground --fill-max-edges 0 --decimate-tris 250000` ran in 27 s → 1 closed manifold island, consistent normals, 249,998 tris, orig→new max 0.025 % of the diagonal. With `--voxel-rel 0.002 --decimate-tris 100000`: 24 s, closed, deviation max 0.066 %. Notes: `remove_doubles` itself deleted the coincident duplicate faces. One hole whose boundary touched itself at a vertex was skipped by `holes_fill`, so the script falls back to `bmesh.ops.triangle_fill` per remaining loop.

## 10. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Recalc Normals leaves random dark faces | mesh not welded (triangle soup), so faces have no neighbours | merge by distance first, then recalc |
| Small part turns to mush after cleanup | absolute merge distance (0.1 mm) larger than feature spacing | relative tolerance, diagonal × 1e-5 |
| Welding a large scan does nothing | absolute tolerance too small for units read ×100 | fix scale first; relative tolerance |
| Hard-surface asset looks blobby after weld | split-normal edges merged | Smooth by Angle / `use_sharp_edge_from_normals` |
| Voxel remesh erased thin parts (straps, ears, antennae) | parts < 2 voxels thick | smaller voxel, or remesh parts separately and join |
| Voxel remesh made a double-walled hollow | open mesh (holes) remeshed | fill holes before remeshing |
| QuadriFlow errors or produces garbage | non-manifold / multiple shells / holes | weld, fill, remove inner shells or voxel remesh first |
| Legit buttons/bolts deleted | `min_island_pct` removed intentional small parts | `--min-island-pct 0` for multi-part assets |
| Eyes/mechanism inside removed | inner-shell removal | `--keep-inner` |
| Filled hole reads as a flat patch | holes_fill caps are flat | sculpt/Smooth the cap, or voxel remesh + smooth |
| Filling a gouge or crack in a rough wall (by script) folds faces, leaves a dark lip, or leaves a patch standing proud | Pushing its vertices out along the wall normal folds an undercut gouge. Filling only the deep vertices leaves the lip's side-on faces and a slightly sunken patch, which reads dark under a grazing light. A patch on a fitted surface stands proud wherever the wall recedes | Delete every face in a box around the gouge. Re-triangulate the hole in the wall's own plane (u, z): `mathutils.geometry.delaunay_2d_cdt` with the rim loop as the constraint plus a ~0.1 m interior grid. Give the interior depths a harmonic interpolation of the rim's depths. No vertex moves along the wall, so nothing folds. Check the rim loop is simple in (u, z) first, and count edges over 120° before and after |
| Bake shows seams / wrong island colours | blurred atlas or EXTEND margin bleeding | ADJACENT_FACES margin, per-island dilation |
| Baked result has black spots / projection misses | cage/ray distance too small or too big | cage_extrusion 1–3 % of size, max_ray_distance ≈ 2× |
| AI model's back looks wrong from other angles | generator hallucinated unseen sides | compare to other reference views; rebuild or symmetrize from the good half |
| Decimate breaks symmetry | collapse order asymmetric | symmetrize first, Decimate `use_symmetry` |
