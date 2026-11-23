"""Archviz shell from a JSON floor plan: mitred walls with thickness, live boolean openings (windows/doors) with frames,
glass panes (single plane + Principled Thin Wall on 5.2+; 6 mm solid pane fallback on older versions) and hinged door leaves, floor/ceiling slabs that overlap the walls (no light leaks), per-room floor
finishes, world-scale box UVs (1 UV unit = 1 m) and placeholder materials. Verifies every opening by ray casts.

Headless / CLI (prints one JSON line = the result dict):
    blender -b [scene.blend] --python plan_to_rooms.py -- --plan plan.json [--save out.blend]
Live (Blender:execute_blender_code): set before exec
    PLAN_OPTS = {"plan": {...plan dict...} or "path/plan.json"}        -> `result` dict
Without PLAN_OPTS the file only defines build_from_plan / example_plan.

Plan format (metres, Z up, plan coordinates on the XY plane; see example_plan()):
    {"level": "L0", "height": 2.7, "thickness": 0.12, "floor_thickness": 0.25, "ceiling_thickness": 0.25,
     "floor_finish": 0.015, "boolean_solver": "EXACT", "live_openings": true,
     "walls": [{"id": "EXT", "path": [[x, y], ...], "closed": true, "thickness": 0.3, "align": "center|left|right"}],
     "openings": [{"id": "WIN1", "wall": "EXT", "segment": 0, "offset": 1.0, "width": 2.4, "height": 1.5, "sill": 0.9,
                   "type": "window|door|void", "frame": 0.06, "frame_depth": 0.08, "inset": 0.0, "glass": 0.006,
                   "open_deg": 0, "hinge": "left|right"}],
     "rooms": [{"name": "Studio", "polygon": [[x, y], ...]}]}
  offset = distance along the segment's wall path from its start point to the opening's near edge.
  align: path is the wall's centre line, or its left/right face (left = +90 deg from the segment direction).
  Room polygons may use wall centre lines: finishes extend under the walls instead of meeting them coplanar.

Design choices: exterior slabs cover the walls' outer footprint so wall/ceiling junctions are closed volumes; openings
are Boolean modifiers driven by a hidden cutter parented to an OPN_<id> empty together with frame/glass/leaf, so moving
the empty moves the whole opening (set live_openings=false to apply the booleans). Door leaves have their origin on the
hinge axis. Limitations: straight segments only (sample arcs into points), one storey per call, no stairs/roofs.
"""
import bpy, bmesh, json, math, sys
from mathutils import Vector, Matrix

MATS = {  # name: (base color, roughness, extra) -- neutral placeholders with plausible albedo
    "MAT_Wall_Paint": ((0.80, 0.80, 0.78), 0.85, {}),
    "MAT_Ceiling_Paint": ((0.82, 0.82, 0.82), 0.9, {}),
    "MAT_Slab_Concrete": ((0.45, 0.44, 0.42), 0.8, {}),
    "MAT_Floor_Finish": ((0.42, 0.30, 0.20), 0.45, {}),
    "MAT_Frame": ((0.12, 0.12, 0.12), 0.4, {}),
    "MAT_Door": ((0.70, 0.68, 0.64), 0.5, {}),
    "MAT_Glass": ((1.0, 1.0, 1.0), 0.0, {"Transmission Weight": 1.0, "IOR": 1.5, "Thin Wall": True}),  # Thin Wall: 5.2+
}


def example_plan():
    """6 x 3.5 m studio, 2.6 m ceiling, exterior walls 0.3 m, one window, one door, one partition."""
    return {"level": "L0", "height": 2.6, "thickness": 0.12,
            "walls": [{"id": "EXT", "path": [[0, 0], [6, 0], [6, 3.5], [0, 3.5]], "closed": True, "thickness": 0.3},
                      {"id": "P1", "path": [[4.2, 3.5], [4.2, 1.6]], "closed": False, "thickness": 0.1}],
            "openings": [{"id": "WIN1", "wall": "EXT", "segment": 0, "offset": 1.2, "width": 2.0, "height": 1.4, "sill": 0.9, "type": "window"},
                         {"id": "DOOR1", "wall": "EXT", "segment": 3, "offset": 0.8, "width": 0.9, "height": 2.1, "sill": 0.0,
                          "type": "door", "open_deg": 30}],
            "rooms": [{"name": "Studio", "polygon": [[0, 0], [6, 0], [6, 3.5], [0, 3.5]]}]}


# ---------------------------------------------------------------- helpers
def _mat(name):
    m = bpy.data.materials.get(name)
    if m:
        return m
    col, rough, extra = MATS[name]
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True  # deprecated/no-op in 5.x, required before
    except Exception:
        pass
    bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*col, 1.0)
        bsdf.inputs["Roughness"].default_value = rough
        for k, v in extra.items():
            if k in bsdf.inputs:
                bsdf.inputs[k].default_value = v
    m.diffuse_color = (*col, 1.0 if name != "MAT_Glass" else 0.3)
    return m


def _coll(name, parent):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in parent.children:
        parent.children.link(c)
    return c


def _obj(name, me, coll, mat=None):
    old = bpy.data.objects.get(name)
    if old:
        bpy.data.objects.remove(old)
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    if mat and me is not None:
        me.materials.append(_mat(mat))
    return o


def _box_uv(bm, mw=Matrix.Identity(4)):
    """World-scale box projection: 1 UV unit = 1 metre, axis picked by dominant face normal."""
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        n = (mw.to_3x3() @ f.normal)
        ax = max(range(3), key=lambda i: abs(n[i]))
        for l in f.loops:
            w = mw @ l.vert.co
            l[uv].uv = (w.y, w.z) if ax == 0 else (w.x, w.z) if ax == 1 else (w.x, w.y)


def _box(bm, cx, cy, cz, sx, sy, sz, mat=Matrix.Identity(4)):
    r = bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.transform(bm, verts=r["verts"], matrix=mat @ Matrix.Translation((cx, cy, cz)) @ Matrix.Diagonal((sx, sy, sz, 1)))


def _offset_path(pts, closed, t, align):
    """Left/right face polylines of a wall path with mitred joins (miter length capped at 4x thickness)."""
    P = [Vector((p[0], p[1], 0)) for p in pts]
    n = len(P)
    hl, hr = {"center": (t / 2, t / 2), "left": (0.0, t), "right": (t, 0.0)}[align]
    L, R = [], []
    for i in range(n):
        prev = P[i - 1] if (closed or i > 0) else None
        nxt = P[(i + 1) % n] if (closed or i < n - 1) else None
        ds = []
        if prev is not None: ds.append((P[i] - prev).normalized())
        if nxt is not None: ds.append((nxt - P[i]).normalized())
        norms = [Vector((-d.y, d.x, 0)) for d in ds]
        m = sum(norms, Vector()).normalized()
        c = max(m.dot(norms[0]), 0.25)
        L.append(P[i] + m * (hl / c))
        R.append(P[i] - m * (hr / c))
    return P, L, R


def _wall_mesh(name, pts, closed, t, h, align):
    P, L, R = _offset_path(pts, closed, t, align)
    n = len(P)
    bm = bmesh.new()
    Lb = [bm.verts.new(v) for v in L]; Lt = [bm.verts.new(v + Vector((0, 0, h))) for v in L]
    Rb = [bm.verts.new(v) for v in R]; Rt = [bm.verts.new(v + Vector((0, 0, h))) for v in R]
    segs = range(n) if closed else range(n - 1)
    for i in segs:
        j = (i + 1) % n
        bm.faces.new((Lb[i], Lb[j], Lt[j], Lt[i]))
        bm.faces.new((Rb[j], Rb[i], Rt[i], Rt[j]))
        bm.faces.new((Lt[i], Lt[j], Rt[j], Rt[i]))
        bm.faces.new((Lb[j], Lb[i], Rb[i], Rb[j]))
    if not closed:
        bm.faces.new((Rb[0], Lb[0], Lt[0], Rt[0]))
        bm.faces.new((Lb[-1], Rb[-1], Rt[-1], Lt[-1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    _box_uv(bm)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    return me, P, L, R


def _outline(walls):
    """Outer footprint of all walls (union of wall face polylines) as convex-safe bbox polygon per closed wall."""
    xs, ys = [], []
    for _, _, L, R in walls:
        for v in L + R:
            xs.append(v.x); ys.append(v.y)
    return min(xs), min(ys), max(xs), max(ys)


def _slab(name, poly_or_bbox, z0, z1, coll, mat):
    bm = bmesh.new()
    if isinstance(poly_or_bbox, tuple):
        x0, y0, x1, y1 = poly_or_bbox
        poly = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    else:
        poly = poly_or_bbox
    vs = [bm.verts.new((x, y, z0)) for x, y in poly]
    f = bm.faces.new(vs)
    bmesh.ops.recalc_face_normals(bm, faces=[f])
    r = bmesh.ops.extrude_face_region(bm, geom=[f])
    top = [e for e in r["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=top, vec=(0, 0, z1 - z0))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    _box_uv(bm)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    return _obj(name, me, coll, mat)


def _poly_area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))) / 2


# ---------------------------------------------------------------- main
def build_from_plan(plan, scene=None):
    if isinstance(plan, str):
        with open(bpy.path.abspath(plan), encoding="utf-8") as f:
            plan = json.load(f)
    scene = scene or bpy.context.scene
    lvl = plan.get("level", "L0")
    H = float(plan.get("height", 2.7)); T = float(plan.get("thickness", 0.12))
    ft = float(plan.get("floor_thickness", 0.25)); ct = float(plan.get("ceiling_thickness", 0.25))
    fin = float(plan.get("floor_finish", 0.015)); solver = plan.get("boolean_solver", "EXACT")
    live = bool(plan.get("live_openings", True))
    root = _coll(f"ARCH_{lvl}", scene.collection)
    cw, co, cs, cf, cc = (_coll(f"{lvl}_{k}", root) for k in ("Walls", "Openings", "Slabs", "Floors", "Cutters"))
    cc.hide_render = True; cc.hide_viewport = True
    warnings, report = [], {"level": lvl, "blender": bpy.app.version_string, "walls": [], "openings": [], "rooms": []}

    walls = {}
    for w in plan["walls"]:
        t = float(w.get("thickness", T)); h = float(w.get("height", H)); closed = bool(w.get("closed", False))
        me, P, L, R = _wall_mesh(f"WALL_{lvl}_{w['id']}", w["path"], closed, t, h, w.get("align", "center"))
        o = _obj(f"WALL_{lvl}_{w['id']}", me, cw, "MAT_Wall_Paint")
        walls[w["id"]] = (o, P, L, R, t, h, closed, w.get("align", "center"))
        segs = len(P) if closed else len(P) - 1
        report["walls"].append({"id": w["id"], "object": o.name, "thickness": t, "height": h, "segments": segs,
                                "centre_length": round(sum((P[(i + 1) % len(P)] - P[i]).length for i in range(segs)), 3)})

    for op in plan.get("openings", []):
        wo, P, L, R, t, h, closed, align = walls[op["wall"]]
        seg = int(op.get("segment", 0)); a = P[seg]; b = P[(seg + 1) % len(P)]
        d = (b - a).normalized(); nrm = Vector((-d.y, d.x, 0)); seglen = (b - a).length
        typ = op.get("type", "window"); wdt = float(op["width"]); hgt = float(op["height"])
        sill = float(op.get("sill", 0.0 if typ == "door" else 0.9)); off = float(op.get("offset", 0.0))
        fr = float(op.get("frame", 0.06 if typ != "void" else 0.0)); fd = float(op.get("frame_depth", 0.08))
        centre_shift = {"center": 0.0, "left": -t / 2, "right": t / 2}[align]
        inset = float(op.get("inset", 0.0))
        s = off + wdt / 2
        c = a + d * s + nrm * (centre_shift + inset)
        if off < 0 or off + wdt > seglen:
            warnings.append(f"{op['id']}: opening [{off}, {off + wdt}] exceeds segment length {seglen:.3f}")
        if off < t or seglen - (off + wdt) < t:
            warnings.append(f"{op['id']}: opening within one wall thickness of a corner (frame/lintel will clash)")
        if sill + hgt > h - 0.05:
            warnings.append(f"{op['id']}: head at {sill + hgt:.2f} m leaves <5 cm lintel under a {h} m wall")
        basis = Matrix(((d.x, nrm.x, 0, c.x), (d.y, nrm.y, 0, c.y), (0, 0, 1, 0), (0, 0, 0, 1)))
        name = f"OPN_{lvl}_{op['id']}"
        emp = bpy.data.objects.get(name)
        if emp: bpy.data.objects.remove(emp)
        emp = bpy.data.objects.new(name, None); emp.empty_display_type = 'ARROWS'; emp.empty_display_size = 0.3
        co.objects.link(emp); emp.matrix_world = basis
        # cutter
        bm = bmesh.new(); _box(bm, 0, 0, sill + hgt / 2, wdt, t + 0.2, hgt)
        cme = bpy.data.meshes.new(f"CUT_{lvl}_{op['id']}"); bm.to_mesh(cme); bm.free()
        cut = _obj(f"CUT_{lvl}_{op['id']}", cme, cc); cut.display_type = 'WIRE'; cut.parent = emp
        mod = wo.modifiers.new(f"Opening_{op['id']}", 'BOOLEAN'); mod.operation = 'DIFFERENCE'; mod.object = cut
        if hasattr(mod, "solver"):
            try: mod.solver = solver
            except TypeError: warnings.append(f"boolean solver {solver} unavailable, using {mod.solver}")
        parts = {}
        if typ != "void" and fr > 0:
            bm = bmesh.new()
            _box(bm, -wdt / 2 + fr / 2, 0, sill + hgt / 2, fr, fd, hgt)          # jambs
            _box(bm, wdt / 2 - fr / 2, 0, sill + hgt / 2, fr, fd, hgt)
            _box(bm, 0, 0, sill + hgt - fr / 2, wdt - 2 * fr, fd, fr)            # head
            if typ == "window":
                _box(bm, 0, 0, sill + fr / 2, wdt - 2 * fr, fd, fr)              # sill rail
            _box_uv(bm)
            fme = bpy.data.meshes.new(f"FRAME_{lvl}_{op['id']}"); bm.to_mesh(fme); bm.free()
            parts["frame"] = _obj(f"FRAME_{lvl}_{op['id']}", fme, co, "MAT_Frame")
        if typ == "window":
            thin_ok = "Thin Wall" in [s.name for s in next(n for n in _mat("MAT_Glass").node_tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs]
            g = float(op.get("glass", 0.0 if thin_ok else 0.006))  # 5.2+: single plane + Thin Wall; older: 6 mm solid pane
            bm = bmesh.new()
            if g > 0:
                _box(bm, 0, 0, sill + hgt / 2, wdt - 2 * fr, g, hgt - 2 * fr)
            else:  # single plane: correct with Principled Thin Wall (5.2+); without it refraction bends the view
                bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5,
                                      matrix=Matrix.Translation((0, 0, sill + hgt / 2)) @ Matrix.Rotation(math.pi / 2, 4, 'X')
                                      @ Matrix.Diagonal((wdt - 2 * fr, hgt - 2 * fr, 1, 1)))
            gme = bpy.data.meshes.new(f"GLASS_{lvl}_{op['id']}"); bm.to_mesh(gme); bm.free()
            parts["glass"] = _obj(f"GLASS_{lvl}_{op['id']}", gme, co, "MAT_Glass")
        if typ == "door":
            lw, lh, lt, gap = wdt - 2 * fr - 0.006, hgt - fr - 0.008, 0.04, 0.003
            hinge_left = op.get("hinge", "left") == "left"
            hx = -wdt / 2 + fr + gap if hinge_left else wdt / 2 - fr - gap
            bm = bmesh.new(); _box(bm, (lw / 2) if hinge_left else (-lw / 2), 0, lh / 2, lw, lt, lh)
            _box_uv(bm)
            lme = bpy.data.meshes.new(f"DOOR_{lvl}_{op['id']}"); bm.to_mesh(lme); bm.free()
            leaf = _obj(f"DOOR_{lvl}_{op['id']}", lme, co, "MAT_Door")
            leaf.parent = emp
            leaf.matrix_parent_inverse = Matrix.Identity(4)
            leaf.location = (hx, 0, sill + 0.008)
            leaf.rotation_euler = (0, 0, math.radians(float(op.get("open_deg", 0))) * (1 if hinge_left else -1))
            parts["leaf"] = leaf
        for k, p in parts.items():
            if p.parent is None:
                p.parent = emp
        report["openings"].append({"id": op["id"], "type": typ, "wall": wo.name, "segment": seg, "width": wdt, "height": hgt,
                                   "sill": sill, "head": round(sill + hgt, 3), "empty": emp.name,
                                   "parts": {k: v.name for k, v in parts.items()}, "_centre": c, "_normal": nrm, "_t": t})

    # slabs over the full wall footprint -> wall/slab junctions are closed
    bbox = _outline([(None, v[1], v[2], v[3]) for v in walls.values()])
    _slab(f"SLAB_{lvl}_Floor", bbox, -ft, 0.0, cs, "MAT_Slab_Concrete")
    top = max(v[5] for v in walls.values())
    ceil = _slab(f"SLAB_{lvl}_Ceiling", bbox, top, top + ct, cs, "MAT_Ceiling_Paint")
    for rm in plan.get("rooms", []):
        o = _slab(f"FLR_{lvl}_{rm['name']}", [tuple(p) for p in rm["polygon"]], 0.0, fin, cf, "MAT_Floor_Finish")
        report["rooms"].append({"name": rm["name"], "object": o.name, "plan_area_m2": round(_poly_area(rm["polygon"]), 3)})

    # evaluate + verify openings by ray casts on the evaluated scene
    vl = bpy.context.view_layer; vl.update()
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    for rep in report["openings"]:
        c, nrm, t = rep.pop("_centre"), rep.pop("_normal"), rep.pop("_t")
        wall = bpy.data.objects[rep["wall"]]
        glass = rep["parts"].get("glass"); leaf = rep["parts"].get("leaf")
        mid_z = rep["sill"] + rep["height"] / 2
        origin = Vector((c.x, c.y, mid_z)) + nrm * (t + 0.5)
        hits = []
        loc = origin; remaining = 2 * t + 1.0
        for _ in range(8):
            hit, hloc, _, _, ob, _ = scene.ray_cast(dg, loc, -nrm, distance=remaining)
            if not hit: break
            hits.append(ob.original.name)
            remaining -= (hloc - loc).length + 1e-4; loc = hloc - nrm * 1e-4
        wall_hit = wall.name in hits
        beside = Vector((c.x, c.y, mid_z)) + nrm * (t + 0.5) + (Vector((nrm.y, -nrm.x, 0)) * (rep["width"] / 2 + 0.15))
        hit_b, _, _, _, ob_b, _ = scene.ray_cast(dg, beside, -nrm, distance=2 * t + 1.0)
        rep["cut_verified"] = (not wall_hit) and hit_b and ob_b.original.name == wall.name
        rep["ray_hits_through_centre"] = hits
        if not rep["cut_verified"]:
            warnings.append(f"{rep['id']}: opening not cut cleanly (centre hits {hits}, beside hits {ob_b.original.name if hit_b else None})")

    if not live:
        for o, *_ in walls.values():
            ev = o.evaluated_get(dg)
            me = bpy.data.meshes.new_from_object(ev)
            old = o.data; o.modifiers.clear(); o.data = me; bpy.data.meshes.remove(old)
        for ob in list(cc.objects):
            bpy.data.objects.remove(ob)
    tris = 0
    for ob in root.all_objects:
        if ob.type == 'MESH':
            ev = ob.evaluated_get(dg); m = ev.to_mesh(); tris += sum(len(p.vertices) - 2 for p in m.polygons); ev.to_mesh_clear()
    report.update({"collection": root.name, "slab_bbox": [round(x, 3) for x in bbox], "ceiling_top": top, "tris": tris,
                   "live_openings": live, "warnings": warnings})
    return report


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="plan_to_rooms.py")
    p.add_argument("--plan", help="plan JSON path; omit to build example_plan()"); p.add_argument("--save")
    a = p.parse_args(argv)
    res = build_from_plan(a.plan or example_plan())
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(a.save)); res["saved"] = a.save
    return res


if "PLAN_OPTS" in globals():  # live exec
    result = build_from_plan(PLAN_OPTS["plan"])
    print(json.dumps(result))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print("PLAN_TO_ROOMS " + json.dumps(result))
else:
    result = {"defined": ["build_from_plan", "example_plan"]}
