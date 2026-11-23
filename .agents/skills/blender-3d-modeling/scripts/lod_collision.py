"""LOD chain + game collision generator with measured quality: tris per LOD, surface deviation, silhouette overlap,
convex-hull collision (UCX_), box (UBX_) / sphere (USP_) primitives, sockets, optional FBX LodGroup empty.

Headless / CLI (prints one line: LOD_COLLISION <json>):
    blender -b asset.blend --python lod_collision.py -- (--object NAME | --objects A,B,C | --source-collection KIT)
        [--ratios 1,0.5,0.25,0.125] [--method COLLAPSE|PLANAR|UNSUBDIV] [--symmetry X|Y|Z] [--chain] [--triangulate]
        [--lod-group] [--collision convex,box,sphere] [--per-part] [--max-hull-tris 255] [--render-name SM_Crate]
        [--check-collision UCX_Crate_,UBX_Crate_] [--max-dev-pct 1.0] [--min-iou 0.95] [--samples 3000]
        [--out-collection EXPORT] [--save out.blend]
    --collection NAME  deprecated alias of --out-collection (still accepted, adds a line to "warnings" in the JSON).
                       Note it names the OUTPUT collection; the input scope is --source-collection, unlike the other
                       scripts of this skill where --collection is the input scope.
Live (Blender:execute_blender_code): set before exec
    LOD_OPTS = {"object": "Crate", "ratios": [1, .5, .25], "collision": ["convex"], "lod_group": True}  -> `result` dict
    LOD_OPTS = {"source_collection": "KIT", "ratios": [1, .5], "collision": ["box"], "out_collection": "EXPORT"}
Without LOD_OPTS the file only defines generate_lods, make_collision, check_collision, add_socket, run.

Modes: --object NAME runs one object and returns {lods, collision, check_collision, warnings, pass} (shape unchanged).
--objects A,B,C and/or --source-collection NAME (every MESH object in it, child collections included; generated
*_LODn and UCX_/UBX_/USP_ objects are skipped so re-runs are idempotent) run the same pipeline per object and return
results: [{object, lods, collision, pass}, ...] plus the overall pass; a missing, non-mesh or failing object is
recorded with "error" and pass false without stopping the batch (traceback on stderr). --render-name applies to
single-object runs only (in a batch each object's own name is the render name). --out-collection receives the LODs,
LodGroup and collision objects (created and linked to the scene collection when missing); without it they join the
source object's collections. --check-collision is global (name prefixes), not per object.

LODs: new objects <base>_LOD0..n (LOD0 = source with modifiers applied; source untouched; re-running replaces them).
Each LOD is decimated from LOD0 (or from the previous level with --chain) and the ratio is corrected up to 4 times so
tris land within 5 % of target (COLLAPSE). PLANAR (Decimate 'DISSOLVE') searches the angle limit to reach the target;
it can stall on curved surfaces (reported, not forced). Quality per LOD, world space:
  deviation  symmetric Hausdorff-like distance: area-weighted surface samples + vertices of each mesh -> nearest point
             on the other (BVHTree.find_nearest); max / p95 / mean in mm and max as % of the LOD0 bbox diagonal
  silhouette orthographic ray-cast masks along X, Y, Z (64x64); IoU vs LOD0, min over the 3 axes
  gate       tris within 15 % of target, max deviation <= max_dev_pct * 2^(level-1) % of diagonal, IoU >= min_iou
Collision: named <PREFIX><render_name>_NN (Unreal FBX convention), same parent + world matrix as the source, wire,
hidden from render. Convex hulls come from bmesh.ops.convex_hull; with max_hull_tris the hull is reduced by keeping
extreme vertices per grid cell, re-hulled, then scaled about its centroid just enough to enclose every source vertex.
Every hull is verified: convex (no vertex in front of any face plane) and enclosing (max source vertex outside, mm).
Limitations: deviation is sampled (small spikes between samples can be missed); convex hulls of concave assets are
coarse (use --per-part on separate loose parts, or model UCX pieces by hand); sphere/box are bounds-based.
Decimation does not lock border (open-edge) vertices: on kit pieces whose socket edges must stay aligned, COLLAPSE can
move boundary vertices - mark the borders sharp/seam and use PLANAR (its SEAM/SHARP delimiters keep them), then re-run
tile_sockets.py on the LODs.
"""
import bpy, bmesh, json, math, re, sys
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

LOD_RE = re.compile(r"_LOD\d+$")
PREFIX = {"convex": "UCX_", "box": "UBX_", "sphere": "USP_"}


# ------------------------------------------------------------------ helpers
def _base(name):
    return LOD_RE.sub("", name)


def _arrays(me, mw=None):
    me.calc_loop_triangles()
    co = np.empty(len(me.vertices) * 3, np.float64); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    tri = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("vertices", tri); tri = tri.reshape(-1, 3)
    if mw is not None:
        m = np.array(mw); co = co @ m[:3, :3].T + m[:3, 3]
    return co, tri


def _eval_copy(obj, name):
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    me.name = name
    return me


def _remove(name):
    o = bpy.data.objects.get(name)
    if o is None: return
    data = o.data
    bpy.data.objects.remove(o, do_unlink=True)
    if isinstance(data, bpy.types.Mesh) and data.users == 0:
        bpy.data.meshes.remove(data)


def _new_obj(name, data, like, collection=None):
    _remove(name)
    o = bpy.data.objects.new(name, data)
    cols = [collection] if collection else (list(like.users_collection) or [bpy.context.scene.collection])
    for c in cols: c.objects.link(o)
    o.parent = like.parent
    o.matrix_world = like.matrix_world.copy()
    return o


def _tris(me):
    me.calc_loop_triangles(); return len(me.loop_triangles)


def _decimate(obj, method, ratio, symmetry, angle_deg, iterations):
    m = obj.modifiers.new("__LOD_DECIMATE__", 'DECIMATE')
    if method == 'COLLAPSE':
        m.decimate_type = 'COLLAPSE'; m.ratio = max(1e-4, min(1.0, ratio))
        if symmetry: m.use_symmetry = True; m.symmetry_axis = symmetry
    elif method == 'PLANAR':
        m.decimate_type = 'DISSOLVE'; m.angle_limit = math.radians(angle_deg); m.delimit = {'NORMAL', 'MATERIAL', 'SEAM', 'SHARP', 'UV'}
    else:
        m.decimate_type = 'UNSUBDIV'; m.iterations = iterations
    me = _eval_copy(obj, obj.name + "__tmp")
    obj.modifiers.remove(m)
    return me


def _sample(co, tri, n, rng):
    a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) * 0.5
    if area.sum() <= 0: return co
    idx = rng.choice(len(tri), n, p=area / area.sum())
    u, v = rng.random(n), rng.random(n); f = u + v > 1; u[f], v[f] = 1 - u[f], 1 - v[f]
    return np.vstack([a[idx] + (b[idx] - a[idx]) * u[:, None] + (c[idx] - a[idx]) * v[:, None], co])


def _bvh(co, tri):
    return BVHTree.FromPolygons([tuple(p) for p in co], [tuple(int(i) for i in t) for t in tri], all_triangles=True)


def _dists(pts, bvh):
    out = np.empty(len(pts))
    for i, p in enumerate(pts):
        h = bvh.find_nearest(Vector(p), 1e6)
        out[i] = h[3] if h[0] is not None else 1e6
    return out


def _silhouette(bvh, lo, hi, axis, res=64):
    u, v = [k for k in range(3) if k != axis]
    mask = np.zeros((res, res), bool)
    d = Vector((0, 0, 0)); d[axis] = -1.0
    pad = (hi - lo).max() * 0.02
    for i in range(res):
        for j in range(res):
            o = Vector((0, 0, 0))
            o[u] = lo[u] - pad + (i + .5) * (hi[u] - lo[u] + 2 * pad) / res
            o[v] = lo[v] - pad + (j + .5) * (hi[v] - lo[v] + 2 * pad) / res
            o[axis] = hi[axis] + pad + 1.0
            mask[i, j] = bvh.ray_cast(o, d)[0] is not None
    return mask


def measure(ref, test, samples=3000, seed=1):
    """Compare two (co, tri) world-space meshes: deviation stats (m) and silhouette IoU per axis."""
    rng = np.random.default_rng(seed)
    (ca, ta), (cb, tb) = ref, test
    ba, bb = _bvh(ca, ta), _bvh(cb, tb)
    d_ab = _dists(_sample(ca, ta, samples, rng), bb); d_ba = _dists(_sample(cb, tb, samples, rng), ba)
    allv = np.concatenate([d_ab, d_ba])
    lo, hi = ca.min(0), ca.max(0); diag = float(np.linalg.norm(hi - lo))
    ious = []
    for ax in range(3):
        ma, mb = _silhouette(ba, lo, hi, ax), _silhouette(bb, lo, hi, ax)
        un = np.logical_or(ma, mb).sum(); ious.append(float(np.logical_and(ma, mb).sum() / un) if un else 1.0)
    return {"max_dev_mm": round(float(allv.max()) * 1000, 3), "p95_dev_mm": round(float(np.percentile(allv, 95)) * 1000, 3),
            "mean_dev_mm": round(float(allv.mean()) * 1000, 3), "max_dev_pct_diag": round(float(allv.max()) / diag * 100, 3) if diag else 0.0,
            "lod_to_ref_max_mm": round(float(d_ba.max()) * 1000, 3), "ref_to_lod_max_mm": round(float(d_ab.max()) * 1000, 3),
            "silhouette_iou_xyz": [round(x, 4) for x in ious], "silhouette_iou_min": round(min(ious), 4)}


# ------------------------------------------------------------------ LODs
def generate_lods(object, ratios=(1.0, 0.5, 0.25, 0.125), method="COLLAPSE", symmetry=None, chain=False, triangulate=False,
                  lod_group=False, collection=None, samples=3000, max_dev_pct=1.0, min_iou=0.95, tolerance=0.15):
    src = bpy.data.objects[object] if isinstance(object, str) else object
    base = _base(src.name); method = method.upper()
    col = bpy.data.collections.get(collection) if isinstance(collection, str) else collection
    lod0_me = _eval_copy(src, f"{base}_LOD0")
    lod0 = _new_obj(f"{base}_LOD0", lod0_me, src, col)
    ref = _arrays(lod0.data, lod0.matrix_world); t0 = _tris(lod0.data)
    lods = [{"name": lod0.name, "level": 0, "tris": t0, "target_tris": t0, "ratio": 1.0}]
    prev = lod0
    for lvl, r in enumerate(ratios[1:], start=1):
        target = max(4, int(round(t0 * r)))
        work_src = prev if chain else lod0
        name = f"{base}_LOD{lvl}"
        tmp = _new_obj(name, work_src.data.copy(), src, col)
        info = {"name": name, "level": lvl, "target_tris": target}
        if method == 'COLLAPSE':
            rr = target / max(1, _tris(work_src.data)); me = None
            for _ in range(5):
                if me: bpy.data.meshes.remove(me)
                me = _decimate(tmp, 'COLLAPSE', rr, symmetry, 0, 0); t = _tris(me)
                if abs(t - target) / target <= 0.05: break
                rr = min(1.0, rr * target / max(1, t))
            info["decimate_ratio"] = round(rr, 4)
        elif method == 'PLANAR':
            lo_a, hi_a, me, best = 0.1, 60.0, None, None
            for _ in range(10):
                mid = (lo_a + hi_a) / 2; cand = _decimate(tmp, 'PLANAR', 0, None, mid, 0); t = _tris(cand)
                if best is None or abs(t - target) < abs(_tris(best[1]) - target):
                    if best: bpy.data.meshes.remove(best[1])
                    best = (mid, cand)
                else:
                    bpy.data.meshes.remove(cand)
                if t > target: lo_a = mid
                else: hi_a = mid
            me = best[1]; info["angle_limit_deg"] = round(best[0], 2)
        else:
            me = _decimate(tmp, 'UNSUBDIV', 0, None, 0, lvl if not chain else 1)
        old = tmp.data; tmp.data = me; me.name = name
        if old.users == 0: bpy.data.meshes.remove(old)
        if triangulate:
            bm = bmesh.new(); bm.from_mesh(tmp.data); bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
            bm.to_mesh(tmp.data); bm.free()
        info["tris"] = _tris(tmp.data); info["ratio"] = round(info["tris"] / t0, 4)
        q = measure(ref, _arrays(tmp.data, tmp.matrix_world), samples)
        info.update(q)
        allowed = max_dev_pct * 2 ** (lvl - 1)
        fails = []
        if abs(info["tris"] - target) / target > tolerance: fails.append(f"tris {info['tris']} vs target {target} (>{int(tolerance*100)} %)")
        if q["max_dev_pct_diag"] > allowed: fails.append(f"deviation {q['max_dev_pct_diag']} % of diagonal > {allowed} %")
        if q["silhouette_iou_min"] < min_iou: fails.append(f"silhouette IoU {q['silhouette_iou_min']} < {min_iou}")
        info["allowed_dev_pct"] = allowed; info["pass"] = not fails; info["issues"] = fails
        lods.append(info); prev = tmp
    group = None
    if lod_group:
        gname = f"LOD_{base}"; _remove(gname)
        group = bpy.data.objects.new(gname, None); group["fbx_type"] = "LodGroup"
        for c in ([col] if col else (list(src.users_collection) or [bpy.context.scene.collection])): c.objects.link(group)
        group.parent = src.parent; group.matrix_world = src.matrix_world.copy()
        for l in lods:
            o = bpy.data.objects[l["name"]]; o.parent = group; o.matrix_parent_inverse = Matrix.Identity(4); o.matrix_basis = Matrix.Identity(4)
    return {"source": src.name, "method": method, "chain": chain, "lod_group": group.name if group else None,
            "lods": lods, "pass": all(l.get("pass", True) for l in lods)}


# ------------------------------------------------------------------ collision
def _hull_verts_faces(pts):
    bm = bmesh.new()
    for p in pts: bm.verts.new(Vector(p))
    res = bmesh.ops.convex_hull(bm, input=bm.verts[:], use_existing_faces=False)
    drop = list({*res["geom_interior"], *res["geom_unused"]})
    drop = [g for g in drop if isinstance(g, bmesh.types.BMVert)]
    if drop: bmesh.ops.delete(bm, geom=drop, context='VERTS')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.verts.index_update()
    V = np.array([v.co[:] for v in bm.verts]); F = [[v.index for v in f.verts] for f in bm.faces]
    bm.free()
    return V, F


def _planes(V, F):
    c = V.mean(0); P = []
    for f in F:
        a, b, d = V[f[0]], V[f[1]], V[f[2]]
        n = np.cross(b - a, d - a); ln = np.linalg.norm(n)
        if ln < 1e-12: continue
        n /= ln
        if n @ (a - c) < 0: n = -n
        P.append((n, float(n @ a)))
    return P


def hull_metrics(V, F, pts):
    """convexity violation (hull verts in front of own planes) and enclosure (pts outside) in mm; all local coords."""
    P = _planes(V, F)
    N = np.array([p[0] for p in P]); D = np.array([p[1] for p in P])
    conv = float(np.max(V @ N.T - D)) if len(P) else 0.0
    outside = float(np.max(pts @ N.T - D)) if len(P) else 0.0
    return max(conv, 0.0), max(outside, 0.0)


def _reduce_hull(pts, max_tris):
    V, F = _hull_verts_faces(pts)
    cells = 24
    while len(F) > max_tris and cells >= 2:
        lo, hi = V.min(0), V.max(0); span = np.maximum(hi - lo, 1e-9); c = V.mean(0)
        key = np.floor((V - lo) / span * (cells - 1e-6)).astype(int)
        keep = {}
        for i, k in enumerate(map(tuple, key)):
            d = np.linalg.norm(V[i] - c)
            if k not in keep or d > keep[k][0]: keep[k] = (d, i)
        V, F = _hull_verts_faces(V[[i for _, i in keep.values()]])
        cells = int(cells * 0.75)
    P = _planes(V, F); c = V.mean(0)
    # smallest uniform scale about the centroid that puts every source point behind every face plane
    s = max([1.0] + [float(n @ (pts[int(np.argmax(pts @ n))] - c)) / (d - float(n @ c)) for n, d in P if d - float(n @ c) > 1e-12])
    return c + (V - c) * s, F, s


def _loose_parts(me):
    n = len(me.vertices); parent = np.arange(n)
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for e in me.edges:
        a, b = find(e.vertices[0]), find(e.vertices[1])
        if a != b: parent[a] = b
    roots = np.array([find(i) for i in range(n)])
    return [np.nonzero(roots == r)[0] for r in np.unique(roots)]


def _mesh_from(name, V, F):
    me = bpy.data.meshes.new(name); me.from_pydata([tuple(map(float, v)) for v in V], [], F); me.update()
    return me


def make_collision(object, kinds=("convex",), per_part=False, max_hull_tris=255, render_name=None, collection=None):
    src = bpy.data.objects[object] if isinstance(object, str) else object
    rn = render_name or src.name
    col = bpy.data.collections.get(collection) if isinstance(collection, str) else collection
    me = _eval_copy(src, "__coll_src__"); co, _ = _arrays(me)
    parts = _loose_parts(me) if per_part else [np.arange(len(me.vertices))]
    bpy.data.meshes.remove(me)
    out = []
    for kind in kinds:
        pre = f"{PREFIX[kind]}{rn}_"
        for o in [o for o in bpy.data.objects if o.name.startswith(pre)]: _remove(o.name)
        groups = parts if kind == "convex" else [np.arange(len(co))]
        for k, idx in enumerate(groups):
            pts = co[idx]; name = f"{pre}{k:02d}"; rec = {"name": name, "kind": kind}
            if kind == "convex":
                V, F, s = _reduce_hull(pts, max_hull_tris); rec["inflate_scale"] = round(s, 5)
            elif kind == "box":
                lo, hi = pts.min(0), pts.max(0)
                V = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
                F = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
            else:
                c = (pts.min(0) + pts.max(0)) / 2; r = float(np.linalg.norm(pts - c, axis=1).max())
                bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=r / math.cos(math.pi / 8))
                V = np.array([v.co[:] for v in bm.verts]) + c; bm.verts.index_update(); F = [[v.index for v in f.verts] for f in bm.faces]; bm.free()
            o = _new_obj(name, _mesh_from(name, V, F), src, col)
            o.display_type = 'WIRE'; o.hide_render = True
            conv, outside = hull_metrics(V, F, pts)
            tris = sum(len(f) - 2 for f in F)
            rec.update({"verts": len(V), "tris": tris, "convex": conv <= 1e-4, "convexity_violation_mm": round(conv * 1000, 3),
                        "encloses": outside <= 1e-4, "max_outside_mm": round(outside * 1000, 3)})
            rec["pass"] = rec["convex"] and rec["encloses"] and (kind != "convex" or tris <= max_hull_tris)
            out.append(rec)
    return {"source": src.name, "render_name": rn, "collision": out, "pass": all(r["pass"] for r in out)}


def check_collision(prefixes, render_object=None, tol_mm=0.1, max_hull_tris=255):
    """Validate existing collision objects (e.g. hand-made UCX_) against their render mesh (name after the prefix,
    minus the trailing _NN, or render_object). Checks convexity, enclosure of the render mesh, tri limit."""
    ps = prefixes.split(",") if isinstance(prefixes, str) else list(prefixes)
    out, sets = [], {}
    for o in [o for o in bpy.data.objects if o.type == 'MESH' and any(o.name.startswith(p) for p in ps)]:
        pre, rest = o.name.split("_", 1)
        rn = render_object or re.sub(r"_\d+$", "", rest)
        rec = {"name": o.name, "render_mesh": rn}
        me = _eval_copy(o, "__chk__"); V, _ = _arrays(me, o.matrix_world)
        F = [list(p.vertices) for p in me.polygons]; tris = sum(len(f) - 2 for f in F); bpy.data.meshes.remove(me)
        conv, _ = hull_metrics(V, F, V)
        rec.update({"tris": tris, "convexity_violation_mm": round(conv * 1000, 3), "convex": conv * 1000 <= tol_mm,
                    "tri_limit_ok": not o.name.startswith("UCX_") or tris <= max_hull_tris})
        out.append(rec); sets.setdefault((pre, rn), []).append((rec, V, F))
    set_recs = []
    for (pre, rn), items in sets.items():
        ren = bpy.data.objects.get(rn); srec = {"set": f"{pre}_{rn}", "render_mesh": rn, "pieces": len(items)}
        if ren is None:
            srec.update(issue="render mesh not found (collision name must match the exported render mesh name exactly)", encloses=False)
        else:
            rme = _eval_copy(ren, "__chk_r__"); pts, _ = _arrays(rme, ren.matrix_world); bpy.data.meshes.remove(rme)
            # a render vertex is covered if it is inside ANY piece of the set (compound collision = union of hulls)
            worst = np.full(len(pts), np.inf)
            for _, V, F in items:
                P = _planes(V, F)
                if not P: continue
                N = np.array([p[0] for p in P]); D = np.array([p[1] for p in P])
                worst = np.minimum(worst, np.max(pts @ N.T - D, axis=1))
            outside = float(max(0.0, worst.max())) if len(pts) else 0.0
            srec.update(max_outside_mm=round(outside * 1000, 3), encloses=outside * 1000 <= tol_mm,
                        uncovered_vertices=int((worst * 1000 > tol_mm).sum()))
        srec["pass"] = srec["encloses"] and all(r["convex"] and r["tri_limit_ok"] for r, _, _ in items)
        for r, _, _ in items: r["pass"] = r["convex"] and r["tri_limit_ok"] and srec["encloses"]
        set_recs.append(srec)
    return {"checked": out, "sets": set_recs, "pass": all(s["pass"] for s in set_recs) if set_recs else None}


def add_socket(object, socket, location=(0, 0, 0)):
    """Empty SOCKET_<socket> parented to object at a local offset (Unreal FBX socket convention)."""
    src = bpy.data.objects[object] if isinstance(object, str) else object
    name = f"SOCKET_{socket}"; _remove(name)
    e = bpy.data.objects.new(name, None); e.empty_display_type = 'ARROWS'; e.empty_display_size = 0.1
    for c in (list(src.users_collection) or [bpy.context.scene.collection]): c.objects.link(e)
    e.parent = src; e.matrix_parent_inverse = Matrix.Identity(4); e.location = location
    return {"socket": name, "parent": src.name}


def _targets(object, objects, source_collection, warnings):
    """Resolve the object names to process -> (names, batch). batch is True when --objects / --source-collection was
    used (results list shape); names may include missing objects, reported per object by _one."""
    names, batch = [], False
    if object is not None: names.append(object if isinstance(object, str) else object.name)
    if objects:
        batch = True
        names += [str(x).strip() for x in (objects.split(",") if isinstance(objects, str) else objects) if str(x).strip()]
    if source_collection:
        batch = True
        col = bpy.data.collections.get(source_collection) if isinstance(source_collection, str) else source_collection
        if col is None:
            warnings.append(f"source collection '{source_collection}' not found")
        else:
            skipped = []
            for o in sorted(col.all_objects, key=lambda o: o.name):
                if o.type != 'MESH': continue
                if LOD_RE.search(o.name) or any(o.name.startswith(p) for p in PREFIX.values()): skipped.append(o.name); continue
                names.append(o.name)
            if skipped: warnings.append(f"skipped generated LOD/collision objects in '{col.name}': {', '.join(skipped)}")
    seen, uniq = set(), []
    for n in names:
        if n not in seen: seen.add(n); uniq.append(n)
    return uniq, batch


def _one(name, ratios, method, symmetry, chain, triangulate, lod_group, collision, per_part, max_hull_tris, render_name,
         samples, max_dev_pct, min_iou, col):
    """LOD + collision pipeline for one object -> {object, lods?, collision?, error?, pass}; never raises."""
    rec = {"object": name}
    src = bpy.data.objects.get(name)
    if src is None: rec["error"] = "object not found"
    elif src.type != 'MESH': rec["error"] = f"not a mesh object ({src.type})"
    else:
        try:
            if ratios: rec["lods"] = generate_lods(src, ratios, method, symmetry, chain, triangulate, lod_group, col, samples, max_dev_pct, min_iou)
            if collision: rec["collision"] = make_collision(src, collision, per_part, max_hull_tris, render_name, col)
        except Exception as e:
            import traceback; traceback.print_exc()
            rec["error"] = f"{type(e).__name__}: {e}"
    rec["pass"] = "error" not in rec and all(v.get("pass") is not False for v in rec.values() if isinstance(v, dict))
    return rec


def run(object=None, ratios=None, method="COLLAPSE", symmetry=None, chain=False, triangulate=False, lod_group=False,
        collision=None, per_part=False, max_hull_tris=255, render_name=None, check=None, samples=3000, max_dev_pct=1.0,
        min_iou=0.95, collection=None, save=None, objects=None, source_collection=None, out_collection=None):
    """collection= is the deprecated name of out_collection= (the OUTPUT collection); objects= (list or 'A,B,C') and
    source_collection= select several objects -> 'results' list. See the module docstring for the shapes."""
    out = {"blender": bpy.app.version_string}; warnings = []
    if collection is not None:
        warnings.append("'collection' / --collection is deprecated in this script (it names the OUTPUT collection): use "
                        "--out-collection; for an input scope use --source-collection")
        if out_collection is None: out_collection = collection
    col = None
    if out_collection:
        col = bpy.data.collections.get(out_collection) if isinstance(out_collection, str) else out_collection
        if col is None:
            col = bpy.data.collections.new(out_collection); bpy.context.scene.collection.children.link(col)
            warnings.append(f"out collection '{out_collection}' did not exist: created and linked to the scene collection")
        out["out_collection"] = col.name
    names, batch = _targets(object, objects, source_collection, warnings)
    args = (ratios, method, symmetry, chain, triangulate, lod_group, collision, per_part, max_hull_tris)
    tail = (samples, max_dev_pct, min_iou, col)
    if batch:
        if render_name and len(names) > 1:
            warnings.append("--render-name ignored in batch mode (each object uses its own name)"); render_name = None
        if not names: warnings.append("no target objects resolved")
        out["objects"] = len(names)
        out["results"] = [_one(n, *args, render_name, *tail) for n in names]
    elif names:
        rec = _one(names[0], *args, render_name, *tail)
        for k in ("lods", "collision", "error"):
            if k in rec: out[k] = rec[k]
    if check:
        out["check_collision"] = check_collision(check, max_hull_tris=max_hull_tris)
    out["warnings"] = warnings
    out["pass"] = ("error" not in out and all(v.get("pass") is not False for v in out.values() if isinstance(v, dict))
                   and all(r["pass"] for r in out.get("results", [])) and not (batch and not names))
    if save: bpy.ops.wm.save_as_mainfile(filepath=save, copy=True)
    return out


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="lod_collision.py")
    p.add_argument("--object"); p.add_argument("--objects", help="comma-separated object names (batch mode)")
    p.add_argument("--source-collection", help="every mesh object in this collection (batch mode)")
    p.add_argument("--ratios", default=""); p.add_argument("--method", default="COLLAPSE")
    p.add_argument("--symmetry"); p.add_argument("--chain", action="store_true"); p.add_argument("--triangulate", action="store_true")
    p.add_argument("--lod-group", action="store_true"); p.add_argument("--collision", default="")
    p.add_argument("--per-part", action="store_true"); p.add_argument("--max-hull-tris", type=int, default=255)
    p.add_argument("--render-name"); p.add_argument("--check-collision"); p.add_argument("--samples", type=int, default=3000)
    p.add_argument("--max-dev-pct", type=float, default=1.0); p.add_argument("--min-iou", type=float, default=0.95)
    p.add_argument("--out-collection", help="collection receiving the LODs / collision objects (created if missing)")
    p.add_argument("--collection", help="deprecated alias of --out-collection"); p.add_argument("--save")
    a = p.parse_args(argv)
    ratios = [float(x) for x in a.ratios.split(",") if x] or None
    return run(a.object, ratios, a.method, a.symmetry, a.chain, a.triangulate, a.lod_group,
               [k for k in a.collision.split(",") if k] or None, a.per_part, a.max_hull_tris, a.render_name,
               a.check_collision, a.samples, a.max_dev_pct, a.min_iou, a.collection, a.save,
               objects=a.objects, source_collection=a.source_collection, out_collection=a.out_collection)


if "LOD_OPTS" in globals():
    result = run(**LOD_OPTS)
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("LOD_COLLISION " + json.dumps(result, default=str))
else:
    result = {"defined": ["run", "generate_lods", "make_collision", "check_collision", "add_socket", "measure", "hull_metrics", "_one", "_targets"]}
