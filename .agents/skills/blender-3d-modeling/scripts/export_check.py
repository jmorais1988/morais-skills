"""Export round-trip check for game / web delivery: export objects to FBX / GLB / OBJ with an engine preset, re-import
into a temporary scene, and compare against the source so scale, axis, material, UV, normal and animation losses are
caught before the file reaches the engine.

Headless / CLI (prints one line: EXPORT_CHECK <json>):
    blender -b asset.blend --python export_check.py -- [--objects A,B | --collection NAME | --selection]
        [--formats FBX,GLB,OBJ] [--preset unity|unreal|godot|web] [--out DIR] [--name asset] [--budget-mb 10]
        [--override '{"FBX": {"axis_up": "Z"}}'] [--tol 0.001] [--delete-files]
        [--expect-extensions KHR_materials_clearcoat,...] [--expect-variants Red,Blue|2]
Live (Blender:execute_blender_code): set before exec
    EXPORT_OPTS = {"collection": "Export", "formats": ["FBX", "GLB"], "preset": "unity", "out_dir": "D:/out"}  -> `result`
Without EXPORT_OPTS the file only defines export_check, PRESETS and helpers.

Checks (per format; `issues` fail the format, `warnings` don't):
  preflight     unapplied / negative object scale, unapplied rotation, meshes without UVs, n-gons (engines triangulate
                on import - bake normals on the same triangulation), material names without a MAT_ / M_ / MI_ prefix
                (naming hint only: export copies are expected to carry engine-style names)
  object count  mesh objects in vs out;  tris  total and per object (> 0.5 % difference = issue)
  size / axis   world bbox of the whole export and per object: same sorted dims but different order = axis error;
                ratio != 1 = scale error (reports the factor, e.g. 100 = cm/m mismatch)
  transforms    imported object scale != 1 (unapplied scale shipped to the engine) = issue; rotation != 0 = warning
  materials     every source material name must come back (engine prefixes and .001 suffixes ignored)
  UV sets       per object count;  custom normals  source had custom normals and the import has none = issue
  animation     actions on exported objects vs actions created by the import (0 after export = issue)
  shape keys    per object: shape key count (Basis excluded) and Key-datablock actions (active action + NLA strip
                actions on mesh.shape_keys) before vs after. Fewer keys after = issue "lost shape keys"; keys animated
                before and no Key action after = issue "lost shape-key animation" (OBJ: both are warnings - the
                format carries neither). Source/imported values sit in objects[<name>].shape_keys / .shape_key_actions.
                FBX: the presets use the exporter's default take modes (NLA strips + all actions), which open takes
                from Object animation only - a Key action on a mesh without object-level animation exports no take
                (measured: keys arrive, "lost shape-key animation" is genuine). Fix with --override
                '{"FBX": {"bake_anim_use_nla_strips": false, "bake_anim_use_all_actions": false}}' (one global take of
                the scene range; measured to round-trip) or export clips with export_actions.py (shape-key mode).
  export_apply  the GLB presets apply modifiers; when an exported mesh has shape keys the check forces
                export_apply=False (warning) because the glTF exporter drops the shape keys of any mesh it evaluates
                with modifiers - apply non-deform modifiers yourself before the export. An explicit
                --override '{"GLB": {"export_apply": true}}' is kept and only warned about.
  file size     vs budget_mb
Re-import uses the target's convention, not the file's metadata, where the importer allows it: FBX presets for Y-up
engines (unity, godot, web) import with manual orientation -Z forward / Y up, so an FBX written with the wrong axes
shows up rotated; glTF is Y-up by spec, so export_yup=False shows up rotated. The unreal preset trusts FBX axis
metadata (as Unreal's importer converts axes) [unverified per engine version].
  glTF JSON     GLB outputs are parsed (stdlib: GLB header + JSON chunk; .gltf read as JSON) into `gltf`:
                extensionsUsed/Required, per-material extensions, KHR_materials_variants names and per-primitive
                mappings (variant -> material), Draco primitives, meshopt bufferViews, image MIME types. Structural
                issues: extension objects not declared in extensionsUsed, extensionsRequired not in Used, variant or
                material index out of range, embedded image without mimeType. Warnings: declared but unused
                extension, variant with no effective mapping (every primitive keeps its default material).
                Morph targets: `gltf.morph_targets` lists every mesh with targets (per-primitive target counts,
                extras.targetNames, default weights) and `gltf.weights_animations` (with time_start/time_end/samples from the
    sampler input accessor) the animations whose channels
                target `weights` (name + channel counts); warnings when targetNames and target counts disagree or
                primitives of one mesh differ in target count.
  expectations  --expect-extensions KHR_materials_clearcoat,KHR_draco_mesh_compression (each must be in
                extensionsUsed) and --expect-variants Red,Blue (names, exact set; or a count) -> issues on mismatch.
                Variants export only with the add-on preference KHR_materials_variants_ui enabled (a hint is added).
Inspect an existing file without exporting (Blender or plain Python, stdlib only):
    blender -b --python export_check.py -- --inspect model.glb [--expect-extensions A,B] [--expect-variants Red,Blue]
    python export_check.py --inspect model.glb [...]
Limitations: a Blender round-trip proves the file is self-consistent, not how a given engine version interprets it;
confirm once per pipeline in the engine. Armature/bone orientation is not compared; shape keys are compared by count
and by the presence of Key animation, not per-key deltas or sampled weights. The glTF check reads JSON only (no
accessor/bufferView bounds validation) - run the Khronos glTF Validator for full conformance.
"""
import json, math, os, re, struct, sys, tempfile
try:
    import bpy
    import numpy as np
except ImportError:  # plain Python: only inspect_gltf / --inspect are usable
    bpy = np = None

SUFFIX = re.compile(r"\.\d{3}$")
ENGINE_PREFIX = re.compile(r"^(SM_|SK_|M_|MI_|MAT_)")

_FBX_BASE = dict(use_mesh_modifiers=True, mesh_smooth_type='FACE', add_leaf_bones=False, use_custom_props=True,
                 object_types={'MESH', 'ARMATURE', 'EMPTY'}, path_mode='COPY', embed_textures=False)
_GLB_BASE = dict(export_format='GLB', export_yup=True, export_apply=True, export_extras=True, export_texcoords=True,
                 export_normals=True, export_materials='EXPORT', export_animations=True)
_OBJ_BASE = dict(forward_axis='NEGATIVE_Z', up_axis='Y', apply_modifiers=True, export_uv=True, export_normals=True,
                 export_materials=True, export_triangulated_mesh=False)

PRESETS = {
    "unity": {"FBX": dict(_FBX_BASE, apply_scale_options='FBX_SCALE_ALL', axis_forward='-Z', axis_up='Y', bake_space_transform=True),
              "GLB": dict(_GLB_BASE), "OBJ": dict(_OBJ_BASE), "import_fbx_manual_axes": ('-Z', 'Y')},
    "unreal": {"FBX": dict(_FBX_BASE, apply_scale_options='FBX_SCALE_NONE', apply_unit_scale=True, axis_forward='-Z', axis_up='Y',
                           bake_space_transform=False),
               "GLB": dict(_GLB_BASE), "OBJ": dict(_OBJ_BASE), "import_fbx_manual_axes": None},
    "godot": {"GLB": dict(_GLB_BASE), "FBX": dict(_FBX_BASE, apply_scale_options='FBX_SCALE_ALL', axis_forward='-Z', axis_up='Y',
                                                  bake_space_transform=True),
              "OBJ": dict(_OBJ_BASE), "import_fbx_manual_axes": ('-Z', 'Y')},
    "web": {"GLB": dict(_GLB_BASE, export_image_format='AUTO'), "FBX": dict(_FBX_BASE, apply_scale_options='FBX_SCALE_ALL',
            axis_forward='-Z', axis_up='Y', bake_space_transform=True), "OBJ": dict(_OBJ_BASE), "import_fbx_manual_axes": ('-Z', 'Y')},
}
EXT = {"FBX": ".fbx", "GLB": ".glb", "OBJ": ".obj"}
DATA_KINDS = ("objects", "meshes", "materials", "actions", "images", "armatures", "collections", "cameras", "lights", "textures")


def _clean(name):
    return SUFFIX.sub("", name)


def _resolve(objects, collection, selection):
    if objects:
        names = objects.split(",") if isinstance(objects, str) else objects
        objs = [bpy.data.objects[n] for n in names]
        return objs + [c for o in objs for c in o.children_recursive if c not in objs]
    if collection:
        return list(bpy.data.collections[collection].all_objects)
    if selection:
        return list(bpy.context.selected_objects)
    return [o for o in bpy.context.scene.objects if o.type in ('MESH', 'ARMATURE', 'EMPTY') and not o.hide_render]


def _world_co(o, evaluated=True):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg) if evaluated else o
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    mw = np.array(o.matrix_world); co = co @ mw[:3, :3].T + mw[:3, 3]
    me.calc_loop_triangles()
    info = {"tris": len(me.loop_triangles), "uv_sets": len(me.uv_layers), "custom_normals": bool(me.has_custom_normals),
            "ngons": sum(1 for p in me.polygons if p.loop_total > 4)}
    ev.to_mesh_clear()
    return co, info


def _actions_of(objs):
    acts = set()
    for o in objs:
        ad = o.animation_data
        if not ad: continue
        if ad.action: acts.add(ad.action.name)
        for t in ad.nla_tracks:
            for s in t.strips:
                if s.action: acts.add(s.action.name)
    return acts


def _metrics(objs):
    per, allco, mats = {}, [], set()
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    for o in objs:
        if o.type != 'MESH': continue
        co, info = _world_co(o)
        if len(co): allco.append(co)
        loc, rot, scl = o.matrix_world.decompose()
        m = sorted({_clean(s.material.name) for s in o.material_slots if s.material})
        mats.update(m)
        sk = o.data.shape_keys
        per[_clean(o.name)] = dict(info, bbox_size=(co.max(0) - co.min(0)).round(5).tolist() if len(co) else [0, 0, 0],
                                   bbox_center=((co.max(0) + co.min(0)) / 2).round(5).tolist() if len(co) else [0, 0, 0],
                                   scale=[round(x, 5) for x in scl], rotation_deg=round(math.degrees(rot.angle), 3), materials=m,
                                   shape_keys=max(len(sk.key_blocks) - 1, 0) if sk else 0,
                                   shape_key_actions=len(_actions_of([sk])) if sk else 0)
    co = np.vstack(allco) if allco else np.zeros((1, 3))
    return {"objects": per, "mesh_objects": len(per), "tris": sum(v["tris"] for v in per.values()),
            "bbox_size": (co.max(0) - co.min(0)).round(5).tolist(), "materials": sorted(mats),
            "shape_keys": sum(v["shape_keys"] for v in per.values()),
            "shape_key_actions": sum(v["shape_key_actions"] for v in per.values())}


def _preflight(objs):
    issues, warnings = [], []
    for o in objs:
        s = o.scale
        if o.type == 'MESH':
            if any(abs(x - 1) > 1e-4 for x in s): issues.append(f"{o.name}: unapplied scale {tuple(round(x, 4) for x in s)} (Ctrl+A > Scale)")
            if any(x < 0 for x in s): issues.append(f"{o.name}: negative scale flips normals in engines")
            if any(abs(r) > 1e-4 for r in o.rotation_euler) and o.rotation_mode != 'QUATERNION': warnings.append(f"{o.name}: unapplied rotation (fine for placed instances, not for asset roots)")
            me = o.data
            if not me.uv_layers: warnings.append(f"{o.name}: no UV map")
            ng = sum(1 for p in me.polygons if p.loop_total > 4)
            if ng: warnings.append(f"{o.name}: {ng} n-gons - triangulate before baking normals so engine triangulation matches")
            for sl in o.material_slots:
                if sl.material and not sl.material.name.startswith(("MAT_", "M_", "MI_")):
                    warnings.append(f"material '{sl.material.name}' on {o.name}: no MAT_ / M_ / MI_ prefix (naming hint; export copies use engine names)")
    return issues, sorted(set(warnings))


def _export(fmt, path, preset, overrides, objs=None, warnings=None):
    """Run the exporter with the preset settings (+ overrides); returns the settings actually used.
    GLB: export_apply is forced False when an exported mesh has shape keys (the glTF exporter drops the shape keys of
    a mesh it evaluates with modifiers) unless an override asked for it explicitly; both cases add a warning."""
    kw = dict(PRESETS[preset][fmt]); ov = (overrides or {}).get(fmt, {}); kw.update(ov)
    if fmt == "GLB" and kw.get("export_apply") and objs:
        sk = [o for o in objs if o.type == 'MESH' and o.data.shape_keys and len(o.data.shape_keys.key_blocks) > 1]
        if sk:
            mods = [o.name for o in sk if o.modifiers]
            if ov.get("export_apply"):
                msg = (f"override keeps export_apply=True although {len(sk)} exported mesh(es) have shape keys: the glTF "
                       f"exporter cannot export shape keys with Apply Modifiers (meshes with modifiers lose them: {mods})")
            else:
                kw["export_apply"] = False
                msg = (f"export_apply forced False: {len(sk)} exported mesh(es) have shape keys and the glTF exporter cannot "
                       f"export shape keys with Apply Modifiers (it evaluates the mesh and drops them) - apply non-deform "
                       f"modifiers before the export" + (f"; meshes with modifiers: {mods}" if mods else ""))
            if warnings is not None: warnings.append(msg)
    if fmt == "FBX": bpy.ops.export_scene.fbx(filepath=path, use_selection=True, **kw)
    elif fmt == "GLB": bpy.ops.export_scene.gltf(filepath=path, use_selection=True, **kw)
    else: bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True, **kw)
    return kw


def _import(fmt, path, preset):
    before = {k: set(getattr(bpy.data, k)) for k in DATA_KINDS}
    tmp = bpy.data.scenes.new("__EXPORT_CHECK__")
    try:
        with bpy.context.temp_override(scene=tmp, view_layer=tmp.view_layers[0], collection=tmp.collection):
            if fmt == "FBX":
                axes = PRESETS[preset].get("import_fbx_manual_axes")
                # manual axes + bake_space_transform: conversion goes into mesh data, so a leftover root rotation is real.
                # Metadata-trusting import (unreal) must NOT bake: with cm unit files the importer then leaves x100 roots.
                if axes: bpy.ops.import_scene.fbx(filepath=path, use_manual_orientation=True, axis_forward=axes[0], axis_up=axes[1], bake_space_transform=True)
                else: bpy.ops.import_scene.fbx(filepath=path)
            elif fmt == "GLB": bpy.ops.import_scene.gltf(filepath=path)
            else: bpy.ops.wm.obj_import(filepath=path)
        new = {k: [i for i in getattr(bpy.data, k) if i not in before[k]] for k in DATA_KINDS}
        objs = [o for o in new["objects"]]
        tmp.frame_set(tmp.frame_current)
        with bpy.context.temp_override(scene=tmp, view_layer=tmp.view_layers[0]):
            m = _metrics(objs)
        m["actions"] = len(new["actions"])
    finally:
        ids = [i for k in DATA_KINDS for i in getattr(bpy.data, k) if i not in before[k]]
        bpy.data.batch_remove(ids)
        bpy.data.scenes.remove(tmp)
    return m


def _compare(src, imp, tol, fmt=""):
    issues, warnings = [], []
    if imp["mesh_objects"] != src["mesh_objects"]: issues.append(f"mesh objects {src['mesh_objects']} -> {imp['mesh_objects']}")
    if src["tris"] and abs(imp["tris"] - src["tris"]) / src["tris"] > 0.005: issues.append(f"tris {src['tris']} -> {imp['tris']}")
    def size_issue(a, b, label):
        a, b = np.array(a), np.array(b)
        if np.allclose(a, b, rtol=tol, atol=tol): return None
        if np.allclose(np.sort(a), np.sort(b), rtol=tol, atol=tol): return f"{label}: axis error - bbox {a.round(4).tolist()} came back as {b.round(4).tolist()}"
        r = b / np.where(a == 0, 1, a); r = r[a > tol]
        return f"{label}: scale error x{round(float(np.median(r)), 4) if len(r) else '?'} - bbox {a.round(4).tolist()} -> {b.round(4).tolist()}"
    e = size_issue(src["bbox_size"], imp["bbox_size"], "whole export")
    if e: issues.append(e)
    got = {ENGINE_PREFIX.sub("", m) for m in imp["materials"]}
    missing = sorted(m for m in src["materials"] if ENGINE_PREFIX.sub("", m) not in got)
    if missing: issues.append(f"materials lost/renamed: {missing}")
    for name, s in src["objects"].items():
        i = imp["objects"].get(name)
        if i is None: issues.append(f"{name}: not found after import (renamed?)"); continue
        e = size_issue(s["bbox_size"], i["bbox_size"], name)
        if e: issues.append(e)
        if any(abs(x - 1) > 1e-3 for x in i["scale"]): issues.append(f"{name}: object scale {i['scale']} reaches the engine (apply scale before export)")
        if i["rotation_deg"] > 0.01 and fmt != "OBJ": warnings.append(f"{name}: imported with {i['rotation_deg']} deg root rotation")
        if i["uv_sets"] != s["uv_sets"]:
            issues.append(f"{name}: UV sets {s['uv_sets']} -> {i['uv_sets']}" + (" (OBJ stores one UV set: lightmap UV2 is lost)" if fmt == "OBJ" else ""))
        if s["custom_normals"] and not i["custom_normals"]: issues.append(f"{name}: custom normals lost")
        # shape keys: count (Basis excluded) and Key-datablock animation must survive; OBJ carries neither -> warnings
        sink = warnings if fmt == "OBJ" else issues
        if s.get("shape_keys") and i.get("shape_keys", 0) < s["shape_keys"]:
            sink.append(f"{name}: lost shape keys {s['shape_keys']} -> {i.get('shape_keys', 0)}"
                        + (" (OBJ stores no shape keys)" if fmt == "OBJ" else ""))
        if s.get("shape_key_actions") and not i.get("shape_key_actions"):
            sink.append(f"{name}: lost shape-key animation ({s['shape_key_actions']} Key action(s) -> 0)"
                        + (" (OBJ stores no animation)" if fmt == "OBJ" else ""))
    return issues, warnings


NO_OBJECT_EXT = {"KHR_mesh_quantization"}  # declared in extensionsUsed without any extension object


def read_gltf_json(path):
    """glTF JSON dict from a .glb (header + first chunk) or .gltf file, plus container facts."""
    with open(path, "rb") as f:
        data = f.read()
    facts = {"file": path, "size_mb": round(len(data) / 2**20, 4)}
    if data[:4] == b"glTF":
        _, ver, length = struct.unpack_from("<III", data, 0)
        clen, ctype = struct.unpack_from("<II", data, 12)
        if ctype != 0x4E4F534A:
            raise ValueError("GLB first chunk is not JSON")
        facts.update(container="GLB", glb_version=ver, header_length_ok=length == len(data))
        off = 20 + clen
        if off + 8 <= len(data):
            blen, btype = struct.unpack_from("<II", data, off)
            facts["bin_chunk_bytes"] = blen if btype == 0x004E4942 else None
        return json.loads(data[20:20 + clen].decode("utf-8")), facts
    facts["container"] = "glTF"
    return json.loads(data.decode("utf-8-sig")), facts


def _ext_keys(node, acc):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "extensions" and isinstance(v, dict):
                acc.update(v)
            _ext_keys(v, acc)
    elif isinstance(node, list):
        for v in node:
            _ext_keys(v, acc)
    return acc


def inspect_gltf(path):
    """Stdlib-only report of extensions, variants, compression and texture MIME types for a .glb/.gltf file."""
    j, facts = read_gltf_json(path)
    issues, warnings = [], []
    used, req = j.get("extensionsUsed", []), j.get("extensionsRequired", [])
    mats, meshes, images = j.get("materials", []), j.get("meshes", []), j.get("images", [])
    mname = lambda i: (mats[i].get("name", f"material[{i}]") if isinstance(i, int) and 0 <= i < len(mats) else None)
    present = set(_ext_keys(j, {}))
    for e in sorted(present - set(used)):
        issues.append(f"extension {e} used in the document but missing from extensionsUsed")
    for e in sorted(set(req) - set(used)):
        issues.append(f"extensionsRequired {e} not listed in extensionsUsed")
    for e in sorted(set(used) - present - NO_OBJECT_EXT):
        warnings.append(f"extensionsUsed lists {e} but no object carries it")
    per_mat = [{"name": m.get("name", f"material[{i}]"), "extensions": sorted(m.get("extensions", {}))} for i, m in enumerate(mats)]
    by_ext = {}
    for m in per_mat:
        for e in m["extensions"]:
            by_ext.setdefault(e, []).append(m["name"])
    variants = [v.get("name", f"variant[{i}]") for i, v in
                enumerate(j.get("extensions", {}).get("KHR_materials_variants", {}).get("variants", []))]
    mappings, draco, effective = [], 0, {v: 0 for v in variants}
    for mi, mesh in enumerate(meshes):
        for pi, prim in enumerate(mesh.get("primitives", [])):
            ext = prim.get("extensions", {})
            draco += "KHR_draco_mesh_compression" in ext
            maps = ext.get("KHR_materials_variants", {}).get("mappings")
            if maps is None:
                continue
            row = {"mesh": mesh.get("name", f"mesh[{mi}]"), "primitive": pi, "material": mname(prim.get("material")), "variants": {}}
            for mp in maps:
                target = mname(mp.get("material"))
                if target is None:
                    issues.append(f"{row['mesh']}[{pi}]: variant mapping material index {mp.get('material')} out of range")
                for vi in mp.get("variants", []):
                    if not 0 <= vi < len(variants):
                        issues.append(f"{row['mesh']}[{pi}]: variant index {vi} out of range ({len(variants)} variants)"); continue
                    row["variants"][variants[vi]] = target
                    if target != row["material"]:
                        effective[variants[vi]] += 1
            mappings.append(row)
    for v, n in effective.items():
        if n == 0:
            warnings.append(f"variant '{v}' changes no primitive's material (unassigned or mapped to the default)")
    meshopt = {}
    for bv in j.get("bufferViews", []):
        for e in bv.get("extensions", {}):
            if "meshopt" in e: meshopt[e] = meshopt.get(e, 0) + 1
    img_rows, mimes = [], {}
    guess = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".ktx2": "image/ktx2"}
    for i, im in enumerate(images):
        uri = im.get("uri", "")
        mime = im.get("mimeType") or (uri[5:uri.find(";")] if uri.startswith("data:") else guess.get(os.path.splitext(uri)[1].lower()))
        if "bufferView" in im and not im.get("mimeType"):
            issues.append(f"image {im.get('name', i)} in a bufferView has no mimeType")
        img_rows.append({"name": im.get("name", f"image[{i}]"), "mimeType": mime, "embedded": "bufferView" in im or uri.startswith("data:")})
        mimes[mime] = mimes.get(mime, 0) + 1
    tex_src_ext = {}
    for t in j.get("textures", []):
        for e in t.get("extensions", {}):
            tex_src_ext[e] = tex_src_ext.get(e, 0) + 1
    if draco and "KHR_draco_mesh_compression" not in req:
        warnings.append("Draco primitives but KHR_draco_mesh_compression not in extensionsRequired")
    # morph targets: per-primitive target counts, extras.targetNames (glTF convention), animations driving `weights`
    morph_rows = []
    for mi, mesh in enumerate(meshes):
        counts = [len(p.get("targets", [])) for p in mesh.get("primitives", [])]
        if not any(counts):
            continue
        mname_ = mesh.get("name", f"mesh[{mi}]")
        names = (mesh.get("extras") or {}).get("targetNames")
        morph_rows.append({"mesh": mname_, "primitive_targets": counts, "targetNames": names, "weights": mesh.get("weights")})
        if len(set(counts)) > 1:
            warnings.append(f"{mname_}: primitives disagree on morph target count {counts}")
        if isinstance(names, list) and any(c != len(names) for c in counts if c):
            warnings.append(f"{mname_}: extras.targetNames has {len(names)} names but primitives carry {counts} targets")
    weights_anims = []
    for ai, an in enumerate(j.get("animations", [])):
        chans = an.get("channels", [])
        n = sum(1 for ch in chans if (ch.get("target") or {}).get("path") == "weights")
        if n:
            # sampler input accessor min/max = the clip's time range in seconds (glTF accessors carry min/max)
            t0, t1, samples = None, None, 0
            accs, samplers = j.get("accessors", []), an.get("samplers", [])
            for ch in chans:
                if (ch.get("target") or {}).get("path") != "weights":
                    continue
                si = ch.get("sampler")
                if not (isinstance(si, int) and 0 <= si < len(samplers)):
                    continue
                ii = samplers[si].get("input")
                if not (isinstance(ii, int) and 0 <= ii < len(accs)):
                    continue
                acc = accs[ii]
                lo, hi = (acc.get("min") or [None])[0], (acc.get("max") or [None])[0]
                if lo is not None:
                    t0 = lo if t0 is None else min(t0, lo)
                if hi is not None:
                    t1 = hi if t1 is None else max(t1, hi)
                samples = max(samples, acc.get("count", 0))
            weights_anims.append({"name": an.get("name", f"animation[{ai}]"), "weights_channels": n, "channels": len(chans),
                                  "time_start": t0, "time_end": t1, "samples": samples})
    return dict(facts, generator=j.get("asset", {}).get("generator"), extensionsUsed=used, extensionsRequired=req,
                counts={**{k: len(j.get(k, [])) for k in ("nodes", "meshes", "materials", "textures", "images", "animations")},
                        "morph_target_meshes": len(morph_rows), "weights_animations": len(weights_anims)},
                primitives=sum(len(m.get("primitives", [])) for m in meshes), materials=per_mat, material_extensions=by_ext,
                variants=variants, variant_mappings=mappings, draco_primitives=draco, meshopt_buffer_views=meshopt,
                morph_targets=morph_rows, weights_animations=weights_anims,
                images=img_rows, mime_types=mimes, texture_extensions=tex_src_ext,
                issues=list(dict.fromkeys(issues)), warnings=list(dict.fromkeys(warnings)))


def check_gltf_expectations(info, expect_extensions=None, expect_variants=None):
    """Issues when the inspected file lacks expected extensions or its variant names/count differ."""
    issues, warnings = [], []
    if isinstance(expect_extensions, str): expect_extensions = [e for e in expect_extensions.split(",") if e]
    for e in expect_extensions or []:
        if e not in info["extensionsUsed"]:
            issues.append(f"expected extension {e} not in extensionsUsed {info['extensionsUsed']}")
    if expect_variants is not None and expect_variants != "":
        if isinstance(expect_variants, str):
            expect_variants = int(expect_variants) if expect_variants.isdigit() else [v for v in expect_variants.split(",") if v]
        got = info["variants"]
        if isinstance(expect_variants, int):
            if len(got) != expect_variants: issues.append(f"expected {expect_variants} variant(s), file has {len(got)} {got}")
        else:
            miss, extra = sorted(set(expect_variants) - set(got)), sorted(set(got) - set(expect_variants))
            if miss: issues.append(f"expected variant(s) {miss} missing (file has {got})")
            if extra: warnings.append(f"unexpected variant(s) {extra}")
        if got and not info["variant_mappings"]:
            issues.append("variants declared but no primitive carries KHR_materials_variants mappings")
        if not got and bpy is not None:
            try:
                if not bpy.context.preferences.addons["io_scene_gltf2"].preferences.KHR_materials_variants_ui:
                    warnings.append("glTF add-on preference KHR_materials_variants_ui is off: variants are not exported")
            except (KeyError, AttributeError):
                pass
    return issues, warnings


def export_check(objects=None, collection=None, selection=False, formats=("FBX", "GLB"), preset="unity", out_dir=None,
                 name="export_check", budget_mb=None, overrides=None, tol=0.001, delete_files=False,
                 expect_extensions=None, expect_variants=None):
    preset = preset.lower(); formats = [f.upper() for f in (formats.split(",") if isinstance(formats, str) else formats)]
    if isinstance(overrides, str): overrides = json.loads(overrides)
    objs = _resolve(objects, collection, selection)
    out_dir = bpy.path.abspath(out_dir) if out_dir else tempfile.mkdtemp(prefix="export_check_")
    os.makedirs(out_dir, exist_ok=True)
    sc = bpy.context.scene; sc.frame_set(sc.frame_current)  # animated objects: measure what the exporter evaluates, not unkeyed edits
    src = _metrics(objs); src["actions"] = len(_actions_of(objs))
    pre_issues, pre_warn = _preflight(objs)
    vl = bpy.context.view_layer
    prev_sel = [o for o in vl.objects if o.select_get()]; prev_act = vl.objects.active
    for o in vl.objects: o.select_set(False)
    for o in objs:
        if o.name in vl.objects: o.select_set(True)
    out = {"blender": bpy.app.version_string, "preset": preset, "source": src,
           "preflight": {"issues": pre_issues, "warnings": pre_warn}, "formats": {}}
    try:
        for fmt in formats:
            path = os.path.join(out_dir, name + EXT[fmt]); rec = {"file": path}
            try:
                exp_warn = []
                rec["settings"] = {k: (sorted(v) if isinstance(v, set) else v)
                                   for k, v in _export(fmt, path, preset, overrides, objs, exp_warn).items()}
                rec["size_mb"] = round(os.path.getsize(path) / 2**20, 4)
                imp = _import(fmt, path, preset); rec["imported"] = imp
                issues, warnings = _compare(src, imp, tol, fmt)
                warnings = exp_warn + warnings
                if src["actions"] and fmt != "OBJ" and imp["actions"] == 0: issues.append(f"{src['actions']} action(s) exported, none imported")
                if budget_mb and rec["size_mb"] > budget_mb: issues.append(f"file {rec['size_mb']} MB > budget {budget_mb} MB")
                if fmt == "GLB":
                    g = rec["gltf"] = inspect_gltf(path)
                    ei, ew = check_gltf_expectations(g, expect_extensions, expect_variants)
                    issues += g["issues"] + ei; warnings += g["warnings"] + ew
                rec["issues"], rec["warnings"] = issues, warnings; rec["pass"] = not issues
            except Exception as ex:
                rec["pass"] = False; rec["issues"] = [f"{type(ex).__name__}: {ex}"]
            if delete_files and os.path.exists(path): os.remove(path)
            out["formats"][fmt] = rec
    finally:
        for o in vl.objects: o.select_set(o in prev_sel)
        vl.objects.active = prev_act
    out["pass"] = not pre_issues and all(r["pass"] for r in out["formats"].values())
    out["summary"] = {"preflight": not pre_issues, **{f: r["pass"] for f, r in out["formats"].items()}}
    return out


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="export_check.py")
    p.add_argument("--objects"); p.add_argument("--collection"); p.add_argument("--selection", action="store_true")
    p.add_argument("--formats", default="FBX,GLB"); p.add_argument("--preset", default="unity", choices=sorted(PRESETS))
    p.add_argument("--out"); p.add_argument("--name", default="export_check"); p.add_argument("--budget-mb", type=float)
    p.add_argument("--override"); p.add_argument("--tol", type=float, default=0.001); p.add_argument("--delete-files", action="store_true")
    p.add_argument("--expect-extensions", help="comma list; each must be in extensionsUsed of the GLB")
    p.add_argument("--expect-variants", help="comma list of KHR_materials_variants names, or a count")
    p.add_argument("--inspect", help="inspect an existing .glb/.gltf only (no export)")
    a = p.parse_args(argv)
    if a.inspect:
        return inspect_file(a.inspect, a.expect_extensions, a.expect_variants)
    return export_check(a.objects, a.collection, a.selection, a.formats, a.preset, a.out, a.name, a.budget_mb, a.override, a.tol,
                        a.delete_files, a.expect_extensions, a.expect_variants)


def inspect_file(path, expect_extensions=None, expect_variants=None):
    g = inspect_gltf(path)
    ei, ew = check_gltf_expectations(g, expect_extensions, expect_variants)
    issues, warnings = g["issues"] + ei, g["warnings"] + ew
    return {"inspect": path, "gltf": g, "issues": issues, "warnings": warnings, "pass": not issues,
            "summary": {"gltf": not issues}}


if "EXPORT_OPTS" in globals():
    _o = dict(EXPORT_OPTS)
    result = inspect_file(_o.pop("inspect"), **_o) if _o.get("inspect") else export_check(**_o)
    print(json.dumps(result["summary"]))
elif __name__ == "__main__" and ("--" in sys.argv or bpy is None):
    _a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    result = _cli(_a); print("EXPORT_CHECK " + json.dumps(result, default=str))
else:
    result = {"defined": ["export_check", "inspect_gltf", "inspect_file", "check_gltf_expectations", "PRESETS"]}
