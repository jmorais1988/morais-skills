"""Toon/anime custom normals: transfer smooth normals from a proxy shape (sphere, ellipsoid or any mesh object) onto a
target mesh inside a vertex-group mask, then MEASURE the result (deviation from the proxy inside, unchanged outside).

Headless / CLI (prints one line `NORMAL_TRANSFER {json}`):
    blender -b char.blend --python normal_transfer.py -- --target Head --proxy ELLIPSOID --vgroup face_mask \
        [--fit-group head_fit --inflate 1.0 --bone head --method DATA_TRANSFER|NORMAL_EDIT --mix 1.0 \
         --mapping POLYINTERP_NEAREST --place AFTER_DEFORM|KEEP|FIRST|LAST --apply --tol-in 2.0 --tol-out 0.5 \
         --pose-bone jaw --pose-deg 20 --pose-axis X --measure-only --name NRM_Transfer --save out.blend]
    --proxy SPHERE | ELLIPSOID -> generated object NRMPROXY_<target> fitted to --fit-group (or all vertices); or an object name.
Live (Blender MCP execute): set before exec
    NORMAL_TRANSFER_OPTS = {"target": "Head", "proxy": "ELLIPSOID", "vertex_group": "face_mask", "bone": "head"}
    -> `result` dict. Without NORMAL_TRANSFER_OPTS only functions are defined (fit_proxy, add_transfer, add_normal_edit,
    measure, normal_transfer).

Builds (idempotent: objects/modifiers with the same names are reused)
- Proxy: smooth UV ellipsoid, radii baked into the mesh (object scale 1), hidden from render/camera/shadow, drawn as wire;
  with --bone it is parented to that bone of the target's Armature modifier object so it follows the head.
- DATA_TRANSFER (default): Face Corner Data > Custom Normals, Nearest Face Interpolated, Object Transform on, mask =
  vertex group, placed right AFTER the last deform modifier (Armature/Lattice/...). Shape keys always evaluate before
  modifiers, so expressions never bend the transferred normals.
- NORMAL_EDIT: Radial mode toward an Empty NRMCENTER_<target> at the proxy center (no proxy mesh; sphere-like result).

Report (angles in degrees)
- inside  : corners of vertices with mask weight >= 0.999 -> angle(evaluated normal, proxy normal interpolated at the
            nearest proxy surface point).  Gate: p95 <= tol_in.
- outside : corners with weight <= 0.001 -> angle(evaluated normal, same corner with the transfer modifiers disabled).
            Gate: max <= tol_out.
- defects : no_mask, mask_missing, mask_empty, deform_after_transfer, proxy_not_following_rig, flat_faces_in_mask,
            inside_deviation, outside_changed, topology_changed, transfer_disabled (+ the same gates re-measured posed
            when --pose-bone is given: posed_inside_deviation / posed_outside_changed).
Limitations: topology-changing modifiers AFTER the transfer (Subdivision, Mirror, ...) are muted while measuring;
anything topology-changing BEFORE it makes per-corner comparison impossible (topology_changed). The proxy normal is the
nearest-surface normal, which for a concave custom proxy can differ from what Data Transfer matched. --apply bakes the
normals into the mesh: they then ride any later deformation (jaw, squash) instead of staying proxy-driven.
"""
import bpy, bmesh, json, math, sys
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc

DEFORM_TYPES = {'ARMATURE', 'LATTICE', 'MESH_DEFORM', 'SURFACE_DEFORM', 'CAST', 'CURVE', 'DISPLACE', 'HOOK',
                'LAPLACIANDEFORM', 'SHRINKWRAP', 'SIMPLE_DEFORM', 'SMOOTH', 'CORRECTIVE_SMOOTH', 'LAPLACIANSMOOTH',
                'WARP', 'WAVE', 'MESH_CACHE', 'MESH_SEQUENCE_CACHE'}
TOPOLOGY_TYPES = {'SUBSURF', 'MULTIRES', 'REMESH', 'DECIMATE', 'TRIANGULATE', 'WELD', 'BEVEL', 'SOLIDIFY', 'MIRROR',
                  'ARRAY', 'BOOLEAN', 'EDGE_SPLIT', 'SKIN', 'NODES', 'MASK', 'BUILD', 'SCREW', 'WIREFRAME'}


def _obj(x):
    if isinstance(x, bpy.types.Object): return x
    o = bpy.data.objects.get(x)
    if o is None: raise KeyError(f"object {x!r} not found")
    return o


def _armature_of(target):
    for m in target.modifiers:
        if m.type == 'ARMATURE' and m.object is not None and m.show_viewport:
            return m.object
    return None


def _weights(obj, group_name):
    me = obj.data; w = np.zeros(len(me.vertices), np.float64)
    vg = obj.vertex_groups.get(group_name) if group_name else None
    if vg is None: return None
    gi = vg.index
    for v in me.vertices:
        for g in v.groups:
            if g.group == gi: w[v.index] = g.weight; break
    return w


def fit_proxy(target, shape="ELLIPSOID", fit_group=None, inflate=1.0, center=None, radii=None, segments=64, rings=32,
              bone=None, armature=None, name=None):
    """Create/update a smooth ellipsoid proxy aligned to the target's rotation. center (world) / radii override the fit."""
    target = _obj(target); name = name or f"NRMPROXY_{target.name}"
    rot = target.matrix_world.to_quaternion().to_matrix()
    if center is None or radii is None:
        w = _weights(target, fit_group) if fit_group else None
        mw = target.matrix_world
        pts = [rot.transposed() @ (mw @ v.co) for v in target.data.vertices if w is None or w[v.index] >= 0.5]
        if not pts: raise ValueError(f"fit group {fit_group!r} selects no vertices")
        lo = Vector([min(p[i] for p in pts) for i in range(3)]); hi = Vector([max(p[i] for p in pts) for i in range(3)])
        c_rot = (lo + hi) / 2; half = (hi - lo) / 2
        center = rot @ c_rot if center is None else Vector(center)
        if radii is None:
            radii = Vector(half) * inflate
            if shape == "SPHERE": radii = Vector([max(half) * inflate] * 3)
    center, radii = Vector(center), Vector(radii)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=1.0)
    for v in bm.verts: v.co = Vector((v.co.x * radii.x, v.co.y * radii.y, v.co.z * radii.z))
    for f in bm.faces: f.smooth = True
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.get(name)
    if ob is not None and ob.type == 'MESH':
        old = ob.data; ob.data = me
        if old.users == 0: bpy.data.meshes.remove(old)
    else:
        ob = bpy.data.objects.new(name, me)
        (target.users_collection[0] if target.users_collection else bpy.context.scene.collection).objects.link(ob)
    ob.hide_render = True; ob.display_type = 'WIRE'
    for attr in ("visible_camera", "visible_shadow", "visible_diffuse", "visible_glossy"):
        if hasattr(ob, attr): setattr(ob, attr, False)
    world = Matrix.Translation(center) @ rot.to_4x4()
    if bone:
        arm = _obj(armature) if armature else _armature_of(target)
        if arm is None or bone not in arm.data.bones:
            raise ValueError(f"bone {bone!r}: no armature (pass armature= or give the target an Armature modifier)")
        ob.parent = arm; ob.parent_type = 'BONE'; ob.parent_bone = bone
        ob.matrix_parent_inverse = Matrix.Identity(4)
    else:
        ob.parent = None
    bpy.context.view_layer.update()
    ob.matrix_world = world
    bpy.context.view_layer.update()
    return ob


def _place(target, mod, place):
    mods = list(target.modifiers); cur = mods.index(mod)
    if place == "KEEP": return cur
    if place == "FIRST": dest = 0
    elif place == "LAST": dest = len(mods) - 1
    else:  # AFTER_DEFORM
        others = [m for m in mods if m != mod]
        last = max([i for i, m in enumerate(others) if m.type in DEFORM_TYPES], default=-1)
        dest = last + 1
    if dest != cur:
        target.modifiers.move(cur, dest)
    return dest


def add_transfer(target, proxy, vertex_group=None, name="NRM_Transfer", mix_factor=1.0, mapping="POLYINTERP_NEAREST",
                 place="AFTER_DEFORM"):
    target, proxy = _obj(target), _obj(proxy)
    mod = target.modifiers.get(name)
    if mod is not None and mod.type != 'DATA_TRANSFER':
        target.modifiers.remove(mod); mod = None
    if mod is None:
        mod = target.modifiers.new(name, 'DATA_TRANSFER')
    mod.object = proxy; mod.use_object_transform = True
    mod.use_loop_data = True; mod.data_types_loops = {'CUSTOM_NORMAL'}; mod.loop_mapping = mapping
    mod.mix_mode = 'REPLACE'; mod.mix_factor = mix_factor
    mod.vertex_group = vertex_group or ""
    _place(target, mod, place)
    return mod


def add_normal_edit(target, center_world, vertex_group=None, name="NRM_Radial", mix_factor=1.0, place="AFTER_DEFORM",
                    bone=None):
    target = _obj(target); ename = f"NRMCENTER_{target.name}"
    emp = bpy.data.objects.get(ename)
    if emp is None:
        emp = bpy.data.objects.new(ename, None); emp.empty_display_type = 'SPHERE'
        (target.users_collection[0] if target.users_collection else bpy.context.scene.collection).objects.link(emp)
    if bone:
        arm = _armature_of(target)
        emp.parent = arm; emp.parent_type = 'BONE'; emp.parent_bone = bone; emp.matrix_parent_inverse = Matrix.Identity(4)
        bpy.context.view_layer.update()
    emp.matrix_world = Matrix.Translation(Vector(center_world))
    mod = target.modifiers.get(name)
    if mod is not None and mod.type != 'NORMAL_EDIT':
        target.modifiers.remove(mod); mod = None
    if mod is None: mod = target.modifiers.new(name, 'NORMAL_EDIT')
    mod.mode = 'RADIAL'; mod.target = emp; mod.mix_mode = 'COPY'; mod.mix_factor = mix_factor
    mod.vertex_group = vertex_group or ""
    _place(target, mod, place)
    bpy.context.view_layer.update()
    return mod


class _ProxySampler:
    def __init__(self, proxy, dg):
        ev = proxy.evaluated_get(dg); me = ev.to_mesh()
        M = ev.matrix_world; N3 = M.to_3x3().inverted_safe().transposed()
        self.co = [M @ v.co for v in me.vertices]
        cn = np.empty(len(me.loops) * 3, np.float32); me.corner_normals.foreach_get("vector", cn); cn = cn.reshape(-1, 3)
        self.tris = [(tuple(t.vertices), tuple(t.loops)) for t in me.loop_triangles]
        self.cn = [(N3 @ Vector(n)).normalized() for n in cn]
        self.bvh = BVHTree.FromPolygons(self.co, [t[0] for t in self.tris])
        ev.to_mesh_clear()

    def normal(self, p):
        loc, _fn, idx, _d = self.bvh.find_nearest(p)
        (a, b, c), (la, lb, lc) = self.tris[idx]
        wa, wb, wc = poly_3d_calc([self.co[a], self.co[b], self.co[c]], loc)
        return (self.cn[la] * wa + self.cn[lb] * wb + self.cn[lc] * wc).normalized()


def _eval_corners(obj, dg):
    ev = obj.evaluated_get(dg); me = ev.to_mesh()
    nc, nv = len(me.loops), len(me.vertices)
    cv = np.empty(nc, np.int32); me.loops.foreach_get("vertex_index", cv)
    nrm = np.empty(nc * 3, np.float32); me.corner_normals.foreach_get("vector", nrm)
    co = np.empty(nv * 3, np.float32); me.vertices.foreach_get("co", co)
    M = np.array(ev.matrix_world, dtype=np.float64); R = M[:3, :3]
    co_w = co.reshape(-1, 3) @ R.T + M[:3, 3]
    n_w = nrm.reshape(-1, 3) @ np.linalg.inv(R)  # inverse-transpose applied to row vectors
    n_w /= np.maximum(np.linalg.norm(n_w, axis=1, keepdims=True), 1e-12)
    ev.to_mesh_clear()
    return {"nv": nv, "nc": nc, "cv": cv, "co": co_w, "n": n_w}


def _stats(a):
    if a.size == 0: return {"count": 0}
    return {"count": int(a.size), "mean": round(float(a.mean()), 3), "p95": round(float(np.percentile(a, 95)), 3),
            "max": round(float(a.max()), 3)}


def _ang(a, b):
    return np.degrees(np.arccos(np.clip((a * b).sum(axis=1), -1.0, 1.0)))


def _transfer_mods(target):
    return [m for m in target.modifiers if (m.type == 'DATA_TRANSFER' and m.use_loop_data and 'CUSTOM_NORMAL' in m.data_types_loops)
            or m.type == 'NORMAL_EDIT']


def _parent_chain(ob):
    while ob is not None:
        yield ob; ob = ob.parent


def measure(target, proxy=None, vertex_group=None, tol_in=2.0, tol_out=0.5, orig_corners=None, prefix=""):
    """Gate an existing setup. proxy: object whose surface normals are the goal (for NORMAL_EDIT pass the fitted proxy)."""
    target = _obj(target); proxy = _obj(proxy) if proxy else None
    defects, notes = [], []
    tmods = _transfer_mods(target)
    all_mods = list(target.modifiers)
    if not tmods and orig_corners is None:
        defects.append(prefix + "transfer_missing")
    for m in tmods:
        if not (m.show_viewport and m.show_render): defects.append(prefix + f"transfer_disabled:{m.name}")
        if m.vertex_group == "" : defects.append(prefix + f"no_mask:{m.name}")
        elif target.vertex_groups.get(m.vertex_group) is None: defects.append(prefix + f"mask_missing:{m.name}:{m.vertex_group}")
    last_t = max([all_mods.index(m) for m in tmods], default=-1)
    first_t = min([all_mods.index(m) for m in tmods], default=len(all_mods))
    after = [m for m in all_mods[last_t + 1:] if m.show_viewport] if tmods else []
    deform_after = [m.name for m in after if m.type in DEFORM_TYPES]
    if deform_after: defects.append(prefix + "deform_after_transfer:" + ",".join(deform_after))
    topo_before = [m.name for m in all_mods[:first_t] if m.show_viewport and m.type in TOPOLOGY_TYPES]
    arm = _armature_of(target)
    if arm is not None and not prefix:
        for m in tmods:
            src = m.object if m.type == 'DATA_TRANSFER' else m.target
            if src is not None and arm not in list(_parent_chain(src)):
                defects.append(f"proxy_not_following_rig:{m.name}:{src.name}")
    vg_name = vertex_group or next((m.vertex_group for m in tmods if m.vertex_group), None)
    w = _weights(target, vg_name) if vg_name else None
    if w is None:
        w = np.ones(len(target.data.vertices))  # unmasked: everything is "inside"
        if not any(d.startswith(prefix + "no_mask") for d in defects): defects.append(prefix + "no_mask")
    if (w >= 0.999).sum() == 0: defects.append(prefix + "mask_empty")
    sharp = target.data.attributes.get("sharp_face")
    if sharp is not None and not prefix:
        sf = np.zeros(len(target.data.polygons), bool); sharp.data.foreach_get("value", sf)
        pv = [p.vertices for p in target.data.polygons]
        nflat = sum(1 for i, p in enumerate(pv) if sf[i] and any(w[v] >= 0.5 for v in p))
        if nflat: notes.append(f"{nflat} flat-shaded faces in mask: custom normals still win (5.2), but Shade Flat/Smooth "
                               "by Angle or a Weighted Normal modifier later can reset them")
    # mute topology modifiers after the transfer while measuring
    muted = [m for m in after if m.type in TOPOLOGY_TYPES]
    for m in muted: m.show_viewport = False
    try:
        dg = bpy.context.evaluated_depsgraph_get(); dg.update()
        cur = _eval_corners(target, dg)
        if orig_corners is None:
            for m in tmods: m.show_viewport = False
            dg.update(); orig = _eval_corners(target, dg)
            for m in tmods: m.show_viewport = True
            dg.update()
        else:
            orig = orig_corners
    finally:
        for m in muted: m.show_viewport = True
        bpy.context.evaluated_depsgraph_get().update()
    res = {"weights_group": vg_name, "muted_while_measuring": [m.name for m in muted]}
    if cur["nv"] != len(w) or cur["nc"] != orig["nc"]:
        defects.append(prefix + "topology_changed:" + ",".join(topo_before))
        res.update({"inside": {"count": 0}, "outside": {"count": 0}, "defects": defects}); return res
    wc = w[cur["cv"]]
    inside, outside = wc >= 0.999, wc <= 0.001
    res["blend_corners"] = int((~inside & ~outside).sum())
    if proxy is not None and inside.any():
        smp = _ProxySampler(proxy, bpy.context.evaluated_depsgraph_get())
        vidx = np.unique(cur["cv"][inside])
        pn = np.zeros((cur["nv"], 3))
        for vi in vidx: pn[vi] = smp.normal(Vector(cur["co"][vi]))
        d_in = _ang(cur["n"][inside], pn[cur["cv"][inside]])
        res["inside"] = _stats(d_in)
        if d_in.size and res["inside"]["p95"] > tol_in: defects.append(prefix + f"inside_deviation:p95={res['inside']['p95']}>{tol_in}")
    else:
        res["inside"] = {"count": int(inside.sum()), "note": "no proxy given"}
    d_out = _ang(cur["n"][outside], orig["n"][outside])
    res["outside"] = _stats(d_out)
    if d_out.size and res["outside"]["max"] > tol_out: defects.append(prefix + f"outside_changed:max={res['outside']['max']}>{tol_out}")
    if not outside.any(): notes.append("no zero-weight corners: outside gate not measurable")
    res["defects"], res["notes"] = defects, notes
    return res


def _pose(arm, bone, axis, deg):
    pb = arm.pose.bones[bone]
    saved = (pb.rotation_mode, tuple(pb.rotation_euler), tuple(pb.rotation_quaternion))
    pb.rotation_mode = 'XYZ'; e = [0.0, 0.0, 0.0]; e["XYZ".index(axis)] = math.radians(deg); pb.rotation_euler = e
    bpy.context.view_layer.update()
    return pb, saved


def _unpose(pb, saved):
    pb.rotation_mode = saved[0]; pb.rotation_euler = saved[1]; pb.rotation_quaternion = saved[2]
    bpy.context.view_layer.update()


def normal_transfer(target, proxy="ELLIPSOID", vertex_group=None, fit_group=None, inflate=1.0, bone=None,
                    method="DATA_TRANSFER", mix_factor=1.0, mapping="POLYINTERP_NEAREST", place="AFTER_DEFORM",
                    apply=False, tol_in=2.0, tol_out=0.5, pose_bone=None, pose_deg=20.0, pose_axis="X",
                    measure_only=False, name=None):
    target = _obj(target); warnings = []
    if target.type != 'MESH': raise TypeError("target must be a mesh")
    if vertex_group and target.vertex_groups.get(vertex_group) is None:
        warnings.append(f"vertex group {vertex_group!r} not found on target: modifier would affect the WHOLE mesh")
    if not vertex_group:
        warnings.append("no vertex_group: the whole mesh gets proxy normals (hair line, neck, ears lose their shading)")
    if proxy in ("SPHERE", "ELLIPSOID"):
        pobj = bpy.data.objects.get(f"NRMPROXY_{target.name}") if measure_only else \
            fit_proxy(target, proxy, fit_group=fit_group, inflate=inflate, bone=bone)
    else:
        pobj = _obj(proxy) if proxy else None
    if pobj is None: raise ValueError("no proxy object (run without measure_only first)")
    if not measure_only:
        if method == "DATA_TRANSFER":
            add_transfer(target, pobj, vertex_group, name or "NRM_Transfer", mix_factor, mapping, place)
        elif method == "NORMAL_EDIT":
            add_normal_edit(target, pobj.matrix_world.translation, vertex_group, name or "NRM_Radial", mix_factor, place, bone)
        else:
            raise ValueError("method must be DATA_TRANSFER or NORMAL_EDIT")
    if target.data.shape_keys and apply:
        warnings.append("target has shape keys: applied normals are computed on the Basis and do not update with keys")
    rep = measure(target, pobj, vertex_group, tol_in, tol_out)
    if vertex_group and target.vertex_groups.get(vertex_group) is None:
        rep["defects"].insert(0, f"mask_missing:{vertex_group}")
    result = {"target": target.name, "proxy": pobj.name, "method": method,
              "stack": [(m.name, m.type) for m in target.modifiers], **rep}
    if pose_bone:
        arm = _armature_of(target)
        if arm is None or pose_bone not in arm.pose.bones:
            warnings.append(f"pose test skipped: no armature bone {pose_bone!r}")
        else:
            pb, saved = _pose(arm, pose_bone, pose_axis, pose_deg)
            try:
                posed = measure(target, pobj, vertex_group, tol_in, tol_out, prefix="posed_")
            finally:
                _unpose(pb, saved)
            result["posed"] = {"bone": pose_bone, "deg": pose_deg, "axis": pose_axis,
                               "inside": posed["inside"], "outside": posed["outside"]}
            result["defects"] += [d for d in posed["defects"] if d.startswith("posed_inside") or d.startswith("posed_outside")]
    if apply and not measure_only:
        tm = _transfer_mods(target)
        dg = bpy.context.evaluated_depsgraph_get()
        for m in tm: m.show_viewport = False
        dg.update(); orig = _eval_corners(target, dg)
        for m in tm: m.show_viewport = True
        deforms_before = [m.name for m in target.modifiers if m.type in DEFORM_TYPES and list(target.modifiers).index(m) < list(target.modifiers).index(tm[-1])]
        with bpy.context.temp_override(object=target, active_object=target, selected_objects=[target],
                                       selected_editable_objects=[target]):
            for m in tm: bpy.ops.object.modifier_apply(modifier=m.name)
        result["applied"] = [m for m in [x[0] for x in result["stack"]] if target.modifiers.get(m) is None]
        if deforms_before:
            warnings.append(f"applied after deform modifiers {deforms_before}: normals were computed on the REST mesh and now ride the deformation")
        after = measure(target, pobj, vertex_group, tol_in, tol_out, orig_corners=orig, prefix="applied_")
        result["after_apply"] = {"inside": after["inside"], "outside": after["outside"],
                                 "has_custom_normals": target.data.has_custom_normals}
    result["warnings"] = warnings
    result["passed"] = not result["defects"]
    return result


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="normal_transfer.py")
    p.add_argument("--target", required=True); p.add_argument("--proxy", default="ELLIPSOID")
    p.add_argument("--vgroup"); p.add_argument("--fit-group"); p.add_argument("--inflate", type=float, default=1.0)
    p.add_argument("--bone"); p.add_argument("--method", default="DATA_TRANSFER", choices=["DATA_TRANSFER", "NORMAL_EDIT"])
    p.add_argument("--mix", type=float, default=1.0); p.add_argument("--mapping", default="POLYINTERP_NEAREST")
    p.add_argument("--place", default="AFTER_DEFORM", choices=["AFTER_DEFORM", "KEEP", "FIRST", "LAST"])
    p.add_argument("--apply", action="store_true"); p.add_argument("--tol-in", type=float, default=2.0)
    p.add_argument("--tol-out", type=float, default=0.5); p.add_argument("--pose-bone")
    p.add_argument("--pose-deg", type=float, default=20.0); p.add_argument("--pose-axis", default="X", choices=list("XYZ"))
    p.add_argument("--measure-only", action="store_true"); p.add_argument("--name"); p.add_argument("--save")
    a = p.parse_args(argv)
    res = normal_transfer(a.target, a.proxy, a.vgroup, a.fit_group, a.inflate, a.bone, a.method, a.mix, a.mapping,
                          a.place, a.apply, a.tol_in, a.tol_out, a.pose_bone, a.pose_deg, a.pose_axis, a.measure_only, a.name)
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(a.save)); res["saved"] = a.save
    return res


if "NORMAL_TRANSFER_OPTS" in globals():  # live exec
    _o = dict(NORMAL_TRANSFER_OPTS)
    result = normal_transfer(_o.pop("target"), **_o)
    print("NORMAL_TRANSFER " + json.dumps(result))
elif __name__ == "__main__" and "--" in sys.argv and "--target" in sys.argv[sys.argv.index("--") + 1:]:
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print("NORMAL_TRANSFER " + json.dumps(result))
else:
    result = {"defined": ["fit_proxy", "add_transfer", "add_normal_edit", "measure", "normal_transfer"]}
