"""Interchange & linked-library integrity checks: USD round-trip, Alembic cache round-trip, library/override report.

  usd       export the target objects with wm.usd_export -> import into a temporary scene with wm.usd_import ->
            compare mesh object count, triangles, world bbox + per-vertex deviation (units/axis), materials, UV map
            count, frame range and animated positions at sampled frames; reads stage metadata (metersPerUnit, upAxis,
            time codes) through pxr when available. Diagnoses scale factors (x100 cm/m, x0.0254 in ...) and axis swaps.
  alembic   export (wm.alembic_export) -> import (wm.alembic_import) -> per-vertex world deviation at sampled frames.
  library   report libraries (missing, absolute, needs resync, packed/archive), missing linked data-blocks, override
            hierarchies (system vs editable, overridden properties, broken references); optional --search-dir
            relocation of missing libraries (wm.lib_relocate) and --resync of override hierarchies.
  library-selftest  build lib.blend + shot.blend in --out, link + override hierarchy + local edits, change the source
            (add object, move vertex, rename an overridden object), reopen, break the path, relocate; reports what
            survived. The body runs in a child `blender -b --factory-startup` process that empties its own scene by
            deleting data-blocks (it never resets settings/preferences); the calling session is left untouched and
            receives the child's report.

Headless / CLI (prints one line: INTERCHANGE_CHECK <json>):
    blender -b scene.blend --python interchange_check.py -- usd [--objects A,B | --collection C] [--animation]
        [--frames 1,12,24] [--units METERS|CENTIMETERS|MILLIMETERS|INCHES|FEET|...] [--meters-per-unit 1]
        [--no-apply-units] [--expect-units CENTIMETERS] [--import-scale 1]
        [--convert-orientation --forward NEGATIVE_Z --up Y] [--subdiv BEST_MATCH|TESSELLATE|IGNORE] [--no-materials]
        [--materialx] [--instancing] [--usdz] [--root-prim /root] [--tol-mm 0.1] [--out DIR] [--keep]
    blender -b scene.blend --python interchange_check.py -- alembic [--objects A,B | --collection C]
        [--frames 1,12,24] [--export-scale 1] [--import-scale 1] [--tol-mm 0.1] [--out DIR] [--keep]
    blender -b shot.blend  --python interchange_check.py -- library [--search-dir DIR] [--resync [--enforce]] [--save]
    blender -b --python interchange_check.py -- library-selftest --out DIR [--timeout 600] [--in-process]
        (--in-process runs the selftest body in the current session instead of a child -- it replaces the open file;
        this is what the parent passes to the child, so a plain call never needs it)
  Targets default to the selected objects. Exports go to --out (default: a temp dir, deleted unless --keep).
Live (Blender:execute_blender_code): set before exec
    INTERCHANGE_OPTS = {"op": "usd", "objects": ["GEO_Crate"], "units": "CENTIMETERS"}   -> `result` dict
    INTERCHANGE_OPTS = {"op": "library-selftest", "out_dir": "D:/tmp/selftest", "script": "<path to this file>"}
    (all ops are safe live: usd / alembic / library remove the imported data and the temporary scene afterwards
    and restore the source scene's frame range/selection; library-selftest spawns a child process. When the file is
    exec'd through a bridge `__file__` is undefined, so pass `script` = the path of this file for the child.)
Without INTERCHANGE_OPTS the file only defines the functions.
Limitations: objects are matched by name (sanitized, collision suffixes stripped); per-vertex deviation needs equal
vertex counts and order (true for Blender->Blender round-trips of plain meshes; subdivision exported as a USD
subdiv scheme re-imports as the cage -> triangle mismatch is reported, not hidden); materials compare names
only (UsdPreviewSurface/MaterialX lose node detail -- inspect looks separately); Alembic carries no materials.
"""
import bpy, os, re, sys, json, math, shutil, subprocess, tempfile
import numpy as np

TAG = "INTERCHANGE_CHECK"
DATA_TYPES = ("objects", "meshes", "materials", "images", "actions", "cache_files", "collections", "node_groups",
              "lights", "cameras", "curves", "armatures", "worlds", "textures", "pointclouds", "volumes", "shape_keys")
UNIT_FACTORS = {"x100 (m->cm)": 100.0, "x0.01 (cm->m)": 0.01, "x1000 (m->mm)": 1000.0, "x0.001 (mm->m)": 0.001,
                "x10": 10.0, "x0.1": 0.1, "x39.37 (m->in)": 39.3701, "x0.0254 (in->m)": 0.0254,
                "x3.281 (m->ft)": 3.28084, "x0.3048 (ft->m)": 0.3048}


# ------------------------------------------------------------------ shared helpers
def _base(name):
    m = re.match(r"^(.*)\.\d{3,}$", name)
    return m.group(1) if m else name


def _san(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()


def _targets(objects=None, collection=None):
    if isinstance(objects, str):
        objects = [n for n in objects.split(",") if n]
    if objects:
        return [bpy.data.objects[n] for n in objects]
    if collection:
        return list(bpy.data.collections[collection].all_objects)
    return list(bpy.context.selected_objects)


def _snapshot():
    return {t: set(getattr(bpy.data, t)) for t in DATA_TYPES if hasattr(bpy.data, t)}


def _new_ids(snap):
    return {t: [i for i in getattr(bpy.data, t) if i not in snap[t]] for t in snap}


def _cleanup(new, scene=None):
    ids = [i for t, lst in new.items() if t != "shape_keys" for i in lst]
    try:
        bpy.data.batch_remove(ids)
    except Exception:
        for i in ids:
            try:
                getattr(bpy.data, i.id_type.lower() + "s").remove(i)
            except Exception:
                pass
    if scene is not None and scene.name in bpy.data.scenes:
        bpy.data.scenes.remove(scene)


def _mesh_sample(o, dg):
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        n = len(me.vertices)
        co = np.empty(n * 3, np.float64); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        mw = np.array(ev.matrix_world, np.float64)
        co = co @ mw[:3, :3].T + mw[:3, 3]
        me.calc_loop_triangles()
        uvb = None
        if me.uv_layers.active and len(me.loops):
            a = np.empty(len(me.loops) * 2, np.float64); me.uv_layers.active.uv.foreach_get("vector", a)
            a = a.reshape(-1, 2); uvb = [a.min(0).round(5).tolist(), a.max(0).round(5).tolist()]
        return {"co": co, "verts": n, "tris": len(me.loop_triangles), "uv_maps": [u.name for u in me.uv_layers],
                "uv_bbox": uvb}
    finally:
        ev.to_mesh_clear()


def _collect(objs, scene, view_layer, frames):
    """{key: {"name", "materials", "frames": {f: sample}}} for MESH objects, evaluated in (scene, view_layer)."""
    out = {}
    meshes = [o for o in objs if o.type == 'MESH']
    with bpy.context.temp_override(scene=scene, view_layer=view_layer):
        cur = scene.frame_current
        for f in frames:
            scene.frame_set(f)
            dg = bpy.context.evaluated_depsgraph_get()
            for o in meshes:
                e = out.setdefault(o.name, {"name": o.name, "data": o.data.name, "materials":sorted({_base(s.material.name) for s in o.material_slots if s.material}),
                                            "frames": {}})
                e["frames"][f] = _mesh_sample(o, dg)
        scene.frame_set(cur)
    return out


def _match(src, imp_objs):
    """Map imported object -> source key by blender name property, full sanitized name, or collision-stripped name."""
    skeys = {_san(k): k for k in src}
    # USD import (merge_parent_xform) names the object after the mesh prim = source *data* name (measured 5.2)
    dkeys = {}
    for k, s in src.items():
        dkeys.setdefault(_san(s.get("data") or ""), []).append(k)
    pairs, unmatched = {}, []
    for o in imp_objs:
        cands = [o.get("userProperties:blender:object_name"), o.get("blender:object_name"), o.name, _base(o.name),
                 o.parent.name if o.parent else None]
        k = next((skeys[_san(c)] for c in cands if isinstance(c, str) and _san(c) in skeys and skeys[_san(c)] not in pairs), None)
        if k is None:
            for c in (o.name, _base(o.name), o.data.name if o.data else None):
                free = [x for x in dkeys.get(_san(c or ""), []) if x not in pairs]
                if len(free) == 1:
                    k = free[0]; break
        if k is None:
            unmatched.append(o.name)
        else:
            pairs[k] = o
    return pairs, unmatched


def _nearest_factor(r):
    best = min(UNIT_FACTORS.items(), key=lambda kv: abs(math.log(r / kv[1])) if r > 0 else 1e9)
    return best[0] if r > 0 and abs(math.log(r / best[1])) < 0.02 else None


def _compare(src, imp, tol_m, check_materials=True):
    rows, ratios, axis_notes = [], [], []
    ok_all = True
    for k, s in src.items():
        i = imp.get(k)
        if i is None:
            rows.append({"object": k, "pass": False, "issue": "not found after import"}); ok_all = False; continue
        r = {"object": k, "imported_as": i["name"], "frames": {}}
        f0 = next(iter(s["frames"]))
        s0, i0 = s["frames"][f0], i["frames"].get(f0)
        r["tris"] = [s0["tris"], i0["tris"]]
        r["verts"] = [s0["verts"], i0["verts"]]
        issues = []
        if s0["tris"] != i0["tris"]:
            issues.append("triangle count differs (subdivision exported as scheme? triangulation?)")
        sd = s0["co"].max(0) - s0["co"].min(0) if s0["verts"] else np.zeros(3)
        idim = i0["co"].max(0) - i0["co"].min(0) if i0["verts"] else np.zeros(3)
        diag_s, diag_i = float(np.linalg.norm(sd)), float(np.linalg.norm(idim))
        if diag_s > 1e-9:
            ratios.append(diag_i / diag_s)
        if not np.allclose(sd, idim, atol=tol_m) and np.allclose(np.sort(sd), np.sort(idim), atol=tol_m):
            perm = [int(np.argmin(np.abs(idim - v))) for v in sd]
            axis_notes.append(f"{k}: dims {np.round(sd, 4).tolist()} -> {np.round(idim, 4).tolist()} (axes permuted {perm})")
        for f, sf in s["frames"].items():
            fi = i["frames"].get(f)
            if fi is None:
                continue
            bb = float(max(np.abs(sf["co"].min(0) - fi["co"].min(0)).max(), np.abs(sf["co"].max(0) - fi["co"].max(0)).max())) if sf["verts"] and fi["verts"] else None
            vd = float(np.abs(sf["co"] - fi["co"]).max()) if sf["verts"] == fi["verts"] and sf["verts"] else None
            r["frames"][f] = {"bbox_dev_mm": round(bb * 1000, 4) if bb is not None else None,
                              "max_vertex_dev_mm": round(vd * 1000, 4) if vd is not None else None}
            if bb is None or bb > tol_m or (vd is not None and vd > tol_m):
                issues.append(f"frame {f}: deviation bbox {bb if bb is None else round(bb * 1000, 3)} mm, vertex "
                              f"{vd if vd is None else round(vd * 1000, 3)} mm > {tol_m * 1000:.3f} mm")
        r["uv_maps"] = [s0["uv_maps"], i0["uv_maps"]]
        if len(s0["uv_maps"]) != len(i0["uv_maps"]):
            issues.append("UV map count differs")
        elif s0["uv_bbox"] and i0["uv_bbox"] and not np.allclose(s0["uv_bbox"], i0["uv_bbox"], atol=1e-3):
            issues.append(f"active UV bounds differ {s0['uv_bbox']} -> {i0['uv_bbox']}")
        r["materials"] = [s["materials"], i["materials"]]
        if check_materials and s["materials"] != i["materials"]:
            issues.append("material names differ")
        r["issues"], r["pass"] = issues, not issues
        ok_all &= r["pass"]
        rows.append(r)
    med = float(np.median(ratios)) if ratios else None
    diag = []
    if med is not None and abs(med - 1) > 1e-3:
        fac = _nearest_factor(med)
        diag.append(f"imported size = {med:.5g} x source" + (f" -> unit mismatch {fac}" if fac else ""))
    diag += [f"axis mismatch: {a}" for a in axis_notes]
    return ok_all, rows, med, diag


def _usd_stage_info(path):
    try:
        from pxr import Usd, UsdGeom, UsdShade
    except Exception as e:
        return {"available": False, "error": str(e)}
    st = Usd.Stage.Open(path)
    prims = list(st.Traverse())
    dp = st.GetDefaultPrim()
    return {"available": True, "metersPerUnit": UsdGeom.GetStageMetersPerUnit(st), "upAxis": str(UsdGeom.GetStageUpAxis(st)),
            "defaultPrim": dp.GetPath().pathString if dp else None, "startTimeCode": st.GetStartTimeCode(),
            "endTimeCode": st.GetEndTimeCode(), "timeCodesPerSecond": st.GetTimeCodesPerSecond(), "prims": len(prims),
            "meshes": sum(1 for p in prims if p.IsA(UsdGeom.Mesh)),
            "materials": [p.GetPath().pathString for p in prims if p.IsA(UsdShade.Material)][:20],
            "shaders": sorted({str(p.GetAttribute("info:id").Get()) for p in prims if p.IsA(UsdShade.Shader) and p.GetAttribute("info:id").Get()})[:20]}


def _frames_for(scene, animation, frames):
    if frames:
        return [int(f) for f in (frames.split(",") if isinstance(frames, str) else frames)]
    if animation:
        a, b = scene.frame_start, scene.frame_end
        return sorted({a, (a + b) // 2, b})
    return [scene.frame_current]


class _Roundtrip:
    """Context: select targets, temp dir, temp scene; restores selection/frame range; removes imported data."""

    def __init__(self, targets, out_dir, keep):
        self.targets, self.keep = targets, keep
        self.dir = out_dir or tempfile.mkdtemp(prefix="interchange_")
        os.makedirs(self.dir, exist_ok=True)

    def __enter__(self):
        self.scene, self.vl = bpy.context.scene, bpy.context.view_layer
        self.sel = [o for o in self.scene.objects if o.select_get()]
        self.active = self.vl.objects.active
        self.range = (self.scene.frame_start, self.scene.frame_end, self.scene.frame_current)
        for o in self.scene.objects:
            o.select_set(False)
        for o in self.targets:
            o.select_set(True)
        return self

    def import_into_temp(self, op, **kw):
        self.tmp = bpy.data.scenes.new("_interchange_check_tmp")
        self.tmp.render.fps, self.tmp.render.fps_base = self.scene.render.fps, self.scene.render.fps_base
        tvl = self.tmp.view_layers[0]
        self.snap = _snapshot()
        with bpy.context.temp_override(scene=self.tmp, view_layer=tvl):
            op(**kw)
        self.new = _new_ids(self.snap)
        return self.tmp, tvl, self.new["objects"]

    def __exit__(self, *exc):
        if getattr(self, "new", None) is not None:
            _cleanup(self.new, self.tmp)
        self.scene.frame_start, self.scene.frame_end = self.range[0], self.range[1]
        self.scene.frame_set(self.range[2])
        for o in self.scene.objects:
            o.select_set(o in self.sel)
        self.vl.objects.active = self.active
        if not self.keep:
            shutil.rmtree(self.dir, ignore_errors=True)
        return False


# ------------------------------------------------------------------ USD
def usd_roundtrip(objects=None, collection=None, animation=False, frames=None, units="METERS", meters_per_unit=1.0,
                  apply_units=True, import_scale=1.0, convert_orientation=False, forward="NEGATIVE_Z", up="Y",
                  subdiv="BEST_MATCH", materials=True, materialx=False, instancing=False, usdz=False,
                  root_prim="/root", tol_mm=0.1, out_dir=None, keep=False, expect_units=None):
    """expect_units: the unit the consumer pipeline requires (default = units); stage metersPerUnit must match it.
    Note (measured 5.2): convert_scene_units writes metersPerUnit AND a compensating root xformOp:scale (cm -> x100),
    so Blender->Blender round-trips keep size whatever apply_unit_conversion_scale is; mismatches show up in
    consumers that read one without the other -> check stage_units (expect_units). Re-importing a Blender-authored
    stage ignored apply_unit_conversion_scale and import_scale (scale=100 -> size ratio 1.0), so import_scale can't
    simulate a mis-reading consumer."""
    targets = _targets(objects, collection)
    if not targets:
        return {"pass": False, "error": "no target objects (select some or pass objects/collection)"}
    sc = bpy.context.scene
    fr = _frames_for(sc, animation, frames)
    res = {"op": "usd", "blender": bpy.app.version_string, "targets": [o.name for o in targets], "frames": fr}
    with _Roundtrip(targets, out_dir, keep) as rt:
        src = _collect(targets, rt.scene, rt.vl, fr)
        path = os.path.join(rt.dir, "roundtrip." + ("usdz" if usdz else "usdc"))
        ekw = dict(filepath=path, selected_objects_only=True, export_animation=bool(animation), export_materials=bool(materials),
                   export_uvmaps=True, export_normals=True, convert_scene_units=units, meters_per_unit=float(meters_per_unit),
                   convert_orientation=bool(convert_orientation), export_global_forward_selection=forward,
                   export_global_up_selection=up, export_subdivision=subdiv, generate_preview_surface=True,
                   generate_materialx_network=bool(materialx), use_instancing=bool(instancing), root_prim_path=root_prim)
        bpy.ops.wm.usd_export(**ekw)
        res["export"] = {k: v for k, v in ekw.items() if k != "filepath"}
        res["file"] = path if keep else os.path.basename(path)
        res["file_kb"] = round(os.path.getsize(path) / 1024, 1)
        res["stage"] = _usd_stage_info(path)
        ikw = dict(filepath=path, apply_unit_conversion_scale=bool(apply_units), scale=float(import_scale),
                   set_frame_range=True, import_subdivision=False, import_usd_preview=True, mtl_name_collision_mode='MAKE_UNIQUE')
        tmp, tvl, new_objs = rt.import_into_temp(bpy.ops.wm.usd_import, **ikw)
        res["import"] = {k: v for k, v in ikw.items() if k != "filepath"}
        res["imported_objects"] = len(new_objs)
        res["imported_into_temp_scene"] = all(o.name in tmp.objects for o in new_objs)
        pairs, unmatched = _match(src, [o for o in new_objs if o.type == 'MESH'])
        imp = _collect(list(pairs.values()), tmp, tvl, fr)
        imp = {k: imp[o.name] for k, o in pairs.items() if o.name in imp}
        ok, rows, ratio, diag = _compare(src, imp, tol_mm / 1000.0, check_materials=materials)
        checks = {"object_count": {"source_meshes": len(src), "matched": len(imp), "unmatched_imported": unmatched,
                                   "pass": len(src) == len(imp)},
                  "geometry": {"pass": ok, "size_ratio": None if ratio is None else round(ratio, 6), "objects": rows}}
        if animation:
            checks["frame_range"] = {"source": [rt.range[0], rt.range[1]], "imported": [tmp.frame_start, tmp.frame_end],
                                     "pass": (tmp.frame_start, tmp.frame_end) == (rt.range[0], rt.range[1])}
        if res["stage"].get("available"):
            exp_mpu = {"METERS": 1.0, "KILOMETERS": 1000.0, "CENTIMETERS": 0.01, "MILLIMETERS": 0.001, "INCHES": 0.0254,
                       "FEET": 0.3048, "YARDS": 0.9144}.get(expect_units or units, float(meters_per_unit))
            mpu = res["stage"]["metersPerUnit"]
            checks["stage_units"] = {"metersPerUnit": mpu, "expected": exp_mpu, "pass": abs(mpu - exp_mpu) < 1e-9}
            if not apply_units and abs(mpu - 1.0) > 1e-9:
                diag.append(f"stage metersPerUnit={mpu} but import ignored it (apply_unit_conversion_scale=False)")
        res["checks"], res["diagnosis"] = checks, diag
        res["pass"] = all(c.get("pass", True) for c in checks.values())
    return res


# ------------------------------------------------------------------ Alembic
def alembic_roundtrip(objects=None, collection=None, frames=None, export_scale=1.0, import_scale=1.0, tol_mm=0.1,
                      evaluation_mode="RENDER", out_dir=None, keep=False):
    targets = _targets(objects, collection)
    if not targets:
        return {"pass": False, "error": "no target objects (select some or pass objects/collection)"}
    sc = bpy.context.scene
    fr = _frames_for(sc, True, frames)
    res = {"op": "alembic", "blender": bpy.app.version_string, "targets": [o.name for o in targets], "frames": fr}
    with _Roundtrip(targets, out_dir, keep) as rt:
        src = _collect(targets, rt.scene, rt.vl, fr)
        path = os.path.join(rt.dir, "roundtrip.abc")
        ekw = dict(filepath=path, selected=True, start=min(fr + [sc.frame_start]), end=max(fr + [sc.frame_end]),
                   global_scale=float(export_scale), uvs=True, normals=True, face_sets=False, evaluation_mode=evaluation_mode,
                   as_background_job=False)
        bpy.ops.wm.alembic_export(**ekw)
        res["export"] = {k: v for k, v in ekw.items() if k != "filepath"}
        res["file"] = path if keep else os.path.basename(path)
        res["file_kb"] = round(os.path.getsize(path) / 1024, 1)
        ikw = dict(filepath=path, scale=float(import_scale), set_frame_range=True, validate_meshes=False, as_background_job=False)
        tmp, tvl, new_objs = rt.import_into_temp(bpy.ops.wm.alembic_import, **ikw)
        res["import"] = {k: v for k, v in ikw.items() if k != "filepath"}
        res["imported_objects"] = len(new_objs)
        res["cache_readers"] = sorted({m.type for o in new_objs for m in o.modifiers if m.type == 'MESH_SEQUENCE_CACHE'} |
                                      {c.type for o in new_objs for c in o.constraints if c.type == 'TRANSFORM_CACHE'})
        pairs, unmatched = _match(src, [o for o in new_objs if o.type == 'MESH'])
        imp = _collect(list(pairs.values()), tmp, tvl, fr)
        imp = {k: imp[o.name] for k, o in pairs.items() if o.name in imp}
        ok, rows, ratio, diag = _compare(src, imp, tol_mm / 1000.0, check_materials=False)
        res["checks"] = {"object_count": {"source_meshes": len(src), "matched": len(imp), "unmatched_imported": unmatched,
                                          "pass": len(src) == len(imp)},
                         "geometry": {"pass": ok, "size_ratio": None if ratio is None else round(ratio, 6), "objects": rows},
                         "frame_range": {"exported": [ekw["start"], ekw["end"]], "imported": [tmp.frame_start, tmp.frame_end],
                                         "pass": (tmp.frame_start, tmp.frame_end) == (ekw["start"], ekw["end"])}}
        res["diagnosis"] = diag
        res["pass"] = all(c["pass"] for c in res["checks"].values())
    return res


# ------------------------------------------------------------------ libraries & overrides
_OVR_TYPES = ("objects", "collections", "meshes", "materials", "armatures", "actions", "node_groups", "curves", "images",
              "lights", "cameras", "worlds", "scenes")


def _lib_abs(lib):
    try:
        return os.path.normpath(bpy.path.abspath(lib.filepath, library=lib.parent))
    except TypeError:
        return os.path.normpath(bpy.path.abspath(lib.filepath))


def _find_file(search_dir, filename):
    for root, _, files in os.walk(bpy.path.abspath(search_dir)):
        if filename in files:
            return os.path.join(root, filename)
    return None


def library_report(search_dir=None, resync=False, enforce=False, save=False):
    res = {"op": "library", "blender": bpy.app.version_string, "file": bpy.data.filepath or None}
    relocated = []
    if search_dir:
        for lib in list(bpy.data.libraries):
            p = _lib_abs(lib)
            if getattr(lib, "is_archive", False) or os.path.isfile(p):
                continue
            hit = _find_file(search_dir, os.path.basename(p))
            if hit:
                old = lib.filepath
                r = bpy.ops.wm.lib_relocate(library=lib.name, directory=os.path.dirname(hit) + os.sep,
                                            filename=os.path.basename(hit), filepath=hit, relative_path=bool(bpy.data.filepath))
                relocated.append({"library": lib.name, "from": old, "to": hit, "op": sorted(r)})
            else:
                relocated.append({"library": lib.name, "from": lib.filepath, "to": None, "op": "not found in search_dir"})
    libs = []
    for lib in bpy.data.libraries:
        p = _lib_abs(lib)
        linked = missing = 0
        for t in DATA_TYPES:
            for i in getattr(bpy.data, t, []):
                if i.library == lib:
                    linked += 1
                    missing += bool(getattr(i, "is_missing", False))
        libs.append({"name": lib.name, "filepath": lib.filepath, "resolved": p, "exists": os.path.isfile(p),
                     "is_missing": lib.is_missing, "relative": lib.filepath.startswith("//"),
                     "indirect_parent": lib.parent.name if lib.parent else None,
                     "is_archive": getattr(lib, "is_archive", False), "needs_liboverride_resync": lib.needs_liboverride_resync,
                     "file_version": list(lib.version) if getattr(lib, "version", None) else None,
                     "linked_ids": linked, "missing_ids": missing})
    roots, broken = {}, []
    for t in _OVR_TYPES:
        for i in getattr(bpy.data, t, []):
            ol = i.override_library
            if ol is None or i.library is not None:
                continue
            root = ol.hierarchy_root
            e = roots.setdefault(root.name if root else "(none)", {"root_type": type(root).__name__ if root else None,
                                                                    "members": 0, "editable": 0, "system": 0, "edits": {}})
            e["members"] += 1
            if ol.is_system_override:
                e["system"] += 1
            else:
                e["editable"] += 1
                paths = [p.rna_path for p in ol.properties]
                if paths:
                    e["edits"][f"{type(i).__name__}:{i.name}"] = paths[:12]
            ref = ol.reference
            if ref is None or getattr(ref, "is_missing", False):
                broken.append({"id": f"{type(i).__name__}:{i.name}", "reference": ref.name if ref else None,
                               "reason": "reference missing (library moved/renamed or ID renamed in source)"})
    if resync:
        sc, vl = bpy.context.scene, bpy.context.view_layer
        done = []
        for name in list(roots):
            rid = next((i for t in _OVR_TYPES for i in getattr(bpy.data, t, []) if i.name == name and i.override_library
                        and i.library is None and i.override_library.hierarchy_root == i), None)
            if rid is None:
                continue
            try:
                ok = rid.override_library.resync(sc, view_layer=vl, do_hierarchy_enforce=bool(enforce), do_whole_hierarchy=True)
                done.append({"root": name, "success": bool(ok)})
            except Exception as ex:
                done.append({"root": name, "error": f"{type(ex).__name__}: {ex}"})
        res["resync"] = done
    missing_ids = [f"{type(i).__name__}:{i.name}" for t in DATA_TYPES for i in getattr(bpy.data, t, [])
                   if i.library is not None and getattr(i, "is_missing", False)]
    res.update({"libraries": libs, "relocated": relocated, "override_hierarchies": roots, "broken_overrides": broken,
                "missing_linked_ids": missing_ids[:100], "missing_linked_id_count": len(missing_ids)})
    res["checks"] = {"libraries_found": all(l["exists"] and not l["is_missing"] for l in libs if not l["is_archive"]),
                     "no_missing_ids": not missing_ids, "no_broken_overrides": not broken,
                     "no_pending_resync": not any(l["needs_liboverride_resync"] for l in libs),
                     "relative_paths": all(l["relative"] for l in libs if not l["is_archive"])}
    res["pass"] = all(v for k, v in res["checks"].items() if k != "relative_paths")
    if save and bpy.data.filepath:
        bpy.ops.wm.save_mainfile(); res["saved"] = bpy.data.filepath
    return res


_WIPE_TYPES = ("objects", "collections", "meshes", "materials", "lights", "cameras", "images", "actions", "armatures",
               "curves", "node_groups", "textures", "cache_files", "pointclouds", "volumes", "libraries")


def _wipe_session():
    """Empty the current session by deleting data-blocks (objects first, then their data, then libraries).
    Deliberately NOT wm.read_factory_settings(): that resets preferences/extensions of the running Blender.
    Leaves the session untitled (bpy.data.filepath == ''), so the next save_as_mainfile makes paths relative."""
    for t in _WIPE_TYPES:
        ids = list(getattr(bpy.data, t, []))
        if ids:
            try:
                bpy.data.batch_remove(ids)
            except Exception:
                for i in ids:
                    try:
                        getattr(bpy.data, t).remove(i)
                    except Exception:
                        pass
    for sc in bpy.data.scenes:
        sc.frame_set(sc.frame_start)


def library_selftest(out_dir, in_process=False, script=None, timeout=600):
    """Parent: run the selftest body in a child `blender -b --factory-startup --python <this file> -- library-selftest
    --out DIR --in-process` and return the child's report (the child's tagged line). The calling session is untouched.
    in_process=True runs the body here (replaces the open file) -- only the child uses it."""
    if in_process:
        return _library_selftest_body(out_dir)
    D = os.path.abspath(bpy.path.abspath(out_dir))
    out = {"op": "library-selftest", "blender": bpy.app.version_string, "dir": D}
    script = script or globals().get("__file__")
    if not script or not os.path.isfile(str(script)):
        out.update({"pass": False, "error": "path of interchange_check.py unknown: pass script=<path> (live/exec use) "
                                            "or run it from the CLI so the selftest can be delegated to a child process"})
        return out
    cmd = [bpy.app.binary_path, "-b", "--factory-startup", "--python", os.path.abspath(str(script)), "--",
           "library-selftest", "--out", D, "--in-process"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=float(timeout))
    except subprocess.TimeoutExpired:
        out.update({"pass": False, "error": f"child timed out after {timeout} s", "child": {"cmd": cmd}})
        return out
    child = {"returncode": p.returncode, "cmd": cmd}
    for line in p.stdout.splitlines():
        if line.startswith(TAG + " "):
            try:
                res = json.loads(line[len(TAG) + 1:])
            except ValueError as ex:
                out.update({"pass": False, "error": f"child output not JSON: {ex}", "child": dict(child, line=line[:800])})
                return out
            res["child"] = child
            return res
    out.update({"pass": False, "error": "child produced no tagged line",
                "child": dict(child, stderr_tail=p.stderr[-1500:], stdout_tail=p.stdout[-1500:])})
    return out


def _library_selftest_body(out_dir):
    """The selftest proper. Replaces the open file (open_mainfile) -- run it in a child process (library_selftest)."""
    D = os.path.abspath(bpy.path.abspath(out_dir)); shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
    lib_p, shot_p = os.path.join(D, "lib_crate.blend"), os.path.join(D, "shot_crate.blend")
    out = {"op": "library-selftest", "blender": bpy.app.version_string, "dir": D}
    # 1 library (session emptied by deleting data-blocks; saved as a copy so the session stays untitled and can link it)
    _wipe_session()
    col = bpy.data.collections.new("COL_Crate"); bpy.context.scene.collection.children.link(col)
    me = bpy.data.meshes.new("GEO_Crate"); me.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    me.materials.append(bpy.data.materials.new("MAT_Wood"))
    geo = bpy.data.objects.new("GEO_Crate", me); col.objects.link(geo)
    for n in ("GEO_Handle", "SOCKET_Top"):
        o = bpy.data.objects.new(n, None); col.objects.link(o); o.parent = geo
    bpy.ops.wm.save_as_mainfile(filepath=lib_p, copy=True)
    out["session_untitled_after_lib_copy"] = bpy.data.filepath == ""
    # 2 shot: link + override hierarchy + edits (first real save of an untitled session makes the library path relative)
    _wipe_session()
    out["session_empty_before_shot"] = not bpy.data.objects and not bpy.data.meshes and not bpy.data.libraries
    with bpy.data.libraries.load(lib_p, link=True, relative=True) as (src, dst):
        dst.collections = ["COL_Crate"]
    inst = bpy.data.objects.new("INST_Crate", None); inst.instance_type = 'COLLECTION'; inst.instance_collection = dst.collections[0]
    bpy.context.scene.collection.objects.link(inst)
    root = dst.collections[0].override_hierarchy_create(bpy.context.scene, bpy.context.view_layer, reference=inst, do_fully_editable=False)
    out["override_root"] = root.name if root else None
    out["instance_empty_left_by_api"] = "INST_Crate" in bpy.data.objects
    if "INST_Crate" in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects["INST_Crate"])
    edits = {"GEO_Crate": ("location", (5.0, 0.0, 0.0)), "SOCKET_Top": ("location", (0.0, 0.0, 2.0)),
             "GEO_Handle": ("location", (0.0, 3.0, 0.0))}
    for n, (prop, val) in edits.items():
        o = next(o for o in bpy.data.objects if o.name == n and o.library is None and o.override_library)
        o.override_library.is_system_override = False
        setattr(o, prop, val)
        o.override_library.operations_update()
    out["before_change"] = library_report()
    bpy.ops.wm.save_as_mainfile(filepath=shot_p)
    # 3 change the source: add object, move a vertex, rename one overridden object, delete another
    bpy.ops.wm.open_mainfile(filepath=lib_p)
    c = bpy.data.collections["COL_Crate"]
    lid = bpy.data.objects.new("GEO_Lid", None); c.objects.link(lid)
    bpy.data.meshes["GEO_Crate"].vertices[0].co.z = 0.25
    bpy.data.objects["SOCKET_Top"].name = "SOCKET_Lid"
    bpy.data.objects.remove(bpy.data.objects["GEO_Handle"])
    bpy.ops.wm.save_mainfile()
    # 4 reopen shot (auto-resync on load)
    bpy.ops.wm.open_mainfile(filepath=shot_p)
    loc = lambda n: next((list(map(lambda v: round(v, 4), o.location)) for o in bpy.data.objects
                          if o.name == n and o.library is None and o.override_library), None)
    geo_o = next((o for o in bpy.data.objects if o.name == "GEO_Crate" and o.library is None), None)
    out["after_source_change"] = {
        "new_source_object_overridden": loc("GEO_Lid") is not None,
        "source_vertex_z_seen": round(geo_o.data.vertices[0].co.z, 4) if geo_o else None,
        "edit_kept_GEO_Crate_location": loc("GEO_Crate"),
        "renamed_SOCKET_Top_override": loc("SOCKET_Top"), "renamed_as_SOCKET_Lid": loc("SOCKET_Lid"),
        "deleted_GEO_Handle_override": loc("GEO_Handle"),
        "report": library_report()}
    # 5 break the library path
    moved = os.path.join(D, "moved"); os.makedirs(moved)
    shutil.move(lib_p, os.path.join(moved, os.path.basename(lib_p)))
    bpy.ops.wm.open_mainfile(filepath=shot_p)
    out["broken_path"] = library_report()
    out["broken_path"]["edit_kept_GEO_Crate_location"] = loc("GEO_Crate")
    # 6 relocate by searching
    out["relocated"] = library_report(search_dir=moved)
    bpy.ops.wm.save_mainfile()
    bpy.ops.wm.open_mainfile(filepath=shot_p)
    out["after_relocate_reopen"] = library_report()
    out["after_relocate_reopen"]["edit_kept_GEO_Crate_location"] = loc("GEO_Crate")
    out["pass"] = (out["before_change"]["pass"] and not out["broken_path"]["pass"] and out["after_relocate_reopen"]["pass"])
    return out


# ------------------------------------------------------------------ CLI / live
OPS = {"usd": usd_roundtrip, "alembic": alembic_roundtrip, "library": library_report, "library-selftest": library_selftest}


def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="interchange_check.py")
    sub = ap.add_subparsers(dest="op", required=True)
    u = sub.add_parser("usd"); a = sub.add_parser("alembic")
    for p in (u, a):
        p.add_argument("--objects"); p.add_argument("--collection"); p.add_argument("--frames")
        p.add_argument("--tol-mm", type=float, default=0.1); p.add_argument("--out"); p.add_argument("--keep", action="store_true")
        p.add_argument("--import-scale", type=float, default=1.0)
    u.add_argument("--animation", action="store_true"); u.add_argument("--units", default="METERS")
    u.add_argument("--meters-per-unit", type=float, default=1.0); u.add_argument("--no-apply-units", action="store_true")
    u.add_argument("--convert-orientation", action="store_true"); u.add_argument("--forward", default="NEGATIVE_Z")
    u.add_argument("--up", default="Y"); u.add_argument("--subdiv", default="BEST_MATCH"); u.add_argument("--no-materials", action="store_true")
    u.add_argument("--materialx", action="store_true"); u.add_argument("--instancing", action="store_true")
    u.add_argument("--usdz", action="store_true"); u.add_argument("--root-prim", default="/root")
    u.add_argument("--expect-units", help="unit the consumer requires; stage metersPerUnit must match")
    a.add_argument("--export-scale", type=float, default=1.0)
    l = sub.add_parser("library"); l.add_argument("--search-dir"); l.add_argument("--resync", action="store_true")
    l.add_argument("--enforce", action="store_true"); l.add_argument("--save", action="store_true")
    s = sub.add_parser("library-selftest"); s.add_argument("--out", required=True)
    s.add_argument("--timeout", type=float, default=600, help="seconds allowed for the child process")
    s.add_argument("--in-process", action="store_true",
                   help="run the selftest body in this session (replaces the open file); passed by the parent to its child")
    o = ap.parse_args(argv)
    if o.op == "usd":
        return usd_roundtrip(o.objects, o.collection, o.animation, o.frames, o.units, o.meters_per_unit, not o.no_apply_units,
                             o.import_scale, o.convert_orientation, o.forward, o.up, o.subdiv, not o.no_materials, o.materialx,
                             o.instancing, o.usdz, o.root_prim, o.tol_mm, o.out, o.keep, expect_units=o.expect_units)
    if o.op == "alembic":
        return alembic_roundtrip(o.objects, o.collection, o.frames, o.export_scale, o.import_scale, o.tol_mm, out_dir=o.out, keep=o.keep)
    if o.op == "library":
        return library_report(o.search_dir, o.resync, o.enforce, o.save)
    return library_selftest(o.out, in_process=o.in_process, timeout=o.timeout)


if "INTERCHANGE_OPTS" in globals():
    _o = dict(INTERCHANGE_OPTS); _op = _o.pop("op")
    result = OPS[_op](**_o)
    print(TAG, json.dumps({"op": _op, "pass": result.get("pass")}))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print(TAG, json.dumps(result, default=str))
else:
    result = {"defined": list(OPS.values()) and ["usd_roundtrip", "alembic_roundtrip", "library_report", "library_selftest"]}
