# Shape Keys, Correctives & Visemes

Read this when a mesh needs blend shapes: facial expressions, ARKit/Oculus/Preston Blair sets, corrective shapes driven by bone rotation, eyelid blinks that must clear the eyeball, lip-sync keys generated from phoneme timings, and getting all of that through FBX/glTF. Body animation, clip staging and engine presets are in `animation.md`; this file is the KEY-slot side of a clip.

## Contents
1. Creating and authoring shape keys from code
2. Drivers and corrective shape keys
3. Eyelids, jaw, teeth and tongue
4. Naming sets: ARKit, Oculus, Preston Blair
5. Lip-sync from audio (`scripts/lipsync_keys.py`)
6. Exporting shape keys and shape-key-only clips
7. Checks (`scripts/shapekey_check.py`)
8. Common failures

## 1. Creating and authoring shape keys from code

- **Basis**: `obj.shape_key_add(name="Basis", from_mix=False)`, then one key per shape. Measured in 5.2: new keys start with `value = 1.0` (Python and operator), so set values explicitly before evaluating anything. `key.use_relative=True`, `kb.relative_key` (default Basis), `kb.slider_min/max`, `kb.vertex_group` (mask), `kb.mute`.
- **Slot**: shape-key animation is keyed on the `Key` datablock through a KEY slot (`act.slots.new(id_type='KEY', ...)` → `KEKey`); one action can hold the body's OBJECT slot and the face's KEY slot (`animation.md` §1).
- **Authoring from code**: `kb.data[i].co` or `foreach_set("co", flat)`. In the UI, sculpt or edit with the key active (`obj.active_shape_key_index`). 5.0 added "Make Basis" (`object.shape_key_make_basis`) and 5.1 "Apply to Basis" (`object.shape_key_apply_to_basis`). Destructive, so prefer them only when intended.
- **Mirror L/R**: build `smile.L`; duplicate (`shape_key_add(from_mix=True)` with only that key at 1.0); rename `smile.R`; `bpy.ops.object.shape_key_mirror(use_topology=False)` on the active key. `use_topology=True` only when the mesh is topologically but not positionally symmetric. 5.0 added flipped "Join as Shapes" / "Update from Objects" variants (`join_shapes(use_mirror=True)`). **Split** a symmetric key with two copies whose `vertex_group` masks are left/right halves with a 2–4 cm soft falloff across the centre line.
- **Naming**: side suffix at the end (`.L/.R`, `_L/_R`) or ARKit `Left/Right`. `shapekey_check.py` pairs all of them.

## 2. Drivers and corrective shape keys

- **Drivers**: `fc = kb.driver_add("value"); d = fc.driver; d.type = 'SCRIPTED'`; `v = d.variables.new(); v.type = 'TRANSFORMS'`; `t = v.targets[0]; t.id = rig; t.bone_target = "forearm.L"; t.transform_type = 'ROT_X'; t.transform_space = 'LOCAL_SPACE'; t.rotation_mode = 'SWING_TWIST_X'` (enum verified); `d.expression = "max(0, min(1, rot / 1.5708))"`. Measured: 0.25 rad drove the key to 0.5 with a 0.5 rad divisor. Since 5.0 a Python-created driver F-curve gets **2 keyframes** instead of a Generator modifier (verified 2 keys, 0 modifiers), and they form the mapping curve. Simple expressions (min/max/arithmetic) evaluate without Python auto-run.
- **Corrective shape keys**: name `corr_<joint>_<angle>` (`corr_elbow.L_90`). Pose the joint to the target angle, sculpt the fix on a key that is 0 at rest and 1 at that angle (driver as above), and confine it with `vertex_group`. Use swing-twist rotation modes so twist doesn't trigger a bend corrective. The glTF manual requires the driven mesh to be a direct child of the armature for sampled driver export.

## 3. Eyelids, jaw, teeth and tongue

- **Eyelid over eyeball**: a lid must stay outside the eyeball (plus cornea bulge) at **every** blink value, not just 0 and 1. Shape keys interpolate each vertex along a straight line. A lid that rotates around the eye by θ cuts the chord through the sphere when `r_lid·cos(θ/2) < r_eye`. Fix with an in-between key at 0.5 (driver-combined), or rotate the lid with bones. Check with `shapekey_check.py --eye "Head:lid.L=Eye.L" --values 0.25,0.5,0.75,1` (form `<lid object>:<group>=<eyeball>`; the object part may be omitted when it is `--object`, as in `--eye "Lid.R=Eye.R"`).
- **Jaw / teeth / tongue**: jaw is a bone (rotation) so lower teeth and tongue ride it rigidly (L3/L2 in `character-modeling.md` §1); the skin gets `jawOpen` via weights plus a corrective. In ARKit `mouthClose` closes the lips while the jaw is open and is meant to be used on top of `jawOpen` [unverified wording]. Tongue uses 2–4 bones or `tongueOut`. Keep the inner mouth bag skinned to jaw and head.

## 4. Naming sets: ARKit, Oculus, Preston Blair

| Set | Count | Names (exact) |
|---|---|---|
| ARKit (Apple `ARFaceAnchor.BlendShapeLocation`) | 52 | eyeBlinkLeft/Right, eyeLookDown/In/Out/UpLeft/Right, eyeSquintLeft/Right, eyeWideLeft/Right, jawForward, jawLeft, jawRight, jawOpen, mouthClose, mouthFunnel, mouthPucker, mouthLeft, mouthRight, mouthSmileLeft/Right, mouthFrownLeft/Right, mouthDimpleLeft/Right, mouthStretchLeft/Right, mouthRollLower, mouthRollUpper, mouthShrugLower, mouthShrugUpper, mouthPressLeft/Right, mouthLowerDownLeft/Right, mouthUpperUpLeft/Right, browDownLeft/Right, browInnerUp, browOuterUpLeft/Right, cheekPuff, cheekSquintLeft/Right, noseSneerLeft/Right, tongueOut |
| Oculus / Meta Lipsync visemes | 15 | sil, PP, FF, TH, DD, kk, CH, SS, nn, RR, aa, E, ih, oh, ou (VRChat-style avatars prefix `vrc.v_` [unverified]) |
| Preston Blair (cartoon) | 10 | AI, E, O, U, etc (C D G K N R S Th Y Z), FV, L, MBP, WQ, rest |

Name the keys exactly as the target expects (case-sensitive), because engines and live-capture apps bind by name. Keep one naming set per mesh.

## 5. Lip-sync from audio (`scripts/lipsync_keys.py`)

Blender does no phoneme recognition. Get timings from an external tool, then turn them into keys:

```
blender -b head.blend --python scripts/lipsync_keys.py -- --object Head --timing cues.json --set oculus
    [--jaw jawOpen | --jaw-bone Rig:jaw --jaw-angle 18] [--blink eyeBlinkLeft,eyeBlinkRight --blink-every 4]
    [--audio line.wav] [--attack 2 --release 3 --offset 0] [--resolve-overlaps] [--save out.blend]
```

| Source | Output the script reads | Symbols |
|---|---|---|
| Rhubarb Lip Sync (CLI, `-f json` / `tsv` / `dat`) | `{"mouthCues":[{"start","end","value"}]}`, TSV `0.05<TAB>D`, Moho `.dat` | A–F basic, G H X extended. The README maps A=MBP, B=etc, C=E, D=AI, E=O, F=U, G=FV, H=L, X=rest |
| Papagayo / Moho switch export | `MohoSwitch1` header, then `frame shape` lines (frames read as 1-based at `--dat-fps` [unverified]) | Preston Blair |
| Forced aligner / TTS timing | JSON list `[{"t":0.12,"phoneme":"AA"}]` with optional `end`/`dur`/`weight` | ARPAbet (stress digits stripped), or viseme names |

- **fps first**: the script converts seconds → frames with the scene's current fps (`scene.render.fps` / `fps_base`, `animation.md` §3). Decide 24/30/60 before keying; changing fps afterwards shifts every viseme, so re-run the script instead of retiming.
- **Mapping**: every symbol maps to the 15 Oculus visemes, then to the output set (`--set oculus|preston|rhubarb|arkit`). ARKit has no visemes, so each viseme becomes a heuristic blend (e.g. `aa` → `jawOpen` 0.7, `ou` → `mouthPucker` 0.8 + `jawOpen` 0.15). Tune it per face or pass `--map custom.json` (`{"AA": {"jawOpen": 0.6}}`). `--prefix vrc.v_` handles prefixed avatars.
- **Envelope**: each segment ramps up over `--attack` frames (default 2), centred on its start, and down over `--release` frames (default 3), centred on its end. Neighbours therefore cross-fade and sum to about 1, so two exclusive visemes can't both exceed 0.9. Co-articulation is built in: a segment shorter than the ramp never reaches full value. `--smooth N` adds a box filter. Consecutive identical visemes merge, so held sounds don't dip.
- **Extra channels**: `--jaw jawOpen` (shape key) or `--jaw-bone Rig:jaw --jaw-angle 18` gets a per-viseme openness curve (`aa` 0.8 … `PP` 0). `--jaw-bone` writes the jaw curve (pose-bone `rotation_euler` X) into a **second action** `<Rig>_Lipsync` with an OBJECT slot on the rig, so the export must pair it with the face action (§6). `--blink` adds seeded blinks every `--blink-every` s ±30 % (close 2 frames, hold 1, open 4). `--audio line.wav` adds a sound strip via `scene.sequence_editor.strips.new_sound` (5.x: `strips`, not `sequences`) and extends `frame_end`.
- **Writing**: keys are LINEAR on integer frames, collinear keys are dropped, and everything goes to action `<object>_Lipsync` with a KEY slot (`KEKey`) on the shape-key datablock. A re-run replaces its own Visemes/Jaw/Blink groups.
- **Clip time origin**: the first key lands at `floor(first cue frame − attack) − 1` (cue frame = `frame_start + t·fps + offset`), which can fall **before** `scene.frame_start` while the audio strip starts exactly at `frame_start`. Exported samplers then start earlier than the wav (§6).
- **Gates** (measured): the clean ARPAbet "hello world" run hit its expected frames 8/8 with 0 exclusivity violations over 15 pairs, all values in [0, 1], and the slot plays (shape-key value after `frame_set` equals the F-curve). Rhubarb JSON → Preston, Rhubarb TSV → Oculus, Moho `.dat` → Oculus and ARPAbet → ARKit also passed. Planted defects were caught: unknown symbol `QX` (`unknown_symbols`); explicit overlapping intervals AA 0.1–0.5 s over UW 0.2–0.4 s (`overlaps` + `exclusive`, 3 frames with both at 1.0; passes after `--resolve-overlaps`); Oculus names on a Preston-keyed head (`missing_keys`, 6 listed). The ARKit exclusivity check covers only contradictory pairs (pucker vs stretch/smile). The heuristic weights stay ≤ 0.8, so it rarely fires.
- Look at it anyway: scrub with audio scrubbing on, since timing offsets of ±1–2 frames read as dubbing errors. Use `--offset -1` to lead the audio slightly [convention].

## 6. Exporting shape keys and shape-key-only clips

- **Formats**: FBX writes shape keys as blend shapes (5.1+ also writes their normals when mesh normals are exported, which the release notes say solves import issues in some game engines), and glTF writes morph targets (`export_morph`, `export_morph_normal`, `export_morph_animation`). Both FBX importers and the glTF importer restored the key and its animation in the round-trip test.
- **Modifiers**: the glTF exporter cannot export shape keys with Apply Modifiers on — export with `export_apply=False` and apply the non-Armature modifiers on the export copy by hand. Modifiers other than Armature above the shape keys can block shape-key export in other exporters too [unverified]; apply them on an export copy. Blender refuses `modifier_apply` on a mesh that has shape keys, so on the export copy either remove the modifier (web meshes rarely keep Subdivision) or bake it per key: evaluate the mesh with each key at 1.0 (`evaluated_get`), keep those copies, then rebuild the keys with `shape_key_add` + vertex copy `[unverified]`.
- **Rigged clips with face animation**: keep the KEY slot in the clip's action, or pass a separate face action with `scripts/export_actions.py --shape-actions '{"Walk": "Walk_face"}'` (JSON `{"clip": "shape_action"}`). The script stages armature and Key strips end to end (extrapolation `NOTHING`) so FBX takes don't leak blink curves; the measured traps (FBX all-actions dropping KEY curves, a Key active action leaking into every take, glTF `export_anim_single_armature`) are in `animation.md` §5.
- **Jaw bone from lip-sync**: `--jaw-bone` (§5) leaves the jaw in `<Rig>_Lipsync` and the visemes in `<Head>_Lipsync`; export both as one clip with `--armature Rig --actions Rig_Lipsync --shape-actions '{"Rig_Lipsync": "Head_Lipsync"}'`.

### Shape-key-only clips (no armature)

A talking head or an expression library with no rig exports through the glTF operator directly:
```python
bpy.ops.export_scene.gltf(filepath=out, use_selection=True, export_apply=False,
    export_morph=True, export_morph_normal=True, export_morph_animation=True,
    export_animation_mode='ACTIONS', export_force_sampling=True, export_anim_slide_to_zero=True)
```
- `scripts/export_actions.py --meshes Head --actions Head_Lipsync --preset web --formats glb` now runs without `--armature` and reports `shape_keys` / `shape_key_curves` per mesh in its re-import check.
- `scripts/export_check.py --inspect out.glb` (plain Python or `blender -b`) now reports the morph-target count per primitive, the `targetNames` list and which animations target `weights`.
- **Time origin**: because the first lip-sync key can precede `scene.frame_start` (§5), verify the sampler's first time in the inspect output (`weights_animations[].time_start`, `time_end`, `samples`); when the web player must start the wav at t = 0, export with `export_frame_range=True` (clip to the playback range) so the clip and the audio share the same origin.

## 7. Checks (`scripts/shapekey_check.py`)

```
blender -b face.blend --python scripts/shapekey_check.py -- --object Head [--keys "*"] [--eps 1e-5]
    [--region "eyeBlink*=lids,jaw*|mouth*=mouth"] [--sym-tol-mm 0.5] [--sym-rel 0.02] [--sym-axis X]
    [--symmetric "jawOpen,mouthFunnel"] [--eye "Head:lid.L=Eye.L" --eye "Lid.R=Eye.R"]
    [--lid-keys "*blink*,*Blink*,*lid*"] [--values 0.25,0.5,0.75,1] [--eye-radius 0] [--clearance-mm 0]
```
It measures in mesh object space (no armature pose); the eyeball is modelled as a sphere (centre = bbox centre of the evaluated eyeball, radius = `--eye-radius` or the mean vertex distance), so add `--clearance-mm` or a larger radius for a bulging cornea.

| Gate | Tool | Pass |
|---|---|---|
| Shape keys | `shapekey_check.py` | no empty or muted keys; moved verts inside their region group (weight ≥ `--weight-min` 0.001); L/R mirror error ≤ max(0.5 mm, 2 % peak); L key moves the +X side (character's left = +X facing −Y) |
| Lids | `shapekey_check.py --eye` | 0 lid points inside eyeball + clearance at 0.25/0.5/0.75/1 |
| Lip-sync | `lipsync_keys.py` (built in) | every non-neutral segment ≥ 1 frame reads ≥ 0.5 × its weight at its middle frame; no two exclusive visemes > 0.9 on one frame; values in [0, 1]; slot plays; no unknown symbols, overlaps or missing keys unless allowed |
| Export | `export_actions.py`, `export_check.py --inspect` | shape-key count per mesh matches; `shape_key_curves` animated; morph targets, `targetNames` and `weights` samplers present in the GLB |
| Look | scrub with audio scrubbing; blink at every value | no lid/eye clipping mid-blink; visemes land within ±1–2 frames of the audio |

## 8. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| New shape key already fully applied | 5.2 keys start at value 1.0 | set `kb.value = 0` after creation |
| Lid cuts the eyeball mid-blink only | linear shape-key interpolation chord | in-between key or bone-rotated lid; `--values 0.25,0.5,0.75` |
| Smile.R weaker or in a different place | hand-sculpted twin | mirror with `shape_key_mirror`; symmetry gate |
| Jaw key drags the forehead | unmasked sculpt | `kb.vertex_group`, region gate |
| Corrective fires on twist | euler bend axis picks up twist | `SWING_TWIST_*` rotation mode on the driver target |
| Visemes off by a constant factor of frames | fps changed after keying | set fps first; re-run `lipsync_keys.py` |
| `unknown_symbols` / `missing_keys` / `overlaps` | symbol outside the tables; wrong `--set` or prefix; overlapping cue intervals | `--map`, `--set`, `--prefix vrc.v_`; `--resolve-overlaps`; `--allow-unknown/--allow-missing` only knowingly |
| Jaw bone still in the exported clip | jaw curve lives in `<Rig>_Lipsync`, exported without the face action | `--armature Rig --actions Rig_Lipsync --shape-actions '{"Rig_Lipsync": "Head_Lipsync"}'` |
| Face curves leak into other clips or vanish | Key NLA strips not muted per take; FBX all-actions can't resolve KEY paths | NLA-staged export via `export_actions.py` (`animation.md` §5) |
| GLB has no morph targets | `export_apply=True` (Apply Modifiers) | `export_apply=False`; apply non-Armature modifiers on the export copy by hand |
| Web clip starts before the audio | first key at `floor(first cue − attack) − 1` < `frame_start` | `export_frame_range=True`; check the sampler's first time with `export_check.py --inspect` |
