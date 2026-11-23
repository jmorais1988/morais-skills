"""Validate a modular grid tile kit and emit socket-based adjacency rules for Wave Function Collapse / constraint solvers
(Martin Donald-style sockets), so tiles authored in Blender join seamlessly in the engine.

Headless / CLI (prints one line: TILE_SOCKETS <json summary>):
    blender -b kit.blend --python tile_sockets.py -- --collection KIT_Tiles --cell 2 2 2 \
        [--pivot BOTTOM_CENTER|CENTER|CORNER (alias CENTER_BOTTOM) --quantize 0.01 --tol 0.001 --no-rotations --include-invalid \
         --out rules.json --preview --save preview.blend]
Live (Blender:execute_blender_code): set before exec
    TILE_OPTS = {"collection": "KIT_Tiles", "cell": (2, 2, 2), "pivot": "BOTTOM_CENTER", "quantize": 0.01, "tol": 0.001,
                 "rotations": True, "include_invalid": False, "out": "//rules.json", "preview": True}
    -> `result` = full rules dict. Without TILE_OPTS the file only defines the functions below.
Functions: validate_kit, extract_sockets, build_rules, write_rules, build_preview, tile_roots, tile_geometry, cell_bounds.

Tiles = top-level objects of the collection (recursive): a MESH (plus its mesh children) or an EMPTY whose mesh descendants
form one tile. An EMPTY without mesh children is a void tile (all sockets "-1", e.g. air). Tile space = world space minus
the tile root's world origin (unapplied rotation/scale is flagged, geometry is evaluated as displayed, modifiers included).
Cell AABB in tile space: BOTTOM_CENTER x,y in [-c/2,c/2], z in [0,cz]; CENTER all centred; CORNER [0,c].
Custom properties on the tile root: tile_weight (float > 0, default 1), tile_rotations ("0,90" degrees; default all four),
tile_overhang (True = geometry may leave the cell AABB).

Side profile = vertices within tol of a cell face plane + edges with both ends in it, quantized, in integer units of
quantize/2 measured from the face centre. Horizontal sides: (u, v) with u = horizontal tangent to the viewer's right when
looking at the face from OUTSIDE (posX u=+y, negX u=-y, posY u=-x, negY u=+x) and v = z. Vertical sides: (x, y), not mirrored.
Socket IDs: horizontal "<n>s" symmetric (profile == its u-mirror), "<n>" / "<n>f" mirror pair, "-1" empty.
Vertical "v<n>_<r>" where rotating the profile r quarter turns CCW gives the class's canonical form, "v<n>_i" if invariant
under 90 degrees, "-1" empty. Horizontal compatible: both "-1" | equal and ending "s" | a+"f"==b | b+"f"==a.
Vertical compatible: equal strings. Rotation k = CCW quarter turns about +Z through the cell centre (posX->posY->negX->negY).
"""
import bpy, math, re, sys, json
from mathutils import Vector, Matrix

PIVOTS = ("BOTTOM_CENTER", "CENTER", "CORNER")
PIVOT_ALIASES = {"CENTER_BOTTOM": "BOTTOM_CENTER"}  # canonical spelling shared with asset_library.py


def canonical_pivot(pivot):
    p = PIVOT_ALIASES.get(str(pivot).upper(), str(pivot).upper())
    if p not in PIVOTS:
        raise ValueError(f"pivot {pivot!r} not in {PIVOTS} (aliases {sorted(PIVOT_ALIASES)})")
    return p
SIDES = ("posX", "negX", "posY", "negY", "posZ", "negZ")
HSIDES = SIDES[:4]
OPPOSITE = {"posX": "negX", "negX": "posX", "posY": "negY", "negY": "posY", "posZ": "negZ", "negZ": "posZ"}
ROT_SIDE = {"posX": "posY", "posY": "negX", "negX": "negY", "negY": "posX", "posZ": "posZ", "negZ": "negZ"}  # one CCW quarter turn
STEP = {"posX": (1, 0, 0), "negX": (-1, 0, 0), "posY": (0, 1, 0), "negY": (0, -1, 0), "posZ": (0, 0, 1), "negZ": (0, 0, -1)}
# side -> (normal axis, plane on hi bound?, u axis, u sign, v axis)
FRAMES = {"posX": (0, True, 1, 1, 2), "negX": (0, False, 1, -1, 2), "posY": (1, True, 0, -1, 2), "negY": (1, False, 0, 1, 2),
          "posZ": (2, True, 0, 1, 1), "negZ": (2, False, 0, 1, 1)}


def cell_bounds(cell, pivot='BOTTOM_CENTER'):
    cx, cy, cz = (float(c) for c in cell); pivot = canonical_pivot(pivot)
    if pivot == 'BOTTOM_CENTER': return (-cx / 2, -cy / 2, 0.0), (cx / 2, cy / 2, cz)
    if pivot == 'CENTER': return (-cx / 2, -cy / 2, -cz / 2), (cx / 2, cy / 2, cz / 2)
    if pivot == 'CORNER': return (0.0, 0.0, 0.0), (cx, cy, cz)
    raise ValueError(f"pivot {pivot!r} not in {PIVOTS}")


def _coll(c):
    if isinstance(c, str):
        if c not in bpy.data.collections: raise KeyError(f"collection {c!r} not found; have {list(bpy.data.collections.keys())}")
        return bpy.data.collections[c]
    return c


def tile_roots(collection):
    coll = _coll(collection); objs = set(coll.all_objects)
    return sorted((o for o in objs if o.parent not in objs), key=lambda o: o.name)


def tile_parts(root):
    return ([root] if root.type == 'MESH' else []) + sorted((c for c in root.children_recursive if c.type == 'MESH'), key=lambda o: o.name)


def tile_geometry(root, depsgraph=None):
    """Evaluated vertices (tile space), edges (global indices) and faces-per-edge of every mesh part of a tile."""
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    t0 = Matrix.Translation(-root.matrix_world.translation)
    verts, edges, efaces, parts = [], [], [], []
    for p in tile_parts(root):
        ev = p.evaluated_get(dg); me = ev.to_mesh()
        try:
            m = t0 @ p.matrix_world; n = len(me.vertices); ne = len(me.edges)
            co = [0.0] * (3 * n); me.vertices.foreach_get("co", co)
            ei = [0] * (2 * ne); me.edges.foreach_get("vertices", ei)
            li = [0] * len(me.loops); me.loops.foreach_get("edge_index", li)
            base = len(verts)
            verts.extend(m @ Vector(co[3 * i:3 * i + 3]) for i in range(n))
            edges.extend((base + ei[2 * i], base + ei[2 * i + 1]) for i in range(ne))
            cnt = [0] * ne
            for e in li: cnt[e] += 1
            efaces.extend(cnt); parts.append(p.name)
        finally:
            ev.to_mesh_clear()
    return {"verts": verts, "edges": edges, "edge_faces": efaces, "parts": parts}


def _overhang(bmin, bmax, lo, hi):
    return [max(lo[a] - bmin[a], bmax[a] - hi[a], 0.0) for a in range(3)]


def _on_sides(v, lo, hi, tol):
    return [s for s, (ax, onhi, *_r) in FRAMES.items() if abs(v[ax] - (hi[ax] if onhi else lo[ax])) <= tol]


def _parse_rotations(val):
    ks = set()
    for tok in re.split(r"[,\s;]+", str(val).strip()):
        if not tok: continue
        d = float(tok)
        if abs(d / 90 - round(d / 90)) > 1e-6: raise ValueError(f"{tok} is not a multiple of 90")
        ks.add(int(round(d / 90)) % 4)
    if not ks: raise ValueError("empty")
    return sorted(ks)


def validate_kit(collection, cell=(2.0, 2.0, 2.0), pivot='BOTTOM_CENTER', tol=0.001, quantize=0.01, depsgraph=None):
    """Per-tile ERROR/WARN findings. A tile is `valid` when it has no ERROR."""
    coll = _coll(collection); cell = tuple(float(c) for c in cell); q = float(quantize)
    pivot = canonical_pivot(pivot); lo, hi = cell_bounds(cell, pivot)
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    near_band = max(q, 10 * tol)
    out = {"collection": coll.name, "cell": list(cell), "pivot": pivot, "tol": tol, "quantize": q, "tiles": {}, "kit_issues": []}
    for a in range(3):
        if abs(cell[a] / q - round(cell[a] / q)) > 1e-6:
            out["kit_issues"].append({"kind": "cell_not_multiple_of_quantize", "severity": "ERROR", "axis": "XYZ"[a]})
    roots = tile_roots(coll)
    for r in roots:
        issues = []
        add = lambda kind, sev, **kw: issues.append({"kind": kind, "severity": sev, **kw})
        rec = {"object": r.name, "type": r.type, "issues": issues}
        out["tiles"][r.name] = rec
        if r.type not in ('MESH', 'EMPTY'):
            add("unsupported_type", "ERROR", detail=f"{r.type}: tiles must be MESH or EMPTY with mesh children"); continue
        mw = r.matrix_world; _loc, rot, sca = mw.decompose()
        if mw.to_3x3().determinant() < 0:
            add("negative_scale", "ERROR", detail="mirrored transform flips normals/winding in engines; apply transforms")
        ang = rot.angle % (2 * math.pi)
        if min(ang, 2 * math.pi - ang) > 1e-4:
            add("unapplied_rotation", "ERROR", euler_deg=[round(math.degrees(e), 3) for e in mw.to_euler()])
        if any(abs(abs(s) - 1) > 1e-5 for s in sca):
            add("unapplied_scale", "ERROR", scale=[round(s, 5) for s in sca])
        weight, rots = 1.0, [0, 1, 2, 3]
        if "tile_weight" in r.keys():
            try:
                weight = float(r["tile_weight"])
                if not weight > 0: add("bad_tile_weight", "ERROR", value=weight)
            except (TypeError, ValueError):
                add("bad_tile_weight", "ERROR", value=str(r["tile_weight"])); weight = 1.0
        if "tile_rotations" in r.keys():
            try: rots = _parse_rotations(r["tile_rotations"])
            except (TypeError, ValueError) as ex: add("bad_tile_rotations", "ERROR", value=str(r["tile_rotations"]), detail=str(ex))
        allow_over = bool(r.get("tile_overhang", False))
        g = tile_geometry(r, dg); V = g["verts"]
        rec.update(parts=g["parts"], verts=len(V), weight=weight, rotations=[k * 90 for k in rots], overhang_allowed=allow_over)
        if not V:
            rec["note"] = "void tile: no geometry, all sockets -1"; continue
        bmin = [min(v[a] for v in V) for a in range(3)]; bmax = [max(v[a] for v in V) for a in range(3)]
        oh = _overhang(bmin, bmax, lo, hi)
        rec.update(bounds_min=[round(x, 5) for x in bmin], bounds_max=[round(x, 5) for x in bmax], overhang=[round(x, 5) for x in oh])
        if max(oh) > tol and not allow_over:
            fits = [p for p in PIVOTS if p != pivot and max(_overhang(bmin, bmax, *cell_bounds(cell, p))) <= tol]
            ext = [bmax[a] - bmin[a] for a in range(3)]
            if fits:
                add("pivot_mismatch", "ERROR", detail=f"origin placement matches {fits} convention, not {pivot}")
            elif all(ext[a] <= cell[a] + tol for a in range(3)):
                shift = [round(bmin[a] - lo[a], 5) if bmin[a] < lo[a] - tol else round(bmax[a] - hi[a], 5) if bmax[a] > hi[a] + tol else 0.0
                         for a in range(3)]
                add("pivot_offset", "ERROR", origin_should_move_by=shift, detail="geometry fits one cell but origin is off-convention")
            else:
                add("overhang", "ERROR", max_overhang_xyz=[round(x, 5) for x in oh],
                    detail="geometry leaves the cell AABB; set custom property tile_overhang=True if intended")
        on = [_on_sides(v, lo, hi, tol) for v in V]
        # quantize grid on boundary planes (tangent coordinates measured from the cell min corner)
        off, off_max, off_sample, near = 0, 0.0, [], 0
        for v, sides in zip(V, on):
            if sides:
                axes = {a for s in sides for a in (0, 1, 2) if a != FRAMES[s][0]}
                err = max(abs((v[a] - lo[a]) - round((v[a] - lo[a]) / q) * q) for a in axes)
                if err > tol:
                    off += 1; off_max = max(off_max, err)
                    if len(off_sample) < 5: off_sample.append({"sides": sides, "co": [round(c, 5) for c in v]})
            else:
                for s, (ax, onhi, *_r) in FRAMES.items():
                    d = abs(v[ax] - (hi[ax] if onhi else lo[ax]))
                    if tol < d <= near_band: near += 1; break
        if off:
            add("offgrid_boundary_vertices", "ERROR", count=off, max_error=round(off_max, 6), sample=off_sample,
                detail=f"boundary vertices not on the {q} grid -> sockets won't match neighbours")
        if near:
            add("near_boundary_vertices", "WARN", count=near, detail=f"vertices {tol}..{near_band} from a cell face: meant to be on it?")
        border_off = loose_off = nonman = 0
        for (a, b), fc in zip(g["edges"], g["edge_faces"]):
            if fc > 2: nonman += 1
            elif fc < 2 and not (set(on[a]) & set(on[b])):
                if fc == 1: border_off += 1
                else: loose_off += 1
        if border_off: add("open_border_edges_inside_cell", "WARN", count=border_off, detail="holes not on a cell face: visible cracks")
        if loose_off: add("loose_edges_inside_cell", "WARN", count=loose_off)
        if nonman: add("nonmanifold_edges", "WARN", count=nonman, detail="edges with >2 faces")
    base = {}
    for r in roots: base.setdefault(re.sub(r"\.\d{3,}$", "", r.name).lower(), []).append(r.name)
    for names in base.values():
        if len(names) > 1:
            for n in names:
                out["tiles"][n]["issues"].append({"kind": "duplicate_name", "severity": "ERROR", "clashes_with": [x for x in names if x != n],
                                                  "detail": "same name after stripping .001 suffix / case; engines key prototypes by name"})
    for rec in out["tiles"].values():
        rec["valid"] = not any(i["severity"] == "ERROR" for i in rec["issues"])
    return out


# ---------------- profiles & socket registry ----------------
def _prof(points, edges):
    return (tuple(sorted(points)), tuple(sorted(edges)))


def _map_prof(prof, f):
    return _prof({f(p) for p in prof[0]}, {tuple(sorted((f(a), f(b)))) for a, b in prof[1]})


def _mirror_u(prof): return _map_prof(prof, lambda p: (-p[0], p[1]))
def _rot90(prof): return _map_prof(prof, lambda p: (-p[1], p[0]))  # CCW quarter turn about +Z in (x, y)


def side_profile(verts, edges, side, cell, pivot, quantize, tol):
    lo, hi = cell_bounds(cell, pivot); ax, onhi, ua, us, va = FRAMES[side]; pv = hi[ax] if onhi else lo[ax]
    key = lambda c, a: 2 * round((c - lo[a]) / quantize) - round(cell[a] / quantize)  # half-quantize units from face centre
    on = {}
    for i, v in enumerate(verts):
        if abs(v[ax] - pv) <= tol: on[i] = (us * key(v[ua], ua), key(v[va], va))
    if not on: return None
    eds = {tuple(sorted((on[a], on[b]))) for a, b in edges if a in on and b in on and on[a] != on[b]}
    return _prof(set(on.values()), eds)


class SocketRegistry:
    def __init__(self): self.h, self.v, self.profiles = {}, {}, {}

    def hsocket(self, prof):
        if prof is None: return "-1"
        m = _mirror_u(prof); canon = min(prof, m)
        if canon not in self.h:
            self.h[canon] = n = len(self.h); self.profiles[str(n)] = {"points": [list(p) for p in canon[0]], "edges": [[list(a), list(b)] for a, b in canon[1]]}
        n = self.h[canon]
        return f"{n}s" if prof == m else (f"{n}" if prof == canon else f"{n}f")

    def vsocket(self, prof):
        if prof is None: return "-1"
        rots = [prof]
        for _ in range(3): rots.append(_rot90(rots[-1]))
        canon = min(rots)
        if canon not in self.v:
            self.v[canon] = n = len(self.v); self.profiles[f"v{n}"] = {"points": [list(p) for p in canon[0]], "edges": [[list(a), list(b)] for a, b in canon[1]]}
        n = self.v[canon]
        if rots[1] == prof: return f"v{n}_i"
        return f"v{n}_{min(i for i in range(4) if rots[i] == canon)}"


def extract_sockets(collection, cell=(2.0, 2.0, 2.0), pivot='BOTTOM_CENTER', quantize=0.01, tol=0.001, depsgraph=None, registry=None):
    """Rotation-0 sockets of every tile. Keys starting with '_' hold raw profiles for variant generation (not JSON)."""
    cell = tuple(float(c) for c in cell); reg = registry or SocketRegistry()
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    out = {"tiles": {}, "_registry": reg, "_profiles": {}}
    for r in tile_roots(collection):
        g = tile_geometry(r, dg) if r.type in ('MESH', 'EMPTY') else {"verts": [], "edges": []}
        profs = {s: side_profile(g["verts"], g["edges"], s, cell, pivot, float(quantize), tol) for s in SIDES}
        socks = {s: (reg.hsocket(profs[s]) if s in HSIDES else reg.vsocket(profs[s])) for s in SIDES}
        out["tiles"][r.name] = {"sockets": socks, "profile_size": {s: ([len(p[0]), len(p[1])] if p else [0, 0]) for s, p in profs.items()}}
        out["_profiles"][r.name] = profs
    return out


def variant_sockets(ext, tile, k):
    reg, profs, s0 = ext["_registry"], ext["_profiles"][tile], ext["tiles"][tile]["sockets"]
    s = {}
    for side in HSIDES:
        d = side
        for _ in range(k % 4): d = ROT_SIDE[d]
        s[d] = s0[side]
    for side in ("posZ", "negZ"):
        p = profs[side]
        for _ in range(k % 4): p = _rot90(p) if p else None
        s[side] = reg.vsocket(p)
    return {d: s[d] for d in SIDES}


def h_compatible(a, b):
    return (a == "-1" and b == "-1") or (a == b and a.endswith("s")) or a + "f" == b or b + "f" == a


def v_compatible(a, b):
    return a == b


def build_rules(collection, cell=(2.0, 2.0, 2.0), pivot='BOTTOM_CENTER', quantize=0.01, tol=0.001, rotations=True, include_invalid=False):
    cell = tuple(float(c) for c in cell); dg = bpy.context.evaluated_depsgraph_get(); pivot = canonical_pivot(pivot)
    val = validate_kit(collection, cell, pivot, tol, quantize, dg)
    ext = extract_sockets(collection, cell, pivot, quantize, tol, dg)
    notes = []
    if rotations and abs(cell[0] - cell[1]) > tol:
        rotations = False; notes.append("cell x != y: rotation variants disabled")
    protos, excluded, dedupe = {}, [], {}
    for tname in sorted(ext["tiles"]):
        t = val["tiles"][tname]
        if not t["valid"] and not include_invalid:
            excluded.append({"tile": tname, "errors": sorted({i["kind"] for i in t["issues"] if i["severity"] == "ERROR"})}); continue
        ks = [k // 90 for k in t.get("rotations", [0, 90, 180, 270])] if rotations else [0]
        seen = {}
        for k in sorted(ks):
            s = variant_sockets(ext, tname, k); sig = tuple(s.values())
            if sig in seen:
                dedupe.setdefault(tname, []).append({"rotation": k, "same_as": seen[sig]}); continue
            seen[sig] = k
            protos[f"{tname}_{k}"] = {"mesh": tname, "rotation": k, "sockets": s, "weight": t.get("weight", 1.0), "neighbours": {}}
    for pn, p in protos.items():
        for d in SIDES:
            comp = h_compatible if d in HSIDES else v_compatible
            p["neighbours"][d] = [qn for qn, q in protos.items() if comp(p["sockets"][d], q["sockets"][OPPOSITE[d]])]
    orphan_sides = [{"prototype": pn, "side": d, "socket": p["sockets"][d]} for pn, p in protos.items() for d in SIDES if not p["neighbours"][d]]
    orphan_sockets = sorted({f'{o["side"]}:{o["socket"]}' for o in orphan_sides})
    # arc-consistency over HORIZONTAL sides on an unbounded layer (vertical orphans are usually intended grid floors/ceilings,
    # e.g. nothing sits below ground -> reported in orphan_sides, not pruned)
    alive = set(protos); changed = True
    while changed:
        changed = False
        for pn in sorted(alive):
            if any(not any(q in alive for q in protos[pn]["neighbours"][d]) for d in HSIDES):
                alive.discard(pn); changed = True
    tiles_in = sorted({p["mesh"] for p in protos.values()})
    never = [t for t in tiles_in if not any(protos[pn]["mesh"] == t for pn in alive)]
    counts = {"horizontal": {}, "vertical": {}}
    for p in protos.values():
        for d, s in p["sockets"].items():
            c = counts["horizontal" if d in HSIDES else "vertical"]; c[s] = c.get(s, 0) + 1
    n_err = sum(1 for t in val["tiles"].values() if not t["valid"])
    rules = {
        "format": "tile_sockets/1", "blender": bpy.app.version_string, "collection": val["collection"], "cell": list(cell),
        "pivot": pivot, "quantize": quantize, "tol": tol, "rotations_enabled": bool(rotations),
        "conventions": {
            "rotation": "k CCW quarter turns about +Z through cell centre; geometry on posX moves to posY",
            "horizontal_frame": "u = right-hand tangent seen from outside (posX:+y negX:-y posY:-x negY:+x), v = z; units quantize/2 from face centre",
            "vertical_frame": "(x, y) from face centre, not mirrored; v<n>_<r>: r CCW quarter turns map profile to canonical",
            "horizontal_compatible": "both -1 | equal and ending 's' | a+'f'==b | b+'f'==a",
            "vertical_compatible": "equal strings", "neighbours": "neighbours[side] = prototypes allowed in the adjacent cell on that side"},
        "prototypes": protos, "tiles": val["tiles"], "kit_issues": val["kit_issues"], "excluded_tiles": excluded,
        "rotation_dedupe": dedupe, "socket_profiles": ext["_registry"].profiles,
        "report": {"orphan_sides": orphan_sides, "orphan_sockets": orphan_sockets,
                   "border_only_prototypes": sorted({o["prototype"] for o in orphan_sides if o["side"] in HSIDES}),
                   "vertical_orphan_prototypes": sorted({o["prototype"] for o in orphan_sides if o["side"] not in HSIDES}),
                   "unplaceable_interior_prototypes": sorted(set(protos) - alive), "never_placeable_tiles": never,
                   "socket_counts": counts, "notes": notes},
    }
    rules["summary"] = (f"{len(val['tiles'])} tiles ({n_err} with ERRORs, {len(excluded)} excluded), {len(protos)} prototypes, "
                        f"{len(orphan_sides)} orphan sides, {len(set(protos) - alive)} prototypes unplaceable inside an unbounded layer, "
                        f"never placeable tiles: {never}")
    return rules


def write_rules(rules, path):
    path = bpy.path.abspath(path)
    with open(path, "w", encoding="utf-8") as f: json.dump(rules, f, indent=1)
    return path


def build_preview(rules, collection_name="TILE_PREVIEW", spacing=1.6, origin=(0.0, 0.0, 0.0)):
    """Linked duplicates of every prototype (rotated about cell centre), one row per tile, cell wire box + text label."""
    cell, pivot = rules["cell"], rules["pivot"]; lo, hi = cell_bounds(cell, pivot)
    c = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, 0.0)); cc = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2))
    coll = bpy.data.collections.get(collection_name)
    if coll is None:
        coll = bpy.data.collections.new(collection_name); bpy.context.scene.collection.children.link(coll)
    for o in list(coll.objects): bpy.data.objects.remove(o, do_unlink=True)
    rows = sorted({p["mesh"] for p in rules["prototypes"].values()}); made = 0
    for pn, p in sorted(rules["prototypes"].items(), key=lambda kv: (kv[1]["mesh"], kv[1]["rotation"])):
        row, col = rows.index(p["mesh"]), p["rotation"]
        off = Vector(origin) + Vector((col * cell[0] * spacing, -row * cell[1] * spacing, 0.0))
        R = Matrix.Translation(off + c) @ Matrix.Rotation(p["rotation"] * math.pi / 2, 4, 'Z') @ Matrix.Translation(-c)
        root = bpy.data.objects.get(p["mesh"])
        if root is None: continue
        t0 = Matrix.Translation(-root.matrix_world.translation)
        for part in tile_parts(root):
            ob = part.copy(); ob.name = f"PV_{pn}_{part.name}"; ob.parent = None
            for k in [k for k in ob.keys() if k.startswith("tile_")]: del ob[k]
            coll.objects.link(ob); ob.matrix_world = R @ t0 @ part.matrix_world; made += 1
        box = bpy.data.objects.new(f"PV_{pn}_cell", None); box.empty_display_type = 'CUBE'
        box.matrix_world = Matrix.Translation(off + cc) @ Matrix.Diagonal((cell[0] / 2, cell[1] / 2, cell[2] / 2, 1.0))
        coll.objects.link(box)
        cu = bpy.data.curves.new(f"PV_{pn}_label", 'FONT'); s = p["sockets"]
        cu.body = f"{pn}\n+X {s['posX']}  -X {s['negX']}\n+Y {s['posY']}  -Y {s['negY']}\n+Z {s['posZ']}  -Z {s['negZ']}"
        cu.size = cell[0] * 0.07
        lab = bpy.data.objects.new(f"PV_{pn}_label", cu); lab.location = off + Vector((lo[0], lo[1] - cell[1] * 0.12, lo[2]))
        coll.objects.link(lab)
    return {"collection": coll.name, "prototypes": len(rules["prototypes"]), "mesh_objects": made, "rows": rows}


def summarize(rules):
    return {"summary": rules["summary"],
            "tile_issues": {n: [f'{i["severity"]}:{i["kind"]}' for i in t["issues"]] for n, t in rules["tiles"].items() if t["issues"]},
            "excluded_tiles": rules["excluded_tiles"], "kit_issues": rules["kit_issues"],
            "prototypes": {n: " ".join(p["sockets"][d] for d in SIDES) + f" w={p['weight']}" for n, p in rules["prototypes"].items()},
            "socket_order": list(SIDES), "report": {k: v for k, v in rules["report"].items() if k != "orphan_sides"}}


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="tile_sockets.py")
    p.add_argument("--collection", required=True); p.add_argument("--cell", type=float, nargs=3, required=True)
    p.add_argument("--pivot", choices=PIVOTS + tuple(PIVOT_ALIASES), default="BOTTOM_CENTER"); p.add_argument("--quantize", type=float, default=0.01)
    p.add_argument("--tol", type=float, default=0.001); p.add_argument("--no-rotations", action="store_true")
    p.add_argument("--include-invalid", action="store_true"); p.add_argument("--out"); p.add_argument("--preview", action="store_true")
    p.add_argument("--save")
    a = p.parse_args(argv)
    rules = build_rules(a.collection, a.cell, a.pivot, a.quantize, a.tol, rotations=not a.no_rotations, include_invalid=a.include_invalid)
    res = summarize(rules)
    if a.out: res["out"] = write_rules(rules, a.out)
    if a.preview: res["preview"] = build_preview(rules)
    if a.save: bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(a.save)); res["saved"] = a.save
    return rules, res


if "TILE_OPTS" in globals():  # live exec
    _o = dict(TILE_OPTS)
    result = build_rules(_o["collection"], _o.get("cell", (2, 2, 2)), _o.get("pivot", "BOTTOM_CENTER"), _o.get("quantize", 0.01),
                         _o.get("tol", 0.001), rotations=_o.get("rotations", True), include_invalid=_o.get("include_invalid", False))
    if _o.get("out"): result["out"] = write_rules(result, _o["out"])
    if _o.get("preview"): result["preview"] = build_preview(result)
    print("TILE_SOCKETS " + json.dumps(summarize(result)))
elif __name__ == "__main__" and "--" in sys.argv and "--collection" in sys.argv[sys.argv.index("--") + 1:]:
    _rules, _res = _cli(sys.argv[sys.argv.index("--") + 1:])
    result = _rules
    print("TILE_SOCKETS " + json.dumps(_res))
else:
    result = {"defined": ["validate_kit", "extract_sockets", "build_rules", "write_rules", "build_preview", "tile_roots", "tile_geometry"]}
