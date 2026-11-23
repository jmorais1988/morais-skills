# Reference Gathering

Good models are copied from reality (or from a deliberate design), not improvised. This file covers what to search for, how to store it, how to generate what you can't find, and — most importantly — how to extract usable facts from images before modeling.

## Contents
1. When to do this
2. Validate the reference before relying on it
3. What to search for
4. Search tips
5. Folder organization
6. Generating references
7. Extract facts before modeling (mandatory)
8. Setting up in Blender
9. Compare pass

## 1. When to do this

- **New model**: always, before the blockout.
- **Refinement pass**: for whichever component is being refined, gather component-specific references (close-ups, cutaways, alternative angles) and re-check proportions.
- **Issue-fixing pass**: when the user says "the X looks off" — gather references of X specifically from the same angle as the problem view, then compare screenshots side by side.

## 2. Validate the reference before relying on it

Not every image is a usable 3D reference. Judge it before building on it:

- **Good**: one clear subject, fills a good part of the frame, at least one strong silhouette view, major materials visible, hidden sides reasonably inferable (symmetry, known object type).
- **Conditional**: single view but the object is rotationally/bilaterally symmetric; partial occlusion but macro shape clear; fine detail must be approximated; stylized target accepted; exact text/logo fidelity not required. Proceed, but write the assumptions down.
- **Weak / ask for more**: subject ambiguous or cropped; a whole scene rather than an object; key shape blurred, transparent, or hidden; the request needs manufacturing-grade dimensions from a photo; wide-angle distortion. Ask for front/side/back views, a neutral background, higher resolution, close-ups of materials/details, and the intended style (realistic, stylized, low-poly, game prop, hero render).
- **Catalogued items** (a product SKU, a game skin, a model number): the name in the image is not the identity — confirm the exact name and pull official/spec references first; they reveal base features no single photo shows.

A single image never shows the back, the interior, or true depth. Say so, report which parts are inferred, and request another view when it matters rather than faking confidence.

## 3. What to search for

### The whole subject
- Front, side, top/back and three-quarter views. Orthographic "blueprints" or "turnaround sheets" if they exist (vehicles, weapons, aircraft, furniture, characters).
- Real photographs, not only renders/illustrations — renders inherit other artists' mistakes.
- Scale context: the object next to a person, a hand, a ruler. Note real dimensions (spec sheets, Wikipedia, manufacturer pages).
- Several variants/brands of the same object to learn what is *essential* vs incidental.

### Each major component
Break the subject into parts and search each one, e.g.
- Rifle: receiver, barrel & muzzle, stock, grip, magazine, trigger group, sights/optic, rail, sling mounts, screws/pins.
- Human/creature: skull & face planes, ear, eye & eyelid, nose, lips, hand, foot, torso musculature, joint anatomy (knee/elbow/shoulder), skin folds, hair/fur growth direction.
- Car: body panels & panel gaps, wheel/tire/rim, headlight assembly, grille, mirror, door handle, interior, undercarriage.
- Building: façade, window frame, door, roof edge/gutter, brick/stone pattern, stairs, railing.

Component references catch the details generic "whole object" images hide: fillet radii, how parts overlap, fastener placement, thickness of thin parts.

### Material & style references
- Close-up of the surface (brushed steel, cast iron, worn leather, painted wood) — needed for bevel width, edge wear, and texturing later.
- If stylized: 3–5 images of the target style so exaggeration is consistent (e.g. "chunky Overwatch-like proportions").

## 4. Search tips
- `web_search` / `image_search` queries: `"<subject> orthographic"`, `"<subject> blueprint"`, `"<subject> side view"`, `"<subject> reference sheet"`, `"<component> close up"`, `"<subject> dimensions mm"`.
- Wikipedia/Wikimedia Commons, manufacturer sites, museum collections, the-blueprints.com, anatomy sites, and sketchfab (for seeing how others resolved the topology) are consistently useful.
- Prefer high-resolution, neutral-lighting, undistorted images. Wide-angle photos lie about proportions; orthographic or long-lens shots don't.
- Respect licensing: references are for private study — don't copy an artist's design or reproduce a trademarked/copyrighted character; derive your own model from photographs of real things or from the user's own concept art.

## 5. Folder organization

Create a `references/` folder beside the `.blend` (or in `/mnt/user-data/outputs/<asset>/references/` when working in the sandbox):

```
references/
├── manifest.json          # url, file, component, view, source, license note, generated?
├── NOTES.md               # extracted facts (see below) — the thing you actually model from
├── 00_overall/
│   ├── overall_front_01.jpg
│   ├── overall_side_01.jpg
│   └── overall_3q_01.jpg
├── 01_receiver/
├── 02_barrel/
├── 03_stock/
├── 90_materials/
└── 99_style/
```

Naming: `<component>_<view>_<nn>.<ext>` with views `front|side|top|back|3q|closeup|cutaway|ortho`. Numbered prefixes keep the order meaningful in file browsers.

Use `scripts/gather_references.py`:
```bash
python scripts/gather_references.py --out ./references --manifest urls.json
# urls.json: [{"url": "...", "component": "01_receiver", "view": "side", "source": "wikimedia"}, ...]
```
It downloads, skips duplicates (hash), converts to jpg/png, writes `manifest.json` and a `NOTES.md` template with a section per component.

Then measure the key views instead of guessing:
```bash
python scripts/measure_reference.py references/00_overall/00_overall_front_01.jpg --grid 25 --regions regions.json
# → foreground bbox in px, height/width ratio, a labelled-grid overlay PNG to read landmark coordinates off,
#   and median RGB/hex per named region (regions.json: {"receiver": [x0,y0,x1,y1], ...})
```
Convert pixel readings to ratios of one reference dimension (total height, head height, overall length) so they survive any scale change.

## 6. Generating references

**Web references are insufficient when any of these hold** for a part that matters (check against the sensitivity list and detail inventory, per component, after validation):
- no usable view for a sensitivity feature (e.g. no side view of the muzzle, no top view of the roof) or for a hidden side the model must show;
- only renders, illustrations or game screenshots — no photographs or blueprints of a real object;
- images below ~800 px on the subject, heavily compressed, or wide-angle distorted;
- only a different variant/model year/species than the one requested;
- the subject is fictional, a hybrid, or a stylized brief with no style references;
- component close-ups are missing (fastener layout, material surface, how parts join).

Then, if an image-generation tool is present (image MCP tools such as `generate_image`/`text_to_image`, ComfyUI MCPs, CLI image generators, or any other generator in the session — check once and note what exists; respect billing/consent rules):
- Generate **orthographic** views: "front orthographic view of X, plain grey background, neutral lighting, no perspective, full object in frame". Then side, top, back. A single turnaround sheet ("front, side, back views side by side, same scale") keeps views more consistent than separate prompts; crop it into views.
- Generate **component close-ups** with the same prompt stem and seed so parts are consistent.
- **Image editing from a real photo** (image-to-image / edit): the best way to get a missing angle or variant of a real object — pass the best photo and ask for the other view; still design intent, not measurement.
- Generate a **material sheet** if needed (texture albedos for the model itself follow `texture-sources-and-pbr-sets.md` §3).
- Turn watermarks off; generate 2–4 candidates and keep the most consistent; record generator, model, prompt, seed and date in the manifest.
- Store them in the same folders, set `"generated": true` in the manifest, and treat them as *design intent*, not ground truth — cross-check proportions across generated views since they often disagree with each other, and prefer real photos wherever both exist.
- If no image generation is available, you can still create a **reference by proxy**: photographs of the closest real object plus a written list of deliberate deviations.

## 7. Extract facts before modeling (mandatory)

Looking at images while modeling is not the same as knowing the object. Work through these layers in order, writing observations (what is there) separately from inferences (what you conclude), in 3D object-space terms (front/back/lateral/proximal — never "left of the photo"), using concrete modeling vocabulary rather than adjectives ("2 mm chamfer, 2 segments" not "nice edges"). Use `scripts/measure_reference.py` to get pixel measurements and sampled colors instead of eyeballing.

1. **Identify & classify** — what it is (specific noun), category, organic / hard surface / hybrid, realistic vs stylized, confidence.
2. **Overall form & silhouette** — bounding volume as a few primitives; bilateral / radial / no symmetry; proportions as ratios to one named reference dimension (total length, head height…). Measure from the image, don't estimate.
3. **Macro → meso → micro** — major assemblies → sub-assemblies → surface feature groups. Never treat the object as one blob and never skip the meso level.
4. **How parts connect** — for every part: attached-to / inside / flush-with / embedded-in, and the contact type — the vocabulary and the attachment contract live in `assembly-and-hierarchy.md` §3 (embedded, socket, overlap, hinge, surface-contact, glued). Parts that only "sit near" each other float or clip later.
5. **Surface class per part** (decides the technique — see `topology.md` §0): continuous-sculpt (horn, bulge, vessel) · assembled-solid (crate, canister, panel) · conforming-shell (cowling, fitted cloth) · surface-relief (ridges, rivets — geometry only if it changes the silhouette at viewing distance) · fiber-strand (cable, rope, hair clump) · material-only (decal, printed logo).
6. **Materials & finish** — per surface: albedo (lighting removed — don't read highlights/shadows as color), metal vs dielectric, roughness, relief type (brushed, cast, pitted, grain), translucency; finish (matte / satin / gloss / anodized). Sample colors as region medians, not by eye.
7. **Detail inventory** — scan the image zone by zone (3×3 grid, or per planned component) and list every identity-defining small mark: bevels, fasteners (count, spacing, head shape), seams, panel lines, grooves/ridges, stitches, holes, decals/text, emissive parts, wear (chips, scratches, stains, patina). Minimums by complexity class: 3 simple / 6 moderate / 10 complex / 16 ultra-complex (`quality-gates.md` §1). For each decide: **geometry** (affects silhouette or catches a hard highlight line), **normal/texture** (visible but no silhouette change), or **skip at this LOD**.
8. **Identity-defining features & sensitivity** — which 3–5 measurements, if wrong by 10 %, make it stop reading as *this* object (a muzzle's width-to-depth ratio, a blade's grind, a car's greenhouse-to-body ratio). These get checked first at every review.
9. **Uncertainty** — what is occluded, hidden, blurry, or foreshortened; what a second view would resolve. Depth is unmeasurable from a front view — flag depth values as inferred.
10. **Deformation** — which parts move, hinge, or bend → separate objects, pivot positions, loop requirements.

Record it in `NOTES.md` (the gatherer writes a template). Facts, ratios, decisions — this list is what you model from; the images double-check it, and it becomes the checklist for the comparison pass.

```
## Overall
- Real dimensions: L 1040 mm, H 220 mm (with mag), W 70 mm. Source: <url>
- Reference unit: L. barrel ≈ 0.45 L; stock ≈ 0.28 L; receiver height ≈ 1.5× barrel Ø
- Silhouette landmarks: ...
- Symmetry: mirror across X except charging handle (right) and ejection port
- Repeats: rail slots pitch 10 mm × 22; vent holes 6 × 2
- Sensitivity (check first): barrel:receiver ratio, stock drop angle, mag curve radius

## 01_receiver  [assembled-solid]
- Shape: extruded box, 3 mm fillets, top rail integral
- Connects: barrel screws into front face (visible ring, butt); stock pin at rear (socket)
- Geometry details: ejection port, mag-well chamfer, 6 rail slots
- Texture-only details: engraving, small screws
- Material: anodized aluminum, sampled #2b2d31, roughness ~0.35 → bevel 1.5 mm, 2 seg
- Inferred: rear face shape (not visible) — mirrored from side view
```

## 8. Setting up in Blender

Run `scripts/setup_reference_images.py` inside Blender with the ortho image paths and the real-world height; it creates image empties aligned to front/side/top/back, sized so 1 unit = 1 m, on their own `REF` collection (hidden from render, displayed only in ortho). Then model with numpad views over the references.

## 9. Compare pass

At the end of each stage, run the review in `references/review-and-comparison.md`: same-angle screenshots against 2–3 key references, the required views and capture rules of `review-and-comparison.md` §1, layer-by-layer comparison, the sensitivity list first, and an explicit log of what changed vs. what still doesn't match in `NOTES.md` under `## Comparison log`.
