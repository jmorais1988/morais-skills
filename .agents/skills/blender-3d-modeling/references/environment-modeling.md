# Environment Modeling (terrain, rocks, water, roads, modular kits, scatter, atmosphere)

An environment is judged from a camera, not a turntable. It succeeds when its **composition, scale and density read correctly from the intended viewpoints** and fails when every asset is individually fine but the scene looks like assets placed on a plane. Plan from the shot and the biome rules outward; model assets last. Profile: `project_state.py init --profile environment`.

## Contents
1. Brief & reference study
2. Camera, scale & detail tiers
3. Blockout & composition
4. Terrain
5. Rocks & cliffs
6. Water
7. Roads, paths, tracks, walls along curves
8. Modular kits & trim sheets
9. Scattering
10. Atmosphere & lighting
11. Performance & game export
12. Review & common failures

## 1. Brief & reference study

Add to the usual target questions: **viewpoints** (fixed render camera, player eye height and path, drone/aerial, driving camera), **playable/visible extent** (m²), **time of day / weather / season**, **biome & geography** (latitude, altitude, climate, geology), **realism vs stylization**, **engine terrain or mesh**.

References per layer, into `references/`: `00_overall` (establishing shots, mood), `01_terrain` (landform, erosion, soil color), `02_rocks` (geology close-ups — strata, fracture pattern, weathering), `03_vegetation` (per species, see `flora.md`), `04_water`, `05_manmade` (roads, fences, ruins, props), `06_ground_closeup` (debris, leaf litter, tire ruts), `90_materials`, `98_lighting` (sky, fog, sun angle).

Write a **biome rules table** in NOTES.md — this is what the scatter masks implement, so derive it from references, not taste:

| Element | Where it grows/lies (slope, altitude, moisture, sun, proximity) | Density & clustering | Scale range | Orientation |
|---|---|---|---|---|
| Pine | slope < 30°, 800–1600 m, north faces denser | clustered groves, gaps 5–20 m | 8–25 m | world up |
| Boulders | below cliffs (talus), slope 25–40°, stream beds | clumps of 3–7, size sorted downhill | 0.3–3 m | half-buried, aligned to normal 50 % |
| Grass | slope < 35°, not on paths/rock, shade thins it | continuous, noise-modulated | 0.2–0.6 m | normal 30 % |

## 2. Camera, scale & detail tiers

- Put the camera(s) and a **1.8 m human + a vehicle dummy** in the scene before anything else; every review shot keeps them visible. Scale mistakes are the #1 environment failure (5 m-tall grass, 40 cm bricks).
- Player/eye height ≈ 1.6–1.7 m; driving camera ≈ 1.2–2.5 m behind/above; FOV per target (render 35–50 mm; games 60–90° horizontal).
- **Detail tiers by distance** (decide per camera):
  - *Foreground / hero* (0–10 m): unique geometry, sculpted relief, unique or high-res textures, decals, close debris.
  - *Midground* (10–100 m): modular kits, tiling materials with macro variation, instanced vegetation.
  - *Background* (100 m+): low-poly silhouettes, cards/impostors, HDRI or matte painting, atmospheric perspective carries depth.
- Spend geometry where the camera looks and where silhouettes cut the sky; spend nothing on what is occluded.

## 3. Blockout & composition

1. Grey-box the landform and big masses (terrain plane, primitive mountains, cube buildings, cone trees) at scale.
2. Set **sun direction early** — it decides which faces are lit, where shadows guide the eye, and which slopes are sunny (vegetation rules).
3. Compose from the camera: foreground frame element, midground subject, background silhouette; leading lines (roads, rivers, ridges) toward the focal point; value grouping (dark foreground, lighter hazy background).
4. Render grey-box shots (Workbench/EEVEE) and compare to the mood references at thumbnail size before building assets. Changing a mountain is cheap now.

## 4. Terrain

| Method | Use when | Notes |
|---|---|---|
| **Displace** modifier on a subdivided grid (procedural or heightmap image) | most render terrains; editable | `direction='Z'` (avoids overhang self-intersection), heightmap as 16-bit PNG/EXR, Non-Color, `strength` = height range in m, `mid_level` = sea-level value; OBJECT coords for procedural |
| **Geometry Nodes** (Grid → Set Position with noise stack; store masks as attributes) | parametric, want slope/height masks as attributes for materials & scatter | expose seed/scale/height; keep instancing downstream in the same tree or a second modifier |
| **Sculpt** on multires/remeshed plane | hero landforms, riverbanks, ruts, localized edits | combine: Displace for macro, sculpt layer for hero areas |
| **A.N.T. Landscape** extension | quick noise landscapes | extension since 4.2 (limited support) — check installed; apply result then refine |
| **Real DEM** via BlenderGIS (GeoTIFF/SRTM) | real locations | SRTM ≈ 90 m/px public (30 m US) — add procedural detail on top |
| External erosion (Gaea, World Machine, Instant Terra) | believable erosion/flow channels | import heightmap + flow/deposition masks as Non-Color images |

- Believability comes from **erosion logic**: water flows downhill in branching channels, deposits at slope breaks, talus collects under cliffs, ridges are sharper than valleys. Pure noise terrain reads as "CG noise"; at minimum use ridged noise for ridges plus a smoothed low-frequency base, and sculpt drainage channels.
- Resolution: vertex spacing ≤ the smallest landform the camera must read (hero ground 0.1–0.25 m near camera, 1–4 m far). Use a denser patch near the camera instead of densifying everything; or adaptive subdivision (Cycles, experimental) with true displacement.
- **Terrain material** = masks, not one texture: rock where `Geometry Normal Z` < cos(slope) (Map Range for a soft transition), snow/grass by `Position Z` bands with noise-broken edges, dirt in concavities (AO/Pointiness or a baked curvature), paths/tire tracks from a painted mask or distance-to-curve attribute, wetness near water. Use **Box projection** (blend 0.1–0.3) or triplanar for steep faces so textures don't stretch; add a **macro variation** layer (large-scale noise into color/roughness) to kill tiling. Recipes: `procedural-materials.md` §1; node-tree rules: `shader-nodes.md` §2.
- Game engines: export a heightmap (engine-recommended resolutions, e.g. Unity 2ⁿ+1) and splat masks rather than a mesh; sculpt/paint in the engine's terrain tool if the pipeline expects it.

## 5. Rocks & cliffs

- Rocks are **planes and fractures**, not blobs. Workflow: cube/icosphere → Voxel Remesh → sculpt with planar/trim brushes (Flatten, Scrape, Trim tools) to cut facets → chip edges (Clay Strips/Pinch) → Displace with Voronoi (distance) + noise at two scales for fine fracture. Or boolean-fracture a volume (Cell Fracture extension) and pick good fragments.
- Geology decides shape: sedimentary → horizontal strata bands and blocky breaks; granite → rounded, exfoliating shells; basalt → hexagonal columns; slate → thin plates; river rocks → smooth ellipsoids.
- **Kit**: 5–9 rocks (large/medium/small, flat/tall variants) + 2–3 cliff pieces; reuse via rotation (rocks have no up), scaling within ±30 %, burying. Bake high → low for games (`scripts/bake_maps.py --source`).
- Placement: bury 10–30 % into terrain (never resting on points — floating rocks are the classic failure; `scene_gates.py` attachment check on hero rocks), small rocks cluster around big ones and downhill of cliffs, moss/dust on upward faces (normal Z mask, world space so it stays "up" after rotation).
- Cliffs: layered modular pieces overlapping into each other; hide seams with vegetation and rubble; vertical box-mapped materials.

## 6. Water

Stylized/toon water (flat color, shoreline foam band): `stylized-npr.md` §5.

- **Ocean / large lakes**: Ocean modifier — `resolution` R gives a (R·16)² simulation grid; `spatial_size` in m; lower `depth` = choppier shallow waves; `choppiness` sharpens crests; wind velocity m/s; animate `time`. Foam/spray need a named color attribute layer to reach the shader.
- **Water shader**: Principled, Transmission 1, IOR 1.333, Roughness 0.02–0.1, Base Color near white; depth color via Volume Absorption on the Volume output (or a separate volume body); animated normal from two scrolling noise/wave layers at different scales and directions; shoreline foam from a proximity mask (GN Geometry Proximity to terrain, stored attribute).
- **Rivers**: a strip mesh along a curve (Array + Curve, `modifiers-and-curves.md` §3) with UVs running along the flow → scroll the normal/foam texture along V; carve the riverbed into terrain first; wet dark band on banks; rocks break the flow (foam masks downstream).
- Waterfalls: stacked scrolling alpha cards + mist volume/particles; puddles: flat planes with low roughness and a mask, slightly below ground.

## 7. Roads, paths, tracks, walls along curves

- Draw a curve on the terrain (snap to face) → road strip unit + Array + Curve → **Shrinkwrap** (PROJECT along −Z, small offset) to follow terrain → Weld; or GN Curve to Mesh with a road profile + Raycast/Geometry Proximity to snap Z.
- **Flatten terrain under the road**: GN — Geometry Proximity to the road curve → falloff (Map Range) → blend terrain Z toward the curve's Z. Add shoulders/ditches as profile shape.
- **Offroad tracks / tire ruts**: sculpt or displace two parallel grooves along the path curve (distance-to-curve mask offset by ± half the vehicle's track width) with raised berms, plus a decal/mask for compressed darker soil and puddles in ruts. Starting numbers (measure the actual vehicle): track width 1.4–1.8 m center-to-center, groove width ≈ tire width 0.25–0.35 m (wider when churned), depth 3–8 cm on firm dirt, 10–25 cm in mud, berms 2–8 cm high and about one groove-width wide; a raised grassy crown between ruts on little-used trails; tread imprint as a tiling normal/height decal along the groove UVs.
- Walls, curbs, fences, guardrails: Array + Curve for continuous pieces, GN Resample + Instance on Points for posts; add randomness in tilt/scale for old or rural structures.

## 8. Modular kits & trim sheets

Walls, ruins, stairs and other man-made midground pieces are a modular kit: grid module, pivots, piece list, trim sheets, seams and stress layouts follow `modular-kits-and-wfc.md` (§1–3, §8–9); texel density targets: `uv-unwrapping.md`. Towns and cities: `large-sets-and-cities.md`; part libraries: `kitbashing.md`.

## 9. Scattering

Tools: `scripts/scatter_on_surface.py` (GN, 4.2+; slope/height/vertex-group masks, Poisson min distance, pick-instance, random yaw/tilt/scale), Blender 5.0+ **Scatter on Surface** modifier (`modifiers-and-curves.md` §6), Geo-Scatter (paid; free Biome-Reader) if installed.

1. **Implement the biome rules table as masks**: slope (normal Z), altitude (position Z), painted vertex groups (paths, clearings, art-direction), proximity (distance to water/roads/rocks via GN Geometry Proximity stored as attributes), noise-modulated density for **clustering** — natural distributions clump; uniform Poisson everywhere reads CG.
2. **Layers large → small**, each its own scatter: trees/boulders → bushes/medium rocks → grass/flowers → debris/litter. Smaller layers are **excluded** from inside larger instances' footprints (paint or proximity mask) and denser around their bases (leaf litter under trees, pebbles around boulders).
3. Per layer: Poisson `min_distance` ≈ instance footprint; scale range with rare outliers; random yaw always; align-to-normal 0 for trees (they grow up), 0.3–1 for rocks/debris/grass; sink 5–20 % into ground.
4. **Variation**: ≥ 3–5 variants per element, per-instance color variation in the material (Object Info → Random or the instance `id`), mix of dead/dry variants.
5. Keep instances **unrealized**; realize only for export formats that require it.
6. Check density from the camera, not from above: grass that looks full from top view is sparse at grazing angles, and vice versa.

## 10. Atmosphere & lighting

- Sky: HDRI (Poly Haven CC0) for real lighting quickly, or **Sky Texture** — in 5.0 Nishita became "Single Scattering" (legacy) and a new **Multiple Scattering** model was added ("Dust" → "Aerosols"); both are physically bright, lower Exposure. Match the Sun light's angle to the sky's sun.
- **Aerial perspective** is the strongest depth cue: distant values lighter and shifted to sky color. Use a volume **object** (cube around the scene, Principled Volume density ≈ 0.001–0.02, anisotropy 0.3–0.7 for sun shafts). In EEVEE 4.2+ a *World* volume blocks sun and world lighting — use an object volume instead. Cycles volumes are expensive: test with low samples, larger step rate.
- **Night skies for real-time (VR, games):** a painted star map smears every star over 1–2 texels and reads blurry up close. Draw the catalogue stars (e.g. Hipparcos, V ≤ 7, positions + magnitude + B−V colour) as one mesh of camera-facing additive sprites with an analytic Gaussian falloff (no texture), and keep only the diffuse Milky Way and the faint stars painted. Pitfalls:
  - Never guess the panorama's longitude origin, direction and mirroring. Render the sky as the engine shows it, detect stars, match catalogue pairs by angular distance (allow both handedness fits), refine with Kabsch, and use the fitted transform. In a left-handed engine (Unity) the correct sky has determinant −1 in raw coordinates, so a "mirrored" fit proves nothing: check one asterism's chirality in a render (seen from inside with north up, east is on the left).
  - Faintness is intensity, never sub-pixel size: keep a minimum sprite of ~1–1.5 display pixels (smaller shimmers), and cap the peak at 1.0 on LDR targets so brighter stars grow instead of clipping.
  - Calibrate flux per magnitude against the sky you're replacing, and match the painted layer's level to the old map. Published star-map layers aren't always on the same scale as their combined map: fit the weights (least squares) before summing.
  - Mask the sprite stars out of the painted star layer (radius by magnitude, stretched by 1/cos dec in equirect) so they don't appear twice.
  - Cull sprites below the painted horizon, measured from the panorama camera.
- Ground fog: volume object with density falling off by height (Gradient texture on Position Z → Map Range → Density).
- Lighting review uses the three look-dev views from `materials-and-lookdev.md` §7 plus the actual shot cameras at the planned time of day.

## 11. Performance & game export

- Instancing everywhere (GN instances, collection instances, Alt+D linked duplicates); one mesh datablock per unique asset.
- Viewport: display heavy scatter as bounds/points, GN viewport display percentage; **Simplify** (max subdivision, child particles, texture limit; Cycles camera/distance culling).
- Games: `_LOD0.._LODn` naming (Unity auto-creates LOD groups from FBX; LOD naming and ratio rules: `game-engine-delivery.md` §4), impostors/billboards for distant trees (Unreal Impostor Baker), draw-call budgets → shared materials and atlases across a kit, collision meshes (`UCX_` in Unreal) simplified per asset, terrain as heightmap. Budgets: `poly-budgets-and-targets.md`.

## 12. Review & common failures

Review shots: every planned camera + a player-height walk/drive sequence + one aerial; thumbnail value check; a distance shot to catch tiling and repetition; close-ups at ground contact (floating rocks/props, grass through roads); lighting at the planned time of day.

- Human/vehicle dummy missing → wrong scale discovered late.
- Flat plane with assets placed on it; noise terrain with no erosion logic.
- Uniform scatter density, no clustering, no exclusion zones, identical instance scale.
- Visible texture tiling on terrain from distance (no macro variation).
- Rocks and props floating or intersecting without burial; trees on 60° slopes; grass growing on roads and inside rocks.
- Everything equally detailed — no foreground/background hierarchy, no atmospheric depth.
- Realizing millions of instances; per-asset unique materials across a kit.
- Scatter run after props were placed puts rocks inside them (a tripod leg through a boulder): give placed props keep-out zones, or delete scattered pieces whose footprint overlaps a prop's, and remove their colliders too.
- Multi-leg stands (tripods, landing legs) placed from ONE ground sample under their centre float or sink on uneven ground (measured: feet 16 cm buried and 4 cm floating on a cave floor): ray-cast each foot, then move each leg's vertices by delta × t along the leg (t = 0 at the hub, 1 at the foot) so legs stay straight. A stand whose feet span more than ~15 cm of height, or that has no ground under a foot, should move to the nearest spot that passes, not be bent to fit.
- Smoothing creases in an irregular, decimated terrain with Laplacian/Taubin on z oscillates and made them steeper (dihedrals over 20°: 40 → 55). A bilateral height filter (Gaussian in XY ~1.2 m × Gaussian in height difference ~0.5 m) blended in by a soft zone weight removed them (33 → 5) without touching nearby cliffs. Measure dihedrals only between well-shaped, floor-like faces: slivers' normals are unstable, and a floor meeting a wall is a real edge.
  - Repeated bilateral passes still drag a rim or lip toward the lower side next to it (measured −0.9 m): keep the zone off rims, give wall vertices (n.z < 0.5) zero weight, and cap each vertex's change (e.g. 0.3 m).
  - Smoothing moves the ground under things standing on it: shift each rock (and its collider) by the ground's change under its centre. Sample that change from every floor vertex nearby (zero where nothing moved), not only from the moved ones: when only a few scattered vertices move, the nearest moved one can be metres away.
  - Z-only smoothing beside walls folds faces into knife edges, even with wall vertices at zero weight (measured: edges over 150° went from 2 to 37). Count edges whose faces are over 120° apart before and after every smoothing. Guard it: wherever a face turns more than ~55°, or an edge sharpens past 120°, halve the change at its vertices and repeat. A full revert there also brought back the floor creases the smoothing removed.
  - Make the step idempotent (a version flag on the mesh), and make prop seating measure the current mesh rather than re-apply a computed delta: a re-run otherwise doubles the change.

### Joining a heightfield terrain to a 3D cave or pit

- **Build the cave as one implicit surface** (signed field, marching cubes).
- **Join it to the terrain in ONE mesh.** Constrained Delaunay of a height grid plus the cave's boundary loop, weld, and quadric-decimate everything together with only the outer borders pinned, then `beautify_fill`.
  - Angle-walk zippers fold triangles.
  - Overlapping skirts bake black.
  - A dense pinned loop against coarse terrain makes a sliver fan.
- **Classify materials on normals averaged over ~1 m** and absorb small patches.
- **Bound "inside the tube" tests on every axis.**
