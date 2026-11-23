"""Shape key gates: per-key moved vertices / max displacement, region confinement, L/R symmetry of paired keys,
empty or muted keys, and an optional eyelid-vs-eyeball penetration test per key value.

Headless / CLI (prints one line: SHAPEKEY_CHECK <json>):
    blender -b face.blend --python shapekey_check.py -- --object Head [--keys "*"] [--eps 1e-5]
        [--region "eyeBlink*=lids,jaw*|mouth*=mouth"] [--weight-min 0.001]
        [--sym-tol-mm 0.5] [--sym-rel 0.02] [--sym-axis X] [--symmetric "jawOpen,mouthFunnel"]
        [--eye "Head:lid.L=Eye.L" --eye "Lid.R=Eye.R"] [--lid-keys "*blink*,*Blink*,*lid*"]
        [--values 0.25,0.5,0.75,1] [--eye-radius 0] [--clearance-mm 0]
Live (Blender:execute_blender_code): set before exec
    SHAPEKEY_OPTS = {"object": "Head", "region": {"eyeBlink*": "lids"}, "eyes": [{"lid": "Head", "lid_group": "lid.L",
                     "eyeball": "Eye.L"}], ...}   -> `result` dict
Without SHAPEKEY_OPTS the file only defines check_shape_keys and helpers.

What is measured (object space of the mesh, metres; mm in the report):
  * per key: displacement vs its relative key (normally Basis); moved = |d| > eps; max/mean displacement; vertex_group.
  * region: for keys matching a glob, every moved vertex must have weight >= weight_min in the named vertex group;
    moved vertices outside are counted with their max displacement (a "blink" that also lifts the upper lip fails).
  * symmetry: keys named with .L/.R, _L/_R, Left/Right, _left/_right are paired; basis vertices are mirrored across
    --sym-axis with a KD-tree; error = max |d_L(v) - mirror(d_R(mirror(v)))|; passes when error <= max(sym-tol-mm,
    sym-rel x max displacement). Also checks the L key moves mostly on the +X side (character's left = +X facing -Y).
    Keys listed in --symmetric must equal their own mirror.
  * eyes: for each lid/eyeball pair and each lid key at each value (others zeroed, drivers/armature untouched),
    evaluated lid vertices closer than radius + clearance to the eyeball centre are penetrations. The eyeball is a
    sphere: centre = bbox centre of the evaluated eyeball, radius = --eye-radius or the mean vertex distance.
Limitations: object space only (no armature pose); sphere eyeball model (not cornea bulge; use a larger radius or
clearance for a bulging cornea); symmetry needs a mirror-symmetric basis (unmatched vertices are reported).
"""
import bpy, fnmatch, json, math, sys
import numpy as np

SIDE_PATTERNS = [(".L", ".R"), ("_L", "_R"), (".l", ".r"), ("_l", "_r"), ("Left", "Right"), ("_left", "_right"),
                 (".left", ".right")]


def _globs(spec):
    if spec is None: return ["*"]
    if isinstance(spec, str): spec = [s for s in spec.replace("|", ",").split(",")]
    return [s.strip() for s in spec if s and s.strip()]


def _match(name, spec):
    return any(fnmatch.fnmatchcase(name, g) for g in _globs(spec))


def _coords(kb):
    a = np.empty(len(kb.data) * 3, np.float64); kb.data.foreach_get("co", a); return a.reshape(-1, 3)


def _group_weights(obj, group_name):
    vg = obj.vertex_groups.get(group_name)
    w = np.zeros(len(obj.data.vertices))
    if vg is None: return None
    gi = vg.index
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi: w[v.index] = g.weight; break
    return w


def _pair_name(name):
    for l, r in SIDE_PATTERNS:
        if name.endswith(l): return "L", name[: -len(l)] + r
        if name.endswith(r): return "R", name[: -len(r)] + l
        # suffix before a trailing number / infix e.g. eyeBlinkLeft, mouthSmile_L
        if l in ("Left",) and l in name: return "L", name.replace(l, r)
        if r in ("Right",) and r in name: return "R", name.replace(r, l)
    return None, None


def _mirror_map(basis, axis=0, tol=1e-4):
    from mathutils.kdtree import KDTree
    kd = KDTree(len(basis))
    for i, c in enumerate(basis): kd.insert(c.tolist(), i)
    kd.balance()
    mp = np.full(len(basis), -1, np.int64)
    for i, c in enumerate(basis):
        m = c.copy(); m[axis] = -m[axis]
        co, j, d = kd.find(m.tolist())
        if d <= tol: mp[i] = j
    return mp


def _key_stats(obj, kb, eps):
    ref = kb.relative_key if kb.relative_key else obj.data.shape_keys.reference_key
    d = _coords(kb) - _coords(ref)
    n = np.linalg.norm(d, axis=1)
    moved = n > eps
    return d, n, moved, ref.name


def _eval_world_verts(o, dg):
    ev = o.evaluated_get(dg); me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3, np.float64); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    ev.to_mesh_clear()
    mw = np.array(o.matrix_world); return co @ mw[:3, :3].T + mw[:3, 3]


def _eye_check(eye, keys, values, clearance, default_radius, lid_keys):
    lid = bpy.data.objects.get(eye.get("lid", ""))
    ball = bpy.data.objects.get(eye.get("eyeball", ""))
    if lid is None or ball is None:
        return {"pass": None, "note": f"lid/eyeball object not found: {eye}"}
    group = eye.get("lid_group")
    mask = None
    if group:
        w = _group_weights(lid, group)
        if w is None: return {"pass": None, "note": f"lid group {group} missing on {lid.name}"}
        mask = w > 0.0
    sk = lid.data.shape_keys
    if not sk: return {"pass": None, "note": f"{lid.name} has no shape keys"}
    blocks = [kb for kb in sk.key_blocks[1:] if _match(kb.name, eye.get("keys", lid_keys))]
    saved = {kb.name: (kb.value, kb.mute) for kb in sk.key_blocks}
    rows, worst = [], 0.0
    try:
        for kb in sk.key_blocks[1:]: kb.value = 0.0
        tested = [(None, 0.0)] + [(kb, v) for kb in blocks for v in values]
        for kb, v in tested:
            if kb is not None: kb.value = v
            bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
            bv = _eval_world_verts(ball, dg)
            c = (bv.min(0) + bv.max(0)) / 2
            r = eye.get("radius") or default_radius or float(np.linalg.norm(bv - c, axis=1).mean())
            lv = _eval_world_verts(lid, dg)
            if mask is not None and len(mask) == len(lv): lv = lv[mask]
            dist = np.linalg.norm(lv - c, axis=1)
            depth = (r + clearance) - dist
            inside = depth > 0
            md = float(depth[inside].max()) if inside.any() else 0.0
            worst = max(worst, md)
            rows.append({"key": kb.name if kb else "(rest)", "value": v, "lid_points_inside": int(inside.sum()),
                         "max_penetration_mm": round(md * 1000, 3), "min_clearance_mm": round(float((dist - r).min()) * 1000, 3),
                         "eye_radius_mm": round(r * 1000, 3)})
            if kb is not None: kb.value = 0.0
    finally:
        for kb in sk.key_blocks:
            if kb.name in saved: kb.value, kb.mute = saved[kb.name]
        bpy.context.view_layer.update()
    fails = [r for r in rows if r["lid_points_inside"]]
    return {"pass": (not fails) if blocks else None, "lid": lid.name, "lid_group": group, "eyeball": ball.name,
            "keys_tested": [kb.name for kb in blocks], "worst_penetration_mm": round(worst * 1000, 3),
            "failing": fails[:20], "samples": rows[:60],
            "note": None if blocks else "no lid keys matched; only rest state measured"}


def check_shape_keys(object=None, keys="*", eps=1e-5, region=None, weight_min=1e-3, sym_tol_mm=0.5, sym_rel=0.02,
                     sym_axis="X", symmetric=None, eyes=None, lid_keys="*blink*,*Blink*,*lid*,*Lid*",
                     values=(0.25, 0.5, 0.75, 1.0), eye_radius=0.0, clearance_mm=0.0, mirror_tol_mm=0.1):
    obj = bpy.data.objects.get(object) if object else bpy.context.object
    out = {"blender": bpy.app.version_string, "object": obj.name if obj else None}
    if obj is None or obj.type != 'MESH':
        out["pass"] = None; out["note"] = "mesh object not found"; return out
    sk = obj.data.shape_keys
    if not sk or len(sk.key_blocks) < 2:
        out["pass"] = None; out["note"] = "no shape keys besides Basis"; return out
    if isinstance(region, str):
        region = dict(p.split("=", 1) for p in region.split(",") if "=" in p) if "=" in region else None
    axis = "XYZ".index(sym_axis.upper())
    basis = _coords(sk.reference_key)
    ext = float(np.linalg.norm(basis.max(0) - basis.min(0)))
    blocks = [kb for kb in sk.key_blocks if kb != sk.reference_key and _match(kb.name, keys)]
    stats, per_key, failures = {}, [], []
    gw_cache = {}
    for kb in blocks:
        d, n, moved, ref = _key_stats(obj, kb, eps)
        stats[kb.name] = (d, n, moved)
        row = {"key": kb.name, "relative_to": ref, "moved_vertices": int(moved.sum()),
               "max_displacement_mm": round(float(n.max()) * 1000, 3),
               "mean_moved_displacement_mm": round(float(n[moved].mean()) * 1000, 3) if moved.any() else 0.0,
               "vertex_group": kb.vertex_group or None, "mute": kb.mute, "slider": [kb.slider_min, kb.slider_max]}
        issues = []
        if not moved.any(): issues.append("empty key (no vertex moves)")
        if not np.isfinite(d).all(): issues.append("non-finite coordinates")
        if kb.mute: issues.append("muted")
        if region:
            for pat, grp in region.items():
                if _match(kb.name, pat):
                    if grp not in gw_cache: gw_cache[grp] = _group_weights(obj, grp)
                    w = gw_cache[grp]
                    if w is None:
                        row["region"] = {"group": grp, "pass": None, "note": "vertex group missing"}; issues.append(f"region group {grp} missing")
                    else:
                        outside = moved & (w < weight_min)
                        row["region"] = {"group": grp, "pass": not outside.any(), "moved_outside": int(outside.sum()),
                                         "max_outside_mm": round(float(n[outside].max()) * 1000, 3) if outside.any() else 0.0}
                        if outside.any(): issues.append(f"{int(outside.sum())} moved vertices outside '{grp}'")
                    break
        row["issues"] = issues
        if issues and not (issues == ["muted"]): failures.append(kb.name)
        per_key.append(row)
    out["keys"] = per_key

    # symmetry
    sym_rows = []
    need_sym = any(_pair_name(kb.name)[0] for kb in blocks) or symmetric
    if need_sym:
        mp = _mirror_map(basis, axis, tol=max(mirror_tol_mm / 1000, ext * 1e-6))
        unmatched = int((mp < 0).sum())
        ok = mp >= 0
        flip = np.ones(3); flip[axis] = -1
        done = set()

        def compare(nl, nr):
            dl, nlm, _ = stats[nl]; dr, nrm, _ = stats[nr]
            mirrored_r = np.zeros_like(dl); mirrored_r[ok] = dr[mp[ok]] * flip
            err = np.linalg.norm(dl - mirrored_r, axis=1); err[~ok] = 0
            peak = max(float(nlm.max()), float(nrm.max()))
            tol = max(sym_tol_mm / 1000, sym_rel * peak)
            return float(err.max()), tol, peak, int((err > tol).sum())

        for kb in blocks:
            side, twin = _pair_name(kb.name)
            if side != "L" or kb.name in done: continue
            if twin not in stats:
                sym_rows.append({"pair": [kb.name, twin], "pass": False, "note": "twin key missing"}); failures.append(kb.name); continue
            e, tol, peak, nbad = compare(kb.name, twin); done.update({kb.name, twin})
            dl, nl_, mv = stats[kb.name]
            w_side = float(nl_[basis[:, axis] > 1e-9].sum()); w_other = float(nl_[basis[:, axis] < -1e-9].sum())
            # whole-mouth shifts (mouthLeft, jawLeft) move both sides; only a clearly wrong-side key fails
            side_ok = (w_side + w_other) == 0 or w_side / (w_side + w_other) >= 0.35
            passed = e <= tol and side_ok
            sym_rows.append({"pair": [kb.name, twin], "pass": passed, "max_mirror_error_mm": round(e * 1000, 3),
                             "tolerance_mm": round(tol * 1000, 3), "vertices_over_tol": nbad,
                             "L_side_displacement_share": round(w_side / (w_side + w_other), 3) if (w_side + w_other) else None,
                             "side_ok": side_ok})
            if not passed: failures.append(kb.name)
        for kb in blocks:
            if symmetric and _match(kb.name, symmetric) and _pair_name(kb.name)[0] is None:
                e, tol, peak, nbad = compare(kb.name, kb.name)
                sym_rows.append({"self_symmetric": kb.name, "pass": e <= tol, "max_mirror_error_mm": round(e * 1000, 3),
                                 "tolerance_mm": round(tol * 1000, 3), "vertices_over_tol": nbad})
                if e > tol: failures.append(kb.name)
        out["symmetry"] = {"pairs": sym_rows, "basis_vertices_without_mirror": unmatched,
                           "note": "unmatched basis vertices are ignored in the error; an asymmetric basis makes pairs unprovable"}
    # eyes
    if eyes:
        out["eyes"] = [_eye_check(e, keys, list(values), clearance_mm / 1000, eye_radius, lid_keys) for e in eyes]
        for e in out["eyes"]:
            if e.get("pass") is False: failures.append(f"eye:{e.get('lid')}/{e.get('eyeball')}")
    out["failed"] = sorted(set(failures))
    out["pass"] = not failures
    out["summary"] = {"keys": len(per_key), "failed": out["failed"],
                      "symmetry_pairs": len([r for r in sym_rows if "pair" in r]), "eyes": len(eyes or [])}
    return out


def _parse_eye(s):
    # "LidObj[:group]=Eyeball"
    lidpart, ball = s.split("=", 1)
    lid, _, grp = lidpart.partition(":")
    return {"lid": lid, "lid_group": grp or None, "eyeball": ball}


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="shapekey_check.py")
    p.add_argument("--object"); p.add_argument("--keys", default="*"); p.add_argument("--eps", type=float, default=1e-5)
    p.add_argument("--region"); p.add_argument("--weight-min", type=float, default=1e-3)
    p.add_argument("--sym-tol-mm", type=float, default=0.5); p.add_argument("--sym-rel", type=float, default=0.02)
    p.add_argument("--sym-axis", default="X"); p.add_argument("--symmetric")
    p.add_argument("--eye", action="append", default=[]); p.add_argument("--lid-keys", default="*blink*,*Blink*,*lid*,*Lid*")
    p.add_argument("--values", default="0.25,0.5,0.75,1"); p.add_argument("--eye-radius", type=float, default=0.0)
    p.add_argument("--clearance-mm", type=float, default=0.0)
    a = p.parse_args(argv)
    return check_shape_keys(a.object, a.keys, a.eps, a.region, a.weight_min, a.sym_tol_mm, a.sym_rel, a.sym_axis, a.symmetric,
                            [_parse_eye(e) for e in a.eye], a.lid_keys, [float(v) for v in a.values.split(",")],
                            a.eye_radius, a.clearance_mm)


if "SHAPEKEY_OPTS" in globals():
    result = check_shape_keys(**SHAPEKEY_OPTS); print(json.dumps(result.get("summary")))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("SHAPEKEY_CHECK " + json.dumps(result, default=str))
else:
    result = {"defined": ["check_shape_keys"]}
