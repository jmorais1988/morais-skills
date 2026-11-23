# Large Sets: Towns, Cities, Districts, Big Levels

A city is not a big model; it is a **system**: a street network, a zoning pattern, a handful of kits, a procedural filler, hand-placed hero moments, and a performance plan that decides what exists at which distance. Build the system in that order. Detailing buildings before the layout and metrics are frozen is the most expensive mistake in large sets. Profile: `project_state.py init --profile city`. Also: `environment-modeling.md` (terrain, scatter, atmosphere), `modular-kits-and-wfc.md` (kits), `kitbashing.md` (rooftop/prop libraries), `parallel-work-with-subagents.md` (district lanes).

## Contents
1. Brief & reference study
2. Layout language & detail tiers
3. Real-world metrics
4. Order of work
5. Street network & parcels
6. Buildings: hero, kit, procedural filler
7. Dressing & variation
8. Scene & file management in Blender
9. Coordinates & precision
10. Engine-side authoring
11. Review & common failures

## 1. Brief & reference study

Beyond the usual target questions, record in NOTES.md:
- **Viewpoints**: player path/height, vehicle cameras, drone/cinematic shots, skyline shots; playable area vs visible-only area (m²).
- **Place & era**: region, culture, city type (US grid, European historic/planned, Asian dense, informal settlement, fantasy/sci-fi with a real-world analog), period, wealth, climate, topography.
- **District list** with character per district (materials, heights, density, age, street width, activity).
- References per district: street-level photos, aerial/satellite (layout, block shapes, roof types), façade elevations, ground-floor close-ups, street furniture, signage language, material swatches; maps (OSM) for real or analog cities.
- **Metrics table** (§3) filled with the numbers for *this* place, not generic ones.

## 2. Layout language & detail tiers

- Use Lynch's five elements as the skeleton: **paths** (streets, walkways), **edges** (rivers, rail lines, walls, coastlines), **districts** (shared character), **nodes** (junctions, squares, stations), **landmarks** (reference points). Each district should have at least one landmark visible from two or more of its nodes; players navigate by them.
- **Skyline**: deliberate height variation (tall cluster at the core or a node, tapering at the edges); review as a black-silhouette render from player height and from the key shot cameras.
- **Detail tiers by camera** (decide per district, write into the contract):

| Tier | Where | Content |
|---|---|---|
| Hero | player path, cinematic framing, landmark frontages | unique buildings or heavily varied kits, full ground floors, props, decals, interiors where visible |
| Street | second row, side streets | kit buildings with variation, simplified ground floors, dressing at a lower density |
| Background | blocks seen only from afar | façade shells / procedural massing, roof silhouettes, emissive window cards |
| Horizon | skyline and beyond | merged proxies, impostors, matte/HDRI |

- Rule of thumb: a small share of buildings are unique (roughly 5–15 %); the rest are kit or procedural filler. Place the unique ones where the camera spends time.

## 3. Real-world metrics

Collect the target city's actual numbers; these are starting points (US standards unless noted):

| Element | Typical values |
|---|---|
| Urban travel lane | 3.0 m; 3.3 m for bus/truck lanes; 2.7–2.9 m next to turn lanes |
| Sidewalk clear zone | residential 1.5–2.1 m; downtown 2.4–3.7 m; minimum 1.5 m |
| Curb reveal | ≈ 150 mm (100–230 mm range) |
| Block size | Portland 61 × 61 m; Manhattan ≈ 80 × 270 m; Barcelona Eixample ≈ 113 m chamfered squares; Tokyo chō ≈ 109 × 109 m with ≈ 5 m streets and 1.3–2.8 m alleys |
| Lots / plots | Manhattan historic 7.6 × 30.5 m; US suburban ≈ 15–45 m frontage; medieval European burgage plots ≈ 5–12 m frontage, deep |
| Floor-to-floor | residential/hotel ≈ 3.1 m; office ≈ 3.9 m; ground-floor retail 3.7–4.9 m; lobbies 4.5–8 m |
| Haussmann Paris | boulevards ≈ 30 m wide, buildings 12–20 m tall (≤ 6 storeys) |
| Door | exterior ≈ 0.91 × 2.03 m; commercial double doors ≈ 1.8 × 2.1 m |
| Window sill | 0.75–0.9 m (bathrooms 1.2–1.5 m) |
| Street lights | urban poles 8–10 m, spacing ≈ 3–4 × pole height (25–50 m) |
| Street trees | 6–9 m on center |

Put a 1.8 m human, a car (≈ 4.5 × 1.8 × 1.5 m) and a bus (≈ 12 × 2.5 × 3.2 m) in every greybox review shot. Streets that look right from the air are routinely far too wide at eye level.

## 4. Order of work

1. **Layout** — 2D road graph, district boundaries, zoning, landmark and node positions, terrain/water (edges). Freeze before step 3.
2. **Greybox** — parcels extruded to height ranges per zoning; street cross-sections (lanes, curbs, sidewalks) as simple profiles; review from all key cameras; iterate layout here while it is cheap.
3. **Kit spec** — grid module, floor heights, façade bay widths, door/window standard sizes, pivot and naming conventions (`modular-kits-and-wfc.md` §1). Footprints must be whole multiples of each other.
4. **Kits & hero buildings** — in parallel lanes per kit family / per hero building (`parallel-work-with-subagents.md`).
5. **Procedural filler** — façades and massing generated on the greybox parcels from the kits (§6).
6. **Dressing** — street furniture, vehicles, vegetation, signage, decals, clutter (§7).
7. **Lighting & atmosphere** — time of day, emissive windows, fog for depth (`environment-modeling.md` §10).
8. **Optimization** — LOD/HLOD, proxies, culling, streaming layout (§10); re-review from cameras.

## 5. Street network & parcels

- **Hand-authored**: draw road curves (Bezier/poly) on the terrain per the layout; build road meshes with Array + Curve or GN Curve to Mesh with a cross-section profile (lanes, curbs, sidewalks) and Shrinkwrap/raycast to terrain (`modifiers-and-curves.md`, `environment-modeling.md` §7). Intersections as dedicated pieces (T, X, roundabout) snapped to road ends.
- **From real data**: OSM import (Blosm — free: roads/paths as curves, simple extruded buildings, terrain; premium: textured buildings and more; BlenderGIS for DEM/OSM) → use as layout and massing reference, then replace with kits. Verify add-on/version compatibility first.
- **Procedural layouts** (for fictional cities): grow a street graph with L-system-style rules (Parish & Müller 2001: global pattern goals — grid, radial — plus local constraints that snap to intersections and avoid water) or trace streamlines through a tensor/direction field (Chen et al. 2008) — in Blender, approximate with GN curves and repeat zones, or generate the graph in Python and build curves from it.
- **Blocks → parcels**: recursive oriented-bounding-box splits (irregular European lots) or strip subdivision along the street frontage so every parcel touches a street; enforce min/max frontage and depth from the metrics table; store parcel attributes (district, zoning, height range, age, seed) as custom properties or GN attributes — the building generator reads them.
- Variation in the network: real cities have gradients (dense core → sparse fringe), irregular lots, parks, plazas, and geometry that follows terrain and history. A uniform perfect grid everywhere reads as a game map.

## 6. Buildings: hero, kit, procedural filler

- **Hero buildings**: modeled from references like any asset (`hard-surface-categories.md` §5), still using the kit's metrics so they connect to streets and neighbors.
- **Kit buildings**: façade modules (ground-floor shopfront bays, typical floor bays, corner bays, cornice/parapet, roof pieces) authored to the kit grid and assembled per parcel. Grid, pivots, trim sheets, seams and stress layouts: `modular-kits-and-wfc.md`.
- **Procedural filler with Geometry Nodes (shape-grammar approach, after CityEngine CGA)**:
  - *extrude* → parcel footprint → Extrude Mesh to building height (floors × floor height);
  - *comp* → split faces by normal Z into roof / façades / base;
  - *split & repeat* → per façade face: floors = floor(height / floor_height), bays = floor(width / bay_width), stretch the remainder evenly; generate the bay grid and Instance on Points the kit modules chosen by floor type (ground / typical / top) and bay type (corner / door / window / blank);
  - per-building parameters (style, seed, material variant) from parcel attributes; For Each Element zones (4.3+) and Repeat zones for per-face/per-floor logic; Bundles/Closures (5.0+) to pass parameter sets.
  - Roofs: flat with parapet and rooftop kitbash (AC units, water tanks, antennas via scatter with density masks), hip/gable from straight-skeleton-style roof pieces, or modeled roof modules per footprint class.
- Tools to evaluate before relying on them (verify compatibility with the installed Blender): Buildify (free GN library, built for 3.x), Building Tools add-on, iCity (paid GN city generator), SceneCity (paid). Treat them as accelerators; the metrics and variation rules still apply.
- Keep generated buildings as **instances** of kit modules; realize only for export steps that require merged meshes.

## 7. Dressing & variation

- Dressing layers: street furniture on rhythm rules from the metrics (lights every 25–50 m, trees 6–9 m, benches/bins near nodes), vehicles (parked density by street type), signage and shopfronts (the strongest cultural/era signal), vegetation, clutter and decals (stains, graffiti, puddles, cracks) concentrated at edges, corners and ground floors.
- **Break repetition** in the order of `modular-kits-and-wfc.md` §8 (texture variants first — the cheapest — then geometry variants, glue pieces, hero moments). Players notice repeated *details* (a distinctive sign, a broken window) far faster than repeated architecture.
- Density gradients: activity and clutter increase toward nodes and commercial streets; calm stretches between them.

## 8. Scene & file management in Blender

Library relocation, override resync, versioning and naming lint: `project-files-and-naming.md` §2, §4, §5 and §6 respectively; `scripts/naming_lint.py`.

- **Files**: one `.blend` per kit (`kit/<family>.blend`), per hero building, and per district (`districts/<name>.blend`), linked into a master assembly file; lanes can then work in parallel without touching the same file. Mark kit pieces as assets (`scripts/asset_library.py`) so dressing uses the Asset Browser.
- **Hierarchy/naming**: `DIST_Harbor / BLK_014 / BLD_014_03`; kit pieces named per `modular-kits-and-wfc.md` §1 (`KIT_Brick_Wall_4m_A`, grid size in the name). Library overrides only work reliably when all needed collections sit under one linked root collection.
- **Memory**: linked duplicates and collection instances share data; GN instances stay cheap until realized. Only **excluding** a collection from the view layer (checkbox) frees evaluation memory — hiding in viewport doesn't. Distant districts: Viewport Display → Bounds. Render → Simplify (max subdivision, texture limit, Cycles camera/distance culling).
- Save a lightweight **greybox layer** that stays in the master file for layout and camera work even after detailed districts exist.

## 9. Coordinates & precision

- Blender object transforms are single precision: position steps are ≈ 0.1 mm at 1–2 km from origin, ≈ 0.5 mm at 4–8 km, ≈ 2 mm at 16–32 km — vertex jitter, snapping errors and z-fighting appear on detailed geometry far from origin. Godot's guidance: stay within ≈ 4 km (first person) / 8 km (third person) without double-precision builds; Unreal 5 has large world coordinates.
- Model each district near its own local origin (within ~2–4 km), store its world offset on the district root empty or a custom property, and apply the offset at assembly or in the engine.
- Viewport depth precision is separate: raise Clip Start (≥ 0.1 m) and lower Clip End for big scenes to avoid flickering surfaces.

## 10. Engine-side authoring

| Engine | Large-world systems | What to author in Blender |
|---|---|---|
| Unreal 5 | World Partition (streaming grid), HLOD layers (instancing / merged / simplified), Level Instances and Packed Level Actors for repeated buildings, Nanite, large world coordinates | kit pieces exported one per asset at grid-exact size and consistent pivots; placement via instances, not merged cities; Nanite-friendly meshes (smooth normals, few hard edges, avoid stacked coplanar layers and masked materials); collision `UCX_<Mesh>_##` in the same FBX; lightmap UVs only for baked-lighting targets |
| Unity 6 | LOD Groups (`_LOD0.._LODn` names; LOD naming and ratio rules: `game-engine-delivery.md` §4), GPU Resident Drawer / GPU instancing, occlusion culling, additive scenes/Addressables per cell | avoid static batching on thousands of repeated pieces (it copies meshes); author occluder-friendly solid building shells; LODs by name suffix; simple collision meshes |
| Godot 4 | visibility ranges as HLOD (near: individual buildings; far: merged block mesh), MultiMesh (culled as one cluster — keep clusters block-sized), import name hints (`-col`, `-convcol`, `-colonly`, `-occ`, `-navmesh`) | author merged per-block proxy meshes; split MultiMesh clusters spatially; suffix-named collision/occluders |

- Export a **placement manifest** (JSON/CSV of instance transforms + kit piece IDs) so the layout can be rebuilt as engine instances rather than a giant merged mesh.
- Budget per streaming cell, not per city: tris, draw calls/materials, unique textures, instance counts.

## 11. Review & common failures

Review: all shot/player cameras with human/car/bus dummies; street-level walk or drive-through; skyline silhouette from player height; aerial layout check against the district plan; repetition scan (same module/detail twice in one view); far-distance shot with LOD/HLOD active; performance numbers per cell.

- Detailing buildings before layout, metrics and kit grid are frozen.
- Streets and lots at the wrong scale (5 m lanes, 2.4 m floors, 3 m doors); footprints not multiples of each other.
- Uniform density and height; no gradients, landmarks, or open spaces.
- Every block at hero detail; no silhouette/proxy tier.
- Visible repetition of distinctive details; one façade module everywhere.
- One giant `.blend` that blocks parallel work; hidden-but-evaluated collections eating memory; realized instances.
- Geometry tens of km from origin; static batching or oversized MultiMeshes in engines; no HLOD for unloaded cells.
