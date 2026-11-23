# 3D Printing from Blender

Read this before sending any Blender mesh to an FDM, resin (SLA/DLP) or SLS/MJF printer: unit and scale conventions, per-process minimums, fits and holes, the mesh checks in `scripts/export_print.py`, and export with re-import verification. **This file is the numeric authority for print tolerances across the skill — every other reference (jewelry, CAD/enclosures, hard-surface, vector text) defers to the numbers here.** Numbers are starting points: print a calibration/tolerance coupon on the actual machine and material before committing a fit. Casting-specific rules: `jewelry-and-casting.md`; parametric CAD and enclosures: `cad-and-enclosures.md`.

## Contents
1. Blender or CAD?
2. Units, scale and small-part tolerances
3. Process rules: FDM / resin (SLA/DLP) / SLS
4. Fits, holes, orientation, text
5. Mesh checks (`scripts/export_print.py`, 3D Print Toolbox)
6. Export and verification
7. Common failures

## 1. Blender or CAD?

| Job | Tool |
|---|---|
| Sculpted/organic figure, textured relief, jewelry with organic forms, props, cosplay | Blender (mesh) → STL/3MF |
| Ring band / simple setting where shape matters more than fit | Blender, typed dimensions (`hard-surface-modeling.md` §7) |
| Anything with mating fits, screw bosses, hinges, tolerances on drawings | Parametric CAD (build123d, CadQuery, FreeCAD, Fusion) |
| Client needs STEP/IGES, CNC, injection molding, drawings | CAD — Blender cannot write STEP or true NURBS solids |
| Dimension changes likely ("make it 2 mm wider") | CAD script; a mesh needs remodeling |
| CAD part needs rendering, decals, scene | CAD → STL/OBJ/glTF (chord tolerance) → Blender |

Tell the user early when the request is CAD-shaped, and offer a build123d script (`cad-and-enclosures.md` §1) rather than a mesh that only looks right.

## 2. Units, scale and small-part tolerances

- **Keep 1 BU = 1 m** (skill convention) and set *Scene → Units → Length = Millimeters* for typing and display; export with `global_scale=1000`. Alternative for pure-print files: `unit_settings.scale_length = 0.001` (1 BU = 1 mm) → export `global_scale=1`. Both verified to write identical files (US-7 ring: ID 17.300 mm either way). Never mix conventions inside one file.
- **Viewport**: at mm scale raise nothing, lower `clip_start` (default 0.01 m = 10 mm clips small parts when zoomed in) to 0.0001 m.
- **Distance thresholds are in BU, not mm**: Merge by Distance defaults to 0.0001 BU = **0.1 mm in a metre scene**. On a 0.3 mm prong with 24 segments (edge ≈ 0.04 mm) the default merge collapsed 48 verts to 14 (measured); 0.01 mm left it intact. Same trap: Weld modifier `merge_threshold` 0.001 BU = 1 mm, Boolean FAST `double_threshold`, Remesh voxel size. Set thresholds from the smallest feature (**≤ 1/10 of it**), never a fixed 0.0001 m default.
- **Chord error** of a faceted circle = r(1−cos(π/n)); a 17.3 mm bore at n = 128 deviates 0.003 mm — segments are rarely the tolerance problem; unapplied scale and wrong export scale are.
- **Apply scale** before booleans/solidify/bevel and before measuring. Negative scale flips normals on export in some tools — apply and recalc.
- Machine accuracy ranges `[unverified; machine-dependent]`: FDM ±0.1–0.3 mm, resin ±0.05–0.1 mm, SLS ±0.2–0.3 mm. Design fits with those, not with mesh precision.

## 3. Process rules: FDM / resin (SLA/DLP) / SLS

| Rule | FDM (0.4 mm nozzle) | Resin SLA/DLP | SLS / MJF (nylon) |
|---|---|---|---|
| Min wall | **≥ 1.2 mm (3 perimeters)** — the skill-wide rule; 0.8 mm (2 perimeters) is the absolute minimum; functional ≥ 1.6 | 0.5 supported / 1.0 unsupported | 0.8 (1.0–1.5 load-bearing) |
| Min embossed/engraved detail (width & depth) | 1.0 mm | 0.8 mm (jewelry: 0.3–0.5 deep, `jewelry-and-casting.md` §2) | 0.8 mm |
| Interlocking clearance (per side) | 0.3–0.5 mm general; 0.2–0.3 only on a tuned printer after printing a gauge (`cad_enclosure_template.py` defaults to 0.3) | 0.2–0.3 mm | 0.2–0.3 mm (+ powder escape) |
| Overhang without support | ≤ 45° from vertical | needs supports on down-facing areas; tilt parts 10–45° off the plate `[unverified]` | none (powder supports) |
| Bridging | ~5–10 mm clean, longer sags `[unverified]` | n/a | n/a |
| Hollow parts | infill instead | drain holes ≥ 2–3.5 mm, 2 of them `[unverified]` | escape holes ≥ 4–5 mm, 2 of them `[unverified]` |
| First-layer "elephant foot" | 0.3–0.5 mm × 45° chamfer on bed edges | (bottom of supports) | n/a |
| Hole spacing to edge | 1.5–2 × wall | same | same |

Sources: JLC3DP / Formlabs / Sinterit design guides (see `sources.md`). Wall thickness in this table is what `export_print.py --min-wall-mm` should be set to.

## 4. Fits, holes, orientation, text

- **Fit clearances (per side, FDM)** `[unverified; print a gauge]`: press 0.0–0.1 mm, snug/sliding 0.15–0.3 mm, free/rotating 0.3–0.5 mm. Resin/SLS: roughly half of those.
- **Holes**: small vertical FDM holes print undersize (polygon + ooze) — model +0.2–0.3 mm or drill/ream; horizontal holes: teardrop or flat-top to avoid sag. Heat-set inserts: use the insert vendor's hole diameter.
- **Orientation**: layers are weakest in Z tension — orient clips, tabs and hooks so bending strain runs along layers; put cosmetic faces away from supports; for resin tilt large flat faces so peel forces act on a line.
- **Text**: FDM embossed ≥ 1 mm stroke / 0.6–1 mm height, letters ≥ 5 mm tall `[unverified]`; engraved slightly deeper than embossed; bold sans fonts. Build text solids via `vector-and-text.md` §3 (curve → mesh → solidify → boolean).
- **Multi-part prints**: keep each printed piece one manifold shell; model clearance explicitly in the mesh, never "slicer will handle it".

## 5. Mesh checks (`scripts/export_print.py`, 3D Print Toolbox)

`scripts/export_print.py` (headless or live) checks the evaluated world-space meshes and reports mm (`--checks`, `--min-wall-mm`, `--min-clearance-mm`; `--parts` lists the mating parts for the clearance check):

| Check | Method | Clean ring / planted defect (measured) |
|---|---|---|
| manifold | non-manifold/boundary/flipped-winding edges, shells, zero faces, signed volume | ring 0 edges, 1 shell, +190 mm³; open cube 4 edges; flipped cube −125 mm³ |
| intersect | BVH self-overlap, pairs sharing a vertex ignored | two cubes in one mesh → 8 tri pairs |
| thickness | area-weighted inward rays (≥ 1 per triangle), back-face hits only | band 1.600 mm pass; 0.3 mm prong → 0.297 flagged; 1.0 mm prong 0.991 pass |
| clearance | surface samples → nearest on other part, BVH overlap, ray-parity containment | 0.05 mm gap flagged, 0.40 mm pass, 0.5 mm overlap interfering |
| units | BU→mm, negative/unapplied scale, Weld threshold | negative scale flagged |

**3D Print Toolbox** (extension `print3d_toolbox`, 1.4.x, Blender 4.2+; Mesh tab in the N-panel). Install only with the user's OK (online access): Preferences → Get Extensions → "3D Print Toolbox", or `bpy.ops.extensions.package_install(repo_index=<blender.org repo>, pkg_id="print3d_toolbox")` `[operator props verified; install not run]`. Operators (verified from source, and run headless on a 0.5 mm plate — checks work with an active object, no UI needed): `mesh.print3d_check_solid` (non-manifold + bad contiguous), `print3d_check_intersect`, `print3d_check_shells`, `print3d_check_degenerate`, `print3d_check_nonplanar`, `print3d_check_thick` (random-point inward rays, `scene.print3d_toolbox.thickness_min` default 1 mm), `print3d_check_sharp`, `print3d_check_overhang` (default 45°), `print3d_check_all`, `print3d_info_volume`, `print3d_info_area`, `print3d_clean_non_manifold`, `print3d_hollow` (OpenVDB), `print3d_bisect`, `print3d_scale_to_volume`, `print3d_scale_to_bounds`, `object.print3d_align_xy`, `export_scene.print3d_export` (STL/PLY/OBJ; its unit default is "m" — set `export_unit_scale='mm'`). Results live in the extension's report module, not a return value — for scripted gates prefer `export_print.py`, which returns numbers and locations. Repair of failing meshes: `mesh-repair.md` / `scripts/mesh_repair.py`.

## 6. Export and verification

| Format | Operator (5.x) | Notes |
|---|---|---|
| STL | `bpy.ops.wm.stl_export(filepath, export_selected_objects=True, global_scale=1000, apply_modifiers=True, ascii_format=False, forward_axis='Y', up_axis='Z')` | no units in file — slicers assume mm; `use_batch` = one file per object; `use_scene_unit` applies scale_length |
| OBJ | `bpy.ops.wm.obj_export(..., global_scale=1000, forward_axis='Y', up_axis='Z', export_materials=False)` | default axes are Y-up (−Z forward) — set Z-up for print |
| PLY | `bpy.ops.wm.ply_export(..., global_scale=1000, ascii_format=False)` | vertex colours for full-colour printers |
| 3MF | not built in; needs the separate "3MF Import/Export" extension (extensions.blender.org, 4.2+) `[operators unverified]` | carries units, colours, multiple objects |
| legacy | `export_mesh.stl` — gone in 5.x | |

Gate before sending: `blender -b part.blend --python scripts/export_print.py -- --objects PART_ --min-wall-mm 1.2 --formats stl,obj` → exports (`--out-dir`, `--per-object`, `--ascii`), re-imports every STL/OBJ and compares the bbox (US-7 ring: 20.500 × 20.500 × 2.000 mm, error 0.000 mm; bore measured from the file 17.300 mm). Also sanity-check volume (mm³ × density = grams: silver 10.4, 18k yellow ~15.5, platinum 21.4 g/cm³ `[unverified alloy values]`).

## 7. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Part arrives 1000× too small/large | metre scene exported with global_scale 1, or mm scene with 1000 | `export_print.py` sets scale from unit_settings and re-imports to prove the bbox (§6) |
| Prongs/fine wires vanish or turn spiky after cleanup | Merge by Distance / Weld default 0.1 mm (metre scene) | threshold ≤ 1/10 of the smallest feature (0.01 mm) (§2) |
| Small parts disappear when zoomed in | viewport `clip_start` at the 0.01 m default | lower to 0.0001 m (§2) |
| Slicer shows holes / "non-manifold" | open boundaries, zero-area faces, grouped shells | fix and boolean-union into one shell; `mesh-repair.md` |
| Walls missing in slice | features below nozzle/resolution | raise to process minimum (§3); check with `--min-wall-mm` |
| Mating parts fuse or won't assemble | zero clearance modeled, relying on slicer | model clearance per §4; run the clearance check between parts (§5) |
| Vertical holes too tight | FDM polygon + ooze undersize | model +0.2–0.3 mm or drill/ream (§4) |
| Normals inverted in the slicer | negative object scale on export | apply scale and recalc; `export_print.py` units check flags it (§2, §5) |
| Toolbox thickness says 0 faces yet part is thin | `thickness_min` left at 1 mm default in a mm-scaled scene, or open mesh | set the value in scene units; fix manifold first (§5) |
| 3MF export operator missing | 3MF is not built in | install the separate 3MF Import/Export extension, or ship STL (§6) |
