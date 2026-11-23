# Stylized & NPR Rendering (toon, low poly, palettes, diorama cameras)

Stylized work fails differently from PBR. The mesh is usually fine; what goes wrong is a palette the view transform shifts, toon bands that only work in one engine, outlines that break with distance or stack order, and anime faces shaded by noisy topology instead of a designed shape. Pick the style first (§1) and review with §7 instead of the PBR pass in `materials-and-lookdev.md` §2. Outlines, Line Art and Grease Pencil are in `outlines-and-line-art.md`; anime face and hair shading in `anime-face-and-hair.md`. Numbers come from Blender 5.2 tests on synthetic scenes unless marked `[unverified]`.

## Contents
1. Style decision table
2. Color management and engine for flat palettes
3. Toon shading
4. Stylized low poly: flat normals, palettes, color attributes
5. Toon water
6. Isometric / orthographic diorama camera
7. Review for stylized work
8. Common failures

## 1. Style decision table

| Style | Engine / view transform | Shading | Lines |
|---|---|---|---|
| Toon / cel | EEVEE / Standard | Shader to RGB → Constant ramp, 2–3 bands + rim (§3) | hull (characters) + Line Art (sets): `outlines-and-line-art.md` §1, §5 |
| Flat low poly | EEVEE, Workbench preview / Standard | flat normals, palette texture or color attributes, 1 sun (§4) | none or thin hull (`outlines-and-line-art.md` §2) |
| Hand-painted | EEVEE / Standard | painted albedo into Emission/Diffuse, weak light | none |
| Anime character | EEVEE / Standard | toon bands (§3) + proxy face normals, SDF face shadow, angel ring (`anime-face-and-hair.md`); turntables for review: `scripts/shot_setup.py --turntable` (`rendering-and-lighting.md` §5), `scripts/render_cli.py` (`render-farm-and-compositing.md` §2) | hull with vertex-group width + Line Art inner lines (`outlines-and-line-art.md` §5, `anime-face-and-hair.md` §4) |
| Painterly | EEVEE or Cycles / AgX ok | normal lighting, compositor Kuwahara + paper overlay | optional GP strokes (`outlines-and-line-art.md` §6) |
| Ink / technical illustration | any / Standard | white or flat fills (Workbench Flat, Emission) | Line Art or Freestyle (`outlines-and-line-art.md` §1, §3–§4) |
| Pixel look | EEVEE / Standard | low resolution, `render.filter_size = 0`, textures `interpolation='Closest'`, compositor Pixelate, GP `FX_PIXEL` (`outlines-and-line-art.md` §6) | 1 px hull or none |

Stylized low-poly budgets: `poly-budgets-and-targets.md` §1.

## 2. Color management and engine for flat palettes

An unlit Emission swatch (sRGB 0.85, 0.30, 0.20, strength 1) rendered as:

| View transform | Output sRGB |
|---|---|
| Standard | 0.847, 0.298, 0.200 (round-trips) |
| AgX (default) | 0.773, 0.325, 0.212 |
| Filmic | 0.749, 0.333, 0.216 |
| Khronos PBR Neutral | 0.835, 0.239, 0.075 |

- Palette styles: **Standard**, Look None, exposure 0; author sRGB hex. A lit Diffuse surface only hits the swatch where light × cosine = 1. Set the transform before tuning any color.
- **Shader to RGB is EEVEE-only** (`BLENDER_EEVEE`). Freestyle and Grease Pencil render in EEVEE, Cycles and Workbench. Workbench Flat + Object/Attribute color is the fastest stylized preview and a clean ID mask.

## 3. Toon shading

**EEVEE**: Diffuse (or Principled) → **Shader to RGB** → ColorRamp **Constant** (shadow color at 0.0, lit color at 0.2–0.5) → Emission 1 → Output. On a sphere lit from +X, EEVEE banded correctly. **Cycles returned the lit color on both sides** (no light data).

**Engine-agnostic light vector**: dot product of the normal with a driver-fed light direction.
```python
cx = nt.nodes.new("ShaderNodeCombineXYZ")   # -> Vector Math DOT_PRODUCT with Geometry.Normal -> Constant ramp -> Emission
for i, ax in enumerate("XYZ"):
    d = cx.inputs[ax].driver_add("default_value").driver; d.type = 'SCRIPTED'; d.expression = "m"
    v = d.variables.new(); v.name = "m"; v.type = 'SINGLE_PROP'
    v.targets[0].id_type = 'OBJECT'; v.targets[0].id = sun
    v.targets[0].data_path = f"matrix_world[2][{i}]"   # RNA paths index COLUMN first: [2][i] = light's +Z axis
```
Measured: correct bands in EEVEE and Cycles, flipping when the sun rotates 180°. `matrix_world[i][2]` reads a row and inverted the bands. A bare `m` is a simple expression, so it runs without Python auto-exec. Limits: one directional light, no cast shadows. A GN Store Named Attribute of `dot(normal, light)` read by an Attribute node is a per-vertex alternative `[unverified]`.

- **Multiple lights**: Shader to RGB sums all lights, so a fill shifts the bands. Use one key sun and take ambient from the ramp's dark stop.
- **Terminator**: sun `angle = 0`, low `shadow_filter_radius`, `use_shadow_jitter` off. Faceted-terminator acne: Object `shadow_terminator_geometry_offset` / `_normal_offset` (Cycles), or smoother normals (proxy normals, `anime-face-and-hair.md` §1).
- **Rim**: Layer Weight Facing/Fresnel → Constant ramp (edge 0.6–0.8) → Add, masked by the lit band.
- **Specular blob**: Glossy → second Shader to RGB → Constant ramp with a narrow white stop at ≥ 0.9 → Add.
- Keep 2–3 bands and identical band positions across one character's materials.

## 4. Stylized low poly: flat normals, palettes, color attributes

- Faceting is the style. `shade_flat()`, and choose triangulation deliberately (Triangulate Beauty vs Fixed).
- **Palette texture**: e.g. 32×8 swatches, `interpolation = 'Closest'`. Scale each UV island into one swatch. 1 px padding is enough only with Closest filtering and mipmaps off in the engine; with mipmaps, pad per the table in `uv-unwrapping.md` §5. One material + one texture = one draw call.
- **Color attributes**: `mesh.color_attributes.new("Col", 'BYTE_COLOR', 'CORNER')` (CORNER allows per-face colors), Color Attribute node, exported by glTF/FBX.
- Strata/bands: object-Z Gradient → Constant ramp. Record swatches (hex, ≤ 12 per asset, ≤ 32 per scene) in NOTES.md.
- One sun + flat world ambient. AO only as baked vertex color.

## 5. Toon water

Replaces the physical shader of `environment-modeling.md` §6.
- Body: flat color; Fresnel band from Layer Weight Facing → Constant ramp.
- **Shoreline foam (engine-agnostic)**: GN on the water plane → Geometry Proximity to terrain/rocks (Faces) → Store Named Attribute `shore_dist` → shader Attribute → Less Than 0.3–0.6 m, with a scrolling Noise on the threshold → white. Exports when realized.
- Depth by ray: the **Raycast** shader node exists in 5.2 (Position, Direction, Length → Is Hit, Self Hit, Hit Distance, Hit Position, Hit Normal). Cast downward and use Hit Distance as depth. Per the 5.2 manual: Cycles treats all geometry as opaque and the node is expensive (bake the result); EEVEE traces in screen space only (off-screen geometry is missed) and honours `Object.visible_raycast`; attribute outputs at the hit are Cycles-only.
- Foam lines: Voronoi Distance to Edge with slow scrolling (≤ 0.05 m/s) → Constant ramp.

## 6. Isometric / orthographic diorama camera

- `type = 'ORTHO'`. True isometric rotation X 54.736° (35.264° elevation), Y 0, Z 45°. Pixel-art 2:1 isometric uses X 60° (30° elevation).
- `ortho_scale` = max(projected width, projected height × aspect) of the 8 bbox corners in camera space, + 5–10 % margin. Tight clip start/end.
- Camera creation and framing: `scripts/shot_setup.py`, `rendering-and-lighting.md` §3.

## 7. Review for stylized work

Check at final resolution and at 128 px thumbnail:
1. **Silhouette**: Workbench Single black on white. Readable, clear negative space, no tangents.
2. **Value grouping**: desaturated render shows 3–4 value groups, with shadow shapes designed rather than noisy.
3. **Palette count**: unique colors vs the NOTES.md swatch list; no view-transform drift (§2).
4. **Line consistency**: similar on-screen width across depth, no doubled hull + Line Art lines (`outlines-and-line-art.md` §5), intersections drawn, no popping between frames. `lineart_setup.py` alignment numbers.
5. **Engine parity**: hull outlines and color attributes survive export; Shader to RGB, Line Art and Freestyle do not.
6. **Face**: orbit the key light 360° (turntable: `scripts/shot_setup.py --turntable`). The face shadow should step through 2–3 designed shapes, with `normal_transfer.py --pose-bone` for deformation. For SDF face shadows, gate with `scripts/face_sdf.py` `orbit_check` (fails on `wrong_side`, `not_monotonic`, `front_not_lit`, `back_not_shadowed`) and the angel ring with `ring_check` (`ring_drifts`, `ring_too_wide`) — `anime-face-and-hair.md` §5.

## 8. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Swatches duller or shifted | AgX/Filmic | Standard, Look None (§2) |
| Bands in EEVEE, flat color in Cycles | Shader to RGB is EEVEE-only | driver light vector (§3) |
| Bands inverted | `matrix_world[i][2]` reads a row | `matrix_world[2][i]` |
| Bands jump when adding a fill | Shader to RGB sums lights | one key light, ambient in ramp |
| Terminator acne on faceted meshes | shadow terminator on low-poly normals | Cycles terminator offsets, or proxy normals (`anime-face-and-hair.md` §1) |
| Diorama crops or floats | `ortho_scale` from the object size, not the projected bbox | project the 8 corners, + 5–10 % margin (§6) |

Outline, Line Art and Grease Pencil failures (hull covering the object in Cycles, missing or gray lines, bake keyframes, GP API renames): `outlines-and-line-art.md` §7. Face shadow, custom-normal and angel-ring failures: `anime-face-and-hair.md` §6.
