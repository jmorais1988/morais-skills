"""Two-bone IK controls from code (target + pole bones, auto pole angle, stretch, optional reverse-foot roll), an IK
sanity check (rest drift, knee bends toward the pole), and baking controls down to deform bones for export.

Headless / CLI (prints one line: IK_RIG <json>):
    blender -b rig.blend --python ik_rig.py -- --armature Rig --tip shin.L [--add] [--chain-count 2]
        [--target-name IK_shin.L] [--pole-name POLE_shin.L] [--foot foot.L] [--foot-roll] [--pole-dir 0,-1,0]
        [--pole-dist 0] [--pole-angle auto|<deg>] [--stretch 0.1] [--parent root] [--ground-z 0] [--check] [--bend 0.3]
        [--bake 1-48] [--bones deform|a,b,c] [--step 1] [--copy | --export-skeleton [--inherit-scale NONE]]
        [--keep-constraints] [--tol 1e-4] [--save out.blend]
Live (Blender:execute_blender_code): set before exec
    IK_RIG_OPTS = {"armature": "Rig", "tip": "shin.L", "add": True, "foot": "foot.L", "foot_roll": True,
                   "check": True, "bake": [1, 48], "copy": True}   -> `result` dict
Without IK_RIG_OPTS the file only defines add_two_bone_ik, check_ik, bake_to_deform, pole_angle_for and run.

Built bones (suffix copied from the tip, e.g. shin.L -> IK_shin.L): IK_<tip> target at the chain tip, POLE_<tip> placed
along the knee's bend direction (or --pole-dir) one chain length out; with --foot-roll CTRL_<foot> (heel pivot, custom
property "roll", radians: + lifts the heel around the ball, - lifts the toes around the heel), MCH_heel_/MCH_ball_/
MCH_foot_<foot>. Controls are non-deforming. The pole angle is computed so the rest pose is preserved; check_ik proves
it (rest drift) and that the knee bends toward the pole (cosine of knee motion vs pole direction).
bake_to_deform records world head/tail of the deform bones, runs nla.bake (visual keying, only selected, optional
clear constraints) and re-measures -> max bake error in metres. --copy bakes onto <rig>_BAKE and leaves the control rig.
When deform bones hang off control/mechanism bones (Rigify DEF- under ORG-/MCH-; reported as bones_with_unbaked_parent)
a deform-only bake can't reproduce the motion: --export-skeleton builds <rig>_EXPORT (deform bones only, re-parented to
the nearest deform ancestor, Copy Transforms to the source) and bakes that. Pass requires error <= tol, every requested
bone baked and no constraints left.
Limitations: check_ik assumes the IK target/pole are bones of the same armature and measures the joint before the tip
(a 2-bone chain); custom properties (roll) should be 0 during check; foot roll has heel + ball pivots only (no toe-tip
pivot, no banking); in-place baking with clear constraints is destructive -- use --copy or work on a saved copy.
"""
import bpy, json, math, re, sys
from mathutils import Vector, Matrix

_SFX = re.compile(r"([._-](?:L|R|l|r|Left|Right|left|right))$")


def _arm(name):
    o = bpy.data.objects.get(name) if name else next((o for o in bpy.context.scene.objects if o.type == 'ARMATURE'), None)
    if o is None or o.type != 'ARMATURE':
        raise ValueError(f"armature not found: {name}")
    return o


def _mode(obj, mode):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in bpy.context.view_layer.objects:
        if o.select_get():
            o.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if mode != 'OBJECT':
        bpy.ops.object.mode_set(mode=mode)


def _split(name):
    m = _SFX.search(name)
    return (name[:m.start()], m.group(1)) if m else (name, "")


def _chain(bones, tip, n):
    ch = [bones[tip]]
    while len(ch) < n:
        if ch[-1].parent is None:
            raise ValueError(f"chain from {tip} is shorter than chain_count={n}")
        ch.append(ch[-1].parent)
    return ch


def _signed_angle(u, v, n):
    a = u.angle(v, 0.0)
    return -a if u.cross(v).dot(n) < 0 else a


def pole_angle_for(base_matrix_local, tip_tail, pole_loc):
    """Pole angle (radians) that keeps the rest pose: angle from the base bone's X axis to the plane through
    base head, chain tip and pole, measured around the base bone's Y axis. All inputs in armature space."""
    head = base_matrix_local.translation
    x, y = base_matrix_local.col[0].xyz, base_matrix_local.col[1].xyz
    pole_normal = (tip_tail - head).cross(pole_loc - head)
    a = -_signed_angle(x, pole_normal.cross(y), y)   # sign measured in 5.2: the positive form flips the knee
    return (a + math.pi) % (2 * math.pi) - math.pi


def _sel_pose_bone(pb, v):
    if hasattr(pb, "select"):
        pb.select = v
    else:
        pb.bone.select = v


def add_two_bone_ik(armature=None, tip=None, chain_count=2, target_name=None, pole_name=None, pole_dir=None,
                    pole_dist=0.0, pole_angle="auto", stretch=0.0, foot=None, foot_roll=False, parent=None,
                    ground_z=None, iterations=500):
    arm = _arm(armature)
    ad = arm.data
    if tip not in ad.bones:
        raise ValueError(f"tip bone not found: {tip}")
    chain = _chain(ad.bones, tip, chain_count)
    names = [b.name for b in chain]
    base, btip = chain[-1], chain[0]
    root, tip_tail, mid = base.head_local.copy(), btip.tail_local.copy(), btip.head_local.copy()
    L = sum(b.length for b in chain)
    stem, sfx = _split(tip)
    target_name = target_name or f"IK_{stem}{sfx}"
    pole_name = pole_name or f"POLE_{stem}{sfx}"
    if pole_dir:
        pd = Vector(pole_dir).normalized()
    else:
        axis = (tip_tail - root).normalized()
        off = mid - root
        perp = off - axis * off.dot(axis)
        if perp.length < 1e-4 * L:
            raise ValueError("chain is straight in rest pose: pass pole_dir (the bend direction) or pre-bend the joint")
        pd = perp.normalized()
    pole_loc = mid + pd * (pole_dist or L)
    fnames = {}
    _mode(arm, 'EDIT')
    eb = ad.edit_bones

    def ensure(name, head, tail, par=None, roll=0.0):
        e = eb.get(name) or eb.new(name)
        e.head, e.tail, e.roll = head, tail, roll
        e.use_deform = False
        e.parent = eb.get(par) if par else None
        return e

    tgt_parent = parent
    if foot:
        if foot not in eb:
            raise ValueError(f"foot bone not found: {foot}")
        ef = eb[foot]
        fh, ft, froll = ef.head.copy(), ef.tail.copy(), ef.roll
        if foot_roll:
            fstem, fsfx = _split(foot)
            fnames = {k: f"{k}_{fstem}{fsfx}" for k in ("CTRL", "MCH_heel", "MCH_ball", "MCH_foot")}
            gz = min(fh.z, ft.z) if ground_z is None else ground_z
            fwd = Vector((ft.x - fh.x, ft.y - fh.y, 0.0))
            if fwd.length < 1e-6:
                raise ValueError("foot bone is vertical: cannot derive a forward direction for foot roll")
            fwd.normalize()
            flen = (ft - fh).length
            heel = Vector((fh.x, fh.y, gz))
            ensure(fnames["CTRL"], heel, heel + fwd * flen, parent)
            ensure(fnames["MCH_heel"], heel, heel + fwd * flen * 0.5, fnames["CTRL"])
            ensure(fnames["MCH_ball"], ft, ft + fwd * flen * 0.5, fnames["MCH_heel"])
            ensure(fnames["MCH_foot"], fh, ft, fnames["MCH_ball"], froll)
            tgt_parent = fnames["MCH_ball"]
        ensure(target_name, tip_tail, tip_tail + (ft - fh), tgt_parent, froll)
    else:
        d = (btip.tail_local - btip.head_local).normalized()
        ensure(target_name, tip_tail, tip_tail + d * 0.2 * L, tgt_parent, eb[tip].roll)
    ensure(pole_name, pole_loc, pole_loc + Vector((0, 0, 0.1 * L)), parent)
    _mode(arm, 'POSE')
    pbs = arm.pose.bones
    ptip = pbs[tip]
    c = next((c for c in ptip.constraints if c.type == 'IK'), None) or ptip.constraints.new('IK')
    c.name, c.target, c.subtarget = "IK", arm, target_name
    c.pole_target, c.pole_subtarget = arm, pole_name
    c.chain_count, c.use_tail, c.use_stretch, c.iterations = chain_count, True, stretch > 0, iterations
    ang = pole_angle_for(ad.bones[base.name].matrix_local, tip_tail, pole_loc) if pole_angle in (None, "auto") \
        else math.radians(float(pole_angle))
    ang = (ang + math.pi) % (2 * math.pi) - math.pi   # pole_angle clamps to [-pi, pi] instead of wrapping
    c.pole_angle = ang
    for n in names:
        pbs[n].ik_stretch = stretch
    if foot:
        pf = pbs[foot]
        cr = pf.constraints.get("IK_foot") or pf.constraints.new('COPY_ROTATION')
        cr.name, cr.target = "IK_foot", arm
        cr.subtarget = fnames["MCH_foot"] if foot_roll else target_name
    if foot_roll:
        pc = pbs[fnames["CTRL"]]
        pc["roll"] = 0.0
        try:
            pc.id_properties_ui("roll").update(min=-1.6, max=1.6, soft_min=-1.2, soft_max=1.2, subtype='ANGLE')
        except Exception:
            pass
        for key, expr in (("MCH_heel", "min(roll, 0.0)"), ("MCH_ball", "max(roll, 0.0)")):
            pb = pbs[fnames[key]]
            pb.rotation_mode = 'XYZ'
            sz = 1.0 if pb.bone.matrix_local.col[2].z >= 0 else -1.0   # +rot about local X moves the tail toward local Z
            try:
                pb.driver_remove("rotation_euler", 0)
            except Exception:
                pass
            dr = pb.driver_add("rotation_euler", 0).driver
            dr.type = 'SCRIPTED'
            v = dr.variables.new()
            v.name, v.type = "roll", 'SINGLE_PROP'
            v.targets[0].id_type, v.targets[0].id = 'OBJECT', arm
            v.targets[0].data_path = f'pose.bones["{fnames["CTRL"]}"]["roll"]'
            dr.expression = f"{-sz} * {expr}"
    _mode(arm, 'OBJECT')
    return {"armature": arm.name, "chain": names[::-1], "target": target_name, "pole": pole_name,
            "pole_angle_deg": round(math.degrees(ang), 3), "pole_location": [round(x, 4) for x in pole_loc],
            "chain_length": round(L, 4), "stretch": stretch, "foot": foot, "foot_controls": fnames}


def check_ik(armature=None, tip=None, bend=0.3, drift_tol=0.01, cos_min=0.7):
    """Rest drift of the middle joint with the target at the rest tip (should be ~0), knee motion toward the pole side
    when the target moves bend*L toward the chain root, and reach error. Restores the pose afterwards."""
    arm = _arm(armature)
    pbs = arm.pose.bones
    ptip = pbs.get(tip)
    c = next((c for c in ptip.constraints if c.type == 'IK' and not c.mute), None) if ptip else None
    if c is None:
        return {"pass": None, "reason": f"no active IK constraint on {tip}"}
    if c.target != arm or c.subtarget not in pbs or c.pole_target != arm or c.pole_subtarget not in pbs:
        return {"pass": None, "reason": "check needs target and pole bones on the same armature"}
    n = c.chain_count or 2
    chain = _chain(arm.data.bones, tip, n)
    L = sum(b.length for b in chain)
    root, rest_tip, rest_mid = chain[-1].head_local, chain[0].tail_local, chain[0].head_local
    saved = {pb.name: pb.matrix_basis.copy() for pb in pbs}
    ad = arm.animation_data
    act = (ad.action, ad.action_slot) if ad else None
    if ad:
        ad.action = None
    vl = bpy.context.view_layer
    tgt, pole = pbs[c.subtarget], pbs[c.pole_subtarget]
    try:
        for pb in pbs:
            pb.matrix_basis = Matrix.Identity(4)
        vl.update()

        def place(p):
            m = tgt.matrix.copy()
            m.translation = p
            tgt.matrix = m
            vl.update()

        place(rest_tip.copy())
        drift = (ptip.head - rest_mid).length
        axis = (rest_tip - root).normalized()
        pd = pole.head - rest_mid
        pd = pd - axis * pd.dot(axis)
        place(rest_tip + (root - rest_tip).normalized() * bend * L)
        kd = ptip.head - rest_mid
        kd = kd - axis * kd.dot(axis)
        cos = kd.normalized().dot(pd.normalized()) if kd.length > 1e-9 and pd.length > 1e-9 else 0.0
        reach = (ptip.tail - tgt.head).length
    finally:
        for pb in pbs:
            pb.matrix_basis = saved[pb.name]
        if ad and act:
            ad.action = act[0]
            if act[0] is not None:
                ad.action_slot = act[1]
        vl.update()
    ok = drift <= drift_tol * L and cos >= cos_min
    return {"pass": ok, "tip": tip, "chain_count": n, "pole_angle_deg": round(math.degrees(c.pole_angle), 3),
            "rest_drift_m": round(drift, 6), "drift_tol_m": round(drift_tol * L, 6),
            "knee_toward_pole_cos": round(cos, 4), "knee_flip": cos < 0, "bend_reach_error_m": round(reach, 6)}


def _channelbag_fcurves(obj):
    ad = obj.animation_data
    if not ad or not ad.action or not ad.action_slot:
        return []
    out = []
    for layer in ad.action.layers:
        for st in layer.strips:
            cb = st.channelbag(ad.action_slot)
            if cb:
                out += list(cb.fcurves)
    return out


def make_export_skeleton(armature=None, bones="deform", name=None, inherit_scale=None, bbone_segments=1):
    """Deform-only copy of the rig: each kept bone re-parented to its nearest kept ancestor, all other bones removed,
    constraints/drivers/animation cleared, one COPY_TRANSFORMS (world) per bone to the same-named source bone.
    Needed when deform bones hang off control/mechanism bones (Rigify: DEF- under ORG-/MCH-)."""
    src = _arm(armature)
    names = [b.name for b in src.data.bones if b.use_deform] if bones in (None, "deform") else \
        (bones.split(",") if isinstance(bones, str) else list(bones))
    keep = set(names)
    name = name or f"{src.name}_EXPORT"
    old = bpy.data.objects.get(name)
    if old:
        bpy.data.objects.remove(old)
    dup = src.copy()
    dup.data = src.data.copy()
    dup.name = name
    dup.animation_data_clear()
    for col in src.users_collection:
        col.objects.link(dup)
    _mode(dup, 'EDIT')
    eb = dup.data.edit_bones
    for n in names:
        q = src.data.bones[n].parent
        while q is not None and q.name not in keep:
            q = q.parent
        e = eb[n]
        e.use_connect = False
        e.parent = eb[q.name] if q is not None else None
        if bbone_segments:
            e.bbone_segments = bbone_segments
        if inherit_scale:
            e.inherit_scale = inherit_scale
    for e in [e for e in eb if e.name not in keep]:
        eb.remove(e)
    _mode(dup, 'POSE')
    for pb in dup.pose.bones:
        for c in list(pb.constraints):
            pb.constraints.remove(c)
        pb.custom_shape = None
        c = pb.constraints.new('COPY_TRANSFORMS')
        c.name, c.target, c.subtarget = "EXPORT_copy", src, pb.name
    _mode(dup, 'OBJECT')
    reparented = sum(1 for n in names if src.data.bones[n].parent is not None and
                     (dup.data.bones[n].parent is None or dup.data.bones[n].parent.name != src.data.bones[n].parent.name))
    return dup, {"object": dup.name, "bones": len(dup.data.bones), "reparented": reparented}


def bake_to_deform(armature=None, frame_start=1, frame_end=250, bones="deform", step=1, copy=False,
                   clear_constraints=True, action_name=None, tol=1e-4, export_skeleton=False, inherit_scale=None):
    src = _arm(armature)
    scn = bpy.context.scene
    names = [b.name for b in src.data.bones if b.use_deform] if bones in (None, "deform") else \
        ([b for b in bones.split(",")] if isinstance(bones, str) else list(bones))
    nondeform_parent = sum(1 for n in names if src.data.bones[n].parent is not None
                           and src.data.bones[n].parent.name not in names)
    missing = [n for n in names if n not in src.pose.bones]
    if missing or not names:
        return {"pass": False, "reason": f"bones missing/empty: {missing}"}
    frames = list(range(int(frame_start), int(frame_end) + 1, int(step)))
    ref = {}
    for f in frames:
        scn.frame_set(f)
        mw = src.matrix_world
        ref[f] = {n: (mw @ src.pose.bones[n].head, mw @ src.pose.bones[n].tail) for n in names}
    tgt, skel = src, None
    if export_skeleton:
        tgt, skel = make_export_skeleton(src.name, names, inherit_scale=inherit_scale)
    elif copy:
        old = bpy.data.objects.get(f"{src.name}_BAKE")
        if old:
            bpy.data.objects.remove(old)
        tgt = src.copy()
        tgt.data = src.data.copy()
        tgt.name = f"{src.name}_BAKE"
        for col in src.users_collection:
            col.objects.link(tgt)
    _mode(tgt, 'POSE')
    # hidden bones / bone collections are silently skipped by only_selected (Rigify hides DEF-): unhide while baking
    restore = []
    for bc in getattr(tgt.data, "collections_all", []):
        restore += [(bc, "is_visible", bc.is_visible), (bc, "is_solo", getattr(bc, "is_solo", False))]
        bc.is_visible = True
        if hasattr(bc, "is_solo"):
            bc.is_solo = False
    for pb in tgt.pose.bones:
        for owner in (pb, pb.bone):
            if hasattr(owner, "hide") and owner.hide:
                restore.append((owner, "hide", True))
                owner.hide = False
        _sel_pose_bone(pb, pb.name in names)
    bpy.ops.nla.bake(frame_start=frames[0], frame_end=frames[-1], step=int(step), only_selected=True,
                     visual_keying=True, clear_constraints=clear_constraints, clear_parents=False,
                     use_current_action=False, clean_curves=False, bake_types={'POSE'})
    for owner, attr, val in restore:
        setattr(owner, attr, val)
    _mode(tgt, 'OBJECT')
    ad = tgt.animation_data
    act = ad.action if ad else None
    if act is not None:
        if action_name:
            act.name = action_name
        if ad.action_slot is None and len(act.slots):
            ad.action_slot = act.slots[0]
    err, worst = 0.0, None
    for f in frames:
        scn.frame_set(f)
        mw = tgt.matrix_world
        for n in names:
            for i, p in enumerate((mw @ tgt.pose.bones[n].head, mw @ tgt.pose.bones[n].tail)):
                d = (p - ref[f][n][i]).length
                if d > err:
                    err, worst = d, {"frame": f, "bone": n, "point": ("head", "tail")[i]}
    left = {n: [c.type for c in tgt.pose.bones[n].constraints] for n in names if len(tgt.pose.bones[n].constraints)}
    fcs = _channelbag_fcurves(tgt)
    baked_bones = sorted({fc.data_path.split('"')[1] for fc in fcs if fc.data_path.startswith("pose.bones")})
    unbaked = [n for n in names if n not in baked_bones]
    # error alone can be fooled: an unbaked copy bone whose constraints still target the source rig tracks it perfectly
    ok = err <= tol and not unbaked and not (clear_constraints and left)
    return {"pass": ok, "object": tgt.name, "action": act.name if act else None,
            "slot": ad.action_slot.identifier if ad and ad.action_slot else None, "frames": [frames[0], frames[-1]],
            "bones": len(names), "baked_bones": len(baked_bones), "unbaked": unbaked[:10], "fcurves": len(fcs),
            "bones_with_unbaked_parent": nondeform_parent, "export_skeleton": skel,
            "max_bake_error_m": float(f"{err:.3g}"), "worst": worst, "tol_m": tol, "constraints_left": left}


def run(armature=None, tip=None, add=False, check=False, bake=None, save=None, **kw):
    out, failed = {}, []
    add_keys = ("chain_count", "target_name", "pole_name", "pole_dir", "pole_dist", "pole_angle", "stretch", "foot",
                "foot_roll", "parent", "ground_z")
    if add:
        out["add"] = add_two_bone_ik(armature, tip, **{k: kw[k] for k in add_keys if k in kw})
    if check:
        out["check"] = check_ik(armature, tip, **{k: kw[k] for k in ("bend", "drift_tol", "cos_min") if k in kw})
        if out["check"]["pass"] is False:
            failed.append("check")
    if bake:
        fs, fe = (bake if isinstance(bake, (list, tuple)) else [int(x) for x in str(bake).split("-")])
        out["bake"] = bake_to_deform(armature, fs, fe, **{k: kw[k] for k in ("bones", "step", "copy", "clear_constraints",
                                                                           "action_name", "tol", "export_skeleton",
                                                                           "inherit_scale") if k in kw})
        if out["bake"]["pass"] is False:
            failed.append("bake")
    if save:
        bpy.ops.wm.save_as_mainfile(filepath=save, copy=True)
    out["failed"], out["pass"] = failed, not failed
    return out


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="ik_rig.py")
    p.add_argument("--armature"); p.add_argument("--tip", required=True); p.add_argument("--add", action="store_true")
    p.add_argument("--chain-count", type=int, default=2); p.add_argument("--target-name"); p.add_argument("--pole-name")
    p.add_argument("--pole-dir"); p.add_argument("--pole-dist", type=float, default=0.0)
    p.add_argument("--pole-angle", default="auto"); p.add_argument("--stretch", type=float, default=0.0)
    p.add_argument("--foot"); p.add_argument("--foot-roll", action="store_true"); p.add_argument("--parent")
    p.add_argument("--ground-z", type=float); p.add_argument("--check", action="store_true")
    p.add_argument("--bend", type=float, default=0.3); p.add_argument("--bake"); p.add_argument("--bones", default="deform")
    p.add_argument("--step", type=int, default=1); p.add_argument("--copy", action="store_true")
    p.add_argument("--keep-constraints", action="store_true"); p.add_argument("--tol", type=float, default=1e-4)
    p.add_argument("--export-skeleton", action="store_true"); p.add_argument("--inherit-scale")
    p.add_argument("--save")
    a = p.parse_args(argv)
    return run(a.armature, a.tip, add=a.add, check=a.check, bake=a.bake, save=a.save, chain_count=a.chain_count,
               target_name=a.target_name, pole_name=a.pole_name,
               pole_dir=[float(x) for x in a.pole_dir.split(",")] if a.pole_dir else None, pole_dist=a.pole_dist,
               pole_angle=a.pole_angle, stretch=a.stretch, foot=a.foot, foot_roll=a.foot_roll, parent=a.parent,
               ground_z=a.ground_z, bend=a.bend, bones=a.bones, step=a.step, copy=a.copy,
               clear_constraints=not a.keep_constraints, tol=a.tol, export_skeleton=a.export_skeleton,
               inherit_scale=a.inherit_scale)


if "IK_RIG_OPTS" in globals():
    result = run(**IK_RIG_OPTS); print(json.dumps(result, default=str))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("IK_RIG " + json.dumps(result, default=str))
else:
    result = {"defined": ["add_two_bone_ik", "check_ik", "bake_to_deform", "make_export_skeleton", "pole_angle_for", "run"]}
