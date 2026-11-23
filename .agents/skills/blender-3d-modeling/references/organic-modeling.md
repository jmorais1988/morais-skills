# Organic Modeling (characters, creatures, plants, soft & natural forms)

Organic forms are continuous, curved, and usually deform. The pipeline is: reference & anatomy study → base mesh → sculpt forms (big to small) → retopologize → bake/transfer detail → UV → final. See `sculpting.md` for sculpt-mode specifics and `topology.md` for edge flow.

## Contents
1. Anatomy & proportion study
2. Base mesh strategies
3. Modifier stack for organic work
4. Sculpt → retopo → detail pipeline
5. Specific forms
6. Stylized vs realistic
7. Common failures

## 1. Anatomy & proportion study

Before any geometry, from your references write down:
- Canonical proportions: adult human ≈ 7.5 heads tall (8 for heroic), shoulders ≈ 2 head widths (male), hips ≈ shoulders (female), arm span ≈ height, hand ≈ face length, foot ≈ forearm. Animals: measure in head-lengths or body-lengths from side references; note leg segment ratios and joint positions (a dog's "knee" is high, the visible hock is the ankle).
- Landmarks the silhouette depends on: skull/brow ridge, cheekbones, jaw angle, clavicles, ribcage vs pelvis tilt, greater trochanter, knee, ankle bones; on animals: withers, scapula, croup, hock.
- Where the mass is: fat/muscle distribution changes silhouette more than surface detail.
- Skin/fur/feather direction — it dictates sculpt stroke direction and later grooming.

Model landmarks, not surface noise. A head with correct skull planes and no pores beats a pore-perfect head with a wrong jaw.
### Measure, don't estimate

- Work in **head-units (HU)**: head height = crown to chin at the midline. Realistic adults ≈ 7.5 HU, heroic 8, stylized/anime 5–6, chibi/figurine 2–3. Read the style from the reference; never assume realistic.
- Read landmarks off pixels with `scripts/measure_reference.py` (grid overlay + bbox), then store them **normalized to the head box** (0–1 from crown): hairline ~0.0–0.15, eye line ~0.45–0.55 (higher forehead = stylized/young; a low forehead reads as predator/adult), nose base ~0.6–0.7, mouth ~0.75–0.85, ears bracket eye line→nose base. Also record eye spacing as a fraction of skull width (inner-half placement reads "creature/prey", converging reads "primate/hunter"). Stylized faces violate human ratios on purpose — match what's observed.
- Body: measure **segment lengths** (upper arm, forearm, femur, tibia, torso) rather than posed total height — a crouch or foreshortened limb compresses crown-to-floor and gives a wrong HU count. Skull width (ears excluded) drives the head scaffold; ears, horns, hair extend beyond it.
- Cross-check: head + neck + torso + legs should sum to the total; if not, a reading is wrong.
- **Depth is not measurable from a front view.** Muzzle protrusion, cranium depth, chest depth are inferred until you have a profile. Mark them inferred, model them from the closest real animal/person, and validate by screenshotting the model from the three-quarter camera that matches the reference photo.
- **Sensitivity ranking**: list the 3–5 ratios that destroy the likeness fastest if wrong (e.g. muzzle width:depth, interocular fraction, skull width:height, eye-line height, horn/ear length). Get those within ~5 % before anything else and re-check them at every review. Everything else can be refined later.
- Trained habits bias you toward human/canine defaults (round skull, protruding snout, forward-facing eyes). When the reference is a creature, check the plan (top) view outline explicitly — that's where the "dog snout on a frog" error shows.
- Colors: sample region medians from the reference for skin/fur/marking zones rather than picking by eye.


## 2. Base mesh strategies

Pick one; all are valid:

- **Box/primitive blockout**: separate cubes/cylinders/spheres per body part, scaled to the proportions in your notes, then either join + voxel remesh (fast, sculpt-first) or connect by bridging loops (topology-first).
- **Skin modifier armature**: place vertices along the skeleton (extruded single verts), add Skin + Subdivision → instant blobby base with adjustable radius per vertex (Ctrl+A in edit mode). Excellent for creatures, tentacles, trees.
- **Metaballs** for blobby quick forms → convert to mesh → remesh.
- **Quad-sphere / cylinder based**: for heads and limbs when you want clean topology from the start (subdivided cube for head, 8–16 side cylinder per limb).
- **Human base meshes** (Blender's built-in Human Base Mesh via Extensions, or MB-Lab-style generators) when speed matters and the target is a realistic human; adjust proportions with proportional editing.

Keep the base mesh **low** (2–10k faces) and symmetric (Mirror modifier or symmetry in sculpt). Big changes are cheap here and expensive later.

## 3. Modifier stack for organic work

Typical non-destructive order (top → bottom):
1. **Mirror** (clipping + merge; bisect if needed) — symmetric until the very end.
2. **Multiresolution** or **Subdivision Surface** — Multires if sculpting detail levels; Subdivision (Catmull-Clark) for render smoothing. Don't put both on the same object.
3. **Shrinkwrap** — for retopo meshes onto sculpts, or eyelids onto eyes, clothes onto bodies.
4. **Solidify** — non-simulated clothing/leaves/petals modeled as single-sided surfaces get thickness here; simulated garments put Solidify *after* Cloth (table below).
5. **Displace / Smooth / Corrective Smooth / Laplacian Smooth** — even out sculpt noise, fix deformation.
6. **Lattice / Simple Deform / Curve** — proportion changes across a whole body part (lengthen legs, bend a tail along a curve).
7. **Armature** (or **Surface Deform / Mesh Deform** for shells bound to a deforming body) — Corrective Smooth right after it.
8. **Cloth** — only on simulated garments, **after** Armature and **before** Subdivision and Solidify (`cloth-and-garments.md` §1).

Garments need two different orders — decide which kind each one is:

| Garment kind | Stack (top → bottom) | Why |
|---|---|---|
| **Simulated** (Cloth) | Shrinkwrap fit → **Armature → Cloth** → (Corrective Smooth) → Subdivision → **Solidify last** (before Cloth it multiplies the simulated vertices, `cloth-and-garments.md` §1); body: Armature → Collision | Deform first, then simulate: pins and the posed body collider are in the same space as the cloth. Cloth → Armature simulates in rest space against a *posed* collider and then bends the result. Measured (5.2, tube bent 70° by a 2-bone armature, sleeve 30 mm off the body, pinned ends): Armature → Cloth 0/984 sleeve vertices inside the body; Cloth → Armature 72/984 (7.3 %) inside, gap error up to 66 mm |
| **Non-simulated shell** (tight clothing, armor, straps) | Shrinkwrap (offset) → Solidify → Armature with weights copied from the body (Data Transfer) *or* Surface Deform bound to the body | No simulation, so nothing needs the pose first; keep the fit-then-thicken-then-deform order above (`character-modeling.md` §1, layer L4) |

Cloth settings: `cloth-and-garments.md` §2; pinning and collisions: `cloth-and-garments.md` §3; baking: `simulation.md` §2. Corrective shape keys driven by bone rotation (elbows, shoulders): `shape-keys-and-visemes.md` §2.

Apply `Mirror` only when adding asymmetry; apply `Multires` never (bake from it); keep `Subdivision` live for render.

Useful per-face-set and per-vertex-group control: mask painting → vertex groups → modifier vertex group influence.

## 4. Sculpt → retopo → detail pipeline

The canonical steps live in `sculpting.md` §8 (sculpt → production mesh; voxel sizes per stage in `sculpting.md` §1, stages and brushes in `sculpting.md` §2), `topology.md` §8 (retopology) and `baking-maps.md` §1–2 (bake setup and running the bake). For organic subjects:
1. Blockout at real scale → join → coarse **Voxel Remesh** so the body is one shell; primary forms (proportion, gesture, silhouette), then secondary (muscles, fat, bone landmarks), remeshing finer per stage. Compare to references from matching angles every few minutes.
2. **Retopology** with loops around eyes, mouth and joints (`topology.md` §4), density per target budget.
3. **Tertiary detail** (wrinkles, pores, scales) only after retopo + Multires, or on the high-poly as a bake source.
4. UVs on hidden seams (`uv-unwrapping.md`): 1–3 UDIMs for film, one 2k/4k atlas for games.

## 5. Specific forms

- **Heads**: start from the skull's big planes (front, sides, top, back, under-jaw). Eye sockets deeper than beginners think; eyeballs are separate spheres, eyelids wrap them (Shrinkwrap on eyeball while blocking). Ears sit between brow and nose base, angled ~15° back. Mouth is a cylinder wrapping the teeth arch, not a slit in a flat face.
- **Hands**: box → 5 finger cylinders (8 sides) → join with loops flowing from wrist through each finger; knuckle loops 3 per joint. Fingers curl toward the ring finger; palm is thicker at the thumb base.
- **Bodies**: ribcage (egg) + pelvis (bucket) tilted against each other define the torso; limbs as tapered cylinders with the muscle groups as slight offsets, never perfectly round.
- **Animals**: build from skeleton reference — most posing errors are joint-count/joint-position errors. Paws/hooves as separate blockout parts. Fur handled by hair curves/particles, not geometry, except stylized clumps. Full workflow (foot posture, fur grooming, feathers, scales, arthropods): `fauna.md`.
- **Plants**: leaves as flat planes with a curve for the midrib + Solidify; petals arrayed with a Circular Array (Array + Empty offset) or Geometry Nodes instancing on points; trunks via Skin modifier or curves with bevel; use alpha-textured cards for dense foliage in games. Full workflow (growth rules, phyllotaxis, cards, wind, LODs): `flora.md`.
- **Cloth**: model the garment as a single-sided surface over the body (Shrinkwrap offset), use Cloth sim with pinned collar/waist for folds (Armature before Cloth, §3; pinning and collisions: `cloth-and-garments.md` §3), give thickness with Solidify *after* Cloth, then sculpt Crease/Cloth brush for control. Seams and hems as small bevels/insets; stitch rows as instances along a seam curve (`modifiers-and-curves.md` §3, Stitches).
- **Hair**: the most common single-image failure. From one photo, build 5–15 legible clumps/masses matching the silhouette (fringe, part line, volume), layered front to back — never individual strands. Realistic close-ups: curve-based hair system groomed over those masses; games: hair cards (planes on curves, alpha textured); stylized: sculpted clumps (Snake Hook + Crease). Roots attach to the scalp surface; keep scalp coverage before styling.
- **Eyes**: sphere with a cornea bulge; iris concave; separate tear-line mesh at the lid edge sells realism. Lids must wrap the eyeball with overlap (no gap), and a small catchlight facing the key light does more for "alive" than extra geometry — leave room for it in the material.

## 6. Stylized vs realistic

- Stylized still needs correct **structure**; exaggeration is a ratio change (big head, small hands), not an absence of anatomy. Decide the exaggeration ratios in NOTES.md from style references.
- Stylized surfaces are smoother → fewer polys, cleaner subdivision, larger bevels, fewer tertiary details.
- Realistic → hi-res sculpt + bake; skin detail via displacement/normal maps + multi-layer SSS materials.

## 7. Common failures

- Modeling details before the silhouette reads → hours lost; test at thumbnail size.
- Symmetrical faces all the way to final → dead look; add asymmetry (brow height, mouth corner, ear position) at the end.
- Even sausage limbs → no muscle offset, no joint landmarks.
- Too-shallow eye sockets and cheekbones; too-large eyes on realistic heads.
- Sculpting on a stretched base (Dyntopo triangles) then trying to rig it → always retopo before rigging.
- Forgetting real scale → SSS, cloth sim and hair all break.
