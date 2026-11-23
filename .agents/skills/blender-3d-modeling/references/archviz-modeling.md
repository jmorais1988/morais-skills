# Archviz Modeling (plans → shell → furniture)

Read this when building an interior or exterior from drawings and dimensions rather than one reference photo: brief and inputs, plan import and the `plan_to_rooms.py` shell, real-world dimension tables, shell detailing, furniture and scene organisation, exterior context, real-time export and the geometry gates. A room that is dimensionally right and sealed already looks professional before any hero detail; cameras, light, exposure, materials and output — what finally sells the shot — are in `archviz-lighting-and-rendering.md`. Facts marked *measured* come from synthetic tests in Blender 5.2; version boundaries are stated.

## Contents
1. Brief & inputs
2. Plans → shell (`scripts/plan_to_rooms.py`)
3. Real-world dimensions
4. Detailing the shell
5. Furniture, assets & scene organisation
6. Exteriors
7. Real-time export (Unreal & co.)
8. Geometry gates (`scripts/archviz_gates.py`)
9. Common failures

## 1. Brief & inputs

Collect (or state as assumptions) before modeling:

| Input | Why |
|---|---|
| Plans/sections/elevations (DWG/DXF/PDF/IFC/sketch with dimensions) or measured room sizes | Geometry is typed from numbers, never eyeballed |
| Shot list: each camera's room, direction, format (landscape/portrait), resolution | Detail and furniture budget go where cameras look; hidden walls stay simple (`archviz-lighting-and-rendering.md` §1) |
| Stills / animation / VR panorama / real-time (engine) | Render engine, sample budget, topology, lightmaps |
| Location + orientation (north) + date/time or mood (overcast, golden hour, night) | Sun angles, sky, color temperature (`archviz-lighting-and-rendering.md` §2) |
| Style references per room (materials, furniture, mood) | Materials and furniture selection; use `reference-gathering.md` per component |
| Deliverables: file formats, bit depth, passes for post, `.blend` handover | Output setup (`archviz-lighting-and-rendering.md` §5) |

Open the checklist with `scripts/project_state.py init --profile archviz`; its steps follow the archviz order: this file's §1–5, then `archviz-lighting-and-rendering.md` §1–5, then §6–7 here, then the gates.

## 2. Plans → shell (`scripts/plan_to_rooms.py`)

**Import routes (5.x)**: no built-in DXF importer — the *Import AutoCAD DXF* extension has limited support [unverified on 5.2]; convert DWG → DXF with ODA File Converter. SVG imports as curves (`bpy.ops.import_curve.svg`). PDF plans: rasterise, load with `bpy.ops.image.import_as_mesh_planes`, scale the plane by one known long dimension (factor = real / measured), apply scale, lock it on a `REF_Plan` collection. IFC/BIM: Bonsai (0.8.5 targets 5.1+). For an agent the most reliable route is to **type the plan as numbers** and build it with `scripts/plan_to_rooms.py`.

**`scripts/plan_to_rooms.py`** — JSON plan → shell (headless ok; live via `PLAN_OPTS`):
- Walls from centre-line (or face) polylines with **mitred corners and real thickness**; closed loops have no overlapping corner volumes.
- Openings (window/door/void) as **live EXACT booleans** driven by a hidden cutter; cutter, frame, glass and door leaf are parented to an `OPN_<id>` empty, so moving the empty moves the whole opening. Door leaves pivot on the hinge.
- Floor and ceiling **slabs cover the walls' full outer footprint** (walls sit between them → wall/slab junctions are sealed), per-room floor finishes extend under the walls instead of meeting them edge-to-edge.
- World-scale box UVs (1 UV unit = 1 m) so tileable materials are correct at real size; placeholder materials with plausible albedo.
- Each opening is **verified by ray casts** (clear through the centre, solid wall beside it); warnings for openings too close to corners or without a lintel.
- Window panes are single planes with Thin Wall in 5.2+ (6 mm solids on older versions) — glass rules: `archviz-lighting-and-rendering.md` §4.
- Limits: straight segments (sample arcs), one storey per call, no stairs/roofs.

**Manual rules** when modeling by hand: extrude the plan outline to storey height, Solidify with even thickness (offset −1/0/+1 decides which face the plan line is), or extrude a closed 2D outline. Openings: booleans with cutters parented to the wall, or cut geometry when bevels/UVs need clean topology — apply before export. Slabs are 20–25 cm solids overlapping walls, never single planes. Keep the archviz prefixes `WALL_`, `SLAB_`, `FLR_`, `CEIL_`, `OPN_`, `CUT_`, `FRAME_`, `WIN_`/`GLASS_`, `DOOR_`, `FURN_` (plus `GEO_`/`REF_` for props and plan references, and the generic `LGT_`, `CAM_`) — the same set as `project-files-and-naming.md` §1 and the `archviz` profile of `naming_lint.py`; the gates select objects by prefix.

## 3. Real-world dimensions

| Element | EU / international | US |
|---|---|---|
| Exterior wall (finished) | 25–40 cm | 2×6 stud + finishes ≈ 16–20 cm |
| Interior partition | 10–12 cm | 2×4 + drywall ≈ 11.5 cm |
| Ceiling height (residential) | 2.50–2.70 m (varies by national code) | 8–9 ft (2.44–2.74 m) |
| Interior door leaf | 0.80–0.90 × 2.00–2.10 m | 30–36 × 80 in |
| Window sill (living) / kitchen | 0.75–0.90 m / ≈ 1.10 m above counter | similar |
| Kitchen worktop | 0.90 m (0.85–0.95) | 36 in |
| Dining table / desk top | 0.72–0.76 m | 28–30 in |
| Seat height (chair / sofa) | 0.45 m / 0.40–0.45 m | 17–19 in |
| Coffee table | 0.35–0.45 m | 14–18 in |
| Washbasin rim | 0.85–0.87 m | 32–36 in |
| Handrail / guard | ≥ 0.90 m (DIN 18065: 0.80–1.15 m) | 34–38 in |
| Stairs | 2R + G = 60–65 cm, riser 15–19 cm | riser ≤ 7¾ in, tread ≥ 10 in; 7/11 in comfortable |
| Light switch / socket | 1.05 m / 0.30 m [unverified — varies] | 48 in / 12–16 in |
| Baseboard | 6–12 cm high, 1–2 cm proud | 3–7 in |
| Floor planks | 12–22 cm wide, 1.2–2.2 m long, staggered joints | same |

Walls give a room its character — check a door against a 1.80 m human reference before judging anything else.

## 4. Detailing the shell

- **Edges are never razor sharp**: bevel 1–3 mm on furniture and trims (geometry or Bevel shader radius 2–5 mm on large flat architecture).
- **Reveals and depth**: window frames set into the wall depth (inset), a sill board, and the wall return visible — flat cut-outs read as fake. Give frames a 40–70 mm face and 60–100 mm depth.
- **Trims** as curves with a profile (`modifiers-and-curves.md`): baseboards, crown mouldings, shadow gaps (10–20 mm dark recess where wall meets ceiling), door casings.
- **Floors**: plank or tile geometry only where the camera grazes it; otherwise a tileable PBR set at world scale + a per-board/tile random value (Object Info / Voronoi cell ID) for tone variation; grout via a bevel-in-shader or displacement.
- **Soft goods** (cloth settings: `cloth-and-garments.md` §2): curtains and throws via cloth sim pinned to a rail, then Subdivision; cushions via cloth pressure or sculpt (`sculpting.md`); rugs with displacement or hair curves for high pile — keep contact with the floor.
- **Clutter tells the story**: books, plants, a throw, slightly misaligned chairs. Perfect symmetry and empty surfaces read as CG.

## 5. Furniture, assets & scene organisation

- Prefer real product dimensions; check every piece with `scripts/archviz_gates.py` `dims` (keyword ranges) or an `--expect` JSON of the spec (§8).
- **Link** repeated furniture from an asset library (override when it must change), **append** what you will edit; CC0 sources: Poly Haven models, 5.2 remote asset libraries/Online Essentials; BlenderKit renamed Blendkit in 2026 (5.2 support [unverified]). Licensing: `kitbashing.md` §8.
- Every piece rests on its support: root object origin at the base, contact gap 0 ± 2 mm (`contact` gate, §8).
- Collections per level → room → category (`L0/Living/Furniture`); view layers or collection visibility for day/night variants; instances for repeated items.
- Units: Metric, `scale_length` 1.0, display METERS or MILLIMETERS (`scripts/archviz_setup.py` `units()`).

## 6. Exteriors

- Context first: ground plane with real material, neighbours as massing, street furniture, entourage people at true scale (1.65–1.80 m) — they sell scale more than anything.
- Vegetation via `flora.md` assets + `scripts/scatter_on_surface.py`; lawn as hair curves or scattered cards near camera, texture far away.
- Sky/HDRI + sun as `archviz-lighting-and-rendering.md` §2, aerial perspective and haze from `environment-modeling.md` §10; background plate or HDRI backplate for the far distance.
- Facades: window glass reflects the sky — needs an environment worth reflecting; add interior rooms/curtains behind windows so glass isn't a black void.

## 7. Real-time export (Unreal & co.)

- Split the shell by room/element (walls, floor, ceiling, openings, glass separate), apply booleans and modifiers, bake procedural materials to textures (`scripts/bake_maps.py`, `baking-maps.md`), keep real scale (1 unit = 1 m in Blender; engines convert).
- **Unreal 5.x**: glTF and USD import through Interchange (5.2 USD exporter: `convert_scene_units`, lights, MaterialX network); FBX remains common. Lumen needs no lightmap UVs; baked (static) lighting needs a non-overlapping UV2 with padding — or let the engine generate it. No Datasmith exporter for Blender [unverified]. Rename to engine conventions (`SM_`, `M_`) in the export copy, not in the working file.
- Collada was removed in 5.0. Twinmotion: glTF/FBX/USD [unverified].
- Budgets and the generic engine checklist: `poly-budgets-and-targets.md`.

## 8. Geometry gates (`scripts/archviz_gates.py`)

Run `scripts/archviz_gates.py` after the shell and again after furniture. The light-leak, glass, camera, render and UV gates run before final renders: `archviz-lighting-and-rendering.md` §6 — run `leaks` as soon as the shell is closed, it is the render-side proof of the same seal.

| Check | Finds | *Measured* on synthetic rooms |
|---|---|---|
| `closure` | Gaps between wall tops/bottoms and slabs | clean 0 mm; injected 20.0 mm |
| `zfight` | Same-facing coplanar overlaps that are visible (ignores faces buried in a solid) | injected coplanar patch 10 000 cm² found |
| `contact` | Floating/sunk furniture roots | +30 mm floating, −20 mm sunk reported |
| `dims` | Furniture outside keyword ranges or `--expect` spec | 0.84 m coffee table flagged |

A passing gate removes one defect class; the shot review that follows the gates is in `archviz-lighting-and-rendering.md` §6.

## 9. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Bright lines at wall/ceiling corners, room lit from nowhere | Gaps between walls and slabs, single-plane walls/ceilings | Solid walls between overlapping slabs; `closure` gate (§8) + `leaks` gate (`archviz-lighting-and-rendering.md` §6) |
| Flickering stripes on floors/walls | Coplanar duplicate faces (floor plane on slab, decals flush) | Offset or delete; `zfight` gate |
| Everything looks like a model kit | Wrong dimensions, no bevels, empty surfaces | §3 table, `dims` gate, bevels (§4), clutter |
| Floating sofa, no contact shadow | Origin/placement error | `contact` gate; snap roots to floor |
| Unreal import at wrong scale or with black lighting | Unapplied scale, overlapping lightmap UVs with static lighting | Apply transforms, Lumen or proper UV2 (§7) |
