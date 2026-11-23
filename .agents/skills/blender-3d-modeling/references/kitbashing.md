# Kitbashing (assets and scenes from part libraries)

Kitbashing builds a new design from existing parts — the ILM model-shop technique of cutting up tank and battleship kits to detail spaceships. It is fast and gives dense, believable detail, and it fails in predictable ways: detail used to hide a weak silhouette, parts from different kits that don't share a scale or shape language, detail spread evenly with nowhere for the eye to rest, and license violations. Profile: `project_state.py init --profile kitbash`. Grid-snapped building kits are a special case covered in `modular-kits-and-wfc.md`.

## Contents
1. When kitbashing fits
2. Design rules
3. Workflow
4. Building and maintaining a library
5. Blender tools & API (4.2–5.2)
6. Seams, shading & cleanup
7. Game export: bake, merge, instance
8. Licensing
9. Review & common failures

## 1. When kitbashing fits

| Good fit | Poor fit |
|---|---|
| Sci-fi hulls, mechs, industrial machinery, space stations, cityscape rooftops (vents, AC units, antennas), vehicle undersides and engine bays, set dressing clutter, concept/previs | Organic subjects; a specific real object that must match references exactly; stylized assets with a strict shape language the library doesn't share; low-poly game assets shipped as-is from high-poly kits |

A matching-reference job (a real rifle, a real car) may still kitbash *generic* sub-parts (bolts, hoses, connectors) — but the identity-defining parts are modeled from references.

## 2. Design rules

- **Silhouette first.** Block the primary form without kit parts and approve it at thumbnail size (≈ 256 px). Kit detail never fixes or should never distort the primary silhouette.
- **Primary → secondary → tertiary.** Primary = the big masses (split unevenly, e.g. ~70/30, not 50/50); secondary = medium parts that define function (engines, intakes, housings, pipes that cover intersections); tertiary = small detail (greebles, rivets, labels). Place in that order; check each pass from the intended camera distance.
- **Areas of visual rest.** Cluster tertiary detail irregularly around functional zones (joints, access points, engines, edges) and leave large calm panels. Detail everywhere reads as noise ("greeble soup").
- **Functional plausibility.** Every part should suggest a job — intake, hinge, mount, cable run, heat sink, access hatch — and connect to something: pipes end in fittings, cables run to sockets, panels have fasteners, moving parts have clearance.
- **One shape language per asset.** Consistent bevel radii, corner styles, cut angles, hole shapes. Mixing parts from kits with different bevel conventions is visible even when each part is good.
- **Scale cues.** Include known-size elements (handrails ≈ 1 m high, doors ≈ 2 m, ladder rungs ≈ 0.3 m apart, bolts/rivets at real sizes). They sell the size of the whole object; wrong-scale greebles make a battleship read like a toy.
- **Disguise the source.** Recognizable library parts (a well-known kit's signature piece) break the illusion — modify, combine, crop into the surface, or recolor.
- **Repetition with variation.** Repeat parts to create rhythm, but vary spacing, scale (within the same shape family), and orientation.

## 3. Workflow

1. **Reference & contract** (as for any model): subject function, scale, style, detail distribution per zone, budget.
2. **Silhouette blockout** from primitives; approve front/side/top/3q at thumbnail size.
3. **Library audit** before use: `scripts/asset_library.py audit` on the parts you intend to use — scale, pivots, texel density, material conventions, license fields. Reject or fix parts that fail; don't discover mismatches after placing 300 instances.
4. **Primary parts**: large kit pieces that change sub-forms (engine blocks, hull plates), each checked against the silhouette.
5. **Secondary parts**: functional assemblies; route pipes/cables between them (curves with bevel, `modifiers-and-curves.md`).
6. **Tertiary detail**: in clusters at functional zones; GN instancing for large repeated fields (surface greebles) with density masks so rest areas stay clean.
7. **Seams & shading** (§6), **materials** (shared palette or trim sheets; wear masks unify parts from different sources — `procedural-materials.md` §2).
8. **Review** at the intended camera distances + turntable; then **bake or merge** for the target (§7).

Keep parts as **separate objects or linked instances** until the design is approved; never boolean-union a kitbash early.

## 4. Building and maintaining a library

- **Real-world scale**, applied transforms, dimensions on a consistent grid (1 m / 0.5 m / 0.25 m increments) so parts align and arrays work. Shared texturing — one trim sheet set or material palette, one texel density — follows the kit rules in `modular-kits-and-wfc.md` §1, §8 (targets: `uv-unwrapping.md`); `asset_library.py audit` flags density outliers.
- **Pivot convention (one per part type)** — the general pivot rules (center / base / hinge / root / mechanical joint) live in `assembly-and-hierarchy.md` §2; kit parts add: surface-mounted parts → origin at the mounting face center with local **+Z pointing out of the surface** (matches Blender's Align Rotation to Target, which aligns object Z to the target normal); in-line parts (pipes, rails) → origin at one connection end, +X along the run; floor props → bottom center. Inconsistent pivots are the most common library defect.
- **Sockets**: child empties named `SOCKET_<role>` (e.g. `SOCKET_mount`, `SOCKET_pipe_in`) with +Z out of the connection and +Y as the roll reference; `asset_library.py snap` joins a part socket to a target socket.
- **Categories by function and size tier**: panels/plates, vents/grilles, pipes/cables with end fittings, hinges/latches/pistons, fasteners, handles/rails/ladders, antennas/sensors, lights, housings/boxes, decals/labels — each tagged big/medium/small and by style family (`hardsurface_scifi_clean`, `industrial_worn`).
- **Texture consistency**: shared trim sheets or a shared material palette; consistent texel density (rules of thumb ≈ 512 px/m background, 1024 px/m hero); `asset_library.py audit` flags outliers.
- **Metadata on every part**: catalog, tags (function, size tier, style), author, **license and source URL**, triangle count, whether it is a high-poly bake source or a game-ready piece.
- **Library files**: one `.blend` per category in a folder registered as an asset library (Preferences → File Paths/Asset Libraries; its own Preferences page in 5.2). Blender does not copy assets into a library — the `.blend` must already live in the library folder. Version the folder (git LFS or dated snapshots).
- **Harvesting parts from existing models**: separate the piece, apply transforms, re-pivot to the convention, add sockets, strip identity (logos, signature silhouettes) — and check the source license allows extraction and redistribution first (§8).

## 5. Blender tools & API (4.2–5.2)

Linking, library overrides, resync and relocation from code: `project-files-and-naming.md` §3–4.

`scripts/asset_library.py` (headless or live via `ASSET_OPTS={"op": ...}`; prints `ASSET_LIBRARY_RESULT {json}`):
```bash
blender -b library/panels.blend --python scripts/asset_library.py -- mark --names Panel_A,Panel_B --catalog Kit/SciFi/Panels --tags panel,medium --save
blender -b library/panels.blend --python scripts/asset_library.py -- audit --collection Kit --grid 0.5 --pivot BOTTOM_CENTER --palette MAT_Metal,MAT_Rubber
blender -b ship.blend --python scripts/asset_library.py -- place --library library/panels.blend --collection Kit_Wall --name W1 --rotation-deg 0,0,40 --save
blender -b ship.blend --python scripts/asset_library.py -- snap --part W2 --part-socket SOCKET_L --target-socket W1/SOCKET_R --save
```
Audit flags unapplied scale, pivot and off-grid dimensions, texel-density outliers (±25 % of the kit median), stray materials, missing UVs/sockets; `place` reuses one Library datablock for repeated placements; `snap` puts the part socket on the target socket with opposing +Z and aligned +Y (tested to ~1e-6 m). Limits: non-uniform scale with rotated sockets may shear; open edges count as non-manifold unless `allow_boundary`.

- **Marking assets** (`scripts/asset_library.py mark`): `ID.asset_mark()`, `ID.asset_generate_preview()` (object previews render from local −Y — orient hero faces toward −Y), `asset_data.catalog_id`, `.tags.new()`, `.author`, `.description`, `.license` (where available).
- **Catalogs**: `blender_assets.cats.txt` next to the library `.blend`s — UTF-8, first line `VERSION 1`, then `UUID:catalog/path:simple_name` per line (`#` comments allowed). Python has no catalog-creation API; scripts write this file (the script preserves existing lines and never duplicates a path).
- **Import methods changed**: 4.x — Link / Append / Append (Reuse Data) (default); 5.0 adds **Pack** (linked but stored inside the .blend; default for custom libraries) and removes Append (Reuse Data); 5.2 adds a per-asset preferred import method. Scripts that place assets must branch on `bpy.app.version`. Dragged collections become **collection instances** by default.
- **Linking for kits** (`asset_library.py place`): `bpy.data.libraries.load(path, link=True)` + an Empty with `instance_type='COLLECTION'`; reuse the loaded library instead of loading it per placement. Edit linked parts in place with **Library Overrides** (Object → Relations → Make Library Override); keep all child collections under the linked root collection or overrides misbehave.
- **Remote asset libraries (5.2)**: browse an HTTP-hosted library; assets download on demand. Self-host with a static server and `blender -b -c asset_listing generate <dir>` (command from the 5.2 manual).
- **Snapping (4.0+)**: during a transform press **B** to choose the Snap Base; Snap With Closest/Center/Median/Active; Snap To Face Project/Face Nearest for surface placement; **Align Rotation to Target** so parts sit on curved hulls; Snap Peel Object for surfaces with thickness.
- **Geometry Nodes greebles**: Distribute Points on Faces (density from a painted attribute that leaves rest areas empty) → Instance on Points from Collection Info (Pick Instance, random index/scale/yaw, rotation aligned to normal) — `scripts/scatter_on_surface.py` with `align_to_normal=1` and a density attribute does this.
- **Add-ons (verify installed)**: KIT OPS 4 (free: browse KPACKs, drop INSERTs, cutters, hardpoint snapping, create INSERTs; PRO: authoring cutters, factory/batch tools, decals), MESHmachine **plugs** (inserts integrated into the target with normal transfer), DECALmachine (mesh decals, trim-sheet pipeline, atlas export for engines), Bool Tool (extension since 4.2; manages Boolean modifiers).

## 6. Seams, shading & cleanup

| Situation | Treatment |
|---|---|
| Part sits on or into a surface (render) | keep separate; bury slightly (1–3 mm) or overlap; hide the contact with a bevel, gasket/flange part, or a decal line |
| Insert must look carved from a curved surface | MESHmachine-style plug or boolean + **Data Transfer** custom normals from the smooth base (Face Corner Data → Custom Normals) |
| Many parts must become one watertight mesh (sculpt, print) | Boolean union (EXACT) or voxel remesh at a size below the smallest detail, then clean up |
| Game asset | bake high → low (§7) rather than merge |

- Normals since 4.1: Auto Smooth is gone — use the *Smooth by Angle* modifier / set sharpness by angle; old scripts setting `use_auto_smooth` fail.
- Weighted Normal (Face Area, Keep Sharp) on beveled low-poly parts.
- Unify materials across sources: re-assign parts to the asset's shared palette/trims; apply a global wear/dirt mask pass so all parts age together.
- Run `scene_gates.py` for floating parts (attachment) and unintended intersections; declare intentional overlaps.

## 7. Game export: bake, merge, instance

- Most kit libraries are high-poly: treat the kitbash as a **bake source**. Build a low-poly cage over the silhouette, bake normal/AO/curvature (`scripts/bake_maps.py --source`); floating detail (parts hovering above the surface) bakes cleanly; use per-part bake groups or match-by-name to avoid cross-projection.
- Repeated real-geometry parts: keep as instances (linked duplicates / collection instances) in the scene and export as engine instances, not unique meshes.
- Before export: join by material where the engine benefits, atlas UVs or use trim sheets to cut draw calls, check triangle budgets (`poly-budgets-and-targets.md`), remove hidden internal geometry.

## 8. Licensing

Record license + source on every part; check before extracting parts, redistributing, shipping, or training anything.

| Source | Typical terms |
|---|---|
| Poly Haven | CC0 — any use, redistribution allowed |
| BlenderKit | Royalty Free (commercial, no attribution; no reselling as-is, e.g. inside an asset pack) or CC0 |
| Sketchfab downloads | per model: CC0 / CC-BY (credit) / BY-SA (share alike) / BY-ND (no modification — unusable for kitbashing) / BY-NC (non-commercial only); Standard license (commercial, no standalone redistribution); Editorial (no commercial use) |
| KitBash3D | no redistribution/resale/sublicensing of assets; team size tiers; no AI/ML training use; expired subscriptions can't start new projects with the assets |
| Big Medium Small | tiered by team size; games/film allowed; no distributing the models as 3D models |

- Giving clients native work files that expose third-party source meshes can breach licenses.
- Never reproduce trademarked designs or a recognizable copyrighted design by kitbashing it.

## 9. Review & common failures

Review: thumbnail silhouette, intended-distance shots, a "rest areas" check (squint/blur: detail clusters vs calm panels), function pass (does every part connect and plausibly do something), close-ups of contacts and seams, library audit report, license list.

- Greeble soup: even detail everywhere, no rest areas; detail hiding a weak silhouette.
- Mixed styles and bevel conventions from different kits; mismatched scales (door-sized rivets).
- Recognizable, undisguised source parts.
- Floating or buried parts that attach to nothing; pipes that end in mid-air.
- Inconsistent pivots/unapplied scale breaking snapping, arrays and Align Rotation to Target.
- Boolean artifacts and seam shading left unfixed.
- A material per part from each kit → dozens of draw calls.
- Scripts assuming Append (Reuse Data) or `use_auto_smooth` on 5.x.
- License violations: extractable source meshes shipped, CC-ND/NC parts in commercial work, missing CC-BY credits.
