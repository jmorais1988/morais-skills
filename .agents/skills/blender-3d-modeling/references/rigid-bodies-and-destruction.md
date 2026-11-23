# Rigid Bodies and Destruction

Read this for stacks, dominoes, debris, launched projectiles and walls that shatter or stay glued — everything Bullet solves through `scene.rigidbody_world` — and for gating it with `scripts/sim_check.py --checks setup,rigid`. Shared rules (real scale, cache ranges, `ptcache.bake_all`, `matrix_world` results, rigid → keyframe export) are in `simulation.md` §1–2.

## Contents
1. World and per-body settings
2. Ground, dominoes, stacks
3. Constraints
4. Destruction
5. Launching a projectile
6. Breakable walls: count breaks, not movement
7. Rigid bodies driving cloth and fluids
8. Gates (`scripts/sim_check.py --checks setup,rigid`)
9. Common failures

## 1. World and per-body settings

**World** (`scene.rigidbody_world`) defaults: `substeps_per_frame` 10, `solver_iterations` 10, cache 1–250 whatever the scene range is (set `point_cache.frame_end` = scene end or bodies freeze). Stacks and small fast pieces need 20–60 substeps and 20–50 iterations. Substeps before mass or friction tweaks: tunnelling, jitter and explosions are time-step problems (`simulation.md` §1).

| Per body (`o.rigid_body`, add via `rigidbody.object_add()`) | Default | Rule |
|---|---|---|
| `type` | ACTIVE | PASSIVE for set pieces; `kinematic=True` = animated pusher |
| `collision_shape` | CONVEX_HULL | BOX/SPHERE/CAPSULE/CYLINDER for primitives; CONVEX_HULL for rocks; MESH only for passive concave sets (setup warns on ACTIVE + MESH: slow, jittery); COMPOUND from children |
| `mass` | 1 kg | keep mass ratios under ~100:1 between touching bodies |
| `friction` / `restitution` | 0.5 / 0 | ice 0.05; rubber bounce 0.6–0.8 |
| `collision_margin` | 0.04 m | ≤ 10 % of smallest dimension (setup warns) |
| `use_deactivation` / `use_start_deactivated` | off | sleeping piles that wake on impact |

Results live in `matrix_world`, not `location`; `object.visual_transform_apply` freezes a frame, and the keyframe route for export is in `simulation.md` §2.

## 2. Ground, dominoes, stacks

- **Ground: never a zero-thickness plane.** 6 unpushed dominoes (5×20×40 cm) on a plane tipped over by themselves: 2 of 6 with CONVEX_HULL, 6 of 6 with MESH. On a 20 cm slab (scaled cube, BOX) none moved. Setup warns on flat passive bodies.
- **Dominoes.** Height:thickness 5–8:1, spacing 0.5–0.7 × height, BOX shape, margin 1–2 mm, substeps ≥ 20. Push with an initial 15–20° tilt or a kinematic pusher. Spacing ≥ height breaks the chain.
- **Stacking.** Start touching, never overlapping (overlaps explode). Use 30+ substeps and iterations, deactivation on, and pre-settle 20–40 frames → `visual_transform_apply` → real sim.

## 3. Constraints

`rigidbody.connect(con_type, pivot_type, connection_pattern)` with `con_type` FIXED/POINT/HINGE/SLIDER/PISTON/GENERIC/GENERIC_SPRING/MOTOR, `pivot_type` CENTER/ACTIVE/SELECTED, and `connection_pattern` SELECTED_TO_ACTIVE or CHAIN_DISTANCE. It creates Empties with `rigid_body_constraint` (`use_breaking`, `breaking_threshold`, `disable_collisions`, limits, springs, motors). Both `object1` and `object2` must be in the rigid body world collection; setup reports a constraint with a missing or outside object as an error (Bullet ignores it).

## 4. Destruction

| Approach | When | How |
|---|---|---|
| Cell Fracture extension | Voronoi shards of one mesh (glass, rock) | Get Extensions → "Cell Fracture" (v0.2.1, "Blender 4.2 LTS and newer", *limited support*; not bundled; operator `object.add_fracture_cell_objects` `[unverified in 5.2]`). 20–250 points, interior material, recursion near impact |
| Bricks as separate bodies | Masonry, crates, modelled pieces | Array → `mesh.separate(type='LOOSE')` → origins to geometry → BOX shape |
| Pre-broken + glued | Wall that stands until hit | pieces + FIXED constraints between neighbours (`rigidbody.connect(con_type='FIXED', connection_pattern='CHAIN_DISTANCE')` only chains), `use_breaking=True`, sweep `breaking_threshold` from ~0.5 × piece mass upward and count breaks (§6) |
| `object.quick_explode` | Stylised blow-apart | particle Explode modifier, no real physics |

- **Inner faces.** Give fracture faces their own material (raw concrete, broken grain). Cell Fracture has an interior material index; for hand-cut pieces, assign the slot before simulating.
- **Trigger on impact.** Sleeping bodies (`use_deactivation` + `use_start_deactivated`) wait for a hit. In the test a sleeping crate stayed at 0 mm until the chain struck it, then moved 111 mm. Timed breaks: animate `kinematic` on → off, or constraint `enabled`.
- Hundreds of convex shards are fine; thousands need deactivation, fewer substeps, then bake to keyframes for export (`simulation.md` §2).

## 5. Launching a projectile

Rigid bodies have no initial-velocity field. Key the motion while kinematic, then hand off:
```python
ball.rigid_body.kinematic = True;  ball.keyframe_insert("rigid_body.kinematic", frame=6)
ball.rigid_body.kinematic = False; ball.keyframe_insert("rigid_body.kinematic", frame=7)
# location keys frames 1->6 with LINEAR interpolation (auto-clamped Bezier eases to zero speed at the last key)
```
Measured: an 8 kg ball keyed 1 m over 5 frames (4.8 m/s at 24 fps) left the handoff at 4.89 m/s. With the same keys on an ACTIVE body and no kinematic key, the keys were ignored: the ball moved 0.2 m and stopped. `scripts/sim_check.py --checks setup` warns about this. Launch speed = keyed distance per frame × fps.

## 6. Breakable walls: count breaks, not movement

5.2 has no "is broken" property (`RigidBodyConstraint` only has `enabled`, `use_breaking`, `breaking_threshold`). `scripts/sim_check.py --expect-broken GLUE_` calls a constraint broken when object2 drifts more than 10 mm or 5° relative to object1 (`--break-mm`, `--break-deg`). Test: 3×3 wall of 2 kg bricks (40×20×20 cm), 12 FIXED neighbour constraints, the launched ball of §5 hitting it, 20 substeps.

| `breaking_threshold` | Broken | First break | What happened |
|---|---|---|---|
| 1 | 6 / 12 | frame 16 | centre column punched out 1.38 m, the rest moved 25–35 mm |
| 3, 8, 20 | 0 | — | wall toppled as **one block** (all 9 bricks moved 0.45–0.94 m) |

All 9 bricks "moved" in both rows, so move counts can't tell glued from shattered. The threshold is an impulse and depends on impact energy and substeps `[unverified: substep scaling]`, so sweep it per shot.

## 7. Rigid bodies driving cloth and fluids

Coupling is one way (`simulation.md` §2.1): the rigid world is baked first and later solvers read its transforms; nothing pushes back on the bodies.

| Downstream | The rigid object needs | Bake order |
|---|---|---|
| Cloth | a **Collision modifier** (Bullet shapes are invisible to cloth; thin plates need it too — `cloth-and-garments.md` §6) | rigid → cloth (`ptcache.bake_all` bakes both) |
| Smoke / liquid | a Fluid FLOW or EFFECTOR modifier (`fluids-and-smoke.md` §6) | rigid → `fluid.bake_all`; sourcing from an unbaked rigid world works while stepping, but bake rigid first for farm renders |

Setup warns about rigid bodies without a Collision modifier whenever cloth is in the scene.

## 8. Gates (`scripts/sim_check.py --checks setup,rigid`)

```
blender -b dominoes.blend --python scripts/sim_check.py -- --bake --checks setup,rigid \
    --expect-toppled DOM_ --expect-still sleeping
blender -b wall.blend --python scripts/sim_check.py -- --checks setup,rigid --rigid BRICK_ \
    --expect-broken GLUE_ --broken-min 1
```

| Check | Measures | Pass |
|---|---|---|
| setup (rigid items) | unapplied scale, world cache end < scene end, margin > 10 % of smallest dimension, zero-thickness PASSIVE body, ACTIVE + MESH shape, transform keys without a `rigid_body.kinematic` key, constraints outside the world (error), no Collision modifier while cloth is present | no errors |
| rigid | move/rotation/tilt per body (`--move-mm 5`, `--rot-deg 2`), still moving at end, fell below passive | expected toppled (world tilt of the local Z axis vs the start frame > 45°, `--tilt-deg`), expected-still (`sleeping` or prefixes) unmoved, none fell through |
| rigid `--expect-broken` | constraints whose object2 drifted > 10 mm / 5° relative to object1; first break frame; constraints outside the world (setup error) | ≥ `--broken-min` matched constraints broken |

Synthetic tests (each clean case passes, each planted defect fails):

| Scene | Clean | Planted defect |
|---|---|---|
| 10 dominoes, 0.25 m spacing | 10/10 toppled, sleeping crate 0 mm | 0.5 m spacing: 9 standing from `DOM_01`; crate in path moved 111 mm |
| 6 unpushed dominoes | slab: 0 moved | plane: 2 toppled + warning |
| 3×3 glued wall + launched ball | threshold 1: 6/12 broken, first frame 16 | threshold 3: 0 broken (fail); no kinematic key: setup warning, 0 moved |

## 9. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Thin rigid bodies tip on their own | zero-thickness passive plane | slab ground with BOX shape (§2) |
| Gaps between stacked bodies | margin too large for size | margin ≤ 10 % smallest dimension |
| Domino chain stops | spacing ≥ height, low substeps | spacing 0.5–0.7 × height, substeps ≥ 20 |
| Stack explodes at frame 1 | pieces overlap at the start | start touching; pre-settle 20–40 frames → `visual_transform_apply` (§2) |
| Bodies freeze mid-shot | world cache ends at 250 < scene end | `rigidbody_world.point_cache.frame_end` = scene end |
| Projectile drops instead of flying | transform keys on an ACTIVE body with no kinematic key | key `rigid_body.kinematic` True → False, LINEAR location keys (§5) |
| Glued wall topples as one block | `breaking_threshold` too high for the impact | sweep lower; gate with `--expect-broken` (§6) |
| Constraint does nothing | object1/object2 missing or outside the rigid body world | add both bodies to the world collection (setup error, §3) |
| Cloth passes through a rigid body | no Collision modifier on it | add Collision; bake rigid → cloth (§7) |
| Keyframe bake fails in script | `bake_to_keyframes` needs UI context | manual `matrix_world` → keyframe loop (`simulation.md` §2) |
