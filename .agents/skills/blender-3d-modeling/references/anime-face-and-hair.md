# Anime Faces & Hair (proxy normals, SDF face shadow, angel ring)

Read this when a character needs anime/toon face shading: 2–3 designed shadow shapes instead of a topology-driven terminator, a light-angle face shadow map that works in any engine, a hair highlight band that stays put when the camera moves, and the head proportions and topology those setups assume. Toon bands, palette and engine choice are in `stylized-npr.md`; outlines in `outlines-and-line-art.md`. Numbers come from Blender 5.2 tests on synthetic heads unless marked `[unverified]`.

## Contents
1. Proxy normals for the face (`scripts/normal_transfer.py`)
2. Face shadow map, SDF (`scripts/face_sdf.py`)
3. Hair angel ring
4. Head proportions and topology (anime)
5. Checks
6. Common failures

## 1. Proxy normals for the face (`scripts/normal_transfer.py`)

Anime faces use 2–3 designed shadow shapes. Real topology (nose, cheeks, lips) scatters the terminator, so shade the face with normals copied from a simple shape and keep the geometry for the silhouette. `scripts/normal_transfer.py` builds and measures this (`--target Head --proxy ELLIPSOID --vgroup face_mask --bone head [--fit-group head_fit --inflate 1.0 --pose-bone jaw --pose-deg 20 --apply --measure-only]`):
1. Vertex group `face_mask`: 1 on the face, a 2–4 cm blend at hairline/jaw, 0 on neck and ears.
2. Smooth ellipsoid proxy fitted to the head (`NRMPROXY_<target>`, hidden from render, camera and shadow), **parented to the head bone**.
3. Data Transfer: Face Corner Data → Custom Normals, Nearest Face Interpolated, Object Transform on, mask = group, Replace 1.0.
4. Stack **Armature → Data Transfer → Subdivision (`use_custom_normals`) → Solidify outline** (`--place AFTER_DEFORM`). Shape keys evaluate before modifiers, so expressions don't bend the normals.

Measured on a noisy head with head and jaw bones (1,468 full-weight corners inside, 3,196 outside):

| Case | Inside vs proxy p95 / max ° | Outside max ° | Reported |
|---|---|---|---|
| correct stack: rest / shape key on / jaw 25° / head 30° | 0.027 / 0.16; 0.025 / 0.04; 0.024 / 0.03; 0.025 / 0.19 | 0.0 | pass |
| Data Transfer **before** Armature, jaw 25° | 4.13 / 16.4 | 0.0 | `deform_after_transfer`, `posed_inside_deviation` |
| no mask / misspelled mask | whole mesh overwritten | — | `no_mask`, `mask_missing` |
| proxy not parented | 0.024 (stale proxy invisible to the metric) | 0.0 | `proxy_not_following_rig` |
| Normal Edit Radial vs ellipsoid / vs sphere | 15.8 / 16.6; 0.70 / 0.88 | 0.0 | Radial gives **sphere** normals |
| modifier applied | 0.026 | 0.0 | pass |

- 5.x stores custom normals in the `custom_normal` corner attribute (INT16_2D). No Auto Smooth needed (4.1+). Flat-shaded faces still showed custom normals, but Shade Flat / Smooth by Angle / Weighted Normal run later reset them. Applying the Data Transfer kept shape keys in 5.2, but applied normals ride later deformation, so keep the modifier live on rigged heads.
- Topology-changing modifiers after the transfer (Subdivision, Mirror) are muted while measuring; anything topology-changing before it makes the per-corner comparison impossible (`topology_changed`).

## 2. Face shadow map, SDF (`scripts/face_sdf.py`)

`scripts/face_sdf.py` builds and gates it. The map is a grayscale threshold texture in face-UV space. Each texel stores the light-angle value at which it enters shadow, painted for light on the **+U** side. Shader math (engine-agnostic, no light data needed):

```
blender -b char.blend --python scripts/face_sdf.py -- --face-mesh Head --light Sun --head Rig --bone head
    --mask-attr face_mask [--uv-map FaceUV --map SYNTHETIC|path.png|path.exr --u-axis X --forward-axis Z
    --mapping COS|ANGLE --assign-faces MASK|ALL|NONE --material MAT_Face
    --lit-color R G B --shadow-color R G B --outside-color R G B
    --check NUMERIC|BLENDER_EEVEE|CYCLES|"" --steps 24 --measure-only --scratch DIR --save out.blend]
```

| Step | Nodes | Note |
|---|---|---|
| L, U, F vectors | 3 Combine XYZ, 9 drivers `m` / `-m` on `matrix_world[col][i]` | light col 2; head U/forward cols; bone → Empty `FSDFAXES_*` with Copy Transforms |
| dLU, dLF | Vector Math Dot | projection onto the head's U/forward plane |
| flip | Math Less Than (dLU, 0) | u' = u + flip·(1 − 2u) |
| threshold t | COS: `(1 − cos a)/2`, ANGLE: `a/π`, a = atan2(\|dLU\|, dLF) | COS equals the common game formula `step((−FdotL+1)/2, map)` |
| lit | Math Greater Than (map(u', v), t) | Mix shadow/lit (`FSDF_FaceColor`), then Mix outside/face by the mask attribute (`FSDF_Masked`) |

- Axes are head-local: U points toward map U=1, F is where the face looks. Object facing −Y: U `X`, F `-Y`. Vertical bone with roll 0: U `X`, F `Z`, because bone local Z points to world −Y. All 9 drivers were `is_simple_expression`, so no auto-exec is needed.
- Masks shaders can read: copy the face vertex group into a float point attribute (`face_mask`) and read it with an Attribute node. `--mask-attr` accepts a float/int/bool/colour attribute on the POINT, CORNER or FACE domain, or a vertex group.
- **Material slot and faces**: `--assign-faces` (default `MASK`) points the face polygons at the new material slot: `MASK` = polygons whose corners' mask value averages > 0.5 (without a usable `--mask-attr` it degrades to `ALL`, as the shader then treats the whole mesh as face); `ALL` = every polygon; `NONE` = slot appended only, `material_index` untouched. The build dict reports `faces_assigned` / `faces_total` / `assign_faces` (effective mode).
- **Colours**: `--lit-color / --shadow-color / --outside-color R G B` set the `FSDF_FaceColor` and `FSDF_Masked` Mix inputs (linear RGB, alpha 1); defaults lit (1, 0.86, 0.8), shadow (0.72, 0.52, 0.52), outside (0.9, 0.75, 0.7). To keep toon-band shading on the neck and ears outside the mask, feed the body's toon shader colour (`stylized-npr.md` §3 ramp output) into the `FSDF_Masked` Mix **A** input (outside) instead of a flat colour `[unverified]`.
- Authoring: draw 5–9 binary lit masks for light at 0…180°. `masks_to_threshold()` SDF-interpolates them. On a synthetic map, 9 masks rebuilt it with MAE 0.013 in the transition band, where a stair-step union gave 0.062. Two swapped masks reported 2,218 `violations` (lit texels must shrink as the angle grows). Use float/16-bit maps; 8-bit gives 256 threshold steps.
- Face UV must be a symmetric front projection with u = 0.5 on the nose line, or the flipped half won't match.
- Light straight above/below the head (|dLU|, |dLF| ≈ 0) gives t = 0.5; one directional light; cast shadows (hair on face) are not handled.
- **Render checks**: run `--check BLENDER_EEVEE|CYCLES` on a **saved copy** of the .blend, not the working file; the checks restore the scene's render settings afterwards and put temporary renders in `--scratch DIR` (default system temp; files deleted again). `--check NUMERIC` mirrors the node math on the evaluated mesh from the driver-written socket values; renders verify the nodes. `--check ""` builds only (PowerShell 5.1 drops a bare `""`: write `--check '""'`).

Measured, `orbit_check` (sphere head, front-hemisphere mask, synthetic map; lit share of face vs light azimuth):

| Case | Mode | front / back | worst rise | max \|L−R\| | Reported |
|---|---|---|---|---|---|
| clean COS (ANGLE same) | NUMERIC 24 steps / EEVEE 12 / Cycles 12 | 1.0 / 0.0 all | 0.0 | 0.023 / 0.0002 / 0.0014 | pass; 90° = 0.52 / 0.51 / 0.51 |
| bone rig: rest / object 40° + bone 30° turn | NUMERIC | 1.0 / 0.0 | 0.0 | 0.023 | pass; rows identical (Δ 0.0) |
| U driver `-m` (inverted axis) | NUMERIC | 1.0 / 0.0 | 0.0 | 0.023 | `wrong_side` (18 of 24 azimuths) |
| light path `matrix_world[i][2]` (row) | NUMERIC | 0.0 / 0.0 | 0.0 | 0.0 | `front_not_lit` (row 2 ignores azimuth) |
| flip link removed | NUMERIC / EEVEE | 1.0 / 0.0 | 0.0 | 0.023 / 0.0 | `graph_modified` / + `wrong_side` at −120…−60° |
| forward axis `Y` instead of `-Y` | NUMERIC | 0.0 / 1.0 | 0.111 | 0.023 | `not_monotonic`, `front_not_lit`, `back_not_shadowed` |
| drivers read the rig object, not the bone | NUMERIC | 0.50 / 0.53 | 0.367 | 0.343 | all five gates |

A missing flip keeps the lit **share** correct and only moves it to the wrong half. Share-only checks miss it; check the lit centroid side.

## 3. Hair angel ring

`face_sdf.py --hair-mesh Hair --ring-coord UV|OBJECT_Z [--uv-map HairUV --ring-center 0.7 --ring-width 0.06 --check BLENDER_EEVEE]` builds the node group `NPR_AngelRing`. h = hair UV V along the locks, or object Z normalized to the bbox. band = `|h + ViewShift·Facing − Center| < Width/2` (+ Softness ramp), × `Facing < Cutoff` (silhouette cut), with optional noise jitter of Center (`Breakup`) for clumps. Defaults: Center 0.7, Width 0.06, View Shift 0.03, Cutoff 0.8. `ring_check` renders 3 views (az/el 0/10, 60/30, 120/−15) with a debug emission (R ring, G object Z) and measures ring-pixel Z. Hair sphere, 0.24 m tall:

| Case | Engine | Z median per view (m) | p10–p90 width | coverage | Reported |
|---|---|---|---|---|---|
| OBJECT_Z center 0.7 | EEVEE / Cycles | 0.046 0.047 0.045 (drift 0.7 % / 0.6 % of height) | 0.012 | 0.94–1.0 | pass |
| UV V center 0.75 | EEVEE / Cycles | 0.082 0.083 0.080 (1.1 % / 1.2 %) | 0.011 | 0.90–1.0 | pass |
| band on Window (screen) Y | EEVEE | 0.069 0.094 0.031 (26 %) | 0.018–0.031 | 0.91–1.0 | `ring_drifts` |
| Layer Weight Facing as the band coordinate | EEVEE | 0.008 0.022 −0.011 (13.5 %) | 0.19–0.21 | 0.96 | `ring_drifts`, `ring_too_wide` |

For real cards/strands, lay out hair UVs root→tip on V with the same V range per lock. Otherwise the band staggers, which is fine as clumping but not as a ring. Hair representation and scalp checks: `character-modeling.md` §4.

## 4. Head proportions and topology (anime)

Drawing-guide proportions `[sourced: 2D anime tutorials; 3D values unverified]`:

| Feature | Placement |
|---|---|
| Eye line | ~½ of total head height (crown to chin) |
| Eye spacing | ~1 eye width between the eyes, ~1 eye width from each eye to the head side (front view) |
| Nose tip | ~halfway between eye line and chin |
| Mouth | ~⅓ of the nose-to-chin distance below the nose |
| Eye height | 1.2–1.6× eye width for "large-eye" styles `[unverified]` |

Topology `[unverified: common practice, not measured]`:
- Eyes: 3–4 concentric loops (lid rim 12–16 edges); the eye is a separate emission mesh, out of Line Art and `face_mask`.
- Mouth: 3–4 loops, then a mouth bag continuing from the lip loop. Give it mask 0 and a dark unlit material, or the SDF shadow draws inside. Teeth and tongue are separate.
- Hairline: one loop where `face_mask` blends over 2–4 cm; cut the face UV island there and at jaw/ears.
- Stay symmetric (Mirror, UV mirror U) until the face UV is projected. Game heads in this style: 1.5k–4k tris.
- **Hair shadow on face**: real shadows from hair, or a shadow-only offset duplicate. `Object.light_linking` exists in 5.2 for restricting receivers/blockers `[unverified: effect not tested]`.
- **Per-face outlines**: hull thickness group (0 on lips/eyes, thicker on jaw silhouette), a skin-tinted hull material slot, `obj.lineart.usage = 'EXCLUDE'` on texture-drawn eyes/brows (`outlines-and-line-art.md` §5).
- Blinks and visemes on this head: `shape-keys-and-visemes.md`.

## 5. Checks

Orbit the key light 360° and review at final resolution and 128 px thumbnail (`stylized-npr.md` §7); turntables via `scripts/shot_setup.py --turntable`.

| Gate | Tool | Pass |
|---|---|---|
| Proxy normals | `normal_transfer.py` (`--pose-bone jaw` re-measures posed) | inside p95 ≤ `--tol-in` 2.0°, outside max ≤ `--tol-out` 0.5°; no `no_mask`, `mask_missing`, `mask_empty`, `deform_after_transfer`, `proxy_not_following_rig`, `flat_faces_in_mask`, `topology_changed`, `transfer_disabled`, `posed_*` |
| Face shadow | `face_sdf.py` `orbit_check` (`--steps` 24 azimuths, 0 = front) | lit share monotonic front → back (tol 0.02), front ≥ 0.9, back ≤ 0.1, lit centroid on the light's side, \|frac(a) − frac(−a)\| ≤ 0.05; no `drivers_invalid`, `not_monotonic`, `front_not_lit`, `back_not_shadowed`, `wrong_side`, `asymmetric` |
| Angel ring | `face_sdf.py` `ring_check` (3 views) | median Z spread across views ≤ 4 % of hair height, p10–p90 width ≤ 15 %, column coverage ≥ 0.5; no `ring_missing`, `ring_drifts`, `ring_too_wide`, `ring_broken` |
| Look | orbit render, 2–3 shadow shapes | shadow steps through designed shapes, none inside the mouth bag, ring stays a band while the camera moves |

## 6. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Blotchy face shadow | shading follows topology | proxy normals in a face mask (§1) |
| Face shading breaks when the jaw opens | Data Transfer before Armature | Armature → Data Transfer |
| Face shading slides on head turn | proxy not parented to head bone | parent proxy to the bone |
| Neck/ears lose shading | no mask or misspelled group (field silently empty) | mask with blend; `no_mask` / `mask_missing` |
| Neck/ears flat while the face has bands | `FSDF_Masked` outside input is a flat colour | feed the body toon colour into Mix A (§2) `[unverified]` |
| Long head shades like a ball | Normal Edit Radial | Data Transfer from an ellipsoid |
| Custom normals reset | later Shade Flat/Smooth by Angle/Weighted Normal | redo the transfer last; keep it live |
| Face shadow on the side away from the light | U driver sign/axis inverted, or flip missing | fix `--u-axis`; keep the Less Than flip; `wrong_side` (§2) |
| Face shadow ignores light azimuth | light driver reads a row `matrix_world[i][2]` | column path `[2][i]`; `front_not_lit` |
| Face fully shadowed when lit from the front | forward axis sign wrong | `--forward-axis`; bone roll 0 → `Z` |
| Face shadow ignores head turns | drivers read the rig object, not the bone | axes Empty with Copy Transforms to the bone |
| Face material on the wrong polygons | `--assign-faces MASK` degraded to `ALL` (no usable mask attribute) | pass `--mask-attr`; check `faces_assigned` / `faces_total` |
| Shadow halves don't match left/right | asymmetric face UV or map painted for the wrong side | symmetric front projection, map lit from +U |
| Shadow edge staircases | 8-bit map or few masks | float map; SDF-interpolate 5–9 masks |
| Angel ring slides with the camera | band on Window/screen coordinates | UV V or object Z; `ring_drifts` |
| Ring is a rim/blob, not a band | Fresnel/Facing used as the band coordinate | Facing only as a silhouette cut; `ring_too_wide` |
| Shadow drawn inside the mouth | mouth bag inside `face_mask` | mask 0 + dark unlit material on the bag |
| Working file's render settings changed after a check | check run on the working .blend | run `--check` on a saved copy (§2) |
