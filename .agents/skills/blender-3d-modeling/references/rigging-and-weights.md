# Rigging, Weights & Control Rigs

Read this once the character mesh is retopologized and every part carries its layer (`character-modeling.md` §1): armature and weight rules, the measured gates of `scripts/rig_check.py`, pose-sweep and action checks, and control rigs from code (IK, foot roll, Rigify) baked to deform bones for export (`scripts/ik_rig.py`). Prove the rig with measurements, never by looking at the rest pose. `scripts/project_state.py` ships a `character-rig` profile (target → references → armature → weights → rig-check → controls → ik-check → animate → bake-deform → export-actions → reimport-verify); animation authoring starts in `animation.md` once `rig_check.py` passes.

## Contents
1. Armature & weights rules
2. Rig readiness gates (`scripts/rig_check.py`)
3. Pose sweep and animation checks
4. Control rigs from code
5. Common failures

## 1. Armature & weights rules

- Bone names unique, `.L/.R` suffixes (Blender's symmetrize and mirror-paint depend on them); deform bones flagged `use_deform`; control/technical bones not deforming.
- Rest pose: every bone scale (1,1,1); armature object scale 1, rotation applied; character at real scale, feet on Z=0, origin at feet.
- Weights: normalized to 1.0 (`Normalize All`); influences per vertex capped by target — **4 mobile, 8 PC/console, unlimited film** (`Limit Total` to the cap before export); no unweighted vertices; `Clean` to remove near-zero weights.
- Auto-weights from a good armature are a starting point; paint joint blends (elbow/knee inside vs outside), and use Corrective Smooth or shape keys (drivers) for volume loss — corrective shape keys and drivers: `shape-keys-and-visemes.md` §2; their checks: `shape-keys-and-visemes.md` §7.
- L3 parts: weight 1.0 to one bone or bone-parented. L4: Data Transfer from L0 then smooth (layers and the cross-joint test: `character-modeling.md` §1–2).
- Test in **pose mode with real poses**, never trust the rest pose.

## 2. Rig readiness gates (`scripts/rig_check.py`)

`blender -b char.blend --python scripts/rig_check.py -- --armature <rig> [--max-influences 8] [--action <name>]`

| Gate | Pass |
|---|---|
| Bone scale | all deform bones scale (1,1,1) in rest and current pose |
| Weight sum | every vertex Σweights within 1e-4 of 1.0 (or 0 only on non-deforming meshes) |
| Influences | ≤ N per vertex (default 4 = mobile cap; pass 8 for PC/console) |
| Coverage | no unweighted vertex on a deforming mesh; every visible mesh has an Armature modifier or bone parent |
| Symmetry | every `.L` deform bone has a `.R` twin with mirrored head/tail within tolerance |
| Medial/lateral | `.L` bones have +X heads and `.R` have −X (Blender convention: character's left = +X when facing −Y) |
| L3 rigidity | parts tagged `obj["layer"]=="L3"` have a single influence or bone parent |

A gate with missing input (no armature, no action) reports `unevaluated` — never a pass.

## 3. Pose sweep and animation checks

Authoring recipes, loop/root-motion/in-place options and clip export: `animation.md`; `rig_check.py` assigns the action slot automatically (5.x actions assigned without a slot play nothing).

- **Pose sweep** (on by default in `rig_check.py`; `--no-sweep` to skip): rotate each deform bone to 45° and 90° flexion about its local X (and −X), evaluate the mesh, and check: no vertex collapses to the origin; bounding sphere neither collapses (< 70 %) nor explodes (> 150 %) vs rest; no vertex moves more than 0.5 H. Sample at least both sides × two view azimuths; five poses is not coverage.
- **Holes vs creases**: at overlaps between separate parts (L4 over L0) a *hole* shows the background, a *crease* shows skin. Prefer creases; report both counts, not a combined score. Continuous L0 mesh with unified weights is the real fix.
- **Action actually moves** (`--action <name>`): sample the action at ≥4 times; max joint displacement must exceed 1e-3 H. An action that exists, has a duration, and drives nothing is the silent failure this catches.
- **Loop**: a clip loops when pose return ≤ 0.5° per bone **and** hip displacement ≤ 0.01 H between first and last frame — travel distance decides nothing (`--hip-bone`, `--allow-root-motion` with `--root-bone`).
- **Foot contact**: during stance phases the foot bone's world position slides ≤ 0.01 H (`--foot-bones`, `--foot-mode`).
- All thresholds are fractions of figure height **H**, never absolute units.
- Names that describe motion ("arm_swing") are provable; names that imply intent ("attack") are inferred — label them so.

## 4. Control rigs from code

Controls are non-deforming bones that drive deform bones through constraints. Engines only receive deform bones, so every control rig ends with a bake (§4.4).

| Need | Route | Measured cost (5.2, headless) |
|---|---|---|
| One limb, creature leg or arm; no add-on | `scripts/ik_rig.py --add` (two-bone IK, pole, optional foot roll) | < 1 s; 6 readable bones per leg |
| Full biped with IK/FK switch, tweaks, face | Rigify (bundled) from a metarig | 3.1 s generate for the human metarig → 706 bones |
| Game/engine export of either | bake to deform bones: `ik_rig.py --bake 1-48 --copy` | see §4.4 |

### 4.1 IK constraint (API names verified in 5.2)

| Setting | Use |
|---|---|
| `c = pb.constraints.new('IK')` on the chain **tip** (shin, forearm) | `c.target = rig; c.subtarget = "IK_shin.L"`. The target bone must sit outside the chain (unparented, or under root/foot controls) |
| `chain_count` | 2 for thigh+shin. 0 means "to the root" and pulls the spine |
| `pole_target`, `pole_subtarget`, `pole_angle` (radians) | pole bone in the bend plane about 1 chain length out from the knee. A closer pole makes the knee snap when the target passes it |
| `use_tail=True`, `iterations` 500 | defaults |
| `use_stretch` **and** per-bone `pb.ik_stretch` | stretch needs both. Measured on a 0.15 m over-reach: reach error 0.142 m with `ik_stretch=0`, 0.0002 m with 0.1 |
| `use_rotation` | off for legs; the foot copies rotation from its control instead |

**Pole angle** is the angle that keeps the rest pose. `ik_rig.pole_angle_for()` computes it from the base bone's X axis and the root–tip–pole plane, then wraps it: `pole_angle` clamps to ±180° (270° became 180°). A leg along −Y with the pole in front gives −90°, which is also what Rigify's limbs use. `check_ik` (`ik_rig.py --check`) proves it:
- Target at the rest tip: knee drift 0.002 mm.
- Target moved 30 % toward the hip: the knee moves toward the pole (cos 1.0).
- Planted 180° error: drift 120 mm, cos −1 (flip). Planted 90° error: drift 85 mm, cos −0.18. Both fail.

**Pre-bend** knees and elbows a few degrees at rest. A straight chain has no bend direction, so `ik_rig.py` then needs `--pole-dir`.

### 4.2 Foot roll (reverse foot)

`CTRL_foot` (at the heel, on the ground) → `MCH_heel` (heel pivot) → `MCH_ball` (ball pivot at the foot tail) → IK target + `MCH_foot`. The foot deform bone gets Copy Rotation from `MCH_foot`. The custom property `roll` on `CTRL_foot` drives `MCH_heel` X rotation with `min(roll,0)` and `MCH_ball` with `max(roll,0)`. These are simple-expression drivers (`is_simple_expression` True), so no Python auto-run is needed. Measured: roll +0.5 rad lifted the ankle 67 mm while the ball slipped 0.006 mm; roll −0.3 lifted the toes 47 mm. **Gotcha**: setting an ID property from Python does not re-run drivers on `view_layer.update()`, and the rig stayed flat. Call `scene.frame_set(scene.frame_current)` to force it. Toe-tip and bank pivots follow the same pattern (not built by the script).

### 4.3 Rigify from code

- Rigify is a core add-on (`scripts/addons_core/rigify`), not an extension. Enabling it changes the user's setup, so **ask first**. Tests run in a separate `blender -b --factory-startup` process with `addon_utils.enable("rigify", default_set=True)` (0.3 s). With `default_set=False`, generate fails (`KeyError` on `preferences.addons["rigify"]`). Never call `wm.read_factory_settings()` or `preferences.*` in a session with user extensions.
- `bpy.ops.object.armature_human_metarig_add()` exists only after enabling. It adds `metarig` with 159 bones. Other metarig operators: `dir(bpy.ops.object)` [unverified list].
- Fit the metarig joints to the character in edit mode, keeping `.L/.R`. Then make the metarig the **view-layer active object** and call `bpy.ops.pose.rigify_generate()`. Headless works: 3.1 s; regenerating took 4.4 s and rebuilt into the same `metarig.data.rigify_target_rig`. Don't wrap the call in `temp_override(active_object=metarig)`: generation asserts `context.active_object` is the new rig → `AssertionError`, and a half-built `metarig.001` (159 ORG bones, all deforming) is left to delete.
- Output: `rig` with 706 bones: 160 `DEF-` (the only deform bones), 159 `ORG-`, 167 `MCH-`, plus controls (`foot_ik.L`, `foot_heel_ik.L`, `thigh_ik_target.L` pole, `hand_ik.L`, `torso`). You also get the `rig_ui.py` text and a `WGTS_rig` collection. IK/FK lives in custom properties on `thigh_parent.L` / `upper_arm_parent.L`: `IK_FK` (0 = IK), `IK_Stretch` (1.0), `pole_vector`, `IK_parent`, `pole_parent`. Weights go on `DEF-` names.

### 4.4 Bake controls to deform bones for export

In pose mode, select only the deform bones, then run `bpy.ops.nla.bake(frame_start=, frame_end=, step=1, only_selected=True, visual_keying=True, clear_constraints=True, clear_parents=False, use_current_action=False, clean_curves=False, bake_types={'POSE'})`. Visual keying stores the constraint result. `clear_constraints` detaches the baked bones from the controls. A new action is assigned with slot `OB<rig>` (verified). The bake is destructive, so run it on a copy (`ik_rig.py --copy` → `<rig>_BAKE`) or a duplicate file. Then export deform bones only (FBX `use_armature_deform_only=True`; engines per `animation.md` §5).

`ik_rig.py --bake` records world head/tail of every requested bone per frame, bakes, and re-measures. Pass needs max error ≤ 0.1 mm, every bone keyed, and no constraints left. The bake unhides bone collections first, because `only_selected` silently skips hidden bones: before that fix, Rigify keyed 2 of 160 DEF bones. Measured:

| Rig / mode | Max bake error |
|---|---|
| Synthetic leg, deform bones (in place or `--copy`) | 0.004 mm; skinned-mesh deviation 0.004 mm over 0.45 m of motion |
| Planted: thigh left out | 0.81 m → fail (the unbaked parent sits at rest once the controls lose their keys) |
| Rigify human, DEF- only (`foot_ik.L` + `torso` keyed) | 316 mm → fail: 116 of 160 DEF bones are parented to ORG-/MCH- |
| Rigify, DEF- + all ancestors (278 bones) | 7 mm → fail (inherited non-uniform scale shears; visual keys can't store shear) |
| Rigify, `--export-skeleton` (deform-only copy, 116 bones re-parented, Copy Transforms, baked) | 7 mm with inherited scale; **0.0016 mm with `--inherit-scale NONE`** (0.4 s) |

For Rigify → engine: bake the export skeleton, point the mesh's Armature modifier at `<rig>_EXPORT` (vertex groups already use DEF- names), and export that. An engine may re-apply parent scale that `inherit_scale NONE` ignored [unverified]. For game rigs set `IK_Stretch` to 0 and round-trip the export.

## 5. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Mesh collapses or explodes in a pose, vertices fly to the origin | unweighted verts, weights on the wrong bone, bone scale ≠ 1 | pose sweep thresholds (< 70 % / > 150 % sphere, 0.5 H per vertex); `Normalize All`, `Clean`, coverage gate (§1–3) |
| Action exists, has a duration, nothing moves | action drives nothing, or 5.x action assigned without a slot | `--action <name>`: max joint displacement > 1e-3 H; `rig_check.py` assigns the slot (§3) |
| Clip pops at the loop point | pose return > 0.5° per bone or hip displacement > 0.01 H | fix first/last frames; loop gate (§3) |
| Feet skate during stance | foot bone slides > 0.01 H | plant with IK; foot-contact gate (§3) |
| Knee or elbow points sideways/backwards as soon as IK is added | pole angle off by 90°/180° | `pole_angle_for()`; `ik_rig.py --check` (rest drift, cos) (§4.1) |
| Limb stays straight or flips when the target passes the pole | pole too close, or chain straight at rest | pole ≥ 1 chain length out; pre-bend the rest pose (§4.1) |
| `use_stretch` on but the limb never stretches | `pb.ik_stretch` is 0 | set 0.05–0.1 on each chain bone (§4.1) |
| Foot-roll property does nothing from a script | drivers not re-evaluated | `scene.frame_set(scene.frame_current)` (§4.2) |
| `rigify_generate` → AssertionError | `temp_override(active_object=metarig)` | set `view_layer.objects.active` instead (§4.3) |
| Rigify generate KeyError `rigify` | enabled with `default_set=False` | `default_set=True` in a factory-startup process (§4.3) |
| Exported clip plays in Blender, dead in engine | controls exported, deform bones unbaked or partly baked | bake all deform bones with visual keying; export deform only (§4.4) |
| `nla.bake` keyed only a few bones | bones in hidden bone collections aren't selectable (Rigify DEF-) | unhide collections while baking (`ik_rig.py` does) (§4.4) |
| Baked DEF- bones drift (cm to dm) from the control rig | DEF- parented to ORG-/MCH-, or inherited non-uniform scale | `ik_rig.py --bake --export-skeleton --inherit-scale NONE` (§4.4) |
