# Fluids and Smoke

Read this for Mantaflow liquids (pouring, splashing, liquid in a glass) and gas (smoke, fire, dust trailing debris): domain sizing and resolution cost, flows and effectors, caches, rendering the grids, and gating with `scripts/sim_check.py --checks setup,fluid`. Shared rules (real scale, cache ranges, `fluid.bake_all`, disk size, Alembic export of the liquid mesh) are in `simulation.md` §1–2.

## Contents
1. Liquid domain, resolution and cost
2. Liquid method, mesh, particles, cache
3. Flows and effectors
4. Pouring into a glass
5. Smoke and fire
6. Dust and smoke from debris
7. Reading grids in scripts
8. Gates (`scripts/sim_check.py --checks setup,fluid`)
9. Common failures

## 1. Liquid domain, resolution and cost

**Domain** (`FLUID` modifier, `fluid_type='DOMAIN'`, `domain_type='LIQUID'`).
- **Size in metres, snug around the action.** Cell = largest side / `resolution_max` (default 32): a 0.6 m domain at 32 has 19 mm cells. Features under ~2 cells vanish. Use 32–64 for previews and 128–256 for finals. A glass close-up needs ≤ 2 mm cells, a bathtub 5–10 mm; oceans use the Ocean modifier (`environment-modeling.md`).
- **Low resolution changes volume.** In the test a 64 L block measured 68 L at frame 1, then inflated to 135 L as thin sheets spread (19 mm cells). Treat gains as a resolution issue and losses as leaks.
- **Cost grows about res^2.5.** Measured on the pour of §4 (0.6 m domain, 30 frames): 1.5× resolution → 2.6× time, 2× → 5.5×. Shrink the domain before raising resolution: a domain half the size gets half the cell size at the same cost. Time 2–3 resolutions over ~30 frames before committing to a final.
- **Disk.** Resolution 24 for 12 frames with the ALL cache used 2.7 MB; data scales with resolution³ × frames, so 128 × 250 frames reaches tens of GB on a local SSD path (`simulation.md` §2).

## 2. Liquid method, mesh, particles, cache

- **Method.** `simulation_method` FLIP (default, splashy) or APIC (less noise, better swirls). `use_viscosity` + `viscosity_value` for honey. `surface_tension` for droplets.
- **Mesh.** `use_mesh`, `mesh_scale` (mesh upres, default 2), `mesh_particle_radius` (default 2; larger = smoother, blobbier), `mesh_smoothen_pos/neg`, `use_speed_vectors` for motion blur.
- **Particles.** `use_flip_particles` (raw); `use_spray_particles`/`use_foam_particles`/`use_bubble_particles` are secondary particles rendered as small instances.
- **Cache.** `cache_type` REPLAY (default, simulates as you step), MODULAR (bake data, then mesh/particles/noise separately, so mesh settings can be re-tuned without re-simulating), or ALL. A never-baked ALL/MODULAR domain shows only its box. Data is OpenVDB (`cache_data_format`). Set `cache_directory` explicitly, since the default is a temp folder. Bake with `bpy.ops.fluid.bake_all()` inside `temp_override(scene=sc, object=dom, active_object=dom)`; free with `fluid.free_all()` (`simulation.md` §2).

## 3. Flows and effectors

- Flow (`fluid_type='FLOW'`, `flow_type='LIQUID'`): `flow_behavior` GEOMETRY emits the mesh volume once, INFLOW emits continuously, OUTFLOW drains. The flow must be closed and ≥ 2 cells thick (setup warns), or use `surface_distance` > 0. `use_initial_velocity` for jets, `subframes` 1–4 for fast emitters.
- Obstacles (`fluid_type='EFFECTOR'`, `effector_type='COLLISION'`) need ≥ 1–2 cells of thickness or liquid leaks. `use_plane_init` for single planes; GUIDE steers flow. Domain walls come from `use_collision_border_*`: turning off the bottom border drained the test liquid to 0.5 % of its volume.
- A moving obstacle keys its transform like any object. Effector `subframes` handles fast motion and `velocity_factor` scales how much of its motion reaches the liquid `[unverified: moving obstacle not tested]`. Effectors don't feel the liquid back `[unverified in test]` (`simulation.md` §2.1).
- **Liquid in a glass.** Simulate against a thick proxy wall and render a separate real glass. Let the liquid overlap the inner wall by ~0.1 mm (never a gap). Use Cycles for refraction (`rendering-and-lighting.md` §4).

## 4. Pouring into a glass

Scene: domain 0.6 m, 30 frames, cache ALL.
- Spout: a closed cylinder (r 3 cm) as a LIQUID INFLOW, `use_initial_velocity` with `velocity_coord` (0.6, 0, −0.8) m/s, keyed location + rotation (tilt −40° → −60°).
- Glass proxy: EFFECTOR COLLISION, 40 mm walls, `subframes` 1.

| `resolution_max` | Cell | Bake (30 f) | s / frame | Cache | Liquid verts in glass, f30 |
|---|---|---|---|---|---|
| 32 | 18.8 mm | 1.7 s | 0.057 | 6 MB | 66 % |
| 48 | 12.5 mm | 4.5 s | 0.15 | 16 MB | 78 % |
| 64 | 9.4 mm | 9.4 s | 0.31 | 21 MB | 81 % |

Cell = domain's largest side / resolution. Time grew about res^2.5 (1.5× res → 2.6×, 2× → 5.5×) on this tiny scene, so shrink the domain before raising resolution (§1).
Defect: with 5 mm walls (< 1 cell) volume still **rose** to 17.4 L, but only 18 % of the liquid stayed in the glass. A rising volume alone passes, so gate with `--volume-mode rise --liquid-in GLASS_` (§8).

## 5. Smoke and fire

- **Setup.** Domain `domain_type='GAS'`; flow `flow_type` SMOKE/FIRE/BOTH with `flow_behavior='INFLOW'`, plus `density`, `temperature`, `fuel_amount`, `smoke_color`. Domain `alpha`/`beta` (density/heat buoyancy, default 1/1), `vorticity`, `use_dissolve_smoke`, and `burning_rate`/`flame_vorticity`/`flame_max_temp`. 5.0+: vorticity no longer scales with time scale/step, so re-tune old files that changed those.
- **Detail cheaply.** Base resolution 64–128 plus `use_noise` (`noise_scale` 2), and `use_adaptive_domain` (`adapt_margin`, `adapt_threshold`) so only occupied space is simulated (measured in §6).
- **Rendering.** Principled Volume (`ShaderNodeVolumePrincipled`) reading the `density`, `flame` and `temperature` grids. Cycles gives accurate multiple scattering (tune volume step rate/max steps). EEVEE volumes are view-frustum voxels with softer detail and cheaper shadows `[unverified 5.2 setting names]`. Real-time targets use flipbook cards rendered from the sim (not covered in detail here). `object.quick_smoke` builds domain + flow + material as a template.

## 6. Dust and smoke from debris

Give each fragment (keyed or rigid) its own flow. Setup: `flow_type='SMOKE'`, `flow_behavior='INFLOW'`, plus one of the two sources below. Coupling is one way: bake the rigid world, then `fluid.bake_all` (`simulation.md` §2.1; projectiles and breakable walls in `rigid-bodies-and-destruction.md` §5–6).
- Mesh source: `flow_source='MESH'`, `surface_distance` ≥ ½ cell (0.05 m at 94 mm cells), `use_initial_velocity=True` + `velocity_factor` 1 so the smoke trails the motion, `subframes` 2 for fast pieces.
- Particle source (puffs at impact): a particle system on the debris with `render_type='NONE'`, then `flow_source='PARTICLES'`, `particle_system`, `particle_size`. `flow_source` is a dynamic enum: `enum_items` lists only NONE, but assigning `'PARTICLES'` works.
- `use_adaptive_domain` simulates only the occupied box. At res 32 the grid shrank to 1650 cells vs 5632, with identical density near the source. The bake was slower here (0.68 vs 0.40 s), so the saving only shows on large, mostly empty domains `[unverified at scale]`.
- Sourcing from Bullet works without keys. A tumbling rigid shard fell 1.21 m and density stayed within 0.3 m of it on 100 % of sampled frames (fluid bake stepping an unbaked rigid world; bake rigid first for farm renders).
- Defect: a 2 cm shard with `surface_distance` 0 in 94 mm cells emitted **nothing**. Setup warns "flow thinner than 2 voxels".

## 7. Reading grids in scripts

`density_grid` is empty on the original object; read `eds = dom.evaluated_get(dg).modifiers[name].domain_settings` and take `eds.density_grid`. Reshape it to `domain_resolution` reversed (z, y, x). A cell centre is `start_point + (i+0.5)·cell_size` in domain-local space, and adaptive domains change `domain_resolution` every frame. `--gas-near` in `scripts/sim_check.py` samples the grid this way.

## 8. Gates (`scripts/sim_check.py --checks setup,fluid`)

```
blender -b tank.blend --python scripts/sim_check.py -- --bake --checks setup,fluid --volume-loss-pct 50 --volume-gain-pct 150
blender -b dust.blend --python scripts/sim_check.py -- --checks setup,fluid --frames 1:24:4 --gas-near DEBRIS_ --near-m 0.3
blender -b pour.blend --python scripts/sim_check.py -- --checks setup,fluid --volume-mode rise --liquid-in GLASS_ --in-min-pct 50
```

| Check | Measures | Pass |
|---|---|---|
| setup (fluid items) | unapplied scale, fluid cache end < scene end, MESH flows thinner than 2 voxels with `surface_distance` < 1 cell; reports resolution, cell mm, cache type and baked data/mesh flags | no errors |
| fluid | liquid mesh per frame (domain box = missing), volume vs GEOMETRY flow volume, gas density | mesh every frame; 0.5 ≤ ratio ≤ 2.5; density > 0 |
| fluid `--gas-near` | max density within `--near-m` of each object per sampled frame | density > 0.01 on ≥ 50 % of frames after the first (`--near-min-pct`) |
| fluid `--volume-mode rise` / `--liquid-in` | last vs first liquid volume; % liquid verts inside container bbox at the last frame | volume rose; ≥ `--in-min-pct` inside |

The volume gate is asymmetric on purpose: low-resolution FLIP inflates thin sheets (measured up to 2.1× the flow volume at 19 mm cells), while leaks and drains lose volume (0.005×), hence loss 50 % / gain 150 % (`--volume-mode` auto/conserve/rise/skip). Liquid volume is the signed-tetrahedron volume with the reference point on the domain floor, so an open bottom adds no error; open walls make it approximate.

Synthetic tests (each clean case passes, each planted defect fails):

| Scene | Clean | Planted defect |
|---|---|---|
| Liquid, res 32, 64 L block | mesh all frames, ratio 1.07–2.12 | open floor border: ratio 0.005; unbaked or `use_mesh` off: mesh missing |
| Smoke, res 16 | density 0.84 | unbaked: 0 |
| Smoke from moving shard (keyed, rigid, particles, adaptive) | density near object 100 % of frames | 2 cm shard, `surface_distance` 0: 0 % + setup warning |
| Tilted pour into glass, res 32/48/64 | volume rises, 66/78/81 % inside | 5 mm walls: 18 % inside (fail) |

## 9. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Liquid leaks through wall/glass | obstacle < 1–2 cells, border off | thicker sim proxy, higher resolution, borders on |
| Liquid volume balloons | thin sheets at low resolution | raise resolution; accept in previews |
| No liquid surface | `use_mesh` off or mesh unbaked | enable Mesh, bake mesh |
| Domain shows only its box | ALL/MODULAR cache never baked | `fluid.bake_all` (§2) |
| Debris emits no smoke | fragment < 2 cells thick, `surface_distance` 0 | `surface_distance` ≥ ½ cell, or particle-sourced flow (§6) |
| Smoke/liquid ignores the new debris motion | fluid baked before the rigid edit | free fluid, rebake rigid → fluid |
| Pour "fills" but the glass stays empty | walls < 1–2 cells leak; rising volume hides it | walls ≥ 2 cells; `--liquid-in` gate (§8) |
| Final-resolution bake takes hours | resolution raised on an oversized domain | shrink domain first; time 2–3 resolutions over ~30 frames (§1) |
| `density_grid` is empty | read on the original object | read the evaluated object's domain settings (§7) |
| Cache lands in a temp folder | `cache_directory` left at default | set it explicitly to a local SSD path (§2) |
