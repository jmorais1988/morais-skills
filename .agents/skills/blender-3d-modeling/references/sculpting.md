# Sculpting in Blender

Sculpting is for shape-finding and organic detail. Choose the geometry strategy first — it determines what's possible later. API facts below were verified on Blender 5.2 (brush assets since 4.3; stroke `pen_flip` moved from stroke elements to an operator argument in 4.4); version boundaries are stated where they matter.

## Contents
1. Geometry strategy
2. Stage workflow
3. Brush guide
4. Masks, face sets, symmetry, filters
5. Hard-surface sculpting
6. Sculpting from code (MCP / bpy bridge)
7. Performance
8. From sculpt to production mesh
9. Common failures

## 1. Geometry strategy

| Method | What it does | Use for | Avoid for |
|---|---|---|---|
| **Voxel Remesh** (`Ctrl+R`; `bpy.ops.object.voxel_remesh()` with `mesh.remesh_voxel_size`) | Rebuilds the whole mesh as uniform quads by volume; merges overlapping parts into one shell | Blockout and primary/secondary forms; fusing blockout parts; fixing stretched geometry | Fine detail (it erases it); parts thinner than ~2 voxels (they vanish); open meshes (needs a closed volume) |
| **Dyntopo** | Adds/removes triangles under the brush | Quick concept sculpts; local detail (horns, spikes pulled out with Snake Hook) without remeshing | Anything you'll subdivide, rig, UV or bake cleanly — uneven triangles; it destroys UVs, color attributes and face sets |
| **Multiresolution** modifier | Subdivides a clean base into levels storing displacement per level | Tertiary detail on a retopologized all-quad mesh; switching levels; baking displacement | Changing topology afterwards (you can't); bad base topology (poles/triangles pinch at high levels) |

Standard pipeline: **Voxel remesh** coarse → forms → remesh finer as needed → **retopo** (or QuadriFlow for a quick all-quad base) → **Multires** → detail. Skip Dyntopo unless you need local topology.

Voxel size relative to object height H: blockout ≈ H/36 → forms ≈ H/90 → secondary ≈ H/225 → fine ≈ H/600 (a 1.8 m figure: 0.05 → 0.02 → 0.008 → 0.003). Resulting vertex count ≈ **1.35 × surface area / voxel²** (measured on a synthetic sphere; within 5 %), so halving the voxel size ≈ 4× vertices. Mesh settings (5.x names): `use_remesh_fix_poles`, `use_remesh_preserve_volume`, `use_remesh_preserve_attributes` (keeps mask, face sets, colors; 5.2 interpolates them), `remesh_voxel_adaptivity` (>0 reduces faces but produces triangles — keep 0 before multires).

QuadriFlow (`bpy.ops.object.quadriflow_remesh`; full argument list and prerequisites: `topology.md` §8) — all quads (synthetic test: 3000 requested → 2857 quads). Run it on a *copy*; it replaces the mesh.

## 2. Stage workflow

Work coarse to fine and don't advance a stage until the previous one reads correctly from front, side, top and three-quarter views against the references (`review-and-comparison.md`).

| Stage | Resolution | Brushes | Goal / exit check |
|---|---|---|---|
| **Blockout** | primitives or metaballs joined → voxel H/36 | Grab, Elastic Grab, Snake Hook, Clay Strips (big), Inflate | Proportions and gesture match references; silhouette reads at thumbnail size |
| **Primary forms** | voxel H/90 | Clay Strips, Clay, Scrape/Fill, Flatten/Contrast, Smooth (low) | Big planes and masses (skull planes, rib cage, rock faces); no detail yet |
| **Secondary forms** | voxel H/225 or Multires L2–3 | Clay Strips (small), Draw Sharp, Crease Polish, Pinch/Magnify, Layer | Muscle groups, folds, eyelids, cracks, panel edges |
| **Tertiary detail** | Multires L4–5 on a retopo base | Draw with texture alpha, Crease Sharp, Blob, mesh filter Enhance Details / Sharpen | Pores, wrinkles, scratches, scales — often better as a baked normal/texture (`materials-and-lookdev.md`) |

Habits:
- **Apply scale** and put the origin on the symmetry plane before sculpting: brush dabs stretch on non-uniform scale, voxel size is in local units, symmetry mirrors across the origin.
- Symmetry on from the start; asymmetry only in the last pass.
- Big brush, low strength, many strokes; stroke along the form (muscle fibre, fold, grain).
- Don't polish with Smooth — it erases planes. Re-establish the plane with Scrape/Flatten, then smooth lightly.
- Stretched faces after heavy Grab/Snake Hook → remesh again rather than keep pulling.
- Mask or hide what you're not working on instead of relying on careful strokes.
- In Multires, fix large shapes on a low level (or with *Sculpt Base Mesh*), then step back up.

## 3. Brush guide

Since 4.3 brushes are **assets** in the *Essentials* library; `Brush.sculpt_tool` became `Brush.sculpt_brush_type` (5.0). Flatten/Contrast, Fill/Deepen, Scrape/Fill, Plateau and Trim are all type `PLANE` (4.4+). 5.2 Essentials sculpt brushes:

| Purpose | Brushes (exact asset names) |
|---|---|
| Move mass | Grab, Grab 2D, Grab Silhouette, Elastic Grab (volume-preserving, affects the whole mesh with falloff), Snake Hook, Elastic Snake Hook, Pull, Thumb, Nudge, Twist, Pose, Boundary |
| Build up | Clay Strips (main builder), Clay, Clay Thumb, Layer (constant height), Draw, Blob, Inflate/Deflate |
| Planes & cuts | Scrape/Fill, Flatten/Contrast, Fill/Deepen, Plateau, Trim, Scrape Multiplane |
| Edges & creases | Draw Sharp, Crease Polish, Crease Sharp, Pinch/Magnify |
| Relax & density | Smooth, Blur (5.1+), Relax Slide, Relax Pinch, Density |
| Selection | Mask, Face Set Paint |
| Multires | Erase Multires Displacement, Smear Multires Displacement |
| Projection | Scene Project (5.2+, shrinkwraps the surface onto other objects) |
| Cloth | Grab/Push/Pinch/Inflate/Expand/Bend/Twist … Cloth variants — local cloth folds |

Stroke settings: **Front Faces Only** on thin parts, texture alpha for skin/scales, Lazy/Smooth stroke for clean crease lines. 5.1 merged the stroke toggles into `brush.stroke_method`.

## 4. Masks, face sets, symmetry, filters

- **Symmetry** is stored on the **mesh** (`Mesh.use_mirror_x/y/z`, shared with Edit mode) and mirrors across the object's local origin. `Sculpt.use_symmetry_*` also exists but did not mirror scripted strokes in a synthetic test — set the mesh flags. Radial symmetry: `Mesh.radial_symmetry` (5.0+).
- **Masks** (1 = protected): Mask brush, `paint.mask_flood_fill(mode='VALUE'|'VALUE_INVERSE'|'INVERT', value)`, `sculpt.mask_filter(filter_type='SMOOTH'|'SHARPEN'|'GROW'|'SHRINK'|'CONTRAST_INCREASE'|'CONTRAST_DECREASE')`, `sculpt.mask_from_cavity(factor, blur_steps, invert)`, `sculpt.mask_from_boundary`, `sculpt.mask_by_color`. Stored as the point float attribute **`.sculpt_mask`** — writable directly (procedural masks, below).
- **Mask → geometry**: `sculpt.paint_mask_extract(mask_threshold, add_boundary_loop, smooth_iterations, apply_shrinkwrap, add_solidify)` makes a shell object (armor, clothing, plates); `sculpt.paint_mask_slice(mask_threshold, fill_holes, new_object)` splits.
- **Face sets** (face int attribute **`.sculpt_face_set`**): Face Set Paint brush, `sculpt.face_sets_init(mode='LOOSE_PARTS'|'MATERIALS'|'NORMALS'|'UV_SEAMS'|'CREASES'|'SHARP_EDGES'|…)`, `sculpt.face_sets_create(mode='MASKED'|'VISIBLE'|'ALL'|'SELECTION')`, `sculpt.face_set_edit(mode='GROW'|'SHRINK'|'FAIR_POSITIONS'|'FAIR_TANGENCY'|'DELETE_GEOMETRY')`. Use them to hide parts, auto-mask, drive the Pose brush, and `sculpt.face_set_extract`.
- **Auto-masking** (5.2: `brush.mesh_automasking_settings` / `sculpt.mesh_automasking_settings`): Topology, Face Sets, Boundary, Cavity — detail without spilling onto neighbouring parts.
- **Mesh filters** `sculpt.mesh_filter(type, strength, iteration_count)`: SMOOTH, SCALE, INFLATE, SPHERE, RANDOM, RELAX, RELAX_FACE_SETS, SURFACE_SMOOTH, SHARPEN, ENHANCE_DETAILS, ERASE_DISPLACEMENT — whole mesh, respecting the mask. `sculpt.cloth_filter` for gravity/inflate cloth sims on masked regions.

## 5. Hard-surface sculpting

For armor, rocks, worn stone, hammered metal: voxel remesh → Trim (box/lasso/line/polyline gesture) for cuts → Scrape/Flatten/Plateau for planes → Crease Sharp/Pinch to sharpen → Mask + Extract for panels → remesh to fuse. Trim gestures take `trim_mode='DIFFERENCE'|'UNION'|'JOIN'`, `trim_orientation='VIEW'|'SURFACE'`, `trim_extrude_mode='PROJECT'|'FIXED'`, `trim_solver='MANIFOLD'|'EXACT'|'FLOAT'` (MANIFOLD is fastest but needs a manifold mesh). A PROJECT box trim cuts through the whole depth of the mesh along the view (synthetic sphere: tunnel, not a dent) — use `FIXED` extrude or `use_cursor_depth` for shallow cuts [unverified]. Rocks: cube → remesh → Scrape + Crease Sharp with a rock alpha → mesh filter Enhance Details. Retopologize for games.

## 6. Sculpting from code (MCP / bpy bridge)

**Can an agent sculpt?** Yes, when code runs inside a Blender **UI session** (a Blender MCP or socket bridge that execs code in the running app). Every sculpt operator worked when called through `bpy.context.temp_override(window, area=VIEW_3D, region=WINDOW, active_object, object)`: brush strokes with 15+ brush types, mesh filters, masks, face sets, trim gestures, voxel/QuadriFlow remesh, dyntopo flood fill, symmetrize, multires sculpting, mask extract.

**Headless (`blender -b`) is different**: `brush_stroke` and `detail_flood_fill` fail poll, and `paint.mask_flood_fill`, `sculpt.mask_filter`, `sculpt.mesh_filter`, `sculpt.face_sets_init` **crash Blender**. `voxel_remesh`, `quadriflow_remesh`, `dynamic_topology_toggle`, multires subdivide and direct attribute writes work. Headless procedural detail = bmesh displacement along normals, Displace modifier with a texture, or Geometry Nodes.

### Pick the method

| Need | Most reliable method from code |
|---|---|
| Regional change (inflate the lower half, relax a zone, sharpen everything) | Write `.sculpt_mask` from a function of position → `mesh_filter` |
| Local stroke along a known path (a ridge, a brow line, a crease, a groove) | `brush_stroke` with world-space dabs (`scripts/sculpt_ops.py` `stroke_surface`) |
| Move a volume (pull a snout, bend a horn) | Grab/Elastic Grab dabs along the offset (`grab`), or a Proportional-edit/Lattice/Warp modifier in object space |
| Straight cuts, holes, plates | Trim gesture (`trim_box`) or boolean before remesh; mask → `paint_mask_extract` |
| Noise/pattern detail (rock grain, bark, scales) | Displace modifier / bmesh noise / GN, or a texture alpha on Draw — then bake |
| New resolution | `voxel_remesh`, `dyntopo_flood`, `multires` |

### `scripts/sculpt_ops.py`

Exec it in the UI session, then:

```python
s = SculptSession(bpy.data.objects["Rock"], symmetry="X")   # enters Sculpt mode on the object
s.remesh(0.02)                                                  # guarded by an estimated vertex budget
s.brush("Clay Strips", radius=0.05, strength=0.6)               # Essentials brush, radius in METRES
print(s.stroke_surface([(0.3, -0.5, 0.2), (0.3, 0.5, 0.25)])) # snap to surface, resample, frame view, dab
s.set_mask(lambda co: 1.0 if co.z > 0.4 else 0.0)              # protect the top
print(s.filter('INFLATE', strength=0.1))
s.mask_op('CLEAR')
s.close()                                                       # Object mode, restore view, unlink brush library
```

Each call returns stats (`max` displacement, `moved` vertices, `off_surface`/`offscreen_dabs`, warnings). Also: `grab`, `trim_box`, `extract_mask`, `face_sets`, `dyntopo_flood`, `multires`, `evaluated_positions`, `set_symmetry`.

### API facts that break naive scripts (5.2)

| Fact | Consequence |
|---|---|
| Brush activation: `bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', asset_library_identifier="", relative_asset_identifier="brushes/essentials_brushes-mesh_sculpt.blend/Brush/<Name>")` (4.3+; `paint.brush_set` removed) | Active brush is `scene.tool_settings.sculpt.brush`. Activated brushes are **linked into the open file** (a library to `essentials_brushes-mesh_sculpt.blend`); remove that library when done if the file shouldn't reference it |
| `size` / `unprojected_size` are **diameters** (5.0+); `unprojected_radius` no longer exists | For world-unit brushes set `use_locked_size='SCENE'` + `unprojected_size = 2*r` |
| Unified settings are per mode: `tool_settings.sculpt.unified_paint_settings`, with `use_unified_size=True` by default | Setting only `brush.size` does nothing — set both the brush and the unified settings |
| Pixel-locked size (`'VIEW'`, the default) depends on zoom and window size | Identical code moved 4 vs 13 vertices in two windows; always use scene-locked size from code |
| Stroke element keys: `name, location, mouse, mouse_event, pressure, size, time, is_start, x_tilt, y_tilt`; `pen_flip` is an operator argument, not an element key (4.4+) | Extra keys raise `TypeError`; filter by `bpy.types.OperatorStrokeElement.bl_rna.properties` |
| Each element is **one dab at its `location`** (the mouse isn't re-raycast unless `override_location=True`) | Hidden/back-facing points get sculpted; dabs lifted off the surface still sculpt unpredictably — snap points with `closest_point_on_mesh` |
| No interpolation between elements | Resample paths to ~0.25–0.5 × radius spacing or the stroke becomes beads |
| `mode='INVERT'` reverses direction (Draw pushes inward); `mode` only takes `NORMAL`/`INVERT` since 5.1 | Use for grooves instead of changing `brush.direction`. The temporary smooth/mask/erase switches moved to `brush_toggle='SMOOTH'\|'MASK'\|'ERASE'` (5.1+, also on `paint.image_paint`) |
| Mesh vertex positions update immediately (no mode toggle needed); with **Multires**, base vertices don't move | Measure multires displacement on the evaluated mesh **in Object mode** (in Sculpt mode the evaluated mesh isn't subdivided) |
| `.sculpt_mask` (POINT FLOAT) and `.sculpt_face_set` (FACE INT) are plain attributes | Write them in Object mode with `foreach_set`, re-enter Sculpt mode; filters and brushes honour the mask exactly (masked max displacement 0.0 in test) |
| `sculpt.mesh_filter(type=..., strength=..., iteration_count=...)` runs non-modally via exec | No mouse or modal handling needed |
| Gesture ops (`trim_box_gesture`, `paint.hide_show`, `project_line_gesture`) take **region pixel** coords + `wait_for_input=False` | Frame an orthographic view first; project world points with `view3d_utils.location_3d_to_region_2d` |
| `paint_mask_extract` / `face_set_extract` make the new object active and leave Sculpt mode | Re-activate the source object before the next sculpt op |
| `object.multires_base_apply(modifier, apply_heuristic)` — not `multires_apply_base`; also `multires_subdivide(mode='CATMULL_CLARK'|'SIMPLE'|'LINEAR')`, `multires_reshape`, `multires_unsubdivide`, `multires_rebuild_subdiv`, `multires_higher_levels_delete` | Sculpting at `sculpt_levels = 0` moves base vertices directly |
| Every operator pushes an undo step and marks the file dirty | Probe capabilities in a temporary scene and delete it afterwards; save incrementally before remesh/dyntopo/apply |

**Verify every scripted stroke**: `FINISHED` only means the operator ran. Check the returned displacement (0 moved = off-screen path, radius below edge length, or fully masked), then look — MatCap + wireframe screenshots from the stroke's view and an orthogonal one (`review-and-comparison.md`).

## 7. Performance

- 4.3's sculpt-mode rewrite made brushes and mode entry several times faster; a few million faces is a practical viewport ceiling for the active object [unverified — hardware-dependent]; use Multires levels to switch.
- Hide unworked regions with Face Sets or Box Hide; disable Cavity/MatCap overlays if slow.
- Voxel remesh output grows with surface area / voxel² (≈4× per halving); dyntopo constant detail grows the same way with resolution² (synthetic sphere at resolution 40/m: ~80 k verts).
- Keep Multires ≤ 5 levels; each level ≈ 4× faces.

## 8. From sculpt to production mesh

Imported scans or AI-generated meshes: triage and repair them first (`mesh-repair.md`, `scripts/mesh_repair.py`).

Never rig, animate, or ship a raw sculpt. Duplicate → `_hp` collection → retopologize (`topology.md` §8) → bake Normal (tangent, OpenGL/DirectX per engine), Displacement, Curvature, AO, Thickness from `_hp` to the low mesh. Bake with a cage or ray distance ≈ 1–3 % of object size; Cycles `bpy.ops.object.bake(use_selected_to_active=True)`. With Multires on the low mesh, *Bake from Multires* uses viewport levels as low and render levels as high. Reproject a sculpt onto a retopo mesh with a Shrinkwrap (project) → apply, or on a multires object `multires_reshape` from the high-poly. Keep the sculpt file — refinement passes go back to it.

## 9. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Brush dabs oval / wrong size, voxel remesh far too dense | Unapplied or non-uniform scale | Apply scale before sculpting |
| Symmetry mirrors to the wrong place | Origin not on the symmetry plane | Set origin (or `sculpt.symmetrize` after fixing) |
| Scripted stroke `FINISHED` but nothing moved | Pixel radius tiny, path off the surface or off-screen, mask = 1 | Scene-locked radius ≥ 2× edge length, snap points, check `.sculpt_mask` |
| Parts vanish after voxel remesh | Thinner than ~2 voxels | Smaller voxel or thicken first; remesh thin parts separately |
| Blotchy triangles, UVs/colors gone | Dyntopo | Voxel remesh or retopo instead; keep dyntopo local and early |
| Surface pinches at Multires high levels | Poles/triangles in the base | Retopo to all quads (QuadriFlow at minimum) before Multires |
| Planes melted, form looks "soft" | Smooth used as a fixing tool | Scrape/Flatten to rebuild planes; low-strength smooth only |
| Blender crashes running a sculpt script | Mask/filter/face-set op run headless | Run in the UI session with a VIEW_3D override |
| File now references the brush library | `brush.asset_activate` linked Essentials brushes | Remove the added library after scripted sessions (`SculptSession.close`) |
