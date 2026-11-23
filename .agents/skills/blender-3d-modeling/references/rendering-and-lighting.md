# Rendering & Lighting

Read this when a finished model has to become deliverable pixels: engine and device choice, studio/product lighting, camera fitting, glass and caustics, loop-safe turntables, video output and color management (`scripts/shot_setup.py`). Command-line/farm rendering, render passes and the 5.x compositor are in `render-farm-and-compositing.md` (`scripts/render_cli.py`); camera two-point perspective, sun/sky, portals, render presets and the exposure probe live in `archviz-lighting-and-rendering.md` (§1–§5) and `scripts/archviz_setup.py` — reused here, not repeated. Facts marked *measured* come from synthetic tests in Blender 5.2.0 LTS.

## Contents
1. Engine & device
2. Studio & product lighting
3. Product cameras & composition
4. Glass, liquids & caustics
5. Turntables, animation & video output
6. Color management
7. Common failures

## 1. Engine & device

| Deliverable | Engine | Why |
|---|---|---|
| Hero still, glass/metal product, archviz final | Cycles | Correct refraction, soft shadows, caustics, light groups, shadow catcher |
| Turntable/lookdev review, stylized, fast animation | EEVEE (`BLENDER_EEVEE`) | Seconds per frame; ray tracing + probes for reflections |
| Silhouette/clay checks, masks, ortho sheets, CI renders | Workbench (`BLENDER_WORKBENCH`) | No lighting noise, deterministic, fastest |

- Engine ids in 5.x: `CYCLES`, `BLENDER_EEVEE`, `BLENDER_WORKBENCH` (*measured*; `BLENDER_EEVEE_NEXT` is rejected since 5.0).
- **Cycles GPU from code**:
  ```python
  prefs = bpy.context.preferences.addons["cycles"].preferences
  prefs.compute_device_type = 'OPTIX'      # NONE, CUDA, OPTIX, HIP, ONEAPI (METAL on macOS)
  prefs.get_devices()                      # refresh; prefs.devices -> name, type, use
  for d in prefs.devices: d.use = d.type in {'OPTIX'}
  scene.cycles.device = 'GPU'              # CPU | GPU
  ```
  Each device appears once per backend (a CUDA and an OPTIX entry for one NVIDIA card, plus the CPU). Preferences are not saved in `-b` unless you save them, so set the device in the render script, or pass `-- --cycles-device OPTIX` (`+CPU` appends the CPU; flag order: `render-farm-and-compositing.md` §1). Denoiser: `scene.cycles.denoiser` = `OPENIMAGEDENOISE` | `OPTIX`; `denoising_use_gpu`.
- **EEVEE in background mode** needs a GPU context. *Measured*: `-b --factory-startup` on a desktop with a GPU rendered EEVEE fine (first frame dominated by shader compilation). Linux render nodes without a display/GPU driver cannot create the context [unverified here]. Test EEVEE on the actual farm node; fall back to Cycles or Workbench there. `--gpu-backend opengl|vulkan` selects the backend.
- 5.2 Cycles: Performance › Texture Cache (`.tx`, `blender scene.blend --command maketx` pre-generates), Simplify › Texture Resolution %, world `Cast Shadows` (`world.cycles.use_shadows`); OptiX needs driver ≥ 575.

## 2. Studio & product lighting

`scripts/shot_setup.py studio_rig()` builds this rig relative to the hero camera and the target's world bbox, in collection `STUDIO`:

| Light | Placement (camera-relative) | Size / power | Role |
|---|---|---|---|
| `LGT_Key` | 45° to camera-left, 35° up | ≈ 1.2× object size, irradiance E | Shape and main shadow |
| `LGT_Fill` | 60° camera-right, 10° up | 2× larger, 0.25–0.5 × E | Opens shadows (ratio 1:2–1:4) |
| `LGT_Rim` | behind, opposite the key, 25° up | strip (0.25 × 2 size), `spread` 60° | Separates silhouette from background |
| `LGT_Card_n` | flanking, hidden from camera | emissive planes | Long clean highlights on glossy/glass |

- **Power that means something**: `area_light_power(E, w, h, d)` returns watts so a surface facing the light on-axis at distance d receives E in Sun-strength units (white diffuse → linear value E). It uses the exact point-to-rectangle form factor: P = E·π·area / F, which tends to E·π²·d² in the far field. *Measured*: value/E = 0.9998 (size/d 0.05), 0.9999 (0.5), 0.9996 (2.0). The naive E·π·d² is 1/π too dark, and the far-field formula overshoots by 2.3× when the softbox is twice as large as its distance. Start with key E ≈ 2–4 under AgX, then `archviz_setup.exposure_probe()`.
- **Softness** comes from size relative to distance, not from power. Moving a softbox closer makes it softer *and* brighter. `spread` (radians) narrows an area light like a honeycomb grid, giving strip lights with little spill.
- **Reflection cards** for glass and chrome: emissive planes with `visible_camera = False` and `visible_shadow = False`. The product reflects them, the camera never sees them. Black cards (black material) give dark edge lines on glass. Shape highlights with gradient textures on the card.
- **Light linking** keeps a rim light off the backdrop: `light_obj.light_linking.receiver_collection`. **Shadow linking** (`blocker_collection`) stops a prop from shadowing the product. 5.2 can copy links to the selection.
- **Cyc backdrop**: `cyc_backdrop()` builds a floor that curves (cove radius ≈ 1.2× the product diagonal) into a wall behind the product, with smooth normals facing the camera. *Measured*: floor exactly at the target's min Z; a ray through the target lands on `BG_Backdrop`. Use diffuse albedo 0.8, roughness 0.9. For a gradient, light the wall more than the floor, or use a Gradient texture on the wall height.
- **Shadow catcher** (compositing onto a plate or transparent PNG): `obj.is_shadow_catcher = True` plus `render.film_transparent = True` (Cycles only). Enable `view_layer.cycles.use_pass_shadow_catcher` to capture indirect light too. Without that pass Cycles uses a simpler approximation (manual).
- **HDRI studio**: `archviz_setup.hdri_world()` with a studio HDRI at strength 0.5–1 for reflections, plus the area rig for shape. To hide the HDRI from the camera but keep reflections, use film transparent + a backdrop, or a Light Path `Is Camera Ray` mix in the world.

## 3. Product cameras & composition

| Shot | `scripts/shot_setup.py` | Setting |
|---|---|---|
| Hero 3/4 | `hero_camera(target, lens=100, azimuth=35, elevation=12, margin=0.08)` | 85–135 mm (36 mm sensor), camera slightly above the product's mid-height |
| Catalogue front/side/top | `ortho_camera(target, view="FRONT")` | Orthographic, fitted ortho_scale |
| True isometric | `ortho_camera(target, iso="true")` | X rot 54.7356°, Z 45° → elevation 35.2644°, axes 120° apart |
| 2:1 game "isometric" | `ortho_camera(target, iso="dimetric")` | X rot 60°, Z 45° → ground lines at 26.565° |

- **Fitting** uses evaluated world-space vertices (modifiers, parents and children included). Distance is bisected until the tighter axis sits exactly at `margin`, then the framing is centred with lens shift, which keeps the chosen perspective. *Measured*: tight-axis margin 0.0800 and symmetric margins. A Workbench silhouette render agreed with the projected margins within 1 px (hero, front ortho, iso).
- `frame_margins(camera, target, margin)` is the gate. It reports left/right/bottom/top margins, points behind the camera and far-clipped points. *Defects caught*: camera dollied 25 % closer → min margin −0.066, fail; camera inside the target → 144/144 points behind, fail.
- *Measured* iso proof (`axis_projection`): X/Y/Z screen lengths all 0.816497 at −30°/30°/90°. Dimetric: X/Y 0.790569 at ±26.565°, Z 0.866025.
- **DoF**: `hero_camera(..., dof_fstop=4)` focuses on the bbox centre. Small products (≤ 20 cm) at real scale get very shallow DoF at f/2.8, which reads as miniature. Use f/5.6–f/11, or scale the aperture with product size. **Focus stacking** has no built-in equivalent: render with DoF off (all sharp), or render 2–3 focus distances and blend them in comp with a Depth-pass mask.
- Composition: product fills 60–80 % of the tighter axis; shoot slightly above; keep the label facing ≤ 30° off-axis; negative space on the side the product "looks" toward; ≥ 8 % margin for crops/ads.

## 4. Glass, liquids & caustics

- **Materials**: Principled Transmission 1, Roughness 0–0.05, IOR 1.45–1.52 (glass), 1.33 (water), 1.36 (spirits/oil ≈ 1.47). Thin sheets use **Thin Wall** (5.2). Solid glass needs real thickness and outward normals. Tint glass with Volume Absorption, not base color.
- **Liquid in glass**: model the liquid slightly *larger* than the glass inner wall (0.1–0.5 mm overlap) instead of leaving an air gap. For the overlapping interface, give the liquid IOR = liquid/glass ratio (1.33/1.5 ≈ 0.887) so the ray sees one correct interface [unverified in 5.2; classic Cycles recipe]. Meniscus: a small upward curl where the liquid meets the wall. Bubbles are separate small spheres with IOR 1/1.33.
- **Bounces**: transmission ≥ 12, transparent ≥ 16, total ≥ 12, or thick glass goes black. `archviz_setup.render_preset` values are fine starting points.
- **Dispersion**: *measured* in 5.2, Principled, Glass and Refraction BSDF expose **no Dispersion socket**. Compositor Lens Distortion has a `Dispersion` input (chromatic fringing on the image). For physical rainbow edges, mix three Glass BSDFs tinted R/G/B with IOR offsets of about ±0.02 [unverified]; this costs noise.
- **Caustics**:
  - Path-traced: `scene.cycles.caustics_refractive = True` (reflective separately). *Measured* on a glass ball over a floor: shadow-centre value 1.3–2.6 versus 0.0 with caustics off. Costs noise; raise samples, clamp indirect 5–10, `blur_glossy` 0.5–1.
  - MNEE shadow caustics (API verified): caster `obj.cycles.is_caustics_caster`, receiver `obj.cycles.is_caustics_receiver`, light `light.cycles.is_caustics_light` (world: `world.cycles.is_caustics_light`). Needs smooth-shaded triangle meshes with a refractive/glass closure, ≤ 6 caster surfaces, refractive caustics inside shadows only; bump/normal maps and volumes are ignored (manual).
  - *Measured caveat*: with all three flags set, Cycles logged `Use MNEE True`, and flagged casters turned fully opaque to normal shadow rays (shadow 0.07–0.14 → 0.0). Yet **no caustic appeared** in any synthetic test: ico/UV sphere or thick disc, area/point/spot/sun light, CPU and OptiX. The sun gave 2 % of the path-traced energy. MNEE caustics are unreliable in 5.2 tests: render a 128 px test of your own scene before relying on them; if it stays dark, use path-traced refractive caustics or fake them (an emission gobo texture on the floor).
- Glass on a backdrop needs something to refract and reflect: reflection cards, a gradient background, a dark card behind for edge definition.

## 5. Turntables, animation & video output

### 5.1 Building the turn

- **Object vs camera turntable**: rotate the *object* when lights should stay fixed relative to the camera (highlights sweep across the product — the usual lookdev turntable). Orbit the *camera* when the environment/HDRI should rotate with the view.
- **Loop math**: keys 0° at frame `s` and 360° at `s + N`, **linear** interpolation, render range `s … s + N − 1`. Step = 360/N and there is no duplicate frame at the loop seam. `shot_setup.turntable(target, frames=N, mode="object"|"camera")` builds a `TT_Pivot` empty at the bbox bottom-centre, parents the root targets or the camera with world transforms kept (an existing outside parent is replaced and listed under `reparented_from`), and linearizes the F-curves through the 5.x slotted API (`bpy_extras.anim_utils.action_get_channelbag_for_slot(action, slot).fcurves`; see `animation.md`).
- **Rigged characters**: pass the **armature** as the turntable target. `turntable()` parents only root targets to the pivot — a target whose parent is itself a target is left alone and follows its parent — so meshes parented to the armature turn with it. Passing the meshes on their own re-parents them away from the rig.
- CLI form: `blender -b scene.blend --python scripts/shot_setup.py -- --target Bottle --turntable 72 --turntable-mode object [--turntable-margin 0.02] [--check CAM_Hero] [--save out.blend]`; live: `SHOT_OPTS = {"target": ["Bottle"], "turntable": {"frames": 72, "mode": "object", "margin_check": 0.02}}`.

### 5.2 Proving the turn

- `turntable_check(obj, N)` proves it. *Measured* clean: loop matrix difference 1.5e−7, steps 15.000 ± 3e−5° (N = 24), 10.000° (N = 36, camera mode), pass. *Defects caught*: inclusive end frame `s + N` → `duplicate_last_frame`; eased (SINE in/out) keys → steps 0.68–15.69°, `uniform_steps` false.
- **Framing over the turn**: silhouettes change while the target spins, so a fit for one angle can crop another. `turntable(..., margin_check=0.02)` — CLI `--turntable-margin 0.02` — samples ~24 frames of the turn through the hero camera (falls back to the scene camera) and adds `worst_margin_over_turn`, `required_margin`, `margin_camera` and `margin_pass` (worst ≥ M) to the turntable dict (*measured* worst margin 0.077 for a tilted bottle). If it fails, re-fit the hero camera on the widest frame.
- **Playblast before rendering**: `scripts/viewport_capture.py --out DIR --targets Bottle --views persp --frames START:END[:STEP]` captures a Workbench sequence headless — one PNG per view/shading pair per frame (`<prefix>_<view>_<shading>_<frame:04d>.png`), camera fixed per view and framed on the union of the target bbox over the range; the result reports `frames_captured` and only empty frames are flagged. Seconds per turn, enough to catch a wrong pivot, a hitch or a crop before Cycles time is spent.

### 5.3 Motion blur, flicker, persistent data

- **Motion blur**: `render.use_motion_blur`, `motion_blur_shutter` (0.5 = 180°), per-object `obj.cycles.use_motion_blur` / `motion_steps`. EEVEE: `scene.eevee.motion_blur_steps`. A turntable at 5°/frame usually needs none.
- **Flicker**: `scene.cycles.use_animated_seed = True` turns sticky noise into grain (better for video). Denoised frames may shimmer between frames: raise samples/lower the adaptive threshold, and store denoising passes to denoise with temporal consistency offline. EEVEE: more `taa_render_samples`, stable probes.
- **Persistent data** (`render.use_persistent_data`) keeps BVH/textures between frames of a turntable; big win for static geometry, more RAM.

### 5.4 Video output & encoding

- **Video (5.0+)**: set the media type **first**. *Measured*: `image_settings.file_format = 'FFMPEG'` raises unless `image_settings.media_type = 'VIDEO'`; `media_type` is `IMAGE` | `MULTI_LAYER_IMAGE` | `VIDEO`. Then `render.ffmpeg.format` (`MPEG4`, `MKV`, `WEBM`, `QUICKTIME`…), `.codec` (`H264`, `H265`, `AV1`, `PRORES`, `FFV1`, `DNXHD`…), `.constant_rate_factor` (`HIGH`, `MEDIUM`, `LOSSLESS`…), `.ffmpeg_preset` (`BEST`/`GOOD`/`REALTIME`). *Measured* output name: `turn_0001-0006.mp4`.
- **Farms render image sequences, never video**: a crash loses one frame instead of the file, chunks can run in parallel, and the encode happens afterwards (VSE or ffmpeg). Keep EXR/PNG masters. One-line H.264 preview from a PNG master: `ffmpeg -framerate 24 -i turn_%04d.png -c:v libx264 -pix_fmt yuv420p -crf 18 turn.mp4` (`yuv420p` for browser/player compatibility, which also needs even frame dimensions [unverified]).

## 6. Color management

AgX (default) with a Look for most product/archviz work. Brand/swatch colors: **Standard** reproduces flat swatch values exactly, while Khronos PBR Neutral and AgX shift them (the measured per-transform swatch table is `stylized-npr.md` §2); PBR Neutral keeps saturated product colors plausible *under lighting* but is not a swatch-matching transform — verify with a swatch card in frame. The 5.2 view transforms are `Standard`, `ACES 1.3`, `ACES 2.0`, `Khronos PBR Neutral`, `AgX`, `Filmic`, `Filmic Log`, `False Color`, `Raw` (*measured*). Masters are linear EXR (no view transform baked in); previews are PNG with the view applied. Exposure by measurement, looks and working space: `archviz-lighting-and-rendering.md` §3.

## 7. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `enum "FFMPEG" not found` | 5.x media type still IMAGE | `image_settings.media_type = 'VIDEO'` first |
| Turntable hitches at loop | End key frame rendered twice or eased keys | Render `s … s+N−1`, LINEAR keys; `turntable_check` |
| Product cropped on some turntable frames | Framed for one angle only | `margin_check` / `--turntable-margin` over the turn, re-fit on the widest angle |
| Character meshes re-parented away from their rig by the turntable (`reparented_from` lists the armature) | Meshes passed as targets while the armature was not | Pass the armature as the turntable target; parented meshes follow |
| Glass black | Too few transmission/transparent bounces, inverted normals | Bounces ≥ 12/16, recalc normals |
| Shadows under glass pitch black with MNEE flags | Flagged casters block shadow rays; MNEE found no path | Test render; use `caustics_refractive` or fake caustics |
| Lights far too dark/bright after rescaling the product | Watts don't scale with distance | `area_light_power()` or re-run `studio_rig` |
| Grainy shimmer in denoised animation | Per-frame denoise, fixed seed | `use_animated_seed`, more samples, temporal denoise |
