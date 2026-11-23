"""Archviz scene gates: light leaks, wall/slab closure, z-fighting coplanar faces, furniture contact, dimension ranges,
glass, camera (verticals, height, clipping, inside-geometry), render/color-management sanity, UV world scale.

Headless / CLI (prints one line: ARCHVIZ_GATES <json>):
    blender -b scene.blend --python archviz_gates.py -- [--checks leaks,closure,zfight,contact,dims,glass,camera,render,uv]
        [--walls WALL_] [--rooms FLR_] [--portals CUT_] [--furniture FURN_] [--expect dims.json]
        [--rays 256] [--tol-mm 2] [--min-overlap-cm2 1]
Live (Blender:execute_blender_code): set before exec
    GATES_OPTS = {"checks": ["leaks", "zfight", ...], "furniture": "FURN_", ...}   -> `result` dict
Without GATES_OPTS the file only defines run_gates and the individual check functions.

Evidence is the evaluated (modifier-applied) render-visible scene in world space. Name prefixes select roles; pass
several comma-separated prefixes. Every check returns {"pass": bool|None, ...}; None = not applicable/informational.
A pass means that defect class wasn't detected by this sampling, not that the shot is good -- still render and look.
Limitations: leak rays sample directions from interior points, so gaps narrower than the ray spacing at that distance can
be missed (closure catches wall-top/bottom gaps deterministically); z-fighting compares triangles (same-facing coplanar
within 0.5 mm); dimension ranges are generic furniture norms keyed on object-name keywords.
"""
import bpy, bmesh, json, math, sys
from mathutils import Vector
import numpy as np

# keyword -> (dimension, min m, max m, note). Generic residential norms (EU/US overlap); override with --expect.
DIM_RANGES = [
    ("dining_table", "height", 0.72, 0.78, "table top"), ("coffee_table", "height", 0.30, 0.50, "coffee/low table"),
    ("side_table", "height", 0.45, 0.70, "side table"), ("desk", "height", 0.70, 0.78, "desk top"),
    ("table", "height", 0.30, 0.78, "table (generic)"), ("counter", "height", 0.85, 0.95, "kitchen counter top"),
    ("bar_stool", "height", 0.60, 0.85, "bar stool seat"), ("chair", "height", 0.75, 1.10, "chair overall"),
    ("sofa", "height", 0.65, 1.00, "sofa overall"), ("armchair", "height", 0.70, 1.10, "armchair overall"),
    ("bed", "height", 0.40, 1.30, "bed incl. headboard"), ("wardrobe", "height", 1.80, 2.60, "wardrobe"),
    ("door", "height", 1.95, 2.40, "door leaf"), ("floor_lamp", "height", 1.30, 2.00, "floor lamp"),
    ("rug", "height", 0.003, 0.04, "rug pile"), ("toilet", "height", 0.38, 0.85, "toilet incl. cistern"),
    ("bathtub", "height", 0.50, 0.65, "bathtub rim"), ("sink", "height", 0.80, 0.95, "washbasin rim"),
]


def _objs(prefixes, types=('MESH',)):
    ps = [p for p in (prefixes.split(",") if isinstance(prefixes, str) else prefixes or []) if p]
    return [o for o in bpy.context.scene.objects if o.type in types and any(o.name.startswith(p) for p in ps)
            and not o.hide_render and o.visible_get()]


def _dg():
    dg = bpy.context.evaluated_depsgraph_get(); dg.update(); return dg


def _world_tris(o, dg):
    ev = o.evaluated_get(dg); me = ev.to_mesh(); me.calc_loop_triangles()
    co = np.empty(len(me.vertices) * 3, np.float64); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    tri = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("vertices", tri); tri = tri.reshape(-1, 3)
    mw = np.array(o.matrix_world); co = co @ mw[:3, :3].T + mw[:3, 3]
    ev.to_mesh_clear()
    return co, tri


def _cast_all(dg, origin, d, dist=1e4, max_hits=16):
    sc, hits, o = bpy.context.scene, [], Vector(origin)
    for _ in range(max_hits):
        h, loc, nrm, _, ob, _ = sc.ray_cast(dg, o, d, distance=dist)
        if not h: break
        hits.append((loc.copy(), nrm.copy(), ob.original)); dist -= (loc - o).length; o = loc + d * 1e-4
    return hits


def _fib(n):
    g = math.pi * (3 - math.sqrt(5))
    return [Vector((math.cos(g * i) * math.sqrt(1 - (1 - 2 * (i + .5) / n) ** 2), math.sin(g * i) * math.sqrt(1 - (1 - 2 * (i + .5) / n) ** 2),
                    1 - 2 * (i + .5) / n)) for i in range(n)]


def _is_glass(o):
    for s in getattr(o, "material_slots", []):
        m = s.material
        if m and m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == 'BSDF_PRINCIPLED' and n.inputs.get("Transmission Weight") and n.inputs["Transmission Weight"].default_value >= 0.5:
                    return True
                if n.type in ('BSDF_GLASS', 'BSDF_REFRACTION'):
                    return True
    return False


def _thin_wall(o):
    for s in getattr(o, "material_slots", []):
        m = s.material
        if m and m.node_tree:
            for n in m.node_tree.nodes:
                sock = n.inputs.get("Thin Wall") if n.type == 'BSDF_PRINCIPLED' else None
                if sock is not None and not sock.is_linked and bool(sock.default_value):
                    return True
    return False


def _aabb_hit(o, origin, d):
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
    hi = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
    t0, t1 = 0.0, 1e9
    for i in range(3):
        if abs(d[i]) < 1e-12:
            if origin[i] < lo[i] or origin[i] > hi[i]: return False
        else:
            a, b = (lo[i] - origin[i]) / d[i], (hi[i] - origin[i]) / d[i]
            t0, t1 = max(t0, min(a, b)), min(t1, max(a, b))
    return t1 >= t0


# ---------------------------------------------------------------- checks
def check_leaks(rooms="FLR_", portals="CUT_", rays=256, step=0.6):
    """Rays from interior sample points; escaping rays that pass no portal (opening cutter AABB) or glass = leaks."""
    dg = _dg(); floors = _objs(rooms)
    if not floors: return {"pass": None, "note": f"no room floor objects with prefix {rooms}"}
    portal_objs = [o for o in bpy.context.scene.objects if any(o.name.startswith(p) for p in portals.split(",") if p)]
    dirs = _fib(rays); leaks, samples, escapes_ok = [], 0, 0
    for f in floors:
        bb = [f.matrix_world @ Vector(c) for c in f.bound_box]
        x0, x1 = min(v.x for v in bb), max(v.x for v in bb); y0, y1 = min(v.y for v in bb), max(v.y for v in bb); ztop = max(v.z for v in bb)
        nx, ny = max(2, int((x1 - x0) / step)), max(2, int((y1 - y0) / step))
        for i in range(nx):
            for j in range(ny):
                p = Vector((x0 + (i + .5) * (x1 - x0) / nx, y0 + (j + .5) * (y1 - y0) / ny, ztop + 0.05))
                down = _cast_all(dg, p, Vector((0, 0, -1)), 1.0, 2)
                if not down or down[0][2] != f: continue
                up = _cast_all(dg, p, Vector((0, 0, 1)), 20.0, 1)
                if not up: continue  # no ceiling above -> not an enclosed interior point
                ceiling = up[0][0].z
                for z in (p.z, (p.z + ceiling) / 2, ceiling - 0.05):
                    q = Vector((p.x, p.y, z)); samples += 1
                    for d in dirs:
                        h = bpy.context.scene.ray_cast(dg, q, d, distance=1e4)
                        if h[0]:
                            if h[4].original in portal_objs: escapes_ok += 1
                            continue
                        if any(_aabb_hit(po, q, d) for po in portal_objs):
                            escapes_ok += 1; continue
                        leaks.append((q, d))
    clusters = {}
    for q, d in leaks:
        key = (round(d.x, 1), round(d.y, 1), round(d.z, 1)); clusters.setdefault(key, []).append(q)
    top = sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:8]
    return {"pass": not leaks, "leak_rays": len(leaks), "sample_points": samples, "rays_per_point": rays,
            "escapes_through_portals": escapes_ok,
            "leak_directions": [{"dir": k, "rays": len(v), "example_origin": [round(c, 2) for c in v[0]]} for k, v in top]}


def check_closure(walls="WALL_", tol_mm=2.0, reach=0.5):
    """Wall top/bottom faces (at the wall's max/min Z) must touch a slab. A point 1 mm beyond the face that is inside
    another solid (first hit is a back face) = closed; otherwise the distance to the first surface = gap."""
    dg = _dg(); out, fails = [], []
    for o in _objs(walls):
        co, tri = _world_tris(o, dg)
        zmax, zmin = float(co[:, 2].max()), float(co[:, 2].min())
        for sign, label in ((1, "top"), (-1, "bottom")):
            worst, n, open_ = 0.0, 0, 0
            zface = zmax if sign > 0 else zmin
            for t in tri:
                a, b, c = (Vector(co[k]) for k in t)
                nrm = (b - a).cross(c - a)
                if nrm.length < 1e-10 or nrm.normalized().z * sign < 0.99 or abs(a.z - zface) > 1e-3: continue
                cen = (a + b + c) / 3; n += 1
                d = Vector((0, 0, sign)); p = cen + d * 1e-3
                hits = [h for h in _cast_all(dg, p, d, reach, 4) if h[2] != o]
                if not hits: open_ += 1; continue
                gap = 0.0 if hits[0][1].dot(d) > 0 else (hits[0][0] - cen).length  # back face first -> p is inside a solid
                worst = max(worst, gap)
            rec = {"object": o.name, "face": label, "faces": n, "max_gap_mm": round(worst * 1000, 2), "open_faces": open_}
            out.append(rec)
            if worst * 1000 > tol_mm: fails.append(rec)
    return {"pass": not fails if out else None, "tol_mm": tol_mm, "gaps": fails,
            "note": "open_faces = no surface within reach (half-walls, no ceiling); checked faces" , "checked": len(out)}


def check_zfight(prefixes=None, eps=5e-4, min_area_cm2=1.0):
    """Same-facing coplanar overlapping triangles (different objects, or duplicated faces in one object)."""
    dg = _dg()
    objs = [o for o in bpy.context.scene.objects if o.type == 'MESH' and not o.hide_render and o.visible_get()
            and (not prefixes or any(o.name.startswith(p) for p in prefixes.split(",")))]
    buckets = {}
    for oi, o in enumerate(objs):
        co, tri = _world_tris(o, dg)
        for ti, t in enumerate(tri):
            a, b, c = co[t[0]], co[t[1]], co[t[2]]
            n = np.cross(b - a, c - a); ln = np.linalg.norm(n)
            if ln < 1e-9: continue
            n = n / ln; d = float(n @ a)
            key = (round(n[0], 2), round(n[1], 2), round(n[2], 2), int(round(d / eps)))
            buckets.setdefault(key, []).append((oi, ti, tuple(t), np.array([a, b, c]), n))
    pairs, hidden = {}, {}
    for key, items in buckets.items():
        near = items + buckets.get(key[:3] + (key[3] + 1,), [])
        if len(near) < 2: continue
        for i in range(len(items)):
            oi, ti, vi, P, n = items[i]
            u = np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0]); u /= np.linalg.norm(u); v = np.cross(n, u)
            A = [(float(p @ u), float(p @ v)) for p in P]
            for oj, tj, vj, Q, m in near[i + 1:]:
                if oi == oj and (ti == tj or set(vi) & set(vj)): continue
                B = [(float(q @ u), float(q @ v)) for q in Q]
                if min(x for x, _ in A) >= max(x for x, _ in B) or min(x for x, _ in B) >= max(x for x, _ in A): continue
                if min(y for _, y in A) >= max(y for _, y in B) or min(y for _, y in B) >= max(y for _, y in A): continue
                area, cen = _clip_area(A, B)
                if area * 1e4 >= min_area_cm2:
                    p3 = u * cen[0] + v * cen[1] + n * float(n @ P[0])
                    k = (objs[oi].name, objs[oj].name)
                    if _hidden_in_solid(dg, Vector(p3), Vector(n)):
                        hidden[k] = hidden.get(k, 0.0) + area * 1e4; continue
                    r = pairs.setdefault(k, {"area_cm2": 0.0, "at": [round(float(x), 3) for x in p3]})
                    r["area_cm2"] += area * 1e4
    found = [{"objects": list(k), "overlap_cm2": round(v["area_cm2"], 1), "example": v["at"]} for k, v in sorted(pairs.items(), key=lambda kv: -kv[1]["area_cm2"])]
    return {"pass": not found, "pairs": found[:20], "count": len(found),
            "hidden_pairs_ignored": [{"objects": list(k), "overlap_cm2": round(a, 1)} for k, a in list(hidden.items())[:10]],
            "note": "ignored: back-to-back coincident faces, and overlaps whose front side is inside another solid (e.g. wall bottoms buried in a slab)"}


def _hidden_in_solid(dg, p, n):
    """True if the point 1 mm in front of a face lies inside a closed solid (first hit along the normal is a back face)."""
    h = bpy.context.scene.ray_cast(dg, p + n * 1e-3, n, distance=1e4)
    return bool(h[0] and h[2].dot(n) > 0)


def _clip_area(A, B):
    def area(poly): return abs(sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1] for i in range(len(poly)))) / 2
    def orient(poly): return poly if sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1] for i in range(len(poly))) < 0 else poly[::-1]
    out = orient(list(A)); clip = orient(list(B))
    for i in range(len(clip)):
        c0, c1 = clip[i - 1], clip[i]
        inside = lambda p: (c1[0] - c0[0]) * (p[1] - c0[1]) - (c1[1] - c0[1]) * (p[0] - c0[0]) >= -1e-12  # left of CCW edge
        def inter(p, q):
            x1, y1, x2, y2, x3, y3, x4, y4 = *p, *q, *c0, *c1
            den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            if abs(den) < 1e-15: return q
            t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
            return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        inp, out = out, []
        for j in range(len(inp)):
            p, q = inp[j - 1], inp[j]
            if inside(q):
                if not inside(p): out.append(inter(p, q))
                out.append(q)
            elif inside(p): out.append(inter(p, q))
        if not out: return 0.0, (0.0, 0.0)
    cx = sum(p[0] for p in out) / len(out); cy = sum(p[1] for p in out) / len(out)
    return area(out), (cx, cy)


def check_contact(furniture="FURN_", tol_mm=2.0):
    """Lowest points of each furniture root must sit on a surface: gap > tol = floating, below surface = sunk."""
    dg = _dg(); res, bad = [], []
    fobjs = [o for o in _objs(furniture, ('MESH', 'EMPTY')) if not (o.parent and o.parent.name.startswith(tuple(furniture.split(","))))]
    for o in fobjs:
        family = [o] + list(o.children_recursive)
        pts = []
        for m in family:
            if m.type != 'MESH': continue
            co, _ = _world_tris(m, dg); pts.extend(co.tolist())
        if not pts: continue
        P = np.array(pts); zmin = P[:, 2].min(); low = P[P[:, 2] < zmin + 0.01]
        idx = np.linspace(0, len(low) - 1, min(9, len(low))).astype(int)
        gaps = []
        for p in low[idx]:
            hits = [h for h in _cast_all(dg, Vector(p) + Vector((0, 0, 0.3)), Vector((0, 0, -1)), 2.0, 12) if h[2] not in family]
            if hits: gaps.append(p[2] - hits[0][0].z)
        if not gaps: rec = {"object": o.name, "status": "no support found below"}
        else:
            g = min(gaps, key=abs) * 1000
            rec = {"object": o.name, "gap_mm": round(g, 1), "status": "ok" if abs(g) <= tol_mm else ("floating" if g > 0 else "sunk")}
        res.append(rec)
        if rec["status"] != "ok": bad.append(rec)
    return {"pass": not bad if res else None, "tol_mm": tol_mm, "problems": bad, "checked": len(res)}


def check_dims(furniture="FURN_", expect=None, tol=0.01):
    dg = _dg(); out, bad = [], []
    for o in _objs(furniture, ('MESH', 'EMPTY')):
        if o.parent and o.parent.name.startswith(tuple(furniture.split(","))): continue
        fam = [m for m in [o] + list(o.children_recursive) if m.type == 'MESH']
        if not fam: continue
        P = np.vstack([_world_tris(m, dg)[0] for m in fam]); ext = P.max(0) - P.min(0)
        rec = {"object": o.name, "size_m": [round(float(x), 3) for x in ext]}
        lname = o.name.lower()
        if expect and o.name in expect:
            e = expect[o.name]; errs = {k: round(float(ext["xyz".index(k)] - v), 3) for k, v in e.items() if abs(ext["xyz".index(k)] - v) > tol}
            rec["expected"] = e
            if errs: rec["errors_m"] = errs; bad.append(rec)
        else:
            for kw, dim, lo, hi, note in DIM_RANGES:
                if kw in lname or kw.replace("_", "") in lname.replace("_", ""):
                    h = float(ext[2]); rec["rule"] = f"{note}: {lo}-{hi} m"
                    if not lo <= h <= hi: rec["out_of_range"] = round(h, 3); bad.append(rec)
                    break
        out.append(rec)
    return {"pass": not bad if out else None, "problems": bad, "objects": out[:60]}


def check_glass():
    dg = _dg(); out, bad = [], []
    for o in bpy.context.scene.objects:
        if o.type != 'MESH' or o.hide_render or not _is_glass(o): continue
        ev = o.evaluated_get(dg); me = ev.to_mesh()
        bm = bmesh.new(); bm.from_mesh(me); bm.transform(o.matrix_world)
        nonman = sum(1 for e in bm.edges if not e.is_manifold)
        vol = bm.calc_volume(signed=True); ext = [v.co for v in bm.verts]
        bm.free(); ev.to_mesh_clear()
        thin = _thin_wall(o)
        rec = {"object": o.name, "non_manifold_edges": nonman, "signed_volume_m3": round(vol, 6), "thin_wall": thin}
        if nonman and not thin: rec["issue"] = "single-sided glass without Thin Wall (5.2+): refraction through one surface bends the view; enable Thin Wall or give it thickness"
        elif not nonman and thin: rec["note"] = "solid pane with Thin Wall: each face acts as a sheet (double pane); fine, or use a single plane"
        elif vol < 0: rec["issue"] = "normals point inward (flip): refraction inverted"
        if "issue" in rec: bad.append(rec)
        out.append(rec)
    return {"pass": not bad if out else None, "problems": bad, "checked": len(out)}


def check_camera(lens_range=(16, 35), eye=(1.0, 1.7), max_tilt_deg=1.0):
    dg = _dg(); sc = bpy.context.scene; out, bad = [], []
    for cam in [o for o in sc.objects if o.type == 'CAMERA']:
        m = cam.matrix_world.to_3x3(); fwd = (m @ Vector((0, 0, -1))).normalized(); right = (m @ Vector((1, 0, 0))).normalized()
        pitch = math.degrees(math.asin(max(-1, min(1, fwd.z)))); roll = math.degrees(math.asin(max(-1, min(1, right.z))))
        loc = cam.matrix_world.translation; cd = cam.data
        down = _cast_all(dg, loc, Vector((0, 0, -1)), 50, 1)
        inside = 0
        for d in (Vector((1, 0, 0)), Vector((-1, 0, 0)), Vector((0, 1, 0)), Vector((0, -1, 0)), Vector((0, 0, 1)), Vector((0, 0, -1))):
            h = _cast_all(dg, loc, d, 1e3, 1)
            inside += bool(h and h[0][1].dot(d) > 0)
        ahead = _cast_all(dg, loc, fwd, 1e4, 1)
        rec = {"camera": cam.name, "active": sc.camera == cam, "lens_mm": round(cd.lens, 1) if cd.type == 'PERSP' else cd.type,
               "pitch_deg": round(pitch, 2), "roll_deg": round(roll, 2), "shift_x": round(cd.shift_x, 3), "shift_y": round(cd.shift_y, 3),
               "height_above_floor_m": round(loc.z - down[0][0].z, 3) if down else None, "clip": [cd.clip_start, cd.clip_end]}
        issues = []
        if abs(pitch) > max_tilt_deg: issues.append(f"pitched {pitch:.1f} deg: verticals converge -- level the camera (rot X = 90) and frame with shift_y")
        if abs(roll) > 0.5: issues.append(f"rolled {roll:.1f} deg: horizon/verticals tilted")
        if cd.type == 'PERSP' and not lens_range[0] <= cd.lens <= lens_range[1]: issues.append(f"lens {cd.lens:.0f} mm outside {lens_range} (interior norm; exteriors/details may differ)")
        if rec["height_above_floor_m"] is not None and not eye[0] <= rec["height_above_floor_m"] <= eye[1]: issues.append(f"height {rec['height_above_floor_m']} m outside eye range {eye}")
        if inside >= 5: issues.append("camera appears to be inside geometry (back faces in >=5 of 6 directions)")
        if ahead and (ahead[0][0] - loc).length < cd.clip_start: issues.append("clip_start is beyond the first surface ahead")
        if max(abs(cd.shift_x), abs(cd.shift_y)) > 0.5: issues.append("shift > 0.5: strong lens-shift distortion at frame edge")
        rec["issues"] = issues; out.append(rec)
        if issues: bad.append(rec)
    return {"pass": not bad if out else None, "cameras": out}


def check_render():
    sc = bpy.context.scene; r = sc.render; vs = sc.view_settings; info, warn = {}, []
    info.update({"engine": r.engine, "resolution": [r.resolution_x, r.resolution_y, r.resolution_percentage],
                 "view_transform": vs.view_transform, "look": vs.look, "exposure": vs.exposure, "gamma": vs.gamma,
                 "file_format": r.image_settings.file_format, "color_depth": r.image_settings.color_depth})
    if vs.view_transform == 'Standard': warn.append("Standard view transform clips bright windows/sky: use AgX (or Khronos PBR Neutral for true material colors)")
    if r.engine == 'CYCLES':
        c = sc.cycles; g = lambda k, d=None: getattr(c, k, d)
        info.update({k: g(k) for k in ("samples", "use_adaptive_sampling", "adaptive_threshold", "use_denoising", "denoiser", "max_bounces",
                                          "diffuse_bounces", "glossy_bounces", "transmission_bounces", "transparent_max_bounces",
                                          "sample_clamp_direct", "sample_clamp_indirect", "caustics_reflective", "caustics_refractive",
                                          "use_light_tree", "device")})
        if not g("use_denoising", True) and g("samples", 0) < 1024: warn.append("denoising off with < 1024 samples: visible noise in interiors")
        if g("sample_clamp_indirect", 0) == 0: warn.append("indirect clamp 0: fireflies likely in interiors (try 5-10)")
        if g("caustics_refractive", False) or g("caustics_reflective", False): warn.append("caustics on: slow + fireflies through glass/metal; turn off unless needed")
        glass = [o for o in sc.objects if o.type == 'MESH' and not o.hide_render and _is_glass(o)]
        if glass and g("transmission_bounces", 12) < 8: warn.append("transmission_bounces < 8 with glass in scene: panes can render dark")
        if glass and g("transparent_max_bounces", 8) < 8: warn.append("transparent_max_bounces < 8 with glass/alpha: dark or cut-off layers")
        if g("diffuse_bounces", 4) < 3: warn.append("diffuse_bounces < 3: interiors lit through windows go dark")
        if r.image_settings.file_format in ('PNG', 'JPEG') and r.image_settings.color_depth == '8': warn.append("8-bit output: keep a 16-bit/EXR master for post")
    return {"pass": not warn, "settings": info, "warnings": warn}


def check_uv(prefixes=None, ratio_limit=2.0):
    """UV units per metre per object (world-scale box UV = 1.0); flags objects sharing a material at different scales."""
    dg = _dg(); per, bymat = [], {}
    for o in bpy.context.scene.objects:
        if o.type != 'MESH' or o.hide_render or (prefixes and not any(o.name.startswith(p) for p in prefixes.split(","))): continue
        ev = o.evaluated_get(dg); me = ev.to_mesh()
        if not me.uv_layers.active: ev.to_mesh_clear(); per.append({"object": o.name, "uv": None}); continue
        uv = me.uv_layers.active.data; mw = o.matrix_world; wa = ua = 0.0
        for p in me.polygons:
            vs = [mw @ me.vertices[i].co for i in p.vertices]; us = [uv[li].uv for li in p.loop_indices]
            for k in range(1, len(vs) - 1):
                wa += ((vs[k] - vs[0]).cross(vs[k + 1] - vs[0])).length / 2
                ua += abs((us[k] - us[0]).cross(us[k + 1] - us[0])) / 2
        r = math.sqrt(ua / wa) if wa > 0 else None
        mats = [s.material.name for s in o.material_slots if s.material]
        ev.to_mesh_clear()
        per.append({"object": o.name, "uv_units_per_m": round(r, 3) if r else None, "materials": mats})
        for mn in mats:
            if r: bymat.setdefault(mn, []).append((o.name, r))
    mism = [{"material": m, "objects": [(n, round(r, 3)) for n, r in v]} for m, v in bymat.items()
            if len(v) > 1 and max(r for _, r in v) / min(r for _, r in v) > ratio_limit]
    no_uv = [p["object"] for p in per if "uv_units_per_m" not in p]
    return {"pass": not mism, "texture_scale_mismatch": mism, "objects_without_uv": no_uv[:40], "objects": per[:80],
            "note": "world-scale box UVs read 1.0; objects without UVs only matter if their materials use UV coordinates"}


CHECKS = {"leaks": check_leaks, "closure": check_closure, "zfight": check_zfight, "contact": check_contact, "dims": check_dims,
          "glass": check_glass, "camera": check_camera, "render": check_render, "uv": check_uv}


def run_gates(checks=None, walls="WALL_", rooms="FLR_", portals="CUT_", furniture="FURN_", expect=None, rays=256,
              tol_mm=2.0, min_overlap_cm2=1.0):
    checks = checks or list(CHECKS)
    if isinstance(expect, str):
        with open(bpy.path.abspath(expect), encoding="utf-8") as f: expect = json.load(f)
    args = {"leaks": dict(rooms=rooms, portals=portals, rays=rays), "closure": dict(walls=walls, tol_mm=tol_mm),
            "zfight": dict(min_area_cm2=min_overlap_cm2), "contact": dict(furniture=furniture, tol_mm=tol_mm),
            "dims": dict(furniture=furniture, expect=expect), "glass": {}, "camera": {}, "render": {}, "uv": {}}
    out = {"blender": bpy.app.version_string}
    for c in checks:
        try: out[c] = CHECKS[c](**args[c])
        except Exception as e: out[c] = {"pass": False, "error": f"{type(e).__name__}: {e}"}
    out["summary"] = {c: out[c].get("pass") for c in checks}
    return out


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="archviz_gates.py")
    p.add_argument("--checks", default=",".join(CHECKS)); p.add_argument("--walls", default="WALL_"); p.add_argument("--rooms", default="FLR_")
    p.add_argument("--portals", default="CUT_"); p.add_argument("--furniture", default="FURN_"); p.add_argument("--expect")
    p.add_argument("--rays", type=int, default=256); p.add_argument("--tol-mm", type=float, default=2.0); p.add_argument("--min-overlap-cm2", type=float, default=1.0)
    a = p.parse_args(argv)
    return run_gates(a.checks.split(","), a.walls, a.rooms, a.portals, a.furniture, a.expect, a.rays, a.tol_mm, a.min_overlap_cm2)


if "GATES_OPTS" in globals():
    result = run_gates(**GATES_OPTS); print(json.dumps(result["summary"]))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("ARCHVIZ_GATES " + json.dumps(result, default=str))
else:
    result = {"defined": ["run_gates"] + [f.__name__ for f in CHECKS.values()]}
