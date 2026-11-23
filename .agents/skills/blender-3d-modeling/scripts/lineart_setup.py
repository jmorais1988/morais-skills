"""Line Art outlines (Grease Pencil v3 `LINEART` modifier) for a scene, collection or object seen by a camera, with
optional bake to editable strokes, stroke/point counts, and an image-space alignment check of the strokes against a
Workbench object-ID render (silhouette edges).

Headless / CLI (prints one line `LINEART_SETUP {json}`):
    blender -b scene.blend --python lineart_setup.py -- [--source SCENE|COLLECTION|OBJECT --source-name Props \
        --camera CAM_Main --name LINES_Lineart --layer Lines --radius 0.003 --crease 140 --no-contour --no-crease \
        --no-intersection --material-borders --edge-marks --loose --occlusion 0 0 --silhouette NONE|GROUP|INDIVIDUAL \
        --color 0 0 0 --opacity 1 --bake --bake-range CURRENT|RANGE --verify <dir> --verify-res 320 --tol-px 2 \
        --save out.blend]
Live (Blender MCP execute): set before exec
    LINEART_OPTS = {"source": "COLLECTION", "source_name": "Props", "crease": False, "bake": True, "verify_dir": "//qa"}
    -> `result` dict. Without LINEART_OPTS only functions are defined (setup_lineart, stroke_stats, bake_lineart,
    clear_bake, verify_alignment).

What it builds (idempotent: object/layer/material/modifier with the same names are reused)
- Grease Pencil object <name> (created at the origin; moving it did not offset generated lines in tests), layer <layer> with a keyframe, stroke material
  MAT_<name> (stroke on, fill off), modifier "LineArt" (radius = stroke half-width in metres, world space).
- camera: default scene.camera; a different --camera sets use_custom_camera/source_camera (render from that camera!).
- bake: bpy.ops.object.lineart_bake_strokes bakes EVERY frame of the scene range (250 keyframes on a default scene);
  CURRENT temporarily narrows the range to the current frame. Baked modifiers are frozen (is_baked) until clear_bake().

Report: strokes/points evaluated (and baked), source mesh count, defects: no_camera, empty_source, zero_strokes,
camera_mismatch (custom camera differs from scene.camera), baked_stale_risk (note), misaligned (verify).
verify_alignment: renders object IDs with Workbench (flat, AA off, film transparent), marks pixels whose 4-neighbour ID
differs as edges, projects stroke points (GP matrix_world applied) through scene.camera, densifies to 0.5 px and reports
precision (stroke samples within tol px of an edge) and recall (edge pixels within tol px of a stroke). Only contour lines
are in an ID mask: with crease/intersection/material/edge-mark lines enabled, precision is reported but not gated.
Limitations: Line Art sees meshes (and objects convertible to meshes) only; Workbench mask ignores GP-only occluders and
alpha-clipped materials; gates default precision >= 0.9 and recall >= 0.8.
"""
import bpy, json, math, os, sys
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree
from bpy_extras.object_utils import world_to_camera_view

GEOM_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'}


def _material(name, color, opacity):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if not mat.is_grease_pencil:
        bpy.data.materials.create_gpencil_data(mat)
    st = mat.grease_pencil
    st.color = (color[0], color[1], color[2], opacity); st.show_stroke = True; st.show_fill = False
    return mat


def source_objects(source="SCENE", source_name=None, scene=None):
    scene = scene or bpy.context.scene
    if source == "SCENE":
        objs = [o for o in scene.objects if o.type in GEOM_TYPES and o.visible_get()]
    elif source == "COLLECTION":
        coll = bpy.data.collections.get(source_name or "")
        objs = [o for o in coll.all_objects if o.type in GEOM_TYPES] if coll else None
    elif source == "OBJECT":
        o = bpy.data.objects.get(source_name or "")
        objs = [o] if o is not None and o.type in GEOM_TYPES else None
    else:
        raise ValueError("source must be SCENE, COLLECTION or OBJECT")
    if objs is None: return None
    return [o for o in objs if getattr(getattr(o, "lineart", None), "usage", "INHERIT") != 'EXCLUDE']


def _drawings(ob, evaluated):
    src = ob.evaluated_get(bpy.context.evaluated_depsgraph_get()) if evaluated else ob
    for L in src.data.layers:
        if L.hide: continue
        fr = L.current_frame()
        if fr is not None and fr.drawing is not None:
            yield src, L, fr.drawing


def stroke_stats(ob, evaluated=True):
    strokes = points = 0
    for _src, _L, dr in _drawings(ob, evaluated):
        strokes += len(dr.strokes)
        pos = dr.attributes.get("position")
        points += len(pos.data) if pos is not None else 0
    frames = {L.name: [f.frame_number for f in L.frames] for L in ob.data.layers}
    return {"strokes": strokes, "points": points, "keyframes": frames}


def _with_active(ob, op, **kw):
    vl = bpy.context.view_layer; prev = vl.objects.active
    sel = [o for o in vl.objects if o.select_get()]
    for o in sel: o.select_set(False)
    ob.select_set(True); vl.objects.active = ob
    try:
        with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
            return op(**kw)
    finally:
        ob.select_set(False)
        for o in sel: o.select_set(True)
        vl.objects.active = prev


def bake_lineart(ob, bake_range="CURRENT", scene=None):
    scene = scene or bpy.context.scene
    fs, fe, cur = scene.frame_start, scene.frame_end, scene.frame_current
    if bake_range == "CURRENT":
        scene.frame_end = max(fe, cur); scene.frame_start = cur; scene.frame_end = cur
    try:
        ret = _with_active(ob, bpy.ops.object.lineart_bake_strokes, bake_all=False)
    finally:
        scene.frame_start = min(fs, scene.frame_start); scene.frame_end = fe; scene.frame_start = fs
        scene.frame_set(cur)
    mods = [m for m in ob.modifiers if m.type == 'LINEART']
    return {"op": sorted(ret), "is_baked": all(m.is_baked for m in mods), **stroke_stats(ob, evaluated=False)}


def clear_bake(ob):
    return sorted(_with_active(ob, bpy.ops.object.lineart_clear))


def setup_lineart(source="SCENE", source_name=None, camera=None, name="LINES_Lineart", layer="Lines", radius=0.003,
                  crease_deg=140.0, contour=True, crease=True, intersection=True, material_borders=False,
                  edge_marks=False, loose=False, occlusion=(0, 0), silhouette="NONE", color=(0.0, 0.0, 0.0),
                  opacity=1.0, bake=False, bake_range="CURRENT", verify_dir=None, verify_res=320, tol_px=2.0,
                  scene=None):
    scene = scene or bpy.context.scene
    defects, warnings = [], []
    cam = bpy.data.objects.get(camera) if isinstance(camera, str) else camera
    if camera and cam is None: raise KeyError(f"camera {camera!r} not found")
    if cam is None: cam = scene.camera
    if cam is None or cam.type != 'CAMERA': defects.append("no_camera")
    objs = source_objects(source, source_name, scene)
    if objs is None: raise KeyError(f"{source} {source_name!r} not found")
    if not objs: defects.append("empty_source")

    ob = bpy.data.objects.get(name)
    if ob is not None and ob.type != 'GREASEPENCIL':
        raise TypeError(f"object {name!r} exists and is {ob.type}, not GREASEPENCIL")
    if ob is None:
        gp = bpy.data.grease_pencils.new(name)
        ob = bpy.data.objects.new(name, gp); scene.collection.objects.link(ob)
    gp = ob.data
    mod = next((m for m in ob.modifiers if m.type == 'LINEART'), None)
    if mod is not None and mod.is_baked:
        if bake:
            clear_bake(ob)
        else:
            warnings.append("modifier is baked (frozen): clear_bake(ob) / bpy.ops.object.lineart_clear to regenerate")
    lay = gp.layers.get(layer) or gp.layers.new(layer)
    first = min(scene.frame_start, scene.frame_current)
    if len(lay.frames) == 0:
        lay.frames.new(first)
    mat = _material(f"MAT_{name}", color, opacity)
    if gp.materials.find(mat.name) < 0:
        gp.materials.append(mat)
    if mod is None:
        mod = ob.modifiers.new("LineArt", 'LINEART')
    mod.source_type = source
    if source == "COLLECTION": mod.source_collection = bpy.data.collections.get(source_name)
    if source == "OBJECT": mod.source_object = bpy.data.objects.get(source_name)
    mod.target_layer = lay.name; mod.target_material = mat
    mod.radius = radius; mod.opacity = opacity
    mod.use_contour = contour; mod.use_crease = crease; mod.crease_threshold = math.radians(crease_deg)
    mod.use_intersection = intersection; mod.use_material = material_borders; mod.use_edge_mark = edge_marks
    mod.use_loose = loose
    lo, hi = occlusion
    mod.use_multiple_levels = hi > lo; mod.level_start = lo; mod.level_end = hi
    mod.silhouette_filtering = silhouette
    if cam is not None and scene.camera is not None and cam != scene.camera:
        mod.use_custom_camera = True; mod.source_camera = cam
    else:
        mod.use_custom_camera = False
    if mod.use_custom_camera and mod.source_camera != scene.camera:
        defects.append(f"camera_mismatch:{mod.source_camera.name}!=scene.camera:{scene.camera.name if scene.camera else None}")
    bpy.context.evaluated_depsgraph_get().update()
    st = stroke_stats(ob, evaluated=True)
    if st["strokes"] == 0 and "no_camera" not in defects: defects.append("zero_strokes")
    elif st["strokes"] == 0: defects.append("zero_strokes")
    result = {"object": ob.name, "layer": lay.name, "material": mat.name, "modifier": mod.name, "source": source,
              "source_name": source_name, "source_meshes": len(objs), "camera": cam.name if cam else None,
              "settings": {"radius_m": radius, "crease_deg": crease_deg, "contour": contour, "crease": crease,
                           "intersection": intersection, "material_borders": material_borders,
                           "edge_marks": edge_marks, "loose": loose, "occlusion": list(occlusion)},
              "evaluated": st}
    if bake:
        result["baked"] = bake_lineart(ob, bake_range, scene)
        warnings.append("baked strokes do not follow later scene/camera edits until clear_bake + re-bake")
    if verify_dir:
        v = verify_alignment(ob, verify_dir, verify_res, tol_px, scene, objs)
        result["verify"] = v
        defects += v.get("defects", [])
    result["defects"], result["warnings"] = defects, warnings
    result["passed"] = not defects
    return result


def _id_color(i):
    def s2l(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    k = i + 1
    return (s2l(((k >> 8) & 15) / 15), s2l(((k >> 4) & 15) / 15), s2l((k & 15) / 15), 1.0)


def verify_alignment(ob, out_dir, res=320, tol_px=2.0, scene=None, objs=None, min_precision=0.9, min_recall=0.8):
    scene = scene or bpy.context.scene; cam = scene.camera
    if cam is None: return {"defects": ["no_camera"]}
    mod = next((m for m in ob.modifiers if m.type == 'LINEART'), None)
    objs = objs if objs is not None else source_objects(mod.source_type if mod else "SCENE",
                                                        (mod.source_collection.name if mod and mod.source_collection else
                                                         mod.source_object.name if mod and mod.source_object else None), scene)
    out_dir = bpy.path.abspath(out_dir); os.makedirs(out_dir, exist_ok=True)
    r, sh, vs = scene.render, scene.display.shading, scene.view_settings
    aspect = r.resolution_x / r.resolution_y
    W, H = (res, max(1, round(res / aspect))) if aspect >= 1 else (max(1, round(res * aspect)), res)
    saved = {"engine": r.engine, "rx": r.resolution_x, "ry": r.resolution_y, "pct": r.resolution_percentage,
             "ft": r.film_transparent, "fp": r.filepath, "ff": r.image_settings.file_format,
             "cm": r.image_settings.color_mode, "vt": vs.view_transform, "look": vs.look, "exp": vs.exposure,
             "gam": vs.gamma, "light": sh.light, "ct": sh.color_type, "aa": scene.display.render_aa,
             "cav": sh.show_cavity, "shd": sh.show_shadows, "ol": sh.show_object_outline, "xr": sh.show_xray,
             "spec": sh.show_specular_highlight, "dither": r.dither_intensity}
    ids = {o.name for o in objs}
    hidden = [o for o in scene.objects if not o.hide_render and o.name not in ids]
    colors = {o.name: tuple(o.color) for o in objs}
    path = os.path.join(out_dir, f"lineart_verify_{ob.name}.png")
    try:
        for o in hidden: o.hide_render = True
        for i, o in enumerate(objs): o.color = _id_color(i)
        r.engine = 'BLENDER_WORKBENCH'; r.resolution_x, r.resolution_y, r.resolution_percentage = W, H, 100
        r.film_transparent = True; r.filepath = path; r.dither_intensity = 0.0  # dither noise = fake ID edges
        r.image_settings.file_format = 'PNG'; r.image_settings.color_mode = 'RGBA'
        vs.view_transform = 'Standard'; vs.look = 'None'; vs.exposure = 0.0; vs.gamma = 1.0
        sh.light = 'FLAT'; sh.color_type = 'OBJECT'; scene.display.render_aa = 'OFF'
        sh.show_cavity = sh.show_shadows = sh.show_object_outline = sh.show_xray = sh.show_specular_highlight = False
        bpy.ops.render.render(write_still=True)
    finally:
        for o in hidden: o.hide_render = False
        for o in objs: o.color = colors[o.name]
        r.engine = saved["engine"]; r.resolution_x, r.resolution_y, r.resolution_percentage = saved["rx"], saved["ry"], saved["pct"]
        r.film_transparent = saved["ft"]; r.filepath = saved["fp"]; r.dither_intensity = saved["dither"]
        r.image_settings.file_format = saved["ff"]; r.image_settings.color_mode = saved["cm"]
        vs.view_transform = saved["vt"]; vs.look = saved["look"]; vs.exposure = saved["exp"]; vs.gamma = saved["gam"]
        sh.light = saved["light"]; sh.color_type = saved["ct"]; scene.display.render_aa = saved["aa"]
        sh.show_cavity, sh.show_shadows, sh.show_object_outline = saved["cav"], saved["shd"], saved["ol"]
        sh.show_xray, sh.show_specular_highlight = saved["xr"], saved["spec"]
    img = bpy.data.images.load(path, check_existing=False)
    px = np.empty(W * H * 4, np.float32); img.pixels.foreach_get(px); bpy.data.images.remove(img)
    px = px.reshape(H, W, 4)
    q = np.round(px[..., :3] * 15).astype(np.int64)  # ID colours sit on 4-bit sRGB levels
    key = q[..., 0] * 256 + q[..., 1] * 16 + q[..., 2]
    key[px[..., 3] < 0.5] = -1
    edge = np.zeros((H, W), bool)
    dx = key[:, 1:] != key[:, :-1]; edge[:, 1:] |= dx; edge[:, :-1] |= dx
    dy = key[1:, :] != key[:-1, :]; edge[1:, :] |= dy; edge[:-1, :] |= dy
    ey, ex = np.nonzero(edge)
    samples = []
    dg = bpy.context.evaluated_depsgraph_get()
    for src, _L, dr in _drawings(ob, evaluated=True):
        M = src.matrix_world
        cyc = dr.attributes.get("cyclic")
        for si, s in enumerate(dr.strokes):
            pts = []
            for p in s.points:
                c = world_to_camera_view(scene, cam, M @ Vector(p.position))
                pts.append((c.x * W, c.y * H, c.z))
            if s.cyclic and len(pts) > 2: pts.append(pts[0])
            for a, b in zip(pts, pts[1:] if len(pts) > 1 else pts):
                if a[2] <= 0 and b[2] <= 0: continue
                n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.5))
                for k in range(n + 1):
                    t = k / n; x = a[0] + (b[0] - a[0]) * t; y = a[1] + (b[1] - a[1]) * t
                    if 0 <= x < W and 0 <= y < H: samples.append((x, y))
    res_d = {"mask": path, "res": [W, H], "edge_px": int(len(ex)), "samples": len(samples), "tol_px": tol_px}
    defects = []
    if not samples or not len(ex):
        res_d.update({"precision_within_tol": 0.0, "recall_within_tol": 0.0})
        defects.append("misaligned:no_samples_or_edges"); res_d["defects"] = defects; return res_d
    ke = KDTree(len(ex))
    for i, (x, y) in enumerate(zip(ex, ey)): ke.insert((x + 0.5, y + 0.5, 0.0), i)
    ke.balance()
    d_s = np.array([ke.find((x, y, 0.0))[2] for x, y in samples])
    ks = KDTree(len(samples))
    for i, (x, y) in enumerate(samples): ks.insert((x, y, 0.0), i)
    ks.balance()
    d_e = np.array([ks.find((x + 0.5, y + 0.5, 0.0))[2] for x, y in zip(ex, ey)])
    prec = float((d_s <= tol_px).mean()); rec = float((d_e <= tol_px).mean())
    res_d.update({"precision_within_tol": round(prec, 4), "recall_within_tol": round(rec, 4),
                  "sample_to_edge_px": {"p50": round(float(np.percentile(d_s, 50)), 2), "p95": round(float(np.percentile(d_s, 95)), 2)},
                  "edge_to_stroke_px": {"p50": round(float(np.percentile(d_e, 50)), 2), "p95": round(float(np.percentile(d_e, 95)), 2)}})
    interior = bool(mod and (mod.use_crease or mod.use_intersection or mod.use_material or mod.use_edge_mark))
    res_d["precision_gated"] = not interior
    if not interior and prec < min_precision: defects.append(f"misaligned:precision={prec:.3f}<{min_precision}")
    if rec < min_recall: defects.append(f"misaligned:recall={rec:.3f}<{min_recall}")
    res_d["defects"] = defects
    return res_d


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="lineart_setup.py")
    p.add_argument("--source", default="SCENE", choices=["SCENE", "COLLECTION", "OBJECT"]); p.add_argument("--source-name")
    p.add_argument("--camera"); p.add_argument("--name", default="LINES_Lineart"); p.add_argument("--layer", default="Lines")
    p.add_argument("--radius", type=float, default=0.003); p.add_argument("--crease", type=float, default=140.0)
    p.add_argument("--no-contour", action="store_true"); p.add_argument("--no-crease", action="store_true")
    p.add_argument("--no-intersection", action="store_true"); p.add_argument("--material-borders", action="store_true")
    p.add_argument("--edge-marks", action="store_true"); p.add_argument("--loose", action="store_true")
    p.add_argument("--occlusion", type=int, nargs=2, default=[0, 0])
    p.add_argument("--silhouette", default="NONE", choices=["NONE", "GROUP", "INDIVIDUAL"])
    p.add_argument("--color", type=float, nargs=3, default=[0.0, 0.0, 0.0]); p.add_argument("--opacity", type=float, default=1.0)
    p.add_argument("--bake", action="store_true"); p.add_argument("--bake-range", default="CURRENT", choices=["CURRENT", "RANGE"])
    p.add_argument("--verify"); p.add_argument("--verify-res", type=int, default=320); p.add_argument("--tol-px", type=float, default=2.0)
    p.add_argument("--save")
    a = p.parse_args(argv)
    res = setup_lineart(a.source, a.source_name, a.camera, a.name, a.layer, a.radius, a.crease, not a.no_contour,
                        not a.no_crease, not a.no_intersection, a.material_borders, a.edge_marks, a.loose,
                        tuple(a.occlusion), a.silhouette, tuple(a.color), a.opacity, a.bake, a.bake_range,
                        a.verify, a.verify_res, a.tol_px)
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(a.save)); res["saved"] = a.save
    return res


if "LINEART_OPTS" in globals():  # live exec
    result = setup_lineart(**dict(LINEART_OPTS))
    print("LINEART_SETUP " + json.dumps(result))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print("LINEART_SETUP " + json.dumps(result))
else:
    result = {"defined": ["setup_lineart", "stroke_stats", "bake_lineart", "clear_bake", "verify_alignment", "source_objects"]}
