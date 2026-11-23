"""
mesh_audit.py - mesh-level flaw detector for Blender scenes.

Run INSIDE Blender (paste into the Python console, run via blender_socket.py,
or `blender -b file.blend --python mesh_audit.py`). Prints a report and stores
it in bpy.data.texts['mesh_audit_report'] and as `result` (dict).

Detects, using evaluated (modifier-applied) triangle meshes in WORLD space:
  INTERSECT  two parts of DIFFERENT assemblies penetrate deeper than tol (default 3 mm)
  JOIN       same-assembly penetration (intentional kitbash union) - listed only with show_joins=True
  BURIED     a part is entirely inside another part (hidden geometry)
  FLOATING   a part touches nothing (nearest surface farther than --gap)
  GAP        a part's nearest neighbour is between tol and gap (almost touching)
  ASYMMETRY  a _1 / _-1 pair is not mirrored in Y
  BELOWGROUND geometry under z = 0

Bounding boxes are only used as a pre-filter; every verdict comes from
BVH triangle tests and signed point-to-surface distances.

Usage (inside Blender):
    import mesh_audit; result = mesh_audit.run(tol=0.003, gap=0.02,
                       allow=[("Lens","Bezel")], names=None)
`allow` lists pairs (prefix_a, prefix_b) whose intersection is intentional
(e.g. a lens seated in a bezel). Keep this list SHORT and justify each entry.
`names` restricts the audit to objects whose name starts with any prefix.
"""
import bpy, math, sys
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def _eval_tris(obj, dg):
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    if me is None or len(me.vertices) == 0:
        return None
    me.calc_loop_triangles()
    mw = ev.matrix_world
    verts = [mw @ v.co for v in me.vertices]
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    ev.to_mesh_clear()
    return verts, tris


class _Part:
    def __init__(self, obj, dg):
        self.name = obj.name
        r = _eval_tris(obj, dg)
        self.ok = r is not None
        if not self.ok:
            return
        self.verts, self.tris = r
        self.bvh = BVHTree.FromPolygons(self.verts, self.tris, all_triangles=True)
        xs = [v.x for v in self.verts]; ys = [v.y for v in self.verts]; zs = [v.z for v in self.verts]
        self.mn = Vector((min(xs), min(ys), min(zs))); self.mx = Vector((max(xs), max(ys), max(zs)))
        # sample points: all verts plus triangle centroids (catches thin slabs)
        self.samples = list(self.verts) + [
            (self.verts[a] + self.verts[b] + self.verts[c]) / 3 for a, b, c in self.tris]
        # closed (watertight) check: every edge must be shared by exactly two triangles
        cnt = {}
        for a, b, c in self.tris:
            for e in ((a, b), (b, c), (c, a)):
                k = (min(e), max(e)); cnt[k] = cnt.get(k, 0) + 1
        self.closed = all(v == 2 for v in cnt.values())
        self.mindim = min((self.mx - self.mn)[i] for i in range(3))
        self.material = (obj.data.materials[0].name if obj.data.materials and obj.data.materials[0] else "")

    def bbox_overlap(self, o, tol):
        return all(self.mn[i] - tol <= o.mx[i] and o.mn[i] - tol <= self.mx[i] for i in range(3))

    _RAY = Vector((0.371, 0.618, 0.693)).normalized()

    def contains(self, p):
        """Ray-parity point-in-mesh test. Only meaningful for closed meshes."""
        if not self.closed:
            return False
        n = 0; o = p.copy()
        for _ in range(128):
            loc, nor, idx, dist = self.bvh.ray_cast(o, self._RAY)
            if loc is None:
                break
            n += 1; o = loc + self._RAY * 1e-5
        return n % 2 == 1

    def inside_fraction_and_depth(self, o):
        """fraction of o's samples inside self, and max penetration depth (distance to self's surface)."""
        n_in = 0; depth = 0.0
        for p in o.samples:
            if self.contains(p):
                n_in += 1
                loc, nor, idx, dist = self.bvh.find_nearest(p)
                depth = max(depth, dist)
        return n_in / max(1, len(o.samples)), depth

    def min_dist_to(self, o):
        best = 1e9
        for p in o.samples:
            loc, nor, idx, dist = self.bvh.find_nearest(p)
            if loc is not None and dist < best:
                best = dist
        return best


def run(tol=0.003, gap=0.02, allow=(), names=None, exclude=("Ground",), groups=None, show_joins=False, verbose=True):
    """groups: list of (name_prefix, assembly) - parts in the same assembly that cross are JOINs
    (intentional kitbash unions), reported only with show_joins. Parts with no group entry are
    grouped by their first material. Crossings between different assemblies are INTERSECT."""
    dg = bpy.context.evaluated_depsgraph_get()
    objs = [o for o in bpy.data.objects if o.type == 'MESH' and not o.hide_viewport
            and not o.hide_render and o.name not in exclude
            and (names is None or any(o.name.startswith(n) for n in names))]
    parts = [p for p in (_Part(o, dg) for o in objs) if p.ok]
    byname = {p.name: p for p in parts}

    def assembly(p):
        for pre, g in (groups or ()):
            if p.name.startswith(pre):
                return g
        return "mat:" + p.material

    def allowed(a, b):
        for x, y in allow:
            if (a.startswith(x) and b.startswith(y)) or (a.startswith(y) and b.startswith(x)):
                return True
        return False

    findings = []
    touching = {p.name: False for p in parts}
    nearest = {p.name: 1e9 for p in parts}

    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            if not a.bbox_overlap(b, gap):
                continue
            pairs = a.bvh.overlap(b.bvh)
            fa, da = b.inside_fraction_and_depth(a)   # a's samples inside b
            fb, db = a.inside_fraction_and_depth(b)   # b's samples inside a
            depth = max(da, db)
            buried = (fa >= 0.98 and b.closed) or (fb >= 0.98 and a.closed)
            if pairs or buried:
                touching[a.name] = touching[b.name] = True
                nearest[a.name] = nearest[b.name] = 0.0
                if fa >= 0.98 and b.closed:
                    findings.append(("BURIED", a.name, b.name, f"{a.name} lies entirely inside {b.name}"))
                elif fb >= 0.98 and a.closed:
                    findings.append(("BURIED", b.name, a.name, f"{b.name} lies entirely inside {a.name}"))
                elif pairs and depth > tol and not allowed(a.name, b.name):
                    kind = "JOIN" if assembly(a) == assembly(b) else "INTERSECT"
                    if kind == "INTERSECT" or show_joins:
                        findings.append((kind, a.name, b.name,
                                         f"penetration {depth*1000:.0f} mm, {len(pairs)} tri pairs, "
                                         f"{fa*100:.0f}% of {a.name} inside / {fb*100:.0f}% of {b.name} inside"))
            else:
                d = min(a.min_dist_to(b), b.min_dist_to(a))
                nearest[a.name] = min(nearest[a.name], d); nearest[b.name] = min(nearest[b.name], d)
                if d <= tol:
                    touching[a.name] = touching[b.name] = True

    for p in parts:
        if not touching[p.name]:
            d = nearest[p.name]
            if d < 1e8 and d <= gap:
                findings.append(("GAP", p.name, "", f"nearest surface {d*1000:.1f} mm away (not touching)"))
            else:
                findings.append(("FLOATING", p.name, "", f"touches nothing (nearest {d*1000:.0f} mm)" if d < 1e8 else "touches nothing"))
        if p.mn.z < -tol:
            findings.append(("BELOWGROUND", p.name, "", f"min z = {p.mn.z:.3f}"))
        if p.name.endswith("_1"):
            q = byname.get(p.name[:-2] + "_-1")
            if q:
                dev = max(abs(p.mn.x - q.mn.x), abs(p.mx.x - q.mx.x), abs(p.mn.z - q.mn.z),
                          abs(p.mx.z - q.mx.z), abs(p.mn.y + q.mx.y), abs(p.mx.y + q.mn.y))
                if dev > tol:
                    findings.append(("ASYMMETRY", p.name, q.name, f"mirror deviation {dev*1000:.0f} mm"))

    order = {"INTERSECT": 0, "BURIED": 1, "FLOATING": 2, "GAP": 3, "ASYMMETRY": 4, "BELOWGROUND": 5, "JOIN": 6}
    open_parts = [p.name for p in parts if not p.closed]
    findings.sort(key=lambda f: (order[f[0]], f[1]))
    lines = [f"mesh_audit: {len(parts)} parts ({len(open_parts)} open/non-watertight: "
             f"{', '.join(open_parts[:12])}{'...' if len(open_parts) > 12 else ''}), "
             f"tol={tol*1000:.0f}mm gap={gap*1000:.0f}mm, {len(findings)} findings"]
    for kind, a, b, msg in findings:
        lines.append(f"[{kind:11s}] {a}{' <-> ' + b if b else ''}: {msg}")
    text = "\n".join(lines)
    if verbose:
        print(text)
    t = bpy.data.texts.get('mesh_audit_report') or bpy.data.texts.new('mesh_audit_report')
    t.clear(); t.write(text)
    return {"parts": len(parts), "findings": findings, "text": text}


if __name__ == "__main__":
    result = run()
