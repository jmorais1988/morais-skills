"""Ucupaint (layer-based painting add-on, extensions.blender.org/add-ons/ucupaint) from code: detection, and safe wrappers
around the operators verified to work from scripts (Ucupaint 2.4.9 on Blender 5.2). Every wrapper returns a JSON-able
description of the resulting layer stack (describe()).

Works headless AND in a UI session: setup, add_layer (IMAGE / COLOR / procedural NOISE, BRICK, ...), add_mask, set_layer
(blend / opacity / enable), remove_layer, layer_image, describe, remove_node.
UI session only: bake() (wm.y_bake_channels reads attributes set in its invoke(); headless INVOKE falls back to exec and
raises AttributeError) and therefore flatten(). Headless fallback for baking: scripts/bake_maps.py on the same material.
Painting on a layer: layer_image() -> scripts/paint_ops.py PaintSession(obj, image=img, mode='IMAGE', link_socket=None).

Consent: status() never changes anything. If Ucupaint is installed but disabled, ask the user before enable(consent=True)
(enables for this session; preferences are not saved). If it is not installed, tell the user; don't install silently.

Headless / CLI:
    BLENDER -b [file.blend] --python ucupaint_ops.py -- --status
    BLENDER -b file.blend --python ucupaint_ops.py -- --object Crate --setup --add-layer COLOR:Base:Color:MIX:1.0 \
        --add-layer NOISE:Grime:Color:MULTIPLY:0.4 [--enable-consent] [--save out.blend]
    -> prints one line `UCUPAINT_OPS <json>`. User extensions load only WITHOUT --factory-startup.
Live (exec in the UI session): set UCUPAINT_OPTS = {"object": "Crate", "actions": [
        {"op": "setup"}, {"op": "add_layer", "type": "COLOR", "name": "Base", "color": [0.1, 0.5, 0.9]},
        {"op": "add_layer", "type": "IMAGE", "name": "Paint", "size": 1024},
        {"op": "add_mask", "layer": "Paint", "color": "WHITE"}, {"op": "set_layer", "layer": "Base", "opacity": 0.5},
        {"op": "bake", "size": 1024}, {"op": "save_baked", "folder": "//textures"}]} before exec -> `result`.
Exec without UCUPAINT_OPTS only defines functions and sets `result = {"defined": [...]}`.

Data model (2.4.x): the material gets a ShaderNodeGroup whose node_tree has `.yp.is_ypaint_node`; mat.yp.active_ypaint_node
names it. tree.yp.channels (Color/Alpha/AO/Metallic/Roughness/Normal ...: type RGB/VALUE/NORMAL) map to group outputs wired
into the BSDF. tree.yp.layers[0] is the TOP layer; each layer is its own node group (layer.group_node) with a source node
(Image Texture / RGB / procedural), per-channel settings layer.channels[i] (enable, blend_type, intensity_value) and
masks. Opacity / colour values live on group-node input sockets: set them with common.set_entity_prop_value(), not
setattr (setattr alone doesn't change the shader - verified by bake).
"""
import bpy, addon_utils, json, os, sys

PKG_CANDIDATES = ("bl_ext.blender_org.ucupaint", "ucupaint")
LAYER_TYPES = ('IMAGE', 'BRICK', 'CHECKER', 'GRADIENT', 'MAGIC', 'MUSGRAVE', 'NOISE', 'VORONOI', 'WAVE', 'VCOL', 'BACKGROUND',
               'COLOR', 'GROUP', 'HEMI', 'GABOR', 'EDGE_DETECT', 'AO')
MASK_TYPES = ('IMAGE', 'BRICK', 'CHECKER', 'GRADIENT', 'MAGIC', 'MUSGRAVE', 'NOISE', 'VORONOI', 'WAVE', 'VCOL', 'HEMI',
              'OBJECT_INDEX', 'COLOR_ID', 'BACKFACE', 'EDGE_DETECT', 'MODIFIER', 'GABOR', 'AO')
BLEND_TYPES = ('MIX', 'ADD', 'SUBTRACT', 'MULTIPLY', 'SCREEN', 'OVERLAY', 'DIFFERENCE', 'DIVIDE', 'DARKEN', 'LIGHTEN', 'HUE',
               'SATURATION', 'VALUE', 'COLOR', 'SOFT_LIGHT', 'LINEAR_LIGHT', 'DODGE', 'BURN', 'EXCLUSION')


# ---------------------------------------------------------------- detection
def _installed_module():
    names = {m.__name__ for m in addon_utils.modules(refresh=False)}
    return next((p for p in PKG_CANDIDATES if p in names), None)


def _enabled_module():
    addons = bpy.context.preferences.addons
    return next((p for p in PKG_CANDIDATES if p in addons), None)


def status():
    """Never changes anything. installed/enabled/version/ui_session + a message saying what to do."""
    enabled, installed = _enabled_module(), _installed_module()
    out = {"installed": bool(installed or enabled), "enabled": bool(enabled), "module": enabled or installed,
           "ui_session": not bpy.app.background, "blender": bpy.app.version_string}
    if enabled:
        try:
            out["version"] = _common().get_current_version_str()
        except Exception:
            out["version"] = None
        out["message"] = "Ucupaint enabled" + ("" if out["ui_session"] else " (headless: bake() unavailable, use scripts/bake_maps.py)")
    elif installed:
        out["message"] = ("Ucupaint is installed but disabled: ask the user before enabling "
                          "(enable(consent=True) enables it for this session only)")
    else:
        out["message"] = ("Ucupaint is not installed: ask the user to install it (Edit > Preferences > Get Extensions > "
                          "'Ucupaint', or extensions.blender.org/add-ons/ucupaint). Nothing was changed. Native Texture "
                          "Paint (scripts/paint_ops.py) works without it.")
    return out


def enable(consent=False):
    if _enabled_module():
        return status()
    if not consent:
        return dict(status(), error="refused: enabling an add-on needs the user's consent (enable(consent=True))")
    mod = _installed_module()
    if not mod:
        return dict(status(), error="not installed")
    # Not saved by this call; it persists only if the user's "Auto-Save Preferences" is on (they consented to enabling).
    addon_utils.enable(mod, default_set=True)
    return status()


def _require():
    mod = _enabled_module()
    if not mod:
        raise RuntimeError(status()["message"])
    return mod


def _common():
    import importlib
    return importlib.import_module(_require() + ".common")


def _prefs():
    return bpy.context.preferences.addons[_require()].preferences


# ---------------------------------------------------------------- context helpers
def _view3d():
    wm = bpy.context.window_manager
    for w in (wm.windows if wm and not bpy.app.background else []):
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                return w, a, next(r for r in a.regions if r.type == 'WINDOW')
    return None


def _activate(obj, mat=None):
    vl = bpy.context.view_layer
    if bpy.context.object and bpy.context.object.mode != 'OBJECT' and bpy.context.object != obj:
        with _ctx(bpy.context.object):
            bpy.ops.object.mode_set(mode='OBJECT')
    vl.objects.active = obj
    obj.select_set(True)
    if mat is not None:
        idx = next((i for i, s in enumerate(obj.material_slots) if s.material == mat), None)
        if idx is not None:
            obj.active_material_index = idx


def _ctx(obj):
    v = _view3d()
    kw = dict(active_object=obj, object=obj, selected_objects=[obj], selected_editable_objects=[obj])
    if v:
        kw.update(window=v[0], area=v[1], region=v[2])
    return bpy.context.temp_override(**kw)


def _obj(o):
    return bpy.data.objects[o] if isinstance(o, str) else o


def yp_node(obj):
    """(material, group node, tree.yp) of the active Ucupaint node on the object's active material, or (mat, None, None)."""
    obj = _obj(obj)
    mat = obj.active_material
    if not mat or not mat.node_tree:
        return mat, None, None
    node = mat.node_tree.nodes.get(getattr(mat, "yp", None) and mat.yp.active_ypaint_node or "")
    if node is None:
        node = next((n for n in mat.node_tree.nodes if n.type == 'GROUP' and n.node_tree and getattr(n.node_tree, "yp", None)
                     and n.node_tree.yp.is_ypaint_node), None)
    return mat, node, (node.node_tree.yp if node else None)


def _layer(yp, layer):
    if isinstance(layer, int):
        return yp.layers[layer], layer
    idx = next((i for i, l in enumerate(yp.layers) if l.name == layer), None)
    if idx is None:
        raise KeyError(f"no Ucupaint layer '{layer}' (have {[l.name for l in yp.layers]})")
    return yp.layers[idx], idx


def _channel_idx(yp, channel):
    if channel in (None, 'ALL', -1, '-1'):
        return '-1' if channel is not None else '0'
    if isinstance(channel, int):
        return str(channel)
    idx = next((i for i, c in enumerate(yp.channels) if c.name == channel), None)
    if idx is None:
        raise KeyError(f"no channel '{channel}' (have {[c.name for c in yp.channels]})")
    return str(idx)


def _call(obj, opname, *args, **kw):
    with _ctx(obj):
        return sorted(getattr(bpy.ops.wm, opname)(*args, **kw))


def _unique(name, taken):
    if name not in taken:
        return name
    i = 1
    while f"{name}.{i:03d}" in taken:
        i += 1
    return f"{name}.{i:03d}"


def _set_opacity(entity, value, layer=None):
    """Write an opacity socket (common.set_entity_prop_value), then toggle the owning layer's enable so Ucupaint
    reconnects its nodes - measured: a value written right after y_new_layer was otherwise ignored by the shader."""
    kw = {"layer": layer} if layer is not None else {}
    _common().set_entity_prop_value(entity, 'intensity_value', float(value), **kw)
    owner = layer if layer is not None else entity
    e = owner.enable
    owner.enable = not e
    owner.enable = e


# ---------------------------------------------------------------- describe
def describe(obj):
    obj = _obj(obj)
    mat, node, yp = yp_node(obj)
    if yp is None:
        return {"object": obj.name, "material": mat.name if mat else None, "ucupaint": False}
    c = _common()
    out = {"object": obj.name, "material": mat.name, "ucupaint": True, "node": node.name, "tree": node.node_tree.name,
           "version": yp.version, "use_baked": yp.use_baked, "active_layer": yp.active_layer_index,
           "channels": [], "layers": []}
    for ch in yp.channels:
        bn = node.node_tree.nodes.get(ch.baked) if ch.baked else None
        out["channels"].append({"name": ch.name, "type": ch.type, "colorspace": ch.colorspace,
                                "baked_image": bn.image.name if bn is not None and bn.image else None})
    for l in yp.layers:
        src = c.get_layer_source(l)
        d = {"name": l.name, "type": l.type, "enable": l.enable,
             "opacity": round(float(c.get_entity_prop_value(l, 'intensity_value')), 4),
             "image": src.image.name if src is not None and getattr(src, "image", None) else None,
             "uv": getattr(l, "uv_name", None),
             "channels": {yp.channels[i].name: {"enable": lc.enable, "blend": lc.blend_type,
                                                "opacity": round(float(c.get_entity_prop_value(lc, 'intensity_value', layer=l)), 4)}
                          for i, lc in enumerate(l.channels) if i < len(yp.channels)},
             "masks": []}
        for m in l.masks:
            ms = c.get_mask_source(m)
            d["masks"].append({"name": m.name, "type": m.type, "enable": m.enable, "blend": m.blend_type,
                               "opacity": round(float(c.get_entity_prop_value(m, 'intensity_value', layer=l)), 4),
                               "image": ms.image.name if ms is not None and getattr(ms, "image", None) else None})
        out["layers"].append(d)
    return out


# ---------------------------------------------------------------- operations
def setup(obj, material=None, color=True, alpha=False, ao=False, metallic=False, roughness=True, normal=False,
          bsdf='BSDF_PRINCIPLED', linear_blending=True):
    """Quick node setup on the object's material (created if missing). Reuses the existing Principled BSDF
    (EXEC_DEFAULT skips the invoke that would find it -> without target_bsdf_name a duplicate BSDF + output appear).
    Idempotent: returns the existing stack if the material already has a Ucupaint node."""
    obj = _obj(obj)
    _require()
    if material is not None:
        mat = bpy.data.materials.get(material) if isinstance(material, str) else material
        if mat is None:
            mat = bpy.data.materials.new(material)
        if mat.name not in [s.material.name for s in obj.material_slots if s.material]:
            obj.data.materials.append(mat)
    else:
        mat = obj.active_material
        if mat is None:
            mat = bpy.data.materials.new(f"MAT_{obj.name}")
            obj.data.materials.append(mat)
    _activate(obj, mat)
    if yp_node(obj)[2] is not None:
        return dict(describe(obj), existing=True)
    target = next((n.name for n in mat.node_tree.nodes if n.type == bsdf and any(l.to_node.type == 'OUTPUT_MATERIAL'
                   for l in n.outputs[0].links)), "")
    ret = _call(obj, "y_quick_ypaint_node_setup", 'EXEC_DEFAULT', type=bsdf, color=color, alpha=alpha, ao=ao,
                metallic=metallic, roughness=roughness, normal=normal, use_linear_blending=linear_blending,
                switch_to_material_view=False, target_bsdf_name=target)
    return dict(describe(obj), ret=ret, reused_bsdf=target or None)


def add_layer(obj, type='IMAGE', name=None, channel='Color', blend='MIX', opacity=1.0, color=(1.0, 1.0, 1.0), size=1024,
              uv_map=None, texcoord='UV', hdr=False):
    """New layer on top of the active layer. channel: name/index, or 'ALL'. color = linear RGB for COLOR layers.
    IMAGE layers get a new transparent image (paint it via layer_image() + paint_ops.py)."""
    obj = _obj(obj)
    mat, node, yp = yp_node(obj)
    if yp is None:
        raise RuntimeError("no Ucupaint node: run setup() first")
    if type not in LAYER_TYPES or blend not in BLEND_TYPES:
        raise ValueError(f"type in {LAYER_TYPES}, blend in {BLEND_TYPES}")
    _activate(obj, mat)
    taken = set(bpy.data.images.keys()) | {l.name for l in yp.layers}
    name = _unique(name or type.title(), taken)
    uv = uv_map or (obj.data.uv_layers.active.name if obj.data.uv_layers else "")
    w, h = (size, size) if isinstance(size, int) else size
    ret = _call(obj, "y_new_layer", 'EXEC_DEFAULT', type=type, name=name, channel_idx=_channel_idx(yp, channel),
                blend_type=blend, solid_color=tuple(color[:3]), width=w, height=h, hdr=hdr, uv_map=uv, texcoord_type=texcoord)
    layer, _ = _layer(yp, name)
    if opacity != 1.0:
        _set_opacity(layer, opacity)
    return dict(describe(obj), ret=ret, added=name)


def set_layer(obj, layer, blend=None, opacity=None, enable=None, channel='Color', channel_opacity=None, channel_enable=None):
    """Layer opacity (whole layer) and per-channel blend / opacity / enable. Values go to the node sockets."""
    obj = _obj(obj)
    mat, node, yp = yp_node(obj)
    l, idx = _layer(yp, layer)
    c = _common()
    if opacity is not None:
        _set_opacity(l, opacity)
    if enable is not None:
        l.enable = bool(enable)
    ci = int(_channel_idx(yp, channel)) if channel not in ('ALL', -1, '-1') else None
    lcs = [l.channels[ci]] if ci is not None else list(l.channels)
    for lc in lcs:
        if blend is not None:
            if blend not in BLEND_TYPES:
                raise ValueError(f"blend in {BLEND_TYPES}")
            lc.blend_type = blend
        if channel_opacity is not None:
            _set_opacity(lc, channel_opacity, layer=l)
        if channel_enable is not None:
            lc.enable = bool(channel_enable)
    return describe(obj)


def add_mask(obj, layer, type='IMAGE', name=None, color='WHITE', blend='MULTIPLY', opacity=1.0, size=1024, uv_map=None):
    """Mask on `layer` (IMAGE masks: WHITE = fully visible, BLACK = hidden; paint them with paint_ops, Non-Color)."""
    obj = _obj(obj)
    mat, node, yp = yp_node(obj)
    l, idx = _layer(yp, layer)
    if type not in MASK_TYPES:
        raise ValueError(f"type in {MASK_TYPES}")
    _activate(obj, mat)
    yp.active_layer_index = idx
    name = _unique(name or f"{l.name} Mask", set(bpy.data.images.keys()) | {m.name for m in l.masks})
    uv = uv_map or (obj.data.uv_layers.active.name if obj.data.uv_layers else "")
    w, h = (size, size) if isinstance(size, int) else size
    ret = _call(obj, "y_new_layer_mask", 'EXEC_DEFAULT', type=type, name=name, width=w, height=h, color_option=color,
                uv_name=uv, blend_type=blend)
    l, _ = _layer(yp, layer)
    m = next(m for m in l.masks if m.name == name)
    if opacity != 1.0:
        _set_opacity(m, opacity, layer=l)
    return dict(describe(obj), ret=ret, added_mask=name)


def remove_layer(obj, layer):
    """Removes a layer (its single-user images too; never deletes files on disk). Refreshes Ucupaint's UI cache first
    (the operator indexes wm.ypui.layer_ui.channels, which only the panel draw fills -> IndexError otherwise)."""
    obj = _obj(obj)
    mat, node, yp = yp_node(obj)
    l, idx = _layer(yp, layer)
    removed = l.name
    _activate(obj, mat)
    yp.active_layer_index = idx
    import importlib
    ui = importlib.import_module(_require() + ".ui")
    with _ctx(obj):
        ui.update_yp_ui()
    ret = _call(obj, "y_remove_layer", 'EXEC_DEFAULT', remove_children=False, remove_on_disk=False)
    return dict(describe(obj), ret=ret, removed=removed)


def layer_image(obj, layer):
    """(image, uv_map_name) painted by an IMAGE layer - hand to paint_ops.PaintSession(obj, image=img, mode='IMAGE')."""
    obj = _obj(obj)
    mat, node, yp = yp_node(obj)
    l, _ = _layer(yp, layer)
    src = _common().get_layer_source(l)
    if src is None or not getattr(src, "image", None):
        raise ValueError(f"layer '{l.name}' ({l.type}) has no image")
    return src.image, getattr(l, "uv_name", None)


def _baked_stats(img):
    import numpy as np
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    a = a.reshape(h, w, 4)
    cov = a[..., 3] > 0.5
    return {"image": img.name, "size": [w, h], "colorspace": img.colorspace_settings.name, "coverage": round(float(cov.mean()), 4),
            "mean_rgb": [round(float(v), 4) for v in (a[cov][:, :3].mean(axis=0) if cov.any() else a[..., :3].mean(axis=(0, 1)))],
            "min": round(float(a[..., :3].min()), 4), "max": round(float(a[..., :3].max()), 4)}


def bake(obj, size=1024, samples=1, margin=5, uv_map=None, only_active_channel=False, fxaa=True, device='CPU'):
    """Bake every used channel to images inside the Ucupaint tree (UI session only). Returns per-channel pixel stats.
    Ucupaint preferences skip_property_popups/default_image_resolution are overridden during the call and restored."""
    obj = _obj(obj)
    if bpy.app.background or _view3d() is None:
        return {"error": "Ucupaint bake needs a UI session (wm.y_bake_channels uses invoke-only state). Headless: "
                         "scripts/bake_maps.py on this material, or run in the live session.", "baked": False}
    mat, node, yp = yp_node(obj)
    if yp is None:
        raise RuntimeError("no Ucupaint node on the active material")
    _activate(obj, mat)
    w, h = (size, size) if isinstance(size, int) else size
    for ch in yp.channels:  # invoke() reuses an existing baked image's size -> rescale first
        bn = node.node_tree.nodes.get(ch.baked) if ch.baked else None
        if bn is not None and bn.image and tuple(bn.image.size) != (w, h):
            bn.image.scale(w, h)
    p = _prefs()
    saved = {k: getattr(p, k) for k in ("skip_property_popups", "default_image_resolution") if hasattr(p, k)}
    try:
        p.skip_property_popups = True
        if "default_image_resolution" in saved:
            p.default_image_resolution = 'DEFAULT'
        ret = _call(obj, "y_bake_channels", 'INVOKE_DEFAULT', width=w, height=h, use_custom_resolution=True, samples=samples,
                    margin=margin, uv_map=uv_map or obj.data.uv_layers.active.name, only_active_channel=only_active_channel,
                    fxaa=fxaa, bake_device=device)
    except RuntimeError as e:
        return dict(describe(obj), error=str(e).strip(), baked=False)
    finally:
        for k, v in saved.items():
            setattr(p, k, v)
    stats = {}
    for ch in yp.channels:
        bn = node.node_tree.nodes.get(ch.baked) if ch.baked else None
        if bn is not None and bn.image:
            stats[ch.name] = _baked_stats(bn.image)
    out = dict(describe(obj), ret=ret, baked=bool(stats), stats=stats)
    wrong = [k for k, s in stats.items() if s["size"] != [w, h]]
    if wrong:
        out["warning"] = f"baked size differs from requested for {wrong}"
    return out


def save_baked(obj, folder, prefix=None, file_format='PNG'):
    """Write every baked channel image to <folder>/<prefix>_<Channel>.png (prefix default: material name)."""
    obj = _obj(obj)
    mat, node, yp = yp_node(obj)
    folder_abs = bpy.path.abspath(folder)
    os.makedirs(folder_abs, exist_ok=True)
    out = []
    for ch in yp.channels:
        bn = node.node_tree.nodes.get(ch.baked) if ch.baked else None
        if bn is None or not bn.image:
            continue
        path = os.path.join(folder_abs, f"{prefix or mat.name}_{ch.name.replace(' ', '')}.png")
        img = bn.image
        img.filepath_raw, img.file_format = path, file_format
        img.save()
        out.append({"channel": ch.name, "path": path, "exists": os.path.exists(path), "size": list(img.size)})
    return out


def remove_node(obj, keep_baked=True):
    """Remove the Ucupaint node. If channels are baked, Ucupaint rewires the baked images into the material
    ('Baked Textures' frame) - the flattened, add-on-free material for export. Unbaked stacks are simply deleted."""
    obj = _obj(obj)
    mat, node, yp = yp_node(obj)
    if yp is None:
        return describe(obj)
    baked = any(c.baked for c in yp.channels)
    if not baked and keep_baked:
        return dict(describe(obj), error="not baked: bake() first or remove_node(obj, keep_baked=False)")
    _activate(obj, mat)
    if baked:
        yp.use_baked = True
    ret = _call(obj, "y_remove_yp_node", 'EXEC_DEFAULT')
    nt = mat.node_tree
    return {"ret": ret, "material": mat.name, "ucupaint": yp_node(obj)[2] is not None,
            "image_nodes": [{"node": n.name, "image": n.image.name if n.image else None,
                             "to": [(l.to_node.name, l.to_socket.name) for l in n.outputs[0].links]}
                            for n in nt.nodes if n.bl_idname == 'ShaderNodeTexImage']}


def flatten(obj, folder, size=1024, confirm=False, **bake_kw):
    """bake -> save_baked -> remove_node: the stack becomes plain image textures (destructive: needs confirm=True)."""
    if not confirm:
        return {"error": "flatten removes the layer stack: call with confirm=True after saving the .blend"}
    b = bake(obj, size=size, **bake_kw)
    if not b.get("baked"):
        return b
    saved = save_baked(obj, folder)
    return {"bake": b.get("stats"), "saved": saved, "removed": remove_node(obj)}


# ---------------------------------------------------------------- entry points
ACTIONS = {"setup": setup, "add_layer": add_layer, "set_layer": set_layer, "add_mask": add_mask, "remove_layer": remove_layer,
           "bake": bake, "save_baked": save_baked, "remove_node": remove_node, "flatten": flatten, "describe": describe}


def run(opts):
    if opts.get("enable_consent"):
        enable(consent=True)
    st = status()
    if not st["enabled"]:
        return {"status": st}
    obj = _obj(opts["object"])
    log = []
    for a in opts.get("actions", []):
        a = dict(a)
        op = a.pop("op")
        try:
            r = ACTIONS[op](obj, **a)
            log.append({"op": op, "ok": "error" not in r if isinstance(r, dict) else True, "error": r.get("error") if isinstance(r, dict) else None})
        except Exception as e:
            log.append({"op": op, "ok": False, "error": repr(e)})
            break
    return {"status": st, "log": log, "stack": describe(obj)}


def _cli():
    import argparse
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="ucupaint_ops.py")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--object")
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--add-layer", action="append", default=[], help="TYPE:NAME[:CHANNEL[:BLEND[:OPACITY]]]")
    ap.add_argument("--enable-consent", action="store_true", help="user agreed to enable Ucupaint for this session")
    ap.add_argument("--save")
    a = ap.parse_args(argv)
    if a.status or not a.object:
        return {"status": status()}
    acts = [{"op": "setup"}] if a.setup else []
    for spec in a.add_layer:
        p = spec.split(":")
        d = {"op": "add_layer", "type": p[0].upper(), "name": p[1] if len(p) > 1 else None}
        if len(p) > 2: d["channel"] = p[2]
        if len(p) > 3: d["blend"] = p[3].upper()
        if len(p) > 4: d["opacity"] = float(p[4])
        acts.append(d)
    out = run({"object": a.object, "actions": acts, "enable_consent": a.enable_consent})
    if a.save and out.get("log") is not None:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save), copy=True)
        out["saved"] = os.path.abspath(a.save)
    return out


if "UCUPAINT_OPTS" in globals():
    result = run(globals()["UCUPAINT_OPTS"])
elif __name__ == "__main__" and bpy.app.background and "--" in sys.argv:
    print("UCUPAINT_OPS " + json.dumps(_cli(), default=str))
else:
    result = {"defined": ["status", "enable", "describe", "setup", "add_layer", "set_layer", "add_mask", "remove_layer",
                          "layer_image", "bake", "save_baked", "remove_node", "flatten", "yp_node", "run"]}
