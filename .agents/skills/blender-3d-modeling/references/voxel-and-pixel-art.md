# Voxel & Pixel-Art Assets (voxel models, palette textures, pixel-art on 3D)

Read this when a mesh must become a voxel asset that stays on a grid, or when pixel-art textures and low-res renders must stay crisp on 3D geometry. The quiet failures: off-grid vertices, coincident inner faces, blurry filtered texels, palette colours shifted by the view transform. All numbers below were measured in Blender 5.2 unless marked `[unverified]`. Tool: `scripts/voxelize.py`. SVG logos and text objects: `vector-and-text.md`.

## Contents
1. Voxel assets: routes, grid contract, culling, greedy meshing, palettes, .vox
2. Pixel-art textures on 3D
3. Script: `scripts/voxelize.py`
4. Common failures

## 1. Voxel assets: routes, grid contract, culling, greedy meshing, palettes, .vox

### 1.1 Construction routes

| Route | Grid-aligned? | Inner faces | Use |
|---|---|---|---|
| `scripts/voxelize.py` (ray-parity occupancy → culled faces → greedy merge) | Yes, world grid, pivot snapped | None (gate-checked) | Game-ready voxel props from any closed mesh, palette colours |
| Remesh modifier `mode='BLOCKS'` (`octree_depth`, `scale`) | **No**: the grid follows the bbox, not the world (sphere r 0.5, depth 4 → blocks of 0.0694 m starting at −0.52083) | Surface only | Quick look-dev; re-snap before kits |
| GN: Mesh to Volume → Distribute Points in Volume (Mode = Grid, Spacing = s) → Instance on Points (Cube, size s) → Realize | Points land exactly on multiples of `s` (100 % measured) | **Every shared face stays** (coincident internal pairs, 6 faces/voxel; Merge by Distance welds vertices only) `[unverified count]` | Parametric or animated voxel effects, not export |
| GN: Mesh to Volume → Volume to Mesh | No (0 % of vertices on grid): smooth iso-surface | – | Blobby remesh, not voxels |
| Manual cube grid | Yes if placed at integer multiples | Must be culled | Hand-built voxel art: model with snapping, then run `voxelize.py --check` |

### 1.2 Grid contract and inside test

- **Grid contract**: voxel corners at integer multiples of the voxel size in world space. Pivot (origin) snapped to a grid point, usually BOTTOM_CENTER, so local vertices are exact multiples too. Voxel size is a whole divisor of the kit module (`modular-kits-and-wfc.md` §1).
- **Inside test**: ray parity along voxel-centre columns, voted over X/Y/Z. Rays at half-voxel offsets never hit grid edges, and voting absorbs small holes. On a closed sphere, `nearest`-normal sign and parity agreed on all 2126 voxels. Parity stays the default because nearest-sign breaks on thin parts and open meshes `[unverified beyond the sphere test]`.

### 1.3 Culling and greedy meshing

- **Cull inner faces**: emit a face only where filled meets empty. Sphere r 1 m at 0.125 m: naive 12 756 faces → culled 1 200 → **greedy 613**. 2 m cube at 0.25 m: 3 072 → 384 → 6 faces / 8 vertices. Voxel volume 4.152 m³ vs mesh 4.159 m³ (0.16 %).
- **Greedy meshing** merges coplanar same-colour faces into maximal rectangles per slice. It creates **T-junctions** (470 non-manifold edges on the greedy sphere). That's fine for flat-shaded engine blocks, but can show sparkle cracks under heavy vertex animation and breaks printing and booleans. Use `--no-greedy` there (culled, shared vertices: 0 non-manifold on the cube).

### 1.4 Colours and shared palettes

- **Colours**: 1 px per colour, with no padding between palette texels. That layout only holds with Image Texture `interpolation='Closest'` and **mipmaps off** (engine: Point/Nearest filtering, no mip generation, §2); once mipmaps are generated, neighbouring texels blend at every mip level, so a mipmapped palette needs padding between colours by the padding table in `uv-unwrapping.md` §5, not 1 px. Palette texture next-power-of-two × 1 (the script fills the unused width with white), every face's UVs on its texel centre, Principled roughness high (0.8 in the script). Merge only faces of the same colour. Band edges of a colour attribute produce blended in-between colours (3 bands → 29 quantized colours), so lower `--max-colors` or paint hard colour borders.
- **Shared palette for a prop set**: `--palette-in palette.json|palette.png` snaps every sampled colour to the nearest entry (sRGB distance). The full palette goes into the texture in file order, so every prop gets a byte-identical texture, the same texel index per colour and one shared material `MAT_PAL_<file stem>`. That means one texture and one material for the whole set; `--max-colors` is ignored. JSON takes `[[r,g,b],…]` (ints 0–255, floats 0–1), `"#rrggbb"` strings or `{"colors": […]}`. A PNG gives its unique opaque pixels, top row first. `--palette-out x.json|x.png` writes the resolved palette, and a shared palette read back comes out exactly equal. Measured: a cube and a sphere against a 6-colour palette gave identical palette PNGs (same SHA-1) with max distance 1.75 and 4.78 (0–255 units). The same pair without a shared palette produced two different textures. A green prop against a palette with no green reported 76.8 and a warning (threshold `--palette-warn 48`). Build the palette first (`--palette-out` from the most colourful prop, or hand-author it). Never feed a padded `--palette-png` texture back in, because its white padding becomes a colour.

### 1.5 Shading and export

- Flat (no smooth, no custom normals). Export with **no** tangent-space normal map. If an engine smooths, split vertices per face or mark all edges sharp (`game-engine-delivery.md` §3).

### 1.6 .vox (MagicaVoxel)

- No built-in importer. The **"MagicaVoxel VOX format"** extension (extensions.blender.org, v1.6.0 June 2026, Blender 4.2+, GPL-3.0+/MIT) imports with voxel size, join models, hierarchy as empties and centre origins. Meshing modes include greedy and (1.6.0) watertight greedy. Material modes: vertex colour, material per colour, 256×1 palette texture, textured UV unwrap. Operator id and headless behaviour `[unverified]`, since the extension isn't installed. Loads only without `--factory-startup`. After import run `voxelize.py --check <obj> --voxel-size <s>`.

## 2. Pixel-art textures on 3D

| Stage | Setting |
|---|---|
| Texture | Power-of-two, no mip/smoothing in source; sRGB |
| Blender shading | Image Texture `interpolation='Closest'` (enum: Linear, Closest, Cubic, Smart) |
| UVs | Snapped to the texel grid (`voxelize.py --snap-uvs OBJ --texels 32 32`: residual 0.5 → 0 texels measured); texel density constant across the kit (`uv-unwrapping.md` §4) |
| Engine import | Point / Nearest filtering, **no mipmaps**, no compression or lossless, no anisotropic `[unverified per engine — set in the engine's texture import settings (e.g. Filter Mode Point / Nearest, mip generation off)]` |
| Low-res render | Resolution = target (e.g. 320×180, 100 %). `render.filter_size = 0` (default 1.5). Cycles `filter_width` min 0.01. EEVEE `taa_render_samples = 1`. View transform **Standard** (AgX shifts palette colours). **Orthographic** camera with `ortho_scale` = pixels ÷ pixels-per-metre, so one texel lands on a whole number of screen pixels. Upscale afterwards with nearest-neighbour |

`voxelize.pixel_art_render(scene, w, h)` applies the render row (measured: filter_size 0.0, TAA 1, Cycles 0.01, Standard). Camera details: `rendering-and-lighting.md` §3; compositing: `render-farm-and-compositing.md` §4. Toon and outline looks: `stylized-npr.md`.

## 3. Script: `scripts/voxelize.py`

Voxelize (§1.1–1.4) / `--check` any voxel mesh (off-grid vertices, non-axis faces, internal faces, duplicates) / `--snap-uvs` + `--closest` (§2) / `pixel_art_render` (§2). Planted defects caught: a vertex moved 13 mm, a quad inside the solid, a coincident duplicate face, the wrong voxel size (8/8 vertices off-grid).

## 4. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Voxel kit pieces don't line up | Remesh Blocks grid follows the bbox; pivot off grid | `voxelize.py` world grid + snapped pivot; `--check` |
| Voxel mesh has 6× the expected faces | Instances/cubes with coincident inner faces | Cull + greedy merge; gate `internal_faces == 0` |
| Cracks or sparkles between greedy faces | T-junctions | `--no-greedy` for those assets, or weld in the engine |
| Pixel texture blurry | Linear interpolation / mipmaps / filtering | Closest in Blender; Point/Nearest, no mips in the engine |
| Palette colours bleed into neighbours in the engine | Mipmaps generated on a 1-px-per-colour palette | Mip generation off, or pad the palette per `uv-unwrapping.md` §5 (see §1.4 here) |
| Texel edges crawl across faces | UVs not on the texel grid | `snap_uvs` to texture size; constant texel density |
| Palette colours look washed out | AgX view transform | Standard view transform for pixel/voxel renders |
