"""Bake any (procedural / layered) material on a mesh to texture files for export - Cycles, headless-safe.

Live session (Blender:execute_blender_code): exec this file, then
    result = bake_maps("Rock_low", r"D:/out/rock", maps=("BASECOLOR", "NORMAL"), size=1024, source_objects=["Rock_high"])
or set BAKE_OPTS before exec: {"object": "Rock_low", "out": r"D:/out", "maps": [...], "size": 1024, "source": [...],
    "cage": "Rock_cage", "normal_convention": "DIRECTX", "orm": True, "bit_depth": 16, "uv_map": "UVMap",
    "ao_samples": 8, "ao_distance": 0.5, "margin_type": "EXTEND", ...}  -> `result` dict
Headless / CLI (prints one line: BAKE_MAPS <json>):
    blender -b file.blend --python bake_maps.py -- --object OBJ --out <dir> [--maps BASECOLOR,NORMAL] [--size 1024]
        [--margin 16] [--margin-type ADJACENT_FACES|EXTEND] [--samples 16] [--ao-samples 8] [--ao-distance 0.5]
        [--uv-map UVMap] [--source HighPoly1,HighPoly2] [--cage-extrusion 0.02] [--cage CageObj]
        [--max-ray-distance 0.1] [--device CPU|GPU] [--bit-depth 8|16|32] [--format PNG|EXR]
        [--normal-convention OPENGL|DIRECTX | --directx] [--orm] [--udim auto|on|off] [--triangulate]
        [--auto-uv] [--no-unwrap] [--save out.blend]

Maps -> files <out>/<object>_<MAP>[.<UDIM>].png|exr (colour: BASECOLOR/EMIT sRGB; others Non-Color):
  BASECOLOR  DIFFUSE, pass_filter {'COLOR'}. Cycles weights diffuse colour by (1-metallic)(1-transmission) and also by
             the dielectric specular, coat and sheen layers (measured 5.2: default Principled 0.963x, coat+sheen shifts
             hue), so Metallic, Transmission Weight, Specular IOR Level, Coat Weight and Sheen Weight are temporarily 0
             during this bake (links and values restored). Result matches an emission bake of the base colour exactly.
  ROUGHNESS  ROUGHNESS          AO  AO (scene geometry occludes)          EMIT  EMIT
  NORMAL     tangent space; OPENGL (+X +Y +Z, file _NORMAL) or DIRECTX (green = -Y, file _NORMAL_DX)
  METALLIC   no native pass: each top-level Principled BSDF's shader output links are re-routed through a temp Emission
             shader fed by its Metallic link/value, baked as EMIT, then links restored (verified by link signature).
  ORM        orm=True also bakes AO/ROUGHNESS/METALLIC and writes <object>_ORM (R=AO, G=Roughness, B=Metallic).
source_objects -> selected-to-active (high -> low) with cage_extrusion, or a cage object (same topology as the low mesh,
hidden from render while baking) and max_ray_distance (0 = unlimited). Material edits then apply to the sources.
UVs are required: a mesh without a UV map raises unless auto_uv=True (Smart UV Project, reported as a warning).
uv_map picks the target UV map by name (default: the active map; a missing name raises and lists the available maps;
with auto_uv on a UV-less mesh the generated map takes that name) - the bake op gets it explicitly, so the active /
render-active flags do not matter. ao_samples = Cycles sample count for the AO map only (default samples).
ao_distance = Cycles AO ray length in metres = scene.world.light_settings.distance (5.2; a scene without a world gets a
temporary one; restored). margin_type = scene.render.bake.margin_type: ADJACENT_FACES (default, follows the mesh) or
EXTEND (plain outward smear, safer for many tiny islands). All four are reported (uv_map, ao_samples, ao_distance,
margin_type; ao_distance = the scene value when not overridden, None without a world).
UDIM: udim='auto' bakes to a tiled image when the target UVs occupy tiles other than 1001 (Cycles supports tiled bake
since 3.2); each used tile is created, filled and saved via the <UDIM> token; bake margin stays inside each tile.
Output depth: 8-bit PNG (default), 16-bit PNG (float buffer), EXR half (16) or full float (32). Stats of float images
are linear values. triangulate=True adds a temporary Triangulate modifier (Beauty, keep normals) so the tangent basis
matches a mesh that is triangulated the same way at export. device='GPU' enables the first available Cycles GPU
backend (OPTIX, CUDA, HIP, ONEAPI, METAL) for this bake, falls back to CPU with a warning, and restores preferences.
Engine, samples, device, bake settings, selection, visibility and temporary modifiers are restored.
Limits: Principled nodes inside node groups are not re-routed for METALLIC/BASECOLOR; pure Emission shaders in the
tree leak into METALLIC; stats are over baked pixels (alpha>0 before the gutter is filled).
Returns `result` dict: per map path(s), seconds, min/max/mean/std, coverage, constant flag (per tile for UDIM).
"""
import bpy, os, sys, time, json, math, warnings
import numpy as np

ALL_MAPS = ('BASECOLOR', 'ROUGHNESS', 'NORMAL', 'AO', 'METALLIC', 'EMIT')
BAKE_TYPE = {'BASECOLOR': 'DIFFUSE', 'ROUGHNESS': 'ROUGHNESS', 'NORMAL': 'NORMAL', 'AO': 'AO', 'METALLIC': 'EMIT', 'EMIT': 'EMIT'}
SRGB = {'BASECOLOR', 'EMIT'}
TMP = "__BAKE_TMP__"
GPU_BACKENDS = ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL')


def _sock(coll, names):
    for key in ('identifier', 'name'):
        for n in names:
            for s in coll:
                if getattr(s, key) == n and getattr(s, 'enabled', True):
                    return s
    return None


def link_signature(nt):
    return sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in nt.links)


def _principleds(mat):
    return [n for n in mat.node_tree.nodes if n.bl_idname == 'ShaderNodeBsdfPrincipled']


def _zero_inputs(mat, names):
    """Unlink + zero the named Principled inputs; returns undo list."""
    nt, undo = mat.node_tree, []
    for p in _principleds(mat):
        for nm in names:
            s = _sock(p.inputs, (nm,))
            if s is None: continue
            src = s.links[0].from_socket if s.is_linked else None
            undo.append((s, src, s.default_value))
            if src: nt.links.remove(s.links[0])
            s.default_value = 0.0
    return undo


def _restore_inputs(mat, undo):
    for s, src, v in reversed(undo):
        s.default_value = v
        if src: mat.node_tree.links.new(src, s)


def _route_metallic(mat):
    nt, undo = mat.node_tree, []
    for p in _principleds(mat):
        bsdf, met = _sock(p.outputs, ('BSDF',)), _sock(p.inputs, ('Metallic',))
        targets = [l.to_socket for l in bsdf.links]
        if not targets: continue
        em = nt.nodes.new('ShaderNodeEmission'); em.name = TMP + "METAL_" + p.name; em.location = p.location
        col = _sock(em.inputs, ('Color',))
        if met.is_linked: nt.links.new(met.links[0].from_socket, col)
        else: col.default_value = (met.default_value,) * 3 + (1.0,)
        _sock(em.inputs, ('Strength',)).default_value = 1.0
        for t in targets: nt.links.new(_sock(em.outputs, ('Emission',)), t)
        undo.append((p, targets, em))
    return undo


def _unroute_metallic(mat, undo):
    nt = mat.node_tree
    for p, targets, em in undo:
        nt.nodes.remove(em)
        for t in targets: nt.links.new(_sock(p.outputs, ('BSDF',)), t)


def _pixels(img):
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32); img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)


def _stats(img, name):
    px = _pixels(img)
    mask = px[..., 3] > 0.5
    vals = px[..., :3][mask] if mask.any() else px[..., :3].reshape(-1, 3)
    e = {"min": round(float(vals.min()), 4), "max": round(float(vals.max()), 4), "mean": round(float(vals.mean()), 4),
         "std": round(float(vals.std()), 4), "mean_rgb": [round(float(v), 4) for v in vals.mean(0)],
         "coverage": round(float(mask.mean()), 4)}
    e["constant"] = bool(e["max"] - e["min"] < 2 / 255 or e["std"] < 0.004)
    if name == 'NORMAL':
        dev = float(np.abs(vals - np.array([0.5, 0.5, 1.0], dtype=np.float32)).mean())
        e["mean_abs_dev_from_flat"] = round(dev, 4); e["flat"] = dev < 0.01
    px[..., 3] = 1.0  # solid alpha for export (gutter pixels stay black)
    img.pixels.foreach_set(px.ravel())
    return e


def _unwrap(obj):
    vl = bpy.context.view_layer
    for o in vl.objects:
        if o.select_get(): o.select_set(False)
    obj.select_set(True); vl.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.005)
    bpy.ops.object.mode_set(mode='OBJECT')


def _uv_tiles(obj, uv_name):
    me = obj.data; lay = me.uv_layers[uv_name]
    if not len(me.polygons): return {1001}
    uv = np.empty(len(me.loops) * 2); lay.uv.foreach_get("vector", uv); uv = uv.reshape(-1, 2)
    ls = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", lt)
    cen = np.add.reduceat(uv, ls, axis=0) / lt[:, None]  # face centroid decides the tile
    t = np.floor(cen).astype(np.int64)
    return {int(1001 + u + 10 * v) for u, v in np.unique(t, axis=0) if 0 <= u <= 9 and v >= 0}


def _enable_gpu(rep):
    """Enable the first Cycles GPU backend with devices; returns an undo tuple or None (CPU fallback)."""
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
    except (KeyError, AttributeError):
        rep["warnings"].append("device GPU: Cycles add-on preferences unavailable - baking on CPU"); return None
    saved_type = prefs.compute_device_type
    prefs.get_devices()
    saved_use = [(d.name, d.type, d.use) for d in prefs.devices]
    for backend in GPU_BACKENDS:
        try:
            prefs.compute_device_type = backend
        except TypeError:
            continue
        prefs.get_devices()
        devs = [d for d in prefs.devices if d.type == backend]
        if devs:
            for d in prefs.devices: d.use = d.type == backend
            rep["notes"].append(f"GPU bake on {backend}: {[d.name for d in devs]}")
            return prefs, saved_type, saved_use
    try: prefs.compute_device_type = saved_type
    except TypeError: pass
    rep["warnings"].append("device GPU: no GPU backend with devices found - baking on CPU")
    return None


def _restore_gpu(undo):
    if not undo: return
    prefs, saved_type, saved_use = undo
    try:
        prefs.compute_device_type = saved_type; prefs.get_devices()
        lookup = {(n, t): u for n, t, u in saved_use}
        for d in prefs.devices:
            if (d.name, d.type) in lookup: d.use = lookup[(d.name, d.type)]
    except Exception:
        pass


def _new_image(name, size, float_buf, tiles, colorspace):
    # colour space is set BEFORE the alpha-0 fill: changing it afterwards frees the generated buffer and Blender
    # regenerates the image opaque black (measured 5.2), which would make every pixel count as "baked".
    if tiles is None:
        img = bpy.data.images.get(name)
        if img is None or tuple(img.size) != (size, size) or img.source != 'GENERATED' or img.is_float != float_buf:
            img = bpy.data.images.new(name, size, size, alpha=True, float_buffer=float_buf)
        img.colorspace_settings.name = colorspace
        img.pixels.foreach_set(np.zeros(size * size * 4, dtype=np.float32))  # alpha 0 = unbaked
        return img
    img = bpy.data.images.new(name, size, size, alpha=True, float_buffer=float_buf, tiled=True)
    img.colorspace_settings.name = colorspace
    for t in sorted(tiles):
        if t != 1001: img.tiles.new(tile_number=t)
    for idx in range(len(img.tiles)):
        img.tiles.active_index = idx
        with bpy.context.temp_override(edit_image=img):
            bpy.ops.image.tile_fill(color=(0, 0, 0, 0), generated_type='BLANK', width=size, height=size,
                                    float=float_buf, alpha=True)
    if 1001 not in tiles:
        try: img.tiles.remove(img.tiles.get(1001))
        except Exception: pass
    return img


def _save(img, path, fmt, bit_depth):
    img.filepath_raw = path
    img.file_format = 'OPEN_EXR' if fmt == 'EXR' else 'PNG'
    if fmt == 'EXR': img.use_half_precision = bit_depth == 16
    img.save()


def bake_maps(obj_name, out_dir, maps=ALL_MAPS, size=2048, margin=16, samples=16, source_objects=None,
              cage_extrusion=0.02, uv_unwrap_if_missing=False, cage_object=None, max_ray_distance=0.0, device='CPU',
              bit_depth=8, file_format='PNG', normal_convention='OPENGL', orm=False, udim='auto', triangulate=False,
              auto_uv=None, uv_map=None, ao_samples=None, ao_distance=None, margin_type=None):
    sc, vl = bpy.context.scene, bpy.context.view_layer
    obj = bpy.data.objects.get(obj_name)
    if obj is None or obj.type != 'MESH':
        raise ValueError(f"mesh object {obj_name!r} not found")
    sources = [bpy.data.objects[n] for n in (source_objects or [])]
    cage = bpy.data.objects.get(cage_object) if cage_object else None
    if cage_object and (cage is None or cage.type != 'MESH'):
        raise ValueError(f"cage mesh object {cage_object!r} not found")
    if cage is not None and not sources:
        raise ValueError("cage_object needs source_objects (selected-to-active bake)")
    maps = [m.upper() for m in maps]
    bad = [m for m in maps if m not in BAKE_TYPE]
    if bad: raise ValueError(f"unknown maps {bad}; valid {ALL_MAPS}")
    added = [m for m in ('AO', 'ROUGHNESS', 'METALLIC') if orm and m not in maps]
    maps += added
    file_format = file_format.upper().replace('OPEN_EXR', 'EXR')
    if file_format not in ('PNG', 'EXR'): raise ValueError("file_format must be PNG or EXR")
    bit_depth = int(bit_depth)
    if (file_format, bit_depth) not in (('PNG', 8), ('PNG', 16), ('EXR', 16), ('EXR', 32)):
        raise ValueError("bit_depth: PNG 8|16, EXR 16|32")
    normal_convention = normal_convention.upper()
    if normal_convention not in ('OPENGL', 'DIRECTX'): raise ValueError("normal_convention must be OPENGL or DIRECTX")
    float_buf = bit_depth > 8 or file_format == 'EXR'
    ext = '.exr' if file_format == 'EXR' else '.png'
    auto_uv = uv_unwrap_if_missing if auto_uv is None else auto_uv
    if margin_type is not None:
        margin_type = str(margin_type).upper()
        if margin_type not in ('ADJACENT_FACES', 'EXTEND'): raise ValueError("margin_type must be ADJACENT_FACES or EXTEND")
    ao_samples = samples if ao_samples is None else int(ao_samples)
    if ao_samples < 1: raise ValueError("ao_samples must be >= 1")
    if ao_distance is not None:
        ao_distance = float(ao_distance)
        if ao_distance <= 0: raise ValueError("ao_distance must be > 0 (metres)")
    os.makedirs(out_dir, exist_ok=True)
    rep = {"object": obj.name, "size": size, "samples": samples, "ao_samples": ao_samples, "selected_to_active": bool(sources),
           "sources": [s.name for s in sources], "cage": cage.name if cage else None, "max_ray_distance": max_ray_distance,
           "format": file_format, "bit_depth": bit_depth, "normal_convention": normal_convention,
           "maps": {}, "warnings": [], "notes": []}
    if added: rep["notes"].append(f"orm: added maps {added}")
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT'); rep["notes"].append("switched to OBJECT mode")
    # visibility / selection bookkeeping
    tracked = [obj] + sources + ([cage] if cage else [])
    vis = {o.name: (o.hide_get(), o.hide_select, o.hide_render) for o in tracked}
    sel = [o.name for o in vl.objects if o.select_get()]; active = vl.objects.active
    for o in [obj] + sources:
        o.hide_set(False); o.hide_select = False; o.hide_render = False
    if not obj.data.uv_layers:
        if not auto_uv:
            raise ValueError(f"{obj.name} has no UV map: unwrap it (scripts/uv_tools.py) or pass auto_uv=True / --auto-uv")
        _unwrap(obj); rep["warnings"].append("no UV map: Smart UV Project applied (auto_uv) - replace with a real unwrap for hero assets")
        if uv_map: obj.data.uv_layers.active.name = uv_map
    if uv_map:
        lay = obj.data.uv_layers.get(uv_map)
        if lay is None:
            raise ValueError(f"{obj.name} has no UV map {uv_map!r}; available: {[l.name for l in obj.data.uv_layers]}")
        uv_name = lay.name
    else:
        uv_name = obj.data.uv_layers.active.name
    rep["uv_map"] = uv_name
    tiles = _uv_tiles(obj, uv_name)
    use_udim = (tiles != {1001}) if udim in ('auto', None) else udim in (True, 'on', 'ON', 1)
    if not use_udim and tiles != {1001}:
        rep["warnings"].append(f"UVs occupy tiles {sorted(tiles)} but udim is off: out-of-0-1 faces wrap into one image")
    rep["udim_tiles"] = sorted(tiles) if use_udim else None
    if cage is not None:
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()); cev = cage.evaluated_get(bpy.context.evaluated_depsgraph_get())
        if len(ev.data.vertices) != len(cev.data.vertices) or len(ev.data.polygons) != len(cev.data.polygons):
            rep["warnings"].append(f"cage {cage.name} topology differs from {obj.name} (verts/faces): Cycles may refuse or misproject")
    # target materials (need image nodes) / shading materials (edited for BASECOLOR/METALLIC)
    if not obj.material_slots or any(s.material is None for s in obj.material_slots):
        m = bpy.data.materials.new("BAKE_" + obj.name)
        if not obj.material_slots: obj.data.materials.append(m)
        for s in obj.material_slots:
            if s.material is None: s.material = m
        rep["warnings"].append(f"empty material slot(s): assigned new {m.name}")
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        for m in {s.material for o in [obj] + sources for s in o.material_slots if s.material}:
            if m.node_tree is None or not getattr(m, 'use_nodes', True):
                m.use_nodes = True; rep["warnings"].append(f"{m.name}: use_nodes enabled")
    tgt_mats = list(dict.fromkeys(s.material for s in obj.material_slots))
    shade_mats = list(dict.fromkeys(s.material for o in (sources or [obj]) for s in o.material_slots if s.material))
    for m in shade_mats:
        if not _principleds(m) and ({'BASECOLOR', 'METALLIC'} & set(maps)):
            rep["warnings"].append(f"{m.name}: no top-level Principled BSDF - METALLIC bakes 0, BASECOLOR not metal-corrected")
    before = {m.name: link_signature(m.node_tree) for m in set(tgt_mats) | set(shade_mats)}
    # render settings
    r, b = sc.render, sc.render.bake
    saved_engine = r.engine
    r.engine = 'CYCLES'; cy = sc.cycles
    saved_cy = {k: getattr(cy, k) for k in ('samples', 'device', 'bake_type', 'use_denoising') if hasattr(cy, k)}
    saved_bake = {p.identifier: getattr(b, p.identifier) for p in b.bl_rna.properties
                  if not p.is_readonly and p.identifier not in ('rna_type',)}
    cy.samples = samples
    gpu_undo = _enable_gpu(rep) if str(device).upper() == 'GPU' else None
    cy.device = 'GPU' if gpu_undo else 'CPU'
    rep["device"] = cy.device
    if hasattr(cy, 'use_denoising'): cy.use_denoising = False
    # margin type (scene.render.bake.margin_type, Blender 3.1+; saved_bake restores it)
    mt_ok = hasattr(b, 'margin_type')
    if margin_type and not mt_ok:
        rep["warnings"].append("margin_type: scene.render.bake.margin_type not available in this Blender - ignored")
    if margin_type and mt_ok: b.margin_type = margin_type
    rep["margin_type"] = b.margin_type if mt_ok else None
    # AO ray distance (Cycles reads scene.world.light_settings.distance; verified 5.2)
    ao_undo = tmp_world = None
    if ao_distance is not None and sc.world is None:
        tmp_world = bpy.data.worlds.new(TMP + "WORLD"); sc.world = tmp_world
        rep["notes"].append("no scene world: temporary world created for ao_distance")
    ls = getattr(sc.world, 'light_settings', None) if sc.world is not None else None
    if ls is None or not hasattr(ls, 'distance'):
        if ao_distance is not None:
            rep["warnings"].append("ao_distance: world.light_settings.distance not available - ignored")
        rep["ao_distance"] = None
    else:
        if ao_distance is not None:
            ao_undo = (ls, ls.distance); ls.distance = ao_distance
        rep["ao_distance"] = round(float(ls.distance), 6)
    tri_mod = None
    pixels_for_orm = {}
    try:
        if triangulate:
            tri_mod = obj.modifiers.new(TMP + "TRIANGULATE", 'TRIANGULATE')
            tri_mod.quad_method = 'BEAUTY'; tri_mod.ngon_method = 'BEAUTY'
            if hasattr(tri_mod, 'keep_custom_normals'): tri_mod.keep_custom_normals = True
            if cage is not None:  # Cycles requires identical face counts between cage and low
                cage_tri = cage.modifiers.new(TMP + "TRIANGULATE", 'TRIANGULATE')
                cage_tri.quad_method = 'BEAUTY'; cage_tri.ngon_method = 'BEAUTY'
            rep["notes"].append("temporary Triangulate modifier (Beauty) during bake - triangulate the export mesh the same way")
        if cage is not None:
            cage.hide_render = True
        for o in vl.objects:
            if o.select_get(): o.select_set(False)
        for o in sources: o.select_set(True)
        obj.select_set(True); vl.objects.active = obj
        for name in maps:
            t0 = time.time()
            img = _new_image(f"{obj.name}_{name}", size, float_buf, tiles if use_udim else None,
                             'sRGB' if name in SRGB else 'Non-Color')
            tmp = []
            for m in tgt_mats:
                nt = m.node_tree; prev = nt.nodes.active
                n = nt.nodes.new('ShaderNodeTexImage'); n.name = TMP + name; n.image = img; n.select = True
                nt.nodes.active = n; tmp.append((m, n, prev))
            undo_zero, undo_route = [], []
            try:
                if name == 'BASECOLOR':
                    # Cycles' DIFFUSE colour pass is also weighted down by the dielectric specular, coat and sheen
                    # layers (measured 5.2: default Principled 0.963x; coat+sheen shifts hue); zero them for the bake.
                    undo_zero = [(m, _zero_inputs(m, ('Metallic', 'Transmission Weight', 'Transmission',
                                                      'Specular IOR Level', 'Coat Weight', 'Sheen Weight')))
                                 for m in shade_mats]
                if name == 'METALLIC':
                    undo_route = [(m, _route_metallic(m)) for m in shade_mats]
                kw = dict(type=BAKE_TYPE[name], width=size, height=size, margin=margin, target='IMAGE_TEXTURES',
                          save_mode='INTERNAL', use_clear=False, use_selected_to_active=bool(sources),
                          cage_extrusion=cage_extrusion, max_ray_distance=max_ray_distance, uv_layer=uv_name)
                if mt_ok: kw["margin_type"] = rep["margin_type"]
                cy.samples = ao_samples if name == 'AO' else samples
                if cage is not None: kw.update(use_cage=True, cage_object=cage.name)
                if name == 'BASECOLOR': kw["pass_filter"] = {'COLOR'}
                if name == 'NORMAL':
                    kw.update(normal_space='TANGENT', normal_r='POS_X', normal_b='POS_Z',
                              normal_g='NEG_Y' if normal_convention == 'DIRECTX' else 'POS_Y')
                bpy.ops.object.bake(**kw)
            finally:
                for m, u in undo_route: _unroute_metallic(m, u)
                for m, u in undo_zero: _restore_inputs(m, u)
                for m, n, prev in tmp:
                    m.node_tree.nodes.remove(n)
                    if prev is not None: m.node_tree.nodes.active = prev
            stem = f"{obj.name}_{name}" + ("_DX" if name == 'NORMAL' and normal_convention == 'DIRECTX' else "")
            if not use_udim:
                e = _stats(img, name)
                path = os.path.abspath(os.path.join(out_dir, stem + ext))
                _save(img, path, file_format, bit_depth)
                e.update(path=path)
                if name in ('AO', 'ROUGHNESS', 'METALLIC'): pixels_for_orm[name] = {1001: _pixels(img)[..., 0].copy()}
            else:
                pattern = os.path.abspath(os.path.join(out_dir, stem + ".<UDIM>" + ext))
                _save(img, pattern, file_format, bit_depth)
                e = {"path": pattern, "tiles": {}}
                for t in sorted(tiles):
                    tp = pattern.replace("<UDIM>", str(t))
                    timg = bpy.data.images.load(tp, check_existing=False)
                    timg.colorspace_settings.name = 'sRGB' if name in SRGB else 'Non-Color'
                    te = _stats(timg, name)
                    timg.filepath_raw = tp; timg.file_format = img.file_format
                    if file_format == 'EXR': timg.use_half_precision = bit_depth == 16
                    timg.save()
                    if name in ('AO', 'ROUGHNESS', 'METALLIC'):
                        pixels_for_orm.setdefault(name, {})[t] = _pixels(timg)[..., 0].copy()
                    te["path"] = tp; e["tiles"][t] = te
                    bpy.data.images.remove(timg)
                tv = list(e["tiles"].values())
                e["constant"] = all(x["constant"] for x in tv)
                if name == 'NORMAL': e["flat"] = all(x.get("flat") for x in tv)
                e["coverage"] = round(float(np.mean([x["coverage"] for x in tv])), 4)
            e["seconds"] = round(time.time() - t0, 2)
            if e["constant"]:
                rep["warnings"].append(f"{name}: constant map" + (f" (mean {e['mean']})" if "mean" in e else "") +
                                       " - fine only if the channel has no variation")
            if e.get("flat"):
                rep["warnings"].append("NORMAL: flat normal map (no detail captured)")
            rep["maps"][name] = e
        if orm:
            t0 = time.time(); orm_rep = {"channels": {"R": "AO", "G": "ROUGHNESS", "B": "METALLIC"}, "paths": []}
            for t in sorted(pixels_for_orm['AO']):
                ao, ro, me_ = pixels_for_orm['AO'][t], pixels_for_orm['ROUGHNESS'][t], pixels_for_orm['METALLIC'][t]
                h, w = ao.shape
                oimg = bpy.data.images.new(f"{obj.name}_ORM" + (f".{t}" if use_udim else ""), w, h, alpha=False, float_buffer=float_buf)
                oimg.colorspace_settings.name = 'Non-Color'
                oimg.pixels.foreach_set(np.dstack([ao, ro, me_, np.ones_like(ao)]).astype(np.float32).ravel())
                path = os.path.abspath(os.path.join(out_dir, f"{obj.name}_ORM" + (f".{t}" if use_udim else "") + ext))
                _save(oimg, path, file_format, bit_depth)
                orm_rep["paths"].append(path)
                bpy.data.images.remove(oimg)
            orm_rep["path"] = orm_rep["paths"][0] if not use_udim else os.path.abspath(os.path.join(out_dir, f"{obj.name}_ORM.<UDIM>{ext}"))
            orm_rep["seconds"] = round(time.time() - t0, 2)
            rep["maps"]["ORM"] = orm_rep
    finally:
        if tri_mod is not None:
            obj.modifiers.remove(tri_mod)
        if cage is not None and cage.modifiers.get(TMP + "TRIANGULATE"):
            cage.modifiers.remove(cage.modifiers[TMP + "TRIANGULATE"])
        if ao_undo is not None:
            try: ao_undo[0].distance = ao_undo[1]
            except Exception: pass
        if tmp_world is not None:
            sc.world = None
            try: bpy.data.worlds.remove(tmp_world)
            except Exception: pass
        r.engine = 'CYCLES'
        for k, v in saved_cy.items():
            try: setattr(cy, k, v)
            except Exception: pass
        for k, v in saved_bake.items():
            try: setattr(b, k, v)
            except Exception: pass
        _restore_gpu(gpu_undo)
        r.engine = saved_engine
        for o in vl.objects:
            if o.select_get(): o.select_set(False)
        for n in sel:
            if n in vl.objects: vl.objects[n].select_set(True)
        vl.objects.active = active
        for n, (h, hs, hr) in vis.items():
            o = bpy.data.objects[n]; o.hide_set(h); o.hide_select = hs; o.hide_render = hr
    after = {m: link_signature(bpy.data.materials[m].node_tree) for m in before}
    rep["links_restored"] = all(before[m] == after[m] for m in before)
    if not rep["links_restored"]:
        rep["warnings"].append("material links differ after bake - inspect " + str([m for m in before if before[m] != after[m]]))
    rep["summary"] = (f"{obj.name}: baked {len(rep['maps'])} map(s) at {size}px into UV {uv_name!r}{' UDIM ' + str(sorted(tiles)) if use_udim else ''} in "
                      f"{round(sum(e.get('seconds', 0) for e in rep['maps'].values()), 1)} s on {rep['device']}; constant: "
                      f"{[k for k, e in rep['maps'].items() if e.get('constant')]}; links restored: {rep['links_restored']}")
    return rep


def _run(o):
    split = lambda v: [x.strip() for x in v.split(',') if x.strip()] if isinstance(v, str) else v
    kw = {"maps": split(o.get("maps")) or ALL_MAPS, "source_objects": split(o.get("source")) or None}
    for k in ("size", "margin", "samples", "cage_extrusion", "uv_unwrap_if_missing", "max_ray_distance", "device",
              "bit_depth", "normal_convention", "orm", "udim", "triangulate", "auto_uv", "uv_map", "ao_samples",
              "ao_distance", "margin_type"):
        if o.get(k) is not None: kw[k] = o[k]
    if o.get("cage") or o.get("cage_object"): kw["cage_object"] = o.get("cage") or o.get("cage_object")
    if o.get("format") or o.get("file_format"): kw["file_format"] = o.get("format") or o.get("file_format")
    if o.get("directx"): kw["normal_convention"] = 'DIRECTX'
    rep = bake_maps(o["object"], o["out"], **kw)
    if o.get("save"):
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(o["save"])); rep["saved"] = os.path.abspath(o["save"])
    return rep


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="bake_maps.py")
    p.add_argument("--object", required=True); p.add_argument("--out", required=True); p.add_argument("--maps")
    p.add_argument("--size", type=int); p.add_argument("--margin", type=int); p.add_argument("--samples", type=int)
    p.add_argument("--source"); p.add_argument("--cage-extrusion", type=float); p.add_argument("--save")
    p.add_argument("--cage"); p.add_argument("--max-ray-distance", type=float)
    p.add_argument("--device", choices=("CPU", "GPU"), type=str.upper)
    p.add_argument("--bit-depth", type=int, choices=(8, 16, 32)); p.add_argument("--format", choices=("PNG", "EXR"), type=str.upper)
    p.add_argument("--normal-convention", choices=("OPENGL", "DIRECTX"), type=str.upper)
    p.add_argument("--directx", action="store_true", default=None); p.add_argument("--orm", action="store_true", default=None)
    p.add_argument("--udim", choices=("auto", "on", "off"), type=str.lower)
    p.add_argument("--triangulate", action="store_true", default=None)
    p.add_argument("--uv-map", dest="uv_map", help="UV map to bake into (default: the active UV map; error if missing)")
    p.add_argument("--ao-samples", dest="ao_samples", type=int, help="Cycles samples for the AO map only (default: --samples)")
    p.add_argument("--ao-distance", dest="ao_distance", type=float,
                   help="AO ray distance in metres (scene.world.light_settings.distance; default: scene value)")
    p.add_argument("--margin-type", dest="margin_type", choices=("ADJACENT_FACES", "EXTEND"), type=str.upper,
                   help="bake margin fill (scene.render.bake.margin_type; default: scene value)")
    p.add_argument("--auto-uv", dest="auto_uv", action="store_true", default=None,
                   help="Smart UV Project when the mesh has no UV map (otherwise an error)")
    p.add_argument("--no-unwrap", dest="no_unwrap", action="store_true",
                   help="kept for compatibility: missing UVs are already an error unless --auto-uv")
    a = vars(p.parse_args(argv)); a.pop("no_unwrap", None)
    if a.get("udim") is not None: a["udim"] = {"auto": "auto", "on": True, "off": False}[a["udim"]]
    return _run(a)


_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if globals().get("BAKE_OPTS"):
    result = _run(dict(BAKE_OPTS))
elif "--object" in _argv:
    result = _cli(_argv)
else:
    result = {"ready": "call bake_maps(obj_name, out_dir, maps=..., size=..., source_objects=...)"}
if "summary" in result:
    print("BAKE_MAPS " + json.dumps(result, default=str))
