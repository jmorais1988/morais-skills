# Fauna (mammals, birds, reptiles, fish, insects, creatures)

Animals are characters with non-human skeletons and coverings. The dominant failures are **skeletal** (joints in the wrong place, human/dog defaults on the wrong species) and **coverage** (fur/feathers/scales that are uniform, directionless, or detached from the body). Build from the skeleton outward and treat the covering as its own modeled system. Profile: `project_state.py init --profile fauna`. Also required: `organic-modeling.md` (anatomy measurement), `sculpting.md`, `character-modeling.md` §1–2 (layer classification), `rigging-and-weights.md` §1 and §3 (weights, pose sweep), `topology.md`.

## Contents
1. Classify
2. Reference study specifics
3. Skeleton-first blockout
4. Sculpt & topology notes by body plan
5. Fur
6. Feathers
7. Scales, scutes & skin relief
8. Arthropods, fish, birds, amphibians
9. Rigging & motion checks
10. Materials
11. Review & common failures

## 1. Classify

| Axis | Values → consequence |
|---|---|
| Body plan | quadruped mammal · biped/bird · reptile (sprawling or erect) · fish · arthropod (exoskeleton) · cephalopod/soft · fictional hybrid (decompose into real donors) |
| Foot posture | **plantigrade** (whole foot: bears, humans, rodents) · **digitigrade** (toes: dogs, cats, birds) · **unguligrade** (hoof tips: horses, deer). In digitigrade/unguligrade hind legs, the visible "backward knee" is the **ankle (hock)**; the real knee is high, near the belly |
| Covering | skin · short fur · long fur/mane · feathers · scales/scutes · exoskeleton plates · slime/wet |
| Deformation | rigged & animated (game/film) vs static pose (print, still render) — static still needs believable weight distribution |
| Style | realistic / stylized (exaggeration ratios written in NOTES.md) |

A fictional creature is decomposed into real donors ("lion body, eagle wings, horse ears") and each part follows the donor's anatomy and attachment — wings need a shoulder/pectoral structure that could power them.

## 2. Reference study specifics

Beyond `reference-gathering.md`:
- **Skeleton references** (museum mounts, veterinary diagrams) in side, front, top views for the species or closest relative — `references/01_skeleton/`. Measure joint positions from the skeleton, not from the furry outline.
- Proportions in **head-lengths or body-lengths** (nose tip → tail root): leg segment ratios (humerus/radius/metacarpal; femur/tibia/metatarsal), withers height vs body length, neck length, tail length.
- **Covering maps**: fur/feather/scale **direction** (draw arrows on a side and top reference), length by region (short on face/legs, long on mane/tail/belly), markings pattern, scale size gradient.
- **Motion references**: gait video frames (walk, trot, gallop; flight; swimming) — joint ranges tell you where loops and pivots go.
- Variation: sex, age, season (winter coat), subspecies.
- **Sensitivity list** (check first every review): muzzle length:skull length, eye position & forward/lateral angle (predator forward, prey lateral), ear size/position, leg length:body depth, neck length, hock height.

## 3. Skeleton-first blockout

1. Place the **armature (or an edge skeleton)** first at the measured joint positions over the side/top skeleton references. Quadrupeds: the scapula floats on the ribcage (most have no clavicle) — shoulder joint is lower and more forward than human intuition; the pelvis is tilted; the spine arches.
2. Block masses around bones: skull, ribcage (deep and narrow in dogs/horses, barrel-shaped in bears), pelvis, limb muscle masses as tapered volumes offset from the bone; neck muscles; tail as spine continuation tapering to tip.
3. Skin modifier on the edge skeleton gives a fast connected blob → voxel remesh → sculpt.
4. Check side, front, **top** views against references before sculpting: top-view width of ribcage vs pelvis and muzzle shape catch most species errors.

## 4. Sculpt & topology notes by body plan

- **Quadruped mammals**: loops encircling shoulder (large area — scapula slides), elbow, carpus, hip, stifle (knee), hock; concentric loops around eyes, mouth (jaw opens wide — extra loops at the lip corners), nostrils; belly/flank loops for breathing; separate eyes, teeth, tongue, claws/hooves, horns/antlers (antlers: curves with taper → mesh, or sculpt; horns: continuous-sculpt with ring ridges).
- **Birds**: long S-curved neck (many vertebrae) hidden under feathers — the silhouette is the feather envelope, the rig is the neck; beak is keratin hard-surface with a crisp cutting edge; eyes nearly fill the skull; legs are scaly digitigrade with a reversed-looking ankle.
- **Reptiles**: sprawling limbs attach laterally; loops for belly-to-side skin stretching; scale detail per §7.
- **Fish**: lofted cross-sections (fusiform, compressed, or depressed), fins as thin membranes (Solidify, thinner toward edges) with ray geometry or alpha; gill slits/operculum as overlapping plates.
- **Snakes/eels/tentacles**: curve-driven (Curve modifier on a tube mesh, or GN Curve to Mesh with radius) — keeps body length constant while posing.

## 5. Fur

Blender **hair curves** (Curves objects attached to a surface mesh; Add → Curve → Empty Hair / Fur):
1. **Guides**: a few hundred curves groomed region by region following the direction map, in **Sculpt Curves** mode (Add Curves, Density, Comb, Snake Hook, Grow/Shrink, Pinch, Puff, Smooth, Slide, Delete, Selection Paint).
2. **Procedural node-group assets** (3.5+, Add Modifier → Hair): Generate Hair Curves / **Interpolate Hair Curves** (children from guides), **Clump Hair Curves**, **Curl Hair Curves**, **Frizz Hair Curves**, **Hair Curves Noise**, **Trim Hair Curves**, Smooth/Straighten/Roll/Rotate Hair Curves, Braid Hair Curves, Set Hair Curve Profile, Attach Hair Curves to Surface (after surface edits/rig deformation), Redistribute Curve Points. Stack order: Interpolate → Clump → Curl → Frizz/Noise → Trim.
3. **Region control** with painted vertex groups/attributes on the body: density (sparser on belly/inner legs), length (face short, mane/tail long), clump amount, frizz. Uniform length everywhere is the main fur tell.
4. **Shading**: Principled Hair BSDF (Cycles; **Chiang** or **Huang** model — Huang, 4.0+, supports elliptical cross-sections and is less noisy); melanin + redness for natural coats, a tint for dyed/fantasy; random melanin per strand; root-to-tip color change via Curve Info intercept. EEVEE doesn't support Principled Hair — plan a Principled-based fallback with anisotropy-like highlights and root darkening.
5. **Skin under fur** colored like the fur root so partings don't read as bald spots; check exposure with a scalp-exposure-style test (`scripts/scalp_exposure.py` logic applies to body regions).
6. Performance: viewport display percentage, children only at render, simplify child count.
7. **Games**: shells (stacked transparent layers along the normal; good from above) + fins (silhouette strips) or hair **cards** baked from the groom (base color + alpha + normal + root/ID/depth maps); short fur often only a normal map + sheen/rim.

## 6. Feathers

- Types: **flight feathers** (primaries on the hand, secondaries on the forearm, tertials; rectrices on the tail) — asymmetric vanes, stiff; **coverts** in overlapping rows over the flight feathers; **contour feathers** covering the body like shingles; **down** (fluffy, mostly hidden).
- Build flight feathers as meshes/cards: rachis (tapered curve) + vane (card with alpha, slight curvature and twist). Place them **by tract** along the wing bones in overlapping rows, each row rotated so tips fan out as the wing extends.
- Body contour feathers: GN instancing of 3–5 feather variants on points distributed over the body (or at groom guide roots), rotated to the stored direction attribute (flow map / hair guides), scaled by region, lifted slightly off the surface and overlapping tail-ward. Community GN tools convert grooms to feathers — check availability rather than assume.
- Rig: wing fold must drive feather rotation (constraints or GN driven by bone angle); check folded and spread poses for intersections.
- Materials: anisotropic sheen along the rachis direction; iridescence via Principled **Thin Film** (4.2+) or a layer-weight hue shift; translucent vane edges when backlit.

## 7. Scales, scutes & skin relief

| Scale size relative to view | Representation |
|---|---|
| Tiny, uniform (lizard skin at distance, fish scale texture) | normal/displacement map (Voronoi-based procedural or sculpt alpha), baked from sculpt for games |
| Medium, readable in silhouette close-up | sculpted/displaced on multires, or displacement with adaptive subdivision (Cycles) |
| Large, distinct (crocodile osteoderms, pangolin, armadillo bands, snake belly scutes, fish scales on a hero fish, dragon plates) | **instanced geometry**: GN Distribute (Poisson) or points along UV/flow grid → Instance on Points aligned to a stored **flow direction** (tail-ward) and surface normal, tilted out 5–20° to overlap like shingles, scale by a painted size gradient; belly scutes as Array + Curve along the spine curve |

- Scale size always follows a gradient (smaller at joints, face, and limb ends; larger on the back) and changes shape by region; one uniform tile over the whole body reads as texture wallpaper.
- Skin folds and wrinkles align with joint bending directions (from motion references), not random noise.

## 8. Arthropods, fish, birds, amphibians

- **Insects/arachnids/crustaceans**: exoskeleton is **hard surface** — model segments (head, thorax, abdomen segments; leg segments coxa → trochanter → femur → tibia → tarsus) as separate assembled-solid objects with overlapping plates and socket joints (`assembly-and-hierarchy.md`); count legs, segments and antennae segments from references (6 legs insects, 8 arachnids). Wings: thin planes with vein geometry or alpha + normal; iridescence via Thin Film; hairs/setae as hair curves.
- **Fish**: swim deformation via a spine rig or Curve modifier on an animated path; wet look (low roughness, clearcoat); scales per §7; eyes flush with the head, no eyelids.
- **Amphibians**: moist skin — low roughness with variation, subsurface, glands/warts via displacement; toe pads.
- **Birds**: see §4 and §6; feet scutes per §7.

## 9. Rigging & motion checks

- **Rigify** sample metarigs in the current manual: Basic Human, Basic Quadruped, Human, Cat, Wolf, Horse, Shark (older builds also had a Bird — check Add → Armature in the installed version). Build others from Rigify sub-rig samples (limbs, paws, tails, fingers for wing digits) on a custom metarig.
- Align bones to the measured skeleton, not the mesh surface; fit the metarig in side and top views.
- Pose sweep (on by default in `scripts/rig_check.py`; `--no-sweep` skips it) with species-relevant poses: quadruped sit, lie down, stretch, head turn 90°, jaw fully open, tail curl, full stride extension; bird wing fold/spread; fish full-body C-bend.
- Fur/feathers must follow deformation (Attach Hair Curves to Surface / Surface Deform) — re-check coverage in the extreme poses.

## 10. Materials

- Skin under coverings visible at partings, eyelids, nose, paw pads, inner ears (thin → SSS glow when backlit).
- **Eyes**: species-specific pupil shape (round, vertical slit, horizontal bar in goats); wet cornea (`materials-and-lookdev.md` §8); nictitating membrane for birds/reptiles if visible.
- Nose/lips wet: low roughness with a thin coat; claws/hooves/beaks/horns: keratin — slight SSS, roughness 0.3–0.6, darker at base or tip per reference, growth-line bump.
- Markings follow the covering's flow and body landmarks (stripes wrap around the body along muscle groups); paint them in UV or as attributes, not as random procedural patterns, when the reference shows a specific pattern.

## 11. Review & common failures

Review: skeleton reference overlaid on side/top renders (joints inside the model at the right places), turntable, top view, pose sweep extremes, close-ups of covering direction and attachment, backlit render for ears/membranes, ground contact of feet in a standing pose.

- Default dog/human anatomy on every species (snout on a cat, forward eyes on a horse, human knee on a hind leg).
- Legs attached too low/far out; scapula fixed like a human shoulder; no ribcage depth.
- Fur uniform in length and direction; bald partings; hair through the ground or clothing.
- Feathers intersecting when the wing folds; a wing with no shoulder musculature.
- Scales as one repeating texture tile; no size gradient; no overlap direction.
- Insect with the wrong leg or segment count; exoskeleton sculpted as soft skin.
- Static "T-pose" presentation for a still render — animals rest in weight-bearing, asymmetric poses.
