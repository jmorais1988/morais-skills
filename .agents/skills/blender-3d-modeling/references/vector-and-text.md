# Vector & Text Assets (SVG logos, text objects)

Read this when flat vector input (SVG logos, emblems, signage, fonts) must become solid geometry at an exact size. The job fails in the same quiet ways: wrong import scale, bevels that fold at corners, holes that vanish, unwelded caps. All numbers below were measured in Blender 5.2 unless marked `[unverified]`. Tool: `scripts/svg_to_solid.py`. Voxel and pixel-art assets: `voxel-and-pixel-art.md`.

## Contents
1. SVG import: curve importer vs Grease Pencil, scale, holes
2. Logo solids: extrude/bevel vs Solidify+Bevel, the bevel clamp
3. Text objects
4. Script: `scripts/svg_to_solid.py`
5. Common failures

## 1. SVG import: curve importer vs Grease Pencil, scale, holes

| | Curve importer (`bpy.ops.import_curve.svg`) | Grease Pencil importer (`bpy.ops.wm.grease_pencil_import_svg`) |
|---|---|---|
| Ships as | Core add-on `io_curve_svg`, enabled in factory settings (4.2+ core add-on; 5.2 verified) | Built-in operator |
| Result | One **2D curve object per `<path>`**, in a new collection named after the file; one `SVGMat` material per fill colour | One Grease Pencil object (strokes + fills) |
| Placement | XY plane, doc top-left → origin with Y flipped (viewBox bottom edge on Y = 0), origin at world 0 | **XZ plane** (front view), `recenter_bounds=True` by default |
| Scale | **90 px/in**: 1 px = 0.28222 mm (200 px → 56.44 mm measured). With a viewBox and `width`/`height` in mm/cm/in/pt/pc, real units are kept (100 mm → 0.1000 m measured), divided by scene `unit_settings.scale_length` | `scale` default 10 (200 px → 0.532 m measured, i.e. 96 dpi × 10); `resolution` 10; `use_scene_unit` False |
| Use for | Logos, signage, emblems, cutters, CNC/print outlines | 2D animation, line art, stylized overlays (`stylized-npr.md`) |

Importer behaviour worth knowing:
- **Inkscape/Illustrator px files are 96 dpi**, the curve importer assumes 90. A px-sized SVG therefore comes in 6.7 % small. Never trust the import size. Measure the flat fill and scale to the target (`svg_to_solid.py --width-mm`).
- **Holes (counters)** come in as extra splines in the same curve object. Blender's 2D fill cuts them by the curve's `fill_rule`, so hole winding doesn't matter under EVEN_ODD (square-with-hole measured: Euler 0 = genus 1 for both windings). The importer does not read the SVG `fill-rule` attribute.
- Paths with `fill="none"` (stroke-only) become **3D unfilled curves**. Strokes are not outlined. In the vector app, convert strokes and live text to paths ("Stroke to Path", "Object to Path") before export. `<image>` and `<text>` elements are ignored.
- **Joining:** filled paths are separate objects. Joining them into one curve (script does it spline by spline, keeping materials) lets counters of one path cut another. Under EVEN_ODD, overlapping separate shapes cancel each other. For unions use `fill_solver='CDT'` + `fill_rule='NONZERO'` (5.1+). In 4.x, boolean the overlap in the vector app.
- **Fill solver (5.1+):** `curve.fill_solver` SWEEP_LINE (default for curves) / CDT (Delaunay, handles self-intersecting outlines). `curve.fill_rule` EVEN_ODD (default) / NONZERO. Text objects default to CDT + NONZERO. Use CDT for imported logos.
- Origin: the importer leaves every object's origin at world 0. After building the solid, centre the mesh on its bbox (script `--origin CENTER|BOTTOM_CENTER`) so it rotates and places predictably.

## 2. Logo solids: extrude/bevel vs Solidify+Bevel, the bevel clamp

**Curve route (default, keeps outline size exact):**

| Property | Meaning (2D curve) | Setting for a logo of total depth D, bevel b |
|---|---|---|
| `extrude` | half-thickness each side of the plane | `D/2 − b` (dz = 2·extrude + 2·bevel, measured) |
| `bevel_depth` | round-over radius | `b` |
| `offset` | moves the outline along its normals | **`−b`** keeps the silhouette on the original outline (100 mm stays 100 mm; offset 0 gives 104 mm with b = 2 mm) |
| `bevel_resolution` | segments per quarter circle (0–32) | 2–4 hero, 0–1 game |
| `fill_mode` | 2D: NONE/BACK/FRONT/BOTH | BOTH |

- **Convert**: `bpy.data.meshes.new_from_object(ob.evaluated_get(dg))` or `bpy.ops.object.convert(target='MESH')`. Both leave the **cap/side seams unwelded** (32 non-manifold edges on a square-with-hole). Always Merge by Distance after conversion — ≤ 0.001 mm for logos, the feature-relative case of the skill rule (≤ 1/10 of the smallest feature, `3d-printing.md` §2). After the merge: 0 non-manifold edges.
- **Bezier corners fold under an inset bevel.** The curve is evaluated with `resolution_u` points on every segment, straight ones included. Near a sharp corner those in-between points move past each other when offset inward. A 20° tip with a 1 mm bevel gave 54 self-intersecting face pairs, and the auto-clamp had to fall to 0.24 mm. Converting splines to POLY (straight segments keep only their end points, curves sampled) fixed it: 1 mm, 0 intersections, and 253 faces instead of 1584. `svg_to_solid.py` does this by default (`--keep-bezier` to skip).
- **Mesh route:** flat fill → mesh → Solidify(D, offset 0, even) → Bevel(width b, limit ANGLE 30°, `use_clamp_overlap`). No folds, and clamp overlap limits bevels in tight spots. Beveled sharp tips get shorter, though (width −0.017 mm at 1 mm bevel on the test logo). Use it when outline precision doesn't matter or the curve route keeps self-intersecting. Weighted Normal after Bevel as in `hard-surface-modeling.md` §3.

**Bevel clamp rule.** An inset bevel self-intersects once `b` passes half the thinnest stroke (the smallest feature radius). It can also fold a rounded convex corner whose radius is below `b`. Keep **b ≤ 40 % of the smallest feature radius** and `b ≤ D/2`. Sharp tips don't count toward the feature size, since the bevel rounds and shortens them. Counters and gaps never close under an inset bevel. They do close with `offset = 0` (outline grows by `b`), in which case also keep `b` below 40 % of half the narrowest gap. Measured on the test logo (thinnest wall 6.38 mm, radius 3.19 mm):

| Bevel | Result |
|---|---|
| 1.276 mm (40 % rule) | 0 self-intersections, manifold, hole kept |
| 4.0 mm (125 % of radius, no clamp) | 275 intersecting face pairs, 52 non-manifold edges, genus wrong |

Same trade-off as the panel rule in `hard-surface-modeling.md` §3. Verify on the evaluated mesh (BVH self-overlap of faces sharing no vertex, zero-area faces, Euler/genus), not by eye. Cleanup when a logo must go further (embossing, printing): Remesh Voxel at ≤ ¼ stroke width, then decimate. Or boolean-union overlapping letters first (`mesh-repair.md`).

**Materials & shots**: brushed or polished metal, enamel fills per SVG colour (keep the `SVGMat` slots as material IDs): `shader-nodes.md` §3, recipes in `procedural-materials.md` §1. Product lighting and turntables: `rendering-and-lighting.md` §2 and §5. Printed badges and cutters (tolerances, min wall): `3d-printing.md` §3–4.

## 3. Text objects

```python
f = bpy.data.fonts.load("/path/Inter-Bold.ttf", check_existing=True)   # .ttf/.otf; built-in "Bfont Regular" always exists
cu = bpy.data.curves.new("TXT_Label", 'FONT'); cu.body = "OPEN 24H"; cu.font = f   # font_bold/_italic/_bold_italic = style slots
cu.size = 0.1; cu.align_x = 'CENTER'; cu.align_y = 'CENTER'          # align_x: LEFT CENTER RIGHT JUSTIFY FLUSH
cu.space_character = 1.05; cu.space_word = 1.0; cu.space_line = 1.2  # multipliers
cu.body_format[3].kerning = -0.5                                       # per-character, float
cu.extrude = 0.004; cu.bevel_depth = 0.0006; cu.offset = -0.0006; cu.bevel_resolution = 2
ob = bpy.data.objects.new("TXT_Label", cu); bpy.context.scene.collection.objects.link(ob)
```

- Measured (Arial, size 1, "AVAV"): `space_character` 1.2 widened 1.951 → 2.251 m. `kerning = 5` on one character widened it by 0.061 m, so kerning units are small: tune by measuring `ob.dimensions`, not by guessing.
- `align_x='CENTER'` centres the text on the origin (x −0.979 … 0.972). Text boxes (`text_boxes`, `overflow`) for paragraphs.
- **Fill**: 5.1+ text defaults to `fill_solver='CDT'`, `fill_rule='NONZERO'`, which handles overlapping glyph contours. In 4.x overlapping contours leave holes or missing parts: fix in a font editor or with a mesh boolean. Extruded + bevelled text after Merge by Distance: 0 non-manifold edges (5.2, CDT).
- **Text on curve**: `cu.follow_curve = curve_obj` works. The manual recommends a **Curve modifier** on the converted text for more control (`modifiers-and-curves.md` §4).
- **Convert** for export, booleans, engraving: `object.convert(target='MESH')`, then Merge by Distance and Limited Dissolve on the caps. Keep the text object as `_source`. Small labels are better as decals or normal-map detail (`hard-surface-modeling.md` §6).
- **Font licensing**: glyph outlines converted to geometry are still the font's design. SIL OFL / Apache fonts (most of Google Fonts) allow use in rendered and embedded products. Many commercial EULAs restrict logo use, outline conversion or embedding in distributed apps and games. Check the licence before shipping geometry made from a font, and never bundle the font file with an asset unless the licence allows it.

## 4. Script: `scripts/svg_to_solid.py`

SVG → joined 2D curve → POLY conversion → scale to `--width-mm` → extrude/bevel (`curve` or `mesh` method) with the 40 % clamp estimate (§2), then a verification loop (bevel × 0.7 while self-intersections remain) → merged, centred mesh (`--origin CENTER|BOTTOM_CENTER`, §1). Gates: width within 0.1 mm, holes preserved (flat loops − islands = solid genus), manifold, 0 self-intersecting pairs. Test logo (20° tip, counter, cubic corner): width error 0.00008 mm, hole 1 → 1, 1 mm and 1.276 mm bevels clean. Planted 4 mm no-clamp caught.

## 5. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Logo 6.7 % too small / wrong size | 96-dpi px SVG read at 90 px/in | Scale by measured width (`--width-mm`); export SVG in mm with a viewBox |
| Letters filled solid, counters gone | Counter path is a separate object, or fill rule unions it | Join all splines into one curve; EVEN_ODD for classic counters |
| Overlapping shapes punch holes into each other | EVEN_ODD across joined paths | CDT + NONZERO (5.1+), or union in the vector app |
| Outline parts missing after import | Stroke-only paths / live text | Stroke to Path, Object to Path before export |
| Logo grows by 2× bevel, counters close | `offset` left at 0 | `offset = −bevel_depth` |
| Ridges or spikes at sharp corners after bevel | Evaluated in-between points fold under inset bevel | POLY conversion (script default); smaller bevel; mesh route |
| Mesh "non-manifold" right after convert | Cap/side seams unwelded | Merge by Distance ≤ 0.001 mm (≤ 1/10 of the smallest feature, `3d-printing.md` §2) |
| Thin strokes self-intersect | Bevel > half the thinnest stroke | b ≤ 40 % of min feature radius; check BVH self-overlap |
| Text glyphs with holes or black parts (4.x) | Overlapping font contours, sweep-line fill | 5.1+ CDT/NONZERO; else boolean union after convert |
