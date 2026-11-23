"""Simulation result gates: cloth penetration / poke-through / stretch / settling, rigid-body topple / move / still /
fall-through, liquid mesh presence and volume ratio, gas density presence, plus setup lint (scale, modifier order, cache
ranges, margins, voxel size). Optionally bakes everything first.

Headless / CLI (prints one line: SIM_CHECK <json>):
    blender -b scene.blend --python sim_check.py -- [--checks setup,cloth,rigid,fluid] [--bake] [--frames 1:120:1]
        [--cloth PREFIX,..] [--colliders PREFIX,..] [--tol-mm 2] [--settle-mm 1] [--stretch-max 1.5]
        [--rigid PREFIX,..] [--expect-toppled PREFIX,..] [--tilt-deg 45] [--expect-still sleeping|PREFIX,..]
        [--move-mm 5] [--rot-deg 2] [--volume-loss-pct 50] [--volume-gain-pct 150] [--volume-mode auto|conserve|rise|skip]
        [--expect-broken PREFIX,.. --broken-min 1 --break-mm 10 --break-deg 5]
        [--gas-near PREFIX,.. --near-m 0.3 --near-min-pct 50] [--liquid-in PREFIX,.. --in-min-pct 50]
        [--save out.blend]      (--settle-mm 0 = report end speed without gating on it)
    Garment example (cloth on a rigged body; no rigid/fluid noise in the report):
    blender -b garment.blend --python sim_check.py -- --checks setup,cloth --cloth SHIRT_ --colliders BODY_Proxy,BODY_Render --tol-mm 2 --settle-mm 0
        (--settle-mm 0 for shots that end while the cloth is still moving -- otherwise pass_settled fails by design)
Live (Blender:execute_blender_code): set before exec
    SIM_CHECK_OPTS = {"checks": ["cloth", "rigid"], "bake": True, "expect_toppled": "DOM_", ...}   -> `result` dict
Without SIM_CHECK_OPTS the file only defines run_checks, bake_all and the individual check helpers.

Frames are stepped one by one from start to end (so unbaked in-memory caches evaluate correctly); checks sample every
`step` frames plus the last two frames (settling = displacement between end-1 and end).
Auto-discovery: cloth = meshes with a Cloth modifier; colliders = meshes with a Collision modifier (enabled or not) plus
--colliders; rigid = objects in the rigid body world collection; fluids = Fluid DOMAIN modifiers.
Every check returns {"pass": bool|None, ...}; None = not applicable / informational.
Limitations: cloth depth is per cloth VERTEX against closed colliders (nearest-face normal sign AND ray parity must both
say inside) -- collider normals must point outward; open colliders (ground planes) count only points behind a face
within 10 cm. Poke-through = collider edges crossing cloth triangles (catches sharp corners between cloth vertices).
Liquid volume is the signed-tetrahedron volume with the reference point on the domain floor (so an open bottom adds no
error); open walls make it approximate. Volume gate is asymmetric: low-res FLIP legitimately INFLATES thin sheets (measured
up to 2.1x the flow volume at 19 mm cells), while leaks/drains LOSE volume (0.005x) -- hence loss 50 % / gain 150 %. Rigid "toppled" = world tilt of the object's local Z axis vs the start frame.
Coupled effects: Bullet exposes no "broken" flag, so a constraint counts as broken once object2's transform relative to
object1 drifts > --break-mm / --break-deg (a glued wall that topples as one block has 0 broken). --volume-mode rise =
inflow fills (last volume > first). --liquid-in = % of liquid-mesh vertices inside the container's world bounding box at
the last sampled frame (a leaking glass still "rises"). --gas-near = max density within --near-m of each object's origin
per sampled frame (grid cell centre = start_point + (i+0.5)*cell_size, domain-local, z/y/x order).
"""
import bpy, json, math, sys
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

DEFORM_TYPES = {'ARMATURE', 'MESH_DEFORM', 'SURFACE_DEFORM', 'LATTICE', 'CURVE', 'HOOK', 'SHRINKWRAP', 'SIMPLE_DEFORM',
                'CAST', 'WAVE', 'DISPLACE', 'LAPLACIANDEFORM', 'WARP', 'CORRECTIVE_SMOOTH', 'SMOOTH', 'NODES'}
GENERATE_TYPES = {'SUBSURF', 'MULTIRES', 'REMESH', 'SOLIDIFY', 'BEVEL', 'ARRAY', 'MIRROR', 'SCREW', 'SKIN', 'TRIANGULATE',
                  'DECIMATE', 'WELD', 'WIREFRAME', 'BOOLEAN'}
RAY_DIR = Vector((0.3714, 0.5571, 0.7428)).normalized()  # irrational-ish direction: avoids grazing axis-aligned edges


# ---------------------------------------------------------------- helpers
def _plist(p):
    if not p: return []
    return [x.strip() for x in (p.split(",") if isinstance(p, str) else p) if x and x.strip()]


def _match(o, prefixes):
    ps = _plist(prefixes)
    return not ps or any(o.name == p or o.name.startswith(p) for p in ps)


def _world_mesh(o, dg):
    """Evaluated world-space vertices (float64 Nx3), triangles (Mx3), edges (Kx2)."""
    ev = o.evaluated_get(dg); me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3, np.float64); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    mw = np.array(ev.matrix_world); co = co @ mw[:3, :3].T + mw[:3, 3]
    me.calc_loop_triangles()
    tri = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("vertices", tri)
    ed = np.empty(len(me.edges) * 2, np.int64); me.edges.foreach_get("vertices", ed)
    ev.to_mesh_clear()
    return co, tri.reshape(-1, 3), ed.reshape(-1, 2)


def _is_closed(tri):
    if not len(tri): return False
    e = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    return bool(np.all(counts != 1))


def _bvh(co, tri):
    return BVHTree.FromPolygons(co.tolist(), tri.tolist(), all_triangles=True, epsilon=0.0)


def _signed_volume(co, tri, ref):
    if not len(tri): return 0.0
    a, b, c = co[tri[:, 0]] - ref, co[tri[:, 1]] - ref, co[tri[:, 2]] - ref
    return float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0)


def _fps(sc):
    return sc.render.fps / (sc.render.fps_base or 1.0)


def _frames(spec, sc):
    fs, fe, st = sc.frame_start, sc.frame_end, 1
    if spec:
        parts = [p for p in str(spec).split(":")]
        if len(parts) > 0 and parts[0]: fs = int(parts[0])
        if len(parts) > 1 and parts[1]: fe = int(parts[1])
        if len(parts) > 2 and parts[2]: st = max(1, int(parts[2]))
    return fs, fe, st


def fluid_domains(sc=None):
    sc = sc or bpy.context.scene
    return [(o, m) for o in sc.objects for m in o.modifiers if m.type == 'FLUID' and m.fluid_type == 'DOMAIN']


def bake_all(free=True, scene=None):
    """Bake point caches (cloth, soft body, rigid body world, particles, dynamic paint) + every Mantaflow domain."""
    sc = scene or bpy.context.scene; info = {}
    with bpy.context.temp_override(scene=sc):
        if free: bpy.ops.ptcache.free_bake_all()
        info["ptcache"] = str(bpy.ops.ptcache.bake_all(bake=True))
    for o, m in fluid_domains(sc):
        with bpy.context.temp_override(scene=sc, object=o, active_object=o):
            if free: bpy.ops.fluid.free_all()
            info["fluid:" + o.name] = str(bpy.ops.fluid.bake_all())
    return info


# ---------------------------------------------------------------- setup lint
def check_setup(cloth=None, rigid=None):
    sc = bpy.context.scene; errors, warnings, info = [], [], {}
    sim_objs = set()
    for o in sc.objects:
        if o.type != 'MESH': continue
        types = [m.type for m in o.modifiers]
        if 'CLOTH' in types and _match(o, cloth):
            sim_objs.add(o); ci = types.index('CLOTH'); cm = o.modifiers[ci]
            late = [m.name for m in o.modifiers[ci + 1:] if m.type in DEFORM_TYPES and m.type not in ('SMOOTH', 'CORRECTIVE_SMOOTH', 'NODES')]
            if late: errors.append(f"{o.name}: deform modifier(s) {late} AFTER Cloth -- the sim ignores them; move Armature above Cloth")
            early_gen = [m.name for m in o.modifiers[:ci] if m.type in ('SUBSURF', 'MULTIRES', 'REMESH', 'SOLIDIFY')]
            if early_gen: warnings.append(f"{o.name}: {early_gen} before Cloth multiplies sim vertices; move Subdivision/Solidify after Cloth")
            if cm.point_cache.frame_end < sc.frame_end:
                warnings.append(f"{o.name}: cloth cache ends at {cm.point_cache.frame_end} < scene end {sc.frame_end} (sim freezes)")
            if cm.point_cache.frame_start > sc.frame_start:
                warnings.append(f"{o.name}: cloth cache starts at {cm.point_cache.frame_start} > scene start {sc.frame_start}")
        if 'COLLISION' in types:
            sim_objs.add(o); ci = types.index('COLLISION')
            late = [m.name for m in o.modifiers[ci + 1:] if m.type in DEFORM_TYPES]
            if late: errors.append(f"{o.name}: deform modifier(s) {late} AFTER Collision -- colliders use the stack up to "
                                   "the Collision modifier; move Collision below Armature/Shrinkwrap")
            if not o.collision.use: warnings.append(f"{o.name}: Collision modifier present but collision.use is off")
        for m in o.modifiers:
            if m.type == 'FLUID' and m.fluid_type in ('DOMAIN', 'FLOW', 'EFFECTOR'): sim_objs.add(o)
    rbw = sc.rigidbody_world
    if rbw and rbw.collection:
        info["rigid_world"] = {"substeps": rbw.substeps_per_frame, "solver_iterations": rbw.solver_iterations,
                               "cache": [rbw.point_cache.frame_start, rbw.point_cache.frame_end], "enabled": rbw.enabled}
        if rbw.point_cache.frame_end < sc.frame_end:
            warnings.append(f"rigid body world cache ends at {rbw.point_cache.frame_end} < scene end {sc.frame_end} (bodies freeze)")
        mesh_shape = []
        for o in rbw.collection.objects:
            rb = o.rigid_body
            if not rb or not _match(o, rigid): continue
            sim_objs.add(o)
            if rb.type == 'ACTIVE' and rb.collision_shape == 'MESH': mesh_shape.append(o.name)
            if rb.type == 'PASSIVE' and min(o.dimensions) < 1e-4:
                warnings.append(f"{o.name}: zero-thickness PASSIVE body ({rb.collision_shape}) -- thin bodies on it hop/tip on their own; "
                                "use a slab (scaled cube, BOX shape)")
            dims = [d for d in o.dimensions if d > 1e-9]
            if dims and rb.collision_shape in ('CONVEX_HULL', 'MESH') and rb.collision_margin > 0.1 * min(dims):
                warnings.append(f"{o.name}: collision margin {rb.collision_margin * 1000:.0f} mm > 10% of smallest dimension "
                                f"{min(dims) * 1000:.0f} mm (visible gaps / floating)")
        if mesh_shape: warnings.append(f"ACTIVE rigid bodies with MESH shape (slow, jittery; use CONVEX_HULL/BOX): {mesh_shape[:20]}")
        keyed_ignored, no_col = [], []
        has_cloth = any(m.type == 'CLOTH' for o in sc.objects for m in o.modifiers)
        for o in rbw.collection.objects:
            rb = o.rigid_body
            if not rb: continue
            ad = o.animation_data; paths = set()
            if ad and ad.action and ad.action_slot:
                try:
                    for lay in ad.action.layers:
                        for s in lay.strips:
                            cb = s.channelbag(ad.action_slot)
                            if cb: paths |= {fc.data_path for fc in cb.fcurves}
                except Exception: pass
            if rb.type == 'ACTIVE' and not rb.kinematic and paths & {"location", "rotation_euler", "rotation_quaternion"} \
                    and "rigid_body.kinematic" not in paths:
                keyed_ignored.append(o.name)
            if has_cloth and o.type == 'MESH' and not any(m.type == 'COLLISION' for m in o.modifiers): no_col.append(o.name)
        if keyed_ignored:
            warnings.append(f"ACTIVE rigid bodies with transform keys but no rigid_body.kinematic key (keys ignored once simulated; "
                            f"key kinematic on -> off to launch): {keyed_ignored[:20]}")
        if no_col:
            warnings.append(f"cloth present but rigid bodies without a Collision modifier (cloth passes through them): {no_col[:20]}")
        if rbw.constraints:
            names = {o.name for o in rbw.collection.objects}
            orph = [e.name for e in rbw.constraints.objects if e.rigid_body_constraint and
                    any(ob is None or ob.name not in names for ob in (e.rigid_body_constraint.object1, e.rigid_body_constraint.object2))]
            if orph: errors.append(f"constraints with object1/object2 missing or outside the rigid body world (ignored): {orph[:20]}")
    for o, m in fluid_domains(sc):
        ds = m.domain_settings
        # original mesh verts: o.dimensions follows the EVALUATED liquid mesh once baked (gave 2.4 mm instead of 19 mm)
        vv = [o.matrix_world @ v.co for v in o.data.vertices] if o.type == 'MESH' and len(o.data.vertices) else None
        dmax = max(max(v[i] for v in vv) - min(v[i] for v in vv) for i in range(3)) if vv else max(o.dimensions)
        cell = dmax / max(1, ds.resolution_max)
        info["fluid:" + o.name] = {"type": ds.domain_type, "resolution_max": ds.resolution_max, "cell_mm": round(cell * 1000, 1),
                                   "cache_type": ds.cache_type, "cache": [ds.cache_frame_start, ds.cache_frame_end],
                                   "baked_data": ds.has_cache_baked_data, "baked_mesh": ds.has_cache_baked_mesh}
        if ds.cache_frame_end < sc.frame_end:
            warnings.append(f"{o.name}: fluid cache ends at {ds.cache_frame_end} < scene end {sc.frame_end}")
        for fo in sc.objects:
            for fm in fo.modifiers:
                if fm.type == 'FLUID' and fm.fluid_type == 'FLOW' and fm.flow_settings.flow_source == 'MESH':
                    thin = min(fo.dimensions) if fo.dimensions else 0
                    if thin < 2 * cell and fm.flow_settings.surface_distance < cell:
                        warnings.append(f"{fo.name}: flow thinner ({thin * 1000:.0f} mm) than 2 voxels of {o.name} "
                                        f"({cell * 1000:.0f} mm) -- raise resolution or Surface Emission")
    for o in sim_objs:
        s = o.scale
        if any(abs(abs(v) - 1.0) > 1e-4 for v in s):
            warnings.append(f"{o.name}: unapplied scale {tuple(round(v, 3) for v in s)} -- apply scale before simulating")
    return {"pass": not errors, "errors": errors, "warnings": warnings, "info": info}


# ---------------------------------------------------------------- collectors
class ClothCollector:
    def __init__(self, sc, fs, fe, cloth, colliders, tol_mm, settle_mm, stretch_max):
        self.fs, self.fe, self.fps = fs, fe, _fps(sc)
        self.cloth = [o for o in sc.objects if o.type == 'MESH' and any(m.type == 'CLOTH' for m in o.modifiers) and _match(o, cloth)]
        auto = [o for o in sc.objects if o.type == 'MESH' and any(m.type == 'COLLISION' for m in o.modifiers)]
        extra = [o for o in sc.objects if o.type == 'MESH' and _plist(colliders) and _match(o, colliders)]
        self.colliders = [o for o in dict.fromkeys(auto + extra) if o not in self.cloth]
        self.tol_mm, self.settle_mm, self.stretch_max = tol_mm, settle_mm, stretch_max
        self.state = {o.name: {"frames": [], "worst": {"depth_mm": 0.0}, "rest": None, "max_stretch": 1.0,
                               "poke_max": 0, "prev": None, "last": None} for o in self.cloth}
        self._bvh_cache = {}

    def _collider(self, o, dg, f):
        co, tri, ed = _world_mesh(o, dg)
        key = (o.name, co.shape, round(float(co.sum()), 6))
        c = self._bvh_cache.get(o.name)
        if c and c["key"] == key: return c
        c = {"key": key, "co": co, "tri": tri, "ed": ed, "closed": _is_closed(tri), "bvh": _bvh(co, tri) if len(tri) else None,
             "lo": co.min(0) if len(co) else None, "hi": co.max(0) if len(co) else None}
        self._bvh_cache[o.name] = c
        return c

    @staticmethod
    def _depths(pts, c, pad=0.1):
        if c["bvh"] is None: return np.zeros(0), np.zeros(0, np.int64)
        m = np.all((pts >= c["lo"] - pad) & (pts <= c["hi"] + pad), axis=1)
        idx = np.nonzero(m)[0]; depth, where = [], []
        bvh = c["bvh"]
        for i in idx:
            p = Vector(pts[i]); loc, nrm, _, dist = bvh.find_nearest(p)
            if loc is None or dist < 1e-7: continue
            v = p - loc
            if v.dot(nrm) >= 0: continue
            if c["closed"]:
                hits, o = 0, p.copy()
                for _ in range(128):
                    hl, _, _, _ = bvh.ray_cast(o, RAY_DIR)
                    if hl is None: break
                    hits += 1; o = hl + RAY_DIR * 1e-6
                if hits % 2 == 0: continue
            else:
                if dist > pad or abs(v.normalized().dot(nrm)) < 0.99: continue
            depth.append(dist); where.append(i)
        return np.array(depth), np.array(where, np.int64)

    @staticmethod
    def _pokes(cloth_bvh, c, lo, hi, max_edges=20000):
        ed = c["ed"]; co = c["co"]
        if not len(ed) or cloth_bvh is None: return 0
        a, b = co[ed[:, 0]], co[ed[:, 1]]
        m = np.all((np.minimum(a, b) <= hi) & (np.maximum(a, b) >= lo), axis=1)
        sel = np.nonzero(m)[0][:max_edges]; n = 0
        for i in sel:
            pa, pb = Vector(a[i]), Vector(b[i]); d = pb - pa; L = d.length
            if L < 1e-9: continue
            hit = cloth_bvh.ray_cast(pa, d / L, L)
            if hit[0] is not None and (hit[0] - pa).length < L - 1e-6: n += 1
        return n

    def step(self, f, dg, sample):
        for o in self.cloth:
            st = self.state[o.name]
            if not (sample or f >= self.fe - 1 or f == self.fs): continue
            co, tri, ed = _world_mesh(o, dg)
            if f == self.fe - 1: st["prev"] = co
            if f == self.fe: st["last"] = co
            if f == self.fs:
                st["rest"] = (ed.copy(), np.linalg.norm(co[ed[:, 0]] - co[ed[:, 1]], axis=1))
            if not sample: continue
            if st["rest"] is not None and len(st["rest"][0]) == len(ed) and len(ed):
                L0 = st["rest"][1]; L = np.linalg.norm(co[ed[:, 0]] - co[ed[:, 1]], axis=1)
                ok = L0 > 1e-9
                if ok.any(): st["max_stretch"] = max(st["max_stretch"], float((L[ok] / L0[ok]).max()))
            lo, hi = co.min(0), co.max(0); cloth_bvh = _bvh(co, tri) if len(tri) else None
            fr = {"frame": f, "max_depth_mm": 0.0, "verts_inside": 0, "poke_edges": 0}
            for col in self.colliders:
                c = self._collider(col, dg, f)
                if c["lo"] is None or np.any(c["lo"] > hi + 0.1) or np.any(c["hi"] < lo - 0.1): continue
                d, w = self._depths(co, c)
                if len(d):
                    k = int(d.argmax()); dm = float(d[k]) * 1000
                    fr["verts_inside"] += int(len(d))
                    if dm > fr["max_depth_mm"]: fr["max_depth_mm"] = round(dm, 2)
                    if dm > st["worst"]["depth_mm"]:
                        st["worst"] = {"depth_mm": round(dm, 2), "frame": f, "collider": col.name, "vertex": int(w[k]),
                                       "location": [round(x, 4) for x in co[w[k]]]}
                if c["closed"]:
                    pk = self._pokes(cloth_bvh, c, lo, hi); fr["poke_edges"] += pk
                    if pk: fr.setdefault("poke_colliders", []).append(col.name)
            st["poke_max"] = max(st["poke_max"], fr["poke_edges"])
            st["frames"].append(fr)

    def finish(self):
        out, ok = {"colliders": [c.name for c in self.colliders]}, True
        if not self.cloth: return {"pass": None, "note": "no cloth objects"}
        if not self.colliders: out["note"] = "no colliders found (add a Collision modifier or pass --colliders)"
        for name, st in self.state.items():
            bad = [fr for fr in st["frames"] if fr["max_depth_mm"] > self.tol_mm or fr["poke_edges"]]
            settle = None
            if st["prev"] is not None and st["last"] is not None and st["prev"].shape == st["last"].shape:
                dmm = float(np.linalg.norm(st["last"] - st["prev"], axis=1).max()) * 1000
                settle = {"max_mm_per_frame": round(dmm, 3), "max_speed_m_s": round(dmm / 1000 * self.fps, 4),
                          "settled": (dmm <= self.settle_mm) if self.settle_mm else None}
            r = {"max_depth_mm": st["worst"]["depth_mm"], "worst": st["worst"], "frames_penetrating": len(bad),
                 "first_bad_frames": [{k: v for k, v in fr.items()} for fr in bad[:8]],
                 "max_poke_edges": st["poke_max"], "max_stretch_ratio": round(st["max_stretch"], 3), "settle": settle,
                 "sampled_frames": len(st["frames"])}
            r["pass_penetration"] = not bad
            r["pass_stretch"] = st["max_stretch"] <= self.stretch_max
            r["pass_settled"] = settle["settled"] if settle else None
            r["pass"] = r["pass_penetration"] and r["pass_stretch"] and r["pass_settled"] is not False
            ok = ok and r["pass"]; out[name] = r
        out["pass"] = ok
        out["thresholds"] = {"tol_mm": self.tol_mm, "settle_mm_per_frame": self.settle_mm, "stretch_max": self.stretch_max}
        return out


def _axis_angle_deg(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, a.normalized().dot(b.normalized())))))


class RigidCollector:
    def __init__(self, sc, fs, fe, rigid, expect_toppled, tilt_deg, expect_still, move_mm, rot_deg, settle_mm,
                 expect_broken=None, broken_min=1, break_mm=10.0, break_deg=5.0):
        rbw = sc.rigidbody_world
        objs = list(rbw.collection.objects) if rbw and rbw.collection else []
        self.active = [o for o in objs if o.rigid_body and o.rigid_body.type == 'ACTIVE' and _match(o, rigid)]
        self.passive = [o for o in objs if o.rigid_body and o.rigid_body.type == 'PASSIVE']
        # constraints: Bullet exposes no "is broken" flag -> broken = relative transform of object2 in object1's frame drifted
        cons = list(rbw.constraints.objects) if rbw and rbw.constraints else []
        self.cons = [e for e in cons if e.rigid_body_constraint and e.rigid_body_constraint.object1 and e.rigid_body_constraint.object2]
        self.expect_broken, self.broken_min, self.break_mm, self.break_deg = expect_broken, int(broken_min), break_mm, break_deg
        self.rel0, self.broke_at = {}, {}
        self.fs, self.fe = fs, fe
        self.expect_toppled, self.tilt_deg, self.move_mm, self.rot_deg, self.settle_mm = expect_toppled, tilt_deg, move_mm, rot_deg, settle_mm
        if expect_still == "sleeping":
            self.still = [o for o in self.active if o.rigid_body.use_start_deactivated]
        else:
            self.still = [o for o in self.active if _plist(expect_still) and _match(o, expect_still)]
        self.m0, self.mprev, self.m1 = {}, {}, {}
        self.floor_z = None

    def step(self, f, dg, sample):
        if f == self.fs:
            self.m0 = {o.name: o.matrix_world.copy() for o in self.active}
            if self.passive:
                zs = [(p.matrix_world @ Vector(c)).z for p in self.passive for c in p.bound_box]
                self.floor_z = min(zs)
        if f == self.fe - 1: self.mprev = {o.name: o.matrix_world.copy() for o in self.active}
        if f == self.fe: self.m1 = {o.name: o.matrix_world.copy() for o in self.active}
        if self.cons and (sample or f == self.fs or f == self.fe):
            for e in self.cons:
                k = e.rigid_body_constraint
                rel = k.object1.matrix_world.inverted() @ k.object2.matrix_world
                if f == self.fs: self.rel0[e.name] = rel; continue
                r0 = self.rel0.get(e.name)
                if r0 is None or e.name in self.broke_at: continue
                dmm = (rel.to_translation() - r0.to_translation()).length * 1000
                ang = math.degrees(r0.to_quaternion().rotation_difference(rel.to_quaternion()).angle); ang = min(ang, 360 - ang)
                if dmm > self.break_mm or ang > self.break_deg: self.broke_at[e.name] = (f, round(dmm, 1), round(ang, 1))

    def _constraints(self):
        if not self.cons: return None, True
        broken = sorted(self.broke_at)
        rigid_names = {o.name for o in self.active} | {o.name for o in self.passive}
        orphans = [e.name for e in self.cons if e.rigid_body_constraint.object1.name not in rigid_names
                   or e.rigid_body_constraint.object2.name not in rigid_names]
        out = {"total": len(self.cons), "breakable": sum(1 for e in self.cons if e.rigid_body_constraint.use_breaking),
               "enabled": sum(1 for e in self.cons if e.rigid_body_constraint.enabled), "broken": len(broken),
               "broken_names": broken[:60], "first_break_frame": min((v[0] for v in self.broke_at.values()), default=None),
               "separated_unbreakable": [n for n in broken if not bpy.data.objects[n].rigid_body_constraint.use_breaking][:20],
               "thresholds": {"break_mm": self.break_mm, "break_deg": self.break_deg}}
        if orphans: out["not_in_world"] = orphans[:20]
        ok = True
        if _plist(self.expect_broken):
            exp = [e.name for e in self.cons if _match(e, self.expect_broken)]
            nb = sum(1 for n in exp if n in self.broke_at)
            out["expect_broken"] = {"matched": len(exp), "broken": nb, "min": self.broken_min}
            ok = nb >= self.broken_min
        return out, ok

    def finish(self):
        if not self.active: return {"pass": None, "note": "no ACTIVE rigid bodies in the rigid body world"}
        per, moved, toppled, fell, moving = {}, [], [], [], []
        for o in self.active:
            M0, M1 = self.m0.get(o.name), self.m1.get(o.name)
            if M0 is None or M1 is None: continue
            t0, t1 = M0.to_translation(), M1.to_translation()
            q0, q1 = M0.to_quaternion(), M1.to_quaternion()
            rot = math.degrees(q0.rotation_difference(q1).angle)
            rot = min(rot, 360 - rot)
            tilt = _axis_angle_deg(M0.col[2].to_3d(), M1.col[2].to_3d())
            dmm = (t1 - t0).length * 1000
            r = {"move_mm": round(dmm, 1), "rot_deg": round(rot, 1), "tilt_deg": round(tilt, 1)}
            if o.name in self.mprev:
                r["last_frame_mm"] = round((t1 - self.mprev[o.name].to_translation()).length * 1000, 2)
                if r["last_frame_mm"] > self.settle_mm: moving.append(o.name)
            if dmm > self.move_mm or rot > self.rot_deg: moved.append(o.name)
            if tilt > self.tilt_deg: toppled.append(o.name)
            if self.floor_z is not None and t1.z < self.floor_z - 0.05: fell.append(o.name)
            per[o.name] = r
        out = {"active": len(self.active), "moved": len(moved), "toppled": len(toppled), "still_moving_at_end": moving[:40],
               "fell_through": fell, "objects": dict(list(per.items())[:200]),
               "thresholds": {"tilt_deg": self.tilt_deg, "move_mm": self.move_mm, "rot_deg": self.rot_deg}}
        ok = not fell
        if _plist(self.expect_toppled):
            exp = sorted([o.name for o in self.active if _match(o, self.expect_toppled)])
            standing = [n for n in exp if n not in toppled]
            out["expect_toppled"] = {"expected": len(exp), "standing": standing[:40],
                                     "first_standing": standing[0] if standing else None,
                                     "toppled_in_order": next((i for i, n in enumerate(exp) if n in standing), len(exp))}
            ok = ok and not standing
        if self.still:
            woke = [o.name for o in self.still if o.name in moved]
            out["expect_still"] = {"expected": len(self.still), "moved": woke[:40]}
            ok = ok and not woke
        cons, cons_ok = self._constraints()
        if cons is not None: out["constraints"] = cons
        ok = ok and cons_ok
        out["pass"] = ok
        return out


class FluidCollector:
    def __init__(self, sc, fs, fe, loss_pct, gain_pct, volume_mode, gas_near=None, near_m=0.3, near_min_pct=50.0,
                 liquid_in=None, in_min_pct=50.0):
        self.domains = fluid_domains(sc); self.fs, self.fe = fs, fe
        self.loss, self.gain, self.mode = loss_pct, gain_pct, volume_mode
        self.near = [o for o in sc.objects if _plist(gas_near) and _match(o, gas_near)]
        self.near_m, self.near_min_pct = near_m, near_min_pct
        self.inside = [o for o in sc.objects if o.type == 'MESH' and _plist(liquid_in) and _match(o, liquid_in)]
        self.in_min_pct = in_min_pct
        self.data = {o.name: {"frames": [], "ref": None, "flow_volume": None} for o, _ in self.domains}
        flows = [(fo, fm) for fo in sc.objects for fm in fo.modifiers if fm.type == 'FLUID' and fm.fluid_type == 'FLOW']
        self.liquid_flows = [(fo, fm) for fo, fm in flows if fm.flow_settings.flow_type in ('LIQUID', 'BOTH')]
        self.non_conserving = [fo.name for fo, fm in self.liquid_flows if fm.flow_settings.flow_behavior != 'GEOMETRY']
        self.non_conserving += [fo.name for fo in sc.objects for fm in fo.modifiers
                                if fm.type == 'FLUID' and fm.fluid_type == 'EFFECTOR' and getattr(fm.effector_settings, "use_effector", False)
                                and fm.effector_settings.effector_type == 'GUIDE' and False]

    def step(self, f, dg, sample):
        if not sample: return
        for o, m in self.domains:
            ds = m.domain_settings; d = self.data[o.name]
            if d["ref"] is None:
                # original mesh verts, NOT o.bound_box (that follows the evaluated liquid mesh)
                bb = np.array([list(o.matrix_world @ v.co) for v in o.data.vertices]) if len(o.data.vertices) else \
                    np.array([list(o.matrix_world @ Vector(c)) for c in o.bound_box])
                d["ref"] = np.array([bb[:, 0].mean(), bb[:, 1].mean(), bb[:, 2].min()])
                d["box_l"] = float(np.prod(bb.max(0) - bb.min(0))) * 1000
            fr = {"frame": f}
            if ds.domain_type == 'LIQUID':
                if f == self.fs and self.liquid_flows:
                    vol = 0.0
                    for fo, fm in self.liquid_flows:
                        if fm.flow_settings.flow_behavior == 'GEOMETRY':
                            co, tri, _ = _world_mesh(fo, dg); vol += abs(_signed_volume(co, tri, co.mean(0)))
                    d["flow_volume"] = vol
                co, tri, _ = _world_mesh(o, dg)
                fr["verts"], fr["tris"] = int(len(co)), int(len(tri))
                fr["volume_l"] = round(abs(_signed_volume(co, tri, d["ref"])) * 1000, 3) if len(tri) else 0.0
                # unbaked/empty cache: the evaluated domain is just its own box mesh -> no liquid
                if d["box_l"] and abs(fr["volume_l"] - d["box_l"]) <= 0.02 * d["box_l"]:
                    fr["domain_box"] = True; fr["tris"] = 0; fr["volume_l"] = 0.0
                if self.inside and fr["tris"]:
                    for c in self.inside:  # share of liquid-mesh vertices inside the container's world bounding box
                        cc = np.array([list(c.matrix_world @ v.co) for v in c.data.vertices]); lo, hi = cc.min(0), cc.max(0)
                        fr.setdefault("in_pct", {})[c.name] = round(float(np.all((co >= lo) & (co <= hi), axis=1).mean() * 100), 1)
            else:
                try:  # runtime grids exist only on the EVALUATED modifier (original returns length 0)
                    eds = o.evaluated_get(dg).modifiers[m.name].domain_settings
                    g = np.array(eds.density_grid[:], np.float32) if len(eds.density_grid) else np.zeros(0)
                    fr["density_max"] = round(float(g.max()), 4) if g.size else 0.0
                    fr["occupied_pct"] = round(float((g > 0.01).mean() * 100), 2) if g.size else 0.0
                    res = list(eds.domain_resolution)
                    if self.near and g.size and g.size == res[0] * res[1] * res[2]:
                        # cell (x,y,z) centre, domain-local = start_point + (i+0.5)*cell_size; grid is z,y,x ordered
                        # (adaptive domains shrink domain_resolution per frame but keep this mapping; verified 5.2)
                        G = g.reshape(res[2], res[1], res[0]); sp = np.array(eds.start_point); cs = np.array(eds.cell_size)
                        imw = np.array(o.matrix_world.inverted())
                        for n in self.near:
                            p = n.evaluated_get(dg).matrix_world.translation
                            pl = imw[:3, :3] @ np.array(p) + imw[:3, 3]
                            rad = self.near_m / np.maximum(cs, 1e-9)
                            lo = np.maximum(np.floor((pl - sp) / cs - 0.5 - rad).astype(int), 0)
                            hi = np.minimum(np.ceil((pl - sp) / cs - 0.5 + rad).astype(int) + 1, res)
                            sub = G[lo[2]:hi[2], lo[1]:hi[1], lo[0]:hi[0]] if np.all(hi > lo) else np.zeros(0)
                            fr.setdefault("near", {})[n.name] = round(float(sub.max()), 4) if sub.size else 0.0
                except Exception as e:
                    fr["density_error"] = str(e)
            d["frames"].append(fr)

    def finish(self):
        if not self.domains: return {"pass": None, "note": "no fluid domains"}
        out, ok = {}, True
        for o, m in self.domains:
            ds = m.domain_settings; d = self.data[o.name]; fr = d["frames"]
            r = {"type": ds.domain_type, "baked_data": ds.has_cache_baked_data, "baked_mesh": ds.has_cache_baked_mesh,
                 "cache_type": ds.cache_type, "resolution_max": ds.resolution_max}
            if ds.domain_type == 'LIQUID':
                missing = [x["frame"] for x in fr if x["tris"] == 0]
                r["mesh_missing_frames"] = missing[:40]; r["frames_sampled"] = len(fr)
                r["pass_mesh"] = not missing and ds.use_mesh
                if not ds.use_mesh: r["note_mesh"] = "domain Mesh option is off -- no liquid surface is generated"
                if not ds.has_cache_baked_data and ds.cache_type != 'REPLAY':
                    r["note_bake"] = f"cache_type {ds.cache_type} but nothing baked -- run fluid.bake_all (or --bake)"
                vols = [x["volume_l"] for x in fr if x["tris"]]
                mode = self.mode
                if mode == "auto": mode = "skip" if self.non_conserving else "conserve"
                if not ds.use_mesh: mode = "skip"
                r["volume_mode"] = mode
                if vols:
                    v0 = vols[0]; ref_l = d["flow_volume"] * 1000 if d["flow_volume"] else None
                    base = ref_l or v0
                    ratios = [round(v / base, 3) for v in vols] if base else []
                    r.update({"volume_first_l": v0, "volume_last_l": vols[-1], "flow_volume_l": round(ref_l, 3) if ref_l else None,
                              "volume_ratio_min": min(ratios) if ratios else None, "volume_ratio_max": max(ratios) if ratios else None,
                              "volume_ratio_last": ratios[-1] if ratios else None,
                              "volume_series_l": [(x["frame"], x["volume_l"]) for x in fr][:60]})
                    if mode == "conserve" and ratios:
                        lo_ok = min(ratios) >= 1 - self.loss / 100.0; hi_ok = max(ratios) <= 1 + self.gain / 100.0
                        r["volume_limits"] = [round(1 - self.loss / 100.0, 3), round(1 + self.gain / 100.0, 3)]
                        r["volume_lost"] = not lo_ok; r["volume_inflated"] = not hi_ok
                        r["pass_volume"] = lo_ok and hi_ok
                    elif mode == "rise":  # inflow fills: last sampled volume must exceed the first non-empty one
                        r["pass_volume"] = vols[-1] > vols[0] and vols[-1] > 0
                    else:
                        r["pass_volume"] = None
                        if self.non_conserving: r["note_volume"] = f"inflow/outflow present {self.non_conserving[:5]}: volume not conserved by design"
                else:
                    r["pass_volume"] = False if mode in ("conserve", "rise") else None
                if self.inside:
                    last_in = next((x["in_pct"] for x in reversed(fr) if x.get("in_pct")), {})
                    r["in_pct_series"] = [(x["frame"], x.get("in_pct")) for x in fr][:60]
                    r["in_pct_last"] = last_in
                    r["pass_inside"] = bool(last_in) and all(v >= self.in_min_pct for v in last_in.values())
                r["pass"] = bool(r["pass_mesh"]) and r["pass_volume"] is not False and r.get("pass_inside") is not False
            else:
                dens = [x.get("density_max", 0) for x in fr]
                r["density_max_series"] = [(x["frame"], x.get("density_max"), x.get("occupied_pct")) for x in fr][:60]
                r["pass"] = any(v > 0 for v in dens)
                if not r["pass"]: r["note"] = "no density at any sampled frame (unbaked, flow not emitting, or wrong flow type)"
                if self.near:
                    later = fr[1:] or fr  # skip the first sample: emission starts after frame 1
                    r["near"] = {}
                    for n in self.near:
                        hit = [x for x in later if x.get("near", {}).get(n.name, 0) > 0.01]
                        pct = round(100.0 * len(hit) / max(1, len(later)), 1)
                        r["near"][n.name] = {"frames_with_density_pct": pct, "radius_m": self.near_m,
                                             "series": [(x["frame"], x.get("near", {}).get(n.name)) for x in fr][:60]}
                        r["pass"] = r["pass"] and pct >= self.near_min_pct
            ok = ok and r["pass"]; out[o.name] = r
        out["pass"] = ok
        return out


# ---------------------------------------------------------------- driver
def run_checks(checks=None, bake=False, frames=None, cloth=None, colliders=None, tol_mm=2.0, settle_mm=1.0,
               stretch_max=1.5, rigid=None, expect_toppled=None, tilt_deg=45.0, expect_still=None, move_mm=5.0,
               rot_deg=2.0, volume_loss_pct=50.0, volume_gain_pct=150.0, volume_mode="auto", save=None,
               expect_broken=None, broken_min=1, break_mm=10.0, break_deg=5.0, gas_near=None, near_m=0.3,
               near_min_pct=50.0, liquid_in=None, in_min_pct=50.0):
    sc = bpy.context.scene
    checks = checks or ["setup", "cloth", "rigid", "fluid"]
    if isinstance(checks, str): checks = _plist(checks)
    out = {"blender": bpy.app.version_string}
    fs, fe, st = _frames(frames, sc)
    out["frames"] = [fs, fe, st]
    if "setup" in checks:
        try: out["setup"] = check_setup(cloth, rigid)
        except Exception as e: out["setup"] = {"pass": False, "error": f"{type(e).__name__}: {e}"}
    if bake:
        try: out["bake"] = bake_all()
        except Exception as e: out["bake"] = {"error": f"{type(e).__name__}: {e}"}
    cols = {}
    if "cloth" in checks: cols["cloth"] = ClothCollector(sc, fs, fe, cloth, colliders, tol_mm, settle_mm, stretch_max)
    if "rigid" in checks: cols["rigid"] = RigidCollector(sc, fs, fe, rigid, expect_toppled, tilt_deg, expect_still, move_mm, rot_deg,
                                                         settle_mm, expect_broken, broken_min, break_mm, break_deg)
    if "fluid" in checks: cols["fluid"] = FluidCollector(sc, fs, fe, volume_loss_pct, volume_gain_pct, volume_mode, gas_near, near_m,
                                                         near_min_pct, liquid_in, in_min_pct)
    orig = sc.frame_current
    if cols:
        for f in range(fs, fe + 1):
            sc.frame_set(f)
            sample = (f - fs) % st == 0 or f == fe
            dg = bpy.context.evaluated_depsgraph_get()
            for k, c in cols.items():
                try: c.step(f, dg, sample)
                except Exception as e: out.setdefault("errors", []).append(f"{k}@{f}: {type(e).__name__}: {e}")
        for k, c in cols.items():
            try: out[k] = c.finish()
            except Exception as e: out[k] = {"pass": False, "error": f"{type(e).__name__}: {e}"}
    sc.frame_set(orig)
    if save: bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(save), copy=True)
    out["summary"] = {c: out[c].get("pass") for c in checks if c in out}
    return out


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="sim_check.py")
    p.add_argument("--checks", default="setup,cloth,rigid,fluid"); p.add_argument("--bake", action="store_true")
    p.add_argument("--frames"); p.add_argument("--cloth"); p.add_argument("--colliders")
    p.add_argument("--tol-mm", type=float, default=2.0); p.add_argument("--settle-mm", type=float, default=1.0)
    p.add_argument("--stretch-max", type=float, default=1.5); p.add_argument("--rigid")
    p.add_argument("--expect-toppled"); p.add_argument("--tilt-deg", type=float, default=45.0)
    p.add_argument("--expect-still"); p.add_argument("--move-mm", type=float, default=5.0); p.add_argument("--rot-deg", type=float, default=2.0)
    p.add_argument("--volume-loss-pct", type=float, default=50.0); p.add_argument("--volume-gain-pct", type=float, default=150.0)
    p.add_argument("--volume-mode", default="auto", choices=["auto", "conserve", "rise", "skip"])
    p.add_argument("--save")
    p.add_argument("--expect-broken"); p.add_argument("--broken-min", type=int, default=1)
    p.add_argument("--break-mm", type=float, default=10.0); p.add_argument("--break-deg", type=float, default=5.0)
    p.add_argument("--gas-near"); p.add_argument("--near-m", type=float, default=0.3); p.add_argument("--near-min-pct", type=float, default=50.0)
    p.add_argument("--liquid-in"); p.add_argument("--in-min-pct", type=float, default=50.0)
    a = p.parse_args(argv)
    return run_checks(a.checks, a.bake, a.frames, a.cloth, a.colliders, a.tol_mm, a.settle_mm, a.stretch_max, a.rigid,
                      a.expect_toppled, a.tilt_deg, a.expect_still, a.move_mm, a.rot_deg, a.volume_loss_pct,
                      a.volume_gain_pct, a.volume_mode, a.save, a.expect_broken, a.broken_min, a.break_mm, a.break_deg,
                      a.gas_near, a.near_m, a.near_min_pct, a.liquid_in, a.in_min_pct)


if "SIM_CHECK_OPTS" in globals():
    result = run_checks(**SIM_CHECK_OPTS); print(json.dumps(result["summary"]))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("SIM_CHECK " + json.dumps(result, default=str))
else:
    result = {"defined": ["run_checks", "bake_all", "check_setup", "fluid_domains", "ClothCollector", "RigidCollector", "FluidCollector"]}
