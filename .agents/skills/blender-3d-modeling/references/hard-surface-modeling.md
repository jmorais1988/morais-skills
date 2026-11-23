# Hard Surface Modeling (tools, weapons, vehicles, furniture, buildings, machines)

Man-made objects: planar and cylindrical faces, controlled fillets, repeated parts, panel gaps, fasteners. Read this for the shared workflow (blockout, booleans, bevels, subdivision cages, modifier stacks, details, precision, cleanup); per-category construction order, starting dimensions and material recipes for vehicles, vehicle interiors, weapons, furniture, architecture and machines are in `hard-surface-categories.md`. Two dominant workflows, choose per part:

| Workflow | Best for | Topology outcome |
|---|---|---|
| **Boolean + Bevel + Weighted Normals** (non-destructive, no subdivision) | Angular/industrial forms, many cuts, fast iteration, game high-poly bake sources | Ngons on flat faces; shading fixed by bevels/normals; needs cleanup or triangulation for export |
| **Subdivision cage with support loops** | Smooth curved man-made forms (car body, helmet, grips, consumer electronics), film/AAA high-poly | All-quad, clean, slower; needs planning for late changes |

Blockout is shared: primitives at real scale, proportions from references, then details. See `topology.md` for the cleanup rules.

## Contents
1. Blockout and structure
2. Boolean workflow
3. Bevel and shading control
4. Subdivision workflow with support loops
5. Modifier stack recipes
6. Details
7. Precision / CAD-like modeling
8. Cleanup and export for hard surface
9. Common failures

## 1. Blockout and structure

- One object per manufactured part (receiver, barrel, magazine…). Real objects are assemblies; modeling them as separate objects gives clean booleans, easy materials, movable parts, and simple LOD/collision later. Parent parts to an Empty or the main body.
- Real dimensions from `references/NOTES.md`. Set scene units metric, `unit_settings.scale_length = 1`, and type dimensions directly (`obj.dimensions`, then apply scale).
- Establish the **primary silhouette** in front/side/top ortho over reference empties before any bevel or boolean.
- Keep the mesh **as simple as possible** at this stage: a cylinder with 32 sides is a blockout; 128 sides is a decision for later.
- Origins at logical pivots (hinge axis, wheel center, ground contact).

## 2. Boolean workflow

- Cutters live in a hidden `CUTTERS` collection (`display_type='WIRE'`, hide_render). Keep them; never apply until export. `CUTTERS` is the standard name for hand-built cutters; Hard Ops creates and reads its own `Cutters` collection (`hard-ops.md`) — leave that one to the add-on.
- **Solver** (`BooleanModifier.solver`, verified 5.2: `'FLOAT'`, `'EXACT'` (the modifier's default), `'MANIFOLD'`; `MANIFOLD` is 4.5+, older builds fall back to `EXACT`): `solver='MANIFOLD'` is the fast choice for clean, closed (manifold) inputs; `'EXACT'` for dirty inputs — it handles coplanar faces and self-intersecting geometry; `'FLOAT'` (named `'FAST'` before 5.0, which 5.x rejects) for speed on simple convex cutters without overlapping geometry. Measured on a parametric ring (`scripts/ring_builder.py`, 6-prong head): EXACT left 20 zero-area faces, MANIFOLD left none. Use `use_self` for cutters intersecting themselves; `use_hole_tolerant` when the cutter is open.
- Avoid **coplanar faces** between cutter and target (shift cutter by 0.1 mm); avoid cutting exactly on existing edges → slivers.
- Order in stack (hand-built): Mirror → Booleans → Bevel → Weighted Normal → (Triangulate at export). Booleans after Bevel produce unbeveled cut edges. Hard Ops sorts Mirror/Array *after* Booleans and Bevel instead (`hard-ops.md` §3).
- Unions of many parts: prefer keeping them separate objects; union only when the design truly fuses them (cast part).
- After booleans on **subdivided** meshes expect artifacts; either accept ngons (no subd) or convert the boolean result into quad topology by hand.
- Chain complexity: many overlapping booleans get slow and unstable. Apply intermediate results deliberately (save `_v00N` first) and clean with Merge by Distance (size-relative threshold, §8) + Limited Dissolve (1–5° for cleanup, keep boundaries; up to 10° only when building LODs, `game-engine-delivery.md` §4).
- Free helper: **Bool Tool** extension (Brush/Auto booleans, Carver). Paid: Hard Ops / Boxcutter (see addons-and-scripting.md; if Hard Ops is installed, `hard-ops.md` has code-safe usage and compatible recipes).

## 3. Bevel and shading control

Real edges are never perfectly sharp; bevels catch highlights and sell the material.

- **Bevel modifier**: `limit_method='ANGLE'` (30°) for a quick pass; `'WEIGHT'` with per-edge bevel weights for control; `segments` 2–3 for game high-poly, 1 for low-poly; `profile` 0.5 (the modifier default, round) to 0.7, 1.0 for support-loop style. Enable `harden_normals` and `use_clamp_overlap`. Bevel weights are the float edge attribute **`bevel_weight_edge`** (4.0+; `MeshEdge.bevel_weight` no longer exists) — the modifier's `edge_weight` property names it:
  ```python
  me = obj.data
  w = me.attributes.get("bevel_weight_edge") or me.attributes.new("bevel_weight_edge", 'FLOAT', 'EDGE')
  w.data[edge_index].value = 1.0
  # bmesh: lay = bm.edges.layers.float.get("bevel_weight_edge") or bm.edges.layers.float.new("bevel_weight_edge"); e[lay] = 1.0
  mod = obj.modifiers.new("Bevel", 'BEVEL'); mod.limit_method = 'WEIGHT'; mod.width = 0.002
  ```
  Verified 5.2: weight on one cube edge → 7 evaluated faces (one bevel strip), on all edges → 26. `harden_normals` no longer depends on Auto Smooth (removed in 4.1): on a *flat-shaded* cube it writes custom normals — flat faces stay exactly flat, bevel faces shade smoothly (same corner normals as on a smooth-shaded cube).
- **Bevel width relative to object**: a 1 m crate ~5–10 mm; a rifle receiver ~1–2 mm; a car body panel edge ~2–3 mm; consistency across comparable features matters more than exact numbers. Over-beveling softens the silhouette and reads "toy-like".
- **Bevel width vs panel thickness**: on sheet-like parts (panels, fenders, hoods, brackets) keep the width ≤ ~40 % of the thickness. Wider bevels either fold through the panel (clamp overlap off → self-intersecting faces and a ridge standing proud of the surface) or collapse into zero-area faces (clamp on) — each setting hides the problem from a different check, so test the evaluated mesh for both (BVH self-overlap of non-adjacent faces, and faces with ~0 area). Verified on synthetic plates with a 0.02 m bevel: width/thickness 2.5 or 1.0 → 16–24 self-intersecting face pairs (clamp off) or 12 zero-area faces (clamp on); 0.4 → clean with either setting. Add-on bevel tools with absolute defaults hit this on every thin part (`hard-ops.md` §7).
- **Weighted Normal modifier** after Bevel: `mode='FACE_AREA'`, `keep_sharp=True` → flat faces stay flat, bevels blend. Requires smooth shading: `bpy.ops.object.shade_smooth()` + Smooth by Angle modifier (Blender 4.1+) or auto smooth (older).
- **Shading artifacts on flat faces** = non-planar ngon or averaged normals. Fix order: check planarity → recalc normals → Weighted Normal → add a bevel on the offending edge → as a last resort, add a support edge.
- Custom normals / data transfer: transfer normals from a smooth low-poly proxy onto a detailed mesh to hide seams (Data Transfer modifier, Face Corner Data → Custom Normals).
- For **low-poly game meshes**, replace geometric bevels with a normal map baked from the beveled high-poly (`references/poly-budgets-and-targets.md`).

## 4. Subdivision workflow with support loops

- Model a cage that is all quads; every edge that must stay sharp gets **two support edges** close to it (Bevel tool with 2 segments, profile 1.0, or Loop Cut + slide). Support loop distance controls the fillet radius after subdivision.
- Keep loops **continuous** around the form; when two features' loops collide, resolve with E/N poles on a flat area.
- Cylindrical holes/ bosses: match the cylinder's segment count to the surrounding grid (e.g. 8-sided hole in a 3×3 face grid via insets).
- Use `edge crease` sparingly for uniformly sharp corners; it's fine on boxy parts, poor on curved intersections.
- Subdivision levels: 2 viewport / 3–4 render; bake source for games at 2–3.
- Check for **pinching**: MatCap (reflective) or a zebra-stripe HDRI shows every ripple. Fix by evening out loop spacing, not by adding more subdivision.

## 5. Modifier stack recipes

- **Panel/plate with holes** (game high-poly): Mirror → Boolean(cutters) → Bevel(angle 30°, 3 seg, harden) → Weighted Normal.
- **Curved smooth housing**: Mirror → Subdivision(2) with support loops → (optional) Shrinkwrap to a clean blockout for perfect curvature → Bevel(small) for real-edge highlight.
- **Thin sheet metal / walls**: model a surface → Solidify (even thickness, rim) → Bevel.
- **Repeats, sweeps, lathes, lattices, bends** (radial bolt circles, treads, chains, threads, pipes and cables, Wireframe grilles, Cast/Lattice/Simple Deform tapers on grips and aero surfaces): pick the construction from `modifiers-and-curves.md` §1.
- **Symmetric asymmetry**: Mirror with `use_bisect_axis` (per-axis booleans, e.g. `(True, False, False)`) for half-modeled parts; disable Mirror per part when the real object isn't symmetric (charging handle, exhaust).

Apply order matters: deformers (Curve, SimpleDeform, Lattice) are usually **last**, after Bevel/Boolean, so cuts deform with the shape. These recipes are hand-built stacks with Mirror first; Hard Ops workflows place Mirror after Booleans and Bevel so cuts repeat in every mirrored copy (`hard-ops.md` §3) — keep one order per object.

Full object → construction table (belts, tracks, chains, cables, springs, lathe parts, railings, tire treads) with a tested belt-along-spline recipe: `modifiers-and-curves.md`. Category recipes (car-body loft, interior split lines and materials, weapon modules, furniture, walls/stairs/façades): `hard-surface-categories.md`.

## 6. Details

Work from the detail inventory in `references/NOTES.md`. For every mark decide **geometry** (it changes the silhouette or catches a hard highlight line under grazing light: bevels, fasteners, grooves, holes, panel gaps), **normal/texture** (visible but no silhouette change: fine engraving, small screws on a background prop, stitches, decals, wear), or **skip at this LOD**. Real edges catch light as a bright line — if the reference shows a crisp highlight along an edge, it must be a real bevel, not a normal map. Over-even spacing and identical repeats look CG; vary within the reference's bounds.

**Cross-section check**: a knife with constant thickness, a grip with no palm swell, a fuselage with no taper all pass a side-view comparison and still read as cardboard. Trace the profile *and* the cross-section from the reference (plan view, end-on view), and confirm the model has real variation along its depth axis before detailing.

- **Fasteners**: bolt/screw heads as separate small objects (8–12 side cylinders + bevel) instanced (Alt+D / collection instances) — never boolean-unioned into the body in the high-poly unless baking requires a single object. For games: normal-map decals or a few polys each.
- **Panel lines/gaps**: boolean with a thin slab (0.5–2 mm for vehicles) beveled to catch AO; or inset-extrude negative on subd cages.
- **Greebles/mechanical detail**: only where references show them; avoid random greeble spam — it destroys believability.
- **Text/labels**: Text object → convert to mesh → remesh or boolean for large embossed text; decals/normal maps for small. Full text-object and SVG-logo workflow: `vector-and-text.md` §2–3.
- **Wear**: edge damage via Bevel + Displace noise on high-poly, or handle in texturing (edge masks from curvature bake).

## 7. Precision / CAD-like modeling

Blender is not a CAD package, but for print/engineering accuracy:
- Type exact values (N-panel, or set `obj.dimensions` and apply), use snapping (increment/vertex/edge), Measure tool, and `Edge Length` overlays.
- Cylinders: choose segment counts so chord error is below tolerance: chord deviation = r(1−cos(π/n)); for a 20 mm radius and 0.05 mm tolerance → n ≥ 45 (use 48/64).
- Keep everything **manifold** and single-shell for printing; union parts with EXACT booleans, run `3D Print Toolbox` checks (non-manifold, intersecting faces, thin walls, overhangs).
- Wall thickness per process and clearance for mating parts — tolerances: `3d-printing.md`.
- Export STL in mm: with 1 BU = 1 m use `bpy.ops.wm.stl_export(filepath=..., global_scale=1000)` (verified 5.2: a 2 m cube writes 2000). `use_scene_unit=True` multiplies by `unit_settings.scale_length`, i.e. it writes *metres* — don't combine it with `global_scale`. There is no built-in 3MF exporter: install the *3MF Import/Export* extension (extensions.blender.org). Tolerances: `3d-printing.md` §2–3; mesh checks: `3d-printing.md` §5; export helpers: `3d-printing.md` §6.
- If true parametric CAD is required (fillets driven by dimensions, STEP output), tell the user Blender is the wrong tool (CadQuery/Build123d via Python, FreeCAD, Fusion 360) and offer a CadQuery script instead.

## 8. Cleanup and export for hard surface

1. Save version. Apply Mirror/Array/Boolean (keep `_source` copies), keep Bevel/Weighted Normal live until the final bake/export.
2. Merge by Distance with a **size-relative** threshold (bbox diagonal × 1e-5, see `mesh-repair.md` §3) — never a fixed 0.0001 m on small parts, where it welds real detail (a 0.1 mm chamfer on a screw head is 0.0001 m). Then Limited Dissolve (1–5° for cleanup — up to 10° only when building LODs, `game-engine-delivery.md` §4 — delimit by normal/material/seam/sharp) on boolean ngon soup, then Triangulate (Beauty) at export if the engine needs it.
3. Recalculate normals; verify Face Orientation overlay all blue.
4. Set sharp edges / smooth by angle so the engine's smoothing groups match.
5. `scripts/mesh_report.py`; fix; then UVs (hard edges ≈ UV seams for clean bakes; unwrap methods and texel density: `uv-unwrapping.md`), then export per target checklist (engines: `game-engine-delivery.md` §2; web glTF: `web-and-mobile-delivery.md` §1; print: `3d-printing.md` §6).

## 9. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Wrong cut sizes and bevel widths | Booleans and bevels on unapplied or negative scale | Apply scale (positive) before Boolean/Bevel (§1) |
| Cut edges razor-sharp while the rest is beveled | Bevel after Boolean missing (Boolean placed after Bevel) | Mirror → Boolean → Bevel → Weighted Normal (§2) |
| Double poly budget with no visual gain | Bevel segments too many on low-poly | 1 segment low-poly, 2–3 game high-poly; bake bevels to normals (§3) |
| Rivet and tank hull look the same | Uniform bevel width on very different-size features (same 5 mm on both) | Width per feature size; consistency only across comparable features (§3) |
| Ridge standing proud, or zero-area faces, on thin panels | Bevel width > ~40 % of panel thickness | Width ≤ 40 % of thickness; test BVH self-overlap and ~0-area faces (§3) |
| Zero-area faces after a clean boolean | EXACT solver on clean closed inputs (20 on the ring test) | `solver='MANIFOLD'` for manifold inputs (§2) |
| Z-fighting, dark patches inside unions | Coplanar faces / interior faces left inside unions | Shift cutter 0.1 mm; delete interior faces; keep parts separate (§2) |
| Hero prop with 300 identical unique bolts | Fasteners duplicated instead of instanced | Alt+D / collection instances (§6) |
| Engraved text in geometry on a game asset | Small labels modelled instead of textured | Decals/normal maps for small text; geometry only for large embossing (§6) |
| Weighted Normals/bevel widths make no sense in engine | Forgot real scale | Metric units, `scale_length = 1`, real dimensions before detailing (§1) |
| Small part loses chamfers after cleanup | Fixed 0.0001 m Merge by Distance | Size-relative threshold, `mesh-repair.md` §3 (§8) |
| Struts or braces stop short of the joint they should meet (ends hanging next to a ball joint, fitting or collar) | Endpoint computed as an offset in free space ("joint + 0.2 m") instead of from the part it attaches to | End every member inside the solid it attaches to (node fitting, collar, ball, plate). On tripod legs the two secondary struts meet the primary at a collar and the primary ends in the ball joint. Prove it with the `auditing-3d-geometry` audit at part level (`quality-gates.md` §3) |
| A band or ring around a cylinder/sphere reads as a floating hoop with a dark slit | Open cylinder at `r + δ` used as the band | Solid ring: inner radius inside the host (`r − δ`) plus top, outer and bottom faces. An open hoop at r + 18 mm audits as an 18 mm GAP |
| Ribs or stiffeners on a curved surface touch it only at their ends | One straight segment between two surface points | Sample the surface profile and chain short segments seated ~1 cm into it |
| Panel or plate mounted on a tube frame floats a few mm | Offset measured from the tube centreline, forgetting the tube radius | Offset less than the tube radius so the back face sits inside the tube |
| Rocks or chunky parts read faceted although they were modelled with rounded edges | A narrow edge rounding (a few % of the size) is erased by collapse-decimating to a low budget, and a low sharp-angle threshold (~40°) hard-shades what survives | Round wider (~7–9 % of the radius), give the decimation enough budget to keep 1–2 rows across the rounding, raise the sharp threshold (~70°) so the rounding shades smooth; inspect under a low grazing light |
| Bevel strips render with the wrong material, or a later split-by-material files them under another object | `bmesh.ops.bevel` creates new faces that keep slot 0 instead of the beveled part's slot | Assign `material_index` on `bevel(...)["faces"]` right after the call; split by material only after checking every slot's faces form the expected parts |
