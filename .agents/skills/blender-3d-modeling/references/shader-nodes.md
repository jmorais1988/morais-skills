# Shader Nodes (Python node trees & API traps)

Read this when building or editing a material's node tree from Python (bpy, MCP or CLI): the Principled BSDF socket names and API traps of Blender 4.x–5.x, a tested layered worn-paint build with reusable helpers, and how to verify the result. What a material must prove: `materials-and-lookdev.md`; where textures come from and map-set builds: `texture-sources-and-pbr-sets.md`; the recipe catalog: `procedural-materials.md`; UVs, texel density and the high→low bake setup: `uv-unwrapping.md`.

## Contents
1. Material task protocol
2. Node-tree rules (API traps in 4.x–5.x)
3. Building node trees in Python — tested example
4. Verification
5. Common failures

## 1. Material task protocol

1. **Spec** each material in NOTES.md (`materials-and-lookdev.md` §2).
2. **Discover tools** once per session and note them in the project state: image-generation tools and skills (`texture-sources-and-pbr-sets.md` §3), MCP asset tools (`texture-sources-and-pbr-sets.md` §2), add-ons (Node Wrangler).
3. **Choose the source** per material (`texture-sources-and-pbr-sets.md` §1); mixing is normal (library albedo + procedural moss mask + baked AO).
4. **Build** in Python (§3) or with `scripts/build_pbr_material.py` for map sets (`texture-sources-and-pbr-sets.md` §4; UDIM tile sets `.1001`/`_1001`/`<UDIM>` become tiled images automatically — `uv-unwrapping.md` §6, `baking-maps.md` §6); name nodes and frames.
5. **Verify** (§4); **bake** for engines, glTF/FBX or EEVEE-incompatible nodes — Baking: `baking-maps.md`.

Independent materials make good parallel lanes (`parallel-work-with-subagents.md`): each owns `textures/<MAT_name>/` and delivers maps + preview + report; the Blender owner builds and assigns.

## 2. Node-tree rules (API traps in 4.x–5.x)

- **Color space**: `image.colorspace_settings.name = 'sRGB'` for base and emission color; **`'Non-Color'`** for normal, roughness, metallic, height, AO, opacity and all masks. "Linear Rec.709" is not Non-Color (it still converts). Wrong color space = washed-out normals and secretly gamma-curved roughness.
- **Principled BSDF names (4.0+)**: Base Color, Metallic, Roughness, IOR, Alpha, Normal, Diffuse Roughness (4.3+), Subsurface Weight/Radius/Scale/IOR/Anisotropy, Specular IOR Level, Specular Tint, Anisotropic, Anisotropic Rotation, Tangent, Transmission Weight, Coat Weight/Roughness/IOR/Tint/Normal, Sheen Weight/Roughness/Tint, Emission Color, Emission Strength, Thin Film Thickness/IOR (4.2+), **Thin Wall** (5.2+, boolean: the surface is a thin sheet — single-plane window glass, leaves, paper; `archviz-lighting-and-rendering.md` §4). Pre-4.0 names (Subsurface, Specular, Clearcoat, Transmission, Emission) raise KeyError; guard version-dependent inputs with `"Thin Wall" in bsdf.inputs`.
- **Look sockets up by name *and* `enabled`**: some Principled inputs are disabled by settings, and `ShaderNodeMix` carries hidden duplicate `A`/`B`/`Result` sockets per data type. Use the enabled one or identifiers (`Factor_Float`, `A_Color`, `B_Color`, `Result_Color`); set `data_type='RGBA'|'FLOAT'|'VECTOR'` *before* linking.
- **bl_idnames that trip people**: Geometry = `ShaderNodeNewGeometry`; ColorRamp = `ShaderNodeValToRGB`; legacy MixRGB = `ShaderNodeMixRGB`; Separate/Combine Color = `ShaderNodeSeparateColor`/`ShaderNodeCombineColor`.
- **Metallic** is 0 or 1 per region (`materials-and-lookdev.md` §1): drive it with a thresholded mask.
- **AO**: Principled has no AO input. Don't multiply AO into base color for Cycles (it already occludes); a light multiply (0.2–0.5) is acceptable only as an EEVEE/game-preview fake. For glTF, plug AO into a group node named **"glTF Material Output"** with input **"Occlusion"** (`scripts/build_pbr_material.py --gltf-occlusion`).
- **Bump node**: set `Strength` and `Distance` explicitly — the 5.2 defaults are Strength 1.0 and Distance 0.001 (1 mm), too small to read on metre-scale objects. Height is data (Non-Color).
- **Normal Map node**: tangent space needs UVs, and the node's UV map must match the texture's. Blender is OpenGL (Y+); Unreal/DirectX maps are Y− (which engine wants which: `game-engine-delivery.md` §2): 5.1+ set the Normal Map node's `node.convention = 'DIRECTX'` (enum `OPENGL`/`DIRECTX`, verified 5.2); older builds flip green (Separate Color → 1−G → Combine). Baking for DirectX targets is `scripts/bake_maps.py --normal-convention DIRECTX`.
- **True displacement**: Displacement node → Material Output *Displacement*; `mat.displacement_method = 'BOTH'` (older: `mat.cycles.displacement_method`); needs dense or adaptive subdivision, otherwise bump only.
- **Cycles-only nodes**: Bevel node, Geometry → Pointiness; the AO node is approximate outside Cycles. Bake masks that use them before EEVEE/engine use.
- **EEVEE 4.2+ transparency**: `mat.surface_render_method = 'DITHERED'` (default) or `'BLENDED'` (sorted semi-transparency); legacy `blend_method` is deprecated, `shadow_method` and Alpha Clip were removed (threshold alpha with Math Greater Than); Thickness output for thin translucent parts.
- **Glass**: Transmission 1, IOR 1.45–1.52, Roughness 0–0.05, near-white base, tint via Volume Absorption on the Volume output (density ≈ 5–15 faint, 30–50 medium); bounce counts: `rendering-and-lighting.md` §4 (not restated here); thin panes: Thin Wall (5.2+). Caustics off for interiors (`archviz-lighting-and-rendering.md` §2); product/liquid shots: path-traced `caustics_refractive`/`caustics_reflective`. MNEE flags (`light.cycles.is_caustics_light`, `ob.cycles.is_caustics_caster`/`is_caustics_receiver`; verified 5.2) gave no caustic in 5.2 tests and blackened flagged shadows — unreliable (`rendering-and-lighting.md` §4).
- `mat.use_nodes = True` still works in 5.2 with a deprecation warning (removal planned for 6.0).

## 3. Building node trees in Python — tested example

Helpers + a worn painted-steel material (paint → bare steel on broken-up edges → cavity dirt → varying roughness → micro bump). Verified in 5.2: Cycles render, 21 links, no invalid/hidden links, wear mask measured on 0.5 m cubes. The same chain as a settings table, next to the other recipes: `procedural-materials.md` §2.

**The Bevel-node radius must exceed the geometry's own bevel**, or the shader normal matches the already-rounded mesh and the edge mask is empty. Measured: radius 0.01 → sharp cube 881 wear pixels, 2 cm-bevelled cube 30; radius 0.03 → 2217 and 294. Use ≈ 1.5× the modeled bevel width; scale noise with the object.

```python
import bpy

def N(nt, kind, loc, label="", **props):
    n = nt.nodes.new(kind); n.location = loc; n.label = label
    for k, v in props.items(): setattr(n, k, v)
    return n

def sock(sockets, name):
    """Enabled socket by name: Mix nodes carry hidden duplicate 'A'/'B'/'Result' sockets per data type."""
    return next(s for s in sockets if s.name == name and s.enabled)

def set_in(node, name, value):
    sock(node.inputs, name).default_value = value

mat = bpy.data.materials.new("MAT_PaintedSteel_Worn"); mat.use_nodes = True
nt = mat.node_tree; nt.nodes.clear(); link = nt.links.new
out  = N(nt, 'ShaderNodeOutputMaterial', (1100, 0))
bsdf = N(nt, 'ShaderNodeBsdfPrincipled', (800, 0)); link(bsdf.outputs["BSDF"], out.inputs["Surface"])
coord = N(nt, 'ShaderNodeTexCoord', (-1000, 0))

# edge-wear mask: angle between a bevel-rounded normal and the true normal (Cycles), broken up by noise
bevel = N(nt, 'ShaderNodeBevel', (-800, -200), "edge normal", samples=8); set_in(bevel, "Radius", 0.03)  # > modeled bevel width
geo   = N(nt, 'ShaderNodeNewGeometry', (-800, -400))
dot   = N(nt, 'ShaderNodeVectorMath', (-600, -300), "cos(angle)", operation='DOT_PRODUCT')
link(bevel.outputs["Normal"], dot.inputs[0]); link(geo.outputs["Normal"], dot.inputs[1])
edge  = N(nt, 'ShaderNodeMapRange', (-400, -300), "edge mask"); set_in(edge, "From Min", 0.995); set_in(edge, "From Max", 0.93)
link(dot.outputs["Value"], edge.inputs["Value"])
brk   = N(nt, 'ShaderNodeTexNoise', (-600, 0), "wear breakup"); set_in(brk, "Scale", 25.0); set_in(brk, "Detail", 6.0)
link(coord.outputs["Object"], brk.inputs["Vector"])
wearm = N(nt, 'ShaderNodeMath', (-200, -200), "edge x noise", operation='MULTIPLY')
link(edge.outputs["Result"], wearm.inputs[0]); link(brk.outputs["Fac"], wearm.inputs[1])
wear  = N(nt, 'ShaderNodeValToRGB', (0, -200), "wear threshold")          # ColorRamp
wear.color_ramp.interpolation = 'CONSTANT'; wear.color_ramp.elements[1].position = 0.35
link(wearm.outputs["Value"], wear.inputs["Fac"])

# cavity dirt from AO (Cycles-only node: bake it for EEVEE/export)
ao   = N(nt, 'ShaderNodeAmbientOcclusion', (-400, 300), "cavity", samples=16); set_in(ao, "Distance", 0.05)
dirt = N(nt, 'ShaderNodeMath', (-200, 300), "dirt = 1 - AO", operation='SUBTRACT')
dirt.inputs[0].default_value = 1.0; link(ao.outputs["AO"], dirt.inputs[1])

# base color: paint -> bare steel where worn -> darkened by dirt
paint = N(nt, 'ShaderNodeMix', (200, 200), "paint / steel", data_type='RGBA')
sock(paint.inputs, "A").default_value = (0.20, 0.25, 0.08, 1)     # olive paint (sample from reference)
sock(paint.inputs, "B").default_value = (0.55, 0.55, 0.53, 1)     # bare steel
link(wear.outputs["Color"], sock(paint.inputs, "Factor"))
grime = N(nt, 'ShaderNodeMix', (450, 200), "dirt", data_type='RGBA', blend_type='MULTIPLY')
sock(grime.inputs, "B").default_value = (0.25, 0.22, 0.18, 1)
link(sock(paint.outputs, "Result"), sock(grime.inputs, "A")); link(dirt.outputs["Value"], sock(grime.inputs, "Factor"))
link(sock(grime.outputs, "Result"), bsdf.inputs["Base Color"])

# metallic follows wear (0 or 1); roughness paint 0.45 -> steel 0.25, +dirt
link(wear.outputs["Color"], bsdf.inputs["Metallic"])
rough = N(nt, 'ShaderNodeMapRange', (450, -100), "roughness"); set_in(rough, "To Min", 0.45); set_in(rough, "To Max", 0.25)
link(wear.outputs["Color"], rough.inputs["Value"])
radd = N(nt, 'ShaderNodeMath', (620, -100), "+ dirt", operation='ADD', use_clamp=True)
link(rough.outputs["Result"], radd.inputs[0]); link(dirt.outputs["Value"], radd.inputs[1])
link(radd.outputs["Value"], bsdf.inputs["Roughness"])

# micro relief: fine noise -> Bump (set Distance explicitly: its default is tiny)
fine = N(nt, 'ShaderNodeTexNoise', (200, -450), "micro"); set_in(fine, "Scale", 400.0)
link(coord.outputs["Object"], fine.inputs["Vector"])
bump = N(nt, 'ShaderNodeBump', (500, -450)); set_in(bump, "Strength", 0.15); set_in(bump, "Distance", 0.001)
link(fine.outputs["Fac"], bump.inputs["Height"]); link(bump.outputs["Normal"], bsdf.inputs["Normal"])
```

**Reusable mask groups**: wrap mask stacks as node groups (`NG_EdgeWear`, `NG_CavityDirt`, `NG_SlopeMask`, `NG_MacroVariation`) with `ng = bpy.data.node_groups.new(name, 'ShaderNodeTree')`, `ng.interface.new_socket("Mask", in_out='OUTPUT', socket_type='NodeSocketFloat')`, used via `ShaderNodeGroup` (`node.node_tree = ng`) so one tweak updates every material.

## 4. Verification

- Three look-dev views (`materials-and-lookdev.md` §7); checker for stretch and density before texture work (`uv_tools.py check`, `uv-unwrapping.md`); a distance shot of tiled areas (repetition shows from far).
- **Normal convention**: a raised bump lit from above must look raised; a dent means green is flipped.
- **Channel isolation**: route roughness / metallic / masks into an Emission shader and render (no hidden gamma, masks where intended).
- EEVEE deliverables: compare against Cycles (Bevel/Pointiness/AO differ).

## 5. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Washed-out normals, secretly gamma-curved roughness | Data maps loaded as sRGB (or "Linear Rec.709", which still converts) | `'Non-Color'` for normal, roughness, metallic, height, AO, opacity and masks (§2) |
| KeyError on Subsurface / Specular / Clearcoat / Transmission / Emission | Pre-4.0 Principled socket names | 4.0+ names (§2); guard version-dependent inputs with `"Thin Wall" in bsdf.inputs` |
| Link lands on a hidden or disabled socket | `ShaderNodeMix` duplicate `A`/`B`/`Result` per data type; Principled inputs disabled by settings | Look up by name *and* `enabled` (the `sock` helper, §3) or use identifiers; set `data_type` before linking |
| Cavities doubly dark in Cycles | AO multiplied into base color | Don't (Cycles already occludes); 0.2–0.5 multiply only as an EEVEE/game fake; glTF via "glTF Material Output" → Occlusion |
| Raised details read as dents | DirectX (Y−) normal map read as OpenGL | `node.convention = 'DIRECTX'` (5.1+) or flip green; check a bump lit from above (§4) |
| Bump has no visible effect | Bump `Distance` defaults to 0.001 (1 mm) | Set both explicitly (§2) |
| Metal looks like grey plastic | Fractional Metallic | 0 or 1 per region via a thresholded mask |
| Edge-wear mask empty on a bevelled mesh | Bevel-node radius ≤ modeled bevel | Radius ≈ 1.5× the modeled bevel width (§3 measurement) |
| Mask works in Cycles, gone in EEVEE/engine | Bevel, Pointiness and AO nodes are Cycles-only (AO approximate elsewhere) | Bake the mask first (`baking-maps.md`) |
| Metal or worn-to-metal edges render black | Judged in a dark/empty world: metal reflects its surroundings | HDRI or bright neutral world |
| Bake gives black metals or misses Metallic | Diffuse bake of a metal; Principled nodes inside node groups aren't rerouted by `scripts/bake_maps.py` (BASECOLOR bakes diffuse color only with metals temporarily non-metallic, METALLIC via a temporary emission reroute) | Ungroup, or bake those channels via Emit (`baking-maps.md`) |
| Unnamed node soup | No labels, frames or groups | Label nodes, use frames and `NG_*` groups (§3) |
