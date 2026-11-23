# Modular Kits & Tilesets (grid-based games, Wave Function Collapse)

A modular kit is a **contract**: every piece obeys the same grid, footprint multiples, pivot rule, wall/floor placement rule and border profiles, so any valid combination joins without gaps, overlaps, z-fighting or shading seams. Write the contract first, build a few pieces, stress-test layouts, and only then detail. For procedural generators (WFC and other constraint solvers) the contract becomes machine-checkable: border profiles → sockets → adjacency rules. Profile: `project_state.py init --profile modular-kit`. This file is the canonical home for kit grids, pivots, piece lists, trim sheets and kit seams; `environment-modeling.md`, `kitbashing.md` and `large-sets-and-cities.md` point here. Texel density targets: `uv-unwrapping.md`.

## Contents
1. The grid spec
2. Wall & floor placement, pivots, corners
3. Piece lists
4. Tileset theory: which tile set for which job
5. WFC: models, sockets, adjacency
6. Designing kits that don't contradict
7. Authoring in Blender & validating
8. Seams, UVs, materials, collision
9. Stress tests
10. Engine & generator integration
11. Common failures

## 1. The grid spec

Voxel kits: the voxel size must divide the module; verify with `scripts/voxelize.py --check` (`voxel-and-pixel-art.md` §1; the script in `voxel-and-pixel-art.md` §3).

Write this block into NOTES.md and freeze it:

```
Unit: 1 BU = 1 m (Unity/Godot: 1 unit = 1 m; Unreal: 100 uu = 1 m)
Module (footprint): 4 m × 4 m, height 4 m   ← main pieces
Sub-modules: 2 m and 1 m (whole divisors); detail snap 0.5 m, fine 0.25 m
Character: 1.8 m; door opening 1.2 × 2.2 m (game-wide standard); window 1.2 × 1.4 m, sill 0.9 m
Wall thickness 0.2 m, placement: CENTERED on cell boundary (each tile owns 0.1 m) | INSET inside cell
Floor slab 0.2 m (never paper-thin), top of floor at Z = 0
Pivot: bottom-center of cell (tiles) | wall mid-length on grid line (wall pieces)
Rotation: Z only, 90° steps; mirroring allowed? yes/no
Texel density: 512 px/m; trims: MAT_Trim_Concrete_A (2048²)
Naming: KIT_<family>_<piece>_<size>_<variant>   e.g. KIT_Brick_Wall_4m_A
```

- **Footprints must be whole multiples of each other** (4 m rooms with 2 m corridors tile forever; a 3 m piece in a 4 m kit eventually creates gaps/overlaps). Designers snap at half the main footprint; keep snap sizes as large as possible.
- Common module choices: 1/2/4 m (Unreal-style 100/200/400 uu), 3 m cubes (character-scale interiors), 50 cm grid for small/variation pieces. Pick from the gameplay metrics (character, camera, door, jump, cover heights), not from habit.
- Fix door/opening sizes game-wide so different kits connect without unique transition pieces. The 1.2 × 2.2 m door is a gameplay convention (oversized so characters and cameras traverse it cleanly), not a real door; real door and opening dimensions are in `archviz-modeling.md` §3.

## 2. Wall & floor placement, pivots, corners

| Rule | Pros | Cons |
|---|---|---|
| **Centered on the cell boundary** (each tile holds half the thickness) | border cross-sections match their mirror → symmetric sockets; fewer unique pieces; one corner piece works inside and outside | wall thickness split across two tiles; single tiles look "half-thick" in isolation |
| **Inset inside the cell** (surfaces e.g. 0.1 m inside the footprint) | back-to-back walls never share a plane (no z-fighting); pieces self-contained | needs dedicated inner/outer corner pieces or caps/pillars ("flanges") to hide overlaps and gaps |

- **For WFC/tile generators prefer centered**: it makes border profiles symmetric and rotation-friendly.
- Pivots: tiles at **cell center or bottom-center**, so rotating a tile never needs a translation; wall pieces at mid-length on the grid line (edge pivots make corners and junctions painful). Decide before production — changing pivots later means fixing every placed instance.
- Floors/ceilings: fixed slab thickness so stacked levels are never coplanar.

## 3. Piece lists

- **Architecture kit**: floor, ceiling, wall (solid), wall with single/double doorway, wall with window, corner (in/out or unified), T and cross junctions, end cap, pillar/flange, stairs (straight, landing), ramp, floor edge/ledge, roof edge/parapet, transition pieces between sub-kits, **damaged/variant** versions, **filler/glue** pieces (trim strips, pipes, cable runs that hide joins).
- **Terrain/tile kit**: see §4 for how many tiles a scheme requires.
- **Road/pipe kit** (edge-based): straight, curve, T, cross, end, plus slope variants.
- Build the minimum set that passes the stress tests (§9) first; variants come after.

## 4. Tileset theory: which tile set for which job

| Scheme | Tile identified by | Tiles (no symmetry → with Z rotation) | Use for |
|---|---|---|---|
| Wang / edge tiles | 4 edges, 2 states | 16 → 6 | roads, pipes, rivers, fences, walls-as-lines |
| Marching squares / corner tiles | 4 corners, 2 states | 16 → 6 | terrain regions, cliffs, building footprints (solid/empty areas) |
| Blob (edges + corners) | 8 neighbors with corner-only-if-both-edges rule | 47 (from 256) | 2D top-down autotiling of a single terrain type |
| 3-state corners | 4 corners, 3 states | 81 | two terrain types + empty |
| Marching cubes | 8 cube corners, 2 states | 256 → 70 with Z rotation, 55 with Z rotation + mirror (15 "classic" cases assume full rotation + inside/outside complement, which art tiles can't use because gravity and solid≠air) | volumetric buildings/terrain in 3D (Townscaper-like) |
| Dual grid | tiles placed at the corners of the logical grid (half-cell offset), chosen by the 4 (2D) or 8 (3D) surrounding cell values | 16 → 6 (2D) | smooth curved terrains/buildings from a simple cell painting; keep gameplay logic (collision, navigation, objects) on the main grid |
| Quarter tiles | each cell split in 4 quarters | 5 with rotation | cheapest art budget; curves limited to half a tile |

Irregular grids (Townscaper): tiles authored in a unit cube and **deformed** into each relaxed quad cell — author border profiles that survive bilinear deformation (straight vertical borders, no detail crossing the cell boundary). Triangle/hex prism grids need fewer tiles for some shapes; solvers such as Tessera/Sylves support them.

## 5. WFC: models, sockets, adjacency

- **Overlapping model** (mxgmn/WaveFunctionCollapse): learns N×N patterns from an example bitmap/voxel sample — good for textures and 2D maps, not for authored 3D kits.
- **Simple tiled model**: explicit tiles + adjacency rules. mxgmn's XML: `<tile name="corner" symmetry="L" weight="0.5"/>`, `<neighbor left="corner 1" right="empty"/>` (number = rotation 0–3); symmetry letters describe each tile's symmetry by the letter's own shape — **X** (1 orientation), **I** and **\\** (2), **T** and **L** (4), **F** (8, rotations + mirrors); `<subset>` selects tiles.
- **Socket-based 3D adjacency** (marian42, popularized by Martin Donald) — what `scripts/tile_sockets.py` generates:
  - each of the 6 faces of a tile has a socket derived from its **border profile** (the vertices lying on that cell face);
  - **horizontal** sockets: symmetric profile → `"0s"` (matches `"0s"`); asymmetric → `"1"` which matches its mirror `"1f"`; empty face → `"-1"`;
  - **vertical** sockets: `"v0_0"…"v0_3"` (profile id + rotation index; matches only the same id and rotation) or `"v0_i"` (rotationally invariant);
  - each mesh yields up to 4 **prototypes** (Z rotations 0/90/180/270, duplicates removed), each with `mesh`, `rotation`, six sockets, `weight`, optional `constrain_to`/`constrain_from` (e.g. `"bot"` for ground-only tiles) and precomputed `neighbours` per direction;
  - optional **exclusion rules** ban pairs that match geometrically but look wrong (two doors facing each other, a roof next to a wall top).
- **Solver features worth using** (DeBroglie/Tessera, Unreal's WFC plugin): weights (control room size, make T-junctions rare for clean roads), fixed tiles (entrances, authored set pieces), border/ground constraints, max-consecutive, count and separation constraints, **path constraints** (connectivity — plain WFC has no global structure), backtracking (the original mxgmn solver restarts instead), multi-cell big tiles (hide the grid), per-biome tile subsets.

## 6. Designing kits that don't contradict

- **Every socket needs a partner** in every direction it can face, including after rotation — `tile_sockets.py` reports orphans; an orphan socket means that tile can only appear where the solver gets lucky, or never.
- Always include **empty/air** and **solid/ground** tiles, plus **transition/filler** tiles for socket pairs that otherwise meet only through rare tiles.
- Constrain the vertical axis: ground tiles only on the bottom layer, air/roof at the top, foundations wider than tops.
- **Support is not implied by sockets.** An empty bottom face (`-1`) matches an empty top face (`-1`), so a platform or roof slab can legally sit on air — the socket test solved layouts with floating slabs and 0 seam errors. Give load-bearing faces their own vertical sockets (e.g. `v2_i` = "needs support" on a slab's bottom, matched only by tops of pillars/walls/ground), or add a solver support constraint, and review solved layouts from the side for floating pieces.
- Keep the number of socket types small and deliberate: too many → dead ends and frequent contradictions; too few → structureless noise. Name profile families in NOTES.md (e.g. `0s` = open floor edge, `1/1f` = wall-with-trim edge, `2s` = full wall face, `v0_i` = flat floor, `v1_*` = stair opening).
- Borders are the design surface: model a small set of **border templates** (exact cross-sections) and snap every tile's border to them; detail stays inside the cell.
- Add weights and constraints only after the raw kit solves reliably on several seeds.

## 7. Authoring in Blender & validating

- Scene units meters; snapping to Increment with **Absolute Grid Snap**, grid scale = module (or half); vertex snapping for border verts; applied transforms on every tile.
- One object (or one Empty with mesh children) per tile, in a `KIT_<name>` collection; origin per the grid spec; exact cell dimensions; custom properties for authored metadata (`tile_weight`, `tile_rotations`, `constrain_to`, `tile_overhang`).
- **Border templates** as a hidden collection of profile curves/meshes to snap against; Weighted Normal or Data Transfer from a shared border template to keep normals identical across partner borders.
- Validate and generate rules:
  ```bash
  blender -b kit.blend --python scripts/tile_sockets.py -- --collection KIT_Tiles --cell 2 2 2 \
      --pivot BOTTOM_CENTER --quantize 0.01 --out kit_rules.json --preview
  ```
  It flags unapplied transforms, geometry outside the cell, off-grid border vertices, pivot violations, duplicate names, and orphan sockets; invalid tiles are left out of the rules unless `--include-invalid`; writes prototypes with sockets, rotations, weights and neighbour lists (prints `TILE_SOCKETS {json}`; live: set `TILE_OPTS` before exec); `--preview` lays out every prototype for a visual check. Read the orphan list before anything else. Tested on a 15-tile kit: WFC layouts solved from the rules on 3 seeds had 0 border-vertex mismatches across ~150–190 joins.
  Limits to know: profiles include **edges**, so partner borders need identical edge splits, not just the same outline — snap borders to shared templates; the pivot check is bounds-based (a thin slab can satisfy two conventions); rotation variants are disabled when cell X ≠ Y; "never placeable" pruning looks at horizontal sides only — vertical rules (ground on the bottom layer, open sky on top) belong in the solver's constraints (`constrain_to`/border constraints).
- Preview layouts in Blender: Geometry Nodes Grid → Instance on Points → Collection Info (Separate Children, Pick Instance) with 90° rotation steps for random stress layouts; or feed `kit_rules.json` to a solver and instantiate its output as linked duplicates.
- Manage the kit in the Asset Browser with a catalog per kit/sub-kit (`scripts/asset_library.py mark`; catalogs, import methods and linking: `kitbashing.md` §5).

## 8. Seams, UVs, materials, collision

- **Border vertices** of partner sockets identical (quantized to the grid); don't rely on merge-by-distance at export — pieces join by exact position.
- **Normals** identical across partner borders (shading seams otherwise); avoid mirrored UVs crossing borders (tangent seams).
- **Textures**: tiling materials for large surfaces + **trim sheets** for detail — one texture of horizontal strips (bevels, panels, moldings, bolts) mapped by UV-placing faces onto the strips; scale UVs only by whole factors (1.4× creates visible seams); world-aligned/triplanar projection hides seams entirely but still needs lightmap UVs; one texel density across the kit (targets, e.g. 512 px/m environment / 1024 px/m hero: `uv-unwrapping.md`).
- **Lightmaps** (baked-lighting targets only): second non-overlapping UV channel per piece.
- **Repeated modules** stay collection instances / linked duplicates. **Break repetition** in this order: texture/material variants (world-position tint, vertex-color blend masks, decals — not unique textures per piece), then 2–3 geometry variants per module, rotation/mirroring where plausible, irregular glue pieces at corners, unique hero moments.
- **Collision**: simple per piece (boxes/convex), engine naming (`UCX_` Unreal, `-col`/`-colonly` Godot); navigation meshes where the engine imports them.

## 9. Stress tests

Before texturing or detailing, build at least 3 different layouts by hand and review them (screenshots from player height + top view) — missing pieces show up immediately:
- **Loopback**: a closed loop through every sub-kit and back to start — misalignment means the footprint is wrong; fix the grid, not with patch pieces.
- **Stack**: multiple floors, stairs between them, rooms above corridors — no coplanar floor/ceiling, stairs land on grid.
- **Gap**: places where pieces should meet at odd combinations (outside corner next to doorway, T junction next to window).
- **All rotations adjacent**: every tile next to every compatible prototype (generated preview or solver output).
- **Unintended shapes**: pillars from corners, courtyards, dead ends — kits get used in ways you didn't plan.
- **Solver runs** (WFC kits): ≥ 3 seeds on a representative grid size; record contradiction/restart rate; inspect seams in the instantiated result (border vertices coincide, no cracks).

## 10. Engine & generator integration

- **Export**: one mesh per tile (FBX/glTF), origin per spec, applied transforms, exact size; metadata via glTF "Include → Custom Properties" (node/mesh `extras`), FBX custom properties (read in Unity with `AssetPostprocessor.OnPostprocessGameObjectWithUserProperties` — test the round trip), or a sidecar JSON (`kit_rules.json`).
- **Godot GridMap**: build a scene with a Node3D root and one MeshInstance3D child per item (each with at most one StaticBody3D + CollisionShape3D and one NavigationRegion3D), materials on the **mesh** (node overrides are ignored), Scene → Convert To → MeshLibrary; GridMap cell size = kit module (consider unchecking Center Y). Importing a MeshLibrary directly from glb ignores collision suffixes — use the inherited-scene route.
- **Unity**: Tessera (DeBroglie-based; paint adjacency on 9 sub-faces per tile face; cube/hex/triangle grids; path/count constraints; backtracking; chunked infinite generation) or a custom solver reading `kit_rules.json`.
- **Unreal**: built-in Wave Function Collapse plugin (experimental; `TileSize` in cm, constraints map, weights, spawn exclusion, can derive constraints from an example actor layout); third-party WFC plugins may conflict by name.
- Custom solvers: `kit_rules.json` neighbour lists are directly usable as the propagation table.

## 11. Common failures

- Footprints that aren't whole multiples → drifting gaps/overlaps; pivots changed mid-production; origins that force a translation on rotation.
- Coplanar walls/floors (z-fighting); paper-thin floors; outside-corner gaps and inside-corner overlaps from inset walls without corner/flange pieces.
- Unapplied scale/rotation; cm/m mismatches between Blender and engine.
- Border vertices slightly off-grid → sockets don't match, hairline cracks, lighting seams; different normals across a border.
- Asymmetric borders not marked flipped, non-invariant vertical sockets marked invariant → impossible or wrong adjacencies.
- Orphan sockets, missing empty/ground tiles, no vertical constraints → frequent contradictions.
- Floating platforms/roofs because empty vertical sockets match each other — seam checks pass, gravity doesn't.
- Too many unique sockets (dead ends) or too few (noise); expecting global structure from WFC without path constraints.
- Detailing before stress tests; repeated distinctive details; encoded piece names nobody can read.
- Engine import traps: Godot materials on nodes, glb MeshLibrary dropping collision, FBX custom properties silently missing.
