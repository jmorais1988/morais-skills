# Baking Maps

How to turn high-poly detail and procedural materials into texture files with `scripts/bake_maps.py` — cage and triangulation rules, texture size, anti-aliasing, mirrored and UDIM islands, numeric verification — and how to hand a low poly to Substance Painter / Marmoset and bring the maps back. Read it when a normal/AO/ORM/base-colour bake or a Painter round-trip is the next step; UV layout and padding are in `uv-unwrapping.md` (its §5 table is the padding authority), engine channel packing in `game-engine-delivery.md` §6.

## Contents
1. Bake setup: low, high, cage, triangulation
2. Running `scripts/bake_maps.py`
3. Texture size, resolution and anti-aliasing
4. Mirrored, stacked and UDIM islands
5. Verifying bakes numerically
6. Substance Painter / Marmoset round-trip
7. Common failures

## 1. Bake setup: low, high, cage, triangulation

- **Pairing**: high poly (sculpt / subd / booleans) and low poly share scale, position and names (`_high`/`_low`); hard edges of the low sit on UV seams (`uv-unwrapping.md` §2).
- **One triangulation rule**: add a real **Triangulate modifier (Beauty, keep normals)** to the low before baking and keep it through export, so the MikkTSpace tangents the engine computes match the ones Blender baked; leave the exporter's `use_triangles` off. `--triangulate` adds an equivalent temporary modifier for the bake only (the cage gets the same one — Cycles rejects a cage with a different face count) — use it only when the export copy carries the same permanent modifier; quads left to the importer may shade differently.
- **Cage**: `--cage-extrusion` ≈ 1–3 % of object size, or `--cage OBJ` = a duplicate of the low mesh pushed 1–3 % of its size out along normals (`bpy.ops.transform.shrink_fatten` in Edit Mode; same topology; hidden from render during the bake). `--max-ray-distance` limits how far rays search (stops hits on neighbouring parts) — set it to ≈ 2× the cage offset. For AO, `hide_render` everything that is not the high/low pair, otherwise scene geometry occludes the bake.

## 2. Running `scripts/bake_maps.py`

```bash
blender -b asset.blend --python scripts/bake_maps.py -- --object GEO_Crate_low --out bakes/crate \
    --maps BASECOLOR,NORMAL --orm --source GEO_Crate_high --cage GEO_Crate_cage --max-ray-distance 0.05 \
    --size 2048 --margin 16 --bit-depth 16 --normal-convention DIRECTX --triangulate [--device GPU] [--udim auto] \
    [--uv-map UVMap] [--ao-samples 64] [--ao-distance 0.5] [--margin-type ADJACENT_FACES|EXTEND]
```

| Setting | Guidance |
|---|---|
| UVs | Required; non-overlapping for unique maps (check first). Missing UVs are an error unless `--auto-uv` (Smart UV, warned) |
| UV map | `--uv-map NAME` picks the target map (default: the **active** map — a lightmap UV2 left active silently receives the bake; a missing name raises and lists the available maps). The bake op gets it explicitly, so active/render-active flags don't matter |
| Projection | §1: `--cage-extrusion` ≈ 1–3 % or `--cage OBJ`; `--max-ray-distance` ≈ 2× cage offset |
| AO | AO needs more samples than a normal map (noise, not geometry): run AO separately or set `--ao-samples N` (Cycles samples for the AO map only; default `--samples`); `--ao-distance m` sets the ray length (`scene.world.light_settings.distance`; a scene without a world gets a temporary one) |
| Margin fill | `--margin-type ADJACENT_FACES` (default, follows the mesh) or `EXTEND` (plain outward smear, safer for many tiny islands); `--margin` px from the padding table in `uv-unwrapping.md` §5 |
| Normal convention | OpenGL (Blender, Unity, Godot, glTF, SP default) or DirectX (Unreal, 3ds Max) — per-engine table in `game-engine-delivery.md` §2; `--normal-convention DIRECTX` bakes green = −Y and writes `_NORMAL_DX` (recognised by `build_pbr_material.py`) |
| Tangent basis | Blender bakes MikkTSpace tangents for the evaluated low mesh — the triangulation rule in §1 |
| Bit depth | 8-bit PNG for colour/ORM; 16-bit PNG for normals and height (no banding on smooth bevels); EXR 16/32 for displacement/position. Float images saved with `img.save()` keep their data; `image.save_render()` applies the scene view transform (AgX) — don't use it for data maps |
| ORM | `--orm` bakes AO/Roughness/Metallic and writes `_ORM` (R=AO, G=Roughness, B=Metallic) for Unreal/glTF-style shaders; Unity HDRP mask map is a different layout (R metal, G AO, B detail, A smoothness) |
| Resolution | Bake at 2× and downsample for anti-aliasing (§3), or use more samples |
| Device | `--device GPU` enables the first Cycles GPU backend (OPTIX/CUDA/HIP/ONEAPI/METAL) and falls back to CPU with a warning |

Old CLI flags (`--object --out --maps --size --margin --samples --source --cage-extrusion --no-unwrap`) still work. The report lists `uv_map`, `ao_samples`, `ao_distance` and `margin_type` (the scene value when not overridden). Before this release the report's `coverage` and `mean` statistics were wrong (the image colour space was set *after* the fill), so older `BAKE_MAPS` reports overstated coverage — re-run rather than trust an archived report.

## 3. Texture size, resolution and anti-aliasing

- **Size for a density**: with density `D` px/m, total surface area `A` m² and `N` same-size tiles packed at fill `f` (0.5 default), each tile needs `T ≥ D × sqrt(A / (N × f))` — at f = 0.5, `T ≥ D × sqrt(2A / N)`; round up to a power of two [derived from `uv_tools.py`'s tile math: `need_px = texture_px × sqrt(uv_area / fill)`]. `uv_tools.py density` reports the same numbers (tiles needed, single-tile size, achievable density).
- **2× bake + downsample** (anti-aliasing without raising samples): bake at `2T`, then per image / per UDIM tile:
  ```python
  img = bpy.data.images[name]          # per tile: load the tile file, or set tiles.active_index
  img.scale(T, T)                      # box filter down to the delivery size
  img.save()                           # img.save(), not save_render(), for data maps
  ```
  Memory caveat: a 4K delivery means an 8K float bake buffer (8192² × 4 channels × 4 bytes = 1 GiB per map before mips) — bake one map at a time or drop to 8-bit for colour maps at that size [unverified: buffer size is arithmetic, headroom not measured].

## 4. Mirrored, stacked and UDIM islands

- **Mirrored / stacked islands** bake from one side only, so offset the duplicates by exactly **+1 U** before baking unique maps and move them back afterwards (`uv-unwrapping.md` §2).
- **When the neighbouring UDIM tile is occupied** (the +1 U target holds real islands), offset the duplicates into an unused tile **row** instead — e.g. +1 V → tile 1011 — bake, discard that tile's output, then move them back.
- **UDIM targets**: supported by Cycles since 3.2; margins stay within a tile; faces spanning tiles bake into several tiles. `--udim auto` switches to a tiled image when the target UVs occupy tiles other than 1001; each used tile is created, filled and saved through the `<UDIM>` token (`_<MAP>.1001.png`, `.1002.png` …).
- **Engines and UDIMs**: Unreal imports UDIM sets only with Virtual Texturing enabled `[unverified per version]`; otherwise, and for Unity/Godot, ship per-tile materials or an atlas (`uv-unwrapping.md` §6).

## 5. Verifying bakes numerically

**Read pixels the right way.** `Image.pixels` returns *linear* floats for EXR/float images but the *stored sRGB-encoded* values for 8-bit sRGB PNGs — decode those before comparing to a linear base colour, or a correct bake looks 13–140 % "too bright" (measured: PNG ratios 1.13/1.95/2.43 for base 0.8/0.3/0.2 were exactly the sRGB encoding). Compare BASECOLOR against an EMIT bake of the same colour, using only alpha = 1 pixels and the median. `bake_maps.py` zeroes Metallic, Transmission, Specular IOR Level, Coat and Sheen for BASECOLOR; without that Cycles bakes base colour 3.7 % dark (coat + sheen: a hue shift).

Tested (synthetic 2 m cube low / 6-segment 0.2 m bevelled high, 256 px): normal map non-flat (mean deviation from flat 0.29); at the +V bevel of the top face green = 0.851 OpenGL vs 0.149 DirectX, at −V 0.203 vs 0.797; red unchanged (mean diff 0.0008). ORM channels identical to the separate AO/Roughness/Metallic files (max diff 0.0). 8-bit, 16-bit PNG (header depth 16) and EXR base colour agree to 0.001. Cage object + triangulate bakes (the cage gets the same temporary Triangulate — Cycles rejects a cage with a different face count). UDIM low with faces in 1001/1002 → `_<MAP>.1001/.1002.png` and `_ORM.1001/.1002.png`, both tiles non-flat. GPU request ran on the available GPU backend and restored the scene device.

## 6. Substance Painter / Marmoset round-trip

**Export from Blender** (per asset, `export_scene.fbx`): `use_selection=True`, `apply_scale_options='FBX_SCALE_ALL'`, `mesh_smooth_type='FACE'` (smoothing groups from sharp edges), `use_tspace=True` (tangents; needs a triangulated or quad/tri mesh), `use_mesh_modifiers=True` (this writes the permanent Triangulate modifier of §1 — the older recipe set `use_triangles=True` for the low to fix the triangulation the bake used; with the modifier in place leave it off), `add_leaf_bones=False` for skinned meshes, `path_mode='AUTO'`, `embed_textures=False`. Verified option names in 5.2; values are pipeline convention. This Painter export is a separate FBX from the engine export — engine scale/axis presets (e.g. Unreal `FBX_SCALE_NONE`) live in `game-engine-delivery.md` §2; Painter only needs consistent scale between low and high.

- **Texture sets = material slots**: one Blender material per texture set on the low poly (name them `MAT_<Name>`; SP names texture sets after the material). Fewer sets = fewer draw calls.
- **Bake by mesh name**: name pairs `<part>_low` / `<part>_high` (case-insensitive in Marmoset; SP's "Match: By Mesh Name" uses configurable suffixes, default `_low`/`_high`). Export the high separately (`<asset>_high.fbx`); explode or name-match to avoid cross-part projection.
- **Normal map format**: SP *Edit → Project Configuration → Normal map format*: OpenGL for Unity/Blender/Maya, DirectX for Unreal/3ds Max; *Compute tangent space per fragment*: enabled for Unreal, disabled for Unity built-in/URP (enabled for HDRP) (Adobe docs). Changing either requires re-baking. Marmoset: set the tangent space to MikkTSpace and flip Y per engine in the bake output [unverified menu names].
- **Triangulate before baking** (the §1 modifier, exported with the mesh) so SP/Marmoset and the engine share one tangent basis.
- **Re-import maps**: export textures from SP with a preset matching the target (e.g. `<Set>_BaseColor`, `_Normal` (OpenGL), `_OcclusionRoughnessMetallic`) and rebuild the Blender material with `scripts/build_pbr_material.py --folder <dir> --name MAT_X` (recognises GL/DX normal tokens and ORM/ARM packs; SP export-name aliases come from the PBR material script).
- **UDIM exports** (`<Set>_BaseColor.1001.png`, `_1001`, or `--map basecolor=dir/<Set>_BaseColor.<UDIM>.png`): the same script builds one tiled image per channel (`source='TILED'`, `<UDIM>` filepath; loading a `<UDIM>` path directly gives an empty FILE image in 5.2) and warns when a map lacks a tile the other maps have. SP imports UDIM meshes with "Use UV tile workflow" [unverified label].

## 7. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Visible seam line in the normal map | UV split without hard edge, or hard edge without UV split; low-res gutter | Match sharp edges to seams; raise bake `--margin` (padding table `uv-unwrapping.md` §5); `--margin-type EXTEND` for many tiny islands |
| Bake has doubled or garbage detail on one side | Mirrored/stacked islands baked in place | Offset duplicates +1 U (or +1 V into an unused tile row) before baking (§4) |
| Normal map looks inverted (dents instead of bumps) | DX vs GL green channel | Bake/export with the engine's convention (`--normal-convention`); flip green |
| Shading artefacts after engine import | Different triangulation or tangents than the bake | Permanent Triangulate modifier before bake and through export (§1); tangents MikkTSpace |
| Bake landed in the lightmap / wrong UV set | Active UV map was not the texture map | `--uv-map NAME` (§2) |
| AO grainy while the normal map is clean | AO sampled at the normal-map sample count | `--ao-samples N`, or bake AO in a separate run |
| AO black patches / neighbours baked in | Other scene objects occluding, or rays reaching a neighbouring part | `hide_render` everything but the pair; `--max-ray-distance` ≈ 2× cage offset (§1) |
| Base colour bake darker than the material | Metallic / coat / sheen / transmission weighting in the DIFFUSE pass | `bake_maps.py` BASECOLOR (zeroes them); compare to an EMIT bake (§5) |
| Bake looks 13–140 % too bright when read back | `Image.pixels` of an 8-bit sRGB PNG is sRGB-encoded | Decode to linear before comparing, or verify on EXR/float (§5) |
| 16-bit map looks washed out / wrong values | Saved with `save_render` (view transform) | `img.save()` on a float image |
| Cycles refuses the cage | Cage face count differs from the low (e.g. one triangulated, one not) | Same topology; `--triangulate` applies to both |
| Out of memory on a 2× bake at 4K | 8K float buffers per map | One map per run, 8-bit colour maps, or bake at 1× with more samples (§3) |
| Lightmap / Combined bake grainy although the scene has Denoise on and plenty of samples | Cycles never denoises a bake (the render Denoise checkbox doesn't apply), and bakes use the render settings, adaptive sampling included, so a noise threshold lets texels stop early | Turn adaptive sampling off for bakes; denoise the baked float image yourself with OIDN in the compositor: fill the chart margins first, denoise, then re-fill from the covered texels (the denoiser bleeds empty texels into the edges otherwise). Headless: a Viewer node returns zeros, so give the compositor a camera, route Image → Denoise (HDR on) → group output, render to a 32-bit EXR and read it back |
| AO black on a thin strap or ribbon lying on another surface, or two mirrored halves that differ | AO looks out along the face normal, and this surface's normal points into what it lies on. Mirroring a path flips the winding | Orient each single-surface part's faces outward before baking: check one face from the middle of the path against the direction it should look |
| Dark patch on the far side of a single-surface panel, in the shape of what's mounted on its front | One surface shares its texels both ways, so the front's contact shadow shows from behind | Give the far side its own surface and UV island, about 2 mm behind |
| Neighbours of an object bake too bright (strong bounce), everything else fine | A renderable mesh with no material renders with Cycles' default light-grey surface, far brighter than e.g. dark terrain | Before baking, list renderable meshes with no material slots and assign the real ones; regenerated meshes lose their materials |

### Lightmap seam lessons

- **Dark island edges or outlines between objects:** the bake margin samples the cleared background at mesh borders, and partly covered edge texels bake dark.
  - Use margin 0.
  - Trust only texels with 4 written neighbours, and rebuild the edge ring from them.
  - Then edge-repeat and push-pull fill. Never decide coverage by colour.
- **Seams between separately baked chunks:** no engine stitches across objects.
  - Put texel centres on the shared edge in both UV maps.
  - Bake each chunk through a copy of the whole surface.
  - Equalise the edge rows on the coarser grid.
- **Albedo seams on organic meshes:** use a triplanar world-space albedo multiplied by the baked lightmap. The lighting chart seams then don't matter for the texture.
- **Organic meshes whose lightmap charts keep seaming** (caves, boulders): bake lighting to vertex colours instead.
  - Use a per-corner FLOAT colour attribute (`bake.target = 'VERTEX_COLORS'`).
  - Refine adaptively: split triangles whose corner values differ, then re-bake.
  - Export with linear colours. There are no UV charts, so there are no seams.
- **Find which layer carries a seam before you fix it:** render with the albedo forced flat, then with the lighting forced white.
