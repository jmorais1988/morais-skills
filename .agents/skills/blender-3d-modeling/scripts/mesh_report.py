"""Topology & hygiene audit for meshes (numpy fast path; scale-relative tolerances).

Live (Blender:execute_blender_code): set `REPORT_OPTS` (alias `MESH_REPORT_OPTS`) before exec, or exec as-is to audit
the selection (or all visible meshes if nothing is selected):
    REPORT_OPTS = {
        "objects": None,          # list of object names; None = selected, or all visible meshes if nothing selected
        "evaluated": False,       # True = audit with modifiers applied (what gets exported)
        "budget_tris": None,      # int; flags objects over budget
        "select_problems": False, # select offending verts/edges/faces in edit mode on the first object
        "curvature_tri_check": True,  # flag triangles/ngons on non-flat regions
        "rel_tol": 1e-5,          # merge/duplicate tolerance = local bbox diagonal x rel_tol ...
        "abs_tol": None,          # ... unless an absolute tolerance (mesh units, = m with scale applied) is given
    }
    -> `result` dict {"summary", "total_tris", "reports": [...], "seconds"} and a printed human summary.
    Set MESH_REPORT_DEFINE_ONLY = True before exec to only define audit()/run_report() without running.
Headless / CLI (prints one line: MESH_REPORT <json>):
    blender -b file.blend --python mesh_report.py -- [--objects A,B] [--evaluated] [--budget-tris N]
        [--rel-tol 1e-5] [--abs-tol 0.0001] [--no-curvature] [--json-out report.json]

Tolerances: duplicate verts = coordinates quantized to `tol` on two half-cell-offset grids (max of both counts; pairs
up to ~tol*sqrt(3) apart can count); degenerate faces = area < tol^2; non-planar ngon = max vertex offset from the
face plane > max(1e-4*sqrt(face area), 5*tol). With a 1-2 m object these equal the old absolute values (1e-5 m
rounding, 1e-10 m^2, 1e-4 m); on a 20 mm part they shrink ~100x so sub-0.1 mm features are not flagged or merged.
All arrays come from foreach_get on generic attributes (no per-element Python): 4M tris 2.6 s vs 14.9 s for the
previous bmesh loop, 8M tris 6.1 s (5.2, synthetic triangulated torus).
Limitations: "inward_facing_faces_heuristic" compares each face normal with the direction from the mesh centroid, so it
is meaningless on non-convex or open shapes (use scripts/mesh_repair.py analyze for a welded consistency check).
"""
import bpy, bmesh, math, json, sys, time
import numpy as np
from collections import Counter

DEFAULTS = {"objects": None, "evaluated": False, "budget_tris": None, "select_problems": False,
            "curvature_tri_check": True, "rel_tol": 1e-5, "abs_tol": None}
OPTS = dict(DEFAULTS)
OPTS.update(globals().get("REPORT_OPTS") or globals().get("MESH_REPORT_OPTS") or {})


def target_objects(names=None):
    if names:
        return [bpy.data.objects[n] for n in names if n in bpy.data.objects and bpy.data.objects[n].type == 'MESH']
    sel = [o for o in bpy.context.selected_objects if o.type == 'MESH']
    return sel or [o for o in bpy.data.objects if o.type == 'MESH' and o.visible_get()]


def _get(coll, attr, n, dtype, width=1):
    a = np.empty(n * width, dtype)
    if n:
        coll.foreach_get(attr, a)
    return a.reshape(-1, width) if width > 1 else a


def _dup_count(co, tol):
    """Approximate duplicate-vertex count: quantize to tol on two grids offset by half a cell, take the larger count."""
    if len(co) < 2 or tol <= 0:
        return 0
    best = 0
    for off in (0.0, 0.5):
        q = np.floor(co / tol + off).astype(np.int64)
        q -= q.min(0)
        if q.max() < (1 << 21):  # pack into one int64 key: 1-D sort is ~5x faster than lexsort
            key = np.sort((q[:, 0] << 42) | (q[:, 1] << 21) | q[:, 2])
            uniq = 1 + int(np.count_nonzero(key[1:] != key[:-1]))
        else:
            s = q[np.lexsort((q[:, 2], q[:, 1], q[:, 0]))]
            uniq = 1 + int(np.count_nonzero(np.any(s[1:] != s[:-1], axis=1)))
        best = max(best, len(co) - uniq)
    return best


def audit(obj, opts=None):
    o_ = dict(OPTS); o_.update(opts or {})
    t0 = time.perf_counter()
    owner = None
    if o_["evaluated"]:
        dg = bpy.context.evaluated_depsgraph_get()
        owner = obj.evaluated_get(dg)
        me = owner.to_mesh()
    else:
        me = obj.data
    try:
        nv, ne, nf, nl = len(me.vertices), len(me.edges), len(me.polygons), len(me.loops)
        at = me.attributes
        # generic attributes (position, .corner_vert, ...) read 2-100x faster than MeshVertex/MeshLoop properties
        co = (_get(at["position"].data, "vector", nv, np.float32, 3) if "position" in at
              else _get(me.vertices, "co", nv, np.float32, 3)).astype(np.float64)
        ev = (_get(at[".edge_verts"].data, "value", ne, np.int32, 2) if ".edge_verts" in at
              else _get(me.edges, "vertices", ne, np.int32, 2)).astype(np.int64)
        ls = _get(me.polygons, "loop_start", nf, np.int32).astype(np.int64)
        lt = np.diff(np.append(ls, nl)) if nf else np.zeros(0, np.int64)
        area = _get(me.polygons, "area", nf, np.float32).astype(np.float64)
        fnor = _get(me.polygon_normals, "vector", nf, np.float32, 3).astype(np.float64)
        fcen = _get(me.polygons, "center", nf, np.float32, 3).astype(np.float64)
        smooth = ~_get(at["sharp_face"].data, "value", nf, bool) if "sharp_face" in at else np.ones(nf, bool)
        lv = (_get(at[".corner_vert"].data, "value", nl, np.int32) if ".corner_vert" in at
              else _get(me.loops, "vertex_index", nl, np.int32)).astype(np.int64)
        le = (_get(at[".corner_edge"].data, "value", nl, np.int32) if ".corner_edge" in at
              else _get(me.loops, "edge_index", nl, np.int32)).astype(np.int64)

        size = float(np.linalg.norm(co.max(0) - co.min(0))) if nv else 0.0
        tol = float(o_["abs_tol"]) if o_.get("abs_tol") else float(o_["rel_tol"]) * size
        tol = tol if tol > 0 else 1e-9

        face_sizes = Counter({int(k): int(v) for k, v in enumerate(np.bincount(np.minimum(lt, 5), minlength=6)) if v})
        tris = int(lt.sum() - 2 * nf)
        valence = np.bincount(ev.ravel(), minlength=nv) if ne else np.zeros(nv, np.int64)
        has_face = np.bincount(lv, minlength=nv) > 0 if nl else np.zeros(nv, bool)
        pole_mask = (valence != 4) & (valence != 0) & ~(((valence == 1) | (valence == 2)) & has_face)
        poles = Counter({int(k): int(v) for k, v in enumerate(np.bincount(valence[pole_mask])) if v}) if pole_mask.any() else Counter()
        bad_pole_verts = np.flatnonzero(pole_mask & (valence >= 6))
        efc = np.bincount(le, minlength=ne) if nl else np.zeros(ne, np.int64)
        non_manifold = np.flatnonzero(efc != 2)
        boundary = np.flatnonzero(efc == 1)
        interior3 = np.flatnonzero(efc > 2)
        loose_verts = np.flatnonzero(valence == 0)
        loose_edges = np.flatnonzero(efc == 0)
        degenerate = np.flatnonzero(area < tol * tol)
        dup = _dup_count(co, tol)
        # degenerate faces have no defined normal (bmesh reports zero) -> never counted as inward
        inward = int(np.count_nonzero((((fcen - fcen.mean(0)) * fnor).sum(1) < 0) & (area >= tol * tol))) if nf else 0

        nonplanar_ngons = np.empty(0, np.int64)
        curved_nonquads = np.empty(0, np.int64)
        slivers = np.empty(0, np.int64)
        if nf:
            lf = np.repeat(np.arange(nf), lt)
            ng = np.flatnonzero(lt > 4)
            if len(ng):
                lm = lt[lf] > 4
                dev = np.abs(((co[lv[lm]] - fcen[lf[lm]]) * fnor[lf[lm]]).sum(1))
                starts = np.concatenate(([0], np.cumsum(lt[ng])[:-1]))
                maxdev = np.maximum.reduceat(dev, starts)
                thr = np.maximum(1e-4 * np.sqrt(area[ng]), 5 * tol)
                nonplanar_ngons = ng[maxdev > thr]
            elen = np.linalg.norm(co[ev[:, 0]] - co[ev[:, 1]], axis=1)
            ll = elen[le]
            fmax = np.maximum.reduceat(ll, ls); fmin = np.minimum.reduceat(ll, ls)
            with np.errstate(divide="ignore", invalid="ignore"):
                slivers = np.flatnonzero((fmin > 0) & (fmax / np.where(fmin > 0, fmin, 1) > 25))
            if o_["curvature_tri_check"] and np.any(lt != 4):
                man = np.flatnonzero(efc == 2)
                ang = np.full(ne, -1.0)
                if len(man):
                    fa = np.full(ne, nf, np.int64); fb = np.full(ne, -1, np.int64)
                    np.minimum.at(fa, le, lf); np.maximum.at(fb, le, lf)  # the two faces of each 2-face edge
                    f1 = fa[man]; f2 = fb[man]
                    ang[man] = np.arccos(np.clip((fnor[f1] * fnor[f2]).sum(1), -1.0, 1.0))
                nq = np.flatnonzero(lt != 4)
                lm = lt[lf] != 4
                starts = np.concatenate(([0], np.cumsum(lt[nq])[:-1]))
                amax = np.maximum.reduceat(ang[le[lm]], starts)
                curved_nonquads = nq[(amax > math.radians(12)) & (amax < math.radians(80))]

        dims = [round(d, 4) for d in obj.dimensions]
        scale_applied = all(abs(s - 1.0) < 1e-6 for s in obj.scale)
        rot_applied = all(abs(r) < 1e-6 for r in obj.rotation_euler)
        quads = face_sizes.get(4, 0)
        rep = {
            "object": obj.name, "verts": nv, "edges": ne, "faces": nf,
            "triangulated_tris": tris, "tris": face_sizes.get(3, 0), "quads": quads, "ngons": face_sizes.get(5, 0),
            "quad_ratio": round(quads / nf, 3) if nf else 0, "poles": {str(k): v for k, v in sorted(poles.items())},
            "poles_6plus": len(bad_pole_verts), "non_manifold_edges": len(non_manifold), "boundary_edges": len(boundary),
            "edges_with_3plus_faces": len(interior3), "loose_verts": len(loose_verts), "loose_edges": len(loose_edges),
            "degenerate_faces": len(degenerate), "approx_duplicate_verts": int(dup),
            "inward_facing_faces_heuristic": inward,
            "nonplanar_ngons": len(nonplanar_ngons), "nonquads_on_curved_regions": len(curved_nonquads),
            "sliver_faces": len(slivers), "dimensions_m": dims, "scale_applied": scale_applied,
            "rotation_applied": rot_applied, "smooth_shaded_ratio": round(int(smooth.sum()) / nf, 2) if nf else 0,
            "modifiers": [f"{m.type}:{m.name}" for m in obj.modifiers], "materials": [m.name for m in obj.data.materials if m],
            "uv_layers": [uv.name for uv in me.uv_layers],
            "size_diag": round(size, 6), "tolerance": tol, "engine": "numpy",
        }
        budget = o_.get("budget_tris")
        if budget:
            rep["over_budget"] = tris > budget
        flags = []
        if len(non_manifold) and len(non_manifold) != len(boundary):
            flags.append("non-manifold edges (internal faces / bad joins)")
        if len(boundary): flags.append(f"{len(boundary)} open boundary edges (holes or intentional open mesh)")
        if len(bad_pole_verts): flags.append("poles with 6+ edges")
        if len(loose_verts) or len(loose_edges): flags.append("loose geometry")
        if len(degenerate): flags.append("degenerate faces")
        if dup: flags.append(f"possible duplicate verts (tol {tol:.3g}) - merge by distance")
        if nf and inward > nf * 0.1: flags.append("many inward normals? recalc outside")
        if len(nonplanar_ngons): flags.append("non-planar ngons -> shading artifacts")
        if len(curved_nonquads): flags.append("tris/ngons on curved regions -> subdivision/deform artifacts")
        if len(slivers): flags.append("sliver faces (boolean near edges?)")
        if not scale_applied: flags.append("scale not applied")
        if budget and tris > budget: flags.append(f"over tri budget ({tris} > {budget})")
        if any(abs(d) > 100 for d in dims) or (dims and max(dims) < 0.005): flags.append("suspicious dimensions - check units/scale")
        rep["flags"] = flags
        rep["seconds"] = round(time.perf_counter() - t0, 3)
        rep["_problem_indices"] = {"verts": np.concatenate((bad_pole_verts, loose_verts)),
                                   "edges": np.concatenate((non_manifold, loose_edges)),
                                   "faces": np.concatenate((degenerate, nonplanar_ngons, curved_nonquads, slivers))}
        return rep
    finally:
        if owner is not None:
            owner.to_mesh_clear()


def select_problems(obj, idx):
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True); bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    for seq in (bm.verts, bm.edges, bm.faces):
        for g in seq: g.select = False
    for key, seq in (("verts", bm.verts), ("edges", bm.edges), ("faces", bm.faces)):
        for i in np.asarray(idx[key]).tolist():
            if i < len(seq): seq[i].select = True
    bm.select_flush_mode(); bmesh.update_edit_mesh(obj.data)


def run_report(**opts):
    o_ = dict(DEFAULTS); o_.update(opts)
    t0 = time.perf_counter()
    objs = target_objects(o_["objects"])
    reports = []
    for o in objs:
        try:
            reports.append(audit(o, o_))
        except Exception as ex:
            reports.append({"object": o.name, "error": f"{type(ex).__name__}: {ex}"})
    total_tris = sum(r.get("triangulated_tris", 0) for r in reports)
    lines = [f"Audited {len(reports)} mesh(es); total triangulated tris: {total_tris}"]
    for r in reports:
        if "error" in r:
            lines.append(f"- {r['object']}: ERROR {r['error']}"); continue
        lines.append(f"- {r['object']}: {r['faces']} faces ({r['tris']} tri / {r['quads']} quad / {r['ngons']} ngon, "
                     f"quad ratio {r['quad_ratio']}), {r['triangulated_tris']} tris, poles {r['poles']}, "
                     f"dims {r['dimensions_m']} m")
        for f in r["flags"]:
            lines.append(f"    ! {f}")
    summary = "\n".join(lines)
    if o_["select_problems"] and reports and "_problem_indices" in reports[0] and not o_["evaluated"]:
        select_problems(objs[0], reports[0]["_problem_indices"])
    for r in reports:
        r.pop("_problem_indices", None)
    return {"summary": summary, "total_tris": total_tris, "reports": reports,
            "seconds": round(time.perf_counter() - t0, 3)}


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="mesh_report.py")
    p.add_argument("--objects", default=""); p.add_argument("--evaluated", action="store_true")
    p.add_argument("--budget-tris", type=int); p.add_argument("--rel-tol", type=float, default=1e-5)
    p.add_argument("--abs-tol", type=float); p.add_argument("--no-curvature", action="store_true")
    p.add_argument("--json-out")
    a = p.parse_args(argv)
    res = run_report(objects=[n for n in a.objects.split(",") if n] or None, evaluated=a.evaluated,
                     budget_tris=a.budget_tris, rel_tol=a.rel_tol, abs_tol=a.abs_tol,
                     curvature_tri_check=not a.no_curvature)
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f: json.dump(res, f, indent=1)
    return res


if globals().get("MESH_REPORT_DEFINE_ONLY"):
    result = {"defined": ["audit", "run_report", "target_objects", "select_problems"]}
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print("MESH_REPORT " + json.dumps(result, default=str))
else:
    result = run_report(**OPTS)
    print(result["summary"])
