# Texture Sources & PBR Map Sets

Read this when deciding where a material's textures come from — procedural, CC0 scan library, image-generated albedo, reference projection or hand-painted — and when turning a folder of maps (downloaded, generated or baked) into a Blender material with the right color spaces and normal convention. Node-tree rules and Python builds: `shader-nodes.md`; procedural recipes: `procedural-materials.md`; baking: `baking-maps.md`.

## Contents
1. Choose the texture source
2. Library textures (Poly Haven, ambientCG)
3. Image-generated textures → full PBR set (`scripts/pbr_from_image.py`)
4. Material from a map set (`scripts/build_pbr_material.py`)
5. Common failures

## 1. Choose the texture source

| Source | Best for | Weak for | Where |
|---|---|---|---|
| **Procedural nodes** | statistical surfaces (metal, plastic, paint, concrete, rust, dirt), close-ups at any resolution, wear that follows edges/cavities/slope | specific patterns (a particular camo, labels), photoreal organic complexity (bark, leaf litter) | `procedural-materials.md`, `shader-nodes.md` §3; bake for export (`baking-maps.md`) |
| **CC0 scan library** (Poly Haven, ambientCG) | photoreal ground, rock, bark, fabric, wood, brick | matching one reference object; stylized looks | §2 |
| **Generated albedo** + derived maps | materials no library has, decals, trim sheets, leaf/feather cards | physical accuracy | §3 |
| **Reference-photo projection** | one specific object's surface | unseen sides | `materials-and-lookdev.md` §5 |
| **Hand-painted** | unique markings, placed stains, masks | large tiling areas | `texture-painting.md` |

Layer procedural masks over any source (edge wear, cavity dirt, dust on top faces, mud low on vehicles): they follow the geometry; painted equivalents don't survive model changes. Mixing sources is normal (library albedo + procedural moss mask + baked AO).

**Tiling natural surfaces built in code (numpy or bake) that must not read as "noise":**
- **Build from features.** Use features with real size-frequency laws (craters N(>D) ~ D⁻², rock fragments ~ D⁻²·⁵), angular clasts (convex polygons with a tilted top facet), strata and joints, pits and drips. Noise belongs only in the grain between features.
- **Size against the repeat.** A feature larger than ~15 % of the tile repeats visibly in a grid. Use many small features and leave larger landforms to the mesh. Fresh, bright features stay small. Thinning a population toward measured counts makes each remaining feature easier to spot repeating, so keep the larger ones soft and shallow. Measured densities are a guide; the in-engine view decides.
- **Use physical height.** Keep the height in metres and compute normals at the real texel size. Judge the result under the target's actual light: a grazing sun turns a few mm of low-frequency height noise into streaks.
- **Hybrid sources.** Procedural macro structure over CC0 scan height for rock micro-relief works where procedural rock reads fake. Resample a scan by cropping its spectrum (FFT), so it stays exactly periodic, with an integer number of repeats that divides the texture size.
- **Failures seen:**
  - Voronoi cell planes or grooves read as paving.
  - Random-walk crack grooves read as raised worms.
  - Stretched noise reads as hair.
  - Mid-scale blob noise reads as Swiss cheese.
  - Per-region values (layers, units) that jump at a border draw a line; blend them across the border.
- **Blend heights need grain.** A height channel used for height-blending (projections, overlays) needs fine grain mixed in, or blend edges follow the big shapes as smooth blobs.

## 2. Library textures (Poly Haven, ambientCG)

- Both are **CC0**. Poly Haven forbids scraping; download individual assets.
- Community **blender-mcp** server: `get_polyhaven_status` → `search_polyhaven_assets(asset_type="textures")` → `download_polyhaven_asset(asset_id, asset_type="textures", resolution="2k")` → `set_texture(object_name, texture_id)` (color spaces and ARM split handled); HDRIs via `asset_type="hdris"`. The official Blender connector exposes code execution only, not asset downloads.
- Otherwise download the map set and build it with `scripts/build_pbr_material.py` (§4): Poly Haven, ambientCG and Substance Painter suffixes are recognised automatically.

## 3. Image-generated textures → full PBR set (`scripts/pbr_from_image.py`)

**Detect** a generator first — any image-generation tool available in the session: MCP image tools (`generate_image`, `text_to_image`, `flux_text_to_image`), ComfyUI MCPs (`execute_workflow`, e.g. CHORD PBR graphs), a CLI image generator, add-ons (StableGen). Follow its consent/billing rules. None available: library textures or procedurals.

**Generate only the albedo** (optionally a grayscale height). Generated normal/roughness/AO maps are unreliable (non-unit normals, random green convention, lighting painted into roughness); derive data maps with code.

Prompt recipe (square, 1–2k):
```
seamless tileable <material> texture, orthographic top-down view, flat even diffuse lighting,
no shadows, no highlights, no vignette, uniform brightness edge to edge, fills the entire frame,
<real scale cue: "1 m × 1 m patch", "pebbles 2–5 cm">, albedo base color only, no text, no border
negative: perspective, horizon, shadow, specular highlight, vignette, gradient, text, watermark, frame, 3d render
```
- **Watermarks off** and automatic prompt rewriting off, whatever the tool; quote `W*H` sizes; check the tool's `--help` rather than guessing flags.
- Native tiling when available (SD/ComfyUI circular padding, Midjourney `--tile`), else fix in post. Fixed seed + shared prompt stem across a family (clean/dirty/wet).
- 3–4 candidates; pick: no perspective, even lighting, no repeating hero feature, correct scale.

Derive and check:
```bash
blender -b --factory-startup --python scripts/pbr_from_image.py -- textures/MAT_Mud/mud_gen.png --out textures/MAT_Mud \
    --name mud --tileable --delight 0.1 --preview --height-exr [--invert-height] [--normal-strength 2]
```
- `PBR_REPORT` seam ratio after `--tileable` ≈ 1 (> 1.5 = visible seam); check the 2×2 previews for seams and repeating blotches (half-offset blending duplicates large features; bricks, planks, text ghost — crop or fix by hand).
- Height from luminance is a guess (bright = high; else `--invert-height`) — sculpt or scan where height matters. Roughness from albedo is a starting variation: base from physics (`--roughness-base`), tuned to reference highlights.
- DirectX normal downloads: `--convert-normal file_dx.png --out dir`. Then build the material from the folder (§4).
- Provenance in `textures/<MAT>/manifest.json` (generator, model, prompt, negative prompt, seed, size, date, `generated: true`). No trademarks, logos or named artists' styles for shipped assets; no restrictively licensed textures into image-to-image.

**Other generated types**: decals/labels (flat neutral background, key to alpha), trim sheets (prompt for horizontal strips of panels/bevels/bolts, then UV-map faces onto strips — `modular-kits-and-wfc.md` §8), leaf/feather cards (single leaf on pure white/black → alpha by keying → `pbr_from_image.py` for normal), skies/backplates (equirectangular prompts are unreliable — prefer Poly Haven HDRIs).

## 4. Material from a map set (`scripts/build_pbr_material.py`)

One node-based Principled material from a texture folder (library download, generated set from §3, or a baked set from `baking-maps.md`):
```bash
blender -b file.blend --python scripts/build_pbr_material.py -- --folder textures/MAT_Mud --name MAT_Mud [--object OBJ] \
    --projection BOX --displacement BUMP --macro-variation 0.3 [--normal-convention DX|GL] [--gltf-occlusion] [--save out.blend]
```
Live session: exec the file, then `maps = find_maps(folder)` and `build_pbr_material("MAT_X", maps, projection='BOX', obj="Name")`, or set `PBR_OPTS` (CLI keys with underscores) before exec. It prints one `BUILD_PBR_MATERIAL` JSON report line.

- Recognises Poly Haven, ambientCG and Substance Painter map suffixes (list in its docstring), prefers GL normals, uses the Normal Map node's DirectX convention for DX maps (green flip before 5.1), splits ARM/ORM and sets color spaces (sRGB base/emission, Non-Color for the rest). Substance names don't say GL or DX — pass `--normal-convention DX|GL` (which engine expects which convention: `game-engine-delivery.md` §2).
- UDIM tile sets (`.1001`/`_1001`/`<UDIM>`) become tiled images automatically (`uv-unwrapping.md` §6, `baking-maps.md` §6); UDIM needs `--projection UV`.
- `--gltf-occlusion` plugs AO into the "glTF Material Output" group (input "Occlusion") so the glTF exporter writes an occlusionTexture; AO is never multiplied into base color for Cycles (`shader-nodes.md` §2).
- **Scale the Mapping to real size**: a 2 m × 2 m texture patch gets scale 0.5 per metre under BOX/OBJECT projection; add `--macro-variation` on large areas.
- After baking, rebuild the exported material from the baked set with the same script and compare procedural vs baked renders before export.

## 5. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Albedo carries shadows, perspective, vignette or a watermark | Generated image used as-is | Re-prompt with the §3 recipe (orthographic, flat lighting, watermark off); pick from 3–4 candidates |
| Normals non-unit or inverted, roughness shows lighting | AI-generated normal/roughness/AO maps trusted | Generate only the albedo; derive data maps with `scripts/pbr_from_image.py` (§3) |
| Visible seam when tiled | Seam ratio > 1.5 | `--tileable`; check the 2×2 previews |
| Bricks, planks or text ghost after `--tileable` | Half-offset blending duplicates large features | Crop a tiling-friendly region or fix by hand |
| Pits read as bumps | Height guessed from luminance (bright = high) | `--invert-height`; sculpt or scan where height matters |
| Downloaded normal map reads inverted | DirectX (Y−) map treated as OpenGL; Substance names don't encode the convention | `--convert-normal` (§3) or `--normal-convention DX` (§4) |
| Texture too large/small on the surface | Mapping not at real size | 2 m patch → scale 0.5 per metre under BOX/OBJECT (§4) |
| Repetition visible from a distance | One tile, no variation | `--macro-variation`, per-object random (`procedural-materials.md` §1); distance shot in review |
| Washed-out normals, gamma-curved roughness from a hand-built set | Data maps loaded as sRGB | Let the script set color spaces, or `'Non-Color'` by hand (`shader-nodes.md` §2) |
