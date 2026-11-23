# Flora (trees, shrubs, grass, flowers, succulents, vines)

Plants read as real when their **growth logic** is right: branch radii that conserve area, leaves arranged by the species' phyllotaxis, crowns with holes, response to light and gravity. They read as fake when they are symmetric lollipops, uniform clones, or dense blobs with no light passing through. Profile: `project_state.py init --profile flora`. Placement in scenes: `environment-modeling.md` §9.

## Contents
1. Species study
2. Growth-structure rules
3. Construction methods
4. Leaves: geometry vs cards vs billboards
5. Materials
6. Variation sets
7. Wind
8. LOD & budgets
9. Review & common failures

## 1. Species study

Identify the species (or the closest real one for a fictional plant) and record, from references:
- **Habit**: tree / shrub / grass / herb / succulent / vine / fern; mature height and crown width; age class.
- **Branching**: monopodial (one dominant leader, conical — firs, spruces) vs sympodial/deliquescent (leader splits, spreading crown — oaks, maples); branch angle ranges from the trunk at each generation; number of visible generations (usually 3–5); drooping, ascending, or horizontal.
- **Phyllotaxis**: alternate (spiral, often ≈ 137.5° golden angle), opposite (pairs, successive pairs rotated 90° — decussate), whorled (3+ per node); leaves per twig; internode length.
- **Leaf**: shape, length × width, petiole length, fold along the midrib, curl, glossy/matte top vs underside color, translucency when backlit.
- **Bark**: pattern (plates, vertical fissures, horizontal lenticels, peeling), color range, moss/lichen side.
- **Environment response**: wind-bent (prevailing direction), light-seeking (crown biased toward open side; forest trees have high crowns and bare lower trunks), crowding, damage (broken branches, dead twigs 5–15 %).
- Season: leaf color, flowers/fruit, bare branches.

## 2. Growth-structure rules

- **Leonardo's rule**: at a fork, parent cross-section area ≈ sum of children's (d_parent² ≈ Σ d_child²). Use it to set radii at every split; violating it (thick twigs on thin branches or vice versa) is visible immediately.
- Taper continuously along each branch; flare at the trunk base into root buttresses; bulge slightly at forks (branch collar).
- No perfectly straight segments: add low-frequency bends and small kinks at nodes; gravity droops long heavy branches; tips turn toward light.
- Branch spacing along the parent follows the phyllotaxis of the species (spiral for alternate, pairs for opposite).
- Crowns have **negative space**: sky visible through them, clumps of foliage separated by gaps. A solid silhouette is the #1 fake-tree tell.
- Grass blades: taper to a tip, bend increasing toward the tip, twist slightly; clumps grow from a tight base.
- Flowers/rosettes/pinecones/sunflower seeds: Vogel spiral — element n at angle n·137.5°, radius c·√n.

## 3. Construction methods

| Method | Best for | Notes |
|---|---|---|
| **Sapling Tree Gen** extension | fast generic trees, many variants by seed | v0.3.7 requires Blender 4.4+; reports of failures on 5.x — verify it registers before planning on it; output is curves (convert → mesh) with leaf planes |
| **Geometry Nodes tree** | parametric species, variants by seed, integrated scatter | curve lines per generation → Resample → Instance child branches on points (rotation from tangent + phyllotaxis angle via index × angle) → Set Curve Radius (Leonardo) → Curve to Mesh; leaves instanced at twig points |
| **Skin modifier** on an edge skeleton | hand-authored hero trunks/roots | per-vertex radius, then Subdivision → sculpt bark relief (or Displace), retopo if needed |
| **Curves with bevel + taper object** | vines, lianas, thin branches, roots on the surface | Shrinkwrap/snap to the host surface; hooks for attachment |
| **Sculpt** | hero trunks, gnarled roots, stumps | from Skin base; bake to low-poly for games |
| **Screw / lathe + Displace** | cacti, palm trunks (ring scars), bamboo | ribs via profile shape; segments via Array |
| **GN phyllotaxis instancing** | flowers, rosettes (succulents, agave), pinecones, ferns (pinnae along rachis) | index → angle 137.5° (or 180°/90° for alternate/opposite) and radius √index; scale by index for size gradient |
| **Hair curves / instanced blades** | close-up grass, moss, fur-like lichen | hair curves render in Cycles/EEVEE, groom with Sculpt Curves (`fauna.md` §5) |
| **Asset libraries** (botaniq, GrassBlade, Geo-Scatter biomes) | production speed | paid unless noted; check installed and license; still apply the study and variation rules |

Build order: trunk & primary branches → silhouette check against reference (crown shape, holes) → secondary/tertiary branches → twigs → leaves → materials → variants → LODs.

## 4. Leaves: geometry vs cards vs billboards

| Distance / target | Representation |
|---|---|
| Hero close-up (render) | modeled leaf mesh: outline polygon, midrib fold (V-shape 5–20°), curl, slight thickness via Solidify or single-sided; petiole geometry attaching to the twig |
| Midground / game LOD0 | **cards**: leaf clusters rendered/baked onto alpha-textured planes (2–4 crossed or curved cards per cluster); cut the card polygon to the alpha silhouette (6–8 verts instead of a quad) to reduce overdraw |
| Far / game low LOD | billboards / impostors (engine impostor bakers) |

- Author cards by modeling a high-poly leaf cluster and baking to a plane: base color + alpha + normal + translucency/thickness (`scripts/bake_maps.py` with `--source`, or render orthographic with a transparent film).
- **Soft crown shading**: transfer custom normals from a proxy ellipsoid around the crown (Data Transfer → Face Corner Data → Custom Normals). Cards then shade as a volume instead of flickering flat planes.
- Alpha in EEVEE 4.2+: material **Render Method** `Dithered` (default, sort-free) or `Blended` (sorting issues); Alpha Clip was removed — threshold in the shader (Math Greater Than on alpha) if hard edges are needed. Python: `mat.surface_render_method = 'DITHERED'`. Shadows are per object (Visibility → Ray Visibility → Shadow) plus material Transparent Shadows.
- Leaves must attach: petiole ends on a twig, twigs on branches. Floating leaf clouds reveal themselves in close-ups and silhouettes.

## 5. Materials

- **Leaf**: base color sampled from reference (top and underside differ — underside lighter/greyer; use Geometry → Backfacing to switch); roughness 0.4–0.7 (waxy leaves lower, with a thin coat); **translucency** is what sells backlit foliage — Principled Subsurface with a small weight, or mix in a Translucent BSDF (≈ 0.2–0.5) tinted yellow-green. In EEVEE set the material **Thickness** to one leaf's thickness (≈ 0.2–0.5 mm; 0 = thin sheet), not the whole card. Vein detail via normal/bump; color variation along the leaf (edges and tips drier).
- **Per-instance variation**: Object Info → Random (or Attribute `id`/stored random from GN, Instancer) → hue/value shift ±5–10 %, a few % of yellowed/dry leaves; never identical leaf color across a tree.
- **Bark**: cylindrical UVs (seam at the back) or box projection with stretched scale along the trunk axis; macro color variation; cavity dirt in fissures; moss/lichen mask by world normal (upward and one side) + noise; roughness 0.75–0.95. Displacement or sculpt for hero bark, normal map otherwise.
- **Grass**: root-to-tip gradient (UV V or curve intercept): darker/yellow at root, lighter at tip; translucency; roughness varies; dry blades mixed in.
- **Flowers/fruit**: petals translucent (SSS), sheen for velvety petals, clearcoat for glossy fruit.
- Shader node patterns: `shader-nodes.md` §3; baking for export: `baking-maps.md` §2.

## 6. Variation sets

- Minimum 3–5 variants per species for any scattered use (different seeds/branch layouts), plus scale (±20–30 %), yaw, slight lean; 1–2 damaged/dead variants mixed at low frequency.
- Keep variants in one collection with consistent origins at the trunk base on the ground (pivot at soil level), so scatter pick-instance works.
- Test a 20-instance grove render: if two copies are recognizable side by side, add variation.

## 7. Wind

- **Blender render**: GN Set Position offset = noise(time, position) × bend weight; store a weight attribute that is 0 at the trunk base and increases with height and with branch generation (trunk sways slowly, twigs and leaves flutter fast with higher frequency). Single plants: Simple Deform Bend with an animated angle and a vertex-group limit.
- **Game engines**: bake wind data into vertex colors/UV channels per the engine's foliage shader convention (commonly per-vertex branch weight/phase/stiffness) or use Unreal Pivot Painter 2 (hierarchy pivots in textures; documented tooling is 3ds Max-based — check community Blender exporters before promising it).
- Hair-curve grass: GN noise on curve points weighted by curve parameter.

## 8. LOD & budgets

- Typical game ranges (rules of thumb — confirm against the project's engine and platform in `poly-budgets-and-targets.md`): hero tree LOD0 ~5–20k tris including cards; each LOD roughly halves (LOD naming and ratio rules: `game-engine-delivery.md` §4); last LOD = impostor/billboard; grass cluster cards tens of tris each. Unreal 5.7's Nanite Foliage (experimental) favors geometric foliage over cards — check the target engine version.
- Reduce by removing twigs and small branches first, merging leaf cards into bigger cluster cards, lowering branch radial segments (trunk 8–12, branches 4–6, twigs 3 or cards).
- Overdraw (layered alpha) often costs more than triangles — fewer, tighter cards beat many loose quads.

## 9. Review & common failures

Review: silhouette against a bright sky (crown shape, holes), turntable, backlit render (translucency), close-up at twig/leaf attachments, grove of variants, distance shot for repetition, wind playback for popping/stretching.

- Lollipop tree: sphere of leaves on a stick, no negative space.
- Branch radii ignoring Leonardo's rule; straight cylinders; no taper or root flare.
- Leaves floating, all facing the same way, identical color; no underside difference.
- Opaque, dark foliage with no translucency in backlight.
- Identical clones in a scatter; pivots not at the base → trees float or sink on slopes.
- Alpha cards as unmasked quads (overdraw, visible rectangles in shadows).
- Wind moving the trunk as much as the leaves.
