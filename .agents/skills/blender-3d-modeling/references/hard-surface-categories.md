# Hard-Surface Categories (vehicles, interiors, weapons, furniture, architecture, machines)

Read this after the shared workflow in `hard-surface-modeling.md` when the object belongs to one of these categories: it holds the per-category construction order, starting dimensions and the measured interior material recipes. Dimensions are starting points; take the rest from the reference (`references/NOTES.md`).

## Contents
1. Vehicles (exterior)
2. Vehicle interiors
3. Weapons
4. Furniture (archviz)
5. Architecture
6. Machines and tools
7. Common failures

## 1. Vehicles (exterior)

- Body panels as separate objects with real panel gaps; car body from a subdivided cage traced over blueprints (side profile first, then front/rear sections, then loft between); wheels from a 32–64 side cylinder + array of spokes; tires with Screw/Array tread; interior blocked separately (§2; car paint flakes: `procedural-materials.md` §3; colour flop and tinted coat: `procedural-materials.md` §4). Racing-game hero cars can reach 80–150k tris.
- Panel-gap slabs and body-edge bevel widths: `hard-surface-modeling.md` §3 and §6. Tread, belt and chain constructions: `modifiers-and-curves.md`.

## 2. Vehicle interiors

Block the cabin against the exterior first (the same hip point, windshield base and door line). Then build parts in the order the camera sees them: instrument panel (IP) and cluster, steering wheel, seats, door cards, console.

### 2.1 Dimensions

Starting points; take the rest from the reference:

| Part | Value |
|---|---|
| Steering wheel | Ø 350–395 mm (sedan/SUV), rim grip 30–40 mm thick (oval, not round), dish 50–90 mm hub → rim plane |
| Interior split lines | nominal 3 ± 1 mm; premium flush fits < 0.5 mm; IP ↔ door card ≈ 5 mm |
| Stitch pitch | 3–4 mm, seam 5–8 mm from the panel edge (`modifiers-and-curves.md` §3 Stitches) |
| Molded-skin grain | secondary grain depth 0–80 µm, cells ≈ 0.3–1 mm (visible only in grazing light) |
| Seat cushion above floor | ≈ 250–350 mm cars, 350–450 mm SUVs/trucks; quilt diamonds 40–80 mm; perforation Ø ≈ 1 mm at 4–6 mm pitch `[unverified]` |

### 2.2 Construction per part

| Part | Method |
|---|---|
| IP main body, door cards, console sides | subd cage traced from sections, large radii (5–20 mm). Split lines are real gaps. Turn the skin **into** the gap with a 3–5 mm return flange so no void shows through |
| Vents, bezels, buttons, knobs, trim strips | booleans + Bevel (hard plastic or chrome parts, small radii); buttons are separate objects with a 0.3–0.5 mm gap |
| Instrument cluster | binnacle hood = subd. Dial face = flat plane with image/decal numerals, needles as separate objects, gauge lens = a thin curved shell (see §2.3). A digital cluster is a screen plane + lens |
| Steering wheel | rim = circle curve with an oval Bevel profile (or a subd torus), spokes/hub = subd, airbag cover as a separate part with its own split line. For the leather wrap, run the seam along the inner rim with stitches (`modifiers-and-curves.md` §3 Stitches) and add slight bulges at the seam |
| Seats | subd cages per cushion/bolster (or cloth sim/sculpt for creases, §4). Quilting: hero = diamond mask (two Wave Bands at ±45°, Math Minimum → Map Range) → Displace modifier on a dense subd mesh, 3–5 mm grooves + stitch curves in them. Mid-distance = the same mask → Bump `[unverified]` |
| Perforation | texture, never geometry (thousands of holes): dot mask (Brick/Voronoi) → darker base + Roughness → 1 + small negative bump; only on inserts, not bolsters. Extreme close-up: GN-instanced dark discs `[unverified]` |

### 2.3 Interior materials

- **Grained soft-touch plastic** (tested 5.2): base ≈ 0.035 linear, Roughness 0.55, Object coords → Voronoi **Smooth F1** Distance (Scale 1500/m ≈ 0.7 mm cells) + 0.25 × Noise (Scale 4000) → Bump Strength 1, **Distance 0.0001** (≈ 100 µm relief). Measured on a 50 mm plate (camera top-down, 0.19 mm/px, Cycles 48 spp) as relative high-pass contrast (luminance − 5×5 box blur, std/mean): sun at 10° elevation flat **0.003** vs grained **0.210**; sun at 75° flat 0.0003 vs grained 0.104. Grazing light doubles the grain's visible contrast, so judge grain with a low light. Apply scale first (Object coords follow object scale). For export, bake to a tiling normal map (`baking-maps.md` §2). Keep the cells ≥ 2–3 px at final resolution, or the grain just reads as roughness `[unverified]`.
- **Leather**: grain cells larger than plastic (Voronoi Scale ≈ 300–600/m), Roughness 0.4–0.6, slightly lighter wear on bolsters (Pointiness/curvature mask). **Alcantara/suede**: Sheen Weight 0.8–1, Roughness 0.9 `[unverified]`.
- **Piano black / gloss trim**: base ≈ 0.01, Roughness 0.1, Coat Weight 1, Coat Roughness 0.02. It shows every reflection, so check it in the shot's HDRI `[unverified]`.
- **Emissive displays**: Emission Color = UI image, Strength ≈ 1–5 under Standard/AgX at interior exposure. Add Coat Weight 1, Coat Roughness 0.03 so the screen reflects like its cover glass without an extra object. Add a small area light only when the screen must visibly light the cabin, as the emissive row in `procedural-materials.md` §1 says `[unverified]`.
- **Gauge lens**: a thin shell with Transmission 1, Roughness 0–0.02, **Thin Wall** on (5.2+, so refraction doesn't warp the needles). Before 5.2, use a ≈ 1 mm Solidify shell at IOR 1.45. A smoked lens gets a grey base color `[unverified]`.

## 3. Weapons

- Strict blueprint accuracy — gamers notice; keep parts modular (receiver, barrel, stock, mag, optic) for animation; bevel weights everywhere (rifle receiver ~1–2 mm, `hard-surface-modeling.md` §3); first-person weapons need dense geometry near the camera (rear sight, receiver) and can be sparse far away.

## 4. Furniture (archviz)

- Exact real dimensions (seat height 430–460 mm, table 750 mm, door 2040×826 mm…); soft parts (cushions) via cloth sim or sculpt + Subdivision; wood via bevels + textures; often 10–50k faces per piece is fine.

## 5. Architecture

- Model to real dimensions from plans; walls as Solidified planes or extruded floor plans; window/door as reusable collection instances; stairs via Array; keep interior/exterior faces separate; watch **coplanar faces** where walls meet floors (z-fighting); façade repetition via Array + Instances; boolean openings before Bevel.

## 6. Machines and tools

- Think in manufacturing terms — cast parts have large fillets, machined parts small chamfers, stamped sheet metal has uniform thickness and rounded folds; this alone makes a model read as real.

## 7. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Car body reads as one moulded shell | Panels fused, no panel gaps | Separate panel objects with real gaps (§1); gap slabs per `hard-surface-modeling.md` §6 |
| Void or exterior visible through an interior split line | Skin ends at the gap without a return | 3–5 mm return flange into the gap (§2.2) |
| Soft-touch grain invisible, or judged under a high light | Grain contrast falls from 0.210 at 10° sun to 0.104 at 75° | Light and judge grain at grazing angles; cells ≥ 2–3 px at final resolution (§2.3) |
| Grain cell size changes when a part is resized | Object coords follow object scale | Apply scale before tuning Voronoi scale (§2.3) |
| Perforated inserts modelled as thousands of holes | Geometry where a texture was enough | Dot mask → base/roughness/bump; GN discs only in extreme close-up (§2.2) |
| Needles warp behind the gauge lens | Refractive shell without Thin Wall | Thin Wall on (5.2+) or ≈ 1 mm Solidify shell at IOR 1.45 (§2.3) |
| Weapon looks "off" to players or can't animate | Blueprint deviations; parts fused | Blueprint accuracy; modular receiver/barrel/stock/mag/optic (§3) |
| Archviz chair or table at the wrong height | Dimensions guessed | Seat 430–460 mm, table 750 mm, door 2040×826 mm (§4) |
| Flickering where walls meet floors | Coplanar faces | Separate interior/exterior faces; no shared coplanar faces (§5) |
| Sharp, unbeveled window and door openings | Boolean cut after Bevel | Boolean openings before Bevel (§5) |
| Machine reads as a generic block | Fillet vocabulary ignored | Cast = large fillets, machined = small chamfers, stamped sheet = uniform thickness, rounded folds (§6) |
