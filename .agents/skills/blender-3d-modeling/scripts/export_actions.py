"""Export several animation clips (actions) of one armature + its skinned meshes -- or shape-key-only clips of meshes
without an armature -- to FBX and/or glTF with engine presets, then re-import every file in a fresh Blender process
and report what actually arrived: clip count, clip durations, bone count, leaf bones, shape key count, shape-key
F-curves, animated channels.

Headless / CLI (prints one line: EXPORT_ACTIONS <json>):
    blender -b rig.blend --python export_actions.py -- --armature Rig [--meshes Body,Face] [--actions "Walk,Run,Idle*"]
        [--shape-actions '{"Walk": "Walk_face"}'] [--preset unity|unreal|godot|web|generic] [--formats fbx,glb]
        [--out //export] [--name Hero] [--fbx-mode nla|all_actions] [--importer new|legacy|both] [--no-verify]
        [--fbx '{"add_leaf_bones": true}'] [--gltf '{"export_def_bones": true}']
    blender -b face.blend --python export_actions.py -- --meshes Face --actions "Talk,Viseme_*" --preset web
        (shape-key-only mode: no --armature and the meshes are bound to none)
Live (Blender:execute_blender_code): set before exec
    EXPORT_ACTIONS_OPTS = {"armature": "Rig", "actions": ["Walk", "Idle"], "preset": "godot", "out": "//export"}
    EXPORT_ACTIONS_OPTS = {"meshes": ["Face"], "actions": ["Talk"], "preset": "web", "out": "//export"}
    -> `result` dict
Without EXPORT_ACTIONS_OPTS the file only defines export_actions / verify helpers.

Modes (result["mode"]):
  armature    --armature, else the armature the --meshes are bound to (Armature modifier / parent), else the scene's
              first armature; meshes default to the ones bound to it. Clips: --actions patterns, else every action with
              a slot that animates its bones. No armature and no meshes -> note "armature not found".
  shape_keys  --meshes without --armature and none of them is bound to an armature: the meshes are exported alone
              with the Key-datablock actions named by --actions (else every action with a KEY slot for one of the
              meshes' Keys); --shape-actions still maps clip -> Key action. Same presets and NLA staging (on the Key
              animation_data). For FBX the first mesh object additionally carries one temporary object-level NLA strip
              per clip whose only job is to define the take window (the FBX exporter opens takes from Object strips
              only) -- measured: without it a Key-only clip yields no FBX take at all.

How clips are exported (Blender 4.4+ slotted actions):
  * one clip = one Action. Its OBJECT slot drives the armature; a KEY slot in the same action (or an action given in
    shape_actions={"Walk": "Walk_face"}) drives the shape keys of the bound meshes.
  * for the export each clip is placed on its own temporary NLA track named after the clip (armature and Key), the
    active action is cleared, pre-existing tracks are muted; afterwards everything is restored and the temporary
    tracks are removed. FBX uses "NLA Strips" takes; glTF uses Animation mode "Actions" merged by action.
  * fbx_mode="all_actions" instead uses the FBX "All Actions" option (exports EVERY compatible action in the file).
Verification runs `blender -b --factory-startup` on each exported file (FBX with the new C++ importer
`wm.fbx_import`, the legacy add-on importer, or both; the child empties its scene by deleting data-blocks before the
import) and compares against the source: every clip present, animated bone curves when the source clip had bone
F-curves, duration within 1.5 frames, bone count == exported bones (deform-only when the preset says so; no armature
at all in shape_keys mode), no leaf bones when disabled, shape key count per mesh and shape-key F-curves
(`key_blocks[...]` paths): checks.shape_keys reports `shape_keys` (re-imported total) and `shape_key_curves`, each
clip row `shape_key_curves` / `shape_key_animated_curves`.
Limitations: one armature per call; object-level (non-bone) animation of the armature is exported but not compared;
clip name matching in the re-import accepts `Clip`, `Armature|Clip`, `Clip_Armature` style names; shape-key clips
are compared by curve presence and animation, not by sampled weights.
"""
import bpy, json, math, os, subprocess, sys, tempfile

FBX_COMMON = dict(object_types={'ARMATURE', 'MESH'}, use_mesh_modifiers=True, mesh_smooth_type='FACE',
                  add_leaf_bones=False, use_armature_deform_only=True, primary_bone_axis='Y', secondary_bone_axis='X',
                  armature_nodetype='NULL', bake_anim=True, bake_anim_use_all_bones=True, bake_anim_use_nla_strips=True,
                  bake_anim_use_all_actions=False, bake_anim_force_startend_keying=True, bake_anim_step=1.0,
                  bake_anim_simplify_factor=0.0, axis_forward='-Z', axis_up='Y')
GLTF_COMMON = dict(export_animations=True, export_animation_mode='ACTIONS', export_merge_animation='ACTION',
                   export_force_sampling=True, export_frame_step=1, export_skins=True, export_influence_nb=4,
                   export_morph=True, export_morph_normal=True, export_morph_animation=True, export_def_bones=False,
                   export_leaf_bone=False, export_anim_single_armature=False, export_reset_pose_bones=True,
                   export_rest_position_armature=True, export_optimize_animation_size=True, export_bake_animation=False,
                   export_anim_slide_to_zero=True)
# export_anim_single_armature=True (exporter default) exports EVERY action in the file on a single-armature export,
# ignoring the chosen clip list -- measured: an unrelated action keyed on another rig was exported as a clip.
PRESETS = {
    # Blender-side settings only; engine-side import settings live in references/animation.md section 5.
    "unity": {"formats": ["fbx"], "fbx": dict(FBX_COMMON, apply_scale_options='FBX_SCALE_ALL'), "gltf": dict(GLTF_COMMON)},
    "unreal": {"formats": ["fbx"], "fbx": dict(FBX_COMMON, apply_scale_options='FBX_SCALE_NONE'), "gltf": dict(GLTF_COMMON),
               "warn_armature_name": "root"},
    "godot": {"formats": ["glb"], "fbx": dict(FBX_COMMON), "gltf": dict(GLTF_COMMON)},
    "web": {"formats": ["glb"], "fbx": dict(FBX_COMMON), "gltf": dict(GLTF_COMMON, export_def_bones=True)},
    "generic": {"formats": ["fbx", "glb"], "fbx": dict(FBX_COMMON), "gltf": dict(GLTF_COMMON)},
}

VERIFY_SRC = r'''
import bpy, json, sys
args = sys.argv[sys.argv.index("--") + 1:]
path, importer = args[0], args[1]
# fresh process (--factory-startup): empty the default scene by deleting data-blocks; never wm.read_factory_settings()
bpy.data.batch_remove([i for t in ("objects", "meshes", "armatures", "actions", "materials", "images", "cameras", "lights",
                                   "collections") for i in getattr(bpy.data, t)])
res = {"file": path, "importer": importer, "session_empty": not (bpy.data.objects or bpy.data.actions or bpy.data.meshes)}
try:
    if path.lower().endswith(".fbx"):
        if importer == "legacy": bpy.ops.import_scene.fbx(filepath=path)
        else: bpy.ops.wm.fbx_import(filepath=path)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
except Exception as e:
    res["error"] = f"{type(e).__name__}: {e}"
from bpy_extras import anim_utils
scn = bpy.context.scene
res["scene_fps"] = scn.render.fps / scn.render.fps_base
res["armatures"] = [{"name": o.name, "bones": len(o.data.bones), "bone_names": [b.name for b in o.data.bones][:300]}
                    for o in bpy.data.objects if o.type == 'ARMATURE']
res["meshes"] = [{"name": o.name, "shape_keys": (len(o.data.shape_keys.key_blocks) - 1) if o.data.shape_keys else 0,
                  "shape_key_names": [k.name for k in o.data.shape_keys.key_blocks[1:]] if o.data.shape_keys else []}
                 for o in bpy.data.objects if o.type == 'MESH']
acts = []
for a in bpy.data.actions:
    slots = []
    for s in a.slots:
        cb = anim_utils.action_get_channelbag_for_slot(a, s)
        fcs = list(cb.fcurves) if cb else []
        anim = 0; bone_anim = 0; key_anim = 0; key_curves = 0
        for f in fcs:
            if f.data_path.startswith("key_blocks"): key_curves += 1
            vals = [k.co[1] for k in f.keyframe_points]
            if len(vals) > 1 and max(vals) - min(vals) > 1e-5:
                anim += 1
                if f.data_path.startswith("pose.bones"): bone_anim += 1
                if f.data_path.startswith("key_blocks"): key_anim += 1
        slots.append({"id": s.identifier, "type": s.target_id_type, "fcurves": len(fcs), "animated": anim,
                      "bone_animated": bone_anim, "key_animated": key_anim, "key_curves": key_curves})
    acts.append({"name": a.name, "frame_range": list(a.frame_range), "slots": slots})
res["actions"] = acts
res["shape_key_curves"] = sum(s["key_curves"] for a in acts for s in a["slots"])
nla = {}
for idb in list(bpy.data.objects) + list(bpy.data.shape_keys):
    if idb.animation_data:
        nla[idb.name] = {"tracks": [t.name for t in idb.animation_data.nla_tracks],
                         "action": idb.animation_data.action.name if idb.animation_data.action else None}
res["animation_data"] = nla
print("EXPORT_ACTIONS_VERIFY " + json.dumps(res))
'''


def _abspath(p):
    return os.path.abspath(bpy.path.abspath(p)) if p.startswith("//") else os.path.abspath(p)


def _bound_meshes(arm):
    return [o for o in bpy.data.objects if o.type == 'MESH' and (
        any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers) or o.parent == arm)]


def _bone_slot(action, arm):
    """Slot of `action` that animates `arm`: identifier OB<name>, else the OBJECT slot with most matching bone curves."""
    from bpy_extras import anim_utils
    best, best_n = None, 0
    names = {b.name for b in arm.data.bones}
    for s in action.slots:
        if s.target_id_type not in ('OBJECT', 'UNSPECIFIED'): continue
        cb = anim_utils.action_get_channelbag_for_slot(action, s)
        if not cb: continue
        n = sum(1 for f in cb.fcurves if f.data_path.startswith('pose.bones["') and f.data_path.split('"')[1] in names)
        if s.identifier == "OB" + arm.name and n: return s, n
        if n > best_n: best, best_n = s, n
    return best, best_n


def _key_slot(action, key):
    ks = [s for s in action.slots if s.target_id_type in ('KEY', 'UNSPECIFIED')]
    for s in ks:
        if s.identifier == "KE" + key.name: return s
    kk = [s for s in ks if s.target_id_type == 'KEY']
    return kk[0] if len(kk) == 1 else None


def _resolve_actions(arm, actions, keys=()):
    """Explicit patterns win; else (armature mode) actions animating the armature's bones, (shape-key mode, arm None)
    actions with a KEY slot for one of the meshes' Key data-blocks."""
    import fnmatch
    if isinstance(actions, str): actions = [a.strip() for a in actions.split(",") if a.strip()]
    pool = list(bpy.data.actions)
    if actions:
        chosen = []
        for pat in actions:
            hits = [a for a in pool if fnmatch.fnmatchcase(a.name, pat)]
            chosen += [a for a in hits if a not in chosen]
            if not hits: chosen.append(pat)  # missing: reported
        return chosen
    if arm is not None:
        return [a for a in pool if _bone_slot(a, arm)[1] > 0]
    return [a for a in pool if any(_key_slot(a, k) is not None for k in keys)]


class _State:
    """Remembers and restores animation assignments, NLA mute flags, selection and frame."""

    def __init__(self, ids, scene):
        self.scene = scene; self.frame = scene.frame_current; self.ids = []
        self.sel = {o: o.select_get() for o in scene.objects}; self.active = bpy.context.view_layer.objects.active
        for idb in ids:
            ad = idb.animation_data
            self.ids.append((idb, ad is not None, ad.action if ad else None, ad.action_slot if ad else None,
                             ad.use_nla if ad else None, {t.name: t.mute for t in ad.nla_tracks} if ad else {}))
        self.new_tracks = []

    def restore(self):
        for idb, had, act, slot, use_nla, mutes in self.ids:
            ad = idb.animation_data
            if ad is None: continue
            for t in list(ad.nla_tracks):
                if t in [nt for i, nt in self.new_tracks if i == idb]: ad.nla_tracks.remove(t)
            for t in ad.nla_tracks:
                if t.name in mutes: t.mute = mutes[t.name]
            ad.action = act
            if act is not None and slot is not None: ad.action_slot = slot
            if use_nla is not None: ad.use_nla = use_nla
            if not had: idb.animation_data_clear()
        for o, s in self.sel.items():
            try: o.select_set(s)
            except Exception: pass
        bpy.context.view_layer.objects.active = self.active
        self.scene.frame_set(self.frame)


def _stage_clips(arm, meshes, clips, shape_actions, state, report, gap=10, extra_ids=()):
    """One NLA track per clip, clips laid end to end on the timeline with extrapolation NOTHING.
    Sequential layout matters for FBX: its NLA-strip take loop mutes/unmutes Object strips only, so Key (shape key)
    strips keep playing; with non-overlapping windows each take only sees its own shape key strip.
    arm may be None (shape-key mode): only the Key strips are staged. extra_ids: further IDs whose active action is
    cleared and whose tracks are muted for the export (the window object of the shape-key mode)."""
    ad = arm.animation_data_create() if arm is not None else None
    keys = [m.data.shape_keys for m in meshes if m.data.shape_keys]
    for idb in ([arm] if arm is not None else []) + list(extra_ids) + keys:
        if idb.animation_data:
            idb.animation_data.action = None
            for t in idb.animation_data.nla_tracks: t.mute = True
    cursor = None
    for act in clips:
        slot, n = _bone_slot(act, arm) if arm is not None else (None, 0)
        row = {"clip": act.name, "frame_range": list(act.frame_range), "bone_curves": n,
               "slot": slot.identifier if slot else None, "key_slots": {}}
        a0, a1 = act.frame_range
        start = int(math.floor(a0)) if cursor is None else cursor
        cursor = start + int(math.ceil(a1 - a0)) + gap
        row["staged_start"] = start
        if slot is not None:
            tr = ad.nla_tracks.new(); tr.name = act.name; state.new_tracks.append((arm, tr))
            st = tr.strips.new(act.name, start, act); st.action_slot = slot; st.name = act.name
            st.extrapolation = 'NOTHING'
        elif arm is not None:
            row["warning"] = "no slot animates this armature's bones"
        for key in keys:
            src = bpy.data.actions.get(shape_actions.get(act.name, "")) if shape_actions else None
            src = src or act
            ks = _key_slot(src, key)
            if ks is None: continue
            kad = key.animation_data_create()
            tr = kad.nla_tracks.new(); tr.name = act.name; state.new_tracks.append((key, tr))
            st = tr.strips.new(act.name, start, src); st.action_slot = ks; st.name = act.name
            st.extrapolation = 'NOTHING'
            row["key_slots"][key.user.name] = ks.identifier
        report.append(row)


def _stage_windows(obj, clips, staged, state, warnings):
    """Shape-key mode + FBX: one temporary object-level NLA strip per clip on `obj` (same start as the Key strip).
    The FBX exporter opens one take per un-muted Object strip and bakes every animated value inside its window,
    shape keys included; Key strips alone open no take (measured). The strip carries the Key action, which has no
    OBJECT slot, so it moves nothing -- it only defines the window."""
    ad = obj.animation_data_create()
    starts = {r["clip"]: r["staged_start"] for r in staged}
    done = {}
    for act in clips:
        if act.name not in starts: continue
        try:
            tr = ad.nla_tracks.new(); tr.name = act.name; state.new_tracks.append((obj, tr))
            st = tr.strips.new(act.name, starts[act.name], act); st.name = act.name; st.extrapolation = 'NOTHING'
            # no OBJECT slot -> Blender gives the strip a 1-frame range (measured: 1-frame take); stretch it to the clip
            a0, a1 = act.frame_range
            length = max(float(a1 - a0), 1.0)
            st.action_frame_start, st.action_frame_end = float(a0), float(a0) + length
            st.frame_end = starts[act.name] + length
            done[act.name] = [st.frame_start, st.frame_end]
        except Exception as ex:
            warnings.append(f"FBX take window strip for clip '{act.name}' on {obj.name} failed: {type(ex).__name__}: {ex}")
    for r in staged:
        if r["clip"] in done: r["fbx_window_strip"] = {"object": obj.name, "frames": done[r["clip"]]}
    return list(done)


def _run_verify(path, importer):
    fd, vpath = tempfile.mkstemp(suffix="_verify_import.py"); os.close(fd)
    with open(vpath, "w", encoding="utf-8") as f: f.write(VERIFY_SRC)
    try:
        p = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python", vpath, "--", path, importer],
                           capture_output=True, text=True, timeout=600)
        for line in p.stdout.splitlines():
            if line.startswith("EXPORT_ACTIONS_VERIFY "): return json.loads(line[len("EXPORT_ACTIONS_VERIFY "):])
        return {"file": path, "importer": importer, "error": "no verify line", "stderr": p.stderr[-800:], "stdout": p.stdout[-800:]}
    finally:
        try: os.remove(vpath)
        except OSError: pass


def _clip_matches(action_name, clip, arm_name):
    if action_name == clip: return True
    for sep in "|_ .":
        if action_name.startswith(clip + sep) or action_name.endswith(sep + clip) or (sep + clip + sep) in action_name:
            return True
    return False


def _compare(v, expect):
    checks = {}
    if v.get("error"): checks["import_ok"] = {"pass": False, "error": v["error"]}; return checks
    fps = v.get("scene_fps") or expect["fps"]
    # clips
    clip_rows, missing = [], []
    for c in expect["clips"]:
        hits = [a for a in v["actions"] if _clip_matches(a["name"], c["clip"], expect["armature"])]
        bone_anim = sum(s["bone_animated"] for a in hits for s in a["slots"])
        key_anim = sum(s["key_animated"] for a in hits for s in a["slots"])
        key_curves = sum(s.get("key_curves", 0) for a in hits for s in a["slots"])
        src_dur_s = (c["frame_range"][1] - c["frame_range"][0]) / expect["fps"]
        durs = [(a["frame_range"][1] - a["frame_range"][0]) / fps for a in hits if any(s["animated"] for s in a["slots"])]
        dur_ok = bool(durs) and all(abs(d - src_dur_s) <= 1.5 / expect["fps"] for d in durs)
        want_keys = bool(c.get("key_slots"))
        # bone curves are required only when the SOURCE clip had some (shape-key-only clips have none)
        want_bones = c.get("bone_curves", 1 if expect.get("armature") else 0) > 0
        issues = []
        if not hits: issues.append("clip not found in file")
        elif want_bones and bone_anim == 0: issues.append("no animated bone curves")
        if hits and not dur_ok: issues.append("duration mismatch")
        if want_keys and key_anim == 0: issues.append("shape key animation missing")
        if not want_keys and key_anim > 0: issues.append("shape key animation leaked into a clip that has none")
        clip_rows.append({"clip": c["clip"], "pass": not issues, "issues": issues, "imported_actions": [a["name"] for a in hits],
                          "bone_animated_curves": bone_anim, "shape_key_curves": key_curves, "shape_key_animated_curves": key_anim,
                          "source_duration_s": round(src_dur_s, 4), "imported_duration_s": [round(d, 4) for d in durs]})
        if issues: missing.append(c["clip"])
    matched = {a["name"] for c in expect["clips"] for a in v["actions"] if _clip_matches(a["name"], c["clip"], expect["armature"])}
    extra = [a["name"] for a in v["actions"] if a["name"] not in matched]
    checks["clips"] = {"pass": not missing, "failed": missing, "rows": clip_rows,
                       "imported_action_count": len(v["actions"])}
    checks["no_unexpected_clips"] = {"pass": not extra, "unexpected": extra[:20]}
    arms = v["armatures"]
    nb = arms[0]["bones"] if arms else 0
    leaf = [n for a in arms for n in a["bone_names"] if n.endswith(("_end", "_leaf"))]
    if expect.get("armature") is None:  # shape-key mode: nothing may have grown an armature
        checks["bones"] = {"pass": not arms, "expected": 0, "imported": nb, "armatures": len(arms), "leaf_like_bones": leaf[:20]}
    else:
        checks["bones"] = {"pass": len(arms) == 1 and nb == expect["bones"], "expected": expect["bones"], "imported": nb,
                           "armatures": len(arms), "leaf_like_bones": leaf[:20]}
    if not expect["leaf_bones"]:
        checks["no_leaf_bones"] = {"pass": not leaf, "leaf_like_bones": leaf[:20]}
    sk_rows, sk_ok = [], True
    for name, n in expect["shape_keys"].items():
        got = [m for m in v["meshes"] if m["name"] == name] or ([m for m in v["meshes"] if m["shape_keys"]] if len(expect["shape_keys"]) == 1 else [])
        g = got[0]["shape_keys"] if got else 0
        sk_rows.append({"mesh": name, "expected": n, "imported": g}); sk_ok &= g == n
    checks["shape_keys"] = {"pass": sk_ok, "rows": sk_rows, "expected": sum(expect["shape_keys"].values()),
                            "shape_keys": sum(r["imported"] for r in sk_rows),
                            "shape_key_curves": sum(r["shape_key_curves"] for r in clip_rows)}
    return checks


def export_actions(armature=None, meshes=None, actions=None, shape_actions=None, preset="generic", formats=None,
                   out="//export", name=None, fbx_mode="nla", importer="both", verify=True, fbx=None, gltf=None):
    scn = bpy.context.scene
    out_rep = {"blender": bpy.app.version_string, "preset": preset}
    if isinstance(meshes, str): meshes = [m for m in meshes.split(",") if m]
    mesh_objs = [bpy.data.objects[m] for m in meshes] if meshes else []
    if armature:
        arm = bpy.data.objects.get(armature)
        if arm is None or arm.type != 'ARMATURE':
            out_rep["pass"] = None; out_rep["note"] = "armature not found"; return out_rep
    elif mesh_objs:  # the armature the meshes are bound to; none -> shape-key-only mode
        arm = next((m.object for o in mesh_objs for m in o.modifiers if m.type == 'ARMATURE' and m.object), None) or \
              next((o.parent for o in mesh_objs if o.parent and o.parent.type == 'ARMATURE'), None)
    else:
        arm = next((o for o in scn.objects if o.type == 'ARMATURE'), None)
        if arm is None:
            out_rep["pass"] = None; out_rep["note"] = "armature not found"; return out_rep
    mode = "armature" if arm is not None else "shape_keys"
    out_rep["mode"] = mode
    if arm is not None and not mesh_objs: mesh_objs = _bound_meshes(arm)
    keys = [m.data.shape_keys for m in mesh_objs if m.data.shape_keys]
    if arm is None and not keys:
        out_rep["pass"] = None; out_rep["note"] = "armature not found and the given meshes have no shape keys"; return out_rep
    P = PRESETS[preset]
    formats = formats or P["formats"]
    if isinstance(formats, str): formats = [f.strip().lower() for f in formats.split(",")]
    fbx_opts = dict(P["fbx"], **(fbx or {})); gltf_opts = dict(P["gltf"], **(gltf or {}))
    if fbx_mode == "all_actions": fbx_opts.update(bake_anim_use_nla_strips=False, bake_anim_use_all_actions=True)
    clips = _resolve_actions(arm, actions, keys)
    out_rep["missing_actions"] = [c for c in clips if isinstance(c, str)]
    clips = [c for c in clips if not isinstance(c, str)]
    warnings = []
    if fbx_mode == "all_actions" and "fbx" in formats and any(s.target_id_type == 'KEY' for c in clips for s in c.slots):
        warnings.append("FBX all_actions validates F-curve paths on the object only: shape-key (KEY slot) animation "
                        "is not exported per clip (measured). Use fbx_mode='nla'.")
    if arm is not None:
        if P.get("warn_armature_name") and arm.name != P["warn_armature_name"]:
            warnings.append(f"armature object is '{arm.name}'; Unreal turns the armature node into a root bone named after it "
                            f"(name it '{P['warn_armature_name']}') [engine side unverified]")
        if any(abs(s - 1) > 1e-6 for s in arm.scale) or any(abs(r) > 1e-6 for r in arm.rotation_euler):
            warnings.append("armature object has unapplied rotation/scale")
    fps = scn.render.fps / scn.render.fps_base
    out_dir = _abspath(out); os.makedirs(out_dir, exist_ok=True)
    base = name or (arm.name if arm is not None else mesh_objs[0].name)
    window_obj = mesh_objs[0] if (arm is None and "fbx" in formats and fbx_mode != "all_actions") else None
    state = _State(([arm] if arm is not None else []) + ([window_obj] if window_obj is not None else []) + keys, scn)
    staged, files = [], []
    try:
        if fbx_mode != "all_actions" or any(f in ("glb", "gltf") for f in formats):
            _stage_clips(arm, mesh_objs, clips, shape_actions or {}, state, staged,
                         extra_ids=[window_obj] if window_obj is not None else ())
        for o in scn.objects: o.select_set(False)
        for o in ([arm] if arm is not None else []) + mesh_objs: o.select_set(True)
        bpy.context.view_layer.objects.active = arm if arm is not None else mesh_objs[0]
        for f in sorted(formats, key=lambda x: x == "fbx"):  # fbx last: the shape-key mode adds its window strips first
            if f == "fbx":
                if window_obj is not None and staged: _stage_windows(window_obj, clips, staged, state, warnings)
                path = os.path.join(out_dir, base + ".fbx")
                bpy.ops.export_scene.fbx(filepath=path, use_selection=True, **fbx_opts)
            elif f in ("glb", "gltf"):
                path = os.path.join(out_dir, base + (".glb" if f == "glb" else ".gltf"))
                bpy.ops.export_scene.gltf(filepath=path, use_selection=True,
                                          export_format='GLB' if f == "glb" else 'GLTF_SEPARATE', **gltf_opts)
            else:
                warnings.append(f"unknown format {f}"); continue
            files.append(path)
    finally:
        state.restore()
    deform_only = fbx_opts.get("use_armature_deform_only", False)
    expect = {"armature": arm.name if arm is not None else None, "fps": fps,
              "clips": staged or [{"clip": c.name, "frame_range": list(c.frame_range),
                                   "bone_curves": _bone_slot(c, arm)[1] if arm is not None else 0} for c in clips],
              "shape_keys": {m.name: len(m.data.shape_keys.key_blocks) - 1 for m in mesh_objs if m.data.shape_keys}}
    out_rep.update({"armature": arm.name if arm is not None else None, "meshes": [m.name for m in mesh_objs], "fps": fps, "clips": expect["clips"],
                    "files": files, "fbx_options": {k: (sorted(v) if isinstance(v, set) else v) for k, v in fbx_opts.items()} if "fbx" in formats else None,
                    "gltf_options": gltf_opts if any(f in ("glb", "gltf") for f in formats) else None, "warnings": warnings})
    if not verify:
        out_rep["pass"] = None; out_rep["note"] = "verification skipped"; return out_rep
    results, all_ok = [], True
    for path in files:
        is_fbx = path.lower().endswith(".fbx")
        imps = (["new", "legacy"] if importer == "both" else [importer]) if is_fbx else ["gltf"]
        for imp in imps:
            v = _run_verify(path, imp)
            e = dict(expect)
            if arm is None:
                e["bones"] = 0
                e["leaf_bones"] = fbx_opts.get("add_leaf_bones", False) if is_fbx else gltf_opts.get("export_leaf_bone", False)
            elif is_fbx:
                e["bones"] = sum(1 for b in arm.data.bones if b.use_deform) if deform_only else len(arm.data.bones)
                e["leaf_bones"] = fbx_opts.get("add_leaf_bones", False)
            else:
                e["bones"] = sum(1 for b in arm.data.bones if b.use_deform) if gltf_opts.get("export_def_bones") else len(arm.data.bones)
                e["leaf_bones"] = gltf_opts.get("export_leaf_bone", False)
            checks = _compare(v, e)
            ok = all(c.get("pass") for c in checks.values())
            all_ok &= ok
            results.append({"file": os.path.basename(path), "importer": imp, "pass": ok, "checks": checks,
                            "imported_actions": [{"name": a["name"], "frame_range": [round(x, 2) for x in a["frame_range"]],
                                                  "slots": [s["id"] for s in a["slots"]]} for a in v.get("actions", [])],
                            "imported_fps": v.get("scene_fps")})
    out_rep["verify"] = results
    out_rep["pass"] = all_ok and not out_rep["missing_actions"]
    out_rep["summary"] = {r["file"] + ":" + r["importer"]: r["pass"] for r in results}
    return out_rep


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="export_actions.py")
    p.add_argument("--armature"); p.add_argument("--meshes"); p.add_argument("--actions")
    p.add_argument("--shape-actions", help='JSON {"clip": "shape_action"}')
    p.add_argument("--preset", default="generic", choices=sorted(PRESETS)); p.add_argument("--formats")
    p.add_argument("--out", default="//export"); p.add_argument("--name")
    p.add_argument("--fbx-mode", default="nla", choices=["nla", "all_actions"])
    p.add_argument("--importer", default="both", choices=["new", "legacy", "both"])
    p.add_argument("--no-verify", action="store_true"); p.add_argument("--fbx"); p.add_argument("--gltf")
    a = p.parse_args(argv)
    return export_actions(a.armature, a.meshes, a.actions, json.loads(a.shape_actions) if a.shape_actions else None,
                          a.preset, a.formats, a.out, a.name, a.fbx_mode, a.importer, not a.no_verify,
                          json.loads(a.fbx) if a.fbx else None, json.loads(a.gltf) if a.gltf else None)


if "EXPORT_ACTIONS_OPTS" in globals():
    result = export_actions(**EXPORT_ACTIONS_OPTS); print(json.dumps(result.get("summary", result.get("note"))))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("EXPORT_ACTIONS " + json.dumps(result, default=str))
else:
    result = {"defined": ["export_actions", "PRESETS"]}
