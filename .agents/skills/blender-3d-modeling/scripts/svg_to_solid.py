"""SVG logo / vector outline -> clean solid mesh at an exact size: import, join, scale to target width, extrude, bevel
with an automatic bevel clamp derived from the smallest feature, convert to mesh, merge seams, centre the origin, report.

Headless / CLI (prints one line: SVG_TO_SOLID <json>):
    blender -b --factory-startup --python svg_to_solid.py -- --svg logo.svg --width-mm 50 --depth-mm 4 \
        [--bevel-mm 0.6 --bevel-resolution 3 --no-clamp --clamp-ratio 0.4 --method curve|mesh \
         --fill-rule EVEN_ODD|NONZERO --solver CDT|SWEEP_LINE --resolution 12 --origin CENTER|BOTTOM_CENTER \
         --upright --name LOGO_Mark --keep-source --keep-bezier --merge-mm 0.001 --save out.blend]
    (--width <m> instead of --width-mm; omit both to keep the importer's size)
Live (Blender:execute_blender_code): set before exec
    SVG_TO_SOLID_OPTS = {"svg": "C:/path/logo.svg", "width_mm": 50, "depth_mm": 4, "bevel_mm": 0.6}  -> `result` dict
Without SVG_TO_SOLID_OPTS the file only defines svg_to_solid / import_svg / join_splines / feature_size / topology /
self_intersections (usable on any bmesh).

How it works
- Importer: bundled core add-on io_curve_svg (`bpy.ops.import_curve.svg`), one 2D curve object per filled path, 90 px/in
  (1 px = 0.2822 mm; Inkscape documents are 96 px/in, so px-sized files come in 6.7 % small -- hence --width-mm).
  Paths without fill become 3D (unfilled) curves and are skipped (reported as `unfilled_paths_skipped`).
- All filled splines are joined into ONE 2D curve (world-space control points, materials kept per spline), so holes
  (counters) are cut by the fill rule across the whole logo: EVEN_ODD (default) makes nested outlines holes regardless of
  winding -- overlapping separate shapes therefore cancel; use --fill-rule NONZERO --solver CDT for unions.
- Size: the flat fill is measured, control points are scaled/centred so the final X width = target (bevel doesn't grow it).
- Curve method (default): extrude = depth/2 - bevel, bevel_depth = bevel, offset = -bevel -> silhouette stays on the original
  outline, the flat caps shrink inward by `bevel`. Mesh method: flat fill -> Solidify(depth) -> Bevel modifier (angle 30 deg,
  clamp overlap) -- beveled sharp tips shorten, so width can come in under target.
- Clamp: min feature radius = half the smallest material thickness measured by 2D rays along inward boundary normals,
  ignoring samples inside the wedge of a sharp convex corner (< 60 deg; sharp tips are rounded by the bevel, not a
  thickness limit). bevel <= clamp_ratio x radius and <= depth/2. Then the evaluated mesh is tested for self-intersection
  (BVH overlap of faces sharing no vertex); while any remain the bevel is multiplied by 0.7 (max 8 tries).
- Gates: width within 0.1 mm of target, holes preserved (flat fill loops-minus-islands == genus of the closed solid),
  0 non-manifold edges after merge, 0 self-intersecting face pairs.
Limitations: raster <image>, text elements and strokes in the SVG are ignored (convert strokes/text to paths first);
gap between separate shapes is reported (`min_gap_mm`) but not used for the clamp because an inset bevel never closes gaps.
"""
import bpy, bmesh, json, math, os, sys
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

MM = 0.001


# ---------------------------------------------------------------- import / join
def _ensure_svg_importer():
    try:
        bpy.ops.import_curve.svg.get_rna_type()
    except Exception:
        import addon_utils
        addon_utils.enable("io_curve_svg", default_set=False)
        bpy.ops.import_curve.svg.get_rna_type()


def import_svg(path):
    """Run the bundled importer; return (new objects, new collections)."""
    _ensure_svg_importer()
    ob0, co0 = set(bpy.data.objects), set(bpy.data.collections)
    bpy.ops.import_curve.svg(filepath=os.path.abspath(path))
    return [o for o in bpy.data.objects if o not in ob0], [c for c in bpy.data.collections if c not in co0]


def join_splines(objs, name):
    """Copy the splines of all filled (2D) curve objects into one new 2D curve datablock, world space."""
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '2D'
    mats, skipped = [], 0
    for o in objs:
        if o.type != 'CURVE':
            continue
        if o.data.dimensions != '2D':
            skipped += 1; continue
        mw = o.matrix_world
        for sp in o.data.splines:
            m = o.data.materials[sp.material_index] if sp.material_index < len(o.data.materials) else None
            if m not in mats:
                mats.append(m)
            ns = cu.splines.new(sp.type)
            ns.use_cyclic_u, ns.material_index = sp.use_cyclic_u, mats.index(m)
            if sp.type == 'BEZIER':
                ns.bezier_points.add(len(sp.bezier_points) - 1)
                for a, b in zip(sp.bezier_points, ns.bezier_points):
                    b.handle_left_type = b.handle_right_type = 'FREE'
                    b.co, b.handle_left, b.handle_right = mw @ a.co, mw @ a.handle_left, mw @ a.handle_right
            else:
                ns.points.add(len(sp.points) - 1)
                for a, b in zip(sp.points, ns.points):
                    b.co = (*(mw @ Vector(a.co[:3])), a.co[3])
                ns.order_u, ns.use_endpoint_u = sp.order_u, sp.use_endpoint_u
    for m in mats:
        cu.materials.append(m)
    return cu, skipped


def _transform_curve(cu, M):
    for sp in cu.splines:
        if sp.type == 'BEZIER':
            for p in sp.bezier_points:
                p.co, p.handle_left, p.handle_right = M @ p.co, M @ p.handle_left, M @ p.handle_right
        else:
            for p in sp.points:
                p.co = (*(M @ Vector(p.co[:3])), p.co[3])


def bezier_to_poly(cu, resolution=12):
    """Replace BEZIER splines by POLY splines. Straight segments keep only their end points: evaluated in-between points
    fold past each other under an inset bevel near sharp corners (measured: 20 deg tip self-intersects at any bevel
    larger than the evaluated point spacing x tan 10 deg). Curved segments are sampled with `resolution` steps."""
    from mathutils.geometry import interpolate_bezier
    old = []
    for si, sp in enumerate(cu.splines):
        if sp.type != 'BEZIER':
            continue
        bp = sp.bezier_points; n = len(bp); pts = []
        for i in range(n if sp.use_cyclic_u else n - 1):
            a, b = bp[i], bp[(i + 1) % n]
            p0, p1, p2, p3 = a.co.copy(), a.handle_right.copy(), b.handle_left.copy(), b.co.copy()
            ch = p3 - p0; L = ch.length
            straight = L < 1e-12 or all((h - p0).cross(ch).length / L <= 1e-6 * L and -1e-9 <= (h - p0).dot(ch) / L <= L + 1e-9
                                        for h in (p1, p2))
            pts.extend([p0] if straight else interpolate_bezier(p0, p1, p2, p3, resolution + 1)[:-1])
        if not sp.use_cyclic_u:
            pts.append(bp[n - 1].co.copy())
        old.append((si, pts, sp.use_cyclic_u, sp.material_index))
    for si, pts, cyc, mi in old:
        ns = cu.splines.new('POLY'); ns.points.add(len(pts) - 1)
        for p, c in zip(ns.points, pts):
            p.co = (c.x, c.y, c.z, 1.0)
        ns.use_cyclic_u, ns.material_index = cyc, mi
    for si, *_ in sorted(old, reverse=True):
        cu.splines.remove(cu.splines[si])
    return len(old)


def _link(ob):
    bpy.context.scene.collection.objects.link(ob); return ob


def _eval_bmesh(ob, merge=0.0):
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), depsgraph=dg)
    bm = bmesh.new(); bm.from_mesh(me); bpy.data.meshes.remove(me)
    if merge > 0:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge)
    return bm


# ---------------------------------------------------------------- analysis
def topology(bm):
    """Islands, boundary loops, non-manifold edges, Euler characteristic, holes.
    Flat fill: holes = boundary loops - islands. Closed solid (no boundary): holes = total genus = (2*islands - euler)/2."""
    bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    adj = {}
    for e in bm.edges:
        if e.is_boundary:
            a, b = e.verts[0].index, e.verts[1].index
            adj.setdefault(a, []).append(b); adj.setdefault(b, []).append(a)
    seen, loops = set(), 0
    for v in adj:
        if v in seen:
            continue
        loops += 1; st = [v]
        while st:
            x = st.pop()
            if x not in seen:
                seen.add(x); st.extend(adj[x])
    fseen, islands = set(), 0
    for f in bm.faces:
        if f.index in fseen:
            continue
        islands += 1; st = [f]
        while st:
            g = st.pop()
            if g.index in fseen:
                continue
            fseen.add(g.index)
            for e in g.edges:
                st.extend(h for h in e.link_faces if h.index not in fseen)
    used = sum(1 for v in bm.verts if v.link_faces)
    euler = used - sum(1 for e in bm.edges if e.link_faces) + len(bm.faces)
    nonman = sum(1 for e in bm.edges if not e.is_manifold)
    holes = (loops - islands) if loops else (2 * islands - euler) // 2
    return {"islands": islands, "boundary_loops": loops, "non_manifold_edges": nonman, "euler": euler, "holes": holes}


def _ray_hits(O, D, A, B, S_idx, seg_idx):
    """Nearest hit distance of 2D rays O+tD against segments A-B, skipping segments that share a vertex with the ray's own edge."""
    E = B - A; N = len(O)
    tbest = np.full(N, np.inf); hit = np.full(N, -1)
    chunk = max(1, 2_000_000 // max(1, len(A)))
    for s in range(0, N, chunk):
        o, d, sv = O[s:s + chunk], D[s:s + chunk], S_idx[s:s + chunk]
        den = d[:, None, 0] * E[None, :, 1] - d[:, None, 1] * E[None, :, 0]
        w = A[None, :, :] - o[:, None, :]
        with np.errstate(divide='ignore', invalid='ignore'):
            t = (w[..., 0] * E[None, :, 1] - w[..., 1] * E[None, :, 0]) / den
            u = (w[..., 0] * d[:, None, 1] - w[..., 1] * d[:, None, 0]) / den
        ok = (np.abs(den) > 1e-18) & (t > 1e-9) & (u >= -1e-9) & (u <= 1 + 1e-9)
        adj = ((seg_idx[None, :, 0] == sv[:, None, 0]) | (seg_idx[None, :, 0] == sv[:, None, 1]) |
               (seg_idx[None, :, 1] == sv[:, None, 0]) | (seg_idx[None, :, 1] == sv[:, None, 1]))
        t = np.where(ok & ~adj, t, np.inf)
        j = t.argmin(1); tb = t[np.arange(len(o)), j]
        tbest[s:s + chunk] = tb; hit[s:s + chunk] = np.where(np.isfinite(tb), j, -1)
    return tbest, hit


def feature_size(bm, sharp_deg=60.0):
    """Smallest material thickness / gap of a flat (z=0) fill mesh, excluding sharp-corner wedges. Units = mesh units."""
    bm.verts.ensure_lookup_table()
    bnd = [e for e in bm.edges if e.is_boundary]
    if not bnd:
        return {"min_feature_radius": float("inf"), "min_gap": float("inf"), "sharp_corners": 0, "samples": 0}
    P = np.array([v.co[:2] for v in bm.verts])
    seg = np.array([[e.verts[0].index, e.verts[1].index] for e in bnd])
    A, B = P[seg[:, 0]], P[seg[:, 1]]
    d = B - A; L = np.linalg.norm(d, axis=1); good = L > 1e-12
    seg, A, B, d, L = seg[good], A[good], B[good], d[good], L[good]
    bnd = [e for e, g in zip(bnd, good) if g]
    mid = (A + B) / 2
    n = np.stack([-d[:, 1], d[:, 0]], 1) / L[:, None]
    fc = np.array([e.link_faces[0].calc_center_median()[:2] for e in bnd])
    n[((fc - mid) * n).sum(1) < 0] *= -1                     # inward = material side
    t_in, _ = _ray_hits(mid, n, A, B, seg, seg)
    t_out, _ = _ray_hits(mid, -n, A, B, seg, seg)
    # sharp corners: boundary vertices with 2 boundary edges and a small opening angle
    vedges = {}
    for k, (a, b) in enumerate(seg):
        vedges.setdefault(a, []).append(k); vedges.setdefault(b, []).append(k)
    cvx, ccv = [], []
    for v, ks in vedges.items():
        if len(ks) != 2:
            continue
        o1 = seg[ks[0]][1] if seg[ks[0]][0] == v else seg[ks[0]][0]
        o2 = seg[ks[1]][1] if seg[ks[1]][0] == v else seg[ks[1]][0]
        a = P[o1] - P[v]; b = P[o2] - P[v]
        a /= np.linalg.norm(a); b /= np.linalg.norm(b)
        phi = math.acos(max(-1.0, min(1.0, float(a @ b))))
        if math.degrees(phi) < sharp_deg:
            convex = float((a + b) @ (n[ks[0]] + n[ks[1]])) > 0
            (cvx if convex else ccv).append((P[v][0], P[v][1], phi))

    def excluded(t, dirs, corners):
        if not corners:
            return np.zeros(len(t), bool)
        C = np.array([c[:2] for c in corners]); sphi = np.sin(np.array([c[2] for c in corners]))
        tt = np.where(np.isfinite(t), t, 0.0)
        R = 1.5 * tt[:, None] / np.maximum(sphi[None, :], 1e-6)
        hp = mid + dirs * tt[:, None]
        ds = np.linalg.norm(mid[:, None, :] - C[None], axis=2); dh = np.linalg.norm(hp[:, None, :] - C[None], axis=2)
        return ((ds <= R) & (dh <= R)).any(1)

    ok_in = np.isfinite(t_in) & ~excluded(t_in, n, cvx)
    ok_out = np.isfinite(t_out) & ~excluded(t_out, -n, ccv)
    angles = [math.degrees(c[2]) for c in cvx + ccv]
    return {"min_feature_radius": float(t_in[ok_in].min() / 2) if ok_in.any() else float("inf"),
            "min_gap": float(t_out[ok_out].min()) if ok_out.any() else float("inf"),
            "sharp_corners": len(cvx) + len(ccv), "min_corner_deg": round(min(angles), 1) if angles else None,
            "samples": int(len(mid)), "wedge_samples_excluded": int((np.isfinite(t_in) & ~ok_in).sum())}


def self_intersections(bm, sample=5):
    """Count face pairs that overlap but share no vertex (BVH overlap on a triangulated copy)."""
    c = bm.copy()
    bmesh.ops.triangulate(c, faces=c.faces[:])
    c.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(c)
    vs = [frozenset(v.index for v in f.verts) for f in c.faces]
    bad = {(min(i, j), max(i, j)) for i, j in tree.overlap(tree) if i != j and not (vs[i] & vs[j])}
    locs = [[round(x, 5) for x in c.faces[i].calc_center_median()] for i, _ in list(bad)[:sample]]
    c.free()
    return len(bad), locs


# ---------------------------------------------------------------- build
def _build(src_cu, name, depth, bevel, bev_res, method, merge):
    cu = src_cu.copy()
    if method == 'curve':
        cu.extrude, cu.bevel_depth, cu.offset, cu.bevel_resolution = max(depth / 2 - bevel, 0.0), bevel, -bevel, bev_res
        tmp = _link(bpy.data.objects.new(name + "_tmp", cu))
        bm = _eval_bmesh(tmp, merge)
        bpy.data.objects.remove(tmp)
    else:
        cu.extrude = cu.bevel_depth = cu.offset = 0.0
        tmp = _link(bpy.data.objects.new(name + "_tmp", cu))
        flat = _eval_bmesh(tmp, merge); bpy.data.objects.remove(tmp)
        me = bpy.data.meshes.new(name + "_tmpmesh"); flat.to_mesh(me); flat.free()
        mo = _link(bpy.data.objects.new(name + "_tmpmesh", me))
        so = mo.modifiers.new("Solidify", 'SOLIDIFY'); so.thickness, so.offset, so.use_even_offset = depth, 0.0, True
        if bevel > 0:
            bv = mo.modifiers.new("Bevel", 'BEVEL')
            bv.width, bv.segments, bv.limit_method, bv.angle_limit, bv.use_clamp_overlap = bevel, max(1, bev_res + 1), 'ANGLE', math.radians(30), True
        bm = _eval_bmesh(mo, merge)
        bpy.data.objects.remove(mo); bpy.data.meshes.remove(me)
    bpy.data.curves.remove(cu)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def svg_to_solid(svg, width_mm=None, width=None, depth_mm=2.0, bevel_mm=0.0, bevel_resolution=3, clamp=True,
                 clamp_ratio=0.4, method='curve', fill_rule='EVEN_ODD', solver='CDT', resolution=12, origin='CENTER',
                 upright=False, name="LOGO_Solid", keep_source=False, merge_mm=0.001, max_iter=8, poly=True, save=None):
    target = width if width is not None else (width_mm * MM if width_mm else None)
    depth, merge = depth_mm * MM, merge_mm * MM
    objs, cols = import_svg(svg)
    curves = [o for o in objs if o.type == 'CURVE']
    if not curves:
        return {"error": "SVG importer produced no curve objects", "svg": svg}
    for old in (name, name + "_src"):
        if old in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[old])
    cu, skipped = join_splines(curves, name + "_src")
    cu.fill_mode = 'BOTH'
    if hasattr(cu, "fill_solver"):                           # 5.1+
        cu.fill_solver, cu.fill_rule = solver, fill_rule
    for sp in cu.splines:
        sp.resolution_u = resolution
    if poly:
        bezier_to_poly(cu, resolution)
    src = _link(bpy.data.objects.new(name + "_src", cu))
    for o in objs:
        data = o.data
        bpy.data.objects.remove(o)
        if data is not None and data.users == 0 and isinstance(data, bpy.types.Curve):
            bpy.data.curves.remove(data)
    for c in cols:
        bpy.data.collections.remove(c)

    flat = _eval_bmesh(src)
    if not flat.verts:
        return {"error": "fill produced no faces (open paths or no fill)", "svg": svg}
    co = np.array([v.co[:] for v in flat.verts]); flat.free()
    w0 = float(np.ptp(co[:, 0])); cx, cy = (co[:, 0].max() + co[:, 0].min()) / 2, (co[:, 1].max() + co[:, 1].min()) / 2
    k = target / w0 if target else 1.0
    _transform_curve(cu, Matrix.Diagonal((k, k, 1.0, 1.0)) @ Matrix.Translation((-cx, -cy, 0.0)))
    flat = _eval_bmesh(src, merge)
    ftopo, feat = topology(flat), feature_size(flat)
    flat.free()

    b_req = bevel_mm * MM
    b_est = clamp_ratio * feat["min_feature_radius"]
    b = min(b_req, depth / 2)
    if clamp:
        b = min(b, b_est)
    tries = []
    for it in range(max_iter):
        bm = _build(cu, name, depth, b, bevel_resolution, method, merge)
        si, locs = self_intersections(bm)
        tries.append({"bevel_mm": round(b / MM, 4), "self_intersections": si})
        if si == 0 or not clamp or b <= 1e-7 or it == max_iter - 1:
            break
        bm.free(); b *= 0.7
    topo = topology(bm)
    zero_area = sum(1 for f in bm.faces if f.calc_area() < 1e-12)
    if upright:
        bmesh.ops.rotate(bm, verts=bm.verts[:], cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, 'X'))
    V = np.array([v.co[:] for v in bm.verts])
    lo, hi = V.min(0), V.max(0)
    shift = -(lo + hi) / 2
    if origin.upper() in ("BOTTOM_CENTER", "CENTER_BOTTOM"):
        shift[2] = -lo[2]
    bmesh.ops.translate(bm, verts=bm.verts[:], vec=Vector(shift))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in cu.materials:
        me.materials.append(m)
    ob = _link(bpy.data.objects.new(name, me))
    if keep_source:
        src.hide_viewport = src.hide_render = True
    else:
        bpy.data.objects.remove(src); bpy.data.curves.remove(cu)
    dims = (hi - lo) / MM
    werr = (dims[0] - target / MM) if target else None
    gates = {"width_within_0.1mm": (abs(werr) <= 0.1) if target else None,
             "holes_preserved": topo["holes"] == ftopo["holes"],
             "manifold": topo["non_manifold_edges"] == 0,
             "no_self_intersection": tries[-1]["self_intersections"] == 0}
    result = {"object": ob.name, "method": method, "blender": bpy.app.version_string,
              "size_mm": [round(float(x), 4) for x in dims], "width_error_mm": round(float(werr), 5) if target else None,
              "import_scale_to_target": round(k, 6), "unfilled_paths_skipped": skipped,
              "splines": len(cu.splines) if keep_source else None,
              "flat": ftopo, "solid": topo, "zero_area_faces": zero_area,
              "verts": len(me.vertices), "faces": len(me.polygons),
              "min_feature_radius_mm": round(feat["min_feature_radius"] / MM, 4), "min_gap_mm": round(feat["min_gap"] / MM, 4) if math.isfinite(feat["min_gap"]) else None,
              "sharp_corners": feat["sharp_corners"], "min_corner_deg": feat["min_corner_deg"],
              "wedge_samples_excluded": feat["wedge_samples_excluded"],
              "bevel_requested_mm": bevel_mm, "bevel_clamp_estimate_mm": round(b_est / MM, 4), "bevel_used_mm": tries[-1]["bevel_mm"],
              "clamp": clamp, "tries": tries, "self_intersection_samples": locs if tries[-1]["self_intersections"] else [],
              "gates": {k: (None if v is None else bool(v)) for k, v in gates.items()},
              "pass": bool(all(v for v in gates.values() if v is not None))}
    if save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(save))
    return result


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="svg_to_solid.py")
    p.add_argument("--svg", required=True)
    p.add_argument("--width-mm", type=float); p.add_argument("--width", type=float)
    p.add_argument("--depth-mm", type=float, default=2.0); p.add_argument("--bevel-mm", type=float, default=0.0)
    p.add_argument("--bevel-resolution", type=int, default=3)
    p.add_argument("--no-clamp", action="store_true"); p.add_argument("--clamp-ratio", type=float, default=0.4)
    p.add_argument("--method", choices=["curve", "mesh"], default="curve")
    p.add_argument("--fill-rule", choices=["EVEN_ODD", "NONZERO"], default="EVEN_ODD")
    p.add_argument("--solver", choices=["CDT", "SWEEP_LINE"], default="CDT")
    p.add_argument("--resolution", type=int, default=12)
    p.add_argument("--origin", default="CENTER"); p.add_argument("--upright", action="store_true")
    p.add_argument("--name", default="LOGO_Solid"); p.add_argument("--keep-source", action="store_true")
    p.add_argument("--merge-mm", type=float, default=0.001); p.add_argument("--save")
    p.add_argument("--keep-bezier", action="store_true", help="skip bezier_to_poly (folds at sharp corners)")
    a = p.parse_args(argv)
    return svg_to_solid(a.svg, width_mm=a.width_mm, width=a.width, depth_mm=a.depth_mm, bevel_mm=a.bevel_mm,
                        bevel_resolution=a.bevel_resolution, clamp=not a.no_clamp, clamp_ratio=a.clamp_ratio,
                        method=a.method, fill_rule=a.fill_rule, solver=a.solver, resolution=a.resolution,
                        origin=a.origin, upright=a.upright, name=a.name, keep_source=a.keep_source,
                        merge_mm=a.merge_mm, poly=not a.keep_bezier, save=a.save)


if "SVG_TO_SOLID_OPTS" in globals():
    result = svg_to_solid(**SVG_TO_SOLID_OPTS)
    print("SVG_TO_SOLID " + json.dumps(result))
elif __name__ == "__main__" and "--" in sys.argv and "--svg" in sys.argv[sys.argv.index("--") + 1:]:
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print("SVG_TO_SOLID " + json.dumps(result))
else:
    result = {"defined": ["svg_to_solid", "import_svg", "join_splines", "feature_size", "topology", "self_intersections", "bezier_to_poly"]}
