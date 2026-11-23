"""Anime face shadow map (SDF threshold map) + hair angel-ring highlight: build the shader setups and MEASURE them.

Face: a grayscale threshold map in face-UV space (texel value = light-angle parameter at which that texel enters shadow,
authored for light on the +U side of the map). Drivers read the light's +Z axis and the head's U/forward axes from
matrix_world COLUMNS (simple expressions `m` / `-m`, no Python auto-exec). Shader: dLU = L.U, dLF = L.F; flip U when
dLU < 0; t = (1 - cos a) / 2 (COS, the common game convention) or a / pi (ANGLE), a = atan2(|dLU|, dLF);
lit = map(u', v) > t; face mask selects face vs outside color. Engine-agnostic (EEVEE, Cycles, Workbench-free).
Ring: node group NPR_AngelRing: band = |h + ViewShift * Facing - Center| < Width/2 (+ Softness), cut at silhouettes by
Layer Weight Facing, optional noise breakup; h = hair UV (V along the locks) or object-space Z normalized to the bbox.

Headless / CLI (prints one line `FACE_SDF {json}`):
    blender -b char.blend --python face_sdf.py -- --face-mesh Head --light Sun --head Rig --bone head \
        [--uv-map FaceUV --map SYNTHETIC|path.png|path.exr --u-axis X --forward-axis Z --mapping COS|ANGLE \
         --mask-attr face_mask --assign-faces MASK|ALL|NONE --material MAT_Face \
         --lit-color R G B --shadow-color R G B --outside-color R G B \
         --check NUMERIC|BLENDER_EEVEE|CYCLES|"" --steps 24 --measure-only --scratch DIR]
    blender -b char.blend --python face_sdf.py -- --hair-mesh Hair --ring-coord UV|OBJECT_Z [--uv-map HairUV \
         --ring-center 0.7 --ring-width 0.06 --check BLENDER_EEVEE --measure-only --scratch DIR] [--save out.blend]
    Axes are head-LOCAL: --u-axis points toward face-UV U=1, --forward-axis is where the face looks. Object facing -Y:
    u X, forward -Y. Vertical head bone (tail up) with roll 0: u X, forward Z (bone local Z = world -Y; other rolls
    rotate this).
    --check "" skips every check (build only). PowerShell 5.1 drops a bare "" argument: write --check '""' there.
    --scratch DIR: folder for the temporary check renders (default: the system temp dir; files are deleted again).
    --assign-faces (default MASK) points polygons of --face-mesh at the face material slot: MASK = polygons whose
    corners' --mask-attr value (float/int/bool/colour attribute on POINT, CORNER or FACE domain, or a vertex group)
    averages > 0.5 (without a usable --mask-attr MASK degrades to ALL, as the shader then treats the whole mesh as
    face); ALL = every polygon; NONE = leave material_index alone (slot only appended, as before). The build dict
    reports faces_assigned / faces_total / material_index / assign_faces (effective mode). Only matters when the mesh
    already has other slots (skin/body at 0, face appended at 1): a slot-less mesh gets the face material at index 0,
    which every polygon uses anyway. Without --material the ACTIVE material is rebuilt in place (no new slot).
    --lit-color / --shadow-color / --outside-color: linear RGB (alpha 1) for the FSDF_FaceColor and FSDF_Masked Mix
    nodes; defaults lit (1, 0.86, 0.8), shadow (0.72, 0.52, 0.52), outside (0.9, 0.75, 0.7).
Live (Blender MCP execute): set before exec
    FACE_SDF_OPTS = {"face_mesh": "Head", "light": "Sun", "head": "Rig", "bone": "head", "check": "NUMERIC",
                     "mask_attr": "face_mask", "assign_faces": "MASK", "lit_color": (1, 0.9, 0.85)}
    FACE_SDF_OPTS = {"hair_mesh": "Hair", "ring_coord": "UV", "uv_map": "HairUV", "check": "BLENDER_EEVEE"}
    -> `result` dict (unknown keys are listed in result["ignored_opts"]). Without FACE_SDF_OPTS only functions are
    defined (see `result["defined"]`).

Report
- face (orbit_check): light orbited around the head in --steps azimuths (0 = front). frac = lit share of masked face
  (area-weighted corners for NUMERIC; visible pixels for a render). Defects: drivers_invalid, not_monotonic (lit share
  must not grow as the light moves front -> back, tol 0.02), front_not_lit (< 0.9), back_not_shadowed (> 0.1),
  wrong_side (lit centroid on the side away from the light), asymmetric (|frac(a) - frac(-a)| > 0.05).
- ring (ring_check): renders 3 views; ring pixels' object Z -> median, p10-p90 width, column coverage. Defects:
  ring_missing, ring_drifts (median spread across views > 4 % of hair height), ring_too_wide (> 15 %),
  ring_broken (coverage < 0.5).
Limitations: one directional light; light straight above/below the head (|dLU|,|dLF| ~ 0) gives t = 0.5; the map must
be authored for light on the +U side with the same mapping (COS/ANGLE); the face UV must be a symmetric front
projection (u = 0.5 on the nose line) or the flip mismatches. NUMERIC mirrors the node math on the evaluated mesh and
reads the driver-written socket values; renders verify the nodes. Cast shadows (hair on face) are not handled.
"""
import bpy, json, math, sys
import numpy as np
from mathutils import Matrix, Vector

AXES = {'X': (0, 1), '-X': (0, -1), 'Y': (1, 1), '-Y': (1, -1), 'Z': (2, 1), '-Z': (2, -1)}
PFX = "FSDF_"


def _obj(x):
    if x is None or isinstance(x, bpy.types.ID): return x
    o = bpy.data.objects.get(x)
    if o is None: raise KeyError(f"object {x!r} not found")
    return o


def _sock(coll, ident):
    for s in coll:
        if s.identifier == ident: return s
    raise KeyError(ident)


def _rgba(c):
    """(r, g, b) or (r, g, b, a) -> 4-tuple of floats (alpha defaults to 1)."""
    c = tuple(float(v) for v in c)
    if len(c) == 3: return c + (1.0,)
    if len(c) == 4: return c
    raise ValueError(f"colour needs 3 or 4 components, got {len(c)}")


# ---------------------------------------------------------------- threshold maps
def synthetic_threshold_map(size=256, nose=0.06, mapping="COS"):
    """Face-like threshold map for tests: shadow edge sweeps from the +U side (u=1 lit longest) with a nose-shaped
    bulge around v=0.45. Returns float32 HxW in [0,1]; same geometric boundary for COS and ANGLE."""
    u = (np.arange(size) + 0.5) / size
    uu, vv = np.meshgrid(u, u)
    p = uu + nose * np.exp(-((vv - 0.45) / 0.12) ** 2) * np.exp(-((uu - 0.5) / 0.15) ** 2)
    p = np.clip(0.02 + 0.96 * p, 0.0, 1.0)          # angle fraction a/pi at which the texel enters shadow
    return (p if mapping == "ANGLE" else (1.0 - np.cos(p * math.pi)) * 0.5).astype(np.float32)


def _boundary(mask, inside):
    """Pixels of `mask == inside` with a 4-neighbour of the other kind."""
    m = mask if inside else ~mask
    o = ~m
    b = np.zeros_like(m)
    b[1:, :] |= o[:-1, :]; b[:-1, :] |= o[1:, :]; b[:, 1:] |= o[:, :-1]; b[:, :-1] |= o[:, 1:]
    return np.argwhere(m & b).astype(np.float32)


def _nearest_dist(points, targets, chunk=4096):
    if len(targets) == 0: return np.full(len(points), 1e9, np.float32)
    out = np.empty(len(points), np.float32)
    for i in range(0, len(points), chunk):
        d = points[i:i + chunk, None, :] - targets[None, :, :]
        out[i:i + chunk] = np.sqrt((d * d).sum(-1)).min(1)
    return out


def masks_to_threshold(masks, params):
    """SDF interpolation of hand-drawn binary LIT masks (HxW bool, light on +U side) at increasing threshold params
    t_k in [0,1] (mapping units). Texels lit in mask k but not k+1 get t_k + (t_k+1 - t_k) * dA / (dA + dB).
    Returns (float32 map, violations = texels lit in k+1 but not in k)."""
    masks = [np.asarray(m, bool) for m in masks]
    out = np.where(masks[0], 1.0, params[0]).astype(np.float32)
    viol = 0
    for k in range(len(masks) - 1):
        A, B = masks[k], masks[k + 1]
        viol += int((B & ~A).sum())
        sel = A & ~B
        pts = np.argwhere(sel).astype(np.float32)
        if len(pts) == 0: continue
        dA = _nearest_dist(pts, _boundary(A, False))       # to first unlit pixel of A
        dB = _nearest_dist(pts, _boundary(B, True))        # to nearest lit pixel of B
        t = params[k] + (params[k + 1] - params[k]) * dA / np.maximum(dA + dB, 1e-6)
        out[sel] = t
    return np.clip(out, 0, 1), viol


def ensure_image(name, arr=None, path=None):
    """Create/replace a packed float image from HxW array, or load path. Non-Color."""
    if path:
        img = bpy.data.images.load(bpy.path.abspath(path), check_existing=True)
    else:
        h, w = arr.shape
        img = bpy.data.images.get(name)
        if img is None or tuple(img.size) != (w, h) or not img.is_float:
            if img: bpy.data.images.remove(img)
            img = bpy.data.images.new(name, w, h, alpha=False, float_buffer=True)
        rgba = np.ones((h, w, 4), np.float32); rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = arr
        img.pixels.foreach_set(rgba.ravel()); img.update(); img.pack()
    img.colorspace_settings.name = "Non-Color"
    return img


def _image_array(img):
    w, h = img.size
    px = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[..., 0]


# ---------------------------------------------------------------- face setup
def axes_source(head, bone=None):
    """Object whose matrix_world carries the head axes. Bone -> Empty FSDFAXES_<bone> with Copy Transforms."""
    head = _obj(head)
    if not bone: return head
    name = f"FSDFAXES_{head.name}_{bone}"
    e = bpy.data.objects.get(name)
    if e is None:
        e = bpy.data.objects.new(name, None); e.empty_display_size = 0.05
        (head.users_collection[0] if head.users_collection else bpy.context.scene.collection).objects.link(e)
    c = e.constraints.get("FSDF_CopyBone") or e.constraints.new('COPY_TRANSFORMS')
    c.name = "FSDF_CopyBone"; c.target = head; c.subtarget = bone
    e.hide_render = True
    return e


def _clear_prefixed(nt):
    if nt.animation_data:
        for fc in list(nt.animation_data.drivers):
            if fc.data_path.startswith(f'nodes["{PFX}'): nt.animation_data.drivers.remove(fc)
    for n in list(nt.nodes):
        if n.name.startswith(PFX): nt.nodes.remove(n)


def _node(nt, typ, name, loc, **props):
    n = nt.nodes.new(typ); n.name = n.label = PFX + name; n.location = loc
    for k, v in props.items(): setattr(n, k, v)
    return n


def _vec_driver(nt, name, loc, target, col, sign):
    cx = _node(nt, "ShaderNodeCombineXYZ", name, loc)
    for i, ax in enumerate("XYZ"):
        d = cx.inputs[ax].driver_add("default_value").driver
        d.type = 'SCRIPTED'; d.expression = "m" if sign > 0 else "-m"
        v = d.variables[0] if len(d.variables) else d.variables.new()
        v.name = "m"; v.type = 'SINGLE_PROP'
        v.targets[0].id_type = 'OBJECT'; v.targets[0].id = target
        v.targets[0].data_path = f"matrix_world[{col}][{i}]"   # column first
    return cx


def _math(nt, name, op, loc, a=None, b=None):
    n = _node(nt, "ShaderNodeMath", name, loc, operation=op)
    for i, x in enumerate((a, b)):
        if x is None: continue
        if isinstance(x, (int, float)): n.inputs[i].default_value = x
        else: nt.links.new(x, n.inputs[i])
    return n


def build_face_sdf(material, light, head, bone=None, uv_map="FaceUV", image=None, map_path=None, u_axis="X",
                   forward_axis="-Y", mapping="COS", mask_attr=None, lit_color=(1.0, 0.86, 0.8, 1),
                   shadow_color=(0.72, 0.52, 0.52, 1), outside_color=(0.9, 0.75, 0.7, 1), map_size=256):
    """(Re)build FSDF_* nodes + drivers in `material`; output Emission to the Material Output."""
    mat = material if isinstance(material, bpy.types.Material) else bpy.data.materials.get(material) \
        or bpy.data.materials.new(material)
    light, src = _obj(light), axes_source(head, bone)
    nt = mat.node_tree; _clear_prefixed(nt)
    if image is None:
        image = ensure_image(f"T_FaceSDF_{mat.name}", path=map_path) if map_path else \
            ensure_image(f"T_FaceSDF_{mat.name}", synthetic_threshold_map(map_size, mapping=mapping))
    uc, us = AXES[u_axis]; fc, fs = AXES[forward_axis]
    X = -1600
    L = _vec_driver(nt, "Light", (X, 300), light, 2, 1)
    U = _vec_driver(nt, "HeadU", (X, 100), src, uc, us)
    F = _vec_driver(nt, "HeadF", (X, -100), src, fc, fs)
    dLU = _node(nt, "ShaderNodeVectorMath", "dLU", (X + 200, 200), operation='DOT_PRODUCT')
    nt.links.new(L.outputs[0], dLU.inputs[0]); nt.links.new(U.outputs[0], dLU.inputs[1])
    dLF = _node(nt, "ShaderNodeVectorMath", "dLF", (X + 200, 0), operation='DOT_PRODUCT')
    nt.links.new(L.outputs[0], dLF.inputs[0]); nt.links.new(F.outputs[0], dLF.inputs[1])
    flip = _math(nt, "Flip", 'LESS_THAN', (X + 400, 300), dLU.outputs["Value"], 0.0)
    absu = _math(nt, "AbsLU", 'ABSOLUTE', (X + 400, 150), dLU.outputs["Value"])
    if mapping == "ANGLE":
        ang = _math(nt, "Angle", 'ARCTAN2', (X + 600, 100), absu.outputs[0], dLF.outputs["Value"])
        thr = _math(nt, "Threshold", 'DIVIDE', (X + 800, 100), ang.outputs[0], math.pi)
    else:
        c2 = _node(nt, "ShaderNodeCombineXYZ", "L2D", (X + 600, 100))
        nt.links.new(absu.outputs[0], c2.inputs[0]); nt.links.new(dLF.outputs["Value"], c2.inputs[1])
        nrm = _node(nt, "ShaderNodeVectorMath", "L2DNorm", (X + 750, 100), operation='NORMALIZE')
        nt.links.new(c2.outputs[0], nrm.inputs[0])
        sep2 = _node(nt, "ShaderNodeSeparateXYZ", "CosA", (X + 900, 100)); nt.links.new(nrm.outputs[0], sep2.inputs[0])
        one_m = _math(nt, "OneMinusCos", 'SUBTRACT', (X + 1050, 100), 1.0, sep2.outputs["Y"])
        thr = _math(nt, "Threshold", 'MULTIPLY', (X + 1200, 100), one_m.outputs[0], 0.5)
    uvn = _node(nt, "ShaderNodeUVMap", "UV", (X + 400, -300), uv_map=uv_map)
    sep = _node(nt, "ShaderNodeSeparateXYZ", "UVSep", (X + 600, -300)); nt.links.new(uvn.outputs[0], sep.inputs[0])
    two_u = _math(nt, "TwoU", 'MULTIPLY', (X + 800, -250), sep.outputs["X"], 2.0)
    one_m2 = _math(nt, "OneMinus2U", 'SUBTRACT', (X + 950, -250), 1.0, two_u.outputs[0])
    fl = _math(nt, "FlipTerm", 'MULTIPLY', (X + 1100, -250), one_m2.outputs[0], flip.outputs[0])
    uf = _math(nt, "UFlipped", 'ADD', (X + 1250, -250), sep.outputs["X"], fl.outputs[0])
    cuv = _node(nt, "ShaderNodeCombineXYZ", "UVOut", (X + 1400, -300))
    nt.links.new(uf.outputs[0], cuv.inputs[0]); nt.links.new(sep.outputs["Y"], cuv.inputs[1])
    tex = _node(nt, "ShaderNodeTexImage", "Map", (X + 1550, -300), image=image, interpolation='Linear',
                extension='EXTEND')
    nt.links.new(cuv.outputs[0], tex.inputs[0])
    lit = _math(nt, "Lit", 'GREATER_THAN', (X + 1850, 0), tex.outputs["Color"], thr.outputs[0])
    mix = _node(nt, "ShaderNodeMix", "FaceColor", (X + 2050, 0), data_type='RGBA')
    nt.links.new(lit.outputs[0], _sock(mix.inputs, "Factor_Float"))
    _sock(mix.inputs, "A_Color").default_value = shadow_color; _sock(mix.inputs, "B_Color").default_value = lit_color
    out_mix = _node(nt, "ShaderNodeMix", "Masked", (X + 2250, 0), data_type='RGBA')
    _sock(out_mix.inputs, "A_Color").default_value = outside_color
    nt.links.new(_sock(mix.outputs, "Result_Color"), _sock(out_mix.inputs, "B_Color"))
    if mask_attr:
        at = _node(nt, "ShaderNodeAttribute", "Mask", (X + 2050, -250), attribute_type='GEOMETRY',
                   attribute_name=mask_attr)
        nt.links.new(at.outputs["Fac"], _sock(out_mix.inputs, "Factor_Float"))
    else:
        _sock(out_mix.inputs, "Factor_Float").default_value = 1.0
    em = _node(nt, "ShaderNodeEmission", "Emission", (X + 2450, 0))
    nt.links.new(_sock(out_mix.outputs, "Result_Color"), em.inputs["Color"])
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None) \
        or nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    drv = [{"path": f.data_path, "valid": f.driver.is_valid, "simple": f.driver.is_simple_expression}
           for f in nt.animation_data.drivers if f.data_path.startswith(f'nodes["{PFX}')]
    return {"material": mat.name, "image": image.name, "axes_source": src.name, "mapping": mapping,
            "drivers": len(drv), "drivers_all_simple": all(d["simple"] for d in drv),
            "drivers_all_valid": all(d["valid"] for d in drv)}


def _mask_values(obj, me, name):
    """Values of mask attribute `name` (float/int/bool -> value, colour -> mean RGB, vector -> X) with their domain,
    or a vertex group's weights (POINT, 0 for unassigned). Returns (None, None) when nothing usable exists."""
    a = me.attributes.get(name) if name else None
    if a is not None and a.domain in ('POINT', 'CORNER', 'FACE'):
        n = len(a.data)
        if a.data_type in ('FLOAT_COLOR', 'BYTE_COLOR'):
            v = np.empty(n * 4, np.float32); a.data.foreach_get("color", v); vals = v.reshape(-1, 4)[:, :3].mean(1)
        elif a.data_type in ('FLOAT_VECTOR', 'FLOAT2'):
            k = 3 if a.data_type == 'FLOAT_VECTOR' else 2
            v = np.empty(n * k, np.float32); a.data.foreach_get("vector", v); vals = v.reshape(-1, k)[:, 0]
        else:
            try:
                vals = np.empty(n, np.float32); a.data.foreach_get("value", vals)
            except (TypeError, RuntimeError):
                vals = np.array([float(d.value) for d in a.data], np.float32)
        return vals.astype(np.float64), a.domain
    vg = obj.vertex_groups.get(name) if name else None
    if vg is not None:
        vals = np.zeros(len(me.vertices)); gi = vg.index
        for v in me.vertices:
            for g in v.groups:
                if g.group == gi: vals[v.index] = g.weight
        return vals, 'POINT'
    return None, None


def assign_face_slot(obj, material, mode="MASK", mask_attr=None):
    """Point polygons of `obj` at the slot holding `material`. MASK: polygons whose corners' `mask_attr` averages
    > 0.5 (degrades to ALL without a usable attribute); ALL: every polygon; NONE: untouched. Returns counts."""
    obj = _obj(obj); me = obj.data
    mat = material if isinstance(material, bpy.types.Material) else bpy.data.materials.get(material)
    slot = next((i for i, s in enumerate(obj.material_slots) if s.material == mat), None)
    n = len(me.polygons)
    out = {"assign_faces": mode, "material_index": slot, "faces_total": n, "faces_assigned": 0}
    if mode == "NONE" or slot is None or n == 0: return out
    sel = np.ones(n, bool)
    if mode == "MASK":
        vals, dom = _mask_values(obj, me, mask_attr)
        if vals is None:
            out["assign_faces"] = "ALL"; out["mask_missing"] = mask_attr
        else:
            if dom == 'FACE':
                per_face = vals
            else:
                ls = np.empty(n, np.int64); me.polygons.foreach_get("loop_start", ls)
                lt = np.empty(n, np.int64); me.polygons.foreach_get("loop_total", lt)
                if dom == 'POINT':
                    lv = np.empty(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", lv); vals = vals[lv]
                per_face = np.add.reduceat(vals, ls) / np.maximum(lt, 1)
            sel = per_face > 0.5
    idx = np.empty(n, np.int32); me.polygons.foreach_get("material_index", idx)
    idx[sel] = slot; me.polygons.foreach_set("material_index", idx); me.update()
    out["faces_assigned"] = int(sel.sum())
    return out


# ---------------------------------------------------------------- angel ring
RING_INPUTS = [("Height", 'NodeSocketFloat', 0.5), ("Center", 'NodeSocketFloat', 0.7),
               ("Width", 'NodeSocketFloat', 0.06), ("Softness", 'NodeSocketFloat', 0.0),
               ("View Shift", 'NodeSocketFloat', 0.03), ("Facing Cutoff", 'NodeSocketFloat', 0.8),
               ("Breakup", 'NodeSocketFloat', 0.0), ("Breakup Scale", 'NodeSocketFloat', 12.0),
               ("Base Color", 'NodeSocketColor', (0.12, 0.08, 0.1, 1)),
               ("Ring Color", 'NodeSocketColor', (0.9, 0.8, 0.85, 1)), ("Intensity", 'NodeSocketFloat', 1.0)]


def angel_ring_group(name="NPR_AngelRing"):
    ng = bpy.data.node_groups.get(name) or bpy.data.node_groups.new(name, 'ShaderNodeTree')
    ng.nodes.clear(); ng.interface.clear()
    for n, t, dv in RING_INPUTS:
        ng.interface.new_socket(name=n, in_out='INPUT', socket_type=t).default_value = dv
    ng.interface.new_socket(name="Fac", in_out='OUTPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket(name="Color", in_out='OUTPUT', socket_type='NodeSocketColor')
    N, Lk = ng.nodes, ng.links
    gi = N.new("NodeGroupInput"); gi.location = (-1200, 0)
    go = N.new("NodeGroupOutput"); go.location = (800, 0)

    def m(op, a, b=None, loc=(0, 0)):
        n = N.new("ShaderNodeMath"); n.operation = op; n.location = loc
        for i, x in enumerate((a, b)):
            if x is None: continue
            if isinstance(x, (int, float)): n.inputs[i].default_value = x
            else: Lk.new(x, n.inputs[i])
        return n.outputs[0]
    lw = N.new("ShaderNodeLayerWeight"); lw.location = (-1000, 300); lw.inputs["Blend"].default_value = 0.5
    facing = lw.outputs["Facing"]
    tc = N.new("ShaderNodeTexCoord"); tc.location = (-1000, -300)
    nz = N.new("ShaderNodeTexNoise"); nz.location = (-800, -300); Lk.new(tc.outputs["Object"], nz.inputs["Vector"])
    Lk.new(gi.outputs["Breakup Scale"], nz.inputs["Scale"])
    jitter = m('MULTIPLY', m('SUBTRACT', nz.outputs["Fac"], 0.5, (-600, -300)), gi.outputs["Breakup"], (-450, -300))
    center = m('ADD', gi.outputs["Center"], jitter, (-300, -200))
    h = m('ADD', gi.outputs["Height"], m('MULTIPLY', facing, gi.outputs["View Shift"], (-600, 150)), (-450, 100))
    d = m('ABSOLUTE', m('SUBTRACT', h, center, (-150, 0)), None, (0, 0))
    hw = m('MULTIPLY', gi.outputs["Width"], 0.5, (-150, -150))
    hi = m('ADD', hw, m('MAXIMUM', gi.outputs["Softness"], 1e-4, (0, -250)), (150, -200))
    mr = N.new("ShaderNodeMapRange"); mr.location = (300, 0); mr.clamp = True
    Lk.new(d, mr.inputs["Value"]); Lk.new(hw, mr.inputs["From Min"]); Lk.new(hi, mr.inputs["From Max"])
    mr.inputs["To Min"].default_value = 1.0; mr.inputs["To Max"].default_value = 0.0
    front = m('LESS_THAN', facing, gi.outputs["Facing Cutoff"], (300, 250))
    fac = m('MULTIPLY', mr.outputs["Result"], front, (500, 100))
    k = m('MINIMUM', m('MULTIPLY', fac, gi.outputs["Intensity"], (500, -100)), 1.0, (650, -100))
    mix = N.new("ShaderNodeMix"); mix.data_type = 'RGBA'; mix.location = (650, -300)
    Lk.new(k, _sock(mix.inputs, "Factor_Float"))
    Lk.new(gi.outputs["Base Color"], _sock(mix.inputs, "A_Color")); Lk.new(gi.outputs["Ring Color"], _sock(mix.inputs, "B_Color"))
    Lk.new(fac, go.inputs["Fac"]); Lk.new(_sock(mix.outputs, "Result_Color"), go.inputs["Color"])
    return ng


def build_angel_ring(material, obj=None, coord="UV", uv_map="HairUV", uv_axis="V", z_range=None, **inputs):
    """RING_* nodes: height source -> NPR_AngelRing group -> Emission -> Material Output. inputs: group input values
    by name with spaces replaced by underscores (center=0.7, width=0.06, view_shift=0.03, ring_color=(...))."""
    mat = material if isinstance(material, bpy.types.Material) else bpy.data.materials.get(material) \
        or bpy.data.materials.new(material)
    nt = mat.node_tree
    for n in list(nt.nodes):
        if n.name.startswith("RING_"): nt.nodes.remove(n)

    def nn(t, name, loc):
        n = nt.nodes.new(t); n.name = n.label = "RING_" + name; n.location = loc; return n
    if coord == "OBJECT_Z":
        obj = _obj(obj)
        if z_range is None:
            zs = [c[2] for c in obj.bound_box]; z_range = (min(zs), max(zs))
        tc = nn("ShaderNodeTexCoord", "Coord", (-900, 0)); sep = nn("ShaderNodeSeparateXYZ", "Sep", (-700, 0))
        nt.links.new(tc.outputs["Object"], sep.inputs[0])
        mr = nn("ShaderNodeMapRange", "Norm", (-500, 0))
        nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
        mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = z_range
        hsock = mr.outputs["Result"]
    else:
        uvn = nn("ShaderNodeUVMap", "UV", (-900, 0)); uvn.uv_map = uv_map
        sep = nn("ShaderNodeSeparateXYZ", "Sep", (-700, 0)); nt.links.new(uvn.outputs[0], sep.inputs[0])
        hsock = sep.outputs["Y" if uv_axis == "V" else "X"]
    g = nn("ShaderNodeGroup", "Group", (-300, 0)); g.node_tree = angel_ring_group()
    nt.links.new(hsock, g.inputs["Height"])
    for k, v in inputs.items():
        g.inputs[k.replace("_", " ").title()].default_value = v
    em = nn("ShaderNodeEmission", "Emission", (0, 0)); nt.links.new(g.outputs["Color"], em.inputs["Color"])
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None) \
        or nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return {"material": mat.name, "group": g.node_tree.name, "coord": coord, "z_range": list(z_range) if z_range else None}


# ---------------------------------------------------------------- measurement helpers
def _head_frame(src, u_axis, forward_axis):
    M = src.matrix_world
    uc, us = AXES[u_axis]; fc, fs = AXES[forward_axis]
    U = Vector(M.col[uc][:3]).normalized() * us
    F = Vector(M.col[fc][:3]).normalized() * fs
    return U, F, U.cross(F).normalized()


def _set_light(light, Ldir):
    loc = light.matrix_world.translation.copy()
    light.matrix_world = Matrix.Translation(loc) @ Ldir.to_track_quat('Z', 'Y').to_matrix().to_4x4()


def _eval_update():
    sc = bpy.context.scene; sc.frame_set(sc.frame_current); bpy.context.view_layer.update()


def _render(engine, res, cam, path):
    """Render `cam` at res x res (Standard view, black world, few samples) to a temporary EXR and return the float
    pixels (h, w, 4). Every scene setting touched -- camera, engine, resolution, view transform/look, output format/
    depth/path, samples, world colour and background strength -- is snapshotted and restored in a finally block
    (in the order taken, so look follows view transform and depth follows format); a world created for the render is
    removed again."""
    import os
    sc = bpy.context.scene; rd = sc.render; vs = sc.view_settings; ims = rd.image_settings
    path = os.path.abspath(bpy.path.abspath(path))
    snap = [(sc, "camera"), (rd, "engine"), (rd, "resolution_x"), (rd, "resolution_y"), (rd, "resolution_percentage"),
            (vs, "view_transform"), (vs, "look"), (ims, "file_format"), (ims, "color_mode"), (ims, "color_depth"),
            (rd, "filepath"), (sc, "world")]
    if engine == 'CYCLES': snap += [(sc.cycles, "samples"), (sc.cycles, "use_denoising")]
    elif hasattr(sc, "eevee"): snap.append((sc.eevee, "taa_render_samples"))
    saved = [(h, a, getattr(h, a)) for h, a in snap if hasattr(h, a)]
    made_world = world = bg = world_saved = None
    try:
        sc.camera = cam; rd.engine = engine
        rd.resolution_x = rd.resolution_y = res; rd.resolution_percentage = 100
        vs.view_transform = 'Standard'; vs.look = 'None'
        ims.file_format = 'OPEN_EXR'; rd.filepath = path
        if engine == 'CYCLES': sc.cycles.samples = 4; sc.cycles.use_denoising = False
        elif hasattr(sc, "eevee"): sc.eevee.taa_render_samples = 1
        if sc.world is None: made_world = sc.world = bpy.data.worlds.new("FSDF_World")
        world = sc.world
        if world.node_tree: bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
        world_saved = (tuple(world.color), bg.inputs["Strength"].default_value if bg else None)
        world.color = (0, 0, 0)
        if bg: bg.inputs["Strength"].default_value = 0.0
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(path, check_existing=False)
        w, h = img.size; px = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(px)
        bpy.data.images.remove(img)
        return px.reshape(h, w, 4)
    finally:
        if world is not None and made_world is None and world_saved is not None:
            world.color = world_saved[0]
            if bg: bg.inputs["Strength"].default_value = world_saved[1]
        for holder, attr, val in saved:
            try: setattr(holder, attr, val)
            except Exception: pass
        if made_world is not None and sc.world is not made_world:
            bpy.data.worlds.remove(made_world)
        try: os.remove(path)
        except OSError: pass


def _ortho_cam(name, center, view_dir, scale):
    cam = bpy.data.objects.get(name)
    if cam is None:
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name)); bpy.context.scene.collection.objects.link(cam)
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = scale; cam.data.clip_start = 0.001; cam.data.clip_end = 100
    loc = center - view_dir.normalized() * (scale * 4)
    cam.matrix_world = Matrix.Translation(loc) @ (-view_dir).to_track_quat('Z', 'Y').to_matrix().to_4x4()
    return cam


def _mesh_frame(obj):
    dg = bpy.context.evaluated_depsgraph_get(); ev = obj.evaluated_get(dg); me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    M = np.array(obj.matrix_world); wc = co @ M[:3, :3].T + M[:3, 3]
    ev.to_mesh_clear()
    lo, hi = wc.min(0), wc.max(0)
    return Vector((lo + hi) / 2), float((hi - lo).max())


def _numeric_face(obj, mat, img_arr, U_true):
    """Mirror of the FSDF node math on evaluated corners, using driver-written socket values; the lit centroid is
    measured along the declared (true) head U axis."""
    nt = mat.node_tree
    vec = lambda n: Vector([nt.nodes[PFX + n].inputs[a].default_value for a in "XYZ"])
    L, U, F = vec("Light"), vec("HeadU"), vec("HeadF")
    dLU, dLF = L.dot(U), L.dot(F)
    flip = 1.0 if dLU < 0 else 0.0
    if nt.nodes.get(PFX + "Angle"):
        t = math.atan2(abs(dLU), dLF) / math.pi
    else:
        ln = math.hypot(dLU, dLF); t = 0.5 * (1 - (dLF / ln if ln > 1e-9 else 0.0))
    uvname = nt.nodes[PFX + "UV"].uv_map; mattr = nt.nodes.get(PFX + "Mask")
    dg = bpy.context.evaluated_depsgraph_get(); ev = obj.evaluated_get(dg); me = ev.to_mesh()
    nl = len(me.loops)
    uv = np.empty(nl * 2); me.uv_layers[uvname].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    lv = np.empty(nl, np.int64); me.loops.foreach_get("vertex_index", lv)
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    M = np.array(obj.matrix_world); wc = co @ M[:3, :3].T + M[:3, 3]
    area = np.empty(len(me.polygons)); me.polygons.foreach_get("area", area)
    tot = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", tot)
    w = np.repeat(area / tot, tot)
    if mattr:
        a = me.attributes.get(mattr.attribute_name)
        vals = np.empty(len(a.data)); a.data.foreach_get("value", vals)
        mask = vals[lv] if a.domain == 'POINT' else vals
    else:
        mask = np.ones(nl)
    ev.to_mesh_clear()
    u = uv[:, 0] + flip * (1 - 2 * uv[:, 0])
    h, wd = img_arr.shape
    s = img_arr[np.clip((uv[:, 1] * h).astype(int), 0, h - 1), np.clip((u * wd).astype(int), 0, wd - 1)]
    lit = (s > t).astype(float)
    wm = w * (mask > 0.5)
    frac = float((wm * lit).sum() / max(wm.sum(), 1e-12))
    side = wc[lv] @ np.array(U_true)
    cen = (wm * side).sum() / max(wm.sum(), 1e-12)
    lit_c = (wm * lit * side).sum() / max((wm * lit).sum(), 1e-12) - cen if (wm * lit).sum() > 0 else 0.0
    return frac, float(lit_c)


GRAPH = [("dLU", 0, "Light"), ("dLF", 1, "HeadF"), ("dLU", 1, "HeadU"), ("Flip", 0, "dLU"), ("AbsLU", 0, "dLU"),
         ("FlipTerm", 1, "Flip"), ("FlipTerm", 0, "OneMinus2U"), ("UFlipped", 1, "FlipTerm"), ("UVOut", 0, "UFlipped"),
         ("Map", 0, "UVOut"), ("Lit", 0, "Map"), ("Lit", 1, "Threshold"), ("FaceColor", 0, "Lit")]
GRAPH_OPS = {"Flip": 'LESS_THAN', "Lit": 'GREATER_THAN', "AbsLU": 'ABSOLUTE', "FlipTerm": 'MULTIPLY', "UFlipped": 'ADD'}


def _graph_defects(nt):
    """NUMERIC mode mirrors the intended math, so hand edits to the FSDF graph are checked structurally."""
    bad = []
    for node, idx, src in GRAPH:
        n = nt.nodes.get(PFX + node)
        lk = n.inputs[idx].links if n else ()
        if not lk or lk[0].from_node.name != PFX + src: bad.append(f"{node}[{idx}]<-{src}")
    for node, op in GRAPH_OPS.items():
        n = nt.nodes.get(PFX + node)
        if n is None or n.operation != op: bad.append(f"{node}.operation!={op}")
    return bad


def orbit_check(face_mesh, light, head, bone=None, material=None, u_axis="X", forward_axis="-Y", steps=24,
                check="NUMERIC", res=96, elevation_deg=0.0, scratch=None, tol_mono=0.02, front_min=0.9,
                back_max=0.1, tol_sym=0.05):
    obj, light, src = _obj(face_mesh), _obj(light), axes_source(head, bone)
    mat = bpy.data.materials.get(material) if isinstance(material, str) else (material or obj.active_material)
    nt = mat.node_tree
    defects = []
    _eval_update()
    Ut, Ft, Up = _head_frame(src, u_axis, forward_axis)      # declared (true) axes
    drv = [f for f in (nt.animation_data.drivers if nt.animation_data else []) if f.data_path.startswith(f'nodes["{PFX}')]
    if not drv or not all(f.driver.is_valid for f in drv): defects.append("drivers_invalid")
    graph = _graph_defects(nt)
    if graph: defects.append("graph_modified")
    img = nt.nodes[PFX + "Map"].image; arr = _image_array(img)
    saved = light.matrix_world.copy()
    cam = None
    if check != "NUMERIC":
        import os, tempfile
        scratch = scratch or tempfile.gettempdir()
        center, size = _mesh_frame(obj)
        cam = _ortho_cam("FSDF_CheckCam", center, -Ft, size * 1.15)
        mix, om = nt.nodes[PFX + "FaceColor"], nt.nodes[PFX + "Masked"]
        keep = [tuple(_sock(mix.inputs, "A_Color").default_value), tuple(_sock(mix.inputs, "B_Color").default_value),
                tuple(_sock(om.inputs, "A_Color").default_value)]
        _sock(mix.inputs, "A_Color").default_value = (0, 1, 0, 1); _sock(mix.inputs, "B_Color").default_value = (1, 0, 0, 1)
        _sock(om.inputs, "A_Color").default_value = (0, 0, 1, 1)
        camx = Vector(cam.matrix_world.col[0][:3]); side_sign = 1.0 if camx.dot(Ut) > 0 else -1.0
    rows = []
    el = math.radians(elevation_deg)
    for k in range(steps + 1):
        a = -180.0 + 360.0 * k / steps
        ar = math.radians(a)
        Ld = (Ft * math.cos(ar) + Ut * math.sin(ar)) * math.cos(el) + Up * math.sin(el)
        _set_light(light, Ld); _eval_update()
        if check == "NUMERIC":
            frac, lc = _numeric_face(obj, mat, arr, Ut)
        else:
            px = _render(check, res, cam, os.path.join(scratch, f"fsdf_{check}_{k:02d}.exr"))
            r, g = px[..., 0] > 0.5, px[..., 1] > 0.5
            litp, shp = r & ~g, g & ~r
            face = litp | shp
            frac = float(litp.sum() / max(face.sum(), 1))
            xs = np.nonzero(face)[1]; xl = np.nonzero(litp)[1]
            lc = float((xl.mean() - xs.mean()) * side_sign) if len(xl) and len(xs) else 0.0
        rows.append({"az": round(a, 2), "frac": round(frac, 4), "lit_centroid": round(lc, 5)})
    light.matrix_world = saved
    if cam is not None:
        _sock(mix.inputs, "A_Color").default_value, _sock(mix.inputs, "B_Color").default_value = keep[0], keep[1]
        _sock(om.inputs, "A_Color").default_value = keep[2]
        bpy.data.objects.remove(cam)
    _eval_update()
    by = {r["az"]: r for r in rows}
    worst_rise = 0.0
    for sgn in (1, -1):
        seq = sorted([r for r in rows if sgn * r["az"] >= 0], key=lambda r: abs(r["az"]))
        for p, q in zip(seq, seq[1:]):
            worst_rise = max(worst_rise, q["frac"] - p["frac"])
    if worst_rise > tol_mono: defects.append("not_monotonic")
    front = by.get(0.0, min(rows, key=lambda r: abs(r["az"])))["frac"]
    back = max(by[-180.0]["frac"], by[180.0]["frac"])
    if front < front_min: defects.append("front_not_lit")
    if back > back_max: defects.append("back_not_shadowed")
    wrong = [r["az"] for r in rows if 0.1 < r["frac"] < 0.9 and 0 < abs(r["az"]) < 180
             and r["lit_centroid"] * r["az"] <= 0]
    if wrong: defects.append("wrong_side")
    asym = max((abs(r["frac"] - by[-r["az"]]["frac"]) for r in rows if -r["az"] in by), default=0.0)
    if asym > tol_sym: defects.append("asymmetric")
    return {"check": check, "steps": steps, "graph": graph, "front_frac": front, "back_frac": back,
            "worst_rise": round(worst_rise, 4),
            "max_asym": round(asym, 4), "wrong_side_az": wrong, "rows": rows, "defects": defects,
            "ok": not defects}


def ring_check(hair_mesh, material=None, views=((0, 10), (60, 30), (120, -15)), check="BLENDER_EEVEE", res=128,
               scratch=None, drift_tol=0.04, width_max=0.15, coverage_min=0.5, expected_center=None):
    """Render each (azimuth, elevation) view with a debug emission (R = ring Fac, G = object Z normalized, B = 1)."""
    import os, tempfile
    obj = _obj(hair_mesh)
    mat = bpy.data.materials.get(material) if isinstance(material, str) else (material or obj.active_material)
    nt = mat.node_tree; g = nt.nodes["RING_Group"]
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
    prev = out.inputs["Surface"].links[0].from_socket if out.inputs["Surface"].links else None
    zs = [c[2] for c in obj.bound_box]; z0, z1 = min(zs), max(zs)
    tmp = []

    def nn(t):
        n = nt.nodes.new(t); n.name = "RINGDBG_" + t; tmp.append(n); return n
    tc, sep, mr, cx, em = (nn("ShaderNodeTexCoord"), nn("ShaderNodeSeparateXYZ"), nn("ShaderNodeMapRange"),
                           nn("ShaderNodeCombineXYZ"), nn("ShaderNodeEmission"))
    nt.links.new(tc.outputs["Object"], sep.inputs[0]); nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = z0, z1
    nt.links.new(g.outputs["Fac"], cx.inputs[0]); nt.links.new(mr.outputs["Result"], cx.inputs[1])
    cx.inputs[2].default_value = 1.0
    nt.links.new(cx.outputs[0], em.inputs["Color"]); nt.links.new(em.outputs[0], out.inputs["Surface"])
    scratch = scratch or tempfile.gettempdir()
    center, size = _mesh_frame(obj)
    rows, defects = [], []
    for i, (az, elv) in enumerate(views):
        a, e = math.radians(az), math.radians(elv)
        view_dir = -Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))  # camera looks along
        cam = _ortho_cam("RING_CheckCam", center, view_dir, size * 1.2)
        px = _render(check, res, cam, os.path.join(scratch, f"ring_{check}_{i}.exr"))
        hair = px[..., 2] > 0.5; ring = hair & (px[..., 0] > 0.5)
        z = z0 + px[..., 1] * (z1 - z0)
        if ring.sum() == 0:
            rows.append({"az": az, "el": elv, "ring_px": 0}); continue
        zr = z[ring]; med = float(np.median(zr)); p10, p90 = np.percentile(zr, [10, 90])
        band_hair = hair & (np.abs(z - med) <= max((p90 - p10), 0.01 * (z1 - z0)))
        cols = np.nonzero(band_hair.any(0))[0]
        cov = float(ring[:, cols].any(0).mean()) if len(cols) else 0.0
        rows.append({"az": az, "el": elv, "ring_px": int(ring.sum()), "z_median": round(med, 4),
                     "z_width": round(float(p90 - p10), 4), "coverage": round(cov, 3)})
        bpy.data.objects.remove(cam)
    for n in tmp: nt.nodes.remove(n)
    if prev is not None: nt.links.new(prev, out.inputs["Surface"])
    H = z1 - z0
    good = [r for r in rows if r["ring_px"]]
    if len(good) < len(rows): defects.append("ring_missing")
    if good:
        meds = [r["z_median"] for r in good]
        drift = (max(meds) - min(meds)) / H
        if drift > drift_tol: defects.append("ring_drifts")
        if max(r["z_width"] for r in good) / H > width_max: defects.append("ring_too_wide")
        if min(r["coverage"] for r in good) < coverage_min: defects.append("ring_broken")
        if expected_center is not None and abs(np.mean(meds) - expected_center) / H > drift_tol:
            defects.append("ring_off_center")
    else:
        drift = None
    return {"check": check, "hair_height": round(H, 4), "drift_rel": None if drift is None else round(drift, 4),
            "views": rows, "defects": defects, "ok": not defects}


# ---------------------------------------------------------------- entry points
def face_sdf(face_mesh=None, light=None, head=None, bone=None, material=None, uv_map="FaceUV", map="SYNTHETIC",
             u_axis="X", forward_axis="-Y", mapping="COS", mask_attr=None, check="NUMERIC", steps=24,
             measure_only=False, hair_mesh=None, ring_coord="UV", ring_center=0.7, ring_width=0.06, scratch=None,
             assign_faces="MASK", lit_color=None, shadow_color=None, outside_color=None, **kw):
    res = {}
    if kw: res["ignored_opts"] = sorted(kw)
    if face_mesh:
        obj = _obj(face_mesh)
        mat = material or (obj.active_material.name if obj.active_material else f"MAT_FaceSDF_{obj.name}")
        if not measure_only:
            m = bpy.data.materials.get(mat) or bpy.data.materials.new(mat)
            if m.name not in [s.material.name for s in obj.material_slots if s.material]: obj.data.materials.append(m)
            colors = {k: _rgba(v) for k, v in (("lit_color", lit_color), ("shadow_color", shadow_color),
                                               ("outside_color", outside_color)) if v is not None}
            res["build"] = build_face_sdf(m, light, head or obj, bone, uv_map, None,
                                          None if map == "SYNTHETIC" else map, u_axis, forward_axis, mapping, mask_attr,
                                          **colors)
            res["build"].update(assign_face_slot(obj, m, (assign_faces or "MASK").upper(), mask_attr))
        if check:
            res["face"] = orbit_check(obj, light, head or obj, bone, mat, u_axis, forward_axis, steps, check,
                                      scratch=scratch)
    if hair_mesh:
        obj = _obj(hair_mesh)
        mat = material if (material and not face_mesh) else (obj.active_material.name if obj.active_material
                                                             else f"MAT_Hair_{obj.name}")
        if not measure_only:
            m = bpy.data.materials.get(mat) or bpy.data.materials.new(mat)
            if not obj.material_slots or obj.material_slots[0].material != m: obj.data.materials.append(m)
            res["ring_build"] = build_angel_ring(m, obj, ring_coord, uv_map if ring_coord == "UV" else None,
                                                 center=ring_center, width=ring_width)
        if check and check != "NUMERIC":
            res["ring"] = ring_check(obj, mat, check=check, scratch=scratch)
    res["ok"] = all(v.get("ok", True) for v in res.values() if isinstance(v, dict))
    return res


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="face_sdf.py")
    p.add_argument("--face-mesh"); p.add_argument("--light"); p.add_argument("--head"); p.add_argument("--bone")
    p.add_argument("--material"); p.add_argument("--uv-map", default=None); p.add_argument("--map", default="SYNTHETIC")
    p.add_argument("--u-axis", default="X", choices=list(AXES)); p.add_argument("--forward-axis", default="-Y", choices=list(AXES))
    p.add_argument("--mapping", default="COS", choices=["COS", "ANGLE"]); p.add_argument("--mask-attr")
    p.add_argument("--assign-faces", default="MASK", choices=["MASK", "ALL", "NONE"])
    for flag in ("--lit-color", "--shadow-color", "--outside-color"):
        p.add_argument(flag, type=float, nargs=3, metavar=("R", "G", "B"), help="linear RGB")
    p.add_argument("--check", default="NUMERIC", choices=["NUMERIC", "BLENDER_EEVEE", "CYCLES", ""])
    p.add_argument("--steps", type=int, default=24); p.add_argument("--measure-only", action="store_true")
    p.add_argument("--hair-mesh"); p.add_argument("--ring-coord", default="UV", choices=["UV", "OBJECT_Z"])
    p.add_argument("--ring-center", type=float, default=0.7); p.add_argument("--ring-width", type=float, default=0.06)
    p.add_argument("--scratch"); p.add_argument("--save")
    a = p.parse_args(argv)
    uv = a.uv_map or ("FaceUV" if a.face_mesh else "HairUV")
    res = face_sdf(a.face_mesh, a.light, a.head, a.bone, a.material, uv, a.map, a.u_axis, a.forward_axis, a.mapping,
                   a.mask_attr, a.check, a.steps, a.measure_only, a.hair_mesh, a.ring_coord, a.ring_center,
                   a.ring_width, a.scratch, assign_faces=a.assign_faces, lit_color=a.lit_color,
                   shadow_color=a.shadow_color, outside_color=a.outside_color)
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(a.save)); res["saved"] = a.save
    return res


DEFINED = ["synthetic_threshold_map", "masks_to_threshold", "ensure_image", "axes_source", "build_face_sdf",
           "assign_face_slot", "angel_ring_group", "build_angel_ring", "orbit_check", "ring_check", "face_sdf"]

if "FACE_SDF_OPTS" in globals():  # live exec
    result = face_sdf(**dict(FACE_SDF_OPTS))
    print("FACE_SDF " + json.dumps(result))
elif __name__ == "__main__" and "--" in sys.argv and any(
        x in sys.argv[sys.argv.index("--") + 1:] for x in ("--face-mesh", "--hair-mesh")):
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print("FACE_SDF " + json.dumps(result))
else:
    result = {"defined": DEFINED}
