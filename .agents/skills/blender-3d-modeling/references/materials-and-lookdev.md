# Materials & Look Development

The model's silhouette is right, and the render still doesn't look like the reference. That's a **look-dev problem, not a geometry problem**: flat single-color albedo, uniform roughness, no relief response, no local wear/dirt, lighting that's only ambient. This file gives the Blender (Principled BSDF / Cycles / EEVEE) equivalents of a disciplined material pass. For building the node trees in Python see `shader-nodes.md`; procedural recipes: `procedural-materials.md`; library/AI-generated textures with derived PBR maps: `texture-sources-and-pbr-sets.md`; baking: `baking-maps.md`.

## Contents
1. Vocabulary → Principled BSDF
2. Material-pass requirements
3. Local overrides: masks
4. Reference-derived color and PBR evidence
5. Projection texturing and de-lighting
6. Frequency bands, texel density, projection
7. Lighting pass & three look-dev views
8. Character material recipes
9. Review order for material/lighting screenshots

## 1. Vocabulary → Principled BSDF

| Term | Principled BSDF / node | Notes |
|---|---|---|
| albedo / base color | Base Color | lighting removed; sample medians from the reference, never highlights/shadows |
| metalness | Metallic (0 or 1, rarely between) | shiny plastic is *not* metal; painted metal is dielectric on top |
| roughness | Roughness | 0.05–0.2 polished, 0.3–0.5 satin, 0.6–0.9 matte; **always vary it** |
| specular F0 | IOR / Specular IOR Level | ~1.45–1.5 (4 %) dielectrics |
| normal / relief | Normal Map or Bump → Normal | brushing, casting grain, pores |
| displacement | Material Output → Displacement (+ Adaptive Subdivision in Cycles) | only when relief must change silhouette/close-up shape |
| AO / cavity dirt, edge wear | AO node or baked AO; Pointiness (convex) or baked Curvature | dirt in cavities; lighter/polished underlayer on crests (§3) |
| clearcoat, anisotropy, sheen | Coat; Anisotropic (+ Rotation, needs tangents); Sheen | lacquer/car paint/wet; brushed metal, hair, fibers; velvet, cloth rim |
| transmission / translucency | Transmission; Subsurface | glass; skin, wax, leaves |
| emissive | Emission Color / Strength | add a real light if it must illuminate neighbors |
| alpha | Alpha | cutouts for hair cards, foliage |
| decal | UV-projected texture mixed by mask, or decal geometry with Shrinkwrap | printed labels, stickers |

Exact socket names, color spaces, EEVEE transparency and version traps: `shader-nodes.md` §2. Independent channels: never reuse the albedo as roughness, height or AO (desaturated albedo as roughness is the classic "plastic-y" tell).

## 2. Material-pass requirements

Before accepting a material, the plan (NOTES.md) must state and the render must prove:
- **Albedo palette**: dominant, secondary, accent colors and *where* they sit; sampled hex values.
- **Roughness response**: base value + variation + local response (smoother on worn edges and handled areas, rougher in cavities and on oxidized zones).
- **Tactile response**: at least one of normal / bump / displacement with a stated scale and strength; readable under grazing light.
- **Locality**: wear, chips, scratches, stains, dirt, moss, patina, soot, wetness tied to regions the reference shows.
- **Material-specific behavior**: transmission/SSS for thin or translucent parts, clearcoat for lacquer, anisotropy for brushed metal, sheen for cloth.
- **Geometric relief**: cracks, seams, folds, chips that affect the silhouette → geometry or displacement, not texture alone.
- **Projection/UV intent** and texel density so detail doesn't stretch across differently scaled parts.
- **Resolution**: ≥1k procedural/baked maps for close-up hero materials, 2k–4k when reference fidelity is the priority.

"Brown bark", "dark metal", "rough stone" are not material descriptions. Translate: "bark: albedo #4a3a2a→#7a6a55 vertical gradient, roughness 0.75 ± 0.1 with 0.6 on ridge crests, vertical ridge bump 2–4 cm wavelength, cavity dirt #2b241c in cracks, moss #4f6b2f patches at root flare, displacement 5 mm".

## 3. Local overrides: masks

Build materials as **base layer + masked overrides** (Mix Shader or Mix Color driven by a mask), where masks come from:
- **Vertex groups** → Attribute node (paint the mask in Weight Paint; the most controllable).
- **Vertex colors / Color Attributes** → Color Attribute node (stylized markings, quick region masks).
- **Geometry → Pointiness** (Cycles) or a baked **Curvature** map: convex = edge wear, concave = cavity dirt.
- **Ambient Occlusion** node or baked AO: dirt accumulation, contact grime.
- **Gravity streaks**: Geometry → Normal, separate Z; downward-facing/ vertical surfaces get streak noise stretched in Z (Mapping node scale).
- **Position/Object coordinates** with Gradient/Noise textures for world-space or object-space mottling, height-based fading, sun-bleaching from above.
- **Painted image masks** (Texture Paint) for anything the reference shows in a specific place — a scratch cluster, a stain, a decal region (painting workflow and layer add-ons: `texture-painting.md`).
- **Geometry Nodes attributes** (e.g. distance to another object, curvature) stored to attributes for complex procedural masks.

Compose: `Base` → `Edge wear` (Pointiness, lighter/metal exposed, lower roughness) → `Cavity dirt` (AO, darker, higher roughness) → `Stains/paint` (painted masks) → `Decals`. Each override touches the right channels (a stain darkens albedo *and* raises roughness; a gloss zone lowers roughness only).

## 4. Reference-derived color and PBR evidence

- Sample albedo as region **medians** with `scripts/measure_reference.py --regions`, avoiding highlights and shadowed zones. Photos include baked lighting, exposure and camera response — treat samples as evidence, not truth; check under neutral light.
- Infer roughness from highlight shape (tight → low, broad/soft → high) and metalness from whether reflections are colored (metal) or white (dielectric). Confidence is limited from one photo; say so.
- Patterned finishes (camo, marble, fades, printed graphics): a procedural approximation reads wrong. Use the reference's own pixels via projection (§5) or a painted texture; reserve procedurals for flat paints and materials with statistical texture (cast metal, plaster).

## 5. Projection texturing and de-lighting

When the goal is matching a specific reference's surface (a face, a painted skin, a labeled object), put the photo's pixels on the mesh:
1. **Camera match**: create a camera, set `lens` (35–50 mm typical), position it so the model's silhouette overlays the reference at matched framing (use the reference as camera background image, `camera.data.show_background_images`).
2. **De-light** the reference first: high-pass/frequency separation (duplicate, blur large radius, subtract → neutral base) in an image editor or Blender's compositor; remove specular hotspots and cast shadows by cloning; AI delighters if available. Baked lighting in albedo fights the new scene's lights — this is a hard requirement, not polish.
3. **Project**: UV Project modifier with the matched camera as projector (or Texture Paint → Project from View, or the `Image → Project Paint` clone tool), onto a dedicated UV map.
4. **Bake** the projected result into the mesh's real unwrapped UVs (Cycles Bake, Emit or Diffuse Color, selected-to-active from a duplicate), so the texture survives from all angles.
5. **Unseen regions**: request another view first; mirror across the symmetry plane where anatomically valid (faces yes, asymmetric hair/clothes no); palette-continue from the nearest edge as a last resort. Record per-region confidence and never present an inferred back as observed.

## 6. Frequency bands, texel density, projection

- Close-up materials need **macro** (large-scale color/height variation), **meso** (features: grain, plates, weave), and **micro** (fine noise) bands, each with an object-relative scale. A single noise texture reads as "CG noise".
- Texel density consistent across parts seen together (e.g. 1024 px/m for hero props), checked with a checker texture; UV-scale parts, don't texture-scale them. Density targets per platform and the tools live in `uv-unwrapping.md` §4 (the 1024 px/m figure is that table's hero-prop row).
- State the projection per part: UV unwrap for anything painted/baked; triplanar/Box mapping for rocks, terrain and quick procedurals (blend settings: `environment-modeling.md` §4); cylindrical for pipes/bottles; object-space procedurals for markings.
- Tiling: break repetition with a second noise-driven mapping offset or a macro variation layer; micro detail must not "swim" when the object scales.

## 7. Lighting pass & three look-dev views

Materials must read correctly in neutral light before you reproduce the reference's light. Capture three views before accepting a look:
1. **Neutral**: soft key + fill (large area lights) or a neutral studio HDRI, mid exposure — honest albedo and form.
2. **Grazing**: a low-angle hard key close-up — exposes plastic-uniform highlights, weak normals, flat roughness, and tiling.
3. **Reference-match**: camera and light direction as close to the source photo as evidence allows — the likeness check.
A material that only convinces under reference-matched light hasn't passed; fix its response first.

Lighting plan fields: key direction/color temperature/intensity/shadow softness; fill or explicit "no fill"; rim/back light or environment reflection for silhouette separation; ambient/world color; exposure and view transform (Filmic/AgX vs Standard — match the reference's contrast intent); background; contact/ground shadow (shadow catcher plane). Real lights, not ambient-only. Light rigs and engine settings: `rendering-and-lighting.md` §1–§2; passes and compositing: `render-farm-and-compositing.md` §4–§5.

## 8. Character material recipes

- **Skin**: Principled Subsurface (Random Walk) with radius scaled to real skin (~1.0, 0.2, 0.1 in Blender's default units, scale 0.05–0.1 m), warm base sampled from the reference, roughness 0.35–0.5 with lower values on nose/forehead (oily zones), fine pore bump; backlit ears/fingers glow via SSS — don't fake with rim light alone.
- **Eyes**: cornea shell (Transmission 1, IOR 1.38) over a sclera/iris sphere; iris slightly concave with a bump; pupil dark; a **catchlight** comes from a real key light — leave the eye smooth and glossy so it appears. Wet line at the lid.
- **Hair**: Principled Hair BSDF (melanin controls) for strands; anisotropic Principled for ribbons/cards; AO between locks.
- **Cloth**: Sheen for velvet/wool rim; woven normal map at the right scale; folds from geometry (cloth sim or sculpt) not just texture; stitches and seams as override masks.
- **Stylized smooth skin**: roughness 0.5–0.6, no metallic, light coat 0.1–0.2 with coat roughness 0.6, colored sheen for rim falloff; **no noise normal map** — let the subdivided geometry carry the form. Toon/cel shading, outlines and NPR looks: `stylized-npr.md`.
- **Markings (L5)**: object/UV-space gradients mixed by smoothstep-like ramps (Map Range) rather than vertex colors on irregular remeshed topology, which produce jagged bands.

## 9. Review order for material/lighting screenshots

1. Albedo palette close to the reference? 2. Value range: cavities dark, highlights placed correctly? 3. Surface response: does roughness break the highlight independently of color; does relief catch grazing light? 4. Locality: wear/dirt/stains where the reference shows them? 5. Light structure identifiable (key, fill, rim, contact shadow, exposure)? 6. Relit neutrally, does the object still have believable material detail?

If the mismatch is color/texture/light and the plan already lists the fields above → fix the material. If the plan doesn't → the plan is shallow; go back to the reference study.
