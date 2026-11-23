# Review & Comparison

Run this at the end of every stage (blockout, primary forms, detail, materials) and whenever the user says something "looks wrong". The point is to turn a vague feeling into a named, measurable discrepancy before touching geometry. This is the visual half; run the deterministic gates first and respect the correction-loop limits (`quality-gates.md` §3–4).

## Contents
1. Capture evidence, not one flattering frame
2. Compare by layer, in this order
3. Name discrepancies precisely, then pick one action
4. Report honestly
5. Common ways a model "looks fake" and where to look

## 1. Capture evidence, not one flattering frame

- **Turntable**: screenshot/render at 0° (front), 90°, 180°, 270°, plus **top** and one **three-quarter**. Defects that survive a front-only review: a hole through the back of a skull, an accessory at the wrong height, a floating part — all invisible from the front.
- **Cross-section / plan view**: a model can match the silhouette perfectly and still be a "2.5D slab" — constant thickness, no grind on a blade, no palm swell on a grip, no taper on a fuselage. Look at it end-on and from above; a rectangle with no interior modelling is the tell. Bisect or use a clipping plane (`Alt+B` region clip, or a Boolean with a thin box) to see the actual cross-section against the reference's.
- **Camera match**: for each key reference photo, set a camera at the same angle and approximate focal length (`camera.data.lens`, 35–50 mm typical for photos; ortho for blueprints), frame the object to the same extent, and screenshot. Side-by-side comparison only means something at matched framing — otherwise you are comparing perspective, not shape.
- **Shading modes**: solid + wireframe (topology/density), MatCap or a zebra-stripe HDRI (surface continuity, pinching), rendered with the target lighting (bevel widths, material read). Flat-lit viewports hide form errors; overly dramatic lighting hides them differently.
- Save the screenshots next to the references (`references/review/<stage>_<view>.png`) so the next pass can diff against them.
- **No screenshot tool, or headless?** `scripts/viewport_capture.py` captures the turntable/top/persp views framed on the target in any mode: OpenGL viewport render in a UI session, Workbench render headless, with a framing check. Bridges, black-screenshot and headless-shading pitfalls: `blender-bridges.md` §7.

## 2. Compare by layer, in this order

Judge each layer separately and don't let a good average hide one failed layer that matters.

1. **Silhouette & proportion** — outer contour, mass distribution, negative space, taper. Check the **sensitivity list** from NOTES.md first: the 3–5 ratios that make it *this* object.
2. **Component structure** — every part present, at the right place, attached the right way (butt / overlap / socket / embed), repeats at the right count and spacing, nothing floating or clipping.
3. **Form detail** — bevels/chamfers, curvature, cross-section thickness, creases, dents, holes, panel gaps. This is where "toy-like" comes from: perfectly sharp or perfectly uniform edges, slab cross-sections, over-even spacing of details.
4. **Surface** — albedo zones, roughness variation, metal vs dielectric, relief; edge wear on crests, dirt in cavities (if the target includes texturing).
5. **Lighting/camera** — only after the above: is a mismatch actually exposure, angle or focal length? Fix the camera before judging the model.
6. **Budget** — is missing detail a deliberate LOD/tri-budget trade? Say so.

Left/right pairs are **mirrors**, not rotations: an ear, hand, or bracket duplicated by rotating 180° about the vertical axis is wrong even though it "looks symmetric" from the front. Check from above. A pair that's wrong the same way on both sides still looks symmetric — compare against the reference, not against the other side.

## 3. Name discrepancies precisely, then pick one action

Write each finding as: *what* (part), *how* (measurable direction and amount), *why it matters* (which layer/identity feature), *cause* (reference misread, wrong technique, wrong proportion, unfinished stage, camera). Example: "Muzzle protrudes 0.28 HH; reference shows ~0.17 HH — reads as a dog snout instead of the flat frog-wide mouth; cause: sculpted from a human-head habit, not the plan view."

Then choose exactly one:
- **continue** — the stage goal is met from all captured views and no layer that matters is failing.
- **refine plan** — a part is missing/invented, proportions or the surface class are wrong → go back to NOTES.md/references, gather more component references, correct the plan, then rebuild the part.
- **refine geometry** — the plan is right but the mesh doesn't match it → fix the mesh.
- **request input** — the reference hides what's needed (back, interior, exact text/logo, material) → ask for views instead of guessing.
- **stop** — target fidelity reached or the user accepts the approximation.

Fix the biggest silhouette/proportion issue first; detail work on wrong proportions is wasted.

## 4. Report honestly

After each pass tell the user, with numbers:
- **What changed** — "receiver lengthened from 0.30 L to 0.34 L; rail slot count 18 → 22; bevel on stock 3 mm → 1.5 mm".
- **What still doesn't match** — "grip is still a flat extrusion (no palm swell); knurling is procedural, not the reference's dot-grid".
- **What can't be verified** from the references — "rear face inferred from side view".
- Use "improved", not "done", until it is done. Gate numbers are reported per `quality-gates.md` §5; a matching front view is no more proof that the model reads in 3D than a passing gate.

Rough fidelity scale for expectation-setting: 0.2 primitives only · 0.4 silhouette recognizable, structure incomplete · 0.6 macro/meso right, detail weak · 0.75 reads correctly, details approximate · 0.85 production-quality match · 0.95 near-reference (usually needs multiple views or hand-sculpted detail). Don't claim 0.9+ from a single ambiguous image unless the object is simple and symmetric.

## 5. Common ways a model "looks fake" and where to look

| Symptom | Usual cause | Check |
|---|---|---|
| Looks right from the front, like cardboard when rotated | slab cross-section, no taper/grind/swell | top & end-on views, bisect |
| Toy-like | every edge equally sharp or equally rounded; bevels too large; no panel gaps | render with reflections; compare bevel widths to real object |
| Generic member of its class, not *this* one | identity features skipped or eyeballed | sensitivity list vs measured ratios |
| Parts feel glued on | abutting instead of overlapping/embedding; missing fasteners or fillets at joins | structure layer; add overlap, fillet, or hardware |
| Too clean / too regular | details evenly spaced, no asymmetry, no wear | randomize slightly within reference bounds |
| Dead face/character | perfect symmetry, eyes too shallow, no catchlight geometry considered | asymmetry pass; socket depth; eye/lid overlap |
| Lumpy or pinched smooth surfaces | poles/tris on curved regions, uneven loop spacing | MatCap/zebra view; `mesh_report.py` curved-nonquads |
