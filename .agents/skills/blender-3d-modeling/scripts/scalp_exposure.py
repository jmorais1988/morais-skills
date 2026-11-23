"""Scalp exposure - geometric bald-patch check for hair: scalp samples with no hair geometry outside the skull.

Headless / CLI (prints one line: SCALP_EXPOSURE <json>):
    blender -b char.blend --python scalp_exposure.py -- --head Head --hair Hair,Bangs [--scalp-group scalp|none]
        [--max-dist 0.06] [--min-proud 0.001] [--hard-max-exposure 0.15] [--samples 600] [--seed 7]
Live (Blender:execute_blender_code): set `SCALP_OPTS` before exec -> `result` dict:
    SCALP_OPTS = {
        "head": "Head",             # mesh with the scalp region
        "scalp_group": "scalp",     # vertex group marking the scalp; None = faces with normal.z > 0.3 in the top 45 % of the head
        "hair": ["Hair"],           # hair objects: meshes, curves with bevel, or anything that converts to a mesh with faces
        "max_dist": 0.06,           # m: how far above the scalp to look for hair
        "min_proud": 0.001,         # m: hair must sit at least this far OUTSIDE the skull to count (sunk hair = bald)
        "hard_max_exposure": 0.15,  # fraction of scalp samples with no hair above -> FAIL
        "samples": 600, "seed": 7,
    }
Exec without SCALP_OPTS (and without CLI args) only defines scalp_exposure(opts) and sets result = {"defined": [...]}.
Counts only hair that is outside the skull along the scalp normal: a nearest-neighbour test passes hair that is
merely nearby but sunk below the surface. Silhouette comparison cannot see a bald crown (it's interior) and tone
comparison can't separate it from a colour shift - this is why it runs on geometry before any render.
Missing inputs return {"pass": None, "unevaluated": [...]} - never a pass. Strand hair curves without faces need a
Curve to Mesh / bevel proxy for the check.
"""
import bpy, bmesh, random, sys, json
from mathutils import Vector
from mathutils.bvhtree import BVHTree

DEFAULTS = {"head": "Head", "scalp_group": "scalp", "hair": ["Hair"], "max_dist": 0.06, "min_proud": 0.001,
            "hard_max_exposure": 0.15, "samples": 600, "seed": 7}


def scalp_exposure(opts=None):
    O = dict(DEFAULTS); O.update(opts or {})
    if isinstance(O["hair"], str):
        O["hair"] = [h for h in O["hair"].split(",") if h]
    rng = random.Random(O["seed"])
    result = {"pass": None, "unevaluated": []}
    dg = bpy.context.evaluated_depsgraph_get()

    head = bpy.data.objects.get(O["head"])
    if not head or head.type != 'MESH':
        result["unevaluated"].append(f"head mesh {O['head']!r} not found"); return result

    # --- scalp sample points (world) with normals ---
    ev = head.evaluated_get(dg); me = ev.to_mesh()
    mw = head.matrix_world; nm = mw.to_3x3().inverted().transposed()
    vg = head.vertex_groups.get(O["scalp_group"]) if O["scalp_group"] else None
    if O["scalp_group"] and vg is None:
        result["unevaluated"].append(f"vertex group {O['scalp_group']!r} not on {head.name}"); ev.to_mesh_clear(); return result
    gi = vg.index if vg else None
    zs = [(mw @ v.co).z for v in me.vertices]; zmin, zmax = min(zs), max(zs)
    faces = []
    for p in me.polygons:
        if gi is not None:
            ws = [next((g.weight for g in me.vertices[vi].groups if g.group == gi), 0.0) for vi in p.vertices]
            if sum(ws) / len(ws) < 0.5: continue
        else:
            n = (nm @ p.normal).normalized(); c = mw @ p.center
            if n.z < 0.3 or c.z < zmin + 0.55 * (zmax - zmin): continue  # upper head, upward-ish facing
        faces.append(p)
    if not faces:
        result["unevaluated"].append("no scalp faces found (check scalp_group)"); ev.to_mesh_clear(); return result
    areas = [p.area for p in faces]; total = sum(areas)
    pts = []
    for _ in range(O["samples"]):
        r = rng.random() * total; acc = 0
        for p, a in zip(faces, areas):
            acc += a
            if acc >= r:
                vs = [mw @ me.vertices[i].co for i in p.vertices]
                ws = [rng.random() for _ in vs]; s = sum(ws)
                pts.append((sum((v * (w / s) for v, w in zip(vs, ws)), Vector()), (nm @ p.normal).normalized())); break
    ev.to_mesh_clear()

    # --- hair geometry -> one BVH ---
    bm = bmesh.new(); hair_names = []
    for hn in O["hair"]:
        ho = bpy.data.objects.get(hn)
        if not ho:
            result["unevaluated"].append(f"hair object {hn!r} missing"); continue
        hev = ho.evaluated_get(dg)
        try:
            hme = hev.to_mesh()
        except Exception:
            result["unevaluated"].append(f"{hn}: cannot convert to mesh (hair curves need a Curve to Mesh / bevel proxy)"); continue
        if hme is None or len(hme.polygons) == 0:
            result["unevaluated"].append(f"{hn}: no faces (strand curves) - add a Curve to Mesh / bevel proxy for the check")
            hev.to_mesh_clear(); continue
        tmp = bmesh.new(); tmp.from_mesh(hme); tmp.transform(ho.matrix_world); bmesh.ops.triangulate(tmp, faces=tmp.faces)
        for f in tmp.faces:
            bm.faces.new([bm.verts.new(v.co) for v in f.verts])
        tmp.free(); hev.to_mesh_clear(); hair_names.append(hn)
    if not hair_names:
        result["unevaluated"].append("no usable hair geometry"); bm.free(); return result
    tree = BVHTree.FromBMesh(bm)

    # --- exposure: ray from scalp point outward along normal; count hair hits beyond min_proud ---
    exposed = 0; hits = []
    for pt, n in pts:
        hit = tree.ray_cast(pt + n * O["min_proud"], n, O["max_dist"])
        if hit[0] is None:
            exposed += 1
        else:
            hits.append(hit[3])
    bm.free()
    frac = exposed / len(pts)
    result.update({"head": head.name, "hair": hair_names, "scalp_samples": len(pts), "exposed_samples": exposed,
                   "exposure_fraction": round(frac, 3), "hard_max": O["hard_max_exposure"],
                   "pass": frac <= O["hard_max_exposure"],
                   "mean_hair_offset_m": round(sum(hits) / len(hits), 4) if hits else None,
                   "summary": f"scalp exposure {frac:.1%} over {len(pts)} samples -> "
                              f"{'PASS' if frac <= O['hard_max_exposure'] else 'FAIL'} (max {O['hard_max_exposure']:.0%})",
                   "note": "a coverage shortfall never justifies widening locks - they slide off the skull; add/adjust roots instead"})
    return result


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="scalp_exposure.py")
    p.add_argument("--head", default=DEFAULTS["head"]); p.add_argument("--hair", default="Hair", help="comma list")
    p.add_argument("--scalp-group", default="scalp", help="vertex group name, or 'none' for the normal/height heuristic")
    for k in ("max-dist", "min-proud", "hard-max-exposure"):
        p.add_argument("--" + k, type=float, default=DEFAULTS[k.replace("-", "_")])
    p.add_argument("--samples", type=int, default=600); p.add_argument("--seed", type=int, default=7)
    a = vars(p.parse_args(argv))
    a = {k.replace("-", "_"): v for k, v in a.items()}
    if str(a["scalp_group"]).lower() == "none": a["scalp_group"] = None
    return scalp_exposure(a)


_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if globals().get("SCALP_OPTS") is not None:
    result = scalp_exposure(SCALP_OPTS)
    print("SCALP_EXPOSURE " + json.dumps(result))
elif __name__ == "__main__" and "--head" in _argv:
    result = _cli(_argv)
    print("SCALP_EXPOSURE " + json.dumps(result))
else:
    result = {"defined": ["scalp_exposure"]}
