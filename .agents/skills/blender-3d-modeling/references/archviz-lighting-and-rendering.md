# Archviz Lighting & Rendering (cameras, light, exposure, output)

Read this once the shell and furniture exist (`archviz-modeling.md`) and the scene has to be shot: archviz is judged **through the shot cameras** and sold by **light**, so this file holds camera and composition rules, daylight and artificial lighting with the measured sun strengths, exposure from measurement, archviz material values, Cycles/EEVEE presets and output, the camera/light/render gates and the shot review. Facts marked *measured* come from synthetic tests in Blender 5.2; version boundaries are stated.

## Contents
1. Camera & composition
2. Lighting
3. Color management & exposure
4. Materials
5. Render settings & output
6. Gates & shot review (`scripts/archviz_gates.py`)
7. Common failures

## 1. Camera & composition

| Shot | Lens (36 mm sensor) | Height | Notes |
|---|---|---|---|
| Interior overview | 18–24 mm | 1.2–1.6 m | Corner position, look across the diagonal; keep the camera inside the room, `clip_start` 0.01–0.05 |
| Interior vignette / detail | 35–85 mm | seat or table height | Shallow DoF (f/2.8–5.6) with focus object |
| Exterior eye level | 24–35 mm | 1.6–1.7 m | Two-point, building fills ≈ 2/3 of frame |
| Exterior aerial | 35–50 mm | as needed | Three-point allowed; still avoid heavy tilt on facades |

- **Two-point perspective**: camera rotation X exactly 90°, roll 0 → verticals stay vertical; frame up/down with lens **shift**, never by tilting. `shift_y = lens × (target_z − camera_z) / (horizontal_distance × sensor_width)` for `sensor_fit` AUTO (*measured*: target lands at NDC (0.5, 0.5)). `scripts/archviz_setup.py` `two_point_camera(name, position_xy, target, lens, eye_height)` does this. Keep |shift| ≤ 0.3; beyond ~0.5 edges stretch. Aim the target at 1.0–1.3 m for interiors so floor and ceiling share the frame; a target near ceiling height fills the frame with ceiling (synthetic test: target at 1.9 m from 1.5 m eye → mostly walls and ceiling).
- **One-point perspective** for symmetric rooms/corridors: camera square to the back wall, vanishing point on a third or centre.
- Composition: thirds (`show_composition_thirds`), foreground element for depth, avoid a wall edge splitting the frame, show ceiling when it's designed, windows in frame for context but not dominant. Portrait format for tall spaces.
- Name cameras `CAM_<room>_<n>`; `batch_render("CAM_")` renders every shot (§5).

## 2. Lighting

**Daylight — Sun + Sky** (`scripts/archviz_setup.py` `sun_and_sky(elevation, azimuth)`):
- 5.0+ Sky Texture types: `MULTIPLE_SCATTERING` (default, most accurate), `SINGLE_SCATTERING` (old Nishita), `PREETHAM`/`HOSEK_WILKIE` (legacy). Very bright by design — compensate with exposure (§3).
- Use the sky with **`sun_disc = False` plus a Sun lamp** at the same angle (sharper, better-sampled shadows). Matching strength is **not 1000 W/m²**: the lamp that equals the sky's own disc measured **≈ 99 W/m² at 15°, 130 at 35°, 142 at 60°** elevation (*measured*, sun_intensity 1, densities 1). A 1000 W/m² lamp under that sky is ~7× too strong relative to the skylight.
- Sun angle from place/time: `sun_angles(lat, lon, utc_datetime)` (NOAA approximation) or the Sun Position extension. Low sun (10–25°) = long warm shafts; 35–50° = neutral afternoon; overcast = sky/HDRI only, no sun lamp.
- **HDRI** (`hdri_world`) for fast realistic skies and reflections; match the Sun lamp to the HDRI's sun direction if it has one; rotate the Mapping Z to place the sun.

**Interiors lit through windows** (Cycles):
- **Portals**: an area light with `light.cycles.is_portal = True` over each window, facing into the room (`window_portals("GLASS_")` sizes and orients them). Slower per sample, converges faster for sky light; they don't help direct sun.
- Enough diffuse bounces (≥ 4, 6 for deep rooms) and no caustics — caustics-off is the right call for interiors; product and liquid shots (glassware, bottles, water) may need path-traced caustics (`caustics_refractive`); MNEE shadow caustics were unreliable in 5.2 tests: `rendering-and-lighting.md` §4.
- Window glass must let light through cheaply — Thin Wall glass (§4).

**Artificial light**: power in Blender watts is radiant, not electrical — ≈ 800 lm LED bulb ≈ 2.1 W, 1000 lm ≈ 2.9 W, 2500 lm tube ≈ 4.5 W (manual table; rough rule W ≈ lm / 683 × 2). Color via Blackbody node (2700 K warm home, 3000–3500 K retail, 4000 K office). IES profiles via `ShaderNodeTexIES` (Cycles). Emissive lampshades still need a real light inside for illumination. Light linking (4.0+: `obj.light_linking.receiver_collection`) to keep a fill off the ceiling.

**Night shots**: sky at low strength (deep blue), all fixtures on, exposure +1…+3 EV; windows show warm interior from outside.

## 3. Color management & exposure

- View transform **AgX** (default 4.0+) for photoreal; looks in 5.2: `AgX - Punchy`, `AgX - Greyscale`, `AgX - Very High Contrast` … `AgX - Base Contrast` … `AgX - Very Low Contrast` (*measured* enum). `AgX - Medium High Contrast` is a good archviz start. For material boards that must match swatches, check with a swatch card in frame: Standard reproduces flat swatch values exactly, Khronos PBR Neutral shifts dark values (`stylized-npr.md` §2). **Standard** clips skies and windows — avoid for daylight interiors.
- 5.0+ per-file working space (`Linear Rec.709` default, `Rec.2020`, `ACEScg`) — decide at project start.
- **Expose from measurement**: `scripts/archviz_setup.py` `exposure_probe(camera)` renders a tiny linear EXR and suggests EV so the median luminance maps to 0.18, and reports how much frame stays above 1.0 after it (the windows). *Measured* on a synthetic studio with one 2 m sunlit window: median 0.55 → −1.6 EV, 5 % of pixels still above 1.0 — normal for a window view with AgX.
- Brightness outside vs inside differs by 3–6 EV in reality; let the window glow (AgX rolls it off) rather than darkening the room, or composite a separately exposed exterior.
- Exteriors under the sky: a sunlit white (0.8) surface measured ≈ 9–35 linear (low → high sun) → expect exposure around −4 to −7 EV; probe per shot.

## 4. Materials

Build with `shader-nodes.md` / `materials-and-lookdev.md` (texture sources and map sets: `texture-sources-and-pbr-sets.md`); archviz specifics:

| Material | Base color (linear) | Roughness | Notes |
|---|---|---|---|
| White paint | 0.75–0.82 (never 1.0) | 0.8–0.95 | Tiny bump/noise breaks CG flatness |
| Concrete | 0.40–0.55 fresh, 0.2–0.3 aged | 0.7–0.9 | Macro stains, formwork tie holes |
| Oak / light wood | 0.35–0.55 | 0.35–0.6 (varnish Coat 0.1–0.3) | Grain along the plank length; per-plank variation |
| Stone / marble | per sample | 0.1–0.4 polished, 0.6+ honed | Veins continuous across slabs (same mapping) |
| Fabric | per sample, darker than you think | 0.8–1.0 | Sheen 0.3–1 for velvet/wool; weave normal at real scale |
| Leather | 0.05–0.3 | 0.4–0.6 | Wrinkle normal, edge darkening |
| Metal (brushed steel) | 0.55–0.65, Metallic 1 | 0.25–0.4 | Anisotropic for brushed |
| Mirror | 0.9, Metallic 1 | 0.0–0.02 | Needs something worth reflecting |
| Window glass | white, Transmission 1, IOR 1.5 | 0 | **5.2+: `Thin Wall` on a single plane** (verified socket); older: 4–6 mm solid pane |

- **Glass**: `scripts/plan_to_rooms.py` makes single-plane panes with Thin Wall in 5.2+ (6 mm solids on older versions). Single-sided glass *without* Thin Wall bends the view; the `glass` gate (§6) reports it. Thick decorative glass (vases, tables): solid with outward normals, Volume Absorption for tint.
- **Scale**: world-scale UVs or Box/triplanar mapping (blend 0.1–0.3); the `uv` gate (§6) reports UV units per metre per object and flags objects sharing a material at different scales.
- **Anti-tiling**: Object Info Random / cell IDs → hue/value/offset variation; macro noise overlay; 5.0+ closures allow blended box mapping and texture bombing.
- CC0 libraries: Poly Haven, ambientCG (`scripts/build_pbr_material.py`, `texture-sources-and-pbr-sets.md` §2).

## 5. Render settings & output

Passes and the 5.x compositor: `render-farm-and-compositing.md` §4–5; CLI/farm rendering and output-folder checks: `render-farm-and-compositing.md` §1–2 (`scripts/render_cli.py`).

`scripts/archviz_setup.py` `render_preset(name)` sets Cycles; values:

| Preset | Samples / adaptive threshold | Bounces (diff/gloss/trans/transp/max) | Clamp indirect | Resolution % |
|---|---|---|---|---|
| `interior_preview` | 128 / 0.05 | 4/4/8/8/8 | 10 | 50 |
| `interior_final` | 1024 / 0.01 | 6/4/12/16/12 | 6 | 100 |
| `exterior_final` | 512 / 0.01 | 3/4/12/16/8 | 10 | 100 |

`interior_preview` trades transmission/transparent bounces (8/8) for speed; the final presets meet the general glass rule (transmission ≥ 12, transparent ≥ 16), whose authority is `rendering-and-lighting.md` §4 — raise a preset's bounces to that rule when thick or stacked glass renders dark. All presets: denoise on (OpenImageDenoise; OptiX on NVIDIA), light tree on, caustics off, Filter Glossy 1, 16-bit EXR master + denoising and Cryptomatte object/material passes. Raise samples rather than the denoiser when flat walls look blotchy. 5.2: Performance › Texture Cache (auto `.tx`) for heavy texture sets. Set the device explicitly (`render_preset(..., device='GPU')`) after enabling it in Preferences.

- **EEVEE** (`BLENDER_EEVEE`, 5.0 name) for quick walkthroughs/previews: `use_raytracing` on, method `SCREEN` or `PROBE`, `ray_tracing_options.use_backface_hit` (5.2, reduces leaks), a baked Volume Probe per room, Sphere probes for reflective rooms, shadow ray/step counts up; 5.2 may render darker than 5.1 (Fast GI "far thickness" removed).
- **Output**: EXR (16-bit half, multilayer = multi-part in 5.0+) for post + PNG/TIFF preview. `batch_render("CAM_", "//renders")` renders every `CAM_` camera and writes EXR + a PNG with the view transform applied (note: `Image.save_render` uses the scene's output format regardless of extension — the helper switches to PNG for that file).
- Animation walkthroughs: camera on a Follow Path with Track To at eye level, 24–30 fps, ≤ 1 m/s walking speed, motion blur on.

## 6. Gates & shot review (`scripts/archviz_gates.py`)

Run `scripts/archviz_gates.py` before final renders (the geometry gates `closure`, `zfight`, `contact`, `dims` run after the shell and after furniture: `archviz-modeling.md` §8):

| Check | Finds | *Measured* on synthetic rooms |
|---|---|---|
| `leaks` | Interior rays escaping through anything but opening cutters (`CUT_`) | clean 0 rays; 2 cm ceiling gap → 18 leak rays at ceiling height |
| `glass` | Single-sided glass without Thin Wall, inverted normals | flagged after disabling Thin Wall |
| `camera` | Pitch/roll (converging verticals), lens and eye-height ranges, camera inside geometry, clipping | 10° pitch flagged |
| `render` | Standard view transform, clamp 0, caustics, low bounces with glass, 8-bit output | Standard + clamp 0 flagged |
| `uv` | Texture scale mismatch between objects sharing a material | — |

A passing gate removes one defect class; then **review each shot camera** (`review-and-comparison.md`): exposure (no crushed corners, windows allowed to glow), verticals, scale cues (door, chair, person), material response under grazing light, contact shadows, repetition, noise/denoise blotches at 100 % crop.

## 7. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Room dark though the sun is out | Glass blocking light (thick refractive panes), too few diffuse bounces, sun behind the facade | Thin Wall glass (§4), bounces ≥ 4, portals, check sun azimuth vs window normal (§2) |
| Blown-out, flat image | Standard view transform, exposure by eye, 1000 W/m² sun with a physical sky | AgX + look, `exposure_probe` (§3), matched sun strength (§2) |
| Buildings "falling backwards" | Camera tilted | Level camera + shift_y (§1); `camera` gate |
| Room lit from nowhere, bright corner lines | Shell gaps (a modeling defect) | `leaks` gate here, `closure` gate and solid slabs: `archviz-modeling.md` §8–9 |
| Repeating tiles/wood | One UV scale, no variation | World-scale UVs, per-object random, macro variation (§4); `uv` gate |
| Fireflies near lamps and chrome | Caustics on, clamp 0, small bright lights | Caustics off, clamp indirect 3–10, larger lights (§5) |
| Blotchy walls after denoise | Too few samples for large flat areas | More samples / lower adaptive threshold, albedo+normal passes (§5) |
