"""Mesh intake & repair for scans, photogrammetry, AI image-to-3D output, CAD tessellation and downloaded assets.

analyze(obj)  -> scale/units/up-axis hints, weld (triangle-soup) check, islands (faces/verts/area/closed/volume),
                 holes (count, edge sizes, perimeter), multi-face edges, degenerate + duplicate faces, orientation
                 (inconsistent edges, flipped-face estimate, inverted closed islands), inner/enclosed shells,
                 symmetry score per axis. All tolerances are relative to the bbox diagonal unless abs_tol is given.
repair(obj, ...) -> [apply rot/scale] [scale to known size] [ground] -> merge by distance -> dissolve degenerate ->
                 delete loose / duplicate faces / small islands -> cut multi-face edges -> fill holes <= N edges ->
                 recalc normals -> remove inner shells -> [voxel remesh] -> [symmetrize] -> [decimate to budget]
                 -> [triangulate] -> analyze again + sampled two-sided deviation vs the (scaled) original + gates.

Headless / CLI (prints one line: MESH_REPAIR <json>):
    BLENDER -b [file.blend] --python mesh_repair.py -- analyze|repair [--object NAME | --import scan.ply]
        [--rel-tol 1e-5] [--abs-tol M] [--expect-longest M] [--target-longest M] [--scale F] [--ground]
        [--min-island-pct 1.0] [--min-island-verts 0] [--keep-inner] [--fill-max-edges 64] [--no-fill]
        [--voxel-rel 0.004 | --voxel-abs M] [--symmetrize -X] [--sym-center bbox|origin]
        [--decimate-tris N] [--decimate-mode collapse|planar|unsubdiv] [--planar-deg 5] [--unsubdiv-iter 2]
        [--triangulate] [--max-dev-rel 0.005] [--samples 20000] [--save out.blend] [--export out.glb|.obj|.ply|.stl]
        [--json-out report.json]
Live (Blender:execute_blender_code): set before exec
    MESH_REPAIR_OPTS = {"mode": "analyze"|"repair", "object": "Scan", "decimate_tris": 200000, ...}  (repair kwargs)
    -> `result` dict. Without MESH_REPAIR_OPTS the file only defines analyze / repair / deviation.

Conventions: `--symmetrize -X` keeps the -X half and mirrors it onto +X (bmesh.ops.symmetrize direction), about the
bbox centre (default) or the object origin. min_island_pct is a percentage of the LARGEST island's area; set 0 for
multi-part assets (buttons, bolts). remove_inner deletes islands enclosed by a larger closed island (ray parity vote) -
turn it off for assets with legitimate interior parts (eyes, mechanisms). --fill-max-edges 0 fills every hole.
Deviation: orig->new samples skip faces deliberately removed (floaters, inner shells); new->ref measures distance to
the original OR to the hole-fill caps (so filled holes don't read as error). Gates pass when the result is closed
manifold, normals consistent, within budget and both deviation maxima <= max_dev_rel x diagonal.
Limitations: hole caps are flat triangulated fills (sculpt/remesh large ones); voxel remesh and decimate drop UVs on
changed topology (bake textures from the original afterwards - references/mesh-repair.md section 6); non-manifold
(bowtie) vertices are only fixed by voxel remesh; parity inner-shell test can be fooled by containers with big holes.
"""
import bpy, bmesh, json, math, os, sys, time
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

RAY_DIRS = [Vector(v).normalized() for v in ((0.2672, 0.5345, 0.8018), (-0.8729, 0.2182, 0.4364), (0.4082, -0.8165, 0.4082))]


# ---------------------------------------------------------------- arrays & graph helpers
def _get(coll, attr, n, dtype, width=1):
    a = np.empty(n * width, dtype)
    if n:
        coll.foreach_get(attr, a)
    return a.reshape(-1, width) if width > 1 else a


def _arrays(me, mw=None):
    nv, ne, nf, nl = len(me.vertices), len(me.edges), len(me.polygons), len(me.loops)
    co = _get(me.vertices, "co", nv, np.float32, 3).astype(np.float64)
    if mw is not None:
        m = np.array(mw); co = co @ m[:3, :3].T + m[:3, 3]
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    return {"co": co, "ev": _get(me.edges, "vertices", ne, np.int32, 2).astype(np.int64),
            "ls": _get(me.polygons, "loop_start", nf, np.int32).astype(np.int64),
            "lt": _get(me.polygons, "loop_total", nf, np.int32).astype(np.int64),
            "lv": _get(me.loops, "vertex_index", nl, np.int32).astype(np.int64),
            "le": _get(me.loops, "edge_index", nl, np.int32).astype(np.int64),
            "tri": _get(me.loop_triangles, "vertices", nt, np.int32, 3).astype(np.int64),
            "tpoly": _get(me.loop_triangles, "polygon_index", nt, np.int32).astype(np.int64)}


def _components(n, a, b):
    """Connected components of n nodes joined by edges a[i]-b[i] (min-label hooking + pointer jumping)."""
    lab = np.arange(n, dtype=np.int64)
    a = np.asarray(a, np.int64); b = np.asarray(b, np.int64)
    while len(a):
        la, lb = lab[a], lab[b]
        m = la != lb
        if not m.any():
            break
        np.minimum.at(lab, np.maximum(la[m], lb[m]), np.minimum(la[m], lb[m]))
        while True:
            nxt = lab[lab]
            if np.array_equal(nxt, lab):
                break
            lab = nxt
        a, b = a[m], b[m]
    _, inv = np.unique(lab, return_inverse=True)
    return inv, (int(inv.max()) + 1 if n else 0)


def _weld_ids(co, tol):
    q = np.round(co / tol).astype(np.int64)
    o = np.lexsort((q[:, 2], q[:, 1], q[:, 0])); s = q[o]
    new = np.concatenate(([True], np.any(s[1:] != s[:-1], axis=1))) if len(s) else np.zeros(0, bool)
    gid = np.cumsum(new) - 1
    rep = np.empty(len(co), np.int64); rep[o] = gid
    return rep, (int(gid[-1]) + 1 if len(gid) else 0)


def _tri_area(co, tri):
    return 0.5 * np.linalg.norm(np.cross(co[tri[:, 1]] - co[tri[:, 0]], co[tri[:, 2]] - co[tri[:, 0]]), axis=1)


def _sample(co, tri, weights, n, rng):
    if len(tri) == 0 or weights.sum() <= 0:
        return np.zeros((0, 3))
    idx = rng.choice(len(tri), n, p=weights / weights.sum())
    r1, r2 = rng.random(n), rng.random(n); s = np.sqrt(r1)
    A, B, C = co[tri[idx, 0]], co[tri[idx, 1]], co[tri[idx, 2]]
    return (1 - s)[:, None] * A + (s * (1 - r2))[:, None] * B + (s * r2)[:, None] * C


def _bvh(co, tri):
    return BVHTree.FromPolygons(co.tolist(), tri.tolist(), all_triangles=True)


def _nearest(bvh, pts):
    out = np.full(len(pts), np.inf)
    for i, p in enumerate(pts.tolist()):
        hit = bvh.find_nearest(Vector(p))
        if hit[0] is not None:
            out[i] = hit[3]
    return out


def _stats(d, diag):
    d = d[np.isfinite(d)]
    if not len(d):
        return {"n": 0}
    q = np.percentile(d, [50, 95, 99])
    return {"n": int(len(d)), "mean": float(d.mean()), "p50": float(q[0]), "p95": float(q[1]), "p99": float(q[2]),
            "max": float(d.max()), "max_rel": float(d.max() / diag) if diag else None, "p99_rel": float(q[2] / diag) if diag else None}


# ---------------------------------------------------------------- topology measurements (shared by analyze & repair)
def _topology(A, tol):
    """Welded edge/face/island tables from arrays A (coords already in the frame you want to measure)."""
    co, ls, lt, lv = A["co"], A["ls"], A["lt"], A["lv"]
    nf, nl = len(lt), len(lv)
    rep, nun = _weld_ids(co, tol) if len(co) else (np.zeros(0, np.int64), 0)
    cow = np.zeros((nun, 3)); cow[rep] = co
    lf = np.repeat(np.arange(nf), lt)
    nxt = np.arange(nl) + 1
    if nf:
        nxt[ls + lt - 1] = ls
    a, b = rep[lv], rep[lv[nxt]] if nl else rep[lv]
    ok = a != b
    lo_, hi_, fwd, ef = np.minimum(a, b)[ok], np.maximum(a, b)[ok], (a < b)[ok], lf[ok]
    key = lo_ * max(nun, 1) + hi_
    order = np.argsort(key, kind="stable"); ks = key[order]
    first = np.concatenate(([True], ks[1:] != ks[:-1])) if len(ks) else np.zeros(0, bool)
    eid_s = np.cumsum(first) - 1; ne_u = int(eid_s[-1]) + 1 if len(eid_s) else 0
    eid = np.empty(len(key), np.int64); eid[order] = eid_s
    ecount = np.bincount(eid_s, minlength=ne_u)
    e_lo, e_hi = lo_[order][first], hi_[order][first]
    fsum = np.bincount(eid, fwd.astype(np.int64), minlength=ne_u)
    inconsistent = (ecount == 2) & (fsum != 1)
    # faces that collapse under welding (fewer than 3 distinct welded corners)
    distinct = np.bincount(lf[ok], minlength=nf) if nf else np.zeros(0, np.int64)
    # duplicate faces (tris/quads): same welded corner set
    dup_faces = np.zeros(0, np.int64)
    small = np.flatnonzero((lt <= 4) & (distinct >= 3))
    if len(small):
        pad = np.full((len(small), 4), -1, np.int64)
        for k in range(4):
            has = lt[small] > k
            pad[has, k] = rep[lv[ls[small[has]] + k]]
        pad.sort(axis=1)
        o = np.lexsort(pad.T[::-1]); s = pad[o]
        same = np.concatenate(([False], np.all(s[1:] == s[:-1], axis=1)))
        dup_faces = small[o[same]]
    vcomp, nis = _components(nun, e_lo, e_hi)
    fisl = vcomp[rep[lv[ls]]] if nf else np.zeros(0, np.int64)
    return {"rep": rep, "nun": nun, "cow": cow, "e_lo": e_lo, "e_hi": e_hi, "ecount": ecount, "inconsistent": inconsistent,
            "collapsed_faces": np.flatnonzero(distinct < 3), "dup_faces": dup_faces, "vcomp": vcomp, "nis": nis, "fisl": fisl}


def _island_table(A, T, farea):
    fisl, nis, vcomp = T["fisl"], T["nis"], T["vcomp"]
    co, tri, tpoly = A["co"], A["tri"], A["tpoly"]
    faces = np.bincount(fisl, minlength=nis)
    area = np.bincount(fisl, farea, minlength=nis)
    used = np.unique(T["rep"][A["lv"]])
    verts = np.bincount(vcomp[used], minlength=nis)
    bnd = np.bincount(vcomp[T["e_lo"][T["ecount"] == 1]], minlength=nis)
    tisl = fisl[tpoly]
    vol = np.bincount(tisl, np.einsum("ij,ij->i", co[tri[:, 0]], np.cross(co[tri[:, 1]], co[tri[:, 2]])) / 6.0, minlength=nis)
    bmin = np.full((nis, 3), np.inf); bmax = np.full((nis, 3), -np.inf)
    np.minimum.at(bmin, vcomp[used], T["cow"][used]); np.maximum.at(bmax, vcomp[used], T["cow"][used])
    return {"faces": faces, "area": area, "verts": verts, "boundary": bnd, "volume": vol, "bmin": bmin, "bmax": bmax,
            "tisl": tisl}


def _holes(T):
    b = T["ecount"] == 1
    if not b.any():
        return {"count": 0, "edges_hist": {}, "largest": []}
    lo, hi = T["e_lo"][b], T["e_hi"][b]
    comp, n = _components(T["nun"], lo, hi)
    lab = comp[lo]
    _, lab = np.unique(lab, return_inverse=True)
    edges = np.bincount(lab)
    per = np.bincount(lab, np.linalg.norm(T["cow"][lo] - T["cow"][hi], axis=1))
    order = np.argsort(-edges)
    hist = {"<=8": int((edges <= 8).sum()), "9-32": int(((edges > 8) & (edges <= 32)).sum()),
            "33-128": int(((edges > 32) & (edges <= 128)).sum()), ">128": int((edges > 128).sum())}
    return {"count": int(len(edges)), "edges_hist": hist,
            "largest": [{"edges": int(edges[i]), "perimeter": round(float(per[i]), 6)} for i in order[:8]]}


def _inner_shells(A, T, I, tol, diag, max_containers=4, max_candidates=400):
    """Islands enclosed by a larger, (nearly) closed island: majority vote of ray-parity tests from sample vertices."""
    nis = T["nis"]
    real = np.flatnonzero(I["faces"] > 0)
    if len(real) < 2:
        return []
    by_area = real[np.argsort(-I["area"][real])]
    containers = [i for i in by_area if I["faces"][i] >= 16 and I["boundary"][i] <= 0.02 * I["faces"][i] * 1.5][:max_containers]
    co, tri, tisl = A["co"], A["tri"], I["tisl"]
    rep, vcomp = T["rep"], T["vcomp"]
    vis = vcomp[rep]  # raw vertex -> island
    found, cache = [], {}
    for cand in by_area[:max_candidates]:
        for c in containers:
            if c == cand or I["area"][cand] >= I["area"][c]:
                continue
            if np.any(I["bmin"][cand] < I["bmin"][c] - tol) or np.any(I["bmax"][cand] > I["bmax"][c] + tol):
                continue
            if c not in cache:
                ct = tri[tisl == c]; uv, inv = np.unique(ct, return_inverse=True)
                cache[c] = _bvh(co[uv], inv.reshape(-1, 3))
            bvh = cache[c]
            vids = np.flatnonzero(vis == cand)
            pick = vids[np.linspace(0, len(vids) - 1, min(7, len(vids))).astype(int)]
            votes = total = 0
            for p in co[pick].tolist():
                for d in RAY_DIRS:
                    o, hits = Vector(p), 0
                    for _ in range(512):
                        loc, _n, _i, _d = bvh.ray_cast(o, d, diag * 2)
                        if loc is None:
                            break
                        hits += 1; o = loc + d * max(tol, diag * 1e-7)
                    total += 1; votes += hits % 2
            if total and votes / total >= 0.6:
                found.append({"island": int(cand), "inside_island": int(c), "parity_votes": f"{votes}/{total}",
                              "faces": int(I["faces"][cand])})
                break
    return found


def _flipped_estimate(obj, A, T, I, tol_local, max_faces):
    me = obj.data
    nf = len(me.polygons)
    if nf == 0 or nf > max_faces:
        return None
    n0 = _get(me.polygons, "normal", nf, np.float32, 3)
    area0 = _get(me.polygons, "area", nf, np.float32)
    bm = bmesh.new(); bm.from_mesh(me)
    lay = bm.faces.layers.int.new("_mr_idx")
    for i, f in enumerate(bm.faces):
        f[lay] = i
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=tol_local)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    tmp = bpy.data.meshes.new("_mr_tmp"); bm.to_mesh(tmp); bm.free()
    try:
        m = len(tmp.polygons)
        idx = _get(tmp.attributes["_mr_idx"].data, "value", m, np.int32).astype(np.int64)
        n1 = _get(tmp.polygons, "normal", m, np.float32, 3)
    finally:
        bpy.data.meshes.remove(tmp)
    flipped = ((n0[idx] * n1).sum(1) < 0) & (area0[idx] > tol_local ** 2)
    k = np.bincount(T["fisl"][idx[flipped]], minlength=T["nis"])
    faces = I["faces"]
    minority = np.minimum(k, faces - k)
    whole = np.flatnonzero((k > faces / 2) & (faces > 0))
    return {"faces_flipped_by_recalc": int(flipped.sum()), "flipped_patch_faces": int(minority.sum()),
            "islands_reversed_by_recalc": int(len(whole))}


def _symmetry(A, farea_tri, bvh, lo, hi, origin, diag, n, rng):
    pts = _sample(A["co"], A["tri"], farea_tri, n, rng)
    if not len(pts):
        return {}
    cen = pts.mean(0)
    tol = 2e-3 * diag
    out = {}
    for k, ax in enumerate("xyz"):
        best = None
        for label, c in (("bbox", (lo[k] + hi[k]) / 2), ("centroid", cen[k]), ("origin", origin[k])):
            m = pts.copy(); m[:, k] = 2 * c - m[:, k]
            d = _nearest(bvh, m)
            rec = {"plane": label, "at": round(float(c), 6), "within_tol_frac": round(float((d <= tol).mean()), 4),
                   "p95_rel": round(float(np.percentile(d, 95) / diag), 6)}
            if best is None or rec["within_tol_frac"] > best["within_tol_frac"]:
                best = rec
        out[ax] = best
    return out


# ---------------------------------------------------------------- analyze
def analyze(obj, rel_tol=1e-5, abs_tol=None, expect_longest=None, sym_samples=2000, flip_max_faces=3_000_000,
            inner_check=True, list_islands=12, seed=0):
    t0 = time.perf_counter()
    if isinstance(obj, str):
        obj = bpy.data.objects[obj]
    mw = obj.matrix_world.copy()
    A = _arrays(obj.data, mw)
    co, tri = A["co"], A["tri"]
    nv, nf = len(co), len(A["lt"])
    res = {"object": obj.name}
    if nf == 0:
        return {**res, "error": "mesh has no faces"}
    lo, hi = co.min(0), co.max(0); dims = hi - lo; diag = float(np.linalg.norm(dims)); longest = float(dims.max())
    tol = float(abs_tol) if abs_tol else rel_tol * diag
    mscale = max(abs(s) for s in mw.to_scale()) or 1.0
    ta = _tri_area(co, tri)
    farea = np.bincount(A["tpoly"], ta, minlength=nf)
    T = _topology(A, tol)
    I = _island_table(A, T, farea)
    real = np.flatnonzero(I["faces"] > 0)
    order = real[np.argsort(-I["area"][real])]
    amax = float(I["area"][order[0]])
    raw_comp, raw_n = _components(nv, A["ev"][:, 0], A["ev"][:, 1])
    raw_islands = int(len(np.unique(raw_comp[A["lv"][A["ls"]]])))
    unit_hint = None
    if longest > 50: unit_hint = f"longest side {longest:.4g} m: likely cm (x0.01) or mm (x0.001) data read as metres"
    elif longest < 0.01: unit_hint = f"longest side {longest:.4g} m: likely metres data read as mm, or a tiny part - confirm"
    base = []
    fn = np.cross(co[tri[:, 1]] - co[tri[:, 0]], co[tri[:, 2]] - co[tri[:, 0]])
    fl = np.linalg.norm(fn, axis=1); fn = fn / np.where(fl > 0, fl, 1)[:, None]
    tc = (co[tri[:, 0]] + co[tri[:, 1]] + co[tri[:, 2]]) / 3
    for k, ax in enumerate("XYZ"):
        for sgn in (-1, 1):
            ext = lo[k] if sgn < 0 else hi[k]
            m = (np.abs(fn[:, k]) > 0.95) & (np.abs(tc[:, k] - ext) < 0.02 * max(dims[k], 1e-12))
            base.append({"dir": ("-" if sgn < 0 else "+") + ax, "flat_area_frac": round(float(ta[m].sum() / ta.sum()), 4)})
    base.sort(key=lambda r: -r["flat_area_frac"])
    orient_hint = None
    if base[0]["flat_area_frac"] > 0.02 and base[0]["dir"] != "-Z":
        orient_hint = f"largest flat extreme face region is {base[0]['dir']}: if that is the base, the source is not Z-up"
    res["scale"] = {"dims_m": [round(float(d), 6) for d in dims], "longest_m": round(longest, 6), "diag_m": round(diag, 6),
                    "min_z": round(float(lo[2]), 6), "grounded": bool(abs(lo[2]) <= max(tol * 10, 1e-6)),
                    "unit_hint": unit_hint, "scale_to_expected": (expect_longest / longest) if expect_longest else None,
                    "flat_extremes": base[:3], "orientation_hint": orient_hint,
                    "object_scale": [round(s, 6) for s in obj.scale], "rotation_applied": all(abs(r) < 1e-6 for r in obj.rotation_euler)}
    res["tolerance_m"] = tol
    coincident = nv - T["nun"]
    res["counts"] = {"verts": nv, "faces": nf, "tris": int(len(tri)),
                     "loose_verts": int(nv - len(np.unique(A["lv"]))),
                     "loose_edges": int((np.bincount(A["le"], minlength=len(A["ev"])) == 0).sum())}
    res["weld"] = {"coincident_verts": int(coincident), "raw_islands": raw_islands,
                   "soup_suspect": bool(coincident > 0.3 * nv and raw_islands > 4 * len(real))}
    small1 = int((I["area"][real] < 0.01 * amax).sum()); small01 = int((I["area"][real] < 0.001 * amax).sum())
    res["islands"] = {"count": int(len(real)), "largest_area_frac": round(amax / float(I["area"].sum()), 4),
                      "below_1pct_of_largest": small1, "below_0_1pct_of_largest": small01,
                      "list": [{"id": int(i), "faces": int(I["faces"][i]), "verts": int(I["verts"][i]),
                                "area": round(float(I["area"][i]), 8), "area_pct_of_largest": round(100 * float(I["area"][i]) / amax, 4),
                                "boundary_edges": int(I["boundary"][i]), "closed": bool(I["boundary"][i] == 0),
                                "signed_volume": round(float(I["volume"][i]), 9)} for i in order[:list_islands]]}
    res["holes"] = _holes(T)
    res["non_manifold"] = {"boundary_edges": int((T["ecount"] == 1).sum()), "multi_face_edges": int((T["ecount"] > 2).sum()),
                           "collapsed_or_degenerate_faces": int(len(T["collapsed_faces"]) + (farea < tol * tol).sum()),
                           "duplicate_faces": int(len(T["dup_faces"]))}
    inverted = [int(i) for i in real if I["boundary"][i] == 0 and I["volume"][i] < 0]
    res["normals"] = {"inconsistent_edges": int(T["inconsistent"].sum()), "inverted_closed_islands": len(inverted)}
    fe = _flipped_estimate(obj, A, T, I, tol / mscale, flip_max_faces)
    res["normals"].update(fe if fe else {"note": f"flip estimate skipped (> {flip_max_faces} faces)"})
    res["shells"] = {"inner": _inner_shells(A, T, I, tol, diag) if inner_check else None}
    rng = np.random.default_rng(seed)
    if sym_samples:
        res["symmetry"] = _symmetry(A, ta, _bvh(co, tri), lo, hi, np.array(mw.translation), diag, sym_samples, rng)
    flags = []
    if unit_hint: flags.append(unit_hint)
    if orient_hint: flags.append(orient_hint)
    if res["weld"]["soup_suspect"]: flags.append("triangle soup / split vertices: merge by distance before anything else")
    elif coincident: flags.append(f"{coincident} coincident verts at tol {tol:.3g}: merge by distance")
    if small1: flags.append(f"{small1} islands < 1% of the largest island's area (floaters?)")
    if res["holes"]["count"]: flags.append(f"{res['holes']['count']} open boundaries (holes)")
    if res["non_manifold"]["multi_face_edges"]: flags.append("edges shared by 3+ faces (internal faces / duplicate shells)")
    if res["non_manifold"]["duplicate_faces"]: flags.append(f"{res['non_manifold']['duplicate_faces']} duplicate faces")
    if res["normals"]["inconsistent_edges"] or res["normals"].get("flipped_patch_faces") or inverted:
        flags.append("inconsistent/flipped normals: recalc outside after welding")
    if res["shells"]["inner"]: flags.append(f"{len(res['shells']['inner'])} enclosed inner shells")
    for ax, s in (res.get("symmetry") or {}).items():
        if s["within_tol_frac"] >= 0.9:
            flags.append(f"near-symmetric across {ax.upper()} ({s['within_tol_frac']:.0%} within 0.2% of size, plane {s['plane']})")
    res["flags"] = flags
    res["seconds"] = round(time.perf_counter() - t0, 2)
    return res


# ---------------------------------------------------------------- repair helpers
def _bm_sync(bm, me):
    bm.to_mesh(me)
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    return _arrays(me)


def _apply_modifier(obj, mod):
    others = [(m, m.show_viewport) for m in obj.modifiers if m != mod]
    for m, _ in others:
        m.show_viewport = False
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    new = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    old = obj.data; name = old.name
    obj.modifiers.remove(mod); obj.data = new
    for m, s in others:
        m.show_viewport = s
    if old.users == 0:
        bpy.data.meshes.remove(old)
    new.name = name


def _tris_of(me):
    lt = _get(me.polygons, "loop_total", len(me.polygons), np.int32)
    return int(lt.sum() - 2 * len(lt))


def deviation(orig_co, orig_tri, orig_weights, obj, caps=None, samples=20000, seed=1):
    """Two-sided sampled closest-point distance (object-local coordinates)."""
    rng = np.random.default_rng(seed)
    A = _arrays(obj.data)
    diag = float(np.linalg.norm(orig_co.max(0) - orig_co.min(0)))
    bvh_new = _bvh(A["co"], A["tri"]); bvh_orig = _bvh(orig_co, orig_tri)
    po = _sample(orig_co, orig_tri, orig_weights, samples, rng)
    pn = _sample(A["co"], A["tri"], _tri_area(A["co"], A["tri"]), samples, rng)
    d_on = _nearest(bvh_new, po)
    d_no = _nearest(bvh_orig, pn)
    d_ref = d_no.copy()
    if caps is not None and len(caps[1]):
        d_cap = _nearest(_bvh(*caps), pn)
        d_ref = np.minimum(d_no, d_cap)
        on_caps = float((d_cap < d_no).mean())
    else:
        on_caps = 0.0
    return {"orig_to_new": _stats(d_on, diag), "new_to_orig_raw": _stats(d_no, diag),
            "new_to_orig_or_fill": _stats(d_ref, diag), "new_samples_on_fill_caps_frac": round(on_caps, 4), "diag": diag}


# ---------------------------------------------------------------- repair
def repair(obj, rel_tol=1e-5, abs_tol=None, apply_transform=True, scale=None, target_longest=None, ground=False,
           min_island_pct=1.0, min_island_verts=0, remove_inner=True, remove_duplicate_faces=True,
           fix_multi_face_edges=True, fill_holes=True, fill_max_edges=64, recalc_normals=True, voxel_rel=None,
           voxel_abs=None, voxel_adaptivity=0.0, voxel_max_faces=8_000_000, symmetrize=None, sym_center="bbox",
           sym_dist_rel=1e-3, decimate_tris=None, decimate_mode="collapse", planar_deg=5.0, unsubdiv_iter=2,
           triangulate=False, max_dev_rel=0.005, samples=20000, analyze_before=True, analyze_after=True,
           require_closed=True, seed=0):
    T0 = time.perf_counter()
    if isinstance(obj, str):
        obj = bpy.data.objects[obj]
    me = obj.data
    steps, out = [], {"object": obj.name, "blender": bpy.app.version_string}
    lap = [time.perf_counter()]

    def log(name, **kw):
        t = time.perf_counter(); steps.append({"step": name, "seconds": round(t - lap[0], 2), **kw}); lap[0] = t

    if analyze_before:
        out["before"] = analyze(obj, rel_tol, abs_tol, sym_samples=1000 if symmetrize else 0, seed=seed)
        log("analyze_before")
    # 1. transforms, units, ground
    if apply_transform:
        mw = obj.matrix_world.copy()
        me.transform(mw.to_3x3().to_4x4())
        if mw.to_3x3().determinant() < 0:
            me.flip_normals()
        obj.matrix_world = Matrix.Translation(mw.translation)
    co = _get(me.vertices, "co", len(me.vertices), np.float32, 3).astype(np.float64)
    longest = float((co.max(0) - co.min(0)).max())
    s = scale if scale else ((target_longest / longest) if target_longest and longest > 0 else None)
    if s and abs(s - 1.0) > 1e-12:
        me.transform(Matrix.Scale(s, 4))
    if ground:
        co = _get(me.vertices, "co", len(me.vertices), np.float32, 3).astype(np.float64)
        lo, hi = co.min(0), co.max(0)
        me.transform(Matrix.Translation((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2])))
        obj.location = (0.0, 0.0, 0.0)
    me.update()
    log("transform_scale_ground", applied_scale=s, grounded=ground)
    # snapshot original (local frame after scaling)
    O = _arrays(me)
    orig_co, orig_tri, orig_tpoly = O["co"], O["tri"], O["tpoly"]
    diag = float(np.linalg.norm(orig_co.max(0) - orig_co.min(0)))
    tol = float(abs_tol) if abs_tol else rel_tol * diag
    out["tolerance"] = tol; out["diag"] = diag
    nf0 = len(O["lt"])
    attr = me.attributes.get("_mr_orig") or me.attributes.new("_mr_orig", 'INT', 'FACE')
    attr.data.foreach_set("value", np.arange(nf0, dtype=np.int32))
    removed_orig = np.zeros(nf0, bool)

    bm = bmesh.new(); bm.from_mesh(me)
    lay = bm.faces.layers.int.get("_mr_orig")
    v0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=tol)
    bmesh.ops.dissolve_degenerate(bm, dist=tol, edges=bm.edges[:])
    log("merge_by_distance", merge_dist=tol, verts_removed=v0 - len(bm.verts))

    # 2. loose, duplicate faces, small islands
    A = _bm_sync(bm, me)
    nv, nf = len(A["co"]), len(A["lt"])
    efc = np.bincount(A["le"], minlength=len(A["ev"]))
    used = np.zeros(nv, bool); used[A["lv"]] = True
    loose_v = [bm.verts[i] for i in np.flatnonzero(~used)]
    loose_e = [bm.edges[i] for i in np.flatnonzero(efc == 0)]
    Tn = _topology(A, tol * 0.5)
    dup = set(Tn["dup_faces"].tolist()) if remove_duplicate_faces else set()
    farea = np.bincount(A["tpoly"], _tri_area(A["co"], A["tri"]), minlength=nf)
    fcomp, nis = _components(nv, A["ev"][:, 0], A["ev"][:, 1])
    fisl = fcomp[A["lv"][A["ls"]]]
    iarea = np.bincount(fisl, farea, minlength=nis)
    iverts = np.bincount(fcomp[used], minlength=nis)
    big = int(np.argmax(iarea))
    kill_isl = ((iarea < min_island_pct / 100.0 * iarea[big]) | (iverts < min_island_verts)) & (np.bincount(fisl, minlength=nis) > 0)
    kill_isl[big] = False
    kill_faces = np.flatnonzero(kill_isl[fisl])
    orig_ids = _get(me.attributes["_mr_orig"].data, "value", nf, np.int32)
    removed_orig[orig_ids[kill_faces][orig_ids[kill_faces] >= 0]] = True
    if dup:
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in sorted(dup)], context='FACES_ONLY')
    kf = [bm.faces[i] for i in kill_faces if i not in dup]
    if kf:
        bmesh.ops.delete(bm, geom=kf, context='FACES')
    loose_e = [e for e in loose_e if e.is_valid]
    if loose_e:
        bmesh.ops.delete(bm, geom=loose_e, context='EDGES')
    loose_v = [v for v in loose_v if v.is_valid]
    if loose_v:
        bmesh.ops.delete(bm, geom=loose_v, context='VERTS')
    log("cleanup_islands", duplicate_faces=len(dup), islands_removed=int(kill_isl.sum()), faces_removed=int(len(kill_faces)),
        loose_verts=len(loose_v), loose_edges=len(loose_e))

    # 3. multi-face edges -> cut faces, then fill holes, recalc normals
    if fix_multi_face_edges:
        A = _bm_sync(bm, me)
        efc = np.bincount(A["le"], minlength=len(A["ev"]))
        bad = np.flatnonzero(efc > 2)
        if len(bad):
            bm.edges.ensure_lookup_table()
            fs = {f for i in bad for f in bm.edges[i].link_faces}
            bmesh.ops.delete(bm, geom=list(fs), context='FACES')
        log("cut_multi_face_edges", edges=int(len(bad)), faces_removed=int(len(bad) and len(fs)))
    caps_co, caps_tri = [], []
    if fill_holes:
        bnd = [e for e in bm.edges if e.is_boundary]
        new_faces = bmesh.ops.holes_fill(bm, edges=bnd, sides=max(0, int(fill_max_edges or 0)))["faces"] if bnd else []
        for f in new_faces:
            f[lay] = -1
        if new_faces:
            tri_res = bmesh.ops.triangulate(bm, faces=new_faces, quad_method='BEAUTY', ngon_method='BEAUTY')
            cap_faces = [f for f in tri_res["faces"] if f.is_valid] or new_faces
            for f in cap_faces:
                f[lay] = -1
                base = len(caps_co)
                caps_co.extend([tuple(v.co) for v in f.verts]); caps_tri.append((base, base + 1, base + 2))
        # fallback: loops holes_fill skips (boundary touching itself at a vertex, etc.) -> triangle_fill per loop
        left = [e for e in bm.edges if e.is_boundary]
        fb = 0
        if left:
            bm.verts.index_update()
            vi = np.array([[e.verts[0].index, e.verts[1].index] for e in left], np.int64)
            comp, _ = _components(len(bm.verts), vi[:, 0], vi[:, 1])
            lab = comp[vi[:, 0]]
            for L in np.unique(lab):
                loop = [left[i] for i in np.flatnonzero(lab == L)]
                if fill_max_edges and len(loop) > fill_max_edges:
                    continue
                for f in bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=loop)["geom"]:
                    if isinstance(f, bmesh.types.BMFace):
                        f[lay] = -1; fb += 1
                        base = len(caps_co)
                        caps_co.extend([tuple(v.co) for v in f.verts]); caps_tri.append((base, base + 1, base + 2))
        remaining = sum(1 for e in bm.edges if e.is_boundary)
        log("fill_holes", filled=len(new_faces), fallback_triangles=fb, max_edges=fill_max_edges, boundary_edges_left=remaining)
    if recalc_normals:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        log("recalc_normals")
    # 4. inner shells (containers are closed now, so parity is reliable)
    if remove_inner:
        A = _bm_sync(bm, me)
        nf = len(A["lt"])
        T = _topology(A, tol * 0.5)
        farea = np.bincount(A["tpoly"], _tri_area(A["co"], A["tri"]), minlength=nf)
        I = _island_table(A, T, farea)
        inner = _inner_shells(A, T, I, tol, diag)
        ids = {r["island"] for r in inner}
        kill = np.flatnonzero(np.isin(T["fisl"], list(ids))) if ids else np.zeros(0, np.int64)
        oid = _get(me.attributes["_mr_orig"].data, "value", nf, np.int32)
        removed_orig[oid[kill][oid[kill] >= 0]] = True
        if len(kill):
            bmesh.ops.delete(bm, geom=[bm.faces[i] for i in kill], context='FACES')
        log("remove_inner_shells", shells=inner)
    bm.to_mesh(me); bm.free(); me.update()

    # 5. voxel remesh
    if voxel_rel or voxel_abs:
        vs = float(voxel_abs) if voxel_abs else voxel_rel * diag
        area = float(_tri_area(*[_arrays(me)[k] for k in ("co", "tri")]).sum())
        est = area / (vs * vs)
        if est > voxel_max_faces:
            log("voxel_remesh", skipped=f"estimated {est:.0f} faces > voxel_max_faces; raise voxel size")
        else:
            m = obj.modifiers.new("MR_Remesh", 'REMESH'); m.mode = 'VOXEL'; m.voxel_size = vs
            m.adaptivity = voxel_adaptivity; m.use_smooth_shade = False
            _apply_modifier(obj, m); me = obj.data
            log("voxel_remesh", voxel_size=vs, estimated_faces=int(est), faces=len(me.polygons))
    # 6. symmetrize
    if symmetrize:
        k = "XYZ".index(symmetrize.strip("+-").upper())
        co = _get(me.vertices, "co", len(me.vertices), np.float32, 3)
        c = float((co[:, k].min() + co[:, k].max()) / 2) if sym_center == "bbox" else 0.0
        off = Vector((0, 0, 0)); off[k] = -c
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.translate(bm, verts=bm.verts[:], vec=off)
        d = ("-" if symmetrize.startswith("-") else "") + "XYZ"[k]
        bmesh.ops.symmetrize(bm, input=bm.verts[:] + bm.edges[:] + bm.faces[:], direction=d, dist=sym_dist_rel * diag)
        bmesh.ops.translate(bm, verts=bm.verts[:], vec=-off)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(me); bm.free(); me.update()
        log("symmetrize", direction=d, plane_at=c, weld_dist=sym_dist_rel * diag)
    # 7. decimate
    if decimate_mode in ("planar", "unsubdiv"):
        m = obj.modifiers.new("MR_Decimate", 'DECIMATE')
        if decimate_mode == "planar":
            m.decimate_type = 'DISSOLVE'; m.angle_limit = math.radians(planar_deg)
        else:
            m.decimate_type = 'UNSUBDIV'; m.iterations = unsubdiv_iter
        _apply_modifier(obj, m); me = obj.data
        log("decimate_" + decimate_mode, tris=_tris_of(me))
    if decimate_tris:
        for it in range(4):
            t = _tris_of(me)
            if t <= decimate_tris * 1.01:
                break
            m = obj.modifiers.new("MR_Decimate", 'DECIMATE'); m.decimate_type = 'COLLAPSE'
            m.ratio = max(1e-4, min(1.0, decimate_tris / t * (1.0 if it == 0 else 0.995)))
            m.use_collapse_triangulate = True
            if symmetrize:
                m.use_symmetry = True; m.symmetry_axis = symmetrize.strip("+-").upper()
            _apply_modifier(obj, m); me = obj.data
        log("decimate_collapse", budget=decimate_tris, tris=_tris_of(me))
    if triangulate:
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
        bm.to_mesh(me); bm.free(); me.update()
        log("triangulate", tris=_tris_of(me))
    if me.attributes.get("_mr_orig"):
        me.attributes.remove(me.attributes["_mr_orig"])

    # 8. report
    w = _tri_area(orig_co, orig_tri) * (~removed_orig[orig_tpoly])
    caps = (np.array(caps_co, np.float64).reshape(-1, 3), np.array(caps_tri, np.int64).reshape(-1, 3))
    out["deviation"] = deviation(orig_co, orig_tri, w, obj, caps, samples, seed + 1)
    log("deviation")
    if analyze_after:
        out["after"] = analyze(obj, rel_tol, abs_tol, sym_samples=1000 if symmetrize else 0, seed=seed)
        log("analyze_after")
    out["steps"] = steps
    g = {}
    if analyze_after:
        a = out["after"]
        g["closed_manifold"] = bool(a["non_manifold"]["boundary_edges"] == 0 and a["non_manifold"]["multi_face_edges"] == 0) if require_closed else None
        g["normals_consistent"] = bool(a["normals"]["inconsistent_edges"] == 0 and not a["normals"].get("flipped_patch_faces")
                                       and a["normals"]["inverted_closed_islands"] == 0)
        g["no_small_islands"] = bool(a["islands"]["below_1pct_of_largest"] == 0) if min_island_pct else None
    t_final = _tris_of(obj.data)
    out["tris_final"] = t_final
    g["within_budget"] = bool(t_final <= decimate_tris * 1.01) if decimate_tris else None
    dv = out["deviation"]
    g["deviation_ok"] = bool(dv["orig_to_new"].get("max_rel", 1) <= max_dev_rel and dv["new_to_orig_or_fill"].get("max_rel", 1) <= max_dev_rel)
    out["gates"] = g
    out["pass"] = all(v for v in g.values() if v is not None)
    out["seconds"] = round(time.perf_counter() - T0, 2)
    return out


# ---------------------------------------------------------------- CLI
IMPORTERS = {".obj": ("wm", "obj_import"), ".ply": ("wm", "ply_import"), ".stl": ("wm", "stl_import"),
             ".glb": ("import_scene", "gltf"), ".gltf": ("import_scene", "gltf"), ".fbx": ("import_scene", "fbx"),
             ".usd": ("wm", "usd_import"), ".usdc": ("wm", "usd_import"), ".usdz": ("wm", "usd_import")}


def import_mesh(path):
    """Import a file into the current scene; join its meshes into one object and return it."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMPORTERS:
        raise ValueError(f"unsupported import type {ext}")
    before = set(bpy.data.objects)
    mod, name = IMPORTERS[ext]
    getattr(getattr(bpy.ops, mod), name)(filepath=path)
    meshes = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
    if not meshes:
        raise RuntimeError("import produced no mesh objects")
    if len(meshes) > 1:
        with bpy.context.temp_override(active_object=meshes[0], object=meshes[0], selected_objects=meshes,
                                       selected_editable_objects=meshes):
            bpy.ops.object.join()
    return meshes[0]


def export_mesh(obj, path):
    ext = os.path.splitext(path)[1].lower()
    for o in bpy.context.view_layer.objects:
        o.select_set(o == obj)
    bpy.context.view_layer.objects.active = obj
    if ext in (".glb", ".gltf"):
        bpy.ops.export_scene.gltf(filepath=path, use_selection=True, export_format='GLB' if ext == ".glb" else 'GLTF_SEPARATE')
    elif ext == ".obj":
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True)
    elif ext == ".ply":
        bpy.ops.wm.ply_export(filepath=path, export_selected_objects=True)
    elif ext == ".stl":
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True)
    else:
        raise ValueError(f"unsupported export type {ext}")
    return path


def _pick_object(name):
    if name:
        return bpy.data.objects[name]
    act = bpy.context.view_layer.objects.active
    if act and act.type == 'MESH':
        return act
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError("no mesh objects in scene")
    return max(meshes, key=lambda o: len(o.data.polygons))


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="mesh_repair.py")
    p.add_argument("mode", choices=["analyze", "repair"])
    p.add_argument("--object"); p.add_argument("--import", dest="imp")
    p.add_argument("--rel-tol", type=float, default=1e-5); p.add_argument("--abs-tol", type=float)
    p.add_argument("--expect-longest", type=float); p.add_argument("--target-longest", type=float)
    p.add_argument("--scale", type=float); p.add_argument("--ground", action="store_true")
    p.add_argument("--min-island-pct", type=float, default=1.0); p.add_argument("--min-island-verts", type=int, default=0)
    p.add_argument("--keep-inner", action="store_true"); p.add_argument("--fill-max-edges", type=int, default=64)
    p.add_argument("--no-fill", action="store_true")
    p.add_argument("--voxel-rel", type=float); p.add_argument("--voxel-abs", type=float)
    p.add_argument("--symmetrize"); p.add_argument("--sym-center", default="bbox", choices=["bbox", "origin"])
    p.add_argument("--decimate-tris", type=int); p.add_argument("--decimate-mode", default="collapse", choices=["collapse", "planar", "unsubdiv"])
    p.add_argument("--planar-deg", type=float, default=5.0); p.add_argument("--unsubdiv-iter", type=int, default=2)
    p.add_argument("--triangulate", action="store_true"); p.add_argument("--max-dev-rel", type=float, default=0.005)
    p.add_argument("--samples", type=int, default=20000); p.add_argument("--save"); p.add_argument("--export")
    p.add_argument("--json-out")
    a = p.parse_args(argv)
    if a.imp:
        if not bpy.data.filepath:  # fresh factory scene: drop the default objects
            for o in list(bpy.data.objects):
                bpy.data.objects.remove(o)
        obj = import_mesh(a.imp)
    else:
        obj = _pick_object(a.object)
    if a.mode == "analyze":
        res = analyze(obj, a.rel_tol, a.abs_tol, expect_longest=a.expect_longest)
    else:
        res = repair(obj, rel_tol=a.rel_tol, abs_tol=a.abs_tol, scale=a.scale, target_longest=a.target_longest,
                     ground=a.ground, min_island_pct=a.min_island_pct, min_island_verts=a.min_island_verts,
                     remove_inner=not a.keep_inner, fill_holes=not a.no_fill, fill_max_edges=a.fill_max_edges,
                     voxel_rel=a.voxel_rel, voxel_abs=a.voxel_abs, symmetrize=a.symmetrize, sym_center=a.sym_center,
                     decimate_tris=a.decimate_tris, decimate_mode=a.decimate_mode, planar_deg=a.planar_deg,
                     unsubdiv_iter=a.unsubdiv_iter, triangulate=a.triangulate, max_dev_rel=a.max_dev_rel, samples=a.samples)
        if a.export:
            res["exported"] = export_mesh(obj, a.export)
        if a.save:
            bpy.ops.wm.save_as_mainfile(filepath=a.save, copy=True); res["saved"] = a.save
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1, default=str)
    return res


if globals().get("MESH_REPAIR_OPTS"):
    _o = dict(MESH_REPAIR_OPTS); _mode = _o.pop("mode", "analyze"); _obj = _pick_object(_o.pop("object", None))
    result = analyze(_obj, **_o) if _mode == "analyze" else repair(_obj, **_o)
    print(json.dumps({k: result.get(k) for k in ("object", "pass", "gates", "flags") if k in result}, default=str))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print("MESH_REPAIR " + json.dumps(result, default=str))
else:
    result = {"defined": ["analyze", "repair", "deviation", "import_mesh", "export_mesh"]}
