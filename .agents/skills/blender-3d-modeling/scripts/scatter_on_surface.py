"""Parametric, non-destructive Geometry Nodes scatter (grass, rocks, trees, debris, scales/feathers) on a mesh surface.

Headless / CLI (prints one line: SCATTER_ON_SURFACE <json>):
    blender -b scene.blend --python scatter_on_surface.py -- --target Terrain --collection Rocks \
        [--name GN_Scatter --min-distance 0.3 --density-max 20 --density-attr grass_mask --slope-max 30 \
         --slope-falloff 10 --height-min 0 --height-max 40 --scale-min 0.8 --scale-max 1.2 --tilt 5 --align 0.3 \
         --seed 3 --realize --max-warn 200000 --proxy BOUNDS --save out.blend]
Live (Blender:execute_blender_code): set before exec
    SCATTER_OPTS = {"target": "Terrain", "collection": "Rocks", "min_distance": 0.3, "seed": 3, ...}  # kwargs below
    -> `result` dict. Without SCATTER_OPTS the file only defines scatter_on_surface / set_viewport_proxy / instance_transforms.

Every parameter is a modifier input (tweak later in the modifier panel, no re-run). Distribution runs in WORLD space
(surface transformed by Self Object's matrix, instances transformed back), so Min Distance (m), Density Max (/m²),
slope and height limits are world-correct even with unapplied object transforms.
Density Factor = named float attribute (painted vertex group; empty/missing name -> 1) x slope mask x height mask.
Slope mask uses FACE normals: 1 below Slope Max, smooth ramp to 0 at Slope Max + Falloff (degrees).
Rotation: Z aligned to mix(world up, surface normal, Align to Normal) -> random yaw about own Z -> random tilt.
Heavy scenes: set_viewport_proxy(collection, 'BOUNDS'), raise Min Distance, or keep Realize off.
"""
import bpy, math, sys, json
from mathutils import Vector

SOCKETS = [  # (name, socket_type, default, min, max, description)
    ("Collection", "NodeSocketCollection", None, None, None, "Objects to instance (children picked randomly)"),
    ("Min Distance", "NodeSocketFloat", 0.5, 0.0, None, "Poisson minimum spacing between points, world metres"),
    ("Density Max", "NodeSocketFloat", 10.0, 0.0, None, "Max points per square metre (Poisson upper bound)"),
    ("Density Attribute", "NodeSocketString", "", None, None, "Float attribute / vertex group used as density factor; empty = 1"),
    ("Slope Max", "NodeSocketFloat", 35.0, 0.0, 180.0, "Degrees from world up where density starts to fall off"),
    ("Slope Falloff", "NodeSocketFloat", 10.0, 0.0, 180.0, "Degrees over which density ramps from 1 to 0"),
    ("Use Height Limits", "NodeSocketBool", False, None, None, "Restrict to world Z between Height Min/Max"),
    ("Height Min", "NodeSocketFloat", -1000.0, None, None, "World Z minimum"),
    ("Height Max", "NodeSocketFloat", 1000.0, None, None, "World Z maximum"),
    ("Scale Min", "NodeSocketFloat", 0.8, 0.0, None, "Uniform random scale minimum"),
    ("Scale Max", "NodeSocketFloat", 1.2, 0.0, None, "Uniform random scale maximum"),
    ("Random Tilt", "NodeSocketFloat", 5.0, 0.0, 90.0, "Max random tilt, degrees (about local X and Y)"),
    ("Align to Normal", "NodeSocketFloat", 0.3, 0.0, 1.0, "0 = instance Z is world up, 1 = surface normal"),
    ("Seed", "NodeSocketInt", 0, None, None, "Random seed for distribution, pick, yaw, tilt, scale"),
    ("Realize Instances", "NodeSocketBool", False, None, None, "Convert instances to real mesh (heavy!)"),
]


def set_input(mod, identifier, value):
    """Set a Geometry Nodes modifier input. 5.2+: mod.properties.inputs.<id>.value (mod[id] raises; inputs[id]=v is a
    silent no-op idprop). <=5.1: mod[id] = value. Re-fetch every time: cached input pointers dangle after interface edits."""
    props = getattr(mod, "properties", None)
    if props is not None and hasattr(props, "inputs"):
        getattr(props.inputs, identifier).value = value
    else:
        mod[identifier] = value


def _avail(s):
    return not s.is_unavailable if hasattr(s, "is_unavailable") else getattr(s, "enabled", True)


def _sock(sockets, name, stype=None):
    """Version-tolerant socket lookup by name (+type): prefers available sockets, 4.x keeps hidden duplicates."""
    cands = [s for s in sockets if s.name == name and (stype is None or s.type == stype)]
    for s in cands:
        if _avail(s): return s
    if cands: return cands[0]
    raise KeyError(f"socket {name!r} type={stype} not in {[(s.name, s.type) for s in sockets]}")


def _build_group(name, legacy=False):
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    it, nodes, links, notes = ng.interface, ng.nodes, ng.links, []
    it.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    it.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    for n, st, d, lo, hi, desc in SOCKETS:
        s = it.new_socket(n, in_out='INPUT', socket_type=st); s.description = desc
        if d is not None: s.default_value = d
        if lo is not None: s.min_value = lo
        if hi is not None: s.max_value = hi
    frames = {}

    def N(kind, x, y, frame=None, label=None, **props):
        try:
            nd = nodes.new(kind)
        except RuntimeError:
            return None
        if frame:
            if frame not in frames:
                fr = nodes.new('NodeFrame'); fr.label = fr.name = frame; fr.label_size = 16; frames[frame] = fr
            nd.parent = frames[frame]  # frame stays at origin -> relative == absolute location on 4.x and 5.x
        nd.location = (x * 200, -y * 170)
        if label: nd.label = label
        for k, v in props.items(): setattr(nd, k, v)
        return nd

    def L(a, b): links.new(a, b)
    def I(nd, name, t=None): return _sock(nd.inputs, name, t)
    def O(nd, name, t=None): return _sock(nd.outputs, name, t)
    def val(nd, name, v, t=None): I(nd, name, t).default_value = v
    def math_node(op, x, y, fr, a=None, b=None, label=None, clamp=False):
        m = N('ShaderNodeMath', x, y, fr, label, operation=op, use_clamp=clamp)
        for sock, v in zip(m.inputs, (a, b)):
            if v is None: continue
            if isinstance(v, bpy.types.NodeSocket): L(v, sock)
            else: sock.default_value = v
        return m

    gi = N('NodeGroupInput', -6, 4, None, "Inputs"); go = N('NodeGroupOutput', 26, 0)
    G = lambda n: gi.outputs[n]

    # ---- world space in/out ----
    selfo = N('GeometryNodeSelfObject', -4, -1, "World Space")
    oinfo = N('GeometryNodeObjectInfo', -3, -1, "World Space", transform_space='ORIGINAL'); L(O(selfo, "Self Object"), I(oinfo, "Object"))
    tw = N('GeometryNodeTransform', -1, 0, "World Space", "To World"); L(G("Geometry"), I(tw, "Geometry"))
    tb_src = None  # instances geometry to bring back
    matrix_mode = legacy is not True and "Transform" in [s.name for s in tw.inputs]
    if matrix_mode:
        I(tw, "Mode").default_value = 'Matrix'; L(O(oinfo, "Transform"), I(tw, "Transform"))
    else:  # TRS fallback (T*R*S forward; inverse = S^-1 * R^-1 * T^-1 as three transforms)
        notes.append("transform: TRS fallback (no matrix mode)")
        for sname in ("Translation", "Rotation", "Scale"): L(O(oinfo, {"Translation": "Location"}.get(sname, sname)), I(tw, sname))

    # ---- masks (evaluated on the world-space surface) ----
    F = "Density Masks"
    nrm = N('GeometryNodeInputNormal', -4, 3, F)
    face = N('GeometryNodeFieldOnDomain', -3, 3, F, "Face Normal", domain='FACE', data_type='FLOAT_VECTOR')
    L(O(nrm, "Normal"), I(face, "Value", 'VECTOR'))
    sxyz = N('ShaderNodeSeparateXYZ', -2, 3, F); L(O(face, "Value", 'VECTOR'), I(sxyz, "Vector"))
    zc = math_node('MINIMUM', -1, 3, F, O(sxyz, "Z"), 1.0, "clamp 0..1", clamp=True)
    ang = math_node('ARCCOSINE', 0, 3, F, zc.outputs[0], None, "slope rad")
    deg = math_node('DEGREES', 1, 3, F, ang.outputs[0], None, "slope deg")
    fo = math_node('MAXIMUM', 0, 4, F, G("Slope Falloff"), 0.001)
    smax_end = math_node('ADD', 1, 4, F, G("Slope Max"), fo.outputs[0], "slope 0 at")
    slope = N('ShaderNodeMapRange', 2, 3, F, "Slope Mask", data_type='FLOAT', clamp=True)
    L(deg.outputs[0], I(slope, "Value", 'VALUE')); L(G("Slope Max"), I(slope, "From Min", 'VALUE'))
    L(smax_end.outputs[0], I(slope, "From Max", 'VALUE')); val(slope, "To Min", 1.0, 'VALUE'); val(slope, "To Max", 0.0, 'VALUE')

    pos = N('GeometryNodeInputPosition', -2, 5.5, F); pz = N('ShaderNodeSeparateXYZ', -1, 5.5, F); L(O(pos, "Position"), I(pz, "Vector"))
    ge = N('FunctionNodeCompare', 0, 5.5, F, "Z >= min", data_type='FLOAT', operation='GREATER_EQUAL')
    le = N('FunctionNodeCompare', 0, 6.5, F, "Z <= max", data_type='FLOAT', operation='LESS_EQUAL')
    for c, h in ((ge, "Height Min"), (le, "Height Max")): L(O(pz, "Z"), I(c, "A", 'VALUE')); L(G(h), I(c, "B", 'VALUE'))
    band = N('FunctionNodeBooleanMath', 1, 6, F, operation='AND'); L(O(ge, "Result"), band.inputs[0]); L(O(le, "Result"), band.inputs[1])
    hsw = N('GeometryNodeSwitch', 2, 6, F, "Height Mask", input_type='FLOAT'); L(G("Use Height Limits"), I(hsw, "Switch"))
    val(hsw, "False", 1.0); L(O(band, "Boolean"), I(hsw, "True"))

    na = N('GeometryNodeInputNamedAttribute', 0, 1.5, F, "Density Attribute", data_type='FLOAT'); L(G("Density Attribute"), I(na, "Name"))
    asw = N('GeometryNodeSwitch', 1, 1.5, F, "Attr or 1", input_type='FLOAT'); L(O(na, "Exists"), I(asw, "Switch"))
    val(asw, "False", 1.0); L(O(na, "Attribute", 'VALUE'), I(asw, "True"))
    m1 = math_node('MULTIPLY', 3, 2, F, O(asw, "Output"), O(slope, "Result", 'VALUE'))
    dens = math_node('MULTIPLY', 4, 3, F, m1.outputs[0], O(hsw, "Output"), "Density Factor")

    # ---- distribute ----
    D = "Distribute"
    dist = N('GeometryNodeDistributePointsOnFaces', 6, 0, D, "Poisson Scatter", distribute_method='POISSON')
    L(O(tw, "Geometry"), I(dist, "Mesh")); L(G("Min Distance"), I(dist, "Distance Min")); L(G("Density Max"), I(dist, "Density Max"))
    L(dens.outputs[0], I(dist, "Density Factor")); L(G("Seed"), I(dist, "Seed"))
    seeds = [math_node('ADD', 6, 2 + k * 0.8, D, G("Seed"), float(k), f"seed+{k}") for k in range(1, 5)]

    # ---- instance picking ----
    P = "Instances"
    ci = N('GeometryNodeCollectionInfo', 8, -2.5, P, transform_space='ORIGINAL'); L(G("Collection"), I(ci, "Collection"))
    val(ci, "Separate Children", True); val(ci, "Reset Children", True)
    dsz = N('GeometryNodeAttributeDomainSize', 9, -1.5, P, component='INSTANCES'); L(O(ci, "Instances"), I(dsz, "Geometry"))
    last = math_node('SUBTRACT', 10, -1.5, P, O(dsz, "Instance Count"), 1.0, "count-1")
    pick = N('FunctionNodeRandomValue', 11, -1.5, P, "Random Pick", data_type='INT')
    val(pick, "Min", 0, 'INT'); L(last.outputs[0], I(pick, "Max", 'INT')); L(seeds[0].outputs[0], I(pick, "Seed"))

    # ---- rotation ----
    R = "Rotation"
    up = N('FunctionNodeInputVector', 8, 1, R, "World Up", vector=(0.0, 0.0, 1.0))
    mix = N('ShaderNodeMix', 9, 1, R, "Up <-> Normal", data_type='VECTOR', factor_mode='UNIFORM')
    L(G("Align to Normal"), I(mix, "Factor", 'VALUE')); L(up.outputs[0], I(mix, "A", 'VECTOR')); L(O(dist, "Normal"), I(mix, "B", 'VECTOR'))
    nz = N('ShaderNodeVectorMath', 10, 1, R, operation='NORMALIZE'); L(O(mix, "Result", 'VECTOR'), nz.inputs[0])
    yaw = N('FunctionNodeRandomValue', 10, 2.2, R, "Random Yaw", data_type='FLOAT')
    val(yaw, "Min", 0.0, 'VALUE'); val(yaw, "Max", 2 * math.pi, 'VALUE'); L(seeds[1].outputs[0], I(yaw, "Seed"))
    trad = math_node('RADIANS', 8, 3.4, R, G("Random Tilt"), None, "tilt rad")
    tneg = math_node('MULTIPLY', 9, 3.4, R, trad.outputs[0], -1.0)
    cmin = N('ShaderNodeCombineXYZ', 10, 3.4, R); cmax = N('ShaderNodeCombineXYZ', 10, 4.4, R)
    for c, src in ((cmin, tneg), (cmax, trad)): L(src.outputs[0], I(c, "X")); L(src.outputs[0], I(c, "Y"))
    tilt = N('FunctionNodeRandomValue', 11, 3.4, R, "Random Tilt", data_type='FLOAT_VECTOR')
    L(cmin.outputs[0], I(tilt, "Min", 'VECTOR')); L(cmax.outputs[0], I(tilt, "Max", 'VECTOR')); L(seeds[2].outputs[0], I(tilt, "Seed"))

    new_rot = not legacy and all(hasattr(bpy.types, t) for t in ("FunctionNodeAlignRotationToVector", "FunctionNodeRotateRotation"))
    if new_rot:
        align = N('FunctionNodeAlignRotationToVector', 11, 1, R, "Align Z", axis='Z'); L(nz.outputs[0], I(align, "Vector"))
        axa = N('FunctionNodeAxisAngleToRotation', 12, 2.2, R, "Yaw"); val(axa, "Axis", (0, 0, 1)); L(yaw.outputs[0], I(axa, "Angle"))
        r1 = N('FunctionNodeRotateRotation', 13, 1, R, "Yaw (local)", rotation_space='LOCAL')
        L(O(align, "Rotation"), I(r1, "Rotation")); L(axa.outputs[0], I(r1, "Rotate By"))
        e2r = N('FunctionNodeEulerToRotation', 12, 3.4, R); L(O(tilt, "Value", 'VECTOR'), I(e2r, "Euler"))
        r2 = N('FunctionNodeRotateRotation', 14, 1, R, "Tilt (local)", rotation_space='LOCAL')
        L(O(r1, "Rotation"), I(r2, "Rotation")); L(e2r.outputs[0], I(r2, "Rotate By")); rot_out = O(r2, "Rotation")
    else:  # 4.1-style Euler chain
        notes.append("rotation: legacy Euler nodes (AlignEulerToVector / RotateEuler)")
        ae = N('FunctionNodeAlignEulerToVector', 11, 1, R, "Align Z (euler)", axis='Z'); L(nz.outputs[0], I(ae, "Vector"))
        r1 = N('FunctionNodeRotateEuler', 13, 1, R, "Yaw (local)")
        if hasattr(r1, "rotation_type"): r1.rotation_type = 'AXIS_ANGLE'
        else: r1.type = 'AXIS_ANGLE'
        r1.space = 'LOCAL'
        L(O(ae, "Rotation"), I(r1, "Rotation", 'VECTOR')); val(r1, "Axis", (0, 0, 1)); L(yaw.outputs[0], I(r1, "Angle"))
        r2 = N('FunctionNodeRotateEuler', 14, 1, R, "Tilt (local)")
        if hasattr(r2, "rotation_type"): r2.rotation_type = 'EULER'
        else: r2.type = 'EULER'
        r2.space = 'LOCAL'
        L(O(r1, "Rotation", 'VECTOR'), I(r2, "Rotation", 'VECTOR')); L(O(tilt, "Value", 'VECTOR'), I(r2, "Rotate By", 'VECTOR'))
        e2r = N('FunctionNodeEulerToRotation', 15, 1, R); L(O(r2, "Rotation", 'VECTOR'), I(e2r, "Euler")); rot_out = e2r.outputs[0]

    # ---- scale + instance ----
    sc = N('FunctionNodeRandomValue', 13, -1.5, P, "Random Scale", data_type='FLOAT')
    L(G("Scale Min"), I(sc, "Min", 'VALUE')); L(G("Scale Max"), I(sc, "Max", 'VALUE')); L(seeds[3].outputs[0], I(sc, "Seed"))
    iop = N('GeometryNodeInstanceOnPoints', 16, 0, P, "Instance on Points")
    L(O(dist, "Points"), I(iop, "Points")); L(O(ci, "Instances"), I(iop, "Instance")); val(iop, "Pick Instance", True)
    L(O(hsw, "Output"), I(iop, "Selection"))  # same height field on points = exact cut (corner mask blurs across big faces)
    L(O(pick, "Value", 'INT'), I(iop, "Instance Index")); L(rot_out, I(iop, "Rotation")); L(O(sc, "Value", 'VALUE'), I(iop, "Scale"))

    # ---- back to object space, realize, join ----
    W = "World Space"
    if matrix_mode:
        inv = N('FunctionNodeInvertMatrix', 16, -3, W); L(O(oinfo, "Transform"), I(inv, "Matrix"))
        tb = N('GeometryNodeTransform', 18, 0, W, "To Object"); I(tb, "Mode").default_value = 'Matrix'
        L(O(iop, "Instances"), I(tb, "Geometry")); L(O(inv, "Matrix"), I(tb, "Transform")); back = O(tb, "Geometry")
    else:
        t1 = N('GeometryNodeTransform', 17, 0, W, "-Location"); L(O(iop, "Instances"), I(t1, "Geometry"))
        neg = N('ShaderNodeVectorMath', 16, -3, W, operation='SCALE'); L(O(oinfo, "Location"), neg.inputs[0]); I(neg, "Scale").default_value = -1
        L(neg.outputs[0], I(t1, "Translation"))
        irot = N('FunctionNodeInvertRotation', 17, -3, W); L(O(oinfo, "Rotation"), irot.inputs[0])
        t2 = N('GeometryNodeTransform', 18, 0, W, "-Rotation"); L(O(t1, "Geometry"), I(t2, "Geometry")); L(irot.outputs[0], I(t2, "Rotation"))
        isc = N('ShaderNodeVectorMath', 18, -3, W, operation='DIVIDE'); isc.inputs[0].default_value = (1, 1, 1); L(O(oinfo, "Scale"), isc.inputs[1])
        t3 = N('GeometryNodeTransform', 19, 0, W, "1/Scale"); L(O(t2, "Geometry"), I(t3, "Geometry")); L(isc.outputs[0], I(t3, "Scale"))
        back = O(t3, "Geometry")
    Q = "Output"
    real = N('GeometryNodeRealizeInstances', 20, 1, Q); L(back, I(real, "Geometry"))
    rsw = N('GeometryNodeSwitch', 22, 0, Q, "Realize?", input_type='GEOMETRY'); L(G("Realize Instances"), I(rsw, "Switch"))
    L(back, I(rsw, "False")); L(O(real, "Geometry"), I(rsw, "True"))
    join = N('GeometryNodeJoinGeometry', 24, 0, Q, "Surface + Scatter")
    L(G("Geometry"), I(join, "Geometry")); L(O(rsw, "Output"), I(join, "Geometry")); L(O(join, "Geometry"), go.inputs[0])
    return ng, notes


def instance_transforms(target, depsgraph=None):
    """[(source_object_name, world Matrix)] for every instance the target's modifiers emit (evaluated depsgraph)."""
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    out = []
    for inst in dg.object_instances:
        if inst.is_instance and inst.parent and inst.parent.original == target:
            out.append((inst.object.original.name, inst.matrix_world.copy()))
    return out


def set_viewport_proxy(collection, display='BOUNDS'):
    """Viewport-only speedup: display every object of the (instance source) collection as BOUNDS/WIRE/SOLID/TEXTURED."""
    coll = bpy.data.collections[collection] if isinstance(collection, str) else collection
    objs = list(coll.all_objects)
    for o in objs: o.display_type = display
    return {"collection": coll.name, "objects": len(objs), "display": display}


def _mask_stats(obj, dattr, smax, sfall, hrange):
    """Area-weighted mean of each density mask on the ORIGINAL (pre-modifier) mesh, world space."""
    me, mw = obj.data, obj.matrix_world
    wv = [mw @ v.co for v in me.vertices]
    weights = None
    if dattr:
        vg = obj.vertex_groups.get(dattr)
        if vg:
            weights = [0.0] * len(me.vertices)
            for v in me.vertices:
                for g in v.groups:
                    if g.group == vg.index: weights[v.index] = g.weight
        elif dattr in me.attributes and me.attributes[dattr].domain == 'POINT' and me.attributes[dattr].data_type == 'FLOAT':
            weights = [d.value for d in me.attributes[dattr].data]
    tot = s_sum = h_sum = a_sum = c_sum = 0.0
    step = max(1, len(me.polygons) // 200000)
    for p in me.polygons[::step] if step > 1 else me.polygons:
        vs = [wv[i] for i in p.vertices]
        n = Vector()
        for i in range(1, len(vs) - 1): n += (vs[i] - vs[0]).cross(vs[i + 1] - vs[0])
        area = n.length / 2
        if area <= 0: continue
        z = max(-1.0, min(1.0, n.normalized().z))
        a = math.degrees(math.acos(z))
        s = 1.0 if a <= smax else max(0.0, 1 - (a - smax) / max(sfall, 1e-3))
        cz = sum(v.z for v in vs) / len(vs)
        h = 1.0 if hrange is None or hrange[0] <= cz <= hrange[1] else 0.0
        w = sum(weights[i] for i in p.vertices) / len(vs) if weights else 1.0
        tot += area; s_sum += area * s; h_sum += area * h; a_sum += area * w; c_sum += area * s * h * w
    t = tot or 1.0
    return {"surface_area_m2": round(tot * step, 3), "slope": round(s_sum / t, 4), "height": round(h_sum / t, 4),
            "attribute": round(a_sum / t, 4), "combined": round(c_sum / t, 4), "attribute_found": weights is not None}


def scatter_on_surface(target, collection, *, name='GN_Scatter', min_distance=0.5, density_max=10.0, density_attribute=None,
                       slope_max_deg=35.0, slope_falloff_deg=10.0, height_range=None, scale_range=(0.8, 1.2),
                       random_tilt_deg=5.0, align_to_normal=0.3, seed=0, realize=False, max_instances_warn=200000, _legacy=False):
    obj = bpy.data.objects[target] if isinstance(target, str) else target
    coll = bpy.data.collections[collection] if isinstance(collection, str) else collection
    if obj.type != 'MESH': raise TypeError(f"{obj.name} is {obj.type}, need MESH")
    warnings = []
    old = obj.modifiers.get(name)
    if old: obj.modifiers.remove(old)
    ng, notes = _build_group(name, legacy=_legacy)
    mod = obj.modifiers.new(name, 'NODES'); mod.node_group = ng
    ids = {i.name: i.identifier for i in ng.interface.items_tree if i.item_type == 'SOCKET' and i.in_out == 'INPUT'}
    values = {"Collection": coll, "Min Distance": float(min_distance), "Density Max": float(density_max),
              "Density Attribute": density_attribute or "", "Slope Max": float(slope_max_deg), "Slope Falloff": float(slope_falloff_deg),
              "Use Height Limits": height_range is not None, "Height Min": float(height_range[0]) if height_range else -1000.0,
              "Height Max": float(height_range[1]) if height_range else 1000.0, "Scale Min": float(scale_range[0]),
              "Scale Max": float(scale_range[1]), "Random Tilt": float(random_tilt_deg), "Align to Normal": float(align_to_normal),
              "Seed": int(seed), "Realize Instances": False}
    for k, v in values.items(): set_input(mod, ids[k], v)
    obj.update_tag(); bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()

    tr = instance_transforms(obj, dg)
    per_src, pts, scales = {}, [], []
    for src, m in tr:
        per_src[src] = per_src.get(src, 0) + 1; pts.append(m.translation); scales.append(sum(m.to_scale()) / 3)
    count = len(tr)
    result = {"target": obj.name, "modifier": mod.name, "node_group": ng.name, "collection": coll.name,
              "blender": bpy.app.version_string, "input_identifiers": ids, "instance_count": count, "per_source": per_src,
              "bounds_min": [round(min(p[i] for p in pts), 3) for i in range(3)] if pts else None,
              "bounds_max": [round(max(p[i] for p in pts), 3) for i in range(3)] if pts else None,
              "scale_range": [round(min(scales), 3), round(max(scales), 3)] if scales else None, "graph_notes": notes}
    ms = _mask_stats(obj, density_attribute, slope_max_deg, slope_falloff_deg, height_range)
    result["mask_area_fraction"] = ms
    result["mask_note"] = "area-weighted mean factor per mask on the pre-modifier mesh; 1 - combined ~ fraction of Density Max rejected"
    if density_attribute and not ms["attribute_found"]:
        warnings.append(f"density attribute '{density_attribute}' not found as vertex group / point float attribute on the original mesh -> GN uses factor 1 (or an attribute created by earlier modifiers)")
    if list(obj.modifiers).index(mod) > 0:
        warnings.append("modifiers before the scatter change the surface; mask_area_fraction is computed on the pre-modifier mesh")
    if any(abs(s - 1) > 1e-6 for s in obj.scale):
        warnings.append(f"target has unapplied scale {tuple(round(s, 4) for s in obj.scale)}: the graph distributes in world space so spacing stays correct, but apply scale (Ctrl+A) for predictable other modifiers/exports")
    if count == 0:
        warnings.append("0 instances: check collection has objects, Density Max/Min Distance, slope/height limits, density attribute")
    if count > max_instances_warn:
        warnings.append(f"{count} instances > {max_instances_warn}: use set_viewport_proxy(collection, 'BOUNDS'), raise Min Distance, lower Density Max, keep Realize off")
    if coll.name in {c.name for c in obj.users_collection} and obj.name in coll.objects:
        warnings.append("target is inside the instance collection (recursive scatter)")
    if realize:
        set_input(mod, ids["Realize Instances"], True); obj.update_tag(); bpy.context.view_layer.update()
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()); me = ev.to_mesh()
        result["realized_mesh"] = {"verts": len(me.vertices), "faces": len(me.polygons)}; ev.to_mesh_clear()
    result["warnings"] = warnings
    return result


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="scatter_on_surface.py")
    p.add_argument("--target", required=True); p.add_argument("--collection", required=True); p.add_argument("--name", default="GN_Scatter")
    p.add_argument("--min-distance", type=float, default=0.5); p.add_argument("--density-max", type=float, default=10.0)
    p.add_argument("--density-attr"); p.add_argument("--slope-max", type=float, default=35.0); p.add_argument("--slope-falloff", type=float, default=10.0)
    p.add_argument("--height-min", type=float); p.add_argument("--height-max", type=float)
    p.add_argument("--scale-min", type=float, default=0.8); p.add_argument("--scale-max", type=float, default=1.2)
    p.add_argument("--tilt", type=float, default=5.0); p.add_argument("--align", type=float, default=0.3); p.add_argument("--seed", type=int, default=0)
    p.add_argument("--realize", action="store_true"); p.add_argument("--max-warn", type=int, default=200000)
    p.add_argument("--proxy", choices=["BOUNDS", "WIRE", "SOLID", "TEXTURED"]); p.add_argument("--save")
    a = p.parse_args(argv)
    hr = None
    if a.height_min is not None or a.height_max is not None:
        hr = (a.height_min if a.height_min is not None else -1e4, a.height_max if a.height_max is not None else 1e4)
    res = scatter_on_surface(a.target, a.collection, name=a.name, min_distance=a.min_distance, density_max=a.density_max,
                             density_attribute=a.density_attr, slope_max_deg=a.slope_max, slope_falloff_deg=a.slope_falloff,
                             height_range=hr, scale_range=(a.scale_min, a.scale_max), random_tilt_deg=a.tilt, align_to_normal=a.align,
                             seed=a.seed, realize=a.realize, max_instances_warn=a.max_warn)
    if a.proxy: res["proxy"] = set_viewport_proxy(a.collection, a.proxy)
    if a.save: bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(a.save)); res["saved"] = a.save
    return res


if "SCATTER_OPTS" in globals():  # live exec
    _o = dict(SCATTER_OPTS); _proxy = _o.pop("proxy", None)
    result = scatter_on_surface(_o.pop("target"), _o.pop("collection"), **_o)
    if _proxy: result["proxy"] = set_viewport_proxy(result["collection"], _proxy)
    print(json.dumps({k: v for k, v in result.items() if k != "input_identifiers"}))
elif __name__ == "__main__" and "--" in sys.argv and "--target" in sys.argv[sys.argv.index("--") + 1:]:
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print("SCATTER_ON_SURFACE " + json.dumps(result))
else:
    result = {"defined": ["scatter_on_surface", "set_viewport_proxy", "instance_transforms"]}
