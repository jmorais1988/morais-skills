# Outlines & Line Art (inverted hull, Line Art, Freestyle, Grease Pencil v3)

Read this when a stylized asset needs lines: choosing between an inverted hull, Line Art, Freestyle and compositor edges; building each from code; sizing lines that survive distance and export; baking Line Art to editable strokes; and writing Grease Pencil v3 strokes directly. Style choice, palettes and toon bands are in `stylized-npr.md`; anime per-face outline widths in `anime-face-and-hair.md` §4. Numbers come from Blender 5.2 tests on synthetic scenes unless marked `[unverified]`.

## Contents
1. Choosing an outline method
2. Inverted hull
3. Line Art (GPv3) and `scripts/lineart_setup.py`
4. Freestyle
5. Combining hull and Line Art without doubled lines
6. Grease Pencil v3 from code
7. Common failures

## 1. Choosing an outline method

| Method | Best for | Engines | Weak spots |
|---|---|---|---|
| **Inverted hull** (Solidify flip) | characters, props, game export | EEVEE; Cycles with backfacing mix; any engine as mesh | doubles tris; thin/open parts; no inner creases |
| **Line Art** (GPv3) | sets, inner creases, intersections, editable/bakeable lines | all (renders as GP) | camera-bound; bake per frame; world-space width |
| **Freestyle** | illustration stills, line styles | EEVEE, Cycles, Workbench (all drew lines in 5.2) | slow, render-only, not editable or exportable |
| Workbench outline | viewport preview | viewport only (0 outline px in an F12 render) | not a render method |
| Compositor edges | quick post on stills | any (5.x `scene.compositing_node_group`; Filter node `Type` is a menu input) | resolution-bound, no occlusion logic; `render-farm-and-compositing.md` §4 |

Engine parity: hull outlines survive export as mesh; Line Art and Freestyle do not (bake Line Art to strokes for a GP asset, or render).

## 2. Inverted hull

```python
m = ob.modifiers.new("Outline", 'SOLIDIFY')
m.thickness = 0.01; m.offset = 1.0; m.use_flip_normals = True; m.use_rim = False
m.material_offset = len(ob.data.materials)            # outline material appended last
m.thickness_vertex_group = "outline_w"; m.thickness_clamp = 0
```
Outline material: Mix Shader(fac = Geometry **Backfacing**, black Emission, Transparent) plus `use_backface_culling = True`. Measured on a sphere: EEVEE with culling alone drew a correct ring, but **Cycles ignores material backface culling**, so the hull covered the object (center black, 2,484 dark px). The Backfacing mix drew the ring in both engines (139 / 149 px). Width is in object units: apply scale; screen-constant width needs a camera-distance driver `[unverified]`. Stack it after Armature (on anime heads: Armature → Data Transfer → Subdivision → Solidify, `anime-face-and-hair.md` §1). Weight 0 on eyes/mouth interior.

## 3. Line Art (GPv3) and `scripts/lineart_setup.py`

`bpy.ops.object.grease_pencil_add(type='LINEART_SCENE'|'LINEART_COLLECTION'|'LINEART_OBJECT')` works headless, or use `scripts/lineart_setup.py` (idempotent, bake, alignment check):

```
blender -b scene.blend --python scripts/lineart_setup.py -- --source SCENE|COLLECTION|OBJECT --source-name Props
    [--camera CAM_Main] [--name LINES_Lineart --layer Lines] [--radius 0.003 --crease 140]
    [--no-contour --no-crease --no-intersection --material-borders --edge-marks --loose --occlusion 0 0]
    [--silhouette NONE|GROUP|INDIVIDUAL] [--color 0 0 0 --opacity 1] [--bake --bake-range CURRENT|RANGE]
    [--verify <dir> --verify-res 320 --tol-px 2] [--save out.blend]
```

Modifier `GreasePencilLineartModifier`, type `'LINEART'`:
- `source_type`, `source_collection` / `source_object`, `target_layer` (name), `target_material`.
- `radius` = half-width in **metres**, world space (4.3+ has no screen-space thickness; default 0.0025). Pixel footprint ≈ distance × sensor_width / (focal × resolution_x). At radius 0.03 m (≈ 1.7 px) lines rendered in EEVEE and Cycles but only reached 0.50 gray on white. Size lines ≥ 2 px at the far distance.
- `crease_threshold` (rad, default 140°): an edge draws when its dihedral angle is **below** the threshold. Icosphere edges (138.19°) drew at 140° and disappeared at 130°.
- `use_contour / use_crease / use_intersection / use_material / use_edge_mark / use_loose`; `use_multiple_levels` + `level_start/level_end` for hidden lines; `silhouette_filtering`; 5.2 `fill_strokes`.
- Overrides: `obj.lineart.usage` (INHERIT, INCLUDE, OCCLUSION_ONLY, EXCLUDE, INTERSECTION_ONLY, NO_INTERSECTION, FORCE_INTERSECTION) and `crease_threshold`; `collection.lineart_usage`; `mat.lineart.mat_occlusion`.
- Camera = `scene.camera` unless `use_custom_camera` + `source_camera`. Moving the GP object did not offset the lines.
- **Bake**: `bpy.ops.object.lineart_bake_strokes(bake_all=False)` bakes **every frame of the scene range**: a default 1–250 scene got 250 keyframes (13 × 250 = 3,250 strokes). Narrow the range for stills (`--bake-range CURRENT` does this temporarily). `lineart_clear()` un-bakes and leaves an empty keyframe at frame 0. Baked modifiers stay frozen (`is_baked`) until cleared.

**Alignment check** (`--verify`): renders object IDs with Workbench (flat, AA off, film transparent), marks pixels whose 4-neighbour ID differs as edges, projects stroke points (GP `matrix_world` applied) through `scene.camera`, densifies to 0.5 px and reports precision (stroke samples within tol px of an edge) and recall (edge pixels within tol px of a stroke). Only contour lines are in an ID mask, so with crease/intersection/material/edge-mark lines on, precision is reported but not gated. Gates default precision ≥ 0.9 and recall ≥ 0.8. Line Art sees meshes (and objects convertible to meshes) only; the Workbench mask ignores GP-only occluders and alpha-clipped materials.

`lineart_setup.py` test (plane, 3 cubes, sphere, 320×240):

| Case | Strokes | Precision / recall within 2 px | Defects |
|---|---|---|---|
| contour only (+ bake) | 9 (baked 9, 1 keyframe) | 1.00 / 0.92 (p50 0.4 px) | none |
| default crease + intersection | 17 | 0.84 (not gated: interior lines) / 1.00 | none |
| custom camera ≠ render camera | 8 | 0.54 / 0.53 | `camera_mismatch`, `misaligned` |
| empty collection / no camera | 0 | — | `empty_source`, `zero_strokes` / `no_camera` |

A nearby second camera (0.6 m offset) still scored 1.00 on boxy geometry, because polyhedron contours are view-stable. The static `camera_mismatch` check is what catches it.

## 4. Freestyle

`render.use_freestyle = True`, `line_thickness_mode = 'ABSOLUTE'`, `line_thickness` px, `view_layer.freestyle_settings` (crease_angle, linesets). Render-only: not editable, not exportable; draws in EEVEE, Cycles and Workbench (§1).

## 5. Combining hull and Line Art without doubled lines

Give each method one job: the **hull draws the contours**, and **Line Art draws inner creases and intersections with contour off** (`use_contour = False`, `lineart_setup.py --no-contour`) — or use Line Art only. With both drawing the silhouette, every outline appears twice at two widths and pops as the widths diverge with distance. Set `obj.lineart.usage = 'EXCLUDE'` on eyes, brows and teeth (features drawn in the texture) so Line Art doesn't ink them, and give the hull weight 0 there through its thickness vertex group. Anime per-region hull widths and skin-tinted hull slot: `anime-face-and-hair.md` §4. Review with `stylized-npr.md` §7 item 4.

## 6. Grease Pencil v3 from code

Version boundaries: **4.3** rewrote GP (object type `GPENCIL` → `GREASEPENCIL`, strokes became attributes in drawings, `layer.info` → `layer.name`, `active_frame` → `current_frame()`). **5.0** renamed `GreasePencilv3` → `GreasePencil`, `bpy.data.grease_pencils_v3` → `bpy.data.grease_pencils`, and old annotation types to `Annotation*`. **5.1** fills via the `fill_id` curve attribute (0 = none) plus `hide_stroke`. **5.2** exposes those on strokes and adds `layer.mask_layers.add/remove`.
```python
gp = bpy.data.grease_pencils.new("GP_Notes"); ob = bpy.data.objects.new("GP_Notes", gp)
bpy.context.scene.collection.objects.link(ob)
mat = bpy.data.materials.new("MAT_Ink"); bpy.data.materials.create_gpencil_data(mat)
mat.grease_pencil.color = (0, 0, 0, 1); mat.grease_pencil.show_fill = False; gp.materials.append(mat)
drawing = gp.layers.new("Ink").frames.new(1).drawing   # layers.new(name, set_active, layer_group)
drawing.add_strokes([4])                               # point counts per new stroke
s = drawing.strokes[-1]; s.material_index = 0; s.cyclic = False
for i, p in enumerate(s.points):
    p.position = (i * 0.5, 0, 0); p.radius = 0.01; p.opacity = 1.0
```
- `drawing.strokes/points` are Python views (drawing + index). Re-fetch after `add_strokes/remove_strokes/resize_strokes`. Bulk: `drawing.attributes["position"|"radius"|"opacity"|"cyclic"|"material_index"]`.
- Stroke: `cyclic, material_index, fill_id, fill_color, fill_opacity, hide_stroke, softness, start_cap, end_cap, curve_type`. Point: `position, radius, opacity, rotation, vertex_color, delta_time`.
- **2D over 3D**: `ob.show_in_front` for overlay notes; `gp.stroke_depth_order = '3D'` for occluded strokes; `layer.use_lights = False` for flat ink; layer `blend_mode`, `opacity`, `tint_color`.
- Modifiers are `GREASE_PENCIL_*` (THICKNESS, SMOOTH, SIMPLIFY, NOISE, OUTLINE, DASH, ...). Shader FX: `FX_RIM, FX_SHADOW, FX_PIXEL, FX_GLOW, FX_BLUR, FX_COLORIZE`. Hand-made strokes rendered in EEVEE, Cycles and Workbench.

## 7. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Hull covers the object in Cycles | Cycles ignores backface culling | Backfacing → Transparent mix (§2) |
| Hull too thin/thick on parts | unapplied scale, thin/open parts | apply scale, thickness vertex group |
| Outline in viewport, not in render | Workbench outline is viewport-only | hull, Line Art or Freestyle |
| Every contour drawn twice, widths diverge with distance | hull and Line Art both draw contours | hull contours + Line Art `--no-contour`, or Line Art only (§5) |
| Line Art inks eyes/brows/teeth | features included in the source | `obj.lineart.usage = 'EXCLUDE'`, hull weight 0 (§5) |
| Line Art draws nothing | no camera, empty source, missing layer | `lineart_setup.py` defects |
| Lines don't match the render | custom camera ≠ scene camera | `camera_mismatch`; clear custom camera |
| Lines gray or vanishing far away | world-space `radius` below ~2 px | size radius from pixel footprint (§3) |
| Bake created hundreds of keyframes | bake covers the scene range | bake CURRENT; clear then re-bake |
| Soft bends lack creases | dihedral above `crease_threshold` | raise toward 170° or mark edges |
| Old GP scripts fail | 4.3 rewrite, 5.0 renames | §6 (`GREASEPENCIL`, `frame.drawing`, `bpy.data.grease_pencils`) |
