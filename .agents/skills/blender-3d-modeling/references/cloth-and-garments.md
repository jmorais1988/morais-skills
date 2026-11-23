# Cloth and Garments

Read this when a garment, drape, flag, curtain, cushion or sewn pattern is simulated with the Cloth modifier — on a prop or on a rigged character — and must be gated with `scripts/sim_check.py --checks setup,cloth`. Shared rules (real scale, cache ranges, baking, Alembic export) are in `simulation.md` §1–2; tearing and node-based cloth are in `simulation.md` §3.

## Contents
1. Mesh and modifier order
2. Presets and settings
3. Collisions, pinning, pressure, sewing, apply
4. Collider proxy recipe
5. Garments on rigged characters
6. Cloth on rigid bodies
7. Gates (`scripts/sim_check.py --checks setup,cloth`)
8. Common failures

## 1. Mesh and modifier order

**Mesh.** Even quads of 1–3 cm for garments or 3–6 cm for drapes. Simulate the cage, never the subdivided or thickened mesh. No loose or doubled geometry (`mesh-repair.md`).

**Stack — one order, always:** (Mask) → **Armature → Cloth → (Corrective Smooth) → Subdivision → Solidify**.

| Modifier | Position | Why |
|---|---|---|
| Mask (optional) | first | hides skin fully covered in every pose |
| Armature | before Cloth | an Armature **after** Cloth is ignored by the sim |
| Cloth | after every deform modifier | simulates the cage vertices only |
| Corrective Smooth (optional) | after Cloth | smooths the result without feeding back into the sim |
| Subdivision | after Cloth | before it, the solver would work on the multiplied vertices |
| Solidify | **after Cloth**, last | before it, Solidify multiplies the simulated vertices; thickness belongs on the result, not in the sim |

`scripts/sim_check.py --checks setup` **warns** on Solidify, Subdivision, Multires or Remesh before Cloth and **errors** on an Armature (or any other deform modifier except Smooth, Corrective Smooth and Nodes) after Cloth. On colliders it errors on any deform modifier after Collision (colliders use the stack **up to** their Collision modifier) and warns when `collision.use` is off.

## 2. Presets and settings

**Bundled presets** (Blender install folder `<version>/scripts/presets/cloth/`, not this skill; stiffness = tension = compression = shear):

| Preset | quality | mass kg | stiffness | bending | damping | Use |
|---|---|---|---|---|---|---|
| Silk | 5 | 0.15 | 5 | 0.05 | 0 | scarves, lining, sheer curtains |
| Cotton (= defaults) | 5 | 0.3 | 15 | 0.5 | 5 | shirts, sheets, tablecloths |
| Wool `[unverified]` | ~10 | ~0.6 | ~30 | ~6 | ~20 | sweaters, coats, blankets — not a bundled preset; interpolated between Cotton and Denim |
| Denim | 12 | 1.0 | 40 | 10 | 25 | jeans, canvas, tarps |
| Leather | 15 | 0.4 | 80 | 150 | 25 | jackets, heavy upholstery |
| Rubber | 7 | 3.0 | 15 | 25 | 25 | inflatables, mats |

Other defaults: `air_damping` 1, `collision_settings.distance_min` 0.015 m, `self_distance_min` 0.015, `collision_quality` 2. Stiff bending at low quality explodes, so raise quality with stiffness. Substeps before stiffness: raise `quality`/`collision_quality` before touching material values (`simulation.md` §1). Column mapping: stiffness = `tension_stiffness` = `compression_stiffness` = `shear_stiffness`; damping = the three matching `*_damping` fields (`bending_damping` keeps its 0.5 default); bending = `bending_stiffness`.

## 3. Collisions, pinning, pressure, sewing, apply

- **Collisions.** The collider gets a Collision modifier. `collision.thickness_outer` plus the cloth's `distance_min` is the visible gap, so keep it below ½ the cloth edge length. Use `collision_quality` 3–5 for fast or thin colliders. Colliders use the stack **up to** their Collision modifier, so a deforming body needs Armature → Collision. Turn on `use_self_collision` only where folds stack (skirts, capes, towels), with `self_distance_min` about 0.5–0.75 × edge length and `vertex_group_self_collisions` to limit it.
- **Pinning.** `settings.vertex_group_mass` is the pin group (weight 1 = fixed); `pin_stiffness` makes pins springy. Pin waistbands, collars, curtain rails and flag edges.
- **Pressure (cushions, pillows).** Closed mesh, `use_pressure=True`, `uniform_pressure_force` 2–10 (soft) or 20+ (balloon), and `shrink_min` < 0 to inflate the rest size. Bake about 30 frames on a collider, then apply.
- **Sewing.** Flat panels plus loose edges joining seam borders, with `use_sewing_springs=True` and `sewing_force_max` 5–50. Gravity 0 while seams close (10–30 frames), then keyframe gravity on.
- **Apply at rest.** Pick a frame where `scripts/sim_check.py` reports end speed ≤ 1 mm/frame, then `object.modifier_apply(modifier="Cloth")`.

## 4. Collider proxy recipe

The collider is a **proxy, not the render body**: the render mesh is too dense, has open armpits and finger gaps for cloth to snag in, and its stack rarely ends in Collision.

1. **Duplicate** the render body; mesh and vertex groups come along.
2. **Decimate** the copy to 2–8k tris (Decimate, Collapse, `ratio` ≈ target ÷ current tris). Vertex groups survive Collapse; if they are lost, copy them back with Data Transfer (`use_vert_data=True`, `data_types_verts={'VGROUP_WEIGHTS'}`, `vert_mapping='POLYINTERP_NEAREST'`), then apply it.
3. **Fill the gaps**: mitten hands (delete the finger loops, bridge the stumps), bridged armpits, closed mouth and eye sockets.
4. **Close it.** The proxy must be a closed manifold with outward normals. `scripts/sim_check.py` runs its depth test (nearest-face normal sign **and** ray parity must both say inside) and its poke-through test **only on closed colliders**; an open collider counts only points behind a face within 10 cm and gets no poke test, so an open proxy hides penetration. Prove closure with `scripts/mesh_report.py`: `boundary_edges` 0, `non_manifold_edges` 0, no inward-facing flag. Prove closure with `scripts/mesh_report.py` (0 boundary / non-manifold edges); prove normal consistency with `scripts/mesh_repair.py analyze` — mesh_report's inward-facing heuristic is centroid-based and says nothing on a non-convex body.
5. **Stack:** Armature (same armature and weights as the body) → Collision, nothing after Collision.
6. **Settings:** `collision.thickness_outer` 5–10 mm, `hide_render = True` (keep it visible in the viewport while tuning).

Gate against both the proxy and the render body (§7): a passing proxy can still hide penetration of the real body.

## 5. Garments on rigged characters

**Stack:** (Mask) → Armature → Cloth → Corrective Smooth → Subdivision → Solidify (§1). **Collider:** the proxy from §4.

### 5.1 Pre-roll

Frame 1 must be non-intersecting, so the sim starts from the pose the garment was modelled in. Key the rest pose 10–25 frames before the action and blend into the first real pose. Bake from the pre-roll start (scene start = cloth `point_cache.frame_start` = pre-roll start).

**Pre-roll from rest for an existing action** (the clip starts mid-motion):
1. Clear the pose (`bpy.ops.pose.transforms_clear()` on all bones, or `pb.matrix_basis = Matrix.Identity(4)`) so frames before the strip evaluate as rest.
2. Put the action in an NLA strip that **starts after the pre-roll** — `tr = ad.nla_tracks.new(); st = tr.strips.new(name, pre_roll_end, act)` — with `st.extrapolation = 'NOTHING'` (so the strip does not hold its first pose back over the pre-roll) and `st.blend_in` = 10–25 frames (the rig eases from rest into the first pose). Set `st.action_slot` when the action has several slots (`animation.md` §1 for slots, §3 for strips).
3. Set scene start and cloth cache start to the pre-roll start, then bake.
- In-place runs and walks (no root motion) never move through the air, so cloth does not trail: add a Wind force field (`object.effector_add(type='WIND')`) against the run direction and tune its strength until the cloth flies back as it would at that speed `[unverified]`.

### 5.2 Construction workflow

1. Flat 2D pattern panels (front, back, sleeves) at real measurements, about 1.5–2 cm quads.
2. Place them around the A-pose and add sewing edges between matching borders.
3. Sew with gravity off, then gravity on until settled on the proxy (§3).
4. Apply, clean, and retopologize for deformation (`topology.md`). Bake fold normals from the sim mesh (`bake_maps.py`).
5. Bind: Data Transfer vertex groups from the body (nearest face interpolated) + Armature, or `object.surfacedeform_bind` in rest pose for tight layers (`organic-modeling.md` §3; layer classification in `character-modeling.md` §2).
6. Sweep poses (`rig_check.py`).

### 5.3 Clipping rules

- Each layer sits at least one collision distance above the one below (skin → shirt 5–10 mm, shirt → jacket 10–15 mm).
- Mask or delete skin fully hidden in every pose.
- Tight garments (leggings, gloves) are skinned, not simulated.
- Gate with §7 against `BODY_Proxy,BODY_Render`: max depth ≤ 2 mm and 0 poke-through edges. Check against the render body too, since a passing proxy can still hide penetration of the real body.

## 6. Cloth on rigid bodies

Solvers couple one way (`simulation.md` §2.1): the rigid body moves the cloth, the cloth never shoves the rigid body — in the test the crate fell the same 650 mm under the sheet. Bullet collision shapes are **invisible to cloth**, so the rigid object also needs a **Collision modifier**. Bake rigid → cloth (`ptcache.bake_all` bakes both; same numbers as frame stepping).

Collision thickness 10 mm, sheet 1.4 m (24×24 quads) dropped onto a body that is itself falling:

| Body | Collision modifier | Max depth | Poke edges |
|---|---|---|---|
| 0.5 m crate | yes | 0 mm | 0 |
| 0.5 m crate | no | 43.7 mm (80 verts inside) | 4 |
| 0.8 × 0.8 × 0.05 m plate | yes | 0 mm | 0 |
| same plate | no | 15.2 mm | 4 |

Thin plates therefore need both a rigid body **and** a Collision modifier. Setup warns about rigid bodies without one whenever cloth is in the scene.

## 7. Gates (`scripts/sim_check.py --checks setup,cloth`)

```
blender -b garment.blend --python scripts/sim_check.py -- --checks setup,cloth --cloth SHIRT_ \
    --colliders BODY_Proxy,BODY_Render --frames 1:120:4 --tol-mm 2 --settle-mm 0
```

- `--checks setup,cloth` only: setup catches the stack and cache errors, and no rigid/fluid noise enters the report.
- `--cloth <garment>` and `--colliders <proxy>,<render body>`: the render body has no Collision modifier, so it is not auto-discovered; name it or the gate cannot see real-body penetration. An open render body (armpits, mouth bag) only gets the depth-behind-a-face test, never the poke-through test — the closed proxy carries the full gate; the render body is a second opinion on depth.
- `--frames start:end:step`: the whole shot, sampled every `step` frames plus the last two.
- `--tol-mm 2 --settle-mm 0`: **settle is only for shots that end at rest.** The default `--settle-mm 1` fails any garment still moving on the last frame (`pass_settled` fails by design), and a 2.4 m drape over a sphere still slid 2 mm/frame at frame 150. For a drape that must come to rest, use `--settle-mm 1` and extend the range until it passes.

| Check | Measures | Pass |
|---|---|---|
| setup (cloth items) | unapplied scale, deform modifier after Cloth (error), generator before Cloth (warning), deform after Collision (error), `collision.use` off, cloth cache start/end vs scene range, rigid bodies without Collision while cloth is present | no errors |
| cloth | per sampled frame: max vertex depth inside closed colliders (mm), collider edges poking through cloth triangles, edge stretch vs start, end speed | depth ≤ `--tol-mm`, 0 pokes, stretch ≤ 1.5 (`--stretch-max`), speed ≤ `--settle-mm` (0 = report only) |

Synthetic tests (each clean case passes, each planted defect fails):

| Scene | Clean | Planted defect |
|---|---|---|
| 2.4 m sheet on cube + sphere | depth 0 mm, 0 pokes, stretch 1.30 | collision off: 327 mm, 36 poke edges, 18 bad frames |
| 1 m sheet dropped 30 cm | 0.025 mm/frame at frame 40 | range ends at frame 8: 58 mm/frame |
| Cloth on falling crate / plate | Collision on: 0 mm | Collision off: 43.7 / 15.2 mm, 4 pokes + setup warning |

## 8. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Cloth falls through collider | thin/fast collider, low collision quality | `collision_quality` 3–5, `thickness_outer` 5–10 mm, thicker proxy |
| Cloth floats above body | `distance_min` + `thickness_outer` too large | ~5 mm total for tight garments |
| Garment ignores character | Armature below Cloth, or Collision above Armature | Armature → Cloth; Armature → Collision (§1) |
| Cloth explodes at frame 1 | starts intersecting, stiff at low quality | pre-roll from rest (§5.1); raise quality; check stretch ratio |
| Cloth passes through a rigid body or thin plate | rigid body has no Collision modifier | add Collision; bake rigid → cloth (§6) |
| Depth reads 0 mm but the body shows through | proxy is open (no parity or poke test), or gate ran against the proxy only | close the proxy (§4); add the render body to `--colliders` |
| Gate fails only on `pass_settled` | shot ends while the garment still moves | `--settle-mm 0` (§7) |
| Sim slow, setup warns "before Cloth multiplies sim vertices" | Solidify or Subdivision above Cloth | move them below Cloth (§1) |
