# Character Modeling: Layers, Build Order & Hair

Read this before blocking out any character or creature. It classifies every part into a **layer** that decides how the part is built and how it will ride the armature, fixes the build order (voids before the fusing remesh, discrete parts after retopo), and covers hair representation and scalp coverage (`scripts/scalp_exposure.py`). Armature, weights, rig gates and control rigs continue in `rigging-and-weights.md`.

## Contents
1. Layer ontology
2. The classification test that matters
3. Build order (ontology order ≠ execution order)
4. Hair
5. Structural completeness checklist
6. Common failures

## 1. Layer ontology

Characters fail in predictable ways when every part is treated the same: rigid jewellery stretching at the wrist, cloth clipping through the body, a mouth that's a dark patch instead of a cavity, hair that's a helmet. Classify every part into a **layer** first; the layer tells you how to build it and how it rides the armature.

| Layer | What | Blender build | Rig treatment |
|---|---|---|---|
| **L-1 Proportion scaffold** | head-unit bounds, joint positions | Empties / a measured armature in rest pose; reference empties | constraint, not a part |
| **L0 Core volume** | head, neck, torso, limbs — one continuous mass crossing joints | blockout parts → join → **Voxel Remesh** (or metaballs → convert → remesh) → sculpt → retopo with joint loops | Armature modifier, weights painted/auto-normalized, influences ≤ target cap (4 mobile, 8 PC/console, unlimited film; caps: `rigging-and-weights.md` §1) |
| **L1 Deformable appendages** | tail, wings, long ears, trunk — elongated, bend along their length, cross joints | Skin modifier chain, curve + bevel, or remeshed sculpt fused into L0 | same armature, own bone chain |
| **L-Void Negative space** | mouth cavity, ear concha, nostrils, torn hems, pierced holes | Boolean DIFFERENCE cutters **before** the final remesh, or sculpted in with masks; keep cutters in `CUTTERS` | none |
| **L2 Internal cavities** | eyes, teeth, tongue, gums — visible only because a void exists | separate primitives inside the void; inner mouth as an inverted-normal shell or a sculpted bag | tongue skinned; eyes/teeth single-bone |
| **L3 Single-bone isolates** | horns, claws, hooves, cuffs, rings, buckles, tail spade — entire extent inside one bone's region | primitives / lathe / extrude / booleans | **parent to the bone** (Object → bone parenting) or vertex group weight 1.0 to one bone — never blended |
| **L4 Cross-joint shells** | tunic, loincloth, cape, armor spanning a limb | duplicate faces of L0 → offset (Shrinkwrap with offset + Solidify) → trim; or cloth sim | Armature (copy weights from L0 via Data Transfer, then Corrective Smooth) |
| **L5 Surface markings** | stripes, scars, tattoos, gradients — zero geometric footprint | texture / vertex color / procedural mask in the material | inherits host |
| **L6 VFX / ephemera** | fire, smoke, glow | particles, volumes, emissive meshes | emitter parented to bone |
| **L-Proxy Colliders** | hit boxes | capsules/boxes in `COLLIDERS`, parented to bones | rigid |

Each part gets exactly **one** primary layer (L0–L6) and any number of modifier layers (L-1, L-Void, L5, L-Proxy). Ear = L1 + L-Void (concha). Loincloth = L4 + L-Void (torn hem). Tail ring = L3 parented to the last tail bone — a rigid tip on a bendy chain is two parts, not an ambiguity. Record the primary layer on the object (`obj["layer"]`); the rig gates read it (`rigging-and-weights.md` §2).

## 2. The classification test that matters

Not "hard or soft" — **does it cross a joint?**
- Entirely inside one bone's region (a cuff mid-forearm) → L3, rigid: weight 1.0 on that bone, or bone-parent. It moves rigidly, no stretching.
- A cuff *at the wrist* would pick up forearm+hand blend and squash → still L3: force every vertex to a single bone.
- Cloth 1–2 cm off the skin → L4: its vertices sit inside the same influence envelope as the skin, so copying L0's weights (Data Transfer → Vertex Groups, nearest face interpolated) makes it follow correctly. Secondary sway bones for cloth join the same armature with small envelopes so no skin vertex is affected. Simulated garments put Cloth *after* Armature (`organic-modeling.md` §3; stack and sim setup in `cloth-and-garments.md` §1).
- Don't fix clipping by making rigid parts soft — you trade a clipping bug for a stretching-metal bug.

## 3. Build order (ontology order ≠ execution order)

1. Scaffold: measured proportions (`organic-modeling.md` "Measure, don't estimate"), armature rest pose at joint positions.
2. Block L0, L1, L4 volumes as separate objects.
3. Apply L-Void cutters (booleans) **before** the fusing remesh — a mouth cut after remeshing gives a flat dark patch.
4. Join + Voxel Remesh → sculpt → retopologize (joint loops per `topology.md` §4).
5. Discrete geometry: L2 and L3 parts, placed against the retopo mesh.
6. Rig: armature, weights, L3 overrides, L4 weight transfer, colliders (`rigging-and-weights.md` §1).
7. Appearance: L5 masks, L6 emitters.

Every part must trace to a reference region; a part with no evidence is deleted, not guessed (e.g. a dark mass read as a mane that is really a far limb).

## 4. Hair

Anime face/hair shading (proxy custom normals, face shadows, hair highlights): `anime-face-and-hair.md` §1–3, `scripts/normal_transfer.py`, `scripts/face_sdf.py`. Lay hair UVs with V running root → tip so the angel-ring highlight stays a band (`anime-face-and-hair.md` §3).

Hair has failure modes no other check sees. Decide the representation from the reference and the target:

| Style read | Representation | Blender |
|---|---|---|
| Large graphic masses, tapered tips (anime/stylized) | 10–16 primary tapered ribbon/loft locks + 4–6 bangs + 8–14 secondary locks over a hidden scalp mass | curves with tapered bevel/taper objects, or sculpted clumps (Snake Hook + Crease), Solidify for ribbons |
| Realistic groom | strand curves over a scalp mesh | Empty Hair → curves object with `surface` set to the head; Geometry Nodes hair assets (interpolate, clump, frizz, trim) |
| Game hair | cards on curves with alpha, layered front to back | plane strips + Curve modifier; alpha-tested textures; hard cutout beats soft transparency |
| Fur | dense short strands / shells | hair curves with Hair Density + Length; or shell layers only for stylized |

Rules regardless of route:
- **Roots bind to the scalp surface**, never floating: hair curves use the surface attachment (UV-based), so re-sculpting the head keeps hair attached. Sculpted clumps overlap the scalp mass by a few mm.
- **Stand proud**: roots leave the scalp along the normal by a small offset so locks don't sink below the skull; a lock that's "near" the head but under the surface is a bald patch.
- **Scalp exposure is checked on geometry** (`scripts/scalp_exposure.py --head <obj> --hair <objs> --scalp-group scalp`): sample scalp points (a `scalp` vertex group / face set) and test whether hair geometry exists *outside* the skull above each point within a radius. Exposure over the hard maximum (default 15 %) fails before any render. A coverage shortfall never justifies widening the locks — widened masses slide off the skull and expose more crown.
- Silhouette first, material second: lock topology/masses are locked only after the turntable silhouette review passes; no shader fixes a wrong mass.
- Face constraints: bangs may not cross both eye centers; nose-to-hair clearance stays open in profile; the head must not read hollow between locks.
- Layer front to back: rear mass → middle silhouette locks → bangs. Vary length, direction, twist; identical spikes = porcupine.
- Hair is rigidly parented (to the head bone) or given its own few bones — never smooth-skinned to the body skeleton (the falloff runs through the skull).
- Materials: Principled Hair BSDF for strands; Principled BSDF with anisotropy for stylized ribbons; an AO/cavity darkening between locks sells volume.

## 5. Structural completeness checklist

The modeling items are checked here; the rig items are measured by `scripts/rig_check.py` (`rigging-and-weights.md` §2–3) and stay on this list so one pass covers the whole character.

- [ ] Every part has exactly one primary layer recorded (`obj["layer"]`)
- [ ] Core volume fits the proportion scaffold; skull width (ears excluded) drives head scale
- [ ] All L-Void cuts applied before remesh; no dark-patch mouths/nostrils
- [ ] No degenerate faces along trimmed edges (`mesh_report.py`)
- [ ] Bone names unique, `.L/.R`, deform flags correct; bone scale 1 at rest
- [ ] Weights normalized, influences ≤ target cap (4 mobile, 8 PC/console; `rigging-and-weights.md` §1), no unweighted verts
- [ ] L3 parts rigid (single bone); L4 shells don't clip L0 in the pose sweep
- [ ] L0↔L1 seams: coincident verts or one merged mesh
- [ ] Pose sweep passes; action moves; loop/foot gates as applicable
- [ ] Joint centers inside the mesh volume (≤5 % outside allowed under clothing)
- [ ] Colliders exist for physics/raycast bones
- [ ] Hair: scalp exposure ≤ max, roots bound, silhouette passed from 4 azimuths
- [ ] Every part traces to a reference region; nothing invented

## 6. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Mouth, nostril or concha is a flat dark patch | L-Void cut applied after the fusing remesh | Boolean DIFFERENCE cutters before Voxel Remesh (§3 step 3); keep cutters in `CUTTERS`; L2 parts inside the void |
| Rigid cuff, ring or buckle stretches or squashes at a joint | L3 part blended between two bones (forearm+hand at the wrist) | every vertex weight 1.0 to one bone, or bone-parent (§2); never make it soft |
| Cloth clips through the body and the "fix" softened the metal | clipping bug traded for a stretching-metal bug | L4 shell with L0 weights copied (Data Transfer) + Corrective Smooth; rigid parts stay L3 (§2) |
| Hair reads as a helmet or a porcupine | one undifferentiated mass, or identical spikes | rear mass → silhouette locks → bangs; vary length, direction, twist; 10–16 primary + 4–6 bangs + 8–14 secondary locks (§4) |
| Bald patch / exposed crown after "fixing" coverage | locks under the scalp surface, or widened locks sliding off the skull | roots stand proud along the normal; add locks, never widen; `scalp_exposure.py` ≤ 15 % (§4) |
| Head reads hollow between locks; bangs cover both eyes | face constraints ignored | keep nose-to-hair clearance in profile; bangs may not cross both eye centers (§4) |
| Hair drags the skull when the neck bends | hair smooth-skinned to the body skeleton | rigid parent to the head bone or own few bones (§4) |
| A part exists in the model but not in the reference (e.g. an invented mane) | dark mass misread | delete it; every part traces to a reference region (§3) |
| Head too large for the scaffold | ears counted into skull width | skull width (ears excluded) drives head scale (§5) |
| Visible gap or crease between body and tail/wing | L0↔L1 seam verts not coincident | coincident verts or one merged mesh (§5) |
| Degenerate faces along trimmed L4 edges | boolean/trim leftovers | `mesh_report.py` (§5), clean before weight transfer |
