"""Parametric solitaire ring for casting/printing: band from ring size, round-brilliant stone proxy (Tolkowsky),
stone-shaped seat cutter, N-prong basket head; gates on inner diameter, prong diameter, notch wall, seat vs girdle
after casting shrinkage, stone/metal interference; optional scripts/export_print.py checks on the unioned metal.

Headless / CLI (prints one line: RING_BUILDER <json>):
    BLENDER -b --factory-startup --python ring_builder.py -- --size US7 [--band-width 2.0] [--band-thickness 1.6]
        [--stone-d 6.5] [--girdle-pct 2.0] [--prongs 4] [--prong-d 1.0] [--seat-clearance 0.05] [--seat-depth-frac 0.35]
        [--culet-clear 0.6] [--tip-frac 0.8] [--shoulder-deg 45] [--no-rail] [--shrink-pct 1.5] [--no-compensate]
        [--min-prong-mm 0.8] [--min-notch-mm 0.5] [--id-tol-mm 0.05] [--max-interference-mm 0.01] [--segments 128]
        [--no-metal-union] [--bool-solver MANIFOLD|EXACT] [--print-gate] [--export-print path/export_print.py]
        [--min-wall-mm 0.5] [--max-thin-area-pct 0.5] [--save ring.blend]
    --size: US7 | US 7.5 | EU54 | ISO54 (inner circumference mm) | UK N | ID17.3 (inner diameter mm) | bare number = US.
Live (Blender:execute_blender_code): set before exec
    RING_OPTS = {"size": "US7", "stone_d": 6.5, "prongs": 4, "prong_d": 1.0, "shrink_pct": 1.5}  -> `result` dict
Without RING_OPTS the file only defines build_ring / ring_size_to_id / gate_ring (result = {"defined": [...]}).

Objects (1 BU = 1 m, scene displays mm; existing objects with these names are replaced): RING_Band, RING_Head
(prongs + gallery rail, seat cut), RING_Metal (band U head, the casting solid; skip with --no-metal-union),
GEM_Stone (never booleaned into metal), CUT_Seat (stone offset by --seat-clearance, kept hidden for re-cutting).
Finger axis = Y, head on +Z. Metal is the PATTERN: nominal metal dims x 1/(1-shrink) when compensating; the stone is
real size and sits in the pattern seat. Gates evaluate the metal AFTER shrink (pattern x (1-shrink) about the seat):
  inner_diameter   vertex and flat-to-flat bore vs size target +- id_tol
  prong_min        min Feret width of each prong's free horizontal section >= min_prong_mm
  notch_wall       min Feret width of each prong section at girdle height (metal behind the seat) >= min_notch_mm
  seat_fits        seat diameter at girdle (min radius of the head section) >= girdle diameter
  interference     stone surface samples inside metal (ray parity), max depth <= max_interference_mm
Round brilliant proxy: table 53 %, crown height 16.2 %, pavilion depth 43.1 % of D, girdle --girdle-pct; 32 facets
around (a proxy for seat cutting and render, not a faceted gem). Prong and cutter polygons are circumscribed so
facets never fall inside the nominal size (flat-to-flat = nominal).
Head: vertical prongs (axis radius = girdle/2 + clearance + prong r - seat_depth_frac * prong d) embedded half a band
thickness into the band; the band top flares (cos^2 over +-shoulder_deg) so every prong lands on band metal -- slanted
prong feet crossing a narrow band's side faces made knife-edge slivers. Prong tips stop at tip_frac of the crown height
(overhang over the crown reported as tip_overhang_mm, warned < min_notch_mm). Booleans run sequentially
(MANIFOLD solver default: EXACT left 20 zero-area faces on a 6-prong head) and outputs are ear-clip triangulated
(fan-triangulating a concave boolean n-gon fakes self-intersections and thin walls in downstream checks).
--print-gate: scripts/export_print.py on RING_Metal; pass = manifold, no intersections, area share thinner than
--min-wall-mm <= --max-thin-area-pct (raw min/p1 reported; they include near-edge ray samples).
Limitations: one head style (N straight prongs + one rail); no draft, fillets or sprues (caster adds; see
3d-printing.md and jewelry-and-casting.md 5); prong tips are flat (bend/burnish over the crown at the bench); no culet hole through the band
(basket is open); ring sizes via formulas (US 11.63 + 0.8128 x size, ISO/EU circumference/pi, UK letters as half sizes).
"""
import bpy, bmesh, json, math, os, re, sys
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

MM = 0.001
TOLK = {"table": 0.53, "crown_h": 0.162, "pav_d": 0.431, "crown_deg": 34.5, "pav_deg": 40.75}
DEFAULTS = dict(size="US7", band_width=2.0, band_thickness=1.6, stone_d=6.5, girdle_pct=2.0, prongs=4, prong_d=1.0,
                seat_clearance=0.05, seat_depth_frac=0.35, culet_clear=0.6, tip_frac=0.8, shoulder_deg=45.0, shrink_pct=1.5, compensate=True,
                min_prong_mm=0.8, min_notch_mm=0.5, id_tol_mm=0.05, max_interference_mm=0.01, segments=128,
                rail=True, metal_union=True, bool_solver="MANIFOLD", print_gate=False, export_print=None, min_wall_mm=0.5,
                max_thin_area_pct=0.5, save=None)


# ---------------------------------------------------------------- sizes
def ring_size_to_id(size):
    """-> (inner diameter mm, parsed description). US ~ 11.63 + 0.8128*s; ISO/EU = inner circumference mm; UK letter
    = US (index-7)/2 + 4 (H=4, N=7, Z=13); ID<mm> literal."""
    s = str(size).strip().upper().replace(" ", "")
    m = re.fullmatch(r"(US|EU|ISO|UK|ID)?([A-Z]|\d+(?:\.\d+)?)", s)
    if not m:
        raise ValueError(f"unrecognised ring size {size!r}")
    sys_, v = m.group(1) or "US", m.group(2)
    if sys_ == "UK" or v.isalpha():
        us = (ord(v) - ord("H")) / 2 + 4
        return 11.63 + 0.8128 * us, f"UK {v} = US {us:g}"
    v = float(v)
    if sys_ == "US":
        return 11.63 + 0.8128 * v, f"US {v:g}"
    if sys_ in ("EU", "ISO"):
        return v / math.pi, f"{sys_} {v:g} (circumference mm)"
    return v, f"ID {v:g} mm"


# ---------------------------------------------------------------- mesh helpers
def _replace_obj(name, verts, faces, coll):
    old = bpy.data.objects.get(name)
    if old is not None:
        me_old = old.data; bpy.data.objects.remove(old)
        if me_old and me_old.users == 0: bpy.data.meshes.remove(me_old)
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:]); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); coll.objects.link(ob)
    return ob


def _revolve(profile, n, circumscribe=False):
    """profile [(r, z)] top->bottom, r == 0 => pole. Revolved about Z -> (verts, faces)."""
    k = 1 / math.cos(math.pi / n) if circumscribe else 1.0
    verts, rings = [], []
    for r, z in profile:
        if r <= 0:
            rings.append([len(verts)]); verts.append((0, 0, z))
        else:
            idx = list(range(len(verts), len(verts) + n)); rings.append(idx)
            verts += [(r * k * math.cos(2 * math.pi * i / n), r * k * math.sin(2 * math.pi * i / n), z) for i in range(n)]
    faces = []
    for a, b in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            if len(a) == 1: faces.append((a[0], b[j], b[i]))
            elif len(b) == 1: faces.append((a[i], a[j], b[0]))
            else: faces.append((a[i], a[j], b[j], b[i]))
    return verts, faces


def _tube_y(r_in, r_out, widths, n):
    """Band: annulus about the Y axis (finger axis), vertices exactly on r_in / r_out; widths[i] per angle step."""
    verts = []
    for sgn in (-1, 1):
        for r in (r_in, r_out):
            verts += [(r * math.cos(2 * math.pi * i / n), sgn * widths[i] / 2, r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    ring = lambda a, i: a * n + i % n  # 0 in-, 1 out-, 2 in+, 3 out+
    faces = []
    for i in range(n):
        faces += [(ring(0, i), ring(0, i + 1), ring(2, i + 1), ring(2, i)), (ring(1, i), ring(3, i), ring(3, i + 1), ring(1, i + 1)),
                  (ring(0, i), ring(1, i), ring(1, i + 1), ring(0, i + 1)), (ring(2, i), ring(2, i + 1), ring(3, i + 1), ring(3, i))]
    return verts, faces


def _cyl_between(p0, p1, r, n):
    """Capped cylinder p0->p1, polygon circumscribed about r (min Feret width = 2r)."""
    p0, p1 = Vector(p0), Vector(p1); ax = (p1 - p0).normalized()
    u = ax.orthogonal().normalized(); v = ax.cross(u); rr = r / math.cos(math.pi / n)
    ring = lambda c: [c + rr * (math.cos(2 * math.pi * i / n) * u + math.sin(2 * math.pi * i / n) * v) for i in range(n)]
    verts = ring(p0) + ring(p1)
    faces = [tuple(range(n))[::-1], tuple(range(n, 2 * n))] + [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    return verts, faces


def _boolean(obj, operand, op, solver="EXACT"):
    solvers = bpy.types.BooleanModifier.bl_rna.properties['solver'].enum_items.keys()
    mod = obj.modifiers.new("_rb_bool", 'BOOLEAN'); mod.operation = op
    mod.solver = solver if solver in solvers else 'EXACT'  # MANIFOLD is 4.5+/5.x; older builds fall back to EXACT
    if isinstance(operand, bpy.types.Collection):
        mod.operand_type = 'COLLECTION'; mod.collection = operand
    else:
        mod.object = operand
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    obj.modifiers.remove(mod); old = obj.data; obj.data = me; me.name = old.name
    bpy.data.meshes.remove(old)
    return obj


def _world_np(o):
    me = o.data; co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co)
    M = np.array(o.matrix_world); return co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]


# ---------------------------------------------------------------- build
def build_ring(**kw):
    p = dict(DEFAULTS); p.update({k: v for k, v in kw.items() if v is not None})
    idmm, size_desc = ring_size_to_id(p["size"])
    s = p["shrink_pct"] / 100.0; k = 1 / (1 - s) if p["compensate"] else 1.0
    n, N = int(p["segments"]), int(p["prongs"])
    D, c, d = p["stone_d"], p["seat_clearance"], p["prong_d"]
    Ri, Ro, w = idmm / 2, idmm / 2 + p["band_thickness"], p["band_width"]
    # nominal metal layout (mm, ring centre at origin, head on +Z)
    z0 = Ro; culet = z0 + p["culet_clear"]; z_gb = culet + TOLK["pav_d"] * D; z_gt = z_gb + p["girdle_pct"] / 100 * D
    z_tab = z_gt + TOLK["crown_h"] * D; r_tab = TOLK["table"] * D / 2
    ca, pa = math.radians(TOLK["crown_deg"]), math.radians(TOLK["pav_deg"])
    rp = d / 2; Rc = D / 2 + c + rp - p["seat_depth_frac"] * d
    z_k = culet; cul_cut = culet - c / math.cos(pa)
    z_hit = cul_cut + (Rc - rp) * math.tan(pa)  # pavilion cutter reaches the prong inner face
    z_rail = z_k + 0.3 * (z_hit - z_k); rail_h, rail_t = 0.8 * d, 0.8 * d
    z_free = z_k + 0.72 * (z_hit - z_k); z_tip = z_gt + p["tip_frac"] * TOLK["crown_h"] * D
    tip_over = z_tip - (z_gt + c * math.cos(ca) + (D / 2 + c * math.sin(ca) - (Rc - rp)) * math.tan(ca))
    phase = math.pi / N
    ang = [phase + 2 * math.pi * i / N for i in range(N)]
    warn = []
    if z_free - (z_rail + rail_h / 2) < 0.1:
        warn.append("stone too shallow for a free prong section above the rail: raise culet_clear")
    if tip_over < p["min_notch_mm"]:
        warn.append(f"prong tip overhang over the crown {tip_over:.3f} mm < min_notch_mm: raise tip_frac")
    # shoulder flare: vertical prongs must land on band metal; widen the band top with a cos^2 taper
    ph0 = math.radians(p["shoulder_deg"]); rr = rp / math.cos(math.pi / 24)
    y_need = max(Rc * abs(math.sin(a)) + rr + 0.3 for a in ang)
    phi_l = max(math.asin(min(1.0, (Rc * abs(math.cos(a)) + rr) / Ro)) for a in ang)
    fl = lambda phi: math.cos(math.pi / 2 * phi / ph0) ** 2 if abs(phi) < ph0 else 0.0
    W = w if 2 * y_need <= w else w + (2 * y_need - w) / max(fl(phi_l), 1e-3)
    if fl(phi_l) < 0.2:
        warn.append("prong landing outside the shoulder taper: raise shoulder_deg")
    widths = [w + (W - w) * fl(((2 * math.pi * i / n - math.pi / 2 + math.pi) % (2 * math.pi)) - math.pi) for i in range(n)]

    coll = bpy.context.scene.collection
    us = bpy.context.scene.unit_settings; us.system = 'METRIC'; us.scale_length = 1.0; us.length_unit = 'MILLIMETERS'
    S = lambda vs, f=k: [tuple(x * MM * f for x in v) for v in vs]

    bv, bf = _tube_y(Ri, Ro, widths, n)
    band = _replace_obj("RING_Band", S(bv), bf, coll)
    stone_prof = [(0, z_tab), (r_tab, z_tab), (D / 2, z_gt), (D / 2, z_gb), (0, culet)]
    sv, sf = _revolve(stone_prof, 32)
    seat_pat = Vector((0, 0, z_gb * MM * k)); seat_nom = Vector((0, 0, z_gb * MM))
    stone = _replace_obj("GEM_Stone", [tuple((Vector(v) * MM) - seat_nom + seat_pat) for v in sv], sf, coll)
    if c >= 0:  # normal offset of crown / girdle / pavilion (monotone profile)
        cut_prof = [(0, z_tab + c), (r_tab + c * math.sin(ca), z_tab + c * math.cos(ca)),
                    (D / 2 + c * math.sin(ca), z_gt + c * math.cos(ca)), (D / 2 + c, z_gt), (D / 2 + c, z_gb),
                    (D / 2 + c * math.sin(pa), z_gb - c * math.cos(pa)), (0, cul_cut)]
    else:  # negative clearance (undersized seat): radial offset only, a normal offset would fold the profile
        cut_prof = [(0, z_tab + c), (r_tab + c, z_tab + c), (D / 2 + c, z_gt), (D / 2 + c, z_gb), (0, cul_cut)]
    cv, cf = _revolve(cut_prof, 64, circumscribe=True)
    cutter = _replace_obj("CUT_Seat", S(cv), cf, coll)

    prong_parts = []
    for a in ang:  # vertical prongs, foot embedded half a band thickness below the band top (steep entry, no knife edge)
        x, y = Rc * math.cos(a), Rc * math.sin(a)
        zb = math.sqrt(max(Ro ** 2 - (abs(x) + rr) ** 2, 0)) - 0.5 * p["band_thickness"]
        prong_parts.append(_cyl_between((x, y, zb), (x, y, z_tip), rp, 24))
    rail_v, rail_f = _revolve([(Rc + rail_t / 2, z_rail + rail_h / 2), (Rc + rail_t / 2, z_rail - rail_h / 2)], n)
    inner_v, inner_f = _revolve([(Rc - rail_t / 2, z_rail - rail_h / 2), (Rc - rail_t / 2, z_rail + rail_h / 2)], n)
    # join outer and inner walls with top/bottom annuli
    V = rail_v + inner_v; F = [f for f in rail_f] + [tuple(i + n * 2 for i in f) for f in inner_f]
    for i in range(n):
        j = (i + 1) % n
        F += [(2 * n + n + i, 2 * n + n + j, j, i), (n + i, n + j, 2 * n + j, 2 * n + i)]
    tmp = bpy.data.collections.new("_rb_tmp"); coll.children.link(tmp)
    sol = p["bool_solver"]
    if p["rail"]:
        head = _replace_obj("RING_Head", S(V), F, coll); parts = prong_parts
    else:
        head = _replace_obj("RING_Head", S(prong_parts[0][0]), prong_parts[0][1], coll); parts = prong_parts[1:]
    for i, (pv, pf) in enumerate(parts):  # sequential unions, one closed shell per operand
        o = _replace_obj(f"_rb_prong{i}", S(pv), pf, tmp)
        _boolean(head, o, 'UNION', sol)
    for o in list(tmp.objects):
        me = o.data; bpy.data.objects.remove(o); bpy.data.meshes.remove(me)
    bpy.data.collections.remove(tmp)
    _boolean(head, cutter, 'DIFFERENCE', sol)
    _boolean(band, cutter, 'DIFFERENCE', sol)
    metal = None
    if p["metal_union"]:
        mv = _world_np(band); metal = _replace_obj("RING_Metal", [tuple(v) for v in mv], [tuple(f.vertices) for f in band.data.polygons], coll)
        _boolean(metal, head, 'UNION', sol)
    for o in (band, head, metal):  # ear-clip n-gons: boolean output has concave n-gons that fan-triangulating tools misread
        if o is None: continue
        bm = bmesh.new(); bm.from_mesh(o.data)
        bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
        bm.to_mesh(o.data); bm.free()
    cutter.hide_set(True); cutter.hide_render = True

    layout = {"id_mm": idmm, "size": size_desc, "girdle_d": D, "z_girdle_bottom": z_gb, "z_girdle_top": z_gt,
              "z_free": z_free, "z_table": z_tab, "prong_axis_r": Rc, "prong_angles_deg": [round(math.degrees(a), 3) for a in ang],
              "pattern_scale": k, "shrink": s, "segments": n, "shoulder_width_mm": round(W, 3),
              "tip_overhang_mm": round(tip_over, 3)}
    return {"params": p, "layout": layout, "warnings": warn,
            "objects": {"band": band.name, "head": head.name, "stone": stone.name, "cutter": cutter.name,
                        "metal": metal.name if metal else None}}


# ---------------------------------------------------------------- measurement
def _section(o, z, bu_to_metal_mm):
    """Horizontal plane section of o at world z (BU): edge/plane intersection points -> Nx2 metal-mm (XY)."""
    co = _world_np(o); e = np.empty(len(o.data.edges) * 2, np.int64); o.data.edges.foreach_get("vertices", e)
    e = e.reshape(-1, 2); a, b = co[e[:, 0]], co[e[:, 1]]
    m = (a[:, 2] - z) * (b[:, 2] - z) < 0
    t = ((z - a[m, 2]) / (b[m, 2] - a[m, 2]))[:, None]
    return (a[m, :2] + t * (b[m, :2] - a[m, :2])) * bu_to_metal_mm


def _feret_min(P, steps=360):
    if len(P) < 3: return 0.0
    th = np.linspace(0, np.pi, steps, endpoint=False); dirs = np.stack([np.cos(th), np.sin(th)], 1)
    pr = P @ dirs.T; return float((pr.max(0) - pr.min(0)).min())


def _by_prong(P, angles):
    a = np.arctan2(P[:, 1], P[:, 0]); diff = np.abs((a[:, None] - np.array(angles)[None] + np.pi) % (2 * np.pi) - np.pi)
    lab = diff.argmin(1); return [P[lab == i] for i in range(len(angles))]


_DIRS = [Vector(v).normalized() for v in ((0.1234, 0.2345, 0.9643), (0.8911, -0.3217, 0.1307), (-0.2711, 0.9123, -0.3079))]


def _inside(bvh, p, max_hits=64):
    """Ray-parity vote over 3 skew directions (a ray grazing a shared edge can miscount one of them)."""
    votes = 0
    for dirv in _DIRS:
        hits, o = 0, Vector(p)
        for _ in range(max_hits):
            loc, nrm, idx, dist = bvh.ray_cast(o, dirv)
            if loc is None: break
            hits += 1; o = loc + dirv * 1e-9
        votes += hits % 2
    return votes >= 2


def _tri_bvh(o, xf):
    """BVH from loop triangles (FromPolygons fan-splits concave boolean n-gons wrongly)."""
    o.data.calc_loop_triangles()
    T = [tuple(t.vertices) for t in o.data.loop_triangles]
    return BVHTree.FromPolygons([tuple(x) for x in xf(_world_np(o)).tolist()], T)


def gate_ring(build, samples=20000, seed=3):
    p, L = build["params"], build["layout"]
    ob = {kk: bpy.data.objects.get(v) for kk, v in build["objects"].items() if v}
    k, s = L["pattern_scale"], L["shrink"]; f = (1 - s) / MM  # pattern BU -> metal mm
    g = {}
    # inner diameter (band verts: radius about Y in XZ)
    co = _world_np(ob["band"]); r = np.hypot(co[:, 0], co[:, 2]) * f
    rin = r[r < r.min() + 0.5 * p["band_thickness"]]
    idv = 2 * float(np.median(rin)); idf = idv * math.cos(math.pi / L["segments"])
    g["inner_diameter"] = {"target_mm": round(L["id_mm"], 4), "vertex_mm": round(idv, 4), "flat_mm": round(idf, 4),
                           "pass": abs(idv - L["id_mm"]) <= p["id_tol_mm"] and abs(idf - L["id_mm"]) <= p["id_tol_mm"]}
    # prong sections
    zf = L["z_free"] * MM * k; zg = 0.5 * (L["z_girdle_bottom"] + L["z_girdle_top"]) * MM * k
    free = [_feret_min(q) for q in _by_prong(_section(ob["head"], zf, f), L["prong_angles_deg"] and [math.radians(a) for a in L["prong_angles_deg"]])]
    Pg = _section(ob["head"], zg, f)
    notch = [_feret_min(q) for q in _by_prong(Pg, [math.radians(a) for a in L["prong_angles_deg"]])]
    g["prong_min"] = {"per_prong_mm": [round(x, 4) for x in free], "min_mm": round(min(free), 4),
                      "limit_mm": p["min_prong_mm"], "pass": min(free) >= p["min_prong_mm"] - 1e-4}
    g["notch_wall"] = {"per_prong_mm": [round(x, 4) for x in notch], "min_mm": round(min(notch), 4),
                       "limit_mm": p["min_notch_mm"], "pass": min(notch) >= p["min_notch_mm"] - 1e-4}
    seat_d = 2 * float(np.hypot(Pg[:, 0], Pg[:, 1]).min()) if len(Pg) else 0.0
    g["seat_fits"] = {"seat_d_after_shrink_mm": round(seat_d, 4), "girdle_d_mm": L["girdle_d"],
                      "clearance_mm": round((seat_d - L["girdle_d"]) / 2, 4), "pass": seat_d >= L["girdle_d"]}
    if seat_d > L["girdle_d"] + 2 * (p["seat_clearance"] + 0.1):
        g["seat_fits"]["warning"] = "seat > girdle + 0.1 mm/side beyond clearance: stone may rattle"
    # interference: metal shrunk about the seat point, stone at its (real) size in the metal seat
    seat_pat = np.array([0, 0, L["z_girdle_bottom"] * MM * k]); seat_met = seat_pat * (1 - s)
    xf = lambda v: (v - seat_pat) * (1 - s) + seat_met
    bvhs = [_tri_bvh(ob[key], xf) for key in ("band", "head")]
    st = ob["stone"]; SV = _world_np(st) - seat_pat + seat_met
    st.data.calc_loop_triangles()
    T = np.array([t.vertices[:] for t in st.data.loop_triangles]); A, B, C = SV[T[:, 0]], SV[T[:, 1]], SV[T[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1); rng = np.random.default_rng(seed)
    ti = rng.choice(len(T), samples, p=area / area.sum()); u, v = rng.random(samples), rng.random(samples)
    flip = u + v > 1; u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    pts = np.vstack([A[ti] + u[:, None] * (B[ti] - A[ti]) + v[:, None] * (C[ti] - A[ti]), SV])
    worst, n_in, gap = 0.0, 0, float("inf"); worst_at = None
    for q in pts:
        for bvh in bvhs:
            loc, nrm, idx, dist = bvh.find_nearest(Vector(q))
            if loc is None: continue
            # inside = nearest-face normal points away from q AND ray-parity vote (either alone misfires on edges)
            if dist < 0.5 * MM and (Vector(q) - loc).dot(nrm) < 0 and _inside(bvh, q):
                n_in += 1
                if dist > worst: worst, worst_at = dist, q
            else:
                gap = min(gap, dist)
    g["interference"] = {"max_depth_mm": round(worst / MM, 4), "inside_samples": n_in, "samples": len(pts),
                         "min_gap_mm": round(gap / MM, 4), "limit_mm": p["max_interference_mm"],
                         "worst_at_mm": None if worst_at is None else [round(x / MM, 3) for x in worst_at],
                         "pass": worst / MM <= p["max_interference_mm"]}
    fails = [kk for kk, v in g.items() if v.get("pass") is False]
    return g, fails


def _print_gate(build, path, min_wall_mm, max_thin_area_pct):
    """export_print.py on the casting solid. pass = manifold & intersect pass & area share below min_wall <=
    max_thin_area_pct (area-weighted, independent of sample density; sample percentiles are not: boolean junctions
    carry many small triangles). The raw export_print min/p1 are kept in the report: they include ray samples next to
    junction / shoulder-flare edges (short chords, ~0.1 % of area), so a strict min fails every boolean ring."""
    ns = {"__name__": "export_print_mod"}
    with open(path, encoding="utf-8") as fh:
        exec(compile(fh.read(), path, "exec"), ns)
    name = build["objects"]["metal"] or build["objects"]["band"]
    r = ns["run_print_gate"](objects=name, checks=["units", "manifold", "intersect", "thickness", "measure"],
                             min_wall_mm=min_wall_mm, samples_per_mm2=4.0)
    po = r["per_object"][name]; th = po.get("thickness", {})
    ok = bool(po.get("manifold", {}).get("pass") and po.get("intersect", {}).get("pass")
              and th.get("area_below_pct") is not None and th["area_below_pct"] <= max_thin_area_pct)
    return {"pass": ok, "export_print_summary": r["summary"], "manifold": po.get("manifold"),
            "intersect_pairs": po.get("intersect", {}).get("intersecting_tri_pairs"),
            "thickness": {kk: r["per_object"][name].get("thickness", {}).get(kk)
                          for kk in ("min_mm", "p1_mm", "p5_mm", "area_below_pct", "pass", "worst")},
            "measure": r["per_object"][name].get("measure")}


def run(**kw):
    b = build_ring(**kw)
    g, fails = gate_ring(b)
    out = {"blender": bpy.app.version_string, **b, "gates": g}
    if b["params"]["print_gate"]:
        path = b["params"]["export_print"] or os.path.join(os.path.dirname(os.path.abspath(__file__)), "export_print.py")
        try:
            out["print_gate"] = _print_gate(b, path, b["params"]["min_wall_mm"], b["params"]["max_thin_area_pct"])
            if not out["print_gate"]["pass"]: fails.append("print_gate")
        except Exception as e:
            out["print_gate"] = {"error": f"{type(e).__name__}: {e}"}; fails.append("print_gate")
    if b["params"]["save"]:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(b["params"]["save"]))
    out["summary"] = {"pass": not fails, "failed": fails}
    return out


def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="ring_builder.py")
    for kk, v in DEFAULTS.items():
        if kk in ("compensate", "metal_union", "rail"):
            ap.add_argument("--no-" + kk.replace("_", "-"), dest=kk, action="store_false")
        elif kk == "print_gate":
            ap.add_argument("--print-gate", action="store_true")
        else:
            ap.add_argument("--" + kk.replace("_", "-"), type=(type(v) if v is not None and not isinstance(v, str) else str), default=v)
    return run(**vars(ap.parse_args(argv)))


if "RING_OPTS" in globals():
    result = run(**RING_OPTS); print(json.dumps(result["summary"]))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("RING_BUILDER " + json.dumps(result, default=str))
else:
    result = {"defined": ["build_ring", "gate_ring", "ring_size_to_id", "run"]}
