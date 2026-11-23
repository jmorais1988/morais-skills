# Animation: Actions, Cycles & Clip Export

How to author animation from code in Blender 5.x (slotted actions), turn timing principles into keyable recipes (walk, run, idle, loops, root motion) and export several clips to engines — each step with a measurable check. Rig building and weights live in `rigging-and-weights.md`; this file starts once the rig passes `scripts/rig_check.py`. Shape keys, correctives, visemes and lip-sync (the KEY-slot side of a clip) live in `shape-keys-and-visemes.md`.

## Contents
1. Slotted actions: the 5.x data model
2. Authoring keys from code
3. NLA, clips, frame range, fps, markers
4. Motion recipes: walk, run, idle, loops, root motion
5. Exporting clips: FBX, glTF, engines
6. Checks
7. Common failures

## 1. Slotted actions: the 5.x data model

4.4 introduced slotted (layered) actions; 5.0 removed the legacy proxies `action.fcurves`, `action.groups`, `action.id_root` (verified absent in 5.2).

| Level | API (5.2, verified) | Notes |
|---|---|---|
| Action | `bpy.data.actions.new(name)` | not bound to an ID type any more |
| Slot | `action.slots.new(id_type='OBJECT', name="Rig")` → identifier `OBRig` | one slot per animated data-block; a duplicate name becomes `OBRig.001`; shape keys use `id_type='KEY'` → `KEKey` |
| Layer / strip | `action.layers.new("Layer")`, `layer.strips.new(type='KEYFRAME')` | 5.2 still supports one layer with one keyframe strip |
| Channelbag | `strip.channelbag(slot, ensure=True)` | holds `fcurves` and `groups` for that slot |
| Helpers | `bpy_extras.anim_utils.action_ensure_channelbag_for_slot(action, slot)`, `action_get_channelbag_for_slot`, `action_get_first_suitable_slot(action, 'OBJECT')`, `animdata_get_channelbag_for_assigned_slot` | prefer these over walking layers |
| Assignment | `ad.action = act`, then `ad.action_slot = slot` | `ad.action_suitable_slots`, `ad.last_slot_identifier` |

**The silent failure** (measured): an action keyed on `RigA` assigned to `RigB` gets `action_slot = None`, `action_suitable_slots = ['OBRigA']`, and the bone does not move (0.0 rad). After `ad.action_slot = ad.action_suitable_slots[0]` it plays (0.5 rad), and the slot lists both rigs as users. Auto-assignment only works when a slot's name matches the object. Always set the slot explicitly. `rig_check.py` now does this: `OB<name>` slot, else first suitable slot, else the slot with the most matching bone curves.

One action can hold several slots: a clip's body motion (OBJECT slot) and its face shape keys (KEY slot) live in the same action. glTF merges them into one animation ("merge by action"), and the new FBX importer rebuilds them the same way (§5). Authoring the KEY slot: `shape-keys-and-visemes.md` §1.

## 2. Authoring keys from code

**Quick path**: `pb.keyframe_insert("rotation_euler", frame=f, group=pb.name)`. Signature in 5.2: `keyframe_insert(data_path, *, index=-1, frame=None, group="", options=set(), keytype='KEYFRAME')`. Options: `INSERTKEY_NEEDED`, `INSERTKEY_VISUAL`, `INSERTKEY_REPLACE`, `INSERTKEY_AVAILABLE`, `INSERTKEY_CYCLE_AWARE`. On an unanimated armature it creates action `<Object>Action`, slot `OB<Object>`, one layer, one strip, the channelbag, and grouped F-curves (verified).

**Direct path** (bulk, no depsgraph cost, exact values):
```python
act = bpy.data.actions.new("Walk")
slot = act.slots.new(id_type='OBJECT', name=rig.name)
cb = act.layers.new("Layer").strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
fc = cb.fcurves.ensure('pose.bones["hips"].location', index=1, group_name="hips")
fc.keyframe_points.add(3)
for k, (f, v) in zip(fc.keyframe_points, [(1, 0), (13, .6), (25, 1.2)]):
    k.co = (f, v); k.interpolation = 'LINEAR'
fc.update()                      # recompute handles after bulk edits
rig.animation_data_create().action = act; rig.animation_data.action_slot = slot
```
`keyframe_points.insert(frame, value, options={'FAST'})` returns the `Keyframe`; `fcurves.find(path, index=)` and `.remove(fc)` work on the channelbag; `Action.fcurve_ensure_for_datablock(datablock, data_path, index=, group_name=)` also exists.

| Setting | Values | Use |
|---|---|---|
| `keyframe.interpolation` | `CONSTANT`, `LINEAR`, `BEZIER` (default) + easing presets | CONSTANT for blocking and stepped/stylized "on twos"; LINEAR for constant-speed root travel; BEZIER for splined motion |
| `keyframe.easing` | `AUTO` (default), `EASE_IN`, `EASE_OUT`, `EASE_IN_OUT` | applies to the easing presets (SINE…BOUNCE) |
| handle types | `AUTO_CLAMPED` (default), `AUTO`, `VECTOR`, `ALIGNED`, `FREE` | AUTO_CLAMPED avoids overshoot at extremes. AUTO overshoots, so feet go through the floor |
| `fc.modifiers.new('CYCLES')` | `mode_before/after` = `REPEAT` (default), `REPEAT_OFFSET`, `MIRROR` | REPEAT_OFFSET makes root travel accumulate cycle after cycle |
| rotation mode | `pb.rotation_mode = 'XYZ'` before keying eulers | quaternion bones need `rotation_quaternion` curves (4 channels) |

A CYCLES modifier on a 1→25 curve returned the frame-13 value at frame 37 (verified). Cycles only affect Blender playback. Exporters bake the frame range, so the loop must be real in the keys (§4).

## 3. NLA, clips, frame range, fps, markers

- **One clip = one action**, named for the engine (`Walk`, `Run`, `Idle_Breathe`, `Attack_01`). Don't use `.001` suffixes or object names inside clip names: the legacy FBX importer already prefixes `Object|`.
- Frame range: `act.use_frame_range = True; act.frame_start, act.frame_end = 1, 25; act.use_cyclic = True`. `act.frame_range` then returns the manual range and `act.curve_frame_range` the key extent (measured `[1,24]` vs `[1,25]`). Exporters use `frame_range`.
- NLA: `tr = ad.nla_tracks.new(); tr.name = "Walk"; st = tr.strips.new("Walk", start, act)`. Strips auto-pick a slot (verified `OBRigA`), but set `st.action_slot` when the action has several. Strip defaults: `blend_type='REPLACE'`, `extrapolation='HOLD'`. Use `NOTHING` for clips laid end to end, or a held strip bleeds into its neighbours. `ad.use_nla`, `tr.mute`, `tr.is_solo` control evaluation.
- FPS: `scene.render.fps` / `fps_base`. Decide before keying (24 film/stylized, 30 games/web, 60 only for fast combat reads); `scripts/lipsync_keys.py` also converts seconds → frames with the current fps. Retiming later: scale keyframe `co.x` and both handles about the start frame, or scale the NLA strip; `bpy.ops.object.shape_key_retime` does *not* retime keys — it only resets the timing of absolute shape keys (verified 5.2 operator description).
- Markers: scene `scene.timeline_markers.new("F_contact_L", frame=1)`; per-action `act.pose_markers.new("contact_L")` with `.frame` (both verified). Use per-action markers for footstep/event frames so they travel with the clip. Engine-side event import is [unverified].

## 4. Motion recipes: walk, run, idle, loops, root motion

Numbers are starting points. H = character height; one **step** = one foot contact to the other; one **cycle** = 2 steps.

| Clip | Frames per step @24 / @30 fps | Step length | Vertical hip bob | Notes |
|---|---|---|---|---|
| Slow walk | 16 / 20 | 0.35 H | 1 % H | long stance, low arm swing |
| Normal walk | 12 / 15 | 0.40–0.45 H | 1.5–2.5 % H | ~1.3–1.4 m/s for an adult; cadence ~110 steps/min |
| Brisk walk | 9–10 / 11–12 | 0.45–0.5 H | 2 % H | more forward lean, bigger arm swing |
| Jog | 7–8 / 9–10 | 0.6–0.8 H | 3 % H | short flight phase |
| Run / sprint | 5–6 / 6–8 | 0.9–1.4 H | 3–5 % H | flight phase, 10–20° lean, arms bent ~90° |
| Stylized walk | 8–12 (on twos) | as design | 3–8 % H | exaggerated bob, holds, CONSTANT interpolation every 2 frames |

**Walk key poses per step** (12-frame step at 24 fps, keys at 1 / 4 / 7 / 10 / 13):
1. **Contact** (f1): front heel touches, legs at maximum spread, hips mid-height, arms opposite at maximum swing.
2. **Down** (f4, ~¼ step): weight lands, front knee bends, hips **lowest**, torso slight forward settle.
3. **Passing** (f7, ½ step): standing leg straight under hips, free foot passes the ankle with the toe lifted, hips rising.
4. **Up** (f10, ~¾ step): push-off on the ball of the back foot, hips **highest**, front leg reaching.
5. **Contact** (f13) = mirror of f1. The cycle's second half is the mirror (`Action.flip_with_pose(object)` exists in 5.2, and pose copy/paste-flipped also works).

Recipe from code: key the 5 poses of step 1 on hips (loc Z bob, rot Z twist ±3–5°, rot Y tilt ±2–4° toward the standing leg), legs via IK controllers (planted = same world position through stance), then mirror for step 2. Set feet LINEAR during stance and BEZIER in swing. Overlap: the chest counter-rotates the hips, and the head settles 1–2 frames after the hips (offset keys, don't duplicate them).

**Run**: contact → down (deeper) → push-off → **flight** (both feet off, hips highest ~⅓ into the step) → contact. Flight phase shows in `rig_check.py`'s foot gate as frames where neither foot is in stance.

**Idle**: 2–4 s loop (48–96 f @24). Breathing 12–20 breaths/min → one breath in 3–5 s; chest rot 1–2°, shoulders rise 3–5 mm. Add an asymmetric weight shift (hips 1–2 cm toward the loaded leg), and never animate both arms identically. Keep amplitude small enough that the loop seam is invisible.

**Spacing / ease**: slow in/out (BEZIER) for organic starts and stops. Keep constant spacing (LINEAR) for mechanical motion and the travel channel of root motion. Holds are two equal keys 3–6 frames apart plus a tiny drift ("moving hold"), or the pose dies.

**Looping** (must be true in the keys, because exporters bake):
- Key the first pose again on the end frame (`frame_end` = start + cycle length) and set the manual range to include it. `rig_check.py` compares `frame_start` vs `frame_end`, requiring ≤ 0.5° per bone and ≤ 0.01 H relative position.
- Make tangents match across the seam: use Cycle-Aware Keying (`INSERTKEY_CYCLE_AWARE`) or a CYCLES modifier while editing so auto handles see the wrap. Without it the curve flattens at the seam and a hitch shows.
- Whether an engine drops the duplicate last frame is engine-specific [unverified]. Test one loop in the engine.

**Root motion vs in-place**:

| | Root motion | In-place |
|---|---|---|
| Travel lives in | `root` bone (preferred) or hips horizontal, or the armature object | nothing: hips XY ≈ constant |
| Planted foot in world | stationary | slides backward at the walk speed |
| Engine moves the character by | extracting root travel | its own capsule speed |
| `rig_check.py` | `allow_root_motion=True`, `root_bone="root"` (or hip travel), `foot_mode="world"` | `foot_mode="in_place"`: reports stance speed m/s |
| Foot sliding appears when | the root channel isn't linear or feet aren't pinned | engine speed ≠ stance speed |

Measured with the gate: a forward walk (1.2 m per 24-frame cycle) fails the loop gate without root motion (hip travel 0.75 H) and passes with `allow_root_motion=True` (residual 0.0 H, speed 1.2 m/s). The same walk in place reports stance speed 1.2 m/s, which is the value to type into the engine's move speed. Keep the root bone at the origin and keyed LINEAR along +Y/−Y. Turning travel isn't compensated by the gate.

**Stylized vs realistic**: stylized means stronger bob and squash (bone scale needs engine support: check scale curves survive re-import), holds and smears, poses on twos (CONSTANT keys every 2 frames; export with `bake_anim_step=1` so steps stay crisp). Realistic means arcs from reference or mocap, subtle overlap, on ones, no scale. Never mix the two timings in one clip set.

## 5. Exporting clips: FBX, glTF, engines

`scripts/export_actions.py` stages the clips, exports with a preset, restores the scene, re-imports each file in a fresh `blender -b --factory-startup`, and fails on missing clips, duration drift, wrong bone count, leaf bones, shape-key loss or leakage, and unexpected extra clips.

| Option (5.2 RNA, verified) | FBX `export_scene.fbx` | glTF `export_scene.gltf` |
|---|---|---|
| Bake/sample | `bake_anim=True`, `bake_anim_step=1.0`, `bake_anim_simplify_factor` (0 = no simplify), `bake_anim_force_startend_keying=True` | `export_force_sampling=True`, `export_frame_step=1`, `export_optimize_animation_size` |
| Which clips | `bake_anim_use_nla_strips` (one take per unmuted strip), `bake_anim_use_all_actions` (every action whose F-curve paths all resolve on the object) | `export_animation_mode` = `ACTIONS` / `ACTIVE_ACTIONS` / `NLA_TRACKS` / `SCENE` / `BROADCAST`; `export_merge_animation` = `ACTION` / `NLA_TRACK` / `NONE` |
| Bones | `use_armature_deform_only`, `add_leaf_bones` (default **True**), `primary_bone_axis='Y'`, `secondary_bone_axis='X'`, `armature_nodetype` | `export_def_bones`, `export_leaf_bone`, `export_rest_position_armature`, `export_armature_object_remove`, `export_hierarchy_flatten_bones` |
| Skin / morph | `use_mesh_modifiers` | `export_skins`, `export_influence_nb=4`, `export_all_influences`, `export_morph*` |
| Traps | NLA takes only mute/unmute **Object** strips, so Key strips keep playing in every take (exporter source) | `export_anim_single_armature` (default **True**) exports **every** action in the file for a single armature |

Measured round trip (2 deform + 1 control bone, `Walk` with a KEY slot, `Idle`, 30 fps):
- `add_leaf_bones=True` + all bones → 5 bones re-imported (`upper_end`, `CTRL_aim_end`) vs 2 expected.
- Default glTF export shipped an unrelated action keyed on another rig as a third clip. `export_anim_single_armature=False` removes it.
- FBX NLA-strip export with overlapping Key strips put Walk's blink curve into the Idle take. Clips laid end to end with strip extrapolation `NOTHING` fixed it (done by the script).
- FBX `bake_anim_use_all_actions` dropped Walk's shape-key curve (KEY slot paths don't resolve on the object), and a Key with an active action leaked blink into every take. Use NLA-strip mode for clips with face animation.
- New FBX importer (`wm.fbx_import`): one action per take named `Walk`, with slots `OBRig` + `KEKey`. Legacy `import_scene.fbx`: separate `Rig|Walk` and `Key|Walk` actions. Both set scene fps to 30.
- glTF import does **not** set scene fps: a 30 fps clip re-imported into a 24 fps scene landed on frames 0.8–24.8 (duration still 1.0 s). Set the scene fps before importing. Presets use `export_anim_slide_to_zero=True`.
- **Rigify**: export `DEF-` bones only (`use_armature_deform_only` / `export_def_bones`). The generated DEF chain is parented through ORG/MCH bones, so check the re-imported hierarchy is a clean deform tree [unverified: exporter re-parenting]. Bake constraints or IK to the DEF bones (`bpy.ops.nla.bake(visual_keying=True, only_selected=…, bake_types={'POSE'})`) when the controls aren't exported.

Shape-key-only clips (a face mesh with no armature: `scripts/export_actions.py --meshes Face …` runs without `--armature`), morph-target options, `--shape-actions` pairing and `export_check.py --inspect`: `shape-keys-and-visemes.md` §6.

Engine notes. Blender-side settings are in the script's presets; engine-side behaviour is **[unverified]**:

| Engine | Format / preset | Engine side [unverified] |
|---|---|---|
| Unity | FBX, `unity` (`FBX_SCALE_ALL`, −Z forward / Y up, deform only, no leaf bones) | Rig tab: Humanoid (Avatar, retargeting) or Generic (creatures); Root node = hips/root; per clip Loop Time / Loop Pose and "Bake Into Pose" for root rotation / Y / XZ; the armature object imports as an extra transform |
| Unreal | FBX, `unreal` (`FBX_SCALE_NONE`, deform only, no leaf bones) | the armature object becomes the root bone named after it, so name it `root`; enable Root Motion on sequences; scale/axis conventions vary by version, so verify with a test import |
| Godot | GLB, `godot` (ACTIONS, merged by action, sampled, morphs) | animations land in an AnimationPlayer; loop via import settings; root motion via AnimationTree's root motion track |
| Web (three.js etc.) | GLB, `web` (deform bones only) | one glTF animation per clip, morph targets by index/name |

## 6. Checks

Turntables: `scripts/shot_setup.py` (`turntable()` / `turntable_check()` — linear keys, render frames s…s+N−1 so the loop doesn't duplicate its first frame).

| Gate | Tool | Pass |
|---|---|---|
| Clip plays | `rig_check.py --action X` | max joint displacement > 1e-3 H, slot assigned |
| Loop | same, `--allow-root-motion` when travelling | pose return ≤ 0.5°, hip residual and relative pose ≤ 0.01 H |
| Foot contact | `--foot-bones … --foot-mode world/in_place` | stance slide ≤ 0.01 H; in-place stance speed = engine speed |
| Shape keys, lids, lip-sync | `shapekey_check.py`, `lipsync_keys.py` gates | `shape-keys-and-visemes.md` §7 |
| Export | `export_actions.py` | every clip present, animated, duration ±1.5 frames; bone count; no leaf bones; shape keys; no leaks or extras |
| Look | viewport playblast front + side at real speed | arcs, weight, no pops at the loop seam |

## 7. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Action assigned, nothing moves | `action_slot` is None (action keyed on another object) | `ad.action_slot = ad.action_suitable_slots[0]`, or run `rig_check.py`, which assigns it |
| `AttributeError: 'Action' object has no attribute 'fcurves'` | legacy 4.3 code on 5.x | `anim_utils.action_get_channelbag_for_slot(act, slot).fcurves` |
| Loop hitches at the seam | end pose ≠ start, or handles not cycle-aware | duplicate first key on the end frame; Cycle-Aware Keying; `rig_check` loop gate |
| Walk loop "fails" but looks fine | intended root motion | `allow_root_motion=True`, key the root bone LINEAR |
| Feet skate in engine | in-place stance speed ≠ capsule speed, or root curve eased | use the gate's `stance_speed_m_per_s`; LINEAR travel |
| Extra `_end` bones / wrong bone count in engine | FBX `add_leaf_bones` default True; control bones exported | `add_leaf_bones=False`, deform only |
| Extra clips in the GLB | `export_anim_single_armature=True` | set False; export via NLA-staged clips |
| Blink/visemes play in every FBX clip | Key NLA strips aren't muted per take | stage clips end to end, extrapolation NOTHING (`export_actions.py`) |
| glTF clip on sub-frames after import | importer keeps scene fps | set scene fps first; export slide-to-zero |

Shape-key failures (lid cutting the eyeball mid-blink, asymmetric mirrored keys, unmasked sculpts, new keys at value 1.0, morph-target export, lip-sync timing): `shape-keys-and-visemes.md` §8.
