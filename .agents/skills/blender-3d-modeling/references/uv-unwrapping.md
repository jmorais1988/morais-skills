# UV Unwrapping, Texel Density and UDIMs

How to cut, unwrap, scale and pack UVs so textures and bakes come out clean: seams by object class, the 5.2 unwrap operators, texel density, padding (the padding table here is the authority for the whole skill), multiple UV sets and UDIMs, verified with `scripts/uv_tools.py`. Baking and the Substance Painter / Marmoset round-trip are in `baking-maps.md`. Numbers are Blender 5.2 unless a version is given; operator options below were verified with `get_rna_type()` in 5.2 and the helper scripts were tested headless on synthetic meshes.

## Contents
1. UV task protocol
2. Seam placement by object class
3. Unwrap operators (5.2)
4. Texel density
5. Packing, padding and multiple UV sets
6. UDIM workflow
7. Verification with `scripts/uv_tools.py`
8. Common failures

## 1. UV task protocol

1. Finish topology and **apply scale** (`Ctrl+A`); UV density math assumes 1 BU = 1 m.
2. Decide the **texture budget**: texture size per texture set (= material) and target density in px/m (§4). Decide UV-set roles: UV0 = textures, UV1 = lightmap (only for baked static lighting).
3. Mark seams (§2) — or let `uv_tools.py unwrap --seams SHARP+ANGLE` do it and then move path cuts to hidden sides.
4. Unwrap (§3), average island scale, straighten rectangular strips.
5. Set density and pack with pixel margins (§4–5), UDIMs if one tile can't hold the density (§6).
6. Check: `uv_tools.py check` must PASS (§7), then a checker render.
7. Bake or export for painting — `baking-maps.md`.

## 2. Seam placement by object class

A seam is a cut; every island must become a topological **disk** (one boundary loop, no handles). Open tubes and closed shells without seams cannot be flattened: Blender 5.2 prints *"Unwrap failed to solve 1 of 1 island(s), edge seams may need to be added"* and leaves a folded or unusable island.

| Object class | Where seams go | Why / notes |
|---|---|---|
| Hard surface (boxes, panels, machines) | On hard edges (≥ 30–60°), along the underside/back, where material or smoothing changes | Normal-map bakes need a UV split wherever the low poly has a hard edge (split normals); otherwise gradients bleed. Rule: **every sharp edge is a seam; not every seam is sharp** |
| Cylinders, pipes, handles | Caps cut at the rim; one straight seam along the side on the least-visible line (back, underside, facing a wall) | Side becomes a straight rectangle — straighten it (§3) so tiling/trim textures run along it |
| Organic (characters, creatures) | Hidden lines: inner arms/legs, under jaw, behind ears, along the back/spine under hair, around hands at wrists | Keep the face as one island; symmetric seams let you mirror |
| Clothing | Along real garment seams and hems | Painted details follow the real construction |
| Terrain, large planes | None or at chunk borders; use world-space projection instead of UVs where possible | Planar mapping has zero stretch on near-flat terrain |
| Rocks, scans, AI meshes | Smart UV Project or automatic seams, then check | Hand seams rarely pay off on noisy geometry |
| Architecture (archviz) | Per face orientation (box mapping) at real scale | Tileable materials; see `archviz-lighting-and-rendering.md` §4 for world-scale UVs |

**Mirrored / overlapping UVs** (symmetric game assets, repeated bolts, tiling trims): overlap mirrored halves or identical parts to double effective density. Only do this when:
- the texture has no baked **unique** information (AO, lightmaps, dirt that must differ left/right, text/decals);
- for normal-map bakes, shift the duplicate islands by exactly **+1 U** before baking (they bake from one side only; move back after), otherwise both copies write into the same pixels — when the neighbouring UDIM tile is occupied, use an unused tile row instead (`baking-maps.md` §4);
- the engine's tangent handedness handles mirroring (MikkTSpace does).
Never overlap in a lightmap UV set. `uv_tools.py check` reports whole-island mirrored (opposite winding) and stacked (same winding) duplicates as warnings, partial overlaps as errors; `--lightmap` makes all overlaps errors.

## 3. Unwrap operators (5.2)

All work headless in Edit Mode with faces selected (tested). Seams: `bpy.ops.mesh.mark_seam(clear=False)`; hard edges to seams: `mesh.edges_select_sharp(sharpness=radians(30))` then `mark_seam`; existing islands to seams: `uv.seams_from_islands(mark_seams=True, mark_sharp=False)` (use `mark_sharp=True` to make hard edges match UV splits).

| Operator | Key options (5.2 identifiers) | Use for |
|---|---|---|
| `uv.unwrap` | `method='ANGLE_BASED'\|'CONFORMAL'\|'MINIMUM_STRETCH'` (default CONFORMAL), `iterations=10` (Minimum Stretch), `use_weights`/`weight_group='uv_importance'`, `fill_holes`, `correct_aspect`, `use_subsurf_data`, `margin_method`, `margin`, `no_flip`, `use_original_bounds` (5.2: keep each island in its previous bounds instead of re-packing) | Seam-based unwrap. **Minimum Stretch** (4.3+, SLIM algorithm) gives the lowest distortion on organic shapes; Angle Based is fast and good for hard surface; Conformal (LSCM) is the classic |
| `uv.smart_project` | `angle_limit` (rad, default 66°), `island_margin`, `area_weight`, `rotate_method='AXIS_ALIGNED'\|'AXIS_ALIGNED_X'\|'AXIS_ALIGNED_Y'`, `scale_to_bounds` | Automatic cuts for scans, rocks, quick bakes; many small islands |
| `uv.lightmap_pack` | `PREF_CONTEXT='ALL_FACES'`, `PREF_PACK_IN_ONE`, `PREF_NEW_UVLAYER`, `PREF_BOX_DIV`, `PREF_MARGIN_DIV` | One island per face/quad group; wasteful but overlap-free lightmaps |
| `uv.follow_active_quads` | `mode='EVEN'\|'LENGTH'\|'LENGTH_AVERAGE'` (needs an active quad face) | Grid-straight strips from a quad loop (belts, pipes, trims) |
| `uv.align` | `axis='ALIGN_S'` (straighten), `'ALIGN_T'`, `'ALIGN_U'`, `'ALIGN_AUTO'`, `'ALIGN_X'`, `'ALIGN_Y'` | Straighten an edge chain |
| `uv.align_rotation` | `method='AUTO'\|'EDGE'\|'GEOMETRY'`, `axis` | Rotate islands upright |
| `uv.average_islands_scale` | `scale_uv`, `shear` | Equalise density between islands before packing |
| `uv.minimize_stretch` | `iterations`, `blend`, `fill_holes` | Relax distortion after unwrapping |
| `uv.select_by_winding` (5.2), `uv.select_overlap`, `uv.select_tile` (5.1) | `winding='NEGATIVE'\|'POSITIVE'`; `extend`; `tile=(u, v)` | Select flipped (mirrored) UV faces, overlapping faces, or everything in one UDIM tile before fixing them |
| `uv.copy_mirrored_faces` | `mesh_axis='POS_X'…`, `uv_axis='X'\|'Y'`, `precision` | Copy UVs to the mirrored half |
| `uv.pack_islands` | §5 | Packing |
| `uv.cube_project`, `uv.cylinder_project`, `uv.project_from_view` | `cube_size`, `radius`, `scale_to_bounds` | Projections for simple primitives / decals |

Scripted route: `scripts/uv_tools.py unwrap --seams SHARP+ANGLE --angle 30 --method MINIMUM_STRETCH` marks seams from sharp edges and dihedral angle, then adds the **minimum cuts to make every chart a disk** (open tube → one side seam; closed shell → one shortest cut; handle/torus → tree-cotree cut graph) and averages island scale. Tested: cube 12 seams + 0 extra; 32-side cylinder 64 seams + 1 extra side seam; UV sphere 16-edge cut; torus (48×12) 60-edge cut graph → one island, check PASS (without cuts: angle stretch 2.53). A sphere cut into one island still has angle stretch 0.44 — doubly curved shapes need more seams (or accept the stretch on hidden areas). Extra cuts follow the shortest path, not visibility — for hero assets move them or mark seams by hand and use `--seams KEEP`.

## 4. Texel density

Density = pixels per metre of surface: `px/m = sqrt(UV area / world area) × texture_px`. Always talk in **px/m** (10.24 px/cm = 1024 px/m). Typical targets [unverified: common studio practice, confirm with the project's art bible]:

| Target | Density | Typical texture |
|---|---|---|
| Mobile / far background props | 128–256 px/m | 512–1024 atlas |
| PC/console third-person environment | 512 px/m | 2048 per large prop or tiling |
| PC/console first-person / hero props | 1024 px/m | 2048–4096 |
| Hero weapons / close-up characters (games) | 2048+ px/m (1st-person weapons often 4096 px/m) | 4096 or UDIMs |
| Archviz real-time | 512–1024 px/m on unique bakes; tiling materials instead of unique UVs for large surfaces | trims/tiling |
| Film / offline hero | 4096–8192+ px/m via several 4k–8k UDIM tiles | UDIMs |

Rules:
- **Unify across parts** that are seen together (a door and its frame; all parts of a kit). A 2× density jump reads as a blurry part next to a sharp one. Kits: `scripts/asset_library.py audit --texel-target` flags part outliers; islands: `uv_tools.py check --target`.
- **Per asset vs scene**: pick one scene density per camera distance class and scale each asset's texture size to hit it, rather than giving every asset a 2048 texture.
- Deliberate exceptions: hidden undersides/insides at ½–¼ density; faces and hands at 1.5–2× on characters.
- Hitting a density: `uv_tools.py density --target 512 --texture-px 2048` scales every island exactly to the target and packs **without rescaling**. If islands don't fit (UV area > 0.5 of the tile) it reports tiles needed, the single-tile texture size, and the achievable density, and with `--udim` spreads islands over UDIM tiles. Tested: cube + cylinder at 256 px/m @1024 → all 9 islands 256.0 px/m, total UV area 0.497. The texture size a density needs over N tiles is derived in `baking-maps.md` §3.
- **Checker verification**: `bpy.ops.image.new(name="Checker", width=1024, height=1024, generated_type='UV_GRID')` (or `'COLOR_GRID'`) on an Image Texture node; squares must be square (stretch) and equal size across parts (density).

## 5. Packing, padding and multiple UV sets

Lightmap UV2 for engines: the bake pipeline in `game-engine-delivery.md` §6 and the lightmap recipe at the end of this section. Atlas repacking (merge objects → one UV set → rebake) for mobile/VR delivery: `web-and-mobile-delivery.md` §5, automated with `scripts/atlas_bake.py`. Margin vs mip bleed, measured there: a 0 px gap bled 59/255 into neighbouring islands, an 8 px gap stayed clean through 3 mip levels.

`bpy.ops.uv.pack_islands` options (5.2): `shape_method='CONCAVE'` (exact) `|'CONVEX'|'AABB'`, `rotate`, `rotate_method='ANY'|'CARDINAL'|'AXIS_ALIGNED'|'AXIS_ALIGNED_X'|'AXIS_ALIGNED_Y'`, `scale`, `merge_overlap` (keep overlapping mirrored islands together), `margin_method='SCALED'|'ADD'|'FRACTION'`, `margin`, `pin`/`pin_method`, `udim_source='CLOSEST_UDIM'|'ACTIVE_UDIM'|'ORIGINAL_AABB'|'CUSTOM_REGION'`.

Margin semantics, measured in 5.2 with two quads, `margin = 16/1024`: `FRACTION` → island gap 32 px, tile border 16 px (the margin is added around each island, so **gap = 2 × margin**); `ADD` + `scale=True` → gap 30.1 px (margin applied before scaling); `SCALED` → 3.2 px (multiplied by the existing UV scale — not a pixel unit). With `scale=False`, ADD margins are absolute. **Performance**: `FRACTION` + `scale=True` + CONCAVE took 55 s on 9 islands vs 3 s for ADD — `uv_tools.py pack` therefore scales once with an inflated ADD margin and re-packs at fixed scale with `margin = gap_px / (2 × texture_px)`.

Padding (gap between islands at the final texture size) [px rule of thumb unverified; the reason is mip-mapping — each mip halves the gap]. **This table is the padding authority for the whole skill** (bake margins, atlases, lightmaps): px gaps per resolution; a 2 px gap fails `uv_tools.py check` (measured `padding` error at 2.0 px, §7).

| Texture | Min gap between islands | Bake margin (`--margin`) |
|---|---|---|
| 512 | 4 px | 4–8 |
| 1024 | 4–8 px | 8 |
| 2048 | 8–16 px | 16 |
| 4096 | 16–32 px | 32 |
| Lightmap 64–256 | 2–4 px at lightmap resolution | — |

UV fraction = px / texture_px (8 px @2048 = 0.0039). Keep islands ≥ half the gap from the tile edge. Bake with `margin` ≥ half the gap so the gutter is filled.

Efficiency: 65–80 % UV fill is good for hand-packed hard surface, 55–70 % for organic/automatic; below 50 % raise density or shrink the texture. `rotate_method='AXIS_ALIGNED'`/`'CARDINAL'` keeps straightened strips and texture direction (wood grain, fabric, text) upright.

**Multiple UV sets**: `mesh.uv_layers.new(name="UV2", do_init=True)` copies the active map. The render/active UV is `uv_layers.active_render`; FBX/glTF export every layer in order. A bake targets the active map unless `bake_maps.py --uv-map NAME` names it — a lightmap UV2 left active silently receives a texture bake (`baking-maps.md` §2).

**Lightmap UV**: Real-time GI (Lumen, APV) usually needs no lightmap UV. When one is needed (UV channel 1 in Unreal/Unity): unique (no overlaps, **also no mirrored/stacked islands**), every island inside 0–1, padding measured at lightmap resolution, low stretch; hard edges split. Recipe tested: copy UV0 → UV2, `uv_tools.py pack --uv-map UV2 --texture-px 128 --margin-px 4` (merge_overlap False separates mirrored halves) → `check --lightmap` PASS, while UV0 still reports its mirrored overlap.

## 6. UDIM workflow

Tiles: 1001 = UV 0–1; `tile = 1001 + u + 10·v` (u = 0..9 per row, next row above). File tokens: `<UDIM>` (`name.1012.png`) and `<UVTILE>` (`name.u2_v2.png`). An island must lie entirely inside one tile — texture filtering never crosses tiles.

- **Layout**: set density first, then `uv_tools.py pack --keep-scale --udim-by AREA` (greedy by margin-padded island bounding box, fill 0.5 per tile) or `--udim-by OBJECT|MATERIAL` (one tile per part/texture set; with scaling each tile gets its own density — the script warns). Blender's own `pack_islands(udim_source='CLOSEST_UDIM')` packs the selection into the tile nearest its centre; `uv.move_on_axis(type='UDIM', axis='X', distance=1)` shifts by whole tiles.
- **Tiled image from code** (tested headless):
  ```python
  img = bpy.data.images.new("T_Prop_BaseColor", 2048, 2048, alpha=True, tiled=True)   # creates 1001
  img.tiles.new(tile_number=1002)
  for i in range(len(img.tiles)):                    # unfilled tiles are NOT saved
      img.tiles.active_index = i
      with bpy.context.temp_override(edit_image=img):
          bpy.ops.image.tile_fill(color=(0, 0, 0, 1), width=2048, height=2048, float=False, alpha=True)
  img.filepath_raw = "//textures/T_Prop_BaseColor.<UDIM>.png"; img.file_format = 'PNG'; img.save()  # -> .1001.png, .1002.png
  ```
  `img.pixels` exposes only the first tile; read other tiles by loading their files.
- **Baking to UDIMs**: supported by Cycles since 3.2 (release notes); margins stay within a tile; faces spanning tiles bake into several tiles. `bake_maps.py` switches to a tiled image automatically when the target UVs occupy tiles other than 1001 (`baking-maps.md` §4).
- **Export**: engines rarely take UDIMs directly (Unreal Virtual Texturing does [unverified per version]); Substance Painter imports them with "Use UV tile workflow" [unverified label]. For game engines, bake/paint in UDIMs and ship per-tile materials or an atlas.

## 7. Verification with `scripts/uv_tools.py`

```bash
blender -b asset.blend --python scripts/uv_tools.py -- check --objects GEO_Crate_low --texture-px 2048 \
    --target 1024 --tolerance 0.1 --min-margin-px 8 [--udim] [--lightmap --uv-map UV2]
```

Reports per object/island: island count, density min/median/max (px/m), stretch (angle = area-weighted mean of σ₁/σ₂ − 1; area = mean |log₂ area ratio| relative to the island's own scale), overlaps (partial / mirrored / stacked / self-folds, rasterised per material and tile), min island gap and tile-border distance in px (exact 2-D edge distances), UDIM tile usage and fill, islands outside 0–1 or crossing tile edges, zero-area islands, flipped triangles. `pass` = no errors. Tested on synthetic cube + cylinder (1024 px, target 256 px/m, 8 px margin):

| Case | Result |
|---|---|
| Clean unwrap → density → pack | 9 islands, 0 overlaps, all 256.0 px/m, min gap 8.0 px |
| One island moved onto another | `overlap` error (3 partial pairs), min gap 0 px |
| Re-packed with 2 px margin | `padding` error, min gap 2.0 px |
| One island scaled ×3 in U | `angle_stretch` 2.00 (expected 3 − 1), `density_out_of_tolerance` 443 px/m (256·√3) |
| Island shifted +1 U | `out_of_0_1` error; PASS with `--udim`, tiles 1001/1002 |
| Mirror modifier / Array modifier (evaluated) | `mirrored_overlap` / `stacked_overlap` warnings; errors with `--lightmap` |
| Torus unwrapped without cuts | angle stretch 2.53 (fail); with automatic cuts PASS |
| Mirrored half: UV0 copied to UV2, UV2 packed at 128 px / 4 px | UV2 `--lightmap` PASS (gap 4.0 px, border 2.0 px); UV0 still fails `--lightmap` (mirrored) |

A pass means these defect classes weren't detected at the raster resolution — still look at a checker render.

## 8. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| "Unwrap failed to solve … island(s)" / one crumpled island | Closed shell or tube without seams (chart not a disk) | Add seams; `uv_tools.py unwrap` adds disk cuts |
| Visible seam line in the normal map | UV split without hard edge, or hard edge without UV split | Match sharp edges to seams (`seams_from_islands(mark_sharp=True)`); bake-side gutter fixes in `baking-maps.md` §7 |
| Colour bleeding from neighbouring islands at distance | Padding too small for mips | Re-pack with the px gap for the texture size (table §5) |
| Blurry part next to a sharp part | Density mismatch | `density --target`; `check --target` |
| Lightmap splotches / leaks in the engine | Overlaps or tiny padding in UV1 | Separate lightmap UV set, `check --lightmap` |
| `pack_islands` takes minutes | `margin_method='FRACTION'` with scaling and exact shape | ADD pre-pass then fixed-scale re-pack (`uv_tools.py pack`) |
| UDIM tiles missing on disk after save | Tiles added but never filled | `image.tile_fill` each tile before `save()` |
| Islands cut across tile borders | UDIM layout by hand, or an island larger than a tile | Lower density or split the island; `check --udim` flags `crosses_tile_edge` |
| Smart UV everywhere, density all over the place | Automatic unwrap without average scale | `uv.average_islands_scale`, then density/pack |
| Lightmap UV fill ~35 % on a model assembled from hundreds of primitives (tubes, boxes) | Smart project cuts each tube/box into many small islands; margins dominate | Write the lightmap UV while generating each primitive (tube → one unrolled rectangle; caps and box faces planar), in metres × a density weight (thin parts ~0.5), then only `pack_islands`. Synthetic 300 tubes/boxes, 8 px margin at 2K: 35 % → 55 % fill |
| Lightmap UV fill stuck near 40 % however small the margin, on a model with flat rings or flanges | A planar UV on a ring is a hollow annulus: one rim measured 0.3 % of the map inside a bounding box of 27 %. Margins barely help (40 → 47.5 %) | List islands by bounding box minus polygon area. Unroll rings into straight strips of at most 45° (radius → V, angle × mean radius → U; area stays within about 10 %), then pack: 60 % on the same model, no mesh or UV0 change |
| Thin faces (plate tops, fin edges, rims) render as black or foreign-coloured lines in the lightmap | Their lightmap island is under ~2 px wide at the final size, so bilinear sampling reads the empty border or a neighbour | Grow every lightmap island to at least ~3 px in each direction (about its centre) before packing; costs a little fill |
