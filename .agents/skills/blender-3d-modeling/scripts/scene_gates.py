"""Structural gates for an assembly: floating parts, .L/.R chirality, sibling intersections, part coverage, 2.5D slabs.

Headless / CLI (prints one line: SCENE_GATES <json>):
    blender -b scene.blend --python scene_gates.py -- [--root Body] [--parts parts.json | --parts "Receiver,Barrel"]
        [--gap-tolerance 0.001] [--chirality-tol 0.002] [--no-intersections] [--allow-overlap Body,Lid ...]
        [--orbit | --no-orbit] [--orbit-min-ratio 0.12] [--explode-preview] [--save out.blend]
    parts.json: ["Receiver", "Barrel"] or {"parts": [...]}.
Live (Blender:execute_blender_code): set `GATE_OPTS` before exec -> `result` dict (same keys as the CLI, underscores):
    GATE_OPTS = {
        "root": None,               # name of the root object/empty; None = all visible meshes
        "parts": None,              # list of contract part names (case-insensitive substring match against object names)
        "gap_tolerance": 0.001,     # m: max gap between a child mesh and its parent mesh before it's "floating"
        "chirality_tol": 0.002,     # m: tolerance when checking .L/.R mirrors
        "check_intersections": True,# BVH overlap between sibling meshes (skips declared pairs)
        "allowed_overlaps": [],     # [["Body","Lid"], ...] intentional interpenetrations
        "orbit": True,              # projected-area collapse test at 8 azimuths (2.5D slab / card detector)
        "orbit_min_ratio": 0.12,    # a part whose min projected area / max projected area is below this is flagged
        "explode_preview": False,   # scale part pivots away from root by 1.6x (undo with ctrl+z / restore below)
    }
Exec without GATE_OPTS (and without CLI args) gates every visible mesh with the defaults (kept for existing workflows);
`run_gates(opts)` is also callable directly. Findings carry "FAIL"/"WARN" keys; missing inputs are listed under
'unevaluated' (never a pass). Limitations: attachment only checks mesh children against their nearest mesh ancestor;
chirality assumes the character faces -Y with left = +X and compares world-space vertices.
"""
import bpy, bmesh, math, re, sys, json, os
from mathutils import Vector
from mathutils.bvhtree import BVHTree

DEFAULTS = {"root": None, "parts": None, "gap_tolerance": 0.001, "chirality_tol": 0.002, "check_intersections": True,
            "allowed_overlaps": [], "orbit": True, "orbit_min_ratio": 0.12, "explode_preview": False}


def meshes_under(root):
    if root is None:
        return [o for o in bpy.data.objects if o.type == 'MESH' and o.visible_get()]
    r = bpy.data.objects.get(root)
    if not r:
        return []
    out = []

    def walk(o):
        for c in o.children:
            if c.type == 'MESH': out.append(c)
            walk(c)
    walk(r)
    if r.type == 'MESH': out.insert(0, r)
    return out


def run_gates(opts=None):
    O = dict(DEFAULTS); O.update(opts or {})
    dg = bpy.context.evaluated_depsgraph_get()
    bms = []

    def bvh_of(obj):
        ev = obj.evaluated_get(dg); me = ev.to_mesh()
        bm = bmesh.new(); bm.from_mesh(me); bm.transform(obj.matrix_world)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        tree = BVHTree.FromBMesh(bm); ev.to_mesh_clear(); bms.append(bm)
        return tree

    def world_verts(obj):
        ev = obj.evaluated_get(dg); me = ev.to_mesh()
        vs = [obj.matrix_world @ v.co for v in me.vertices]; ev.to_mesh_clear(); return vs

    objs = meshes_under(O["root"])
    result = {"objects_checked": [o.name for o in objs], "attachment": [], "chirality": [], "intersections": [],
              "part_coverage": {}, "orbit": [], "naming": [], "unevaluated": []}
    if O["root"] and not bpy.data.objects.get(O["root"]):
        result["unevaluated"].append(f"root object {O['root']!r} not found")
    elif not objs:
        result["unevaluated"].append("no meshes found under root")

    # ---- naming / transforms ----
    for o in objs:
        issues = []
        if re.match(r"^(Cube|Cylinder|Sphere|Plane|Mesh|Object)(\.\d+)?$", o.name): issues.append("default name")
        if " " in o.name: issues.append("space in name")
        if any(abs(s - 1) > 1e-6 for s in o.scale): issues.append("unapplied scale")
        if issues: result["naming"].append({"object": o.name, "issues": issues})

    # ---- attachment: child meshes must touch/overlap parent within tolerance; pivot near contact ----
    cache = {}

    def get_bvh(o):
        if o.name not in cache: cache[o.name] = bvh_of(o)
        return cache[o.name]

    for o in objs:
        p = o.parent
        while p is not None and p.type != 'MESH':
            p = p.parent
        if p is None or p not in objs:
            continue
        ptree = get_bvh(p)
        vs = world_verts(o)
        if not vs:
            continue
        dmin = min((ptree.find_nearest(v)[3] or 1e9) for v in vs)
        overlaps = get_bvh(o).overlap(ptree)
        pivot_gap = ptree.find_nearest(o.matrix_world.translation)[3]
        entry = {"child": o.name, "parent": p.name, "min_gap_m": round(dmin, 5), "overlapping": bool(overlaps),
                 "pivot_to_parent_m": round(pivot_gap, 4) if pivot_gap is not None else None}
        if not overlaps and dmin > O["gap_tolerance"]:
            entry["FAIL"] = f"floating: gap {dmin:.4f} m > tolerance"
        result["attachment"].append(entry)

    # ---- chirality: .L/.R pairs must be sagittal mirrors (x -> -x) ----
    pairs = {}
    for o in objs:
        m = re.match(r"^(.*)[._](L|R|l|r|left|right|Left|Right)$", o.name)
        if m:
            side = 'L' if m.group(2).lower().startswith('l') else 'R'
            pairs.setdefault(m.group(1), {})[side] = o
    for base, sides in pairs.items():
        if 'L' not in sides or 'R' not in sides:
            result["chirality"].append({"pair": base, "unevaluated": "missing counterpart"}); continue
        L, R = sides['L'], sides['R']
        vl, vr = world_verts(L), world_verts(R)
        e = {"pair": base, "L": L.name, "R": R.name, "vert_count_L": len(vl), "vert_count_R": len(vr)}
        if len(vl) != len(vr):
            e["FAIL"] = "vertex counts differ - not a mirrored copy"; result["chirality"].append(e); continue
        treeR = get_bvh(R)
        sample = vl[:: max(1, len(vl) // 200)]
        dev = [d for d in (treeR.find_nearest(Vector((-v.x, v.y, v.z)))[3] for v in sample) if d is not None]
        maxdev = max(dev) if dev else None
        # rotated-copy detector: rotating 180 deg about Z maps (x,y,z)->(-x,-y,z)
        devrot = [d for d in (treeR.find_nearest(Vector((-v.x, -v.y, v.z)))[3] for v in sample) if d is not None]
        maxrot = max(devrot) if devrot else None
        e.update({"max_mirror_deviation_m": round(maxdev, 5) if maxdev is not None else None,
                  "max_rotation_deviation_m": round(maxrot, 5) if maxrot is not None else None})
        if maxdev is not None and maxdev > O["chirality_tol"]:
            if maxrot is not None and maxrot < O["chirality_tol"]:
                e["FAIL"] = "pair is a 180 deg ROTATED copy, not a mirror - same handedness on both sides"
            else:
                e["WARN"] = "pair is not an exact mirror (asymmetric by design? check reference)"
        cl = sum(vl, Vector()) / len(vl); cr = sum(vr, Vector()) / len(vr)
        e["medial_lateral_ok"] = bool(cl.x > 0 > cr.x)   # left should be +X (character facing -Y)
        result["chirality"].append(e)

    # ---- intersections between siblings (unintentional) ----
    if O["check_intersections"]:
        allowed = {frozenset(p) for p in O["allowed_overlaps"]}
        for i, a in enumerate(objs):
            for b in objs[i + 1:]:
                if b.parent == a or a.parent == b or frozenset((a.name, b.name)) in allowed:
                    continue
                ov = get_bvh(a).overlap(get_bvh(b))
                if ov:
                    result["intersections"].append({"a": a.name, "b": b.name, "overlapping_tri_pairs": len(ov),
                                                    "WARN": "sibling meshes interpenetrate - declare in allowed_overlaps if intended"})

    # ---- part coverage ----
    if O["parts"]:
        cov = {"missing": [], "fused": [], "unassigned": []}
        assigned = {}
        for part in O["parts"]:
            key = part.lower().replace(" ", "")
            hits = [o.name for o in objs if key in o.name.lower().replace(" ", "").replace("_", "")]
            if not hits:
                cov["missing"].append(part)
            for h in hits:
                assigned.setdefault(h, []).append(part)
        for oname, parts in assigned.items():
            if len(parts) > 1:
                cov["fused"].append({"object": oname, "parts": parts, "FAIL": "one object matches several contract parts"})
        cov["unassigned"] = [o.name for o in objs if o.name not in assigned]
        cov["FAIL"] = bool(cov["missing"] or cov["fused"])
        cov["note"] = "proves you built what you planned, not that the plan was complete"
        result["part_coverage"] = cov
    else:
        result["unevaluated"].append("part coverage: no parts list given")

    # ---- orbit projected-area collapse (2.5D slab / card detector) ----
    if O["orbit"]:
        for o in objs:
            vs = world_verts(o)
            if len(vs) < 4: continue
            c = sum(vs, Vector()) / len(vs)
            areas = []
            for k in range(8):
                ang = k * math.pi / 4
                u = Vector((-math.sin(ang), math.cos(ang), 0)); w = Vector((0, 0, 1))
                xs = [(v - c).dot(u) for v in vs]; zs = [(v - c).dot(w) for v in vs]
                areas.append((max(xs) - min(xs)) * (max(zs) - min(zs)))
            mx = max(areas) or 1e-9; mn = min(areas)
            e = {"object": o.name, "min_over_max_projected_bbox_area": round(mn / mx, 3),
                 "thinnest_azimuth_deg": int(areas.index(mn) * 45)}
            if mn / mx < O["orbit_min_ratio"]:
                e["WARN"] = "projected footprint collapses at some azimuth - flat card/slab faking a volume? check cross-section"
            result["orbit"].append(e)

    # ---- explode preview ----
    if O["explode_preview"]:
        if not O["root"] or not bpy.data.objects.get(O["root"]):
            result["unevaluated"].append("explode_preview needs an existing root")
        else:
            center = bpy.data.objects[O["root"]].matrix_world.translation.copy(); moved = []
            for o in objs:
                if o.get("explode_with_parent") or o.name == O["root"]: continue
                o.matrix_world.translation = center + (o.matrix_world.translation - center) * 1.6; moved.append(o.name)
            result["explode_preview"] = {"moved": moved, "restore": "Ctrl+Z, or rerun without explode_preview on a reloaded file"}

    for bm in bms: bm.free()
    fails = sum(1 for sec in ("attachment", "chirality", "intersections", "orbit", "naming") for e in result[sec] if "FAIL" in e)
    fails += 1 if result["part_coverage"].get("FAIL") else 0
    warns = sum(1 for sec in ("attachment", "chirality", "intersections", "orbit") for e in result[sec] if "WARN" in e)
    result["fail_count"], result["warn_count"] = fails, warns
    result["summary"] = f"{len(objs)} meshes; {fails} FAIL, {warns} WARN; unevaluated: {result['unevaluated']}"
    return result


def _parts_arg(s):
    if s is None:
        return None
    if os.path.isfile(s):
        data = json.load(open(s, encoding="utf-8"))
        return list(data["parts"] if isinstance(data, dict) else data)
    return [p.strip() for p in s.split(",") if p.strip()]


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="scene_gates.py")
    p.add_argument("--root"); p.add_argument("--parts", help="JSON file (list or {'parts': [...]}) or comma list")
    p.add_argument("--gap-tolerance", type=float, default=DEFAULTS["gap_tolerance"])
    p.add_argument("--chirality-tol", type=float, default=DEFAULTS["chirality_tol"])
    p.add_argument("--no-intersections", action="store_true")
    p.add_argument("--allow-overlap", action="append", default=[], help="A,B (repeatable)")
    p.add_argument("--orbit", dest="orbit", action="store_true", default=True)
    p.add_argument("--no-orbit", dest="orbit", action="store_false")
    p.add_argument("--orbit-min-ratio", type=float, default=DEFAULTS["orbit_min_ratio"])
    p.add_argument("--explode-preview", action="store_true"); p.add_argument("--save")
    a = p.parse_args(argv)
    res = run_gates({"root": a.root, "parts": _parts_arg(a.parts), "gap_tolerance": a.gap_tolerance,
                     "chirality_tol": a.chirality_tol, "check_intersections": not a.no_intersections,
                     "allowed_overlaps": [s.split(",", 1) for s in a.allow_overlap], "orbit": a.orbit,
                     "orbit_min_ratio": a.orbit_min_ratio, "explode_preview": a.explode_preview})
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save)); res["saved"] = os.path.abspath(a.save)
    return res


_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if globals().get("GATE_OPTS") is not None:
    result = run_gates(GATE_OPTS)
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(_argv)
else:
    result = run_gates({})
print("SCENE_GATES " + json.dumps(result, default=str))
