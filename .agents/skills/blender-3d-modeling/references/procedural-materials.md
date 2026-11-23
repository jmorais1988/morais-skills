# Procedural Materials (recipe catalog)

Read this when a surface is built from nodes instead of textures — statistical surfaces such as metal, paint, rubber, mud, rust, wood, concrete and fabric, terrain blends, and the tested layered worn-paint, car-paint flake, color-flop and candy-coat builds with their measured numbers. Helpers, socket/API traps and the full Python of the worn-paint build: `shader-nodes.md`; choosing between procedural, library and generated textures: `texture-sources-and-pbr-sets.md`.

## Contents
1. Recipe catalog
2. Layered worn paint (tested 5.2)
3. Car-paint flakes (tested 5.2)
4. Color flop and tinted clear coat (tested 5.2)
5. Common failures

## 1. Recipe catalog

Chains are left → right; numbers are starting points to tune against the reference.

| Material | Chain / settings |
|---|---|
| **Worn painted steel** (layered) | paint → bare steel on broken-up edges → cavity dirt → varying roughness → micro bump: §2 |
| **Brushed metal** | Object coords → Mapping (scale ≈ 1, 1, 300 across the brush direction) → Noise (detail 15) → Bump 0.05; Metallic 1, Roughness 0.25–0.35, Anisotropic 0.5–0.8; turned parts: Tangent node (radial) → Tangent input |
| **Rubber** (tires, belts, seals, hoses) | base ≈ #1c1c1c–#2a2a2a, Roughness 0.8–0.95, fine Noise bump; dust: Normal Z → Map Range → mix light grey-brown, roughness → 1; tire sidewall text as decal/normal |
| **Solid paint** | Metallic 0, Roughness 0.3–0.5, Coat Weight 0–1 (Coat Roughness 0.03 for glossy); orange peel: very fine Noise → Coat Normal via Bump 0.02 |
| **Metallic car paint** | flake layer: Metallic 1, Roughness 0.3–0.4, **random per-flake normal** (§3); Coat Weight 1, Coat Roughness 0.02–0.05, Coat Normal smooth (or orange peel) |
| **Mud / caked dirt** (vehicles, boots) | mask = (1 − height gradient from Position Z) × Noise (scale 3, detail 8) × (cavity or AO) + splatter (Voronoi F1 thresholded); wet mud #2e241a Roughness 0.15–0.3; dry mud #6b5a45 Roughness 0.9; mix wet↔dry by a second noise; Bump 0.3; hero: Displacement |
| **Rust** | Noise (scale 5, detail 10) × Voronoi → ColorRamp (constant) → mask placed by cavity + edges + gravity streaks (Normal Z & Mapping stretched in Z); color #5a2a12→#8a4a22, Metallic 0, Roughness 0.85, Bump 0.2 |
| **Wood** | Object coords + Noise into Vector (distortion) → Wave (Rings or Bands) with Mapping stretched along the grain → ColorRamp (two sampled browns) → base; same ramp → Roughness 0.45–0.7; bump low; varnish = Coat |
| **Concrete / plaster** | macro Noise (scale 2) × fine Noise → base value variation; Voronoi F1 → Map Range tiny pits → Bump; Roughness 0.85–0.95; stains by Position Z gradient + noise |
| **Stone / terrain blend** | slope mask: Geometry Normal Z → Map Range (0.77 → 0.87 ≈ 40°→30°); height: Position Z → Map Range; blend **per channel** (base, roughness, normal via Mix Vector) inside one Principled — cheaper than Mix Shader and blends normals correctly |
| **Fabric** | Wave Bands ×2 (rotated 90°) or Brick at thread scale → Bump; Sheen Weight 0.5–1, Roughness 0.8; fuzz: Layer Weight facing → lighter rim |
| **Glass** | `shader-nodes.md` §2 Glass |
| **Emissive screens/LEDs** | Emission Color from image/pattern, Strength by exposure; add a real light when it must illuminate surroundings |
| **Per-instance variation** | Object Info → Random (or Attribute `Instancer` type for GN instances) → Hue/Saturation/Value (±0.02 hue, ±10 % value) |
| **Decals / labels** | extra UV map → UV Map node → Image Texture (alpha) → mix into base/roughness/normal by alpha |
| **Stylized toon (EEVEE)** | Diffuse → Shader to RGB → ColorRamp (constant, 2–3 stops) → Emission or base; outlines via Solidify flipped + backface-culled black material (EEVEE-only; Cycles ignores backface culling — Cycles-safe toon and hull recipes: `stylized-npr.md` §3, `outlines-and-line-art.md` §2) |

Foliage, bark, grass: `flora.md` §5; fur, feathers, scales: `fauna.md`; terrain and water: `environment-modeling.md`.

## 2. Layered worn paint (tested 5.2)

Paint → bare steel on broken-up edges → cavity dirt → varying roughness → micro bump. The full Python build with the `N`/`sock`/`set_in` helpers is `shader-nodes.md` §3 (verified in 5.2: Cycles render, 21 links, no invalid/hidden links, wear mask measured on 0.5 m cubes).

| Layer | Nodes / settings |
|---|---|
| Edge mask | Bevel (Radius 0.03, samples 8) and Geometry Normal → Vector Math Dot Product → Map Range From Min 0.995, From Max 0.93 |
| Break-up | Object coords → Noise (Scale 25, Detail 6) × edge mask → ColorRamp (CONSTANT, second stop at 0.35) = wear (0/1) |
| Cavity dirt | AO (Distance 0.05, samples 16) → dirt = 1 − AO (Cycles-only node: bake it for EEVEE/export) |
| Base color | Mix RGBA: olive paint (0.20, 0.25, 0.08) → bare steel (0.55, 0.55, 0.53) by wear; then Mix MULTIPLY with dirt color (0.25, 0.22, 0.18) by dirt |
| Metallic | = wear (0 or 1) |
| Roughness | Map Range wear → To Min 0.45 (paint), To Max 0.25 (steel); + dirt, clamped |
| Micro bump | Object coords → Noise Scale 400 → Bump Strength 0.15, Distance 0.001 (set explicitly: the default is tiny) |

**The Bevel-node radius must exceed the geometry's own bevel**, or the shader normal matches the already-rounded mesh and the edge mask is empty. Measured: radius 0.01 → sharp cube 881 wear pixels, 2 cm-bevelled cube 30; radius 0.03 → 2217 and 294. Use ≈ 1.5× the modeled bevel width; scale noise with the object. Wrap the mask stacks as node groups (`NG_EdgeWear`, `NG_CavityDirt`, `NG_SlopeMask`, `NG_MacroVariation`; `shader-nodes.md` §3) so one tweak updates every material.

## 3. Car-paint flakes (tested 5.2)

A flake is a tiny tilted mirror, so each Voronoi cell needs its *own* normal (Voronoi Distance → Bump only makes smooth dimples). Measured on a 0.5 m sphere, small point light, Cycles 64 spp, 256 px, cell scale 400/m on the test sphere (the code below uses 3000/m, a production car-body value — 2000–5000/m `[unverified]`), strength 0.25 — pixels > 0.1 above their 5×5 local mean: no flakes 6, Voronoi → Bump 14, random normals **179** (high-pass std 0.0044 / 0.0144 / 0.0203). With the `shader-nodes.md` §3 helpers (`N`, `set_in`, `link`, `bsdf`):
```python
tc  = N(nt, 'ShaderNodeTexCoord', (-900, -600))
vor = N(nt, 'ShaderNodeTexVoronoi', (-700, -600), "flake cells", feature='F1'); set_in(vor, "Scale", 3000.0)  # per metre, object space
ctr = N(nt, 'ShaderNodeVectorMath', (-500, -600), "centre", operation='SUBTRACT'); ctr.inputs[1].default_value = (0.5, 0.5, 0.5)
amt = N(nt, 'ShaderNodeVectorMath', (-350, -600), "flake strength", operation='SCALE'); set_in(amt, "Scale", 0.5)  # 2 x 0.25
geo = N(nt, 'ShaderNodeNewGeometry', (-500, -800))
add = N(nt, 'ShaderNodeVectorMath', (-200, -650), operation='ADD'); nrm = N(nt, 'ShaderNodeVectorMath', (-50, -650), operation='NORMALIZE')
link(tc.outputs["Object"], vor.inputs["Vector"]); link(vor.outputs["Color"], ctr.inputs[0]); link(ctr.outputs["Vector"], amt.inputs[0])
link(geo.outputs["Normal"], add.inputs[0]); link(amt.outputs["Vector"], add.inputs[1]); link(add.outputs["Vector"], nrm.inputs[0])
link(nrm.outputs["Vector"], bsdf.inputs["Normal"])   # base/flake layer only; Coat Normal stays smooth
```
Strength 0.1–0.3. Sub-pixel flakes average to slightly rougher metal and denoisers smear them — judge sparkle at final resolution [unverified at production scale].

## 4. Color flop and tinted clear coat (tested 5.2)

**Color flop (pearlescent / two-tone)**: plain paint does **not** flop. At grazing angles the white coat reflection only desaturates it. Measured on a 0.5 m smooth sphere (uniform white world, Cycles 48 spp, 160 px orthographic) as mean linear HSV of the facing zone (cos θ > 0.9) → grazing zone (cos θ 0.15–0.35). Every variant is metallic, Roughness 0.35, Coat Weight 1, Coat Roughness 0.03:

| Variant | Facing H° / S / V | Grazing H° / S / V | ΔHue |
|---|---|---|---|
| Plain red metallic (0.35, 0.02, 0.03) | 358 / 0.84 / 0.37 | 358 / 0.37 / 0.56 | 0° |
| + Thin Film Thickness 300 nm, Thin Film IOR 1.5 | 88 / 0.46 / 0.16 | 347 / 0.39 / 0.56 | −100° |
| + Thin Film 500 nm | 79 / 0.52 / 0.14 | 347 / 0.36 / 0.54 | −91° |
| Layer Weight (Blend 0.35) **Facing** → ColorRamp red → purple (0.12, 0.02, 0.30) → Base Color | 356 / 0.84 / 0.36 | 308 / 0.26 / 0.47 | −48° |

- **Thin Film** gives strong iridescent flop, but it also **recolors the facing view** (red base read olive at 300/500 nm). Pick the thickness by the facing color, and use it for pearl/chameleon paints.
- **Layer Weight Facing → ColorRamp** keeps the face color exactly and puts the ramp's second color at the edges. Use it for art-directed two-tone flop (it works in EEVEE too). Blend ≈ 0.2–0.5 sets how far the edge color creeps in.
- Combine either with the flake normals (§3). Flop reads best on curved panels under an HDRI `[unverified]`.

**Tinted clear coat (candy)**: set Coat Tint over a bright base; the facing color ≈ Coat Tint × the untinted result. Measured:
- Grey base 0.7 dielectric, clear coat: facing (0.72, 0.72, 0.72). With Coat Tint (0.9, 0.55, 0.2) it becomes (0.65, 0.41, 0.17), H 30° S 0.74, and grazing drops to S 0.58 because the coat's own reflection stays untinted.
- Silver metallic 0.8: clear coat S 0 → Coat Tint (0.35, 0.55, 0.95) gives facing (0.30, 0.46, 0.77), H 220° S 0.61.

A candy color is a saturated Coat Tint over silver metallic + flakes. Keep Coat Tint value ≥ 0.3, or the paint goes black instead of deep `[unverified]`.

## 5. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Surface reads flat and CG at every distance | One noise at one scale instead of macro/meso/micro bands; uniform roughness | Band the noise (`materials-and-lookdev.md` §6); vary roughness per layer (§1–2) |
| Edge wear empty on a bevelled mesh | Bevel-node radius ≤ the modeled bevel | Radius ≈ 1.5× modeled bevel width (§2 measurement) |
| "Flakes" look like smooth dimples | Voronoi Distance → Bump | Random per-cell normals into the base Normal, Coat Normal smooth (§3) |
| Sparkle vanishes in the final frame | Sub-pixel flakes average out; denoiser smears them | Judge at final resolution; strength 0.1–0.3 [unverified at production scale] |
| Paint doesn't change hue at grazing angles | Plain metallic + clear coat only desaturates | Thin Film (pearl) or Layer Weight Facing → ColorRamp (two-tone) (§4) |
| Facing color wrong after adding Thin Film | Thin Film recolors the facing view too | Pick thickness by the facing color (§4) |
| Candy paint goes black | Coat Tint value too low | Keep Coat Tint value ≥ 0.3 `[unverified]` |
| Mask disappears in EEVEE / the engine | Bevel, Pointiness, AO are Cycles-only | Bake the mask (`baking-maps.md`) |
| Material exported unbaked | Engines and glTF/FBX don't read procedural nodes | Bake to maps and rebuild from the set (`baking-maps.md`, `texture-sources-and-pbr-sets.md` §4) |
