# Web and Mobile Delivery

How to ship a Blender asset to browser viewers (three.js, model-viewer, Babylon), iOS Quick Look, mobile games and standalone VR (Quest-class): the Principled → glTF material mapping, colourway variants, geometry/texture compression, atlasing, and the draw-call, overdraw and texture-memory budgets that decide whether the scene runs. Read it when the target is a GLB viewer or a mobile/VR frame budget; engine export tables, LODs and collision are in `game-engine-delivery.md`, UV padding in `uv-unwrapping.md`.

## Contents
1. Export settings and viewer setup
2. Principled BSDF → glTF materials
3. Material variants (`KHR_materials_variants`)
4. Compression, validation and web budgets
5. Mobile and standalone VR
6. Verifying a web or mobile delivery (scripts)
7. Common failures

## 1. Export settings and viewer setup

- **GLB settings** (5.2 `export_scene.gltf`) are the Web column of the table in `game-engine-delivery.md` §2: `export_yup=True`, `export_apply=True` — but `export_apply=False` when meshes carry shape keys, because the glTF exporter drops shape keys with Apply Modifiers (`shape-keys-and-visemes.md` §6) — normals always written, tangents off (three.js computes if needed), `export_extras=True`, 4 bone influences, `export_animation_mode='ACTIONS'`, `export_image_format` `AUTO`/`JPEG`/`WEBP`. The validated round-trip preset is `web` in `scripts/export_check.py`.
- **iOS AR Quick Look**: USDZ via `wm.usd_export` with a filepath ending `.usdz` — writes the zip package directly (verified 5.2).
- **three.js**: `GLTFLoader` + `DRACOLoader` / `MeshoptDecoder` / `KTX2Loader` for compressed files; set `renderer.outputColorSpace = SRGBColorSpace` and a tone mapping that matches the look you approved in Blender (AgX in Blender ≈ `AgXToneMapping`).
- Names, pivots, applied transforms and shading rules are the same as for engines — `game-engine-delivery.md` §3.

## 2. Principled BSDF → glTF materials

5.2 exporter; each extension is written only when the input differs from its default — verified by exporting a test material:

| Principled input(s) | glTF |
|---|---|
| Base Color, Metallic, Roughness, Normal, Alpha | core `pbrMetallicRoughness`, `normalTexture`, `alphaMode` |
| Emission Color × Emission Strength > 1 | `emissiveFactor` + `KHR_materials_emissive_strength` |
| Coat Weight / Coat Roughness / Coat Normal | `KHR_materials_clearcoat` |
| Sheen Weight / Sheen Tint / Sheen Roughness | `KHR_materials_sheen` |
| Transmission Weight | `KHR_materials_transmission` |
| Specular IOR Level / Specular Tint | `KHR_materials_specular` (`export_original_specular` keeps the raw values) |
| IOR (≠ 1.5) | `KHR_materials_ior` |
| Anisotropic / Anisotropic Rotation / Tangent | `KHR_materials_anisotropy` |
| Thin Film Thickness / Thin Film IOR | `KHR_materials_iridescence` [not export-tested here] |
| Volume Absorption (Density, Color) + thickness from a "glTF Material Output" group node | `KHR_materials_volume` [not export-tested here] |
| Background shader (or Emission via Light Path "Is Camera Ray" mix) as surface | `KHR_materials_unlit` (Background verified) |
| Mapping node on image UVs | `KHR_texture_transform` |

Only Image Texture → socket links (optionally through Normal Map, Separate Color, Mapping) export; procedural textures must be baked first (`scripts/bake_maps.py`, `baking-maps.md`). Keep one UV map per material unless the viewer supports more.

## 3. Material variants (`KHR_materials_variants`)

Colourways in one file: enable *Preferences → Add-ons → glTF 2.0 → Material Variants* (`preferences.addons['io_scene_gltf2'].preferences.KHR_materials_variants_ui`). This adds the scene list `scene.gltf2_KHR_materials_variants_variants` and operators `bpy.ops.scene.gltf2_variant_add`, `gltf2_variants_slot_add`, `gltf2_assign_to_variant`, `gltf2_assign_as_original`, `gltf2_display_variant`, `gltf2_reset_to_original`. Per mesh, `mesh.gltf2_variant_mesh_data` holds entries of `material_slot_index`, `material`, `variants`.

Workflow (Scene and Mesh "glTF Material Variants" panels): add variants; per mesh add a variant slot, pick its material, tick its variants (or set the slot material, select the variant, *Assign To Variant*); *Assign as Original* stores the default. Verified headless: the operators run and the GLB gets root `KHR_materials_variants.variants` plus per-primitive `mappings` — inspect the mappings (`gltf-transform inspect`, model-viewer), because a mis-assigned slot silently maps several variants to one material. model-viewer exposes them as `variantName`; three.js needs the variants extension handler (`GLTFLoader` user plugin / `three-gltf-extensions`) [unverified]. Without Blender, `gltf-transform` scripting (`@gltf-transform/extensions` `KHRMaterialsVariants`) can merge colourways.

## 4. Compression, validation and web budgets

| Layer | Built into Blender 5.2 exporter | External CLI |
|---|---|---|
| Geometry | Draco `export_draco_mesh_compression_enable` (+ `_level`, position/normal/texcoord quantization); meshopt `export_meshopt_compression_enable` with `export_meshopt_extension` `EXT_meshopt_compression` or `KHR_meshopt_compression` (both verified: 285 KB test sphere → 43 KB Draco, 85 KB EXT / 72 KB KHR meshopt); `export_use_gltfpack` (+ `export_gltfpack_*`) runs gltfpack if its path is set in the add-on preferences | `gltf-transform optimize in.glb out.glb --compress meshopt` (or `draco`); `gltfpack -i in.glb -o out.glb -cc` |
| Textures | `export_image_format='WEBP'` (+ `export_image_add_webp`, `export_image_webp_fallback`), JPEG quality | KTX2/Basis: `gltf-transform uastc` (normal maps, high quality) / `etc1s` (colour, smallest), `gltf-transform optimize … --texture-compress ktx2` (or `webp`/`avif`), `--texture-size 2048`; `gltfpack -tc` |
| Inspect / validate | — | `gltf-transform inspect in.glb`; Khronos glTF Validator (`gltf_validator`, or the web drag-and-drop validator) |
| Extensions / variants gate | `scripts/export_check.py --inspect out.glb --expect-extensions KHR_draco_mesh_compression,KHR_materials_clearcoat --expect-variants Red,Blue` (stdlib JSON parse; also `python export_check.py --inspect …` without Blender) | reports extensionsUsed/Required, per-material extensions, variant → material mappings per primitive, Draco/meshopt, image MIME types; not a full validator |

Install: `npm install --global @gltf-transform/cli`. Draco decodes slower on the client than meshopt and compresses only geometry; meshopt also compresses animation and pairs with gltfpack quantization. KTX2 textures stay compressed in GPU memory (JPEG/WebP/PNG are decoded to full RGBA): a 2K RGBA texture is ~21 MB of GPU memory with mips uncompressed, ~5 MB as UASTC/ASTC-class.

**Web budgets**: ≤ ~100k tris whole scene, textures ≤ 2K (1K on mobile), ≤ 5–10 MB GLB after compression for product viewers, ≤ 3–4 texture sets, < 50 draw calls for smooth mobile browsers (rule of thumb). Run the validator: zero errors; warnings about unused data or non-power-of-two images are worth fixing for KTX2.

## 5. Mobile and standalone VR

Meta's per-frame guidance (Quest 2/Pro: 200–300 draw calls and 750k–1M triangles at medium simulation; Quest 3/3S: 400–600 draws and 1.3–1.8M; ≥ 72 FPS; PC VR 500–1,000 draws, 1–2M tris at 90 FPS). The limits bite in this order: draw calls → overdraw → texture memory → triangles.

### 5.1 Atlas small props

Atlas small props into shared materials with `scripts/atlas_bake.py --collection Props --out <dir> --size 1024 --margin-px 8`. It merges evaluated copies (originals kept hidden), adds a `UVAtlas` map packed at one texel density with a pixel gap (`scripts/uv_tools.py`), bakes BASECOLOR/ROUGHNESS/METALLIC/NORMAL (or `--orm`) selected-to-active from the untouched originals (`scripts/bake_maps.py`), and builds one `MAT_Atlas`. Then it verifies the result: colour error at every face centre against the socket value or a per-source reference bake, a bleed test at UV-island borders, and island gap / bleed-free mip levels.

- **Measured, 12 cubes with 12 materials** (6 solid, 2 object-space gradients, noise, image texture, roughness gradient, tilted normal map): 12 draw calls → 1, max centre error 0.75/255, bleed 0, normal-map tilt error 0.26° on rotated islands, 107.8 px/m everywhere, 18 s on CPU.
- **Planted `--margin-px 0`**: centres stay at 0.52/255, but bleed of 58.9/255 is flagged on all 8 constant-colour materials. The minimum island gap is 0.63 px, so 0 mip levels are bleed-free (8 px gap gives 3).
- **Keep 8 px at 1K and 16 px at 2K** for mip chains. The padding authority for the whole skill (px gap per texture size, bake margins) is the packing section of `uv-unwrapping.md` (§5); the numbers above are the measurement behind it.
- **Selected-to-active vs `--method SELF`**: SELF bakes the merged mesh itself, which changes Object/Generated texture coordinates (measured 62–107/255 error). Props touching within the 5 mm cage extrusion can pick up each other in selected-to-active mode, so space them apart or atlas them in separate groups.
- **Earlier measurement** (`scripts/scene_perf_report.py`): 20 props with 20 materials and 20× 1K textures came to 20 draw calls and 106.6 MB uncompressed / 26.6 MB compressed. Atlased to one 2K set: 1 draw call, 21.3 / 5.3 MB. Linked duplicates of one mesh reported 21 naive vs 2 instanced draw calls.

### 5.2 Instancing, lightmaps, textures

- **Instancing**: repeated meshes as linked duplicates / collection instances so the engine can GPU-instance or batch them (glTF: `export_gpu_instances` writes `EXT_mesh_gpu_instancing` for GN/collection instances). Level-scale instancing, HLOD and streaming cells: `large-sets-and-cities.md` §10.
- **Lightmaps**: static scenes bake lighting in the engine or in Blender (Cycles bake to a non-overlapping UV2 — `scripts/bake_maps.py --uv-map UV2`, `baking-maps.md`; lightmap UV rules in `uv-unwrapping.md` §5); keep UV2 through export (FBX/GLB keep it, OBJ drops it).
- **Textures**: ASTC on Android/Quest (4×4 ≈ 8 bits/pixel for normals and hero, 6×6 ≈ 3.56 bpp, 8×8 = 2 bpp for large surfaces); mips add 33 %. Memory estimate = w × h × bpp / 8 × 4/3. Prefer 1K/512 for props, pack grayscale maps into channels.

### 5.3 Alpha overdraw

Avoid large alpha-blended quads (smoke, foliage cards stacked in depth). Trim cards tight to the opaque area: more verts, fewer transparent pixels. No full-screen transparent effects. Alpha clip — `mat.surface_render_method = 'DITHERED'` with a thresholded Alpha (Alpha Clip was removed in 4.2; API in `shader-nodes.md` §2) — avoids sorting, but on tiled mobile GPUs it still costs a fragment per layer and defeats early-z.

- **Measure** with `scripts/scene_perf_report.py --budget quest3`. It classifies materials as BLENDED / ALPHA_CLIP / TRANSMISSION, then ray-casts a 96-px-wide grid from the active camera. Each pixel counts the transparent layers in front of the nearest opaque surface.
- **Output**: `transparent_coverage`, `overdraw_layers_mean` (full-screen transparent passes), `max_layers`, and per-object coverage with projected bbox area.
- **Quest budget** (rule of thumb): mean ≤ 0.5 layers, max ≤ 4.
- **Measured**: 10 stacked 4 m transparent planes gave coverage 0.5625 and 2.995 mean layers (analytic 0.549 / 2.957), max 10, budget fail. The same planes opaque gave 0 layers. With an opaque wall in front: 0 layers (occlusion counted). The alpha-clip version cost the same 2.995 layers.

### 5.4 Shaders and skinning

- **Shaders**: one Principled-style lit material, no transmission/refraction, no real-time shadows from many lights; emissive/unlit for signage.
- **Skinning**: 4 bone influences, one skinned mesh per character where possible, ≤ ~75 bones for Quest-class characters [rule of thumb].

## 6. Verifying a web or mobile delivery (scripts)

Shape-key clips (talking heads, morph animation): stage, export and re-import with `scripts/export_actions.py --meshes <mesh> --actions <clip> --preset web --formats glb` (no `--armature` needed); recipe and gates in `shape-keys-and-visemes.md` §6. Then the checks below.

| Question | Script | Proven by test |
|---|---|---|
| Does the GLB come back with the same size, axes, materials, UVs, normals, animation? | `scripts/export_check.py --preset web` | see `game-engine-delivery.md` §7 (same checks; `export_yup=False` → "axis error") |
| Does the GLB carry the extensions, variants, compression and texture formats the viewer needs? | `scripts/export_check.py --expect-extensions A,B --expect-variants Red,Blue` (export run) or `--inspect file.glb` | Draco + clearcoat/transmission + 2 variants → pass (2 Draco primitives, Red→MAT_Red / Blue→MAT_Blue mapping); variants preference off → "KHR_materials_variants not in extensionsUsed" + "variant(s) missing"; meshopt instead of Draco → missing Draco reported; wrong variant name → issue; hand-corrupted JSON (undeclared clearcoat, variant index 5) → structural issues; PNG vs `export_image_format='WEBP'` → `image/png` vs `image/webp` + `EXT_texture_webp` |
| Will the scene fit draw-call / texture / triangle / overdraw budgets? | `scripts/scene_perf_report.py --budget quest3\|quest2\|pcvr\|mobile\|web\|pc` (`--max-draw-calls` / `--max-tris` / `--max-texture-mb` override single limits; the draw-call gate uses `draw_calls_naive`) | 20-material vs atlased scene numbers in §5.1; overdraw numbers in §5.3; unused material slots listed |
| Did the atlas keep colours, normals and mip padding? | `scripts/atlas_bake.py` (built-in verification) | 0.75/255 centre error, 0 bleed, 0.26° tilt on the 12-cube test; `--margin-px 0` → 58.9/255 bleed flagged |

`export_check.py`'s glTF check reads JSON only (no accessor/bufferView bounds validation) — run the Khronos glTF Validator for full conformance, and load the file once in the real viewer per pipeline change.

## 7. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Procedural material is flat grey in glTF | Only image textures export | Bake to textures (`baking-maps.md`) |
| Transmission/clearcoat missing in viewer | Viewer lacks the extension | Check viewer support; bake a fallback look |
| Several variants show the same material | Mis-assigned variant slot | Inspect per-primitive mappings (`export_check.py --inspect`, `gltf-transform inspect`) |
| GLB fails to load: "Draco/meshopt decoder" error | Compressed file without decoder in the viewer | Register `DRACOLoader`/`MeshoptDecoder`, or export uncompressed |
| Huge GPU memory despite small GLB | JPEG/PNG/WebP decode to full RGBA | KTX2 (UASTC/ETC1S), smaller textures |
| Quest frame drops in simple-looking scene | Draw calls (one material per prop) or alpha overdraw | Atlas + merge/instance; alpha clip; `scene_perf_report.py` |
| Atlas colours wrong on gradient / noise materials | `--method SELF` changed Object/Generated coordinates, or props within the 5 mm cage picked up each other | Selected-to-active (default); space props apart or atlas in groups |
| Atlas bleeds at distance (mips) | Island gap too small | `--margin-px` 8 at 1K / 16 at 2K; padding table in `uv-unwrapping.md` §5 |
| Lightmap bake landed in the wrong UV set | Lightmap UV2 left active during a texture bake (or vice-versa) | `bake_maps.py --uv-map NAME`; `baking-maps.md` §2 |
