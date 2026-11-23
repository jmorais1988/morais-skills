"""UV toolkit: unwrap with automatic seams, pack with pixel margins / UDIM tiles, set texel density, and a UV check report.

Headless / CLI (prints one line: UV_TOOLS <json>):
    BLENDER -b file.blend --python uv_tools.py -- unwrap --objects A,B [--method ANGLE_BASED|CONFORMAL|MINIMUM_STRETCH]
        [--seams SHARP|ANGLE|SHARP+ANGLE|KEEP|SMART] [--angle 30] [--clear-seams] [--no-disk-cuts] [--iterations 10]
        [--uv-map UVMap] [--new-map] [--no-average] [--save out.blend]
    BLENDER -b file.blend --python uv_tools.py -- pack --objects A,B --texture-px 2048 --margin-px 8 [--uv-map UVMap]
        [--no-rotate] [--rotate-method ANY|CARDINAL|AXIS_ALIGNED] [--shape CONCAVE|CONVEX|AABB] [--keep-scale]
        [--average] [--udim-by OBJECT|MATERIAL|AREA] [--fill 0.5] [--save out.blend]
    BLENDER -b file.blend --python uv_tools.py -- density --objects A,B --target 1024 --texture-px 2048 [--margin-px 8]
        [--uv-map UVMap] [--udim|--no-udim] [--fill 0.5] [--save out.blend]
    BLENDER -b file.blend --python uv_tools.py -- check --objects A,B --texture-px 2048 [--uv-map UVMap]
        [--target 1024 --tolerance 0.1] [--min-margin-px 8] [--udim] [--lightmap] [--group-by MATERIAL|ALL]
        [--max-angle-stretch 0.25 --max-area-stretch 0.5] [--raster-px 2048] [--base-mesh] [--save out.blend]
    BLENDER -b --factory-startup --python uv_tools.py -- [--help | -h]     no subcommand, -h or --help: prints the
        argparse help (all subcommands) and exits 0; `<subcommand> --help` lists that subcommand's options.
Live (Blender:execute_blender_code): set before exec
    UV_OPTS = {"op": "check", "objects": ["Crate_low"], "texture_px": 2048, "target": 1024}   -> `result` dict
    Without UV_OPTS the file only defines unwrap / pack / set_texel_density / check_uvs (and helpers).

Units: texel density is px/m = sqrt(UV area / world area) * texture_px (world area after object transforms).
Margins are GAPS between islands in pixels at texture_px; pack() converts them to Blender's FRACTION margin
(margin = gap_px / (2 * texture_px) -> island gap = gap_px, tile border = gap_px / 2; measured in 5.2).
unwrap(): seams from sharp edges and/or dihedral angle, then extra cuts so every chart is a topological disk (open tubes
get one seam between their boundary loops, closed charts a shortest cut, handles a tree-cotree cut graph); Blender's
unwrap of a non-disk chart fails or folds. Path cuts follow shortest edge length, not visibility: move them to hidden
sides by hand for hero assets (or mark seams yourself and use --seams KEEP).
check_uvs(): islands = faces connected through edges whose UVs coincide. Overlaps are rasterised per texture set
(material) and tile at raster_px: partial overlaps = error; whole-island mirrored (opposite winding) or stacked
(same winding) duplicates = warning (error with lightmap=True). Padding = exact 2-D distance between boundary edges of
different islands (plus tile-border distance). Stretch per triangle from the singular values of the 3-D->UV Jacobian,
normalised by the island's own scale: angle stretch = area-weighted mean(s1/s2 - 1), area stretch = mean |log2(s1*s2/k)|.
Limitations: raster overlap misses overlaps smaller than one raster pixel; three-way overlaps report only the first pair
per pixel; evaluated (modifier) meshes are checked by default, editing ops always act on the base mesh.
"""
import bpy, bmesh, sys, json, math, heapq
import numpy as np

METHODS = ('ANGLE_BASED', 'CONFORMAL', 'MINIMUM_STRETCH')


# ----------------------------------------------------------------------------------------------------------- helpers
def _objects(objects):
    if objects is None:
        objs = [o for o in bpy.context.selected_objects if o.type == 'MESH']
    else:
        names = [n.strip() for n in objects.split(',')] if isinstance(objects, str) else list(objects)
        objs = []
        for n in names:
            o = bpy.data.objects.get(n) if isinstance(n, str) else n
            if o is None or o.type != 'MESH':
                raise ValueError(f"mesh object {n!r} not found")
            objs.append(o)
    if not objs:
        raise ValueError("no mesh objects given/selected")
    return objs


def _object_mode():
    if bpy.context.object is not None and bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def _uv_layer(me, name=None, create=True, new_map=False):
    if new_map:
        lay = me.uv_layers.new(name=name or "UVMap.001", do_init=True)
    elif name:
        lay = me.uv_layers.get(name)
        if lay is None:
            if not create: raise ValueError(f"{me.name}: no UV map {name!r}")
            lay = me.uv_layers.new(name=name, do_init=True)
    else:
        lay = me.uv_layers.active or (me.uv_layers.new(name="UVMap", do_init=True) if create else None)
        if lay is None: raise ValueError(f"{me.name}: no UV map")
    me.uv_layers.active = lay
    return lay


class _Edit:
    """Enter multi-object edit mode on `objs` with the given face masks selected; restores selection on exit."""

    def __init__(self, objs, masks=None):
        self.objs, self.masks = objs, masks

    def __enter__(self):
        vl = bpy.context.view_layer
        _object_mode()
        self.sel = [o for o in vl.objects if o.select_get()]
        self.active = vl.objects.active
        ts = bpy.context.scene.tool_settings
        self.sync = ts.use_uv_select_sync
        ts.use_uv_select_sync = False
        for o in vl.objects:
            if o.select_get(): o.select_set(False)
        for o in self.objs:
            o.hide_set(False); o.select_set(True)
            me = o.data
            m = np.ones(len(me.polygons), bool) if not self.masks else self.masks.get(o.name, np.zeros(len(me.polygons), bool))
            lm = _loop_mask(me, m)  # face flags alone don't survive the edit-mode selection flush: set verts/edges too
            cv = np.empty(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", cv)
            ce = np.empty(len(me.loops), np.int64); me.loops.foreach_get("edge_index", ce)
            vm = np.zeros(len(me.vertices), bool); vm[cv[lm]] = True
            em = np.zeros(len(me.edges), bool); em[ce[lm]] = True
            me.vertices.foreach_set("select", vm); me.edges.foreach_set("select", em)
            me.polygons.foreach_set("select", m)
        vl.objects.active = self.objs[0]
        bpy.ops.object.mode_set(mode='EDIT')
        if self.masks:  # UV select_all/pack also reach UVs of unselected faces: hide them for the duration
            bpy.ops.mesh.hide(unselected=True)
        bpy.ops.uv.select_all(action='SELECT')
        return self

    def __exit__(self, *exc):
        if self.masks:
            bpy.ops.mesh.reveal(select=False)
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.scene.tool_settings.use_uv_select_sync = self.sync
        vl = bpy.context.view_layer
        for o in vl.objects:
            if o.select_get(): o.select_set(False)
        for o in self.sel:
            if o.name in vl.objects: o.select_set(True)
        vl.objects.active = self.active
        return False


def _unique_meshes(objs):
    seen, out = set(), []
    for o in objs:
        if o.data.name not in seen:
            seen.add(o.data.name); out.append(o)
    return out


def _arrays(obj, uv_name=None, evaluated=False):
    """Numpy view of a mesh: world coords, corners, faces, triangles, UVs, material names."""
    if evaluated:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg); me = ev.to_mesh()
    else:
        ev, me = None, obj.data
    try:
        lay = me.uv_layers.get(uv_name) if uv_name else me.uv_layers.active
        nv, nl, nf = len(me.vertices), len(me.loops), len(me.polygons)
        co = np.empty(nv * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        mw = np.array(obj.matrix_world); co = co @ mw[:3, :3].T + mw[:3, 3]
        cv = np.empty(nl, np.int64); me.loops.foreach_get("vertex_index", cv)
        ls = np.empty(nf, np.int64); me.polygons.foreach_get("loop_start", ls)
        lt = np.empty(nf, np.int64); me.polygons.foreach_get("loop_total", lt)
        mi = np.empty(nf, np.int64); me.polygons.foreach_get("material_index", mi)
        me.calc_loop_triangles()
        tl = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("loops", tl)
        tp = np.empty(len(me.loop_triangles), np.int64); me.loop_triangles.foreach_get("polygon_index", tp)
        uv = None
        if lay is not None:
            uv = np.empty(nl * 2); lay.uv.foreach_get("vector", uv); uv = uv.reshape(-1, 2)
        mats = [(s.material.name if s.material else "") for s in obj.material_slots] or [""]
        pid = np.repeat(np.arange(nf), lt)
        nxt = np.arange(nl) + 1
        if nf: nxt[ls + lt - 1] = ls
        return dict(co=co, cv=cv, ls=ls, lt=lt, mi=mi, tl=tl.reshape(-1, 3), tp=tp, uv=uv, pid=pid, nxt=nxt,
                    mats=mats, uv_name=lay.name if lay else None, nf=nf, nl=nl)
    finally:
        if ev is not None: ev.to_mesh_clear()


def _union_labels(n, a, b):
    lab = np.arange(n)
    if len(a) == 0: return lab
    for _ in range(200):
        la, lb = lab[a], lab[b]
        diff = la != lb
        if not diff.any(): break
        m = np.minimum(la[diff], lb[diff])
        np.minimum.at(lab, la[diff], m); np.minimum.at(lab, lb[diff], m)
        while True:
            nl_ = lab[lab]
            if np.array_equal(nl_, lab): break
            lab = nl_
    return lab


def _islands(d):
    """Face -> island label (0..k-1) by UV connectivity; boolean mask of boundary corners (UV edge used once)."""
    cv, nxt, uv, pid = d["cv"], d["nxt"], d["uv"], d["pid"]
    a, b = cv, cv[nxt]
    qa, qb = np.round(uv * 1e6).astype(np.int64), np.round(uv[nxt] * 1e6).astype(np.int64)
    sw = a > b
    v0, v1 = np.where(sw, b, a), np.where(sw, a, b)
    q0 = np.where(sw[:, None], qb, qa); q1 = np.where(sw[:, None], qa, qb)
    keys = np.column_stack([v0, v1, q0, q1])
    _, inv, cnt = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    order = np.argsort(inv, kind='stable')
    same = inv[order][1:] == inv[order][:-1]
    fa, fb = pid[order][:-1][same], pid[order][1:][same]
    lab = _union_labels(d["nf"], fa, fb)
    _, lab = np.unique(lab, return_inverse=True)
    return lab.ravel(), cnt[inv] == 1


def _tri_metrics(d, face_isl, n_isl):
    """Per-triangle 3-D area, signed UV area, singular values; per-island aggregates."""
    tl = d["tl"]; P = d["co"][d["cv"][tl]]; U = d["uv"][tl]
    e1, e2 = P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]
    n = np.cross(e1, e2); nn = np.linalg.norm(n, axis=1); A3 = nn / 2
    d1, d2 = U[:, 1] - U[:, 0], U[:, 2] - U[:, 0]
    Auv = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / 2
    ok = A3 > 1e-14
    l1 = np.linalg.norm(e1, axis=1)
    x = e1 / np.maximum(l1, 1e-30)[:, None]
    y = np.cross(n / np.maximum(nn, 1e-30)[:, None], x)
    q1x, q2x, q2y = l1, (e2 * x).sum(1), (e2 * y).sum(1)
    # J = D @ inv(Q), Q = [[q1x, q2x], [0, q2y]]
    inv_q2y = 1.0 / np.where(np.abs(q2y) > 1e-30, q2y, 1e-30); inv_q1x = 1.0 / np.where(q1x > 1e-30, q1x, 1e-30)
    J00 = d1[:, 0] * inv_q1x; J10 = d1[:, 1] * inv_q1x
    J01 = (d2[:, 0] - J00 * q2x) * inv_q2y; J11 = (d2[:, 1] - J10 * q2x) * inv_q2y
    E, F, G, H = (J00 + J11) / 2, (J00 - J11) / 2, (J10 + J01) / 2, (J10 - J01) / 2
    Q, R = np.hypot(E, H), np.hypot(F, G)
    s1, s2 = Q + R, np.abs(Q - R)
    ti = face_isl[d["tp"]]
    w3 = np.where(ok, A3, 0.0)
    isl_A3 = np.bincount(ti, w3, minlength=n_isl)
    isl_Auv = np.bincount(ti, np.abs(Auv) * ok, minlength=n_isl)
    isl_signed = np.bincount(ti, Auv * ok, minlength=n_isl)
    k = np.where(isl_A3 > 0, isl_Auv / np.maximum(isl_A3, 1e-30), 0.0)
    kt = k[ti]
    aniso = np.where((s2 > 1e-12) & ok, s1 / np.maximum(s2, 1e-12), np.where(ok & (s1 > 1e-12), 1e3, 1.0))
    aniso = np.minimum(aniso, 1e3)
    area_d = np.where(ok & (kt > 0) & (np.abs(Auv) > 0), np.abs(np.log2(np.maximum(np.abs(Auv) / np.maximum(A3, 1e-30), 1e-30) / np.maximum(kt, 1e-30))), 0.0)
    area_d = np.minimum(area_d, 20.0)
    isl_angle = np.bincount(ti, w3 * (aniso - 1), minlength=n_isl) / np.maximum(isl_A3, 1e-30)
    isl_area = np.bincount(ti, w3 * area_d, minlength=n_isl) / np.maximum(isl_A3, 1e-30)
    sgn = np.sign(isl_signed)
    flipped_tri = ok & (np.abs(Auv) > 1e-14) & (np.sign(Auv) != sgn[ti]) & (sgn[ti] != 0)
    isl_folds = np.bincount(ti, flipped_tri.astype(float), minlength=n_isl)
    return dict(A3=A3, Auv=Auv, ti=ti, U=U, isl_A3=isl_A3, isl_Auv=isl_Auv, isl_sign=sgn, isl_angle=isl_angle,
                isl_area=isl_area, isl_folds=isl_folds, tri_aniso=aniso, tri_area_d=area_d, ok=ok)


def _pct(v, w=None, q=0.5):
    v = np.asarray(v, float)
    if not len(v): return None
    if w is None: return float(np.quantile(v, q))
    o = np.argsort(v); cw = np.cumsum(np.asarray(w, float)[o])
    return float(v[o][min(np.searchsorted(cw, q * cw[-1]), len(v) - 1)])


# ------------------------------------------------------------------------------------------------------------- seams
def _is_cut(e):
    return e.seam or len(e.link_faces) != 2


def _charts(bm):
    label = [-1] * len(bm.faces); charts = []
    for f in bm.faces:
        if label[f.index] >= 0: continue
        cid = len(charts); label[f.index] = cid; stack, faces = [f], []
        while stack:
            g = stack.pop(); faces.append(g)
            for e in g.edges:
                if _is_cut(e): continue
                for h in e.link_faces:
                    if label[h.index] < 0:
                        label[h.index] = cid; stack.append(h)
        charts.append(faces)
    return charts, label


def _topology(faces, label, cid):
    """Euler characteristic, boundary loops (as vertex sets) and genus of a chart cut open along seams."""
    F = len(faces)
    edges = {e for f in faces for e in f.edges}
    E = sum((sum(1 for h in e.link_faces if label[h.index] == cid) if _is_cut(e) else 1) for e in edges)
    wedge, W = {}, 0
    for v in {v for f in faces for v in f.verts}:
        fs = [f.index for f in v.link_faces if label[f.index] == cid]
        par = {i: i for i in fs}

        def find(i):
            while par[i] != i:
                par[i] = par[par[i]]; i = par[i]
            return i
        for e in v.link_edges:
            if not _is_cut(e):
                a, b = e.link_faces[0].index, e.link_faces[1].index
                if a in par and b in par: par[find(a)] = find(b)
        roots = {}
        for i in fs:
            r = find(i)
            if r not in roots: roots[r] = W; W += 1
            wedge[(v.index, i)] = roots[r]
    # boundary loops: components of wedges joined by cut half-edges
    par = {}

    def find2(i):
        while par[i] != i:
            par[i] = par[par[i]]; i = par[i]
        return i
    wv = {}
    for e in edges:
        if not _is_cut(e): continue
        for h in e.link_faces:
            if label[h.index] != cid: continue
            a, b = wedge[(e.verts[0].index, h.index)], wedge[(e.verts[1].index, h.index)]
            for x, vv in ((a, e.verts[0]), (b, e.verts[1])):
                par.setdefault(x, x); wv[x] = vv
            ra, rb = find2(a), find2(b)
            if ra != rb: par[ra] = rb
    loops = {}
    for x in par:
        loops.setdefault(find2(x), set()).add(wv[x])
    chi = W - E + F
    b = len(loops)
    g = (2 - b - chi) // 2
    return chi, list(loops.values()), g


def _dijkstra(sources, chart_verts, label, cid, stop=None):
    dist = {v: 0.0 for v in sources}; prev = {}
    heap = [(0.0, v.index, v) for v in sources]; heapq.heapify(heap)
    while heap:
        dd, _, v = heapq.heappop(heap)
        if dd > dist.get(v, 1e30): continue
        if stop is not None and v in stop: return v, prev, dist
        for e in v.link_edges:
            if _is_cut(e) or label[e.link_faces[0].index] != cid: continue
            w = e.other_vert(v)
            nd = dd + e.calc_length()
            if nd < dist.get(w, 1e30):
                dist[w] = nd; prev[w] = e; heapq.heappush(heap, (nd, w.index, w))
    return None, prev, dist


def _mark_path(end, prev):
    n, v = 0, end
    while v in prev:
        e = prev[v]; e.seam = True; n += 1; v = e.other_vert(v)
    return n


def _cotree_cut(faces, label, cid):
    """Cut graph = chart edges not crossed by a dual spanning tree, pruned of dangling (non-boundary) branches."""
    fset = {f.index for f in faces}
    from collections import deque
    tree, seen, stack = set(), {faces[0].index}, deque([faces[0]])  # BFS dual tree -> shorter cut graph than DFS
    while stack:
        f = stack.popleft()
        for e in f.edges:
            if _is_cut(e): continue
            h = e.link_faces[0] if e.link_faces[1] == f else e.link_faces[1]
            if h.index in fset and h.index not in seen:
                seen.add(h.index); tree.add(e); stack.append(h)
    cand = {e for f in faces for e in f.edges if not _is_cut(e) and e not in tree}
    anchored = {v for f in faces for e in f.edges if _is_cut(e) for v in e.verts}
    deg = {}
    for e in cand:
        for v in e.verts: deg[v] = deg.get(v, 0) + 1
    changed = True
    while changed:
        changed = False
        for e in list(cand):
            if e not in cand: continue
            for v in e.verts:
                if v not in anchored and deg[v] == 1:
                    cand.discard(e)
                    for u in e.verts: deg[u] -= 1
                    changed = True
                    break
    for e in cand: e.seam = True
    return len(cand)


def _make_disks(bm, max_rounds=64):
    """Add seams until every chart is a topological disk. Returns (added_edges, remaining_non_disk_charts)."""
    added = 0
    for _ in range(max_rounds):
        bm.faces.index_update(); bm.verts.index_update()
        charts, label = _charts(bm)
        todo = 0
        for cid, faces in enumerate(charts):
            chi, loops, g = _topology(faces, label, cid)
            if chi == 1 and len(loops) == 1: continue
            todo += 1
            verts = {v for f in faces for v in f.verts}
            if g > 0:
                added += _cotree_cut(faces, label, cid)
            elif not loops:  # closed sphere-like chart: cut between two far vertices
                v0 = min(verts, key=lambda v: v.index)
                _, _, dist = _dijkstra([v0], verts, label, cid)
                u = max(dist, key=dist.get)
                _, prev, dist = _dijkstra([u], verts, label, cid)
                w = max(dist, key=dist.get)
                added += _mark_path(w, prev)
            else:  # several boundary loops: connect loop 0 to the nearest other loop
                src = loops[0]; others = set().union(*loops[1:]) - src
                end, prev, _ = _dijkstra(list(src), verts, label, cid, stop=others)
                if end is None:
                    added += _cotree_cut(faces, label, cid)
                else:
                    added += _mark_path(end, prev)
            break  # topology changed: recompute charts
        if todo == 0:
            return added, 0
    charts, label = _charts(bm)
    rest = sum(1 for cid, f in enumerate(charts) if (lambda t: not (t[0] == 1 and len(t[1]) == 1))(_topology(f, label, cid)))
    return added, rest


def mark_seams(obj, mode='SHARP+ANGLE', angle_deg=30.0, clear=False, make_disks=True):
    """Mark seams from sharp edges / dihedral angle on the base mesh, then cut charts into disks."""
    _object_mode()
    me = obj.data; bm = bmesh.new(); bm.from_mesh(me)
    thr = math.radians(angle_deg); marked = 0
    mode = mode.upper()
    for e in bm.edges:
        if clear: e.seam = False
        cut = ('SHARP' in mode and not e.smooth) or \
              ('ANGLE' in mode and len(e.link_faces) == 2 and e.calc_face_angle(0.0) > thr)
        if cut and not e.seam:
            e.seam = True; marked += 1
    added, rest = _make_disks(bm) if make_disks else (0, None)
    bm.to_mesh(me); bm.free(); me.update()
    return {"object": obj.name, "seams_marked": marked, "disk_cut_edges": added, "non_disk_charts_left": rest,
            "seam_edges_total": int(sum(e.use_seam for e in me.edges))}


def unwrap(objects=None, method='ANGLE_BASED', seams='SHARP+ANGLE', angle_deg=30.0, clear_seams=False, make_disks=True,
           uv_map=None, new_map=False, iterations=10, fill_holes=True, correct_aspect=True, average_scale=True):
    """Seams (SHARP / ANGLE / SHARP+ANGLE / KEEP / SMART) + bpy.ops.uv.unwrap on all faces of each object."""
    objs = _objects(objects); method = method.upper(); seams = seams.upper()
    if method not in METHODS: raise ValueError(f"method must be one of {METHODS}")
    _object_mode()
    rep = {"op": "unwrap", "method": method, "seams": seams, "objects": {}}
    for o in _unique_meshes(objs):
        lay = _uv_layer(o.data, uv_map, create=True, new_map=new_map)
        r = {"uv_map": lay.name}
        if seams not in ('KEEP', 'SMART'):
            r.update(mark_seams(o, seams, angle_deg, clear_seams, make_disks))
        elif seams == 'KEEP' and make_disks:
            r.update(mark_seams(o, 'NONE', angle_deg, False, True))
        rep["objects"][o.name] = r
    with _Edit(objs):
        if seams == 'SMART':
            bpy.ops.uv.smart_project(angle_limit=math.radians(angle_deg), island_margin=0.0, area_weight=0.0,
                                     correct_aspect=correct_aspect, scale_to_bounds=False)
        else:
            kw = dict(method=method, fill_holes=fill_holes, correct_aspect=correct_aspect, margin=0.0)
            if method == 'MINIMUM_STRETCH': kw["iterations"] = iterations
            bpy.ops.uv.unwrap(**kw)
        if average_scale:
            bpy.ops.uv.average_islands_scale()
    return rep


# -------------------------------------------------------------------------------------------------------------- pack
def _loop_mask(me, face_mask):
    lt = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", lt)
    return np.repeat(face_mask, lt)


def _shift_to_tile(obj, uv_name, face_mask, tile_index):
    me = obj.data; lay = me.uv_layers[uv_name]
    uv = np.empty(len(me.loops) * 2); lay.uv.foreach_get("vector", uv); uv = uv.reshape(-1, 2)
    lm = _loop_mask(me, face_mask)
    if not lm.any(): return
    base = np.floor(uv[lm].mean(0))
    uv[lm] += np.array([tile_index % 10, tile_index // 10]) - base
    lay.uv.foreach_set("vector", uv.ravel())


def pack(objects=None, texture_px=2048, margin_px=8, uv_map=None, rotate=True, rotate_method='ANY',
         shape_method='CONCAVE', scale=True, average_scale=False, merge_overlap=False, udim_by=None, fill=0.5):
    """Pack islands of all objects together (one atlas) or per group into UDIM tiles.
    udim_by: None | 'OBJECT' | 'MATERIAL' | 'AREA' (AREA = greedy by island UV area, requires scale=False)."""
    objs = _objects(objects); _object_mode()
    for o in objs: _uv_layer(o.data, uv_map, create=False)
    uv_name = {o.name: o.data.uv_layers.active.name for o in objs}
    margin = margin_px / (2.0 * texture_px)
    kw = dict(margin_method='ADD', margin=margin, rotate=rotate, rotate_method=rotate_method,
              shape_method=shape_method, scale=False, merge_overlap=merge_overlap, udim_source='CLOSEST_UDIM')
    rep = {"op": "pack", "texture_px": texture_px, "margin_px": margin_px, "uv_margin": round(margin, 6),
           "udim_by": udim_by, "groups": [], "warnings": []}

    def _visible_uvs(eobjs):
        out = []
        for o in eobjs:
            bm = bmesh.from_edit_mesh(o.data); lay = bm.loops.layers.uv.active
            out.append((o, bm, lay, [l for f in bm.faces if not f.hide for l in f.loops]))
        return out

    def _do_pack(eobjs):
        # FRACTION + scale=True is exact but ~15x slower (55 s vs 3 s on 9 islands, 5.2): scale with an inflated ADD
        # margin first, then re-pack at fixed scale where the ADD margin is an absolute UV distance; if that
        # overflows the tile, shrink uniformly and re-pack at fixed scale again.
        if scale:
            bpy.ops.uv.pack_islands(**dict(kw, scale=True, margin=margin * 1.25))
        bpy.ops.uv.pack_islands(**kw)
        if not scale: return
        for _ in range(4):
            vis = _visible_uvs(eobjs)
            pts = np.array([l[lay].uv[:] for _, _, lay, ls in vis for l in ls]) if vis else np.zeros((0, 2))
            if not len(pts): return
            base = np.floor(pts.min(0) + 1e-7)
            ext = float((pts.max(0) - base).max())
            if ext <= 1.0 - margin + 1e-6: return
            s = (1.0 - 2.0 * margin) / ext * 0.97
            for o, bm, lay, ls in vis:
                for l in ls:
                    u = l[lay].uv; l[lay].uv = (base[0] + (u[0] - base[0]) * s, base[1] + (u[1] - base[1]) * s)
                bmesh.update_edit_mesh(o.data)
            bpy.ops.uv.pack_islands(**kw)
        rep["warnings"].append("pack still overflows the tile after 4 shrink passes")

    if not udim_by:
        with _Edit(objs):
            if average_scale: bpy.ops.uv.average_islands_scale()
            _do_pack(objs)
        for o in objs: _shift_to_tile(o, uv_name[o.name], np.ones(len(o.data.polygons), bool), 0)
        rep["groups"].append({"tile": 1001, "objects": [o.name for o in objs]})
    else:
        udim_by = udim_by.upper(); groups = []
        if udim_by == 'OBJECT':
            groups = [{o.name: np.ones(len(o.data.polygons), bool)} for o in objs]
        elif udim_by == 'MATERIAL':
            names = []
            per = {}
            for o in objs:
                mi = np.empty(len(o.data.polygons), np.int64); o.data.polygons.foreach_get("material_index", mi)
                mats = [(s.material.name if s.material else "") for s in o.material_slots] or [""]
                for idx, mn in enumerate(mats):
                    m = mi == idx
                    if not m.any(): continue
                    if mn not in per: per[mn] = {}; names.append(mn)
                    per[mn][o.name] = per[mn].get(o.name, np.zeros(len(o.data.polygons), bool)) | m
            groups = [per[n] for n in names]
        elif udim_by == 'AREA':
            if scale: raise ValueError("udim_by='AREA' needs scale=False (keeps texel density; use set_texel_density first)")
            items = []
            for o in objs:
                d = _arrays(o, uv_name[o.name]); lab, _ = _islands(d)
                tm = _tri_metrics(d, lab, lab.max() + 1 if len(lab) else 0)
                li = lab[d["pid"]]
                for i in range(len(tm["isl_Auv"])):
                    u = d["uv"][li == i]; w, h = u.max(0) - u.min(0)
                    # padded bounding box, not UV area: square islands don't pack like their area suggests
                    items.append(((w + 2 * margin) * (h + 2 * margin), o, lab == i))
            items.sort(key=lambda t: -t[0])
            bins = []  # [area, {obj: mask}]
            for area, o, m in items:
                for bn in bins:
                    if bn[0] + area <= fill:
                        break
                else:
                    bn = [0.0, {}]; bins.append(bn)
                bn[0] += area
                bn[1][o.name] = bn[1].get(o.name, np.zeros(len(o.data.polygons), bool)) | m
            groups = [bn[1] for bn in bins]
            if any(a > fill for a, _, _ in items):
                rep["warnings"].append("an island alone exceeds the fill ratio: lower density or raise texture_px")
        else:
            raise ValueError("udim_by must be OBJECT, MATERIAL or AREA")
        if scale and len(groups) > 1:
            rep["warnings"].append("scale=True packs each tile at its own scale: texel density differs per tile")
        for ti, g in enumerate(groups):
            gobjs = [o for o in objs if o.name in g]
            with _Edit(gobjs, g):
                if average_scale: bpy.ops.uv.average_islands_scale()
                _do_pack(gobjs)
            for o in gobjs: _shift_to_tile(o, uv_name[o.name], g[o.name], ti)
            rep["groups"].append({"tile": 1001 + ti, "objects": {o.name: int(g[o.name].sum()) for o in gobjs}})
    # bounds after packing
    oob = []
    for o in objs:
        d = _arrays(o, uv_name[o.name]); lab, _ = _islands(d)
        for i in range(lab.max() + 1 if len(lab) else 0):
            lm = np.repeat(lab == i, d["lt"]); u = d["uv"][lm]
            if (np.floor(u.min(0) + 1e-7) != np.floor(u.max(0) - 1e-7)).any(): oob.append(f"{o.name}#{i}")
    rep["islands_crossing_tile_edges"] = oob
    rep["fits"] = not oob
    return rep


# ----------------------------------------------------------------------------------------------------------- density
def set_texel_density(objects=None, target=1024.0, texture_px=2048, uv_map=None, margin_px=8, pack_after=True,
                      udim='auto', fill=0.5, rotate=True):
    """Scale every island to `target` px/m at `texture_px`, then pack without rescaling (single tile or UDIMs)."""
    objs = _objects(objects); _object_mode()
    rep = {"op": "density", "target_px_per_m": target, "texture_px": texture_px, "objects": {}, "warnings": []}
    total = 0.0
    for o in _unique_meshes(objs):
        lay = _uv_layer(o.data, uv_map, create=False)
        d = _arrays(o, lay.name); lab, _ = _islands(d); n = lab.max() + 1 if len(lab) else 0
        tm = _tri_metrics(d, lab, n)
        uv = d["uv"].copy()
        loop_isl = lab[d["pid"]]
        before = []
        for i in range(n):
            if tm["isl_Auv"][i] <= 1e-14 or tm["isl_A3"][i] <= 1e-14: continue
            cur = math.sqrt(tm["isl_Auv"][i] / tm["isl_A3"][i]) * texture_px
            f = target / cur; before.append(cur)
            m = loop_isl == i
            c = (uv[m].min(0) + uv[m].max(0)) / 2
            uv[m] = c + (uv[m] - c) * f
        lay.uv.foreach_set("vector", uv.ravel())
        area = float(tm["isl_A3"].sum()) * (target / texture_px) ** 2
        total += area
        rep["objects"][o.name] = {"islands": int(n), "uv_area_after": round(area, 5),
                                  "density_before": {"min": round(min(before), 2), "max": round(max(before), 2)} if before else None}
    rep["uv_area_total"] = round(total, 5)
    tiles_needed = max(1, math.ceil(total / fill))
    rep["tiles_needed_at_fill"] = tiles_needed
    if tiles_needed > 1:
        need_px = texture_px * math.sqrt(total / fill)
        rep["single_tile_alternatives"] = {"texture_px": int(2 ** math.ceil(math.log2(need_px))),
                                           "density_px_per_m": round(target * math.sqrt(fill / total), 1)}
    if pack_after:
        use_udim = (tiles_needed > 1) if udim == 'auto' else bool(udim)
        if tiles_needed > 1 and not use_udim:
            rep["warnings"].append(f"islands need ~{tiles_needed} tiles at fill {fill}: packing into one tile will overflow")
        rep["pack"] = pack(objs, texture_px, margin_px, uv_map, rotate=rotate, scale=False,
                           udim_by='AREA' if use_udim else None, fill=fill)
    return rep


# ------------------------------------------------------------------------------------------------------------- check
def _raster(tris, tri_isl, R):
    """Rasterise tile-local UV triangles; returns ({(a,b): px}, {island: self-overlap px})."""
    owner = np.full((R, R), -1, np.int64); pairs, selfs = {}, {}
    P = tris * R
    lo = np.clip(np.floor(P.min(1)).astype(np.int64), 0, R); hi = np.clip(np.ceil(P.max(1)).astype(np.int64), 0, R)
    jx, jy = 0.5 + 1.37e-4, 0.5 + 2.71e-4
    for t in range(len(P)):
        x0, y0 = lo[t]; x1, y1 = hi[t]
        if x1 <= x0 or y1 <= y0: continue
        a, b, c = P[t]
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(area) < 1e-12: continue
        X, Y = np.meshgrid(np.arange(x0, x1) + jx, np.arange(y0, y1) + jy)
        s = 1.0 if area > 0 else -1.0
        w0 = ((b[0] - a[0]) * (Y - a[1]) - (b[1] - a[1]) * (X - a[0])) * s
        w1 = ((c[0] - b[0]) * (Y - b[1]) - (c[1] - b[1]) * (X - b[0])) * s
        w2 = ((a[0] - c[0]) * (Y - c[1]) - (a[1] - c[1]) * (X - c[0])) * s
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any(): continue
        sub = owner[y0:y1, x0:x1]; o = sub[inside]; isl = int(tri_isl[t])
        other = (o >= 0) & (o != isl)
        if other.any():
            ks, cs = np.unique(o[other], return_counts=True)
            for k, cnt in zip(ks.tolist(), cs.tolist()):
                key = (min(k, isl), max(k, isl)); pairs[key] = pairs.get(key, 0) + cnt
        same = int((o == isl).sum())
        if same: selfs[isl] = selfs.get(isl, 0) + same
        sub[inside] = np.where(o == -1, isl, o)
    return pairs, selfs


def _seg_dist(p0, p1, q0, q1):
    """Vectorised 2-D segment-segment distance."""
    def pt_seg(p, a, b):
        ab = b - a; t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-30), 0, 1)
        return np.linalg.norm(a + ab * t[:, None] - p, axis=1)

    def orient(a, b, c):
        return (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    d = np.minimum.reduce([pt_seg(p0, q0, q1), pt_seg(p1, q0, q1), pt_seg(q0, p0, p1), pt_seg(q1, p0, p1)])
    o1, o2, o3, o4 = orient(p0, p1, q0), orient(p0, p1, q1), orient(q0, q1, p0), orient(q0, q1, p1)
    cross = (o1 * o2 < 0) & (o3 * o4 < 0)
    return np.where(cross, 0.0, d)


def _close_pairs(A, B, isl, radius):
    """Pairs of segments (different islands) whose distance may be < radius, via a uniform grid."""
    lo = np.floor((np.minimum(A, B) - radius / 2) / radius).astype(np.int64)
    hi = np.floor((np.maximum(A, B) + radius / 2) / radius).astype(np.int64)
    nx, ny = hi[:, 0] - lo[:, 0] + 1, hi[:, 1] - lo[:, 1] + 1
    cnt = nx * ny
    if cnt.sum() > 2e7: raise MemoryError("too many grid cells for padding check; raise min_margin_px or lower texture_px")
    seg = np.repeat(np.arange(len(A)), cnt)
    start = np.repeat(np.cumsum(cnt) - cnt, cnt)
    k = np.arange(cnt.sum()) - start
    ix = lo[seg, 0] + k % nx[seg]; iy = lo[seg, 1] + k // nx[seg]
    key = ix * 2_000_003 + iy
    o = np.argsort(key, kind='stable'); key, seg = key[o], seg[o]
    ii, jj = [], []
    dlt = 1
    while dlt < len(key):
        m = key[dlt:] == key[:-dlt]
        if not m.any(): break
        ii.append(seg[:-dlt][m]); jj.append(seg[dlt:][m]); dlt += 1
    if not ii: return np.zeros(0, np.int64), np.zeros(0, np.int64)
    i, j = np.concatenate(ii), np.concatenate(jj)
    keep = isl[i] != isl[j]
    i, j = np.minimum(i[keep], j[keep]), np.maximum(i[keep], j[keep])
    if not len(i): return i, j
    u = np.unique(np.column_stack([i, j]), axis=0)
    return u[:, 0], u[:, 1]


def check_uvs(objects=None, texture_px=2048, uv_map=None, target=None, tolerance=0.10, min_margin_px=None, udim=False,
              lightmap=False, group_by='MATERIAL', max_angle_stretch=0.25, max_area_stretch=0.5, raster_px=None,
              evaluated=True, max_listed=20):
    """UV quality report: overlaps, stretch, padding, texel density, UDIM tiles, out-of-range islands."""
    objs = _objects(objects)
    _object_mode()
    min_margin_px = texture_px / 256.0 if min_margin_px is None else min_margin_px
    R = int(raster_px or min(texture_px, 2048))
    issues, per_obj, glob = [], {}, []  # glob: island records across objects

    def issue(kind, severity, obj=None, detail=None, islands=None):
        issues.append({"kind": kind, "severity": severity, "object": obj, "islands": islands, "detail": detail})

    segs = []  # (group, tile, p0, p1, gid)
    tris_by = {}  # (group, tile) -> list of (tris, gids)
    for o in objs:
        d = _arrays(o, uv_map, evaluated)
        if d["uv"] is None:
            issue("missing_uv", "error", o.name, f"no UV map {uv_map!r}" if uv_map else "no UV map"); continue
        if d["nf"] == 0: continue
        lab, bcorner = _islands(d); n = int(lab.max()) + 1
        tm = _tri_metrics(d, lab, n)
        base = len(glob)
        loop_isl = lab[d["pid"]]
        # per-island bounds, tiles, material group
        umin = np.full((n, 2), np.inf); umax = np.full((n, 2), -np.inf)
        np.minimum.at(umin, loop_isl, d["uv"]); np.maximum.at(umax, loop_isl, d["uv"])
        face_mat = np.array([d["mats"][min(m, len(d["mats"]) - 1)] for m in d["mi"]], dtype=object)
        dens = np.where(tm["isl_A3"] > 1e-14, np.sqrt(tm["isl_Auv"] / np.maximum(tm["isl_A3"], 1e-30)) * texture_px, np.nan)
        first_face = np.full(n, -1); first_face[lab[::-1]] = np.arange(d["nf"])[::-1]
        for i in range(n):
            tmin, tmax = np.floor(umin[i] + 1e-7), np.floor(umax[i] - 1e-7)
            tile = (int(tmin[0]), int(tmin[1]))
            grp = face_mat[first_face[i]] if group_by.upper() == 'MATERIAL' else "ALL"
            glob.append(dict(obj=o.name, idx=i, tile=tile, crosses=bool((tmin != tmax).any()), group=grp,
                             A3=float(tm["isl_A3"][i]), Auv=float(tm["isl_Auv"][i]), sign=float(tm["isl_sign"][i]),
                             dens=float(dens[i]), angle=float(tm["isl_angle"][i]), area=float(tm["isl_area"][i]),
                             folds=int(tm["isl_folds"][i]), umin=umin[i], umax=umax[i]))
        gids = base + lab[d["tp"]]
        ttile = np.array([glob[g]["tile"] for g in range(base, base + n)])[lab[d["tp"]]] if n else np.zeros((0, 2))
        U = tm["U"]
        for key in {(glob[g]["group"], glob[g]["tile"]) for g in range(base, base + n)}:
            m = (ttile[:, 0] == key[1][0]) & (ttile[:, 1] == key[1][1]) & \
                (np.array([glob[g]["group"] for g in gids]) == key[0]) & tm["ok"]
            tris_by.setdefault(key, []).append((U[m] - np.array(key[1], float), gids[m]))
        bc = np.nonzero(bcorner)[0]
        segs.append((np.array([glob[base + lab[d["pid"][c]]]["group"] for c in bc], dtype=object),
                     d["uv"][bc], d["uv"][d["nxt"][bc]], base + lab[d["pid"][bc]]))
        # object-level stats
        ok_d = ~np.isnan(dens)
        obj_d = math.sqrt(tm["isl_Auv"].sum() / tm["isl_A3"].sum()) * texture_px if tm["isl_A3"].sum() > 0 else None
        per_obj[o.name] = {
            "uv_map": d["uv_name"], "islands": n, "faces": d["nf"],
            "density_px_per_m": {"object": round(obj_d, 2) if obj_d else None,
                                 "island_min": round(float(np.nanmin(dens)), 2) if ok_d.any() else None,
                                 "island_median": round(_pct(dens[ok_d], tm["isl_A3"][ok_d]), 2) if ok_d.any() else None,
                                 "island_max": round(float(np.nanmax(dens)), 2) if ok_d.any() else None},
            "stretch": {"angle_mean": round(float((tm["tri_aniso"] - 1)[tm["ok"]] @ tm["A3"][tm["ok"]] / max(tm["A3"][tm["ok"]].sum(), 1e-30)), 4),
                        "angle_p95": round(_pct((tm["tri_aniso"] - 1)[tm["ok"]], tm["A3"][tm["ok"]], 0.95) or 0, 4),
                        "area_mean": round(float(tm["tri_area_d"][tm["ok"]] @ tm["A3"][tm["ok"]] / max(tm["A3"][tm["ok"]].sum(), 1e-30)), 4),
                        "area_p95": round(_pct(tm["tri_area_d"][tm["ok"]], tm["A3"][tm["ok"]], 0.95) or 0, 4)},
            "uv_fill_0_1": round(float(sum(g["Auv"] for g in glob[base:] if g["tile"] == (0, 0))), 4),
        }
    name = lambda g: f"{glob[g]['obj']}#{glob[g]['idx']}"
    # per-island gates
    zero = [g for g in range(len(glob)) if glob[g]["Auv"] < 1e-12]
    if zero: issue("zero_area_island", "error", detail=f"{len(zero)} island(s) with no UV area", islands=[name(g) for g in zero][:max_listed])
    live = [g for g in range(len(glob)) if glob[g]["Auv"] >= 1e-12]
    cross = [g for g in live if glob[g]["crosses"]]
    if cross: issue("crosses_tile_edge", "error", detail="island spans a 0-1 / UDIM tile border", islands=[name(g) for g in cross][:max_listed])
    if udim:
        neg = [g for g in live if glob[g]["tile"][0] < 0 or glob[g]["tile"][1] < 0 or glob[g]["tile"][0] > 9]
        if neg: issue("invalid_udim_tile", "error", detail="u tile must be 0..9 and v >= 0", islands=[name(g) for g in neg][:max_listed])
    else:
        oob = [g for g in live if glob[g]["tile"] != (0, 0)]
        if oob: issue("out_of_0_1", "error", detail="island outside the 0-1 square (pass udim=True for UDIM layouts)", islands=[name(g) for g in oob][:max_listed])
    st = [g for g in live if glob[g]["angle"] > max_angle_stretch]
    if st: issue("angle_stretch", "error", detail=f"area-weighted mean(s1/s2-1) > {max_angle_stretch}: " + ", ".join(f"{name(g)}={glob[g]['angle']:.2f}" for g in st[:max_listed]), islands=[name(g) for g in st][:max_listed])
    sa = [g for g in live if glob[g]["area"] > max_area_stretch]
    if sa: issue("area_stretch", "warning", detail=f"area-weighted mean |log2 area ratio| > {max_area_stretch}: " + ", ".join(f"{name(g)}={glob[g]['area']:.2f}" for g in sa[:max_listed]), islands=[name(g) for g in sa][:max_listed])
    fo = [g for g in live if glob[g]["folds"] > 0]
    if fo: issue("flipped_triangles", "error", detail="triangles with opposite UV winding inside an island (fold)", islands=[f"{name(g)}:{glob[g]['folds']}" for g in fo][:max_listed])
    dens_all = np.array([glob[g]["dens"] for g in live]); w_all = np.array([glob[g]["A3"] for g in live])
    if target:
        bad = [g for g in live if abs(glob[g]["dens"] / target - 1) > tolerance]
        if bad: issue("density_out_of_tolerance", "error", detail=f"target {target} px/m +-{tolerance * 100:.0f}%: " + ", ".join(f"{name(g)}={glob[g]['dens']:.0f}" for g in bad[:max_listed]), islands=[name(g) for g in bad][:max_listed])
    elif len(dens_all) and np.nanmax(dens_all) / max(np.nanmin(dens_all), 1e-9) > (1 + tolerance) / (1 - tolerance):
        issue("density_spread", "warning", detail=f"island density ranges {np.nanmin(dens_all):.0f}-{np.nanmax(dens_all):.0f} px/m (no target given)")
    # overlaps
    overlaps = {"partial": [], "mirrored": [], "stacked": [], "self": []}
    cell_px = (1.0 / R) ** 2
    for key, parts in tris_by.items():
        T = np.concatenate([p[0] for p in parts]) if parts else np.zeros((0, 3, 2))
        G = np.concatenate([p[1] for p in parts]) if parts else np.zeros(0, np.int64)
        if not len(T): continue
        pairs, selfs = _raster(T, G, R)
        for (a, b), px in pairs.items():
            pa, pb = glob[a]["Auv"] / cell_px, glob[b]["Auv"] / cell_px
            if px < max(2, 0.002 * min(pa, pb)): continue
            frac = px / max(min(pa, pb), 1)
            similar = min(pa, pb) / max(pa, pb, 1) > 0.9
            kind = ("mirrored" if glob[a]["sign"] != glob[b]["sign"] else "stacked") if (frac > 0.9 and similar) else "partial"
            overlaps[kind].append({"islands": [name(a), name(b)], "overlap_px": int(px), "fraction_of_smaller": round(frac, 3),
                                   "group": key[0], "tile": 1001 + key[1][0] + 10 * key[1][1]})
        for g, px in selfs.items():
            if px >= max(2, 0.002 * glob[g]["Auv"] / cell_px):
                overlaps["self"].append({"island": name(g), "overlap_px": int(px)})
    if overlaps["partial"]: issue("overlap", "error", detail=f"{len(overlaps['partial'])} partially overlapping island pair(s)", islands=[p["islands"] for p in overlaps["partial"]][:max_listed])
    if overlaps["self"]: issue("self_overlap", "error", detail="island overlaps itself (fold)", islands=[p["island"] for p in overlaps["self"]][:max_listed])
    for kind in ("mirrored", "stacked"):
        if overlaps[kind]:
            issue(f"{kind}_overlap", "error" if lightmap else "warning",
                  detail=f"{len(overlaps[kind])} {kind} island pair(s): fine for shared colour/normal texels, wrong for AO/lightmaps/unique bakes",
                  islands=[p["islands"] for p in overlaps[kind]][:max_listed])
    # padding
    padding = {"min_margin_px": min_margin_px, "min_gap_px": None, "violations": 0, "min_border_px": None}
    if segs:
        GR = np.concatenate([s[0] for s in segs]); A = np.concatenate([s[1] for s in segs])
        B = np.concatenate([s[2] for s in segs]); I = np.concatenate([s[3] for s in segs])
        gcode = {g: k for k, g in enumerate(sorted(set(GR.tolist())))}
        tl = np.array([glob[i]["tile"] for i in I]).reshape(-1, 2) if len(I) else np.zeros((0, 2))
        key_isl = I.astype(np.int64)
        # segments only interact within the same group and tile: offset them far apart
        gc = np.array([gcode[g] for g in GR], np.float64)
        off = np.column_stack([tl[:, 0] * 10.0 + gc * 1000.0, tl[:, 1] * 10.0])
        radius = 1.5 * min_margin_px / texture_px
        if len(A):
            i, j = _close_pairs(A + off, B + off, key_isl, radius)
            if len(i):
                dist = _seg_dist(A[i], B[i], A[j], B[j]) * texture_px
                pair_min = {}
                for a_, b_, dd in zip(I[i].tolist(), I[j].tolist(), dist.tolist()):
                    k = (min(a_, b_), max(a_, b_))
                    if dd < pair_min.get(k, 1e30): pair_min[k] = dd
                padding["min_gap_px"] = round(min(pair_min.values()), 3)
                bad = sorted(((v, k) for k, v in pair_min.items() if v < min_margin_px - 0.05))
                padding["violations"] = len(bad)
                if bad:
                    issue("padding", "error", detail=f"{len(bad)} island pair(s) closer than {min_margin_px} px; closest {bad[0][0]:.2f} px",
                          islands=[[name(k[0]), name(k[1]), round(v, 2)] for v, k in bad[:max_listed]])
        border = []
        for g in live:
            t = np.array(glob[g]["tile"], float)
            bpx = float(min((glob[g]["umin"] - t).min(), (t + 1 - glob[g]["umax"]).min()) * texture_px)
            border.append((bpx, g))
        if border:
            padding["min_border_px"] = round(min(border)[0], 3)
            nb = [(b_, g) for b_, g in border if b_ < min_margin_px / 2 - 0.05]
            if nb: issue("near_tile_border", "warning", detail=f"{len(nb)} island(s) closer than {min_margin_px / 2} px to the tile edge (bleeds across tiling/UDIM filtering)", islands=[f"{name(g)}={b_:.2f}px" for b_, g in sorted(nb)[:max_listed]])
    # tiles
    tiles = {}
    for g in live:
        t = glob[g]["tile"]; num = 1001 + t[0] + 10 * t[1]
        e = tiles.setdefault(num, {"islands": 0, "uv_fill": 0.0}); e["islands"] += 1; e["uv_fill"] += glob[g]["Auv"]
    for e in tiles.values(): e["uv_fill"] = round(e["uv_fill"], 4)
    errors = [x for x in issues if x["severity"] == "error"]
    rep = {"op": "check", "pass": not errors, "texture_px": texture_px, "target_px_per_m": target, "tolerance": tolerance,
           "raster_px": R, "lightmap": lightmap, "udim": udim, "group_by": group_by, "objects": per_obj,
           "islands_total": len(glob), "tiles": tiles, "overlaps": {k: v[:max_listed] for k, v in overlaps.items()},
           "overlap_counts": {k: len(v) for k, v in overlaps.items()}, "padding": padding,
           "density_px_per_m": {"min": round(float(np.nanmin(dens_all)), 2) if len(dens_all) else None,
                                "median": round(_pct(dens_all, w_all), 2) if len(dens_all) else None,
                                "max": round(float(np.nanmax(dens_all)), 2) if len(dens_all) else None},
           "issues": issues, "blender": bpy.app.version_string}
    rep["summary"] = (f"{'PASS' if rep['pass'] else 'FAIL'}: {len(glob)} islands on {len(per_obj)} object(s); "
                      f"errors {sorted({x['kind'] for x in errors})}; warnings {sorted({x['kind'] for x in issues if x['severity'] == 'warning'})}")
    return rep


# ---------------------------------------------------------------------------------------------------------- run / CLI
def _run(o):
    o = dict(o); op = o.pop("op"); save = o.pop("save", None)
    if op == "unwrap": res = unwrap(**o)
    elif op == "pack": res = pack(**o)
    elif op == "density": res = set_texel_density(**o)
    elif op == "check": res = check_uvs(**o)
    else: raise ValueError("op must be unwrap, pack, density or check")
    if save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(save)); res["saved"] = save
    return res


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="uv_tools.py", description="UV toolkit (unwrap / pack / density / check); "
                                "`<subcommand> --help` lists that subcommand's options. Prints one line: UV_TOOLS <json>.")
    sub = p.add_subparsers(dest="op", required=True, metavar="{unwrap,pack,density,check}")
    u = sub.add_parser("unwrap", help="seams from sharp edges / angle (+ disk cuts), then unwrap")
    pk = sub.add_parser("pack", help="pack islands with a pixel gap into one tile or UDIM tiles")
    de = sub.add_parser("density", help="scale islands to a texel density (px/m) and pack")
    ch = sub.add_parser("check", help="UV report: overlaps, padding, stretch, density, tiles")
    for s in (u, pk, de, ch):
        s.add_argument("--objects"); s.add_argument("--uv-map"); s.add_argument("--save")
    u.add_argument("--method", default="ANGLE_BASED"); u.add_argument("--seams", default="SHARP+ANGLE")
    u.add_argument("--angle", type=float, default=30.0); u.add_argument("--clear-seams", action="store_true")
    u.add_argument("--no-disk-cuts", action="store_true"); u.add_argument("--iterations", type=int, default=10)
    u.add_argument("--new-map", action="store_true"); u.add_argument("--no-average", action="store_true")
    for s in (pk, de, ch):
        s.add_argument("--texture-px", type=int, default=2048)
    pk.add_argument("--margin-px", type=float, default=8); pk.add_argument("--no-rotate", action="store_true")
    pk.add_argument("--rotate-method", default="ANY"); pk.add_argument("--shape", default="CONCAVE")
    pk.add_argument("--keep-scale", action="store_true"); pk.add_argument("--average", action="store_true")
    pk.add_argument("--udim-by"); pk.add_argument("--fill", type=float, default=0.5)
    de.add_argument("--target", type=float, required=True); de.add_argument("--margin-px", type=float, default=8)
    de.add_argument("--udim", dest="udim", action="store_const", const=True, default="auto")
    de.add_argument("--no-udim", dest="udim", action="store_const", const=False); de.add_argument("--fill", type=float, default=0.5)
    ch.add_argument("--target", type=float); ch.add_argument("--tolerance", type=float, default=0.10)
    ch.add_argument("--min-margin-px", type=float); ch.add_argument("--udim", action="store_true")
    ch.add_argument("--lightmap", action="store_true"); ch.add_argument("--group-by", default="MATERIAL")
    ch.add_argument("--max-angle-stretch", type=float, default=0.25); ch.add_argument("--max-area-stretch", type=float, default=0.5)
    ch.add_argument("--raster-px", type=int); ch.add_argument("--base-mesh", action="store_true")
    a = p.parse_args(argv)
    o = {"op": a.op, "objects": a.objects, "uv_map": a.uv_map, "save": a.save}
    if a.op == "unwrap":
        o.update(method=a.method, seams=a.seams, angle_deg=a.angle, clear_seams=a.clear_seams, make_disks=not a.no_disk_cuts,
                 iterations=a.iterations, new_map=a.new_map, average_scale=not a.no_average)
    elif a.op == "pack":
        o.update(texture_px=a.texture_px, margin_px=a.margin_px, rotate=not a.no_rotate, rotate_method=a.rotate_method,
                 shape_method=a.shape, scale=not a.keep_scale, average_scale=a.average, udim_by=a.udim_by, fill=a.fill)
    elif a.op == "density":
        o.update(target=a.target, texture_px=a.texture_px, margin_px=a.margin_px, udim=a.udim, fill=a.fill)
    else:
        o.update(texture_px=a.texture_px, target=a.target, tolerance=a.tolerance, min_margin_px=a.min_margin_px, udim=a.udim,
                 lightmap=a.lightmap, group_by=a.group_by, max_angle_stretch=a.max_angle_stretch,
                 max_area_stretch=a.max_area_stretch, raster_px=a.raster_px, evaluated=not a.base_mesh)
    return _run(o)


_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if globals().get("UV_OPTS"):
    result = _run(UV_OPTS)
    print("UV_TOOLS " + json.dumps(result, default=str))
elif _argv and _argv[0] in ("unwrap", "pack", "density", "check"):
    result = _cli(_argv)
    print("UV_TOOLS " + json.dumps(result, default=str))
elif "--" in sys.argv and (not _argv or _argv[0] in ("-h", "--help")):
    # CLI with no subcommand / -h / --help: print the argparse help (lists every subcommand) and let Blender exit 0
    try: _cli(["--help"])
    except SystemExit: pass
    result = {"help": True, "subcommands": ["unwrap", "pack", "density", "check"]}
else:
    result = {"defined": ["unwrap", "mark_seams", "pack", "set_texel_density", "check_uvs"]}
