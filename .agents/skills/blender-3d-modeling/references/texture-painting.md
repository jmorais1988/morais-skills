# Texture Painting (native Texture Paint, vertex colors, Ucupaint)

How to paint textures in Blender from code and with the user: native Texture Paint strokes in a UI session, vertex-color painting, saving painted images, a hand-painted/stylized game workflow, and the Ucupaint layer add-on (detection, data model, what its operators do from scripts). Everything marked tested was run on Blender 5.2 (Ucupaint 2.4.9); `[unverified]` marks the rest.

## Contents
1. Choose the painting method
2. Native Texture Paint from code
3. Brushes, size and stroke elements
4. Projection, stencil/clone, fill, vertex paint
5. Saving painted images
6. Ucupaint (layer-based painting)
7. Hand-painted / stylized game texturing workflow
8. Verification
9. Common failures

## 1. Choose the painting method

| Need | Use | Tool |
|---|---|---|
| Unique marks in specific places (stains, decals, scratches, masks) on one asset | Native Texture Paint on an image | `scripts/paint_ops.py` |
| Layers you can reorder/blend/mask non-destructively; many channels (color, roughness, normal) at once | Ucupaint (if installed) | `scripts/ucupaint_ops.py` |
| Cheap color on dense meshes, no UVs, low-poly flat-shaded styles | Vertex colors (Color Attributes) | Vertex Paint / attribute API |
| Statistical wear, dirt, edge masks that must follow geometry changes | Procedural masks, baked if needed | `procedural-materials.md` §1, `scripts/bake_maps.py` |
| Hand-painted stylized albedo | Paint over baked AO/curvature guides | §7 |

Painting needs clean, non-overlapping UVs with even texel density first (`uv-unwrapping.md`, `scripts/uv_tools.py`). Overlapping islands paint twice; stretched islands blur.

## 2. Native Texture Paint from code

**UI session only for strokes.** `paint.image_paint` projects from the 3D view: it needs a window + VIEW_3D area/region override (same pattern as `scripts/sculpt_ops.py`). Headless (`blender -b --factory-startup`, tested): `mode_set(mode='TEXTURE_PAINT')` succeeds but `paint.image_paint` fails poll ("context is incorrect", no crash); image creation, numpy fill (4096 px changed), pixel statistics and saving (file written, `is_dirty` cleared) work.

Setup (tested in `PaintSession`):
1. Mesh with a UV map (none → stop and unwrap).
2. Image: `bpy.data.images.new(name, w, h, alpha=True)` + `generated_color`; data maps (roughness, masks) `colorspace_settings.name = 'Non-Color'`.
3. Wire it: Image Texture node → Principled input, node made active (`ensure_material_image`). Or `bpy.ops.paint.add_texture_paint_slot(type='BASE_COLOR', slot_type='IMAGE', name=, width=, height=, color=)` in Texture Paint mode with a VIEW_3D override (tested: creates image + node linked to Base Color). `type` items: BASE_COLOR SPECULAR ROUGHNESS METALLIC NORMAL BUMP DISPLACEMENT; `slot_type` IMAGE or COLOR_ATTRIBUTE.
4. Paint target: `tool_settings.image_paint.mode = 'IMAGE'` + `.canvas = img` paints exactly that image on the active UV map (works for any image, incl. a Ucupaint layer image); `'MATERIAL'` paints `mat.texture_paint_images[mat.paint_active_slot]` (tested).
5. `object.mode_set(mode='TEXTURE_PAINT')`, activate a brush, stroke, **save**.

```python
exec(open(SKILL + "/scripts/paint_ops.py").read())
s = PaintSession(bpy.data.objects["Crate"], image="T_Crate_BaseColor", size=2048, base_color=(0.45, 0.35, 0.25, 1))
s.brush("Paint Hard", radius=0.02, strength=1.0, color=(0.1, 0.08, 0.06))
print(s.stroke_surface([(0.0, -0.5, 0.3), (0.4, -0.5, 0.35)]))   # changed_px, uv_bbox, expected UVs
print(s.save("//textures/T_Crate_BaseColor.png")); print(s.close())
```
Measured (256 px image on a 2 m plane, radius 0.1 m, 1 m stroke): 3852 px changed, UV bbox 0.201–0.799 × 0.451–0.549 against the expected 0.20–0.80 × 0.45–0.55, centroid exact. A dab 50 m off the surface would still paint (projection only uses the mouse position): `stroke()` skips such dabs and reports `off_surface_dabs_skipped` (planted defect: 0 px, 1 skipped).

## 3. Brushes, size and stroke elements

- **Brush assets (4.4+)**: `bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', asset_library_identifier="", relative_asset_identifier="brushes/essentials_brushes-mesh_texture.blend/Brush/<Name>")` in Texture Paint mode. Names in 5.2 (listed from the file): Paint Hard, Paint Soft, Paint Hard Pressure, Paint Soft Pressure, Paint Pixel Art, Airbrush, Blur, Smear, Clone, Fill, Mask, Erase Hard, Erase Soft, Erase Hard Pressure, Erase Pixel Art. Vertex paint (`essentials_brushes-mesh_vertex.blend`): Paint Hard/Soft (+Pressure), Airbrush, Blur, Smear, Average. Activation links the brush file into the .blend; `close()` unlinks the library.
- **Settings**: `brush.color`, `brush.strength`, `brush.blend` (MIX DARKEN MUL LIGHTEN SCREEN ADD OVERLAY SOFTLIGHT … SUB HUE SATURATION COLOR LUMINOSITY ERASE_ALPHA ADD_ALPHA), `brush.image_brush_type` (DRAW, SOFTEN, SMEAR, CLONE, FILL, MASK). Unified settings per mode: `tool_settings.image_paint.unified_paint_settings` (`use_unified_size/strength/color`, `color`, `size`, `unprojected_size`) — set brush and unified together.
- **Size is a diameter (5.x)**: `unprojected_size` (metres, `use_locked_size='SCENE'`) or `size` (pixels, `'VIEW'`).
- **Stroke element keys**: name, location, mouse, mouse_event, pressure, size, time, is_start, x_tilt, y_tilt; `paint.image_paint(stroke=[...], mode='NORMAL'|'INVERT')`. **`size` = brush RADIUS in region pixels for that dab** — measured: size = radius → 26 texels wide (expected 25.6), 2× → 52. Leaving `size=1.0` (fine for sculpt strokes) paints ~nothing: 0 px changed. Each element is one dab (no spacing interpolation) → resample at ≤ 0.25 × radius.
- Frame an orthographic view on the stroke (`frame()`); off-screen dabs are dropped and occluded/back-facing ones are skipped by projection options.

## 4. Projection, stencil/clone, fill, vertex paint

`tool_settings.image_paint` (names verified in 5.2):

| Property | Default use |
|---|---|
| `use_occlude` / `use_backface_culling` / `use_normal_falloff` + `normal_angle` | keep on for painting only visible front faces; turn off to paint through (both sides of thin parts) |
| `seam_bleed` (px) | extend paint across UV seams: 2 default; 4–8 for 2k+ textures and mipmapped game use |
| `dither`, `interpolation` | banding control / 'CLOSEST' for pixel art |
| `use_cavity` + `cavity_curve` | paint only into/away from cavities |
| `stencil_image`, `use_stencil_layer`, `stencil_color`, `invert_stencil` | UV-layer stencil mask while painting `[unverified from code]` |
| `clone_image`, `use_clone_layer`, `clone_alpha`, `clone_offset` | Clone brush from another UV layer/image `[unverified from code]` |
| `canvas`, `mode` | target image (§2) |
| `missing_uvs`, `missing_materials`, `missing_texture` | read-only diagnostics: why nothing paints |

- **Fill**: the "Fill" brush with one dab filled the whole connected image region (tested: 65536/65536 px on a single-island plane). For exact regions use numpy: `PaintSession.fill(color, uv_rect=(u0,v0,u1,v1))` (tested: 4096 px for a quarter). Write `image.pixels.foreach_set()` then `image.update()`.
- **Vertex paint** (tested in a GUI instance): `mesh.color_attributes.new("Col", 'BYTE_COLOR', 'CORNER')`, set it as `active_color` (and `render_color_index`), `VERTEX_PAINT` mode, activate a vertex brush, `paint.vertex_paint(stroke=...)` with the same element keys (`size` = pixel radius) → 148 corners changed on a 40×40 grid; `paint.vertex_color_set()` floods the brush color (6400/6400 corners). A second attempt in a busier scene changed 0 corners (cause not isolated): always measure the attribute after a stroke. Headless: write `color_attributes[...].data.foreach_set("color", ...)` directly.

## 5. Saving painted images

**Painted pixels live only in memory. Saving the .blend does NOT save generated or painted images** unless they are packed; quitting loses them (Blender only warns in the UI).
- `img.filepath_raw = path; img.file_format = 'PNG'; img.save()` → file-backed, `is_dirty` False (tested: `dirty_images()` listed the image before save and nothing after; reload read back the painted red). `save_image()` wraps this and returns existence/bytes.
- Or `img.pack()` to embed in the .blend (bigger files; still unpack for engines).
- Before ending a paint session, gate on `dirty_images() == []` (`PaintSession.close()` reports `unsaved_images`).
- 16-bit/float work (height, masks with gradients): `float_buffer=True` + OPEN_EXR.

## 6. Ucupaint (layer-based painting)

**What it is**: a free GPL extension (extensions.blender.org/add-ons/ucupaint, wiki ucupumar.github.io/ucupaint-wiki) that builds a Photoshop-like layer stack as shader node groups in the material, so layers render live in EEVEE and Cycles. Channels (Color, Alpha, AO, Metallic, Roughness, Normal/height…) are group outputs wired into the BSDF; layers can be images, solid colors, procedural textures (Noise, Voronoi, Brick, Checker, Gradient, Magic, Wave, Gabor, Musgrave), color attributes, fake lighting, edge detect or AO, each with blend modes, opacity and masks. Channels bake to images for export.

**Detection & consent**:
```python
import addon_utils
enabled = "bl_ext.blender_org.ucupaint" in bpy.context.preferences.addons   # legacy installs: "ucupaint"
installed = any(m.__name__.endswith("ucupaint") for m in addon_utils.modules())
```
`scripts/ucupaint_ops.py` `status()` reports installed/enabled/version and what to tell the user; it changes nothing. Installed but disabled → ask before `enable(consent=True)`. Not installed → tell the user (one-click install); don't install silently. User extensions load only when Blender starts WITHOUT `--factory-startup`.

**Data model (2.4.x)**: `mat.yp.active_ypaint_node` names a `ShaderNodeGroup`; its `node_tree.yp` (`is_ypaint_node`, `version`, `use_linear_blending`, `use_baked`) holds `channels` (name, type RGB/VALUE/NORMAL, colorspace, `baked` = name of the baked image node) and `layers`. **`yp.layers[0]` is the top layer.** Each layer: `type`, `enable`, its own node group (`group_node`), a source node (`common.get_layer_source(layer).image` for IMAGE layers), per-channel `layer.channels[i]` (`enable`, `blend_type` — MIX ADD SUBTRACT MULTIPLY SCREEN OVERLAY DIFFERENCE DIVIDE DARKEN LIGHTEN HUE SATURATION VALUE COLOR SOFT_LIGHT LINEAR_LIGHT DODGE BURN EXCLUSION), `masks` (type, blend_type default MULTIPLY). **Opacity values live on group-node input sockets**: set them with `common.set_entity_prop_value(entity, 'intensity_value', v)` — plain `layer.intensity_value = v` does not change the shader (tested: bake unchanged), and a socket value written right after `y_new_layer` was ignored until the layer's `enable` was toggled off/on to force a reconnect (`ucupaint_ops` does this; retest: opacity 0 → base only, 0.5 → exact mix).

**What works from code** (Ucupaint 2.4.9 / Blender 5.2, wrappers in `ucupaint_ops.py`):

| Operator (`bpy.ops.wm.…`) | From script | Notes (tested) |
|---|---|---|
| `y_quick_ypaint_node_setup` | EXEC, headless + UI | pass `target_bsdf_name` of the existing Principled, else EXEC creates a duplicate BSDF + output (invoke normally finds it). Default channels Color + Roughness (+ Metallic/Normal/AO/Alpha flags) |
| `y_new_layer` | EXEC, headless + UI | `type`, `name` (must not clash with an image name), `channel_idx` = channel index as string or `'-1'` all, `blend_type`, `solid_color` (linear), `width/height`, `uv_map`, `texcoord_type`. New layer goes above the active one |
| `y_new_layer_mask` | EXEC, headless + UI | on the ACTIVE layer (`yp.active_layer_index`); `color_option` WHITE/BLACK, `uv_name`, `blend_type` |
| layer/channel blend, enable, opacity | property/socket writes | measured baked linear values: opaque Solid Color (0.1,0.5,0.9) → (0.100,0.503,0.896); layer or channel opacity 0.5 over the 0.8 default → (0.451,0.651,0.847); top layer (0.9,0.9,0.1) at 0.5 → (0.503,0.701,0.503); MULTIPLY → (0.091,0.451,0.091). Blending is linear (`use_linear_blending` True from quick setup) |
| `y_remove_layer` | EXEC after `ui.update_yp_ui()` | without the UI refresh it raises IndexError on `wm.ypui.layer_ui.channels` |
| `y_bake_channels` | **UI session only**, `INVOKE_DEFAULT` with Ucupaint pref `skip_property_popups=True` (restore after) | EXEC raises AttributeError (`no_layer_using` set in invoke); headless INVOKE falls back to EXEC. Invoke reuses an existing baked image's size — rescale it first. Errors "No layer is using any channel!" when all layers are disabled (planted defect caught) |
| `y_remove_yp_node` | EXEC | if baked: rewires baked images into the material ("Baked Textures" frame, Image Texture → Base Color / Roughness) = flattened add-on-free material (tested) |
| `y_merge_layer`, `y_bake_to_layer` (AO/curvature/cavity/pointiness… into a layer), `y_open_image_to_layer`, `y_export_layers`, `y_save_all_baked_images`, UDIM/atlas ops, `paint.y_toggle_eraser` | `[unverified]` — dialogs/file browsers | not tested; hand to the user or test first |

**Painting on a Ucupaint layer**: select the layer, then native strokes on its image — `img, uv = ucupaint_ops.layer_image(obj, "Paint")`; `PaintSession(obj, image=img, mode='IMAGE', link_socket=None)` (tested: 200 px painted on the layer; after baking at 128 px, 156 red pixels in the baked Color). Image masks are Non-Color: paint white/black with the same session. Ucupaint's own panel (N-panel "Ucupaint" in the 3D view / material tab) is the user's interface for everything else.

**Baking / flattening for export**: `bake(obj, size)` → per-channel pixel stats; `save_baked(obj, "//textures")` (the baked images are generated/dirty until saved); `remove_node(obj)` or `flatten(obj, folder, confirm=True)`. Headless alternative: `scripts/bake_maps.py` on the same material bakes BASECOLOR through the Ucupaint group (tested: mean sRGB (0.341,0.722,0.937) vs expected (0.349,0.735,0.955)).

**Performance & compatibility**: every layer adds node groups compiled into the material — many layers make EEVEE shader compilation slow; bake (`yp.use_baked = True`) while working on other things `[unverified: timings]`. Ucupaint 2.4.x requires Blender 4.2+ (manifest); files made with newer Ucupaint may not open correctly in older versions; the add-on stores `yp.version` in the tree. Engines/glTF never see Ucupaint layers — always bake/flatten before export (`game-engine-delivery.md` §6, `web-and-mobile-delivery.md` §2).

## 7. Hand-painted / stylized game texturing workflow

1. **Unwrap** for painting: few seams hidden in low-visibility places, straightened islands for trims, consistent texel density (game props: ~512–1024 px/m at 1–2K — targets: `uv-unwrapping.md` §4), padding from the table in `uv-unwrapping.md` §5 (4–16 px depending on texture size).
2. **Base colors** per material zone: flat fills (`fill(uv_rect=)`, Ucupaint Solid Color layers or vertex colors). Keep values mid-range; save a palette.
3. **Guides**: bake AO (and a curvature/edge mask) with `scripts/bake_maps.py --maps AO` (or Ucupaint `y_bake_to_layer` `[unverified]`), load as Multiply/Overlay layers at 30–60 % to see form.
4. **Paint light and shadow into the albedo**: top-down light gradient (lighter up-facing, darker down), cavity darkening, edge highlights on convex edges, hue shift (warm lights / cool shadows), then detail (wood grain, scratches) with Paint Hard/Soft at small radii; Blur/Smear to soften.
5. **Seams and dilation**: rotate around every seam; raise `seam_bleed`; bake margin ≥ 8 px at 1k (padding table: `uv-unwrapping.md` §5) so mipmaps don't show island borders.
6. **Shader**: unlit/emission or simple diffuse (Principled Roughness ~0.8–1, Metallic 0, Specular low) — stylized work shouldn't get PBR highlights fighting the painted light; preview in the target engine's unlit shader.
7. **Export**: flatten (Ucupaint) → PNG sRGB albedo; name `T_<Asset>_BaseColor` in the export copy (`game-engine-delivery.md` §3).

## 8. Verification

- After every scripted stroke: `changed_px > 0`, `uv_bbox`/`uv_centroid` near `expected_uv_start_end`; `off_surface_dabs_skipped`/`offscreen_dabs` zero.
- `dirty_images()` empty before the session ends; files exist with non-zero bytes.
- Ucupaint: `describe()` shows the intended stack (top first); bake stats `mean_rgb` sampled at island centres match expected colors (whole-image means include margin pixels); `use_baked`/flattened material renders the same as the live stack.
- Look at it: Material Preview from 3 angles and at game distance; check seams with a UV-grid image before painting.

## 9. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Scripted stroke `FINISHED` but 0 px changed | stroke element `size` 1.0 (it is the pixel radius) | set `size` = brush radius in region px (`paint_ops` does) |
| Paint appears in the wrong place / on the far side | view-projected dab from a point not on the visible surface | snap to surface, frame an ortho view, keep occlusion/backface culling on |
| Nothing paints, UI shows pink/missing | `image_paint.missing_uvs/missing_texture`; canvas not on active UV map | unwrap; set `mode='IMAGE'` + `canvas` or the material's active paint slot |
| Painted work gone after reopening | generated/painted image never saved or packed | `img.save()` / `img.pack()`; gate on `dirty_images()` |
| Stroke operator fails in `blender -b` | projection painting needs a 3D view | UI session (GUI timer instance or live bridge); numpy fill headless |
| Visible lines along UV seams in game | no seam bleed / small bake margin; mip bleeding | `seam_bleed` 4–8, bake margin ≥ 8 px, pad islands |
| Ucupaint layer opacity change has no effect | `setattr(layer, 'intensity_value')` only | `common.set_entity_prop_value(...)` / `ucupaint_ops.set_layer` |
| `y_bake_channels` AttributeError `no_layer_using` | called with EXEC_DEFAULT or headless | UI session, INVOKE_DEFAULT with `skip_property_popups` on (`ucupaint_ops.bake`) |
| `y_remove_layer` IndexError `layer_ui.channels` | Ucupaint UI cache never drawn | call `ui.update_yp_ui()` first |
| Duplicate Principled BSDF + Material Output after setup | quick setup via EXEC skipped invoke | pass `target_bsdf_name` (`ucupaint_ops.setup`) |
| Ucupaint operators missing | extension disabled or Blender started with `--factory-startup` | `status()`; ask the user before enabling |
| Exported asset loses all layers | engines don't read node groups | bake + flatten, export images |
