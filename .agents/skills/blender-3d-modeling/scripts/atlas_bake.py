"""Atlas small props for mobile / Quest / web: merge objects into one mesh, pack a new atlas UV map with a pixel margin,
bake every original material into one texture set, rebuild a single material, and prove it (draw calls before/after,
texel density, per-material colour error at island centres and island borders = bleed detector).

Headless / CLI (prints one line: ATLAS_BAKE <json>):
    BLENDER -b scene.blend --python atlas_bake.py -- (--collection Props | --prefix PROP_ | --objects A,B,C) --out <dir>
        [--name ATLAS_Props] [--material MAT_Atlas] [--size 1024] [--margin-px 8] [--bake-margin 8]
        [--maps BASECOLOR,ROUGHNESS,METALLIC,NORMAL] [--orm] [--samples 4] [--no-rotate] [--normal-convention OPENGL|DIRECTX]
        [--delete-originals] [--no-hide-originals] [--ref-size 256] [--no-verify] [--no-uv-check]
        [--tol 2] [--bleed-tol 8] [--method S2A|SELF] [--cage-extrusion 0.005] [--max-ray-distance 0.02]
        [--keep-source-uv] [--scripts-dir <skill>/scripts] [--save out.blend]
    (--scripts-dir: folder holding uv_tools.py and bake_maps.py; default = this file's folder; -h / --help prints the
     argparse help)
Live (Blender:execute_blender_code): set before exec
    ATLAS_OPTS = {"collection": "Props", "out": "D:/out/atlas", "size": 1024, "margin_px": 8,
                  "scripts_dir": "<skill>/scripts"}                                  -> `result` dict
    (scripts_dir is needed when the file is exec'd without __file__; uv_tools.py and bake_maps.py are loaded from it)
Without ATLAS_OPTS the file only defines atlas_bake (and helpers).

Pipeline
  1 select   mesh objects of a collection (recursive), a name prefix, or an explicit list (the output object is excluded).
  2 merge    evaluated copies (modifiers applied, world transform baked in, object-linked materials kept) joined into
             one object; the originals stay (hidden) unless delete_originals. Each face stores its source index in the
             int face attribute `atlas_src`. The render-active UV map of every copy is renamed to the most common name so
             texture lookups survive the join; a copy without UVs gets Smart UV Project (warning).
  3 UVs      new map `UVAtlas` (initialised from the source UVs) -> scripts/uv_tools.py pack(): islands averaged to one
             texel density, packed with margin_px GAP between islands at `size`.
  4 bake     scripts/bake_maps.py (Cycles, margin type EXTEND, dither 0 during the bake):
             method S2A (default) = selected-to-active from the untouched originals onto the coincident merged mesh
             (cage_extrusion 5 mm, max_ray_distance 4x) - Object/Generated coordinates, Object Info, named UV maps and
             group internals all shade exactly as before. Props that touch or interpenetrate within the extrusion can
             pick up the neighbour's surface.
             method SELF = bake the merged mesh with its own materials (UVAtlas active, source map render-active): no
             ray casting, but Object/Generated texture coordinates change with the merge (measured 62-107/255 error).
             BASECOLOR (metal-corrected), ROUGHNESS, METALLIC (emission re-route), NORMAL (tangent space of UVAtlas,
             rotated islands verified), or orm=True -> <name>_ORM (R AO, G rough, B metal; AO sees the whole scene).
  5 material one `MAT_Atlas` (Principled; UV Map node -> UVAtlas; ORM via Separate Color G/B), every face slot 0;
             the source UV map and `atlas_src` are removed afterwards unless keep_source_uv.
  6 verify   per original material, centre of every face: error vs the Principled socket value when unlinked
             (independent), else vs a reference bake of that source on a temporary copy with a fresh smart-project UV
             map at ref_size (robust to overlapping / mirrored source UVs); roughness / metallic vs their sockets.
             Bleed: for constant-colour materials, every UV-island border edge (corners + midpoint, bilinear) vs the
             same atlas 1.5 px inside the island - a neighbour island's colour within half a texel shows up there
             (textured materials report the same number as border_jump_info_255: content may change at a seam).
             BASECOLOR is baked with Specular IOR Level / Coat / Sheen weights at 0 (restored): Cycles' diffuse colour
             pass is otherwise darkened by those layers (measured 1.5-4.5/255 on solid colours).
             Units 8-bit (sRGB for colour). center error > tol -> bake wrong; border bleed > bleed_tol -> margin too small.
             uv_tools.check_uvs() reports the smallest island gap; mip levels free of bleed ~ floor(log2(gap_px)).
Draw calls: before = used material slots summed over the source objects; after = 1 (engines may still split by
lightmap / light count / shadow pass). Texel density per source object = sqrt(UV area / world area) * size.
Limitations: bakes Principled-based surfaces (emission, transparency and SSS are not reproduced by the 3-4 maps);
UV Map nodes naming a non-dominant UV map in some objects sample the wrong map after the join; procedural reference
error includes resampling differences on high-frequency textures (use --ref-size near the atlas density);
multi-material edges inside one UV island are skipped by the border test (their mix is inherent, not bleed).
"""
import bpy, bmesh, json, math, os, sys, time
import numpy as np
from collections import Counter

ATLAS_UV = "UVAtlas"
DEFAULT_MAPS = ('BASECOLOR', 'ROUGHNESS', 'METALLIC', 'NORMAL')


# ------------------------------------------------------------------------------------------------ helpers
def _load(name, scripts_dir=None):
    d = scripts_dir or os.path.dirname(os.path.abspath(globals().get("__file__") or ""))
    path = os.path.join(d, name + ".py")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{path} not found: pass scripts_dir")
    ns = {"__name__": "_atlas_" + name, "__file__": path}
    saved = sys.argv; sys.argv = [saved[0]]  # keep the sibling script from parsing our CLI
    try:
        exec(compile(open(path, encoding="utf-8").read(), path, "exec"), ns)
    finally:
        sys.argv = saved
    return ns


def _select(collection=None, prefix=None, objects=None, exclude=()):
    if objects:
        names = [n.strip() for n in objects.split(",")] if isinstance(objects, str) else list(objects)
        objs = [bpy.data.objects[n] for n in names]
    else:
        if collection:
            if collection not in bpy.data.collections: raise ValueError(f"collection {collection!r} not found")
            pool = bpy.data.collections[collection].all_objects
        else:
            pool = bpy.context.scene.objects
        objs = [o for o in pool if (not prefix or o.name.startswith(prefix))]
    objs = [o for o in objs if o.type == 'MESH' and o.name not in exclude]
    if not objs: raise ValueError("no mesh objects selected (collection / prefix / objects)")
    return objs


def _used_slots(ob, dg):
    me = ob.evaluated_get(dg).data
    if not len(me.polygons): return []
    mi = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("material_index", mi)
    slots = [s.material for s in ob.material_slots]
    return [slots[i] if i < len(slots) else None for i in sorted(set(mi.tolist()))]


def _images(tree, seen=None):
    seen = seen if seen is not None else set()
    if tree is None or tree.name in seen: return set()
    seen.add(tree.name); out = set()
    for n in tree.nodes:
        if getattr(n, "image", None) is not None: out.add(n.image.name)
        if n.type == 'GROUP' and n.node_tree: out |= _images(n.node_tree, seen)
    return out


def _l2s(c):
    c = np.clip(np.asarray(c, float), 0, 1); return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def _constants(mat):
    """{'BASECOLOR': srgb3 | None, 'ROUGHNESS': v | None, 'METALLIC': v | None, 'flat_normal': bool} - None = linked."""
    res = {"BASECOLOR": None, "ROUGHNESS": None, "METALLIC": None, "flat_normal": False}
    if mat is None or mat.node_tree is None: return res
    nt = mat.node_tree
    outs = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output] or \
           [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL']
    if not outs or not outs[0].inputs["Surface"].is_linked: return res
    p = outs[0].inputs["Surface"].links[0].from_node
    if p.bl_idname != 'ShaderNodeBsdfPrincipled': return res
    bc, ro, me = p.inputs["Base Color"], p.inputs["Roughness"], p.inputs["Metallic"]
    if not bc.is_linked: res["BASECOLOR"] = _l2s(bc.default_value[:3])
    if not ro.is_linked: res["ROUGHNESS"] = float(ro.default_value)
    if not me.is_linked: res["METALLIC"] = float(me.default_value)
    res["flat_normal"] = not p.inputs["Normal"].is_linked
    return res


def _pixels(path, colorspace):
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = colorspace
    w, h = img.size
    px = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(px)  # byte images: stored (sRGB-encoded) values
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4).astype(np.float64)


def _bilinear(px, uv):
    h, w = px.shape[:2]
    x = uv[:, 0] * w - 0.5; y = uv[:, 1] * h - 0.5
    x0 = np.floor(x).astype(np.int64); y0 = np.floor(y).astype(np.int64); fx = (x - x0)[:, None]; fy = (y - y0)[:, None]
    g = lambda xx, yy: px[np.clip(yy, 0, h - 1), np.clip(xx, 0, w - 1)]
    return (g(x0, y0) * (1 - fx) * (1 - fy) + g(x0 + 1, y0) * fx * (1 - fy) +
            g(x0, y0 + 1) * (1 - fx) * fy + g(x0 + 1, y0 + 1) * fx * fy)


def _remove_object(name):
    ob = bpy.data.objects.get(name)
    if ob is None: return
    me = ob.data if ob.type == 'MESH' else None
    bpy.data.objects.remove(ob)
    if me is not None and me.users == 0: bpy.data.meshes.remove(me)


# ------------------------------------------------------------------------------------------------ merge
def _merge(objs, name, dg, rep):
    rnames = Counter((o.data.uv_layers.active_render or o.data.uv_layers.active).name if o.data.uv_layers else None for o in objs)
    src_uv = next((n for n, _ in rnames.most_common() if n), "UVMap")
    copies = []
    for i, o in enumerate(objs):
        me = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        me.name = f"{name}_part{i}"
        me.transform(o.matrix_world)
        if o.matrix_world.determinant() < 0: me.flip_normals()
        me.materials.clear()
        for s in o.material_slots: me.materials.append(s.material)
        if me.uv_layers:
            lay = me.uv_layers.active_render or me.uv_layers.active
            if lay.name != src_uv:
                if src_uv in me.uv_layers: me.uv_layers.remove(me.uv_layers[src_uv]); lay = me.uv_layers.active_render or me.uv_layers[0]
                lay.name = src_uv
        attr = me.attributes.get("atlas_src") or me.attributes.new("atlas_src", 'INT', 'FACE')
        attr.data.foreach_set("value", np.full(len(me.polygons), i, np.int32))
        ob = bpy.data.objects.new(me.name, me); bpy.context.scene.collection.objects.link(ob)
        if not me.uv_layers:
            me.uv_layers.new(name=src_uv)
            vl = bpy.context.view_layer
            for x in vl.objects: x.select_set(False)
            ob.select_set(True); vl.objects.active = ob
            bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.0)
            bpy.ops.object.mode_set(mode='OBJECT')
            rep["warnings"].append(f"{o.name}: no UV map - Smart UV Project used for the atlas (textures on it had no UVs)")
        me.uv_layers.active = me.uv_layers[src_uv]
        me.uv_layers[src_uv].active_render = True
        at = me.uv_layers.get(ATLAS_UV) or me.uv_layers.new(name=ATLAS_UV, do_init=True)
        copies.append(ob)
    tgt = copies[0]
    if len(copies) > 1:
        with bpy.context.temp_override(active_object=tgt, object=tgt, selected_objects=copies, selected_editable_objects=copies):
            bpy.ops.object.join()
    tgt.name = name; tgt.data.name = name
    me = tgt.data
    me.uv_layers[src_uv].active_render = True
    me.uv_layers.active = me.uv_layers[ATLAS_UV]
    return tgt, src_uv


# ------------------------------------------------------------------------------------------------ verification
def _face_samples(me, src_uv):
    """(face_index, atlas_uv, source_uv, kind) arrays for face centres and UV-island border edges of UVAtlas."""
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    la, ls = bm.loops.layers.uv[ATLAS_UV], bm.loops.layers.uv[src_uv]
    F, A, S, K = [], [], [], []
    for f in bm.faces:
        F.append(f.index); K.append(0)
        A.append(np.mean([l[la].uv[:] for l in f.loops], 0)); S.append(np.mean([l[ls].uv[:] for l in f.loops], 0))
    eps = 1e-6
    for f in bm.faces:
        for l in f.loops:
            e = l.edge; nxt = l.link_loop_next
            others = [x for x in e.link_loops if x.face != f]
            border = not others
            if others:
                o = others[0]; on = o.link_loop_next
                other = {o.vert.index: o[la].uv, on.vert.index: on[la].uv}  # matched by vertex (any winding)
                seam = any(_uv_diff(other[x.vert.index], x[la].uv) > eps for x in (l, nxt) if x.vert.index in other)
                if not seam: continue  # interior (material changes inside an island are not bleed)
                border = True
            if border:
                for t in (0.0, 0.5, 1.0):
                    F.append(f.index); K.append(1)
                    A.append((1 - t) * np.array(l[la].uv[:]) + t * np.array(nxt[la].uv[:]))
                    S.append((1 - t) * np.array(l[ls].uv[:]) + t * np.array(nxt[ls].uv[:]))
    bm.free()
    return np.array(F), np.array(A), np.array(S), np.array(K)


def _uv_diff(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _texel_density(me, size, nsrc):
    me.calc_loop_triangles(); nt = len(me.loop_triangles)
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    tv = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get("vertices", tv); tv = tv.reshape(-1, 3)
    tl = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get("loops", tl); tl = tl.reshape(-1, 3)
    tp = np.empty(nt, np.int64); me.loop_triangles.foreach_get("polygon_index", tp)
    uv = np.empty(len(me.loops) * 2); me.uv_layers[ATLAS_UV].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    src = np.empty(len(me.polygons), np.int64); me.attributes["atlas_src"].data.foreach_get("value", src)
    p = co[tv]; a3 = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    q = uv[tl]; d1, d2 = q[:, 1] - q[:, 0], q[:, 2] - q[:, 0]; auv = 0.5 * np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0])
    s3 = np.bincount(src[tp], a3, nsrc); suv = np.bincount(src[tp], auv, nsrc)
    dens = np.sqrt(suv / np.maximum(s3, 1e-12)) * size
    return dens, float(auv.sum())


SPEC_OFF = ("Specular IOR Level", "Coat Weight", "Sheen Weight")


def _bake_color(bk, obj_name, out, mats, **kw):
    """BASECOLOR with the dielectric specular, coat and sheen layers switched off: Cycles' DIFFUSE colour pass is
    otherwise darkened by those layers' albedo (measured up to 4.45/255 on solid colours)."""
    undo = [(m, bk["_zero_inputs"](m, SPEC_OFF)) for m in mats if m and m.node_tree]
    try:
        return bk["bake_maps"](obj_name, out, maps=("BASECOLOR",), **kw)
    finally:
        for m, u in undo: bk["_restore_inputs"](m, u)


def _reference(bk, o, dg, out, ref_size, samples, mats, i):
    """Reference BASECOLOR of one source on a temporary copy (same local mesh + transform -> same Object/Generated
    coordinates) with a fresh non-overlapping UVRef bake map; the source UVs stay render-active for textures.
    Returns (pixels HxWx4, per-face UVRef centroids in the copy's face order = the merged mesh's order for source i)."""
    me = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    me.materials.clear()
    for s in o.material_slots: me.materials.append(s.material)
    ob = bpy.data.objects.new(f"__atlas_ref_{i}", me); bpy.context.scene.collection.objects.link(ob)
    ob.matrix_world = o.matrix_world.copy()
    render = me.uv_layers.active_render.name if len(me.uv_layers) and me.uv_layers.active_render else None
    me.uv_layers.active = me.uv_layers.new(name="UVRef", do_init=False)
    vl = bpy.context.view_layer
    for x in vl.objects: x.select_set(False)
    ob.select_set(True); vl.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.03)
    bpy.ops.object.mode_set(mode='OBJECT')
    me = ob.data
    if render: me.uv_layers[render].active_render = True
    me.uv_layers.active = me.uv_layers["UVRef"]
    try:
        r = _bake_color(bk, ob.name, out, mats, size=ref_size, margin=8, samples=samples, udim='off')
        px = _pixels(r["maps"]["BASECOLOR"]["path"], "sRGB")
        uv = np.empty(len(me.loops) * 2); me.uv_layers["UVRef"].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
        ls = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_start", ls)
        lt = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", lt)
        return px, np.add.reduceat(uv, ls, axis=0) / lt[:, None]
    finally:
        _remove_object(ob.name)


# ------------------------------------------------------------------------------------------------ main
def atlas_bake(out, collection=None, prefix=None, objects=None, name="ATLAS_Props", material="MAT_Atlas", size=1024,
               margin_px=8, bake_margin=None, maps=DEFAULT_MAPS, orm=False, samples=4, rotate=True,
               normal_convention='OPENGL', delete_originals=False, hide_originals=True, ref_size=256, verify=True,
               uv_check=True, tol=2.0, bleed_tol=8.0, scripts_dir=None, save=None, method='S2A', cage_extrusion=0.005,
               max_ray_distance=None, keep_source_uv=False):
    t0 = time.time()
    uvt, bk = _load("uv_tools", scripts_dir), _load("bake_maps", scripts_dir)
    out = os.path.abspath(out); os.makedirs(out, exist_ok=True)
    if bpy.context.object is not None and bpy.context.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    rep = {"blender": bpy.app.version_string, "object": name, "material": material, "size": size, "margin_px": margin_px,
           "warnings": [], "notes": []}
    _remove_object(name)
    objs = _select(collection, prefix, objects, exclude={name})
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    used = {o.name: _used_slots(o, dg) for o in objs}
    mats_before = {m for v in used.values() for m in v if m}
    rep["sources"] = [o.name for o in objs]
    rep["before"] = {"objects": len(objs), "draw_calls": sum(max(1, len(v)) for v in used.values()),
                     "materials": len(mats_before),
                     "textures": len(set().union(*[_images(m.node_tree) for m in mats_before]) if mats_before else set())}
    merged, src_uv = _merge(objs, name, dg, rep)
    me = merged.data
    rep["source_uv"] = src_uv
    # ---- pack
    rep["pack"] = uvt["pack"]([merged], texture_px=size, margin_px=margin_px, uv_map=ATLAS_UV, rotate=rotate,
                              scale=True, average_scale=True)
    me.uv_layers[src_uv].active_render = True; me.uv_layers.active = me.uv_layers[ATLAS_UV]
    # ---- per-face material bookkeeping (before the materials are replaced)
    mi = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("material_index", mi)
    src = np.empty(len(me.polygons), np.int64); me.attributes["atlas_src"].data.foreach_get("value", src)
    slot_mats = [s.material for s in merged.material_slots]
    face_mat = [slot_mats[i].name if i < len(slot_mats) and slot_mats[i] else "<none>" for i in mi]
    consts = {m.name: _constants(m) for m in slot_mats if m}
    # ---- bake (margin type EXTEND: gutters repeat the island's own edge, not the 3-D neighbour face; no dither noise)
    sc = bpy.context.scene; bs = sc.render.bake
    saved = (bs.margin_type, sc.render.dither_intensity); bs.margin_type = 'EXTEND'; sc.render.dither_intensity = 0.0
    maps = [m.upper() for m in (maps.split(",") if isinstance(maps, str) else maps)]
    bmargin = int(bake_margin if bake_margin is not None else max(2, margin_px))
    method = method.upper(); rep["method"] = method
    if method not in ('S2A', 'SELF'): raise ValueError("method must be S2A or SELF")
    mat = bpy.data.materials.get(material) or bpy.data.materials.new(material)
    if method == 'S2A':  # target shades nothing itself: one placeholder slot receives the image nodes
        me.materials.clear(); me.materials.append(mat)
        me.polygons.foreach_set("material_index", np.zeros(len(me.polygons), np.int32)); me.update()
    ref_paths = {}
    try:
        tb = time.time()
        kw = dict(maps=maps, size=size, margin=bmargin, samples=samples, orm=orm, normal_convention=normal_convention, udim='off')
        if method == 'S2A':
            ext = float(cage_extrusion)
            kw.update(source_objects=[o.name for o in objs], cage_extrusion=ext,
                      max_ray_distance=float(max_ray_distance if max_ray_distance is not None else 4 * ext))
            rep["cage_extrusion"], rep["max_ray_distance"] = ext, kw["max_ray_distance"]
        shade = [m for m in slot_mats if m]
        rep["maps"] = {}
        for part in (["BASECOLOR"] if "BASECOLOR" in maps else []) + (["REST"] if [m for m in maps if m != "BASECOLOR"] or orm else []):
            if part == "BASECOLOR":
                brep = _bake_color(bk, merged.name, out, shade, **{k: v for k, v in kw.items() if k not in ("maps", "orm")})
            else:
                brep = bk["bake_maps"](merged.name, out, **dict(kw, maps=[m for m in maps if m != "BASECOLOR"]))
            rep["warnings"] += [f"bake: {w}" for w in brep["warnings"] if "constant map" not in w]
            rep["maps"].update({k: v.get("path") for k, v in brep["maps"].items()})
        rep["bake_seconds"] = round(time.time() - tb, 2)
        if verify:
            need = sorted({int(s) for s, fm in zip(src, face_mat) if fm in consts and consts[fm]["BASECOLOR"] is None})
            for i in need:
                ref_paths[i] = _reference(bk, objs[i], dg, os.path.join(out, "_reference"), ref_size, samples, shade, i)
    finally:
        bs.margin_type, sc.render.dither_intensity = saved
    # ---- material
    nt = mat.node_tree; nt.nodes.clear()
    o_n = nt.nodes.new("ShaderNodeOutputMaterial"); o_n.location = (500, 0)
    p = nt.nodes.new("ShaderNodeBsdfPrincipled"); p.location = (150, 0); nt.links.new(p.outputs[0], o_n.inputs["Surface"])
    uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = ATLAS_UV; uvn.location = (-750, 0)

    def tex(key, cs, y):
        path = rep["maps"].get(key)
        if not path: return None
        img = bpy.data.images.load(path, check_existing=True); img.reload(); img.colorspace_settings.name = cs
        n = nt.nodes.new("ShaderNodeTexImage"); n.image = img; n.location = (-450, y); n.label = key
        nt.links.new(uvn.outputs["UV"], n.inputs["Vector"]); return n

    t = tex("BASECOLOR", "sRGB", 300)
    if t: nt.links.new(t.outputs["Color"], p.inputs["Base Color"])
    if orm and rep["maps"].get("ORM"):
        t = tex("ORM", "Non-Color", 0); sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-150, 0)
        nt.links.new(t.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs[1], p.inputs["Roughness"]); nt.links.new(sep.outputs[2], p.inputs["Metallic"])
    else:
        for key, sock, y in (("ROUGHNESS", "Roughness", 0), ("METALLIC", "Metallic", -300)):
            t = tex(key, "Non-Color", y)
            if t: nt.links.new(t.outputs["Color"], p.inputs[sock])
    if rep["maps"].get("NORMAL"):
        t = tex("NORMAL", "Non-Color", -600); nm = nt.nodes.new("ShaderNodeNormalMap"); nm.location = (-150, -600)
        nm.uv_map = ATLAS_UV
        if normal_convention.upper() == 'DIRECTX' and hasattr(nm, "convention"): nm.convention = 'DIRECTX'
        nt.links.new(t.outputs["Color"], nm.inputs["Color"]); nt.links.new(nm.outputs["Normal"], p.inputs["Normal"])
    me.materials.clear(); me.materials.append(mat)
    me.polygons.foreach_set("material_index", np.zeros(len(me.polygons), np.int32)); me.update()
    me.uv_layers[ATLAS_UV].active_render = True
    # ---- metrics
    dens, fill = _texel_density(me, size, len(objs))
    rep["texel_density_px_per_m"] = {"min": round(float(dens.min()), 1), "max": round(float(dens.max()), 1),
                                     "mean": round(float(dens.mean()), 1), "max_over_min": round(float(dens.max() / max(dens.min(), 1e-9)), 3),
                                     "per_source": {o.name: round(float(d), 1) for o, d in zip(objs, dens)}}
    rep["uv_fill"] = round(fill, 4)
    rep["after"] = {"objects": 1, "draw_calls": 1, "materials": 1, "textures": len(_images(mat.node_tree))}
    if uv_check:
        try:
            ck = uvt["check_uvs"]([merged], texture_px=size, uv_map=ATLAS_UV, min_margin_px=max(margin_px, 1), group_by='ALL',
                                  max_listed=5)
            gap = ck["padding"].get("min_gap_px")
            rep["uv_padding"] = {"min_gap_px": gap, "min_border_px": ck["padding"].get("min_border_px"),
                                 "violations": ck["padding"].get("violations", 0),
                                 "bleed_free_mip_levels": (int(math.floor(math.log2(gap))) if gap and gap >= 1 else 0) if gap is not None else None,
                                 "overlaps": ck.get("overlap_counts")}
        except Exception as ex:
            rep["warnings"].append(f"uv check skipped: {ex}")
    if verify:
        F, A, S, K = _face_samples(me, src_uv)
        pxs = {k: _pixels(rep["maps"][k], "sRGB" if k == "BASECOLOR" else "Non-Color")
               for k in ("BASECOLOR", "ROUGHNESS", "METALLIC", "NORMAL", "ORM") if rep["maps"].get(k)}
        refs = ref_paths  # i -> (pixels, per-face UVRef centroids)
        fm = np.array(face_mat, dtype=object)[F]; fs = src[F]
        vr = {"tol_255": tol, "bleed_tol_255": bleed_tol, "materials": {}}
        base = _bilinear(pxs["BASECOLOR"], A)[:, :3] if "BASECOLOR" in pxs else None
        bleed = np.zeros(len(F))
        if base is not None:  # border sample vs the same atlas 1.5 px inside the island: reference-free bleed test
            cent = A[K == 0]; b = K == 1; ins = A.copy()
            dv = cent[F[b]] - A[b]; dl = np.linalg.norm(dv, axis=1, keepdims=True)
            ins[b] = A[b] + dv / np.maximum(dl, 1e-12) * np.minimum(1.5 / size, 0.5 * dl)
            bleed = np.abs(base - _bilinear(pxs["BASECOLOR"], ins)[:, :3]).max(1) * 255
        chan = {"ROUGHNESS": ("ROUGHNESS", 0), "METALLIC": ("METALLIC", 0)}
        if "ORM" in pxs: chan = {"ROUGHNESS": ("ORM", 1), "METALLIC": ("ORM", 2)}
        for mname in sorted(set(face_mat)):
            c = consts.get(mname, {}); sel = fm == mname; e = {"samples_center": int((sel & (K == 0)).sum()),
                                                                "samples_border": int((sel & (K == 1)).sum())}
            if base is not None:
                err = np.full(len(F), np.nan)
                if c.get("BASECOLOR") is not None:
                    err[sel] = np.abs(base[sel] - c["BASECOLOR"]).max(1) * 255; e["reference"] = "socket"
                else:
                    e["reference"] = "bake"
                    for i in set(fs[sel].tolist()):
                        m2 = sel & (fs == i) & (K == 0)
                        fidx = np.where(src == i)[0]
                        if i in refs and len(refs[i][1]) == len(fidx):
                            cen_r = refs[i][1][np.searchsorted(fidx, F[m2])]
                            err[m2] = np.abs(base[m2] - _bilinear(refs[i][0], cen_r)[:, :3]).max(1) * 255
                        else:
                            e["reference"] = "incomplete (topology mismatch)"
                ce, be = err[sel & (K == 0)], bleed[sel & (K == 1)]
                e["basecolor_center_max_255"] = round(float(np.nanmax(ce)), 2) if np.isfinite(ce).any() else None
                # bleed is judged on constant colours only: textures legitimately change at island borders (UV wrap)
                e["border_bleed_max_255" if c.get("BASECOLOR") is not None else "border_jump_info_255"] = \
                    round(float(be.max()), 2) if len(be) else None
            for key in ("ROUGHNESS", "METALLIC"):
                img, ch = chan[key]
                if img in pxs and c.get(key) is not None:
                    v = _bilinear(pxs[img], A[sel & (K == 0)])[:, ch]
                    e[key.lower() + "_center_max_255"] = round(float(np.abs(v - c[key]).max() * 255), 2)
            if "NORMAL" in pxs and c.get("flat_normal"):
                n = _bilinear(pxs["NORMAL"], A[sel & (K == 0)])[:, :3] * 2 - 1
                n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
                e["normal_flat_dev_deg"] = round(float(np.degrees(np.arccos(np.clip(n[:, 2], -1, 1))).max()), 2)
            vr["materials"][mname] = e
        vals = lambda k: [v[k] for v in vr["materials"].values() if v.get(k) is not None]
        vr["max_center_error_255"] = max(vals("basecolor_center_max_255") + vals("roughness_center_max_255") +
                                         vals("metallic_center_max_255"), default=None)
        vr["max_border_bleed_255"] = max(vals("border_bleed_max_255"), default=None)
        vr["centers_ok"] = vr["max_center_error_255"] is not None and vr["max_center_error_255"] <= tol
        vr["bleed_detected"] = bool(vr["max_border_bleed_255"] is not None and vr["max_border_bleed_255"] > bleed_tol)
        vr["bleed_materials"] = sorted(k for k, v in vr["materials"].items() if (v.get("border_bleed_max_255") or 0) > bleed_tol)
        vr["pass"] = vr["centers_ok"] and not vr["bleed_detected"]
        rep["verify"] = vr
    if not keep_source_uv:  # export copy: atlas UVs only, no helper attribute
        if src_uv in me.uv_layers: me.uv_layers.remove(me.uv_layers[src_uv])
        if "atlas_src" in me.attributes: me.attributes.remove(me.attributes["atlas_src"])
        me.uv_layers[ATLAS_UV].active = True; me.uv_layers[ATLAS_UV].active_render = True
    # ---- originals
    for o in objs:
        if delete_originals:
            _remove_object(o.name)
        elif hide_originals:
            o.hide_set(True); o.hide_render = True
    if rep.get("pack", {}).get("warnings"): rep["warnings"] += [f"pack: {w}" for w in rep["pack"]["warnings"]]
    rep["pack"] = {k: rep["pack"].get(k) for k in ("uv_margin", "fits", "islands_crossing_tile_edges")}
    if margin_px < 4: rep["warnings"].append(f"margin_px {margin_px} < 4: mip-mapped sampling bleeds between islands")
    if save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(save)); rep["saved"] = os.path.abspath(save)
    rep["seconds"] = round(time.time() - t0, 2)
    v = rep.get("verify", {})
    rep["summary"] = (f"{len(objs)} objects / {rep['before']['materials']} materials / {rep['before']['draw_calls']} draw calls -> "
                      f"1 / 1 / 1; atlas {size}px margin {margin_px}px; density {rep['texel_density_px_per_m']['min']}-"
                      f"{rep['texel_density_px_per_m']['max']} px/m; center err {v.get('max_center_error_255')} / border bleed "
                      f"{v.get('max_border_bleed_255')} (8-bit); bleed {v.get('bleed_detected')}")
    return rep


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="atlas_bake.py")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--collection"); g.add_argument("--prefix"); g.add_argument("--objects")
    p.add_argument("--out", required=True); p.add_argument("--name", default="ATLAS_Props"); p.add_argument("--material", default="MAT_Atlas")
    p.add_argument("--size", type=int, default=1024); p.add_argument("--margin-px", type=float, default=8)
    p.add_argument("--bake-margin", type=int); p.add_argument("--maps", default=",".join(DEFAULT_MAPS))
    p.add_argument("--orm", action="store_true"); p.add_argument("--samples", type=int, default=4)
    p.add_argument("--no-rotate", action="store_true"); p.add_argument("--normal-convention", default="OPENGL", type=str.upper)
    p.add_argument("--delete-originals", action="store_true"); p.add_argument("--no-hide-originals", action="store_true")
    p.add_argument("--ref-size", type=int, default=256); p.add_argument("--no-verify", action="store_true")
    p.add_argument("--no-uv-check", action="store_true"); p.add_argument("--tol", type=float, default=2.0)
    p.add_argument("--bleed-tol", type=float, default=8.0); p.add_argument("--scripts-dir"); p.add_argument("--save")
    p.add_argument("--method", default="S2A", type=str.upper, choices=("S2A", "SELF"))
    p.add_argument("--cage-extrusion", type=float, default=0.005); p.add_argument("--max-ray-distance", type=float)
    p.add_argument("--keep-source-uv", action="store_true")
    a = p.parse_args(argv)
    return atlas_bake(a.out, a.collection, a.prefix, a.objects, a.name, a.material, a.size, a.margin_px, a.bake_margin,
                      a.maps, a.orm, a.samples, not a.no_rotate, a.normal_convention, a.delete_originals,
                      not a.no_hide_originals, a.ref_size, not a.no_verify, not a.no_uv_check, a.tol, a.bleed_tol,
                      a.scripts_dir, a.save, a.method, a.cage_extrusion, a.max_ray_distance, a.keep_source_uv)


if "ATLAS_OPTS" in globals():
    result = atlas_bake(**ATLAS_OPTS)
elif __name__ == "__main__" and "--" in sys.argv and {"--out", "-h", "--help"} & set(sys.argv[sys.argv.index("--") + 1:]):
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("ATLAS_BAKE " + json.dumps(result, default=str))
else:
    result = {"defined": ["atlas_bake"]}
