# Simulation: Setup, Baking, Solvers & Verification

Read this first for any Blender simulation: it holds the rules every solver shares (real scale, cache ranges, baking from code, export, one-way coupling) and how `scripts/sim_check.py` is invoked, then routes to `cloth-and-garments.md`, `rigid-bodies-and-destruction.md` and `fluids-and-smoke.md` for the domain recipes and gates. Simulations fail quietly — a bake finishes and the viewport looks plausible, but the cloth is 3 cm inside the body, the domino chain stopped at piece four, or the liquid drained through the floor — so set up at real scale, bake from code, then **measure** before showing a frame. API and numbers were checked headless in Blender 5.2 LTS unless marked `[unverified]`.

## Contents
1. Before any simulation
2. Baking from code, caches and export
3. Choosing a solver
4. Particles, hair, Geometry Nodes, soft body
5. Verifying results (`scripts/sim_check.py`)
6. Common failures

## 1. Before any simulation

- **Real scale, applied scale.** 1 BU = 1 m. Cloth mass is kg, rigid margins are metres, and fluid resolution counts voxels across the domain's largest side. Apply scale on cloth, colliders, rigid bodies and fluid objects. `scripts/sim_check.py --checks setup` lists unapplied scale.
- **Cache range = shot range.** Each cache has its own range: cloth `point_cache.frame_start/end`, rigid world `scene.rigidbody_world.point_cache` (defaults to 1–250 whatever the scene is), fluid `domain_settings.cache_frame_start/end`. Past the cache end the sim freezes.
- **Start from rest.** Frame 1 must be non-intersecting. Characters get 10–25 pre-roll frames from the rest pose (`cloth-and-garments.md` §5).
- **Step frames sequentially** (`frame_set(f)` for every f), or bake first. Jumping to frame 80 on an unbaked sim is unreliable.
- **Determinism.** Baked caches replay identically. Rebakes on the same build match in practice `[unverified across builds/OS]`. Farms must read the bake, not re-simulate.
- **Substeps before stiffness.** Tunnelling, jitter and explosions are time-step problems. Raise cloth `quality`/`collision_quality`, rigid `substeps_per_frame`/`solver_iterations`, fluid `timesteps_max` first.

## 2. Baking from code, caches and export

Bake every cache before command-line or farm rendering — render nodes re-simulate or render empty frames otherwise (`render-farm-and-compositing.md` §3, `scripts/render_cli.py`).

| Task | 5.2 code (verified headless) |
|---|---|
| All point caches (cloth, soft body, rigid world, particles) | `bpy.ops.ptcache.bake_all(bake=True)` / `ptcache.free_bake_all()` |
| One cache | `with bpy.context.temp_override(scene=sc, object=o, active_object=o, point_cache=mod.point_cache): bpy.ops.ptcache.bake(bake=True)` |
| Mantaflow domain | `with bpy.context.temp_override(scene=sc, object=dom, active_object=dom): bpy.ops.fluid.bake_all()` / `fluid.free_all()` |
| GN simulation zones | `mod.bake_target='DISK'; mod.bake_directory=path`, then `object.simulation_nodes_cache_bake(selected=True)` with `selected_objects=[o]` in the override |
| Everything | `bake_all()` in `scripts/sim_check.py` (or `--bake`) |

- **No auto-invalidation from Python.** After changing `cloth.settings.mass` on a baked cache, `is_baked` stayed True, `is_outdated` stayed False, and the old frames played. Always free → edit → rebake.
- **Disk cache needs a saved .blend.** An unsaved file with `use_disk_cache=True` silently baked to memory. Saved, it writes to `//blendcache_<file>/`. 5.0+: caches are always ZSTD, and LZO/LZMA caches must be rebaked.
- **GN bakes are packed into the .blend by default** (`mod.bake_target == 'PACKED'`). A per-bake `directory` alone wrote no files. Use `'DISK'` for big sims.
- **Rigid results live in `matrix_world`, not `location`.** `object.visual_transform_apply` freezes a frame.
- **Rigid → keyframes.** `rigidbody.bake_to_keyframes` fails headless (its keyframe sub-operator has no context). Instead, loop frames storing `matrix_world`, remove the rigid body, then per frame set `matrix_world` and `keyframe_insert("location")`/`("rotation_euler")`. This was verified, and the action slot was assigned.
- **Export.** Deforming results (cloth, soft body, liquid mesh) go to Alembic: `wm.alembic_export(filepath, start, end, evaluation_mode='RENDER')`, re-imported with `wm.alembic_import(set_frame_range=True)` or kept in a Mesh Sequence Cache modifier (`usd-and-alembic.md` §3). Rigid bodies go out as keyframes in FBX/glTF. Engines want vertex-animation textures or bone bakes — not yet covered by this skill; the tested routes here are Alembic, shape-key/mesh-sequence caches and rigid-body keyframes. No MDD/PC2 exporter is bundled in 5.2 (no `export_shape.*`).
- **Disk size.** A liquid at resolution 24 for 12 frames with the ALL cache used 2.7 MB. Data scales with resolution³ × frames, so resolution 128 × 250 frames reaches tens of GB. Use a local SSD path, never a synced folder.

### 2.1 Bake order for coupled effects

Blender's solvers only couple **one way**: later solvers read the earlier ones' transforms, and nothing pushes back. Cloth never shoves a rigid body; in the test the crate fell the same 650 mm under the sheet. Fluid effectors don't feel the liquid either `[unverified in test]`.

| Coupling | Needs | Bake order |
|---|---|---|
| Keys → rigid (launch) | `rigid_body.kinematic` keyed True → False (`rigid-bodies-and-destruction.md` §5) | rigid world |
| Rigid → cloth | **Collision modifier** on the rigid object (Bullet shapes are invisible to cloth; `cloth-and-garments.md` §6) | rigid → cloth (`ptcache.bake_all` bakes both; same numbers as frame stepping) |
| Rigid / keys → smoke or liquid | Fluid FLOW or EFFECTOR modifier on the moving object (`fluids-and-smoke.md` §6) | rigid → `fluid.bake_all` |
| Any upstream edit | — | free every downstream cache, rebake in order |

## 3. Choosing a solver

| Need | Use | Detail |
|---|---|---|
| Static drape for a still | Cloth modifier → bake → apply at the chosen frame | `cloth-and-garments.md` §3 |
| Local folds while sculpting | Sculpt Cloth brush / `sculpt.cloth_filter` (`sculpting.md`) | — |
| Animated garment | Cloth after Armature + body proxy collider | `cloth-and-garments.md` §4–5 |
| Tearing, custom forces, node-based cloth/hair | 5.2 **Cloth Dynamics (Experimental)** / **Hair Dynamics** (XPBD; may change next release) | below |
| Stacks, dominoes, debris | Rigid Body (Bullet) | `rigid-bodies-and-destruction.md` §1–3 |
| Glass, masonry, walls that stand until hit | Cell Fracture / separate bricks / breakable constraints | `rigid-bodies-and-destruction.md` §4, §6 |
| Water, pouring | Mantaflow liquid (FLIP/APIC) | `fluids-and-smoke.md` §1–4 |
| Smoke, fire, dust from debris | Mantaflow gas | `fluids-and-smoke.md` §5–6 |
| Scatter, custom particles, growth | Geometry Nodes + Simulation zone (`scatter_on_surface.py`) | §4 |
| Jiggle, cable sag | Soft Body, or cloth with a pin group | §4 |

**5.2 node dynamics.** Assets are in `datafiles/assets/nodes/geometry_nodes_dynamics_assets.blend`: `Cloth Dynamics (Experimental)`, `Hair Dynamics`, `Collider`, `Set Effector`, `Custom Force`, `Custom Effector`. Headless, append them with `bpy.data.libraries.load` and put the group on a `NODES` modifier. `object.modifier_add_node_group(asset_library_type='ESSENTIALS', …)` added nothing headless. Set inputs with `mod.properties.inputs.<Socket_id>.value`. The inputs are Pin Group, Stretchiness, Bendiness, Substeps, Constraint Steps, Mass, Friction, Collision Radius, Linear Damping, Gravity, Tearing (+ mode/threshold), Effectors Collection, and Effectors. Colliders carry a `Collider` modifier and **must** be in the collection plugged into Effectors Collection. Without it the cloth fell through the sphere (min z −2.11 m); with it, 0 vertices ended up inside.

## 4. Particles, hair, Geometry Nodes, soft body

- **Legacy particles** (`PARTICLE_SYSTEM`; `type` EMITTER/HAIR; `physics_type` NO/NEWTON/KEYED/BOIDS/FLUID) still exist in 5.2. Use them for sparks, rain, boids flocks and Quick Explode.
- **Hair → curves**: Hair Curves + procedural hair node assets + 5.2 Hair Dynamics (Empty Hair adds Capture Rest Geometry on the surface). Convert old hair with `curves.convert_from_particle_system` (`fauna.md` §5, `character-modeling.md` §4).
- **Prefer Geometry Nodes** for scatter, attribute-driven instancing, millions of points, and deterministic motion. Use a Simulation zone (Simulation Input/Output, `Delta Time`, 4.0+) for custom state and bake it as in §2.
- **Soft body** (`SOFT_BODY`) for jiggle: `use_goal` + `vertex_group_goal` (1 = follows animation), `goal_spring`/`goal_friction`, `pull`/`push`/`bend`. Run it on a low-poly cage driving the render mesh via Surface Deform. On dense meshes cloth with a pin group is faster and steadier.

## 5. Verifying results (`scripts/sim_check.py`)

One script gates every solver. It prints one line, `SIM_CHECK <json>`; every check returns `{"pass": bool|None, ...}` (None = not applicable / informational).

```
# headless: everything at once
blender -b scene.blend --python scripts/sim_check.py -- --bake --checks setup,cloth,rigid,fluid \
    --colliders BODY_Proxy --tol-mm 2 --settle-mm 1 --expect-toppled DOM_ --expect-still sleeping \
    --volume-loss-pct 50 --volume-gain-pct 150
# live (Blender:execute_blender_code): set before exec, then read `result`
SIM_CHECK_OPTS = {"checks": ["cloth", "rigid"], "bake": True, "expect_toppled": "DOM_"}
```

Without `SIM_CHECK_OPTS` the file only defines `run_checks`, `bake_all` and the individual check helpers.

| Flag | Meaning |
|---|---|
| `--checks setup,cloth,rigid,fluid` | which checks run; always include `setup`, and only the solvers in the shot so the report carries no noise from the others |
| `--bake` | bakes everything first (`bake_all`) |
| `--frames start:end:step` | frames are stepped one by one from start to end (so unbaked in-memory caches evaluate correctly); checks sample every `step` frames plus the last two (settling = displacement between end-1 and end) |
| `--cloth`, `--colliders`, `--rigid` | name prefixes; otherwise auto-discovery: cloth = meshes with a Cloth modifier, colliders = meshes with a Collision modifier (enabled or not) plus `--colliders`, rigid = objects in the rigid body world collection, fluids = Fluid DOMAIN modifiers |
| `--save out.blend` | keep the baked file |

**Setup lint** runs for every solver and must pass with no errors (warnings are listed):

| Check | Measures | Pass |
|---|---|---|
| setup | unapplied scale, Armature after Cloth, generator before Cloth, deform after Collision, cache end < scene end, margin > 10 %, flat passive ground, flow < 2 voxels, transform keys on an ACTIVE body without a kinematic key, rigid bodies without Collision while cloth is present, constraints outside the rigid world | no errors (warnings listed) |

Domain gates, their pass rules and the synthetic evidence behind them: cloth → `cloth-and-garments.md` §7; rigid and `--expect-broken` → `rigid-bodies-and-destruction.md` §8; fluid, `--gas-near`, `--volume-mode rise`/`--liquid-in` → `fluids-and-smoke.md` §8.

**Evidence rules.** A gate is trusted only when its clean case passes and its planted defect fails; each domain file lists those pairs. Quote the measured numbers (mm, frames, %) next to the verdict, never the verdict alone. Gate settling (`--settle-mm`) only on shots that must end at rest; `--settle-mm 0` reports end speed without gating on it.

## 6. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Settings changed, playback identical | baked cache not invalidated | free bake → rebake |
| Sim freezes mid-shot | cache range shorter than scene (rigid default 250) | set cache end = scene end |
| Disk cache on, nothing on disk | .blend unsaved → memory | save first |
| Keyframe bake fails in script | `bake_to_keyframes` needs UI context | manual matrix_world → keyframe loop (§2) |
| Node cloth ignores colliders | Collider object not in Effectors Collection | add it to that collection |
| Old caches glitch in 5.x | LZO/LZMA caches removed | delete and rebake |
| Downstream sim ignores an upstream edit | downstream cache baked before the edit | free every downstream cache, rebake in order (§2.1) |

Domain-specific failure tables: cloth `cloth-and-garments.md` §8, rigid bodies `rigid-bodies-and-destruction.md` §9, fluids and smoke `fluids-and-smoke.md` §9.
