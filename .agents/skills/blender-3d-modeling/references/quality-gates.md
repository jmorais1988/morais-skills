# Quality Gates & Project State

A model built from references needs two disciplines a chat window doesn't give you: a written **definition of done** decided before modeling, and a **checklist with evidence** so progress isn't reconstructed from memory. Scripts do the measuring; you do the judging. No script here approves a model — they only catch the defects that eyes miss.

## Contents
1. Complexity assessment & quality contract
2. Project state checklist
3. Deterministic checks — what they catch and what they can't
4. Bounded correction loop
5. Reporting rules

## 1. Complexity assessment & quality contract

After the reference study (`reference-gathering.md`) and before the blockout, score the subject 0–3 on each axis and write the contract into `references/NOTES.md`:

| Axis | 0 | 3 |
|---|---|---|
| Silhouette complexity | simple outline | heavily interrupted / organic |
| Component count | one piece | dozens of visible parts |
| Hierarchy depth | flat | deep parent–child (assembly of assemblies) |
| Repetition density | none | hundreds of leaves / rivets / scales |
| Material layers | one | many with local wear/dirt/paint |
| Local detail density | plain | dense scratches, seams, pores, grain |
| Occlusion risk | fully visible | many hidden/inferred parts |
| Motion / articulation | static | many pivots, joints, deformation, destruction |

Total → **simple** (few parts, 1–2 materials) · **moderate** (several parts, visible detail) · **complex** (many parts, repeated systems, several hierarchy levels) · **ultra-complex** (fidelity depends on deep hierarchy and microstructure). Minimum detail-inventory counts: 3 / 6 / 10 / 16.

**Quality contract** (specific to *this* subject, never generic):
- Definition of done in one paragraph (what it must read as, from which views, at what distance).
- Required parts at macro / meso / micro level, with counts for repeated systems and their distribution rule ("22 rail slots, 10 mm pitch, starting 12 mm from the front face").
- Required materials and local overrides (edge wear on bevel crests, cavity dirt in grooves…).
- Review views required: the turntable, top, three-quarter, cross-section and camera-matched views of `review-and-comparison.md` §1, plus close-ups on the sensitivity features.
- Failure modes that block completion (e.g. "grip has no palm swell", "eye line above 0.5 HH").
- Budget: tri count / LOD / texture size (from `poly-budgets-and-targets.md`).
- Weak: "make the bark look good". Strong: "trunk needs vertical ridges 20–40 mm apart, cavity-darkened cracks, moss patches at the root flare and inner forks, non-uniform displacement".

If the contract could describe many different objects, the study isn't finished.

## 2. Project state checklist

Keep the checklist outside the conversation:

```bash
python scripts/project_state.py init --state <asset>/.model_state.json --asset "Bowie knife" --profile hard-surface --budget-tris 8000
python scripts/project_state.py next --state <asset>/.model_state.json      # ordered steps, what's pending, loop counters
python scripts/project_state.py mark blockout --state ... --evidence references/review/blockout_turntable.png --note "proportions within 3% of NOTES ratios"
python scripts/project_state.py mark uvs --state ... --skip --reason "user wants untextured STL"
python scripts/project_state.py loop refine-geometry --state ... --stage detail --note "grip cross-section flat → lofted swell"
```

Profiles add steps. `python scripts/project_state.py profiles` prints every profile with its ordered steps — run it rather than trusting a list in prose. Today it lists 24: `hard-surface`, `organic`, `character`, `archviz`, `animation`, `game-asset`, `jewelry`, `character-rig`, `uv-bake`, `stylized`, `simulation`, `product-render`, `mesh-repair`, `logo-solid`, `texture-paint`, `pipeline-publish`, `web-asset`, `print`, `environment`, `flora`, `fauna`, `city`, `modular-kit`, `kitbash`. Every completed step needs an evidence path (screenshot, report JSON); a skipped step needs a reason. `next` exits non-zero and prints `STOP` when a loop limit is hit — then ask the user instead of continuing.

**Scenes that span profiles** (an environment with a vehicle and an animal): one state file per asset with its own profile (`assets/deer/.model_state.json --profile fauna`, `assets/crate/... --profile hard-surface`) plus one scene-level file (`--profile environment`) whose `hero-assets`/`scatter` steps take the asset state files and their final reviews as evidence. Parallel lanes (`parallel-work-with-subagents.md`) each own their asset's state file.

The state file is an index of what's been verified, not the evidence itself; renders, `mesh_report` output and NOTES.md remain the authority. Re-run `next` at the start of every session and before every correction.

## 3. Deterministic checks — what they catch and what they can't

| Check | Script | Catches | Blind to |
|---|---|---|---|
| Topology & hygiene | `mesh_report.py` (bpy; `topology.md` §9) | tris/ngons on curves, ≥6 poles, non-manifold, slivers, unapplied scale, budget | whether the shape is right |
| Silhouette vs reference (aligned) | `silhouette_compare.py` (sandbox) | proportion/outline mismatch after scale+translate alignment; interior appearance difference banded by height; symmetry parity | depth/cross-section; anything about the view it wasn't given; lighting differences are noise — advisory only vs photographs |
| Multi-angle degenerate view | `scene_gates.py --orbit` (bpy) | a part whose projected area collapses at some azimuth (a card faking a volume, a 2.5D slab) | subtle taper errors |
| Chirality (L/R pairs) | `scene_gates.py` (bpy; `assembly-and-hierarchy.md` §4) | `.L/.R` pairs that are rotated copies instead of mirrors; mismatched vertex counts | a pair wrong the same way on both sides (compare to reference) |
| Attachment / floating parts | `scene_gates.py` (bpy; `assembly-and-hierarchy.md` §3) | children whose mesh has a gap to their parent larger than tolerance; pivots far from the contact | wrong *kind* of joint |
| Self-intersection | `scene_gates.py` (bpy) | sibling meshes that interpenetrate unintentionally (BVH overlap) | intentional overlaps (declare them) |
| Part coverage | `scene_gates.py --parts` (bpy; `assembly-and-hierarchy.md` §7) | parts in the contract never built; two contract parts fused into one object; unnamed objects | whether the contract was complete |
| Rig payload | `rig_check.py` (bpy; `rigging-and-weights.md` §2) | weights not normalized, >N influences, unweighted verts, bone scale ≠ 1, unmirrored bone pairs | likeness, animation intent |
| Pose sweep & motion | `rig_check.py --action` (bpy; sweep on by default; `rigging-and-weights.md` §3) | collapse/explosion at 90° flexion, verts snapping to origin, an action that exists but moves nothing, foot slide, loop that doesn't return | creases vs holes trade-offs need eyes |
| Scalp exposure | `scalp_exposure.py` (bpy; `character-modeling.md` §4) | bald patches: scalp points with no hair geometry *outside* the skull above them | hair style/silhouette quality |
| Shape keys | `shapekey_check.py` (bpy; `shape-keys-and-visemes.md` §7) | keys that move nothing, leak outside their region, asymmetric L/R pairs, lids cutting the eyeball at any key value | whether the expression reads |
| Intake repair | `mesh_repair.py` (bpy; `mesh-repair.md` §9) | open/non-manifold shells, flipped normals, floaters, inner shells, budget, deviation from the source | whether hallucinated or scanned regions are *right* |
| Simulation | `sim_check.py` (bpy; `simulation.md` §5) | cloth penetration/poke-through/not settled, dominoes not toppling, sleeping bodies moving, liquid volume loss, missing caches | art direction of the motion |
| Archviz shots | `archviz_gates.py` (bpy; `archviz-modeling.md` §8, `archviz-lighting-and-rendering.md` §6) | light leaks, slab gaps, visible z-fighting, floating/sunk furniture, out-of-range sizes, tilted cameras, render settings | taste, composition, material realism |
| Print readiness | `export_print.py` (bpy; `3d-printing.md` §5) | non-manifold, self-intersection, walls below minimum, part clearances, export scale | printer-specific tolerances |
| Export round-trip | `export_check.py`, `interchange_check.py` (bpy; `game-engine-delivery.md` §7, `usd-and-alembic.md` §5) | axis/scale errors, lost UVs/normals/materials/animation, unit metadata, broken library links | engine-side import settings |
| Naming & hygiene | `naming_lint.py` (bpy; `project-files-and-naming.md` §6) | convention violations, `.001` duplicates, L/R suffix pairs, orphans, absolute/missing paths | whether names are meaningful |
| UVs | `uv_tools.py check` (bpy; `uv-unwrapping.md` §7) | partial overlaps, mirrored/stacked islands in lightmap sets, stretch, padding below the px margin, texel density outside tolerance, out-of-tile islands | seam placement quality |
| Stylized normals & lines | `normal_transfer.py`, `lineart_setup.py --verify` (bpy; `anime-face-and-hair.md` §1, `outlines-and-line-art.md` §3) | custom normals off the proxy inside the mask or changed outside it, wrong modifier order, proxy not following the rig; Line Art strokes missing or misaligned with silhouettes | whether the shading reads as the style |
| Vector & voxel solids | `svg_to_solid.py`, `voxelize.py --check` (bpy; `vector-and-text.md` §4, `voxel-and-pixel-art.md` §3) | logo width off target, holes lost, bevel self-intersection; off-grid voxel vertices, internal or duplicate faces | design fidelity to the brand |
| Painting | `paint_ops.py`, `ucupaint_ops.py` (bpy; `texture-painting.md` §8) | strokes that changed no pixels or landed off-surface, unsaved images, empty Ucupaint bakes | artistic quality |
| Framing & renders | `shot_setup.py` (frame margin, turntable loop), `render_cli.py` (bpy/CLI; `rendering-and-lighting.md` §5, `render-farm-and-compositing.md` §2) | subject cropped or off-centre, non-looping turntables, missing/black/duplicate frames | lighting quality |
| Part contacts | `auditing-3d-geometry` skill (`mesh_audit.py`, bpy) on one object per part | member ends short of joints (GAP/FLOATING), buried parts, pass-throughs between assemblies | whether a deliberate seat is acceptable: triage every hit |

Generated assets merged into a few per-material meshes hide their part contacts from per-object audits. Have the builder record each primitive (assembly tag + face range), write one debug object per primitive for the audit, group them by assembly, and delete them before export. `mesh_audit.py` skips objects with `hide_render = True`.

Order: deterministic checks first, then visual review (`review-and-comparison.md`). A check with missing input reports `unevaluated` with a reason — it is never a pass. A passing check is not proof of 3D realism; it removes one class of defect.

**Silhouette IoU is ~11 % of the picture.** It reads the outline cells only; a face deleted from a head scored identically to the finished face in synthetic tests. Use `interior_difference` bands and your eyes for everything inside the outline, and never optimize toward the IoU number — you'll distort the model to pixel-match a photo.

## 4. Bounded correction loop

Per stage: at most **3** correction iterations; per project: **6** before stopping to ask. The state script counts them from `loop` calls. Stop early if:
- the same defect appears in two consecutive reviews (fix isn't reaching the cause → go back to the plan/references),
- fixes oscillate (A → B → A) — you're tuning against noise,
- scores plateau while a visible defect remains — the gate is measuring the wrong thing.
Each iteration ends with one action chosen per `review-and-comparison.md` §3 (continue / refine plan / refine geometry / request input / stop). Hard-gate failures (non-manifold, floating part, chirality) are always *refine geometry*; repeated or structural defects are *refine plan*.

## 5. Reporting rules

For every gate run, report the number and what the gate did *not* look at (`sampledVertexCount`, `unmeasuredParts`, `missingViews`). Report what changed with values and what still doesn't match (`review-and-comparison.md` §4). "All gates pass" means "these defect classes are absent", not "done".
