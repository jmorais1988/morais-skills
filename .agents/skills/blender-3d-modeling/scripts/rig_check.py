"""Rig readiness gates: bone scale/symmetry, weight normalization/influences/coverage, L3 rigidity, pose sweep,
and action gates (action moves, loops cleanly with or without root motion, foot contact / sliding).

Headless / CLI (prints one line: RIG_CHECK <json>):
    blender -b rig.blend --python rig_check.py -- [--armature Rig] [--action Walk] [--hip-bone hips] [--root-bone root]
        [--allow-root-motion] [--foot-bones foot.L,foot.R] [--foot-mode world|in_place] [--no-sweep]
        [--max-influences 4]
Live (Blender:execute_blender_code): set before exec
    RIG_OPTS = {
        "armature": None,          # armature object name; None = first armature in scene
        "max_influences": 4, "weight_tol": 1e-4,
        "sweep": True,             # pose sweep: flex each deform bone +-45/90 deg about local X and measure the meshes
        "sweep_bones": None,       # subset of bone names; None = all deform bones (slow on dense meshes)
        "action": None,            # action name to prove motion / loop / foot slide
        "hip_bone": None,          # hip/pelvis bone for the loop gate; None = by name (hips/pelvis/hip), else first deform root
        "root_bone": None,         # bone carrying root motion (e.g. "root"); None = armature object travel or hip travel
        "allow_root_motion": False,# True: a clip that travels forward still loops if the pose relative to the travel returns
        "foot_bones": [],          # e.g. ["foot.L", "foot.R"] or IK controllers
        "foot_mode": "world",      # world: planted foot must not move (root motion / stationary); in_place: treadmill
                                   #   feet slide back at constant speed -> residual from a straight-line fit is the slide
        "layer_prop": "layer",     # custom prop naming L0..L6 on meshes; L3 must be single-influence or bone-parented
    }  -> `result` dict. Exec without RIG_OPTS runs with the defaults above (backward compatible).
All thresholds are fractions of figure height H (armature bone Z extent). A gate with missing input reports
'unevaluated', never a pass.
Action assignment: Blender 4.4+ actions are slotted. Assigning an action keyed on another object leaves
animation_data.action_slot = None and nothing moves; this script assigns the slot named OB<armature>, else the first
suitable slot, else the slot with the most matching bone F-curves, and restores the previous action + slot afterwards.
Limitations: root-motion travel is treated as a translation (turning clips are not compensated); foot stance is
"within 2 % H of the foot's lowest point".
"""
import bpy, json, math, sys
from mathutils import Vector

DEFAULTS = {"armature": None, "max_influences": 4, "weight_tol": 1e-4, "sweep": True, "sweep_bones": None,
            "action": None, "hip_bone": None, "root_bone": None, "allow_root_motion": False, "foot_bones": [],
            "foot_mode": "world", "layer_prop": "layer"}
HIP_NAMES = ("hips", "hip", "pelvis", "root_hips")


def pick_hip_bone(arm, name=None):
    if name:
        return arm.pose.bones.get(name)
    for pb in arm.pose.bones:
        n = pb.name.lower().split(":")[-1]
        for pre in ("def-", "def_", "org-", "b_", "bip01_", "bip_"):
            if n.startswith(pre): n = n[len(pre):]
        if n in HIP_NAMES: return pb
    roots = [pb for pb in arm.pose.bones if pb.bone.use_deform and not (pb.parent and pb.parent.bone.use_deform)]
    return roots[0] if roots else (arm.pose.bones[0] if len(arm.pose.bones) else None)


def assign_action(arm, act):
    """Assign action + a slot that animates arm. Returns the slot used (or None)."""
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    if ad.action_slot is None:
        slot = act.slots.get("OB" + arm.name)
        if slot is None and len(ad.action_suitable_slots):
            slot = ad.action_suitable_slots[0]
        if slot is None:
            from bpy_extras import anim_utils
            names = {b.name for b in arm.data.bones}; best = 0
            for s in act.slots:
                cb = anim_utils.action_get_channelbag_for_slot(act, s)
                n = sum(1 for f in cb.fcurves if f.data_path.startswith('pose.bones["') and f.data_path.split('"')[1] in names) if cb else 0
                if n > best: slot, best = s, n
        if slot is not None:
            ad.action_slot = slot
    return ad.action_slot


def _fit_residual(pts):
    """Max xy distance of points from their least-squares straight line in time, and the speed (units/frame)."""
    n = len(pts)
    if n < 3: return 0.0, 0.0
    ts = list(range(n)); tm = sum(ts) / n
    den = sum((t - tm) ** 2 for t in ts) or 1.0
    res = 0.0; vel = []
    for axis in (0, 1):
        vals = [p[axis] for p in pts]; vm = sum(vals) / n
        b = sum((t - tm) * (v - vm) for t, v in zip(ts, vals)) / den
        vel.append(b)
    for t, p in zip(ts, pts):
        dx = p[0] - (sum(q[0] for q in pts) / n + vel[0] * (t - tm))
        dy = p[1] - (sum(q[1] for q in pts) / n + vel[1] * (t - tm))
        res = max(res, math.hypot(dx, dy))
    return res, math.hypot(*vel)


def run_rig_check(opts=None):
    O = dict(DEFAULTS); O.update(opts or {})
    result = {"gates": {}, "unevaluated": []}
    arm = bpy.data.objects.get(O["armature"]) if O["armature"] else next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
    if not arm:
        result["unevaluated"].append("no armature found"); result["summary"] = "no armature found"; return result

    meshes = [o for o in bpy.data.objects if o.type == 'MESH' and (
        any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers) or (o.parent == arm))]
    deform_bones = [b for b in arm.data.bones if b.use_deform]
    zs = [(arm.matrix_world @ b.head_local).z for b in arm.data.bones] + [(arm.matrix_world @ b.tail_local).z for b in arm.data.bones]
    H = (max(zs) - min(zs)) if zs else 1.0
    H = H or 1.0
    result["figure_height_H"] = round(H, 4)
    result["armature"] = arm.name; result["deform_bones"] = len(deform_bones); result["bound_meshes"] = [m.name for m in meshes]

    # --- G: bone scale & armature transform ---
    bad_scale = [pb.name for pb in arm.pose.bones if any(abs(s - 1) > 1e-5 for s in pb.scale)]
    result["gates"]["bone_scale_identity"] = {"pass": not bad_scale, "bones_with_scale": bad_scale}
    result["gates"]["armature_transform"] = {"pass": all(abs(s - 1) < 1e-6 for s in arm.scale) and all(abs(r) < 1e-6 for r in arm.rotation_euler),
                                             "scale": list(arm.scale), "rotation": list(arm.rotation_euler)}

    # --- G: names / symmetry / medial-lateral ---
    names = [b.name for b in arm.data.bones]
    dups = {n for n in names if names.count(n) > 1}
    sym = {"missing_twin": [], "unmirrored": [], "medial_lateral_wrong": []}
    for b in deform_bones:
        if b.name.endswith(".L"):
            tw = arm.data.bones.get(b.name[:-2] + ".R")
            if not tw: sym["missing_twin"].append(b.name); continue
            hl, hr = arm.matrix_world @ b.head_local, arm.matrix_world @ tw.head_local
            tl, tr = arm.matrix_world @ b.tail_local, arm.matrix_world @ tw.tail_local
            if (Vector((-hl.x, hl.y, hl.z)) - hr).length > 0.005 * H or (Vector((-tl.x, tl.y, tl.z)) - tr).length > 0.005 * H:
                sym["unmirrored"].append(b.name)
            if not (hl.x > 0 > hr.x):
                sym["medial_lateral_wrong"].append(b.name)
    result["gates"]["bone_names_unique"] = {"pass": not dups, "duplicates": sorted(dups)}
    result["gates"]["bone_symmetry"] = {"pass": not any(sym.values()), **sym,
                                        "note": "convention: character's left = +X, facing -Y"}

    # --- G: weights ---
    bone_names = {b.name for b in deform_bones}
    wsum_bad = infl_bad = unweighted = 0; l3_bad = []
    per_mesh = []
    for m in meshes:
        gi = {g.index: g.name for g in m.vertex_groups if g.name in bone_names}
        if m.parent_type == 'BONE':
            per_mesh.append({"mesh": m.name, "bone_parented_to": m.parent_bone, "verts": len(m.data.vertices)}); continue
        if not gi:
            result["unevaluated"].append(f"{m.name}: no deform vertex groups"); continue
        ws_b = ib = uw = 0
        for v in m.data.vertices:
            ws = [(gi[g.group], g.weight) for g in v.groups if g.group in gi and g.weight > 1e-6]
            s = sum(w for _, w in ws)
            if not ws: uw += 1
            elif abs(s - 1) > O["weight_tol"]: ws_b += 1
            if len(ws) > O["max_influences"]: ib += 1
            if m.get(O["layer_prop"]) == "L3" and len(ws) > 1: l3_bad.append(m.name); break
        wsum_bad += ws_b; infl_bad += ib; unweighted += uw
        per_mesh.append({"mesh": m.name, "verts": len(m.data.vertices), "weight_sum_off": ws_b, "over_influence": ib, "unweighted": uw})
    result["gates"]["weights_normalized"] = {"pass": wsum_bad == 0, "vertices_off": wsum_bad}
    result["gates"]["max_influences"] = {"pass": infl_bad == 0, "vertices_over": infl_bad, "limit": O["max_influences"]}
    result["gates"]["no_unweighted_vertices"] = {"pass": unweighted == 0, "unweighted": unweighted}
    result["gates"]["L3_rigid_parts"] = {"pass": not l3_bad, "blended_L3_meshes": sorted(set(l3_bad))}
    result["per_mesh"] = per_mesh
    unbound = [o.name for o in bpy.data.objects if o.type == 'MESH' and o.visible_get() and o not in meshes and not o.name.startswith(("REF", "COL_", "SOCKET"))]
    result["gates"]["all_visible_meshes_bound"] = {"pass": not unbound, "unbound": unbound}

    def eval_verts(m):
        dg = bpy.context.evaluated_depsgraph_get(); ev = m.evaluated_get(dg); me = ev.to_mesh()
        vs = [m.matrix_world @ v.co for v in me.vertices]; ev.to_mesh_clear(); return vs

    def bounds(vs):
        c = sum(vs, Vector()) / len(vs); r = max((v - c).length for v in vs); return c, r

    # --- G: pose sweep ---
    if O["sweep"] and meshes:
        bpy.context.view_layer.objects.active = arm
        rest = {m.name: eval_verts(m) for m in meshes}
        rest_b = {k: bounds(v) for k, v in rest.items()}
        bones = [pb for pb in arm.pose.bones if pb.bone.use_deform and (not O["sweep_bones"] or pb.name in O["sweep_bones"])]
        findings = []; frames = 0
        for pb in bones:
            saved = pb.rotation_quaternion.copy(); saved_mode = pb.rotation_mode; pb.rotation_mode = 'XYZ'; saved_e = pb.rotation_euler.copy()
            for ang in (45, 90, -45, -90):
                pb.rotation_euler = (math.radians(ang), 0, 0)
                bpy.context.view_layer.update(); frames += 1
                for m in meshes:
                    vs = eval_verts(m); c, r = bounds(vs); c0, r0 = rest_b[m.name]
                    origin_hits = sum(1 for v in vs if v.length < 1e-6)
                    maxmove = max((a - b).length for a, b in zip(vs, rest[m.name]))
                    bad = []
                    if origin_hits: bad.append(f"{origin_hits} verts at origin")
                    if r0 and (r / r0 < 0.7 or r / r0 > 1.5): bad.append(f"bounding radius ratio {r/r0:.2f}")
                    if maxmove > 0.5 * H: bad.append(f"vertex moved {maxmove/H:.2f} H")
                    if bad: findings.append({"bone": pb.name, "angle": ang, "mesh": m.name, "issues": bad})
            pb.rotation_euler = saved_e; pb.rotation_mode = saved_mode
            if saved_mode == 'QUATERNION': pb.rotation_quaternion = saved
        bpy.context.view_layer.update()
        result["gates"]["pose_sweep"] = {"pass": not findings, "frames_sampled": frames, "bones": len(bones), "findings": findings[:50],
                                         "note": "creases vs holes at part overlaps need visual check; 5 poses is not coverage"}
    else:
        result["unevaluated"].append("pose sweep skipped or no bound meshes")

    # --- G: action moves / loop / foot slide ---
    if O["action"]:
        act = bpy.data.actions.get(O["action"])
        if not act:
            result["unevaluated"].append(f"action {O['action']} not found")
        else:
            _action_gates(arm, act, O, H, result)
    else:
        result["unevaluated"].append("no action given: motion/loop/foot gates unevaluated")

    failed = [k for k, v in result["gates"].items() if not v.get("pass")]
    result["failed"] = failed
    result["summary"] = f"{len(result['gates'])} gates, failed: {failed}; unevaluated: {result['unevaluated']}"
    return result


def _action_gates(arm, act, O, H, result):
    scn = bpy.context.scene; saved_frame = scn.frame_current
    had_ad = arm.animation_data is not None
    ad = arm.animation_data or arm.animation_data_create()
    saved_action, saved_slot, saved_nla = ad.action, ad.action_slot, ad.use_nla
    fps = scn.render.fps / scn.render.fps_base
    try:
        ad.use_nla = False  # evaluate the clip alone
        slot = assign_action(arm, act)
        result["action_slot"] = slot.identifier if slot else None
        if slot is None:
            result["unevaluated"].append(f"action {act.name} has no slot usable by {arm.name}")
        f0, f1 = act.frame_range
        hip = pick_hip_bone(arm, O["hip_bone"])
        root = arm.pose.bones.get(O["root_bone"]) if O["root_bone"] else None
        result["hip_bone"] = hip.name if hip else None
        if O["root_bone"] and root is None:
            result["unevaluated"].append(f"root bone {O['root_bone']} not found")

        def at(f):
            scn.frame_set(int(math.floor(f)), subframe=f - math.floor(f))
            return ({pb.name: (arm.matrix_world @ pb.head).copy() for pb in arm.pose.bones},
                    {pb.name: pb.matrix_basis.to_quaternion() for pb in arm.pose.bones},
                    arm.matrix_world.translation.copy())

        samples = [f0 + (f1 - f0) * t / 4 for t in range(5)]
        poses = [at(f)[0] for f in samples]
        maxdisp = 0.0
        for k in poses[0]:
            for p in poses[1:]:
                maxdisp = max(maxdisp, (p[k] - poses[0][k]).length)
        result["gates"]["action_moves"] = {"pass": maxdisp > 1e-3 * H, "max_joint_displacement_H": round(maxdisp / H, 4),
                                           "note": "a clip that exists is not a clip that plays"}

        h0, q0, o0 = at(f0); h1, q1, o1 = at(f1)
        hip_travel = (h1[hip.name] - h0[hip.name]) if hip else Vector()
        static_excluded = []
        if root is not None:
            travel, source = h1[root.name] - h0[root.name], f"root bone {root.name}"
        elif (o1 - o0).length > 1e-6:
            travel, source = o1 - o0, "armature object"
        else:
            travel, source = Vector((hip_travel.x, hip_travel.y, 0.0)), f"hip bone {hip.name if hip else None} (horizontal)"
        travel_used = travel if O["allow_root_motion"] else Vector()
        excl = {root.name} if root is not None else set()
        if O["allow_root_motion"] and root is None and (o1 - o0).length <= 1e-6 and hip is not None:
            # hip-carried travel: bones outside the hip chain that never move (a static root/scaffold) stay behind by design
            hip_chain = {hip.name} | {c.name for c in hip.children_recursive}
            static_excluded = [k for k in h0 if k not in hip_chain and (h1[k] - h0[k]).length <= 1e-6
                               and all((p[k] - h0[k]).length <= 1e-6 for p in poses)]
        pose_return = max((math.degrees(q0[k].rotation_difference(q1[k]).angle) for k in q0 if k not in excl), default=0.0)
        rel_err = max((((h1[k] - travel_used) - h0[k]).length for k in h0 if k not in static_excluded), default=0.0)
        hip_resid = (hip_travel - travel_used).length
        dur_s = (f1 - f0) / fps if fps else 0
        gate = {"pass": pose_return <= 0.5 and hip_resid <= 0.01 * H and rel_err <= 0.01 * H,
                "pose_return_deg": round(pose_return, 3), "hip_travel_H": round(hip_travel.length / H, 4),
                "hip_residual_H": round(hip_resid / H, 4), "pose_relative_error_H": round(rel_err / H, 4),
                "allow_root_motion": bool(O["allow_root_motion"]), "travel_source": source,
                "travel_m": round(travel.length, 4), "travel_speed_m_per_s": round(travel.length / dur_s, 4) if dur_s else None,
                "static_bones_excluded": static_excluded, "frames": [f0, f1]}
        if not O["allow_root_motion"] and travel.length > 0.01 * H:
            gate["hint"] = "clip travels; pass allow_root_motion=True if the travel is intended root motion"
        result["gates"]["loops_cleanly"] = gate

        if O["foot_bones"]:
            slides, detail = {}, {}
            for fb in O["foot_bones"]:
                pb = arm.pose.bones.get(fb)
                if not pb:
                    result["unevaluated"].append(f"foot bone {fb} not found"); continue
                pos = []
                for f in range(int(f0), int(f1) + 1):
                    scn.frame_set(f); pos.append((arm.matrix_world @ pb.head).copy())
                zmin = min(p.z for p in pos)
                stance = [p.z - zmin < 0.02 * H for p in pos]
                segs, cur = [], []
                for p, s in zip(pos, stance):
                    if s: cur.append(p)
                    elif cur: segs.append(cur); cur = []
                if cur: segs.append(cur)
                worst, speeds = 0.0, []
                for sg in segs:
                    if O["foot_mode"] == "in_place":
                        r, v = _fit_residual([(p.x, p.y) for p in sg]); speeds.append(v * fps)
                    else:
                        r = max(((a - b).xy.length for a in sg for b in sg), default=0.0)
                    worst = max(worst, r)
                slides[fb] = round(worst / H, 4)
                detail[fb] = {"stance_segments": len(segs), "stance_frames": sum(len(s) for s in segs)}
                if speeds: detail[fb]["stance_speed_m_per_s"] = [round(s, 4) for s in speeds]
            result["gates"]["foot_contact"] = {"pass": all(s <= 0.01 for s in slides.values()) and bool(slides),
                                               "foot_slide_H": slides, "mode": O["foot_mode"], "detail": detail,
                                               "note": "in_place: slide = deviation from constant-speed treadmill motion; "
                                                       "match stance speed to the engine's move speed"}
    finally:
        ad.action = saved_action
        if saved_action is not None and saved_slot is not None:
            try: ad.action_slot = saved_slot
            except Exception: pass
        ad.use_nla = saved_nla
        if not had_ad: arm.animation_data_clear()
        scn.frame_set(saved_frame)


def _print_live(result):
    print(result["summary"])
    for k in result.get("failed", []):
        print(" ", k, {kk: vv for kk, vv in result["gates"][k].items() if kk != "pass"})


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="rig_check.py")
    p.add_argument("--armature"); p.add_argument("--action"); p.add_argument("--hip-bone"); p.add_argument("--root-bone")
    p.add_argument("--allow-root-motion", action="store_true"); p.add_argument("--foot-bones", default="")
    p.add_argument("--foot-mode", default="world", choices=["world", "in_place"]); p.add_argument("--no-sweep", action="store_true")
    p.add_argument("--max-influences", type=int, default=4)
    a = p.parse_args(argv)
    return run_rig_check({"armature": a.armature, "action": a.action, "hip_bone": a.hip_bone, "root_bone": a.root_bone,
                          "allow_root_motion": a.allow_root_motion, "foot_bones": [f for f in a.foot_bones.split(",") if f],
                          "foot_mode": a.foot_mode, "sweep": not a.no_sweep, "max_influences": a.max_influences})


if "RIG_OPTS" in globals():
    result = run_rig_check(RIG_OPTS); _print_live(result)
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("RIG_CHECK " + json.dumps(result, default=str))
else:
    result = run_rig_check({}); _print_live(result)
