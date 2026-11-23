"""Print export gate: validate meshes for 3D printing, then export STL/OBJ in millimetres and verify the written files.

Checks (all on the evaluated, modifier-applied mesh in world space, reported in mm):
  units      scene unit system / scale_length -> the global_scale that writes millimetres; unapplied or negative scale
  manifold   non-manifold edges/verts, boundary edges, flipped-winding edges, loose shells, zero-area faces, signed volume
  intersect  self-intersecting triangle pairs (BVH overlap, pairs that share a vertex ignored)
  thickness  wall thickness by inward ray casts from area-weighted surface samples -> min, p1/p5/median, share of area
             below --min-wall-mm, worst locations
  clearance  minimum gap between listed mating parts (surface samples -> BVH nearest, both directions) + interference
  measure    volume mm3, area mm2, bbox mm
  export     wm.stl_export / wm.obj_export with global_scale for mm, then re-import each file and compare bbox (tol mm)

Headless / CLI (prints one line: EXPORT_PRINT <json>):
    blender -b model.blend --python export_print.py -- [--objects RING_,PRONG] [--parts PART_A,PART_B]
        [--min-wall-mm 0.8] [--min-clearance-mm 0.2] [--out-dir //print] [--formats stl,obj] [--per-object]
        [--checks units,manifold,intersect,thickness,clearance,measure,export] [--samples-per-mm2 2] [--max-rays 150000]
        [--tol-mm 0.01] [--ascii]
    --objects / --parts take comma-separated exact names or name prefixes (default: all visible mesh objects).
Live (Blender:execute_blender_code): set before exec
    PRINT_OPTS = {"objects": "RING_", "parts": "PART_A,PART_B", "min_wall_mm": 0.8, "out_dir": "//print"}  -> `result` dict
Without PRINT_OPTS the file only defines run_print_gate and the check functions (result = {"defined": [...]}).

Limitations: thickness = distance along the inward normal to the opposite wall; it misses thin sections that are not
normal to the surface sample (knife edges read correctly only when samples land near them; raise --samples-per-mm2 for
small features). Clearance uses point samples to nearest surface, so it overestimates the true gap by at most the sample
spacing on curved/edge-to-edge contacts. Inside-without-touching (one part fully inside another) is detected by a
ray-parity test from one vertex. The gate never modifies the scene; export writes only the requested objects.
"""
import bpy, bmesh, json, math, os, sys
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


# ---------------------------------------------------------------- helpers
def _dg():
    dg = bpy.context.evaluated_depsgraph_get(); dg.update(); return dg


def _select(spec):
    """Comma list of exact names or prefixes -> visible mesh objects (all visible meshes when spec is empty)."""
    objs = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.visible_get()]
    if not spec:
        return objs
    keys = [k.strip() for k in (spec.split(",") if isinstance(spec, str) else spec) if k.strip()]
    return [o for o in objs if any(o.name == k or o.name.startswith(k) for k in keys)]


def _bu_to_mm():
    us = bpy.context.scene.unit_settings
    return (us.scale_length if us.system != 'NONE' else 1.0) * 1000.0


def _world_bmesh(o, dg):
    """Evaluated mesh of o, transformed to world space, triangulated copy (caller frees)."""
    ev = o.evaluated_get(dg); me = ev.to_mesh()
    bm = bmesh.new(); bm.from_mesh(me); ev.to_mesh_clear()
    bm.transform(o.matrix_world)
    bm.normal_update()
    return bm


def _arrays(bm):
    """World coords + a proper triangulation. Fan-triangulating n-gons is wrong for concave faces (boolean results):
    fan triangles span empty regions, giving fake self-intersections and off-surface thickness samples.
    calc_loop_triangles() triangulates concave n-gons correctly and leaves the bmesh unchanged."""
    bm.verts.ensure_lookup_table(); bm.verts.index_update()
    co = np.array([v.co[:] for v in bm.verts], dtype=np.float64).reshape(-1, 3)
    tris = [(a.vert.index, b.vert.index, c.vert.index) for a, b, c in bm.calc_loop_triangles()]
    return co, np.array(tris, dtype=np.int64).reshape(-1, 3)


def _bvh_tris(co, tris):
    return BVHTree.FromPolygons([Vector(c) for c in co], tris.tolist(), all_triangles=True, epsilon=0.0)


def _samples(co, tris, per_mm2, bu_mm, max_n, seed=1):
    """Area-weighted random surface samples; at least one per triangle (centroid) so tiny features are always hit."""
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    cr = np.cross(b - a, c - a); area2 = np.linalg.norm(cr, axis=1)
    ok = area2 > 1e-20
    a, b, c, cr, area2 = a[ok], b[ok], c[ok], cr[ok], area2[ok]
    nrm = cr / area2[:, None]
    area_mm2 = area2 / 2 * bu_mm * bu_mm
    extra = np.floor(area_mm2 * per_mm2).astype(np.int64)
    budget = max(0, max_n - len(a))
    if extra.sum() > budget and extra.sum() > 0:
        extra = np.floor(extra * (budget / extra.sum())).astype(np.int64)
    rng = np.random.default_rng(seed)
    tri_idx = np.concatenate([np.arange(len(a)), np.repeat(np.arange(len(a)), extra)])
    u = rng.random(len(tri_idx)); v = rng.random(len(tri_idx))
    flip = u + v > 1; u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    u[:len(a)], v[:len(a)] = 1 / 3, 1 / 3
    pts = a[tri_idx] + (b[tri_idx] - a[tri_idx]) * u[:, None] + (c[tri_idx] - a[tri_idx]) * v[:, None]
    w = area_mm2[tri_idx] / np.bincount(tri_idx, minlength=len(a))[tri_idx]
    return pts, nrm[tri_idx], w


def _mm(v, bu_mm):
    return [round(float(x) * bu_mm, 4) for x in v]


def _cluster(locs, cell):
    """Keep one location per grid cell (mm) so the worst-location list isn't 20 copies of one spot."""
    seen, out = set(), []
    for d, p in locs:
        key = tuple(int(math.floor(x / cell)) for x in p)
        if key in seen:
            continue
        seen.add(key); out.append({"thickness_mm": round(d, 4), "at_mm": [round(x, 3) for x in p]})
    return out


# ---------------------------------------------------------------- checks
def check_units(objects):
    sc = bpy.context.scene; us = sc.unit_settings; bu_mm = _bu_to_mm()
    warn = []
    if us.system == 'IMPERIAL':
        warn.append("imperial scene: slicers assume mm; global_scale below still converts BU to mm")
    if us.system == 'METRIC' and us.length_unit not in ('MILLIMETERS', 'MICROMETERS', 'CENTIMETERS') and bu_mm >= 1000:
        warn.append("length display is metres: set Unit Scale 1.0 + Length 'Millimeters' to type small-part values")
    odd = []
    for o in objects:
        s = o.matrix_world.to_scale()
        if min(s) < 0:
            odd.append({"object": o.name, "issue": "negative scale (mirrored): apply scale, recalc normals"})
        elif max(abs(x - 1) for x in s) > 1e-6:
            odd.append({"object": o.name, "issue": f"unapplied scale {tuple(round(x, 4) for x in s)}"})
    for o in objects:
        for m in o.modifiers:
            if m.type == 'WELD' and m.show_viewport and m.merge_threshold * bu_mm > 0.02:
                odd.append({"object": o.name, "issue": f"Weld modifier merges {m.merge_threshold * bu_mm:.3f} mm: small features can collapse"})
    return {"pass": not any("negative" in d["issue"] for d in odd), "system": us.system, "scale_length": us.scale_length,
            "length_unit": us.length_unit, "bu_to_mm": bu_mm, "export_global_scale": bu_mm,
            "object_issues": odd, "warnings": warn}


def check_manifold(o, dg, bu_mm):
    bm = _world_bmesh(o, dg)
    try:
        nm_edges = [e for e in bm.edges if not e.is_manifold]
        boundary = sum(1 for e in nm_edges if e.is_boundary)
        wire = sum(1 for e in bm.edges if e.is_wire)
        flipped = sum(1 for e in bm.edges if e.is_manifold and not e.is_contiguous)
        nm_verts = sum(1 for v in bm.verts if not v.is_manifold)
        zero = sum(1 for f in bm.faces if f.calc_area() * bu_mm * bu_mm < 1e-6)
        # shells (loose parts) by face connectivity
        seen, shells = set(), 0
        for f in bm.faces:
            if f.index in seen:
                continue
            shells += 1; stack = [f]; seen.add(f.index)
            while stack:
                g = stack.pop()
                for e in g.edges:
                    for h in e.link_faces:
                        if h.index not in seen:
                            seen.add(h.index); stack.append(h)
        vol = bm.calc_volume(signed=True) * bu_mm ** 3
        loc = [_mm(e.verts[0].co, bu_mm) for e in nm_edges[:5]]
        ok = not nm_edges and not flipped and nm_verts == 0 and zero == 0 and vol > 0
        return {"pass": ok, "non_manifold_edges": len(nm_edges), "boundary_edges": boundary, "wire_edges": wire,
                "non_manifold_verts": nm_verts, "flipped_winding_edges": flipped, "zero_area_faces": zero,
                "shells": shells, "signed_volume_mm3": round(vol, 4), "sample_locations_mm": loc,
                "note": "negative signed volume = normals inward" if vol <= 0 else ""}
    finally:
        bm.free()


def check_intersect(o, dg, bu_mm, limit=20):
    bm = _world_bmesh(o, dg)
    try:
        co, tris = _arrays(bm)
        if not len(tris):
            return {"pass": None, "note": "no faces"}
        bvh = _bvh_tris(co, tris)
        pairs = bvh.overlap(bvh)
        bad = []
        tset = [set(t) for t in tris.tolist()]
        for i, j in pairs:
            if i < j and not (tset[i] & tset[j]):
                bad.append((i, j))
        faces = sorted({i for p in bad for i in p})
        loc = [_mm(co[tris[i]].mean(axis=0), bu_mm) for i in faces[:limit]]
        return {"pass": not bad, "intersecting_tri_pairs": len(bad), "intersecting_tris": len(faces), "sample_locations_mm": loc}
    finally:
        bm.free()


def check_thickness(o, dg, bu_mm, min_wall_mm=0.8, per_mm2=2.0, max_rays=150000, cap_mm=None):
    """Inward rays from surface samples; hit must be the back side of a wall (hit normal along ray)."""
    bm = _world_bmesh(o, dg)
    try:
        co, tris = _arrays(bm)
        if not len(tris):
            return {"pass": None, "note": "no faces"}
        bvh = _bvh_tris(co, tris)
        pts, nrm, w = _samples(co, tris, per_mm2, bu_mm, max_rays)
        cap_bu = (cap_mm or max(50.0, min_wall_mm * 20)) / bu_mm
        eps = 1e-4 / bu_mm  # 0.1 micron in BU
        d_mm, wts, locs = [], [], []
        missed = 0
        for p, n, wt in zip(pts, nrm, w):
            d = Vector((-n[0], -n[1], -n[2])); org = Vector(p) + d * eps
            hit, hn, _, dist = bvh.ray_cast(org, d, cap_bu)
            # skip coincident/back-facing hits: we want the inside of the opposite wall (its normal points along d)
            tries = 0
            while hit is not None and hn.dot(d) <= 0 and tries < 4:
                org = hit + d * eps; tries += 1
                hit, hn, _, dist2 = bvh.ray_cast(org, d, cap_bu)
                dist = (hit - Vector(p)).length if hit is not None else None
            if hit is None:
                missed += 1; continue
            t = (hit - Vector(p)).length * bu_mm
            d_mm.append(t); wts.append(wt); locs.append((t, (Vector(p) * bu_mm)[:]))
        if not d_mm:
            return {"pass": None, "note": "no inward hits (open mesh or normals inward?)", "rays": len(pts)}
        arr = np.array(d_mm); wa = np.array(wts)
        order = np.argsort(arr)
        below = arr < min_wall_mm
        worst = _cluster([locs[i] for i in order[:400]], cell=max(min_wall_mm, 0.5))[:8]
        return {"pass": bool(arr.min() >= min_wall_mm), "min_wall_mm_required": min_wall_mm,
                "min_mm": round(float(arr.min()), 4), "p1_mm": round(float(np.percentile(arr, 1)), 4),
                "p5_mm": round(float(np.percentile(arr, 5)), 4), "median_mm": round(float(np.median(arr)), 4),
                "samples_below": int(below.sum()), "area_below_pct": round(float(wa[below].sum() / wa.sum() * 100), 3),
                "rays": int(len(pts)), "missed_rays": missed, "worst": worst}
    finally:
        bm.free()


def _inside(bvh, p, cap_bu):
    """Ray parity along 3 jittered axes, majority vote. Step past each hit by a size-relative epsilon (a fixed tiny
    step re-hits the same face and corrupts the parity)."""
    eps = max(cap_bu * 1e-5, 1e-9)
    votes = 0
    for d in (Vector((1, 0.000131, 0.000071)), Vector((0.000093, 1, 0.000117)), Vector((0.000061, 0.000083, 1))):
        d.normalize(); org = Vector(p); n = 0
        for _ in range(256):
            hit, _, _, dist = bvh.ray_cast(org, d, cap_bu)
            if hit is None:
                break
            n += 1; org = hit + d * eps
        votes += n % 2
    return votes >= 2


def check_clearance(parts, dg, bu_mm, min_clearance_mm=0.2, per_mm2=4.0, max_samples=60000):
    if len(parts) < 2:
        return {"pass": None, "note": "need at least 2 parts for clearance"}
    data = {}
    for o in parts:
        bm = _world_bmesh(o, dg)
        co, tris = _arrays(bm); bm.free()
        data[o.name] = (co, tris, _bvh_tris(co, tris))
    pairs = []
    names = list(data)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            A, B = data[names[i]], data[names[j]]
            lo = np.minimum(A[0].min(0), B[0].min(0)); hi = np.maximum(A[0].max(0), B[0].max(0))
            cap = float(np.linalg.norm(hi - lo)) * 2 + 1e-6
            interf = bool(A[2].overlap(B[2]))
            best = (float("inf"), None)
            for src, dst in ((A, B), (B, A)):
                pts, _, _ = _samples(src[0], src[1], per_mm2, bu_mm, max_samples)
                pts = np.vstack([pts, src[0]])
                for p in pts:
                    hit, _, _, dist = dst[2].find_nearest(Vector(p), cap)
                    if hit is not None and dist < best[0]:
                        best = (dist, p)
            contained = (not interf) and (_inside(B[2], A[0][0], cap) or _inside(A[2], B[0][0], cap))
            gap = 0.0 if (interf or contained) else best[0] * bu_mm
            pairs.append({"a": names[i], "b": names[j], "min_gap_mm": round(gap, 4), "interfering": interf,
                          "contained": contained, "at_mm": _mm(best[1], bu_mm) if best[1] is not None else None,
                          "pass": bool(not interf and not contained and gap >= min_clearance_mm)})
    return {"pass": all(p["pass"] for p in pairs), "min_clearance_mm_required": min_clearance_mm, "pairs": pairs}


def measure(o, dg, bu_mm):
    bm = _world_bmesh(o, dg)
    try:
        co, _ = _arrays(bm)
        lo, hi = co.min(0) * bu_mm, co.max(0) * bu_mm
        return {"volume_mm3": round(bm.calc_volume(signed=True) * bu_mm ** 3, 4),
                "area_mm2": round(sum(f.calc_area() for f in bm.faces) * bu_mm ** 2, 4),
                "bbox_min_mm": [round(float(x), 4) for x in lo], "bbox_max_mm": [round(float(x), 4) for x in hi],
                "bbox_size_mm": [round(float(x), 4) for x in hi - lo], "tris": sum(len(f.verts) - 2 for f in bm.faces)}
    finally:
        bm.free()


# ---------------------------------------------------------------- export + verify
def _reimport_bbox(path, fmt):
    before = set(bpy.data.objects)
    if fmt == "stl":
        bpy.ops.wm.stl_import(filepath=path, global_scale=1.0, use_scene_unit=False)
    else:
        bpy.ops.wm.obj_import(filepath=path, global_scale=1.0, forward_axis='Y', up_axis='Z')
    new = [o for o in bpy.data.objects if o not in before]
    pts = []
    for o in new:
        mw = o.matrix_world
        pts += [(mw @ v.co)[:] for v in o.data.vertices]
    for o in new:
        me = o.data; bpy.data.objects.remove(o, do_unlink=True)
        if me and me.users == 0:
            bpy.data.meshes.remove(me)
    if not pts:
        return None
    a = np.array(pts)
    return a.min(0), a.max(0)


def export_and_verify(objects, dg, out_dir, formats=("stl",), per_object=False, ascii=False, tol_mm=0.01):
    scale = _bu_to_mm()
    out_dir = bpy.path.abspath(out_dir or "//print")
    if out_dir.startswith("//") or not os.path.isabs(out_dir):
        out_dir = os.path.abspath(out_dir.lstrip("/"))
    os.makedirs(out_dir, exist_ok=True)
    groups = [[o] for o in objects] if per_object else [objects]
    prev_sel = [o for o in bpy.context.scene.objects if o.select_get()]
    prev_act = bpy.context.view_layer.objects.active
    files = []
    try:
        for grp in groups:
            # expected bbox in mm from evaluated world meshes
            pts = []
            for o in grp:
                bm = _world_bmesh(o, dg); co, _ = _arrays(bm); bm.free(); pts.append(co)
            allp = np.vstack(pts) * scale
            exp_lo, exp_hi = allp.min(0), allp.max(0)
            base = grp[0].name if per_object else (bpy.path.display_name_from_filepath(bpy.data.filepath) or "print_export")
            base = bpy.path.clean_name(base)
            written = []
            for fmt in formats:
                # (re)select every time: an importer run changes the selection
                for o in bpy.context.scene.objects:
                    o.select_set(False)
                for o in grp:
                    o.select_set(True)
                bpy.context.view_layer.objects.active = grp[0]
                path = os.path.join(out_dir, f"{base}.{fmt}")
                if fmt == "stl":
                    bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True, global_scale=scale, use_scene_unit=False,
                                          apply_modifiers=True, ascii_format=ascii, forward_axis='Y', up_axis='Z')
                elif fmt == "obj":
                    bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True, global_scale=scale, apply_modifiers=True,
                                          forward_axis='Y', up_axis='Z', export_materials=False, export_uv=False)
                elif fmt == "ply":
                    bpy.ops.wm.ply_export(filepath=path, export_selected_objects=True, global_scale=scale, apply_modifiers=True,
                                          forward_axis='Y', up_axis='Z', ascii_format=ascii)
                else:
                    files.append({"format": fmt, "error": "unsupported (3MF needs the 3MF Import/Export extension)"}); continue
                written.append((fmt, path))
            for fmt, path in written:  # verify after all formats are written
                rec = {"file": path, "format": fmt, "bytes": os.path.getsize(path) if os.path.exists(path) else 0,
                       "expected_bbox_size_mm": [round(float(x), 4) for x in exp_hi - exp_lo]}
                if rec["bytes"] == 0:
                    rec.update({"pass": False, "error": "file missing/empty (nothing selected or exporter refused)"})
                elif fmt in ("stl", "obj"):
                    try:
                        rb = _reimport_bbox(path, fmt)
                    except Exception as e:
                        rb = None; rec["error"] = f"re-import failed: {e}"
                    if rb is None:
                        rec["pass"] = False
                    else:
                        lo, hi = rb
                        err = float(max(np.abs(lo - exp_lo).max(), np.abs(hi - exp_hi).max()))
                        rec.update({"file_bbox_size_mm": [round(float(x), 4) for x in hi - lo],
                                    "max_bbox_error_mm": round(err, 5), "pass": err <= tol_mm})
                else:
                    rec["pass"] = True; rec["note"] = "written; not re-imported"
                files.append(rec)
    finally:
        for o in bpy.context.scene.objects:
            o.select_set(o in prev_sel)
        bpy.context.view_layer.objects.active = prev_act
    return {"pass": all(f.get("pass", False) for f in files if "error" not in f) and bool(files),
            "global_scale": scale, "tol_mm": tol_mm, "files": files}


ALL_CHECKS = ["units", "manifold", "intersect", "thickness", "clearance", "measure", "export"]


def run_print_gate(objects=None, parts=None, checks=None, min_wall_mm=0.8, min_clearance_mm=0.2, out_dir="//print",
                   formats=("stl",), per_object=False, samples_per_mm2=2.0, max_rays=150000, tol_mm=0.01, ascii=False):
    checks = list(checks or ALL_CHECKS)
    if isinstance(formats, str):
        formats = [f.strip().lower() for f in formats.split(",") if f.strip()]
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    objs = _select(objects)
    out = {"blender": bpy.app.version_string, "objects": [o.name for o in objs]}
    if not objs:
        out["summary"] = {"pass": False, "error": "no mesh objects matched"}; return out
    dg = _dg(); bu_mm = _bu_to_mm()
    if "units" in checks:
        out["units"] = check_units(objs)
    per = {}
    for o in objs:
        r = {}
        try:
            if "manifold" in checks: r["manifold"] = check_manifold(o, dg, bu_mm)
            if "intersect" in checks: r["intersect"] = check_intersect(o, dg, bu_mm)
            if "thickness" in checks: r["thickness"] = check_thickness(o, dg, bu_mm, min_wall_mm, samples_per_mm2, max_rays)
            if "measure" in checks: r["measure"] = measure(o, dg, bu_mm)
        except Exception as e:
            r["error"] = f"{type(e).__name__}: {e}"
        per[o.name] = r
    out["per_object"] = per
    if "clearance" in checks:
        pobjs = _select(parts) if parts else (objs if len(objs) > 1 else [])
        try:
            out["clearance"] = check_clearance(pobjs, dg, bu_mm, min_clearance_mm)
        except Exception as e:
            out["clearance"] = {"pass": False, "error": f"{type(e).__name__}: {e}"}
    if "export" in checks:
        try:
            out["export"] = export_and_verify(objs, dg, out_dir, formats, per_object, ascii, tol_mm)
        except Exception as e:
            out["export"] = {"pass": False, "error": f"{type(e).__name__}: {e}"}
    fails = []
    if out.get("units", {}).get("pass") is False: fails.append("units")
    for n, r in per.items():
        if "error" in r: fails.append(f"{n}:error")
        for c in ("manifold", "intersect", "thickness"):
            if r.get(c, {}).get("pass") is False: fails.append(f"{n}:{c}")
    if out.get("clearance", {}).get("pass") is False: fails.append("clearance")
    if out.get("export", {}).get("pass") is False: fails.append("export")
    out["summary"] = {"pass": not fails, "failed": fails}
    return out


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="export_print.py")
    p.add_argument("--objects", default=""); p.add_argument("--parts", default="")
    p.add_argument("--checks", default=",".join(ALL_CHECKS))
    p.add_argument("--min-wall-mm", type=float, default=0.8); p.add_argument("--min-clearance-mm", type=float, default=0.2)
    p.add_argument("--out-dir", default="//print"); p.add_argument("--formats", default="stl")
    p.add_argument("--per-object", action="store_true"); p.add_argument("--ascii", action="store_true")
    p.add_argument("--samples-per-mm2", type=float, default=2.0); p.add_argument("--max-rays", type=int, default=150000)
    p.add_argument("--tol-mm", type=float, default=0.01)
    a = p.parse_args(argv)
    return run_print_gate(a.objects, a.parts, a.checks.split(","), a.min_wall_mm, a.min_clearance_mm, a.out_dir,
                          a.formats, a.per_object, a.samples_per_mm2, a.max_rays, a.tol_mm, a.ascii)


if "PRINT_OPTS" in globals():
    result = run_print_gate(**PRINT_OPTS); print(json.dumps(result["summary"]))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("EXPORT_PRINT " + json.dumps(result, default=str))
else:
    result = {"defined": ["run_print_gate", "check_units", "check_manifold", "check_intersect", "check_thickness",
                          "check_clearance", "measure", "export_and_verify"]}
