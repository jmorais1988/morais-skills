"""Real-time performance estimate for a scene or collection: triangles, draw calls (naive vs instancing-aware),
materials, unique textures and texture memory (uncompressed and block-compressed), largest offenders, budget check.

Headless / CLI (prints one line: SCENE_PERF_REPORT <json>):
    blender -b scene.blend --python scene_perf_report.py -- [--collection NAME] [--budget quest3|quest2|pcvr|mobile|web|pc]
        [--max-draw-calls N] [--max-tris N] [--max-texture-mb N] [--top 10] [--include-hidden] [--no-overdraw]
        [--overdraw-res 96] [--camera CAM_Main]
    --max-* override single limits of the chosen preset (or, without --budget, define a custom budget of just those
    limits); overdraw limits come from the preset only.
Live (Blender:execute_blender_code): set before exec
    PERF_OPTS = {"collection": "Export", "budget": "quest3", "max_draw_calls": 400, "overdraw_res": 64}  -> `result` dict
Without PERF_OPTS the file only defines perf_report, material_transparency, overdraw_estimate and BUDGETS.

What is counted (evaluated depsgraph, render-visible objects, including collection / Geometry Nodes instances):
  tris              loop triangles per instance (so instances multiply triangles, as the GPU draws them)
  draw calls        per instance: number of material slots actually used by polygons (unused slots don't draw).
                    naive = every instance draws separately; instanced = instances of the same mesh data + material
                    collapse to one call (GPU instancing / SRP batcher-like best case). Engines land between the two;
                    shadow, depth prepass and extra lights multiply the real number.
  texture memory    per unique image used by the materials in use (node trees walked through groups):
                    w * h * channels * bytes/channel (float images 4) * 4/3 mips  = uncompressed;
                    w * h * 1 byte * 4/3 = BC7 / ASTC 4x4 estimate (8 bits per pixel); ASTC 6x6 ~ 3.56 bpp, 8x8 2 bpp.
  transparency      per used material: BLENDED (alpha/transparent BSDF with surface_render_method BLENDED),
                    ALPHA_CLIP (alpha with DITHERED = cutout/MASK at export; alpha test defeats early-z on tiled mobile
                    GPUs), TRANSMISSION (transmission / glass / refraction without alpha).
  overdraw          (active or named camera) one ray per pixel of a low-res grid (default 96 px wide): nearest opaque hit
                    = depth; every transparent triangle crossed in front of it = one layer (front faces only when the
                    material uses backface culling). Reports transparent screen coverage, mean layers over the whole
                    frame (= full-screen transparent passes), max / p95 layers, per-object coverage, projected bbox area.
Budgets (whole visible frame; see game-engine-delivery.md and web-and-mobile-delivery.md): Meta Quest figures are Meta's published per-frame
ranges (upper ends used); overdraw limits are rules of thumb. A budget pass is necessary, not sufficient - profile on
device. The gate compares: draw_calls -> totals.draw_calls_naive (worst case, every instance drawn separately; the
instanced count is reported next to it in the budget block, not gated), tris -> totals.tris, texture_mb ->
totals.texture_mb_compressed_est, overdraw_layers / max_layers -> the overdraw estimate (only when a camera is used).
budget.gated_on names the source field of every check; budget.overrides lists the --max-* limits that replaced preset
values.
Limitations: images that can't be loaded report size 0 (listed under unloaded_images); UDIM tiles count as one tile;
particle-hair and volumes are ignored; draw calls ignore engine batching/merging of static meshes; overdraw uses only
the objects in scope as occluders, ignores alpha value (a 0-alpha texel still costs a fragment) and particle/hair
cards, and samples one ray per grid pixel (sub-pixel cards can be missed; raise --overdraw-res).
"""
import bpy, json, sys
import numpy as np
from collections import defaultdict

BUDGETS = {  # draw_calls, tris, texture_mb (compressed estimate), overdraw_layers (mean over frame), max_layers
    "quest2": {"draw_calls": 300, "tris": 1_000_000, "texture_mb": 512, "overdraw_layers": 0.5, "max_layers": 4, "note": "Meta: 200-300 draws, 750k-1M tris per frame (medium sim); overdraw limits rule of thumb"},
    "quest3": {"draw_calls": 600, "tris": 1_800_000, "texture_mb": 1024, "overdraw_layers": 0.5, "max_layers": 4, "note": "Meta: 400-600 draws, 1.3-1.8M tris per frame (medium sim); overdraw limits rule of thumb"},
    "pcvr": {"draw_calls": 1000, "tris": 2_000_000, "texture_mb": 2048, "overdraw_layers": 1.0, "max_layers": 8, "note": "Meta PC VR guideline: 500-1000 draws, 1-2M tris per frame; overdraw limits rule of thumb"},
    "mobile": {"draw_calls": 150, "tris": 150_000, "texture_mb": 256, "overdraw_layers": 0.5, "max_layers": 4, "note": "rule of thumb, mid-range phone"},
    "web": {"draw_calls": 100, "tris": 150_000, "texture_mb": 128, "overdraw_layers": 1.0, "max_layers": 6, "note": "rule of thumb, three.js / model-viewer on mid-range devices"},
    "pc": {"draw_calls": 3000, "tris": 5_000_000, "texture_mb": 4096, "overdraw_layers": 2.0, "max_layers": 16, "note": "rule of thumb, current PC/console without Nanite"},
}
TRANSPARENT_NODES = {'BSDF_TRANSPARENT': "transparent_bsdf", 'BSDF_GLASS': "glass", 'BSDF_REFRACTION': "refraction"}


def material_transparency(mat):
    """(kind, reasons): kind None | 'BLENDED' | 'ALPHA_CLIP' | 'TRANSMISSION'."""
    if mat is None or mat.node_tree is None: return None, []
    reasons = set()

    def walk(tree, seen):
        if tree is None or tree.name in seen: return
        seen.add(tree.name)
        for n in tree.nodes:
            if n.type in TRANSPARENT_NODES: reasons.add(TRANSPARENT_NODES[n.type])
            if n.bl_idname == 'ShaderNodeBsdfPrincipled':
                a, t = n.inputs.get("Alpha"), n.inputs.get("Transmission Weight")
                if a is not None and (a.is_linked or a.default_value < 0.999): reasons.add("alpha")
                if t is not None and (t.is_linked or t.default_value > 0.001): reasons.add("transmission")
            if n.type == 'GROUP' and n.node_tree: walk(n.node_tree, seen)
    walk(mat.node_tree, set())
    if not reasons: return None, []
    if getattr(mat, "surface_render_method", "DITHERED") == 'BLENDED': kind = 'BLENDED'
    elif reasons & {"alpha", "transparent_bsdf"}: kind = 'ALPHA_CLIP'
    else: kind = 'TRANSMISSION'
    return kind, sorted(reasons)


def overdraw_estimate(items, camera=None, res=96, max_tris=3_000_000):
    """items: [(owner, world_co Nx3, tris Mx3, transparent_mask M, cull_mask M)]. Ray-cast layer count per pixel."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene; cam = bpy.data.objects.get(camera) if camera else sc.camera
    if cam is None or cam.type != 'CAMERA': return {"skipped": "no camera"}
    if sum(len(t) for _, _, t, _, _ in items) > max_tris: return {"skipped": f"more than {max_tris} triangles"}
    tr, br, bl, tl = [Vector(v) for v in cam.data.view_frame(scene=sc)]
    W = int(res); H = max(1, int(round(W * (tl - bl).length / max((br - bl).length, 1e-9))))
    mw = cam.matrix_world; persp = cam.data.type != 'ORTHO'; cam_o = mw.translation.copy()
    fwd = (mw.to_3x3() @ Vector((0, 0, -1))).normalized()
    op_v, op_t, off = [], [], 0
    for _, co, t, tm, _ in items:
        k = ~tm
        if k.any(): op_v.append(co); op_t.append(t[k] + off); off += len(co)
    opaque = BVHTree.FromPolygons(np.vstack(op_v).tolist(), np.vstack(op_t).tolist()) if op_t else None
    trans = []
    for owner, co, t, tm, cm in items:
        if not tm.any(): continue
        tt = t[tm]; used = np.unique(tt); remap = np.full(len(co), -1); remap[used] = np.arange(len(used))
        tree = BVHTree.FromPolygons(co[used].tolist(), remap[tt].tolist())
        lo, hi = co[used].min(0), co[used].max(0)
        corners = [world_to_camera_view(sc, cam, Vector((x, y, z))) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        if any(c.z <= 0 for c in corners): box = (0, W, 0, H)
        else:
            xs = [c.x for c in corners]; ys = [c.y for c in corners]
            box = (max(0, int(np.floor(min(xs) * W))), min(W, int(np.ceil(max(xs) * W))),
                   max(0, int(np.floor(min(ys) * H))), min(H, int(np.ceil(max(ys) * H))))
        trans.append((owner, tree, cm[tm], box))
    layers = np.zeros((H, W), np.int32); per = defaultdict(lambda: np.zeros((H, W), np.int32)); opaque_px = 0
    for j in range(H):
        for i in range(W):
            p = bl + (br - bl) * ((i + 0.5) / W) + (tl - bl) * ((j + 0.5) / H)
            if persp: o = cam_o; d = (mw @ p - cam_o).normalized()
            else: o = mw @ Vector((p.x, p.y, 0.0)); d = fwd
            far = 1e9
            if opaque is not None:
                hit = opaque.ray_cast(o, d)
                if hit[0] is not None: far = hit[3]; opaque_px += 1
            for owner, tree, cull, (x0, x1, y0, y1) in trans:
                if not (x0 <= i < x1 and y0 <= j < y1): continue
                oo, rem, n = o.copy(), far, 0
                for _ in range(64):
                    loc, nrm, idx, dist = tree.ray_cast(oo, d, rem)
                    if loc is None: break
                    if not cull[idx] or nrm.dot(d) < 0: n += 1
                    oo = loc + d * 1e-5; rem -= dist + 1e-5
                    if rem <= 0: break
                if n: layers[j, i] += n; per[owner][j, i] += n
    npx = W * H; cov = layers > 0
    objs = sorted(({"object": k, "screen_coverage": round(float((v > 0).mean()), 4), "mean_layers_where_covered":
                    round(float(v[v > 0].mean()), 2) if (v > 0).any() else 0.0} for k, v in per.items()),
                  key=lambda x: -x["screen_coverage"] * x["mean_layers_where_covered"])
    bbox = {o: round((b[1] - b[0]) * (b[3] - b[2]) / npx, 4) for o, _, _, b in trans}
    for x in objs: x["bbox_screen_fraction"] = bbox.get(x["object"])
    return {"camera": cam.name, "grid": [W, H], "transparent_objects": len(trans),
            "transparent_coverage": round(float(cov.mean()), 4), "overdraw_layers_mean": round(float(layers.sum() / npx), 3),
            "max_layers": int(layers.max()) if npx else 0,
            "p95_layers_where_covered": float(np.percentile(layers[cov], 95)) if cov.any() else 0.0,
            "opaque_coverage": round(opaque_px / npx, 4), "objects": objs}


def _images_in_tree(tree, seen_trees=None):
    seen_trees = seen_trees if seen_trees is not None else set()
    if tree is None or tree.name in seen_trees: return set()
    seen_trees.add(tree.name); imgs = set()
    for n in tree.nodes:
        if getattr(n, "image", None) is not None: imgs.add(n.image)
        if n.type == 'GROUP' and n.node_tree: imgs |= _images_in_tree(n.node_tree, seen_trees)
    return imgs


def _image_mem(img):
    w, h = img.size[:]
    if (w == 0 or h == 0) and img.source in ('FILE', 'SEQUENCE', 'TILED'):
        try: img.reload(); _ = img.pixels[0]; w, h = img.size[:]
        except Exception: pass
    ch = img.channels or 4; bpc = 4 if img.is_float else 1
    mip = 4 / 3
    return w, h, ch, w * h * ch * bpc * mip, w * h * 1 * mip


def perf_report(collection=None, budget=None, top=10, include_hidden=False, overdraw=True, overdraw_res=96, camera=None,
                max_draw_calls=None, max_tris=None, max_texture_mb=None):
    """max_draw_calls / max_tris / max_texture_mb override the preset limits (or form a custom budget without one)."""
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    col = bpy.data.collections.get(collection) if collection else None
    allowed = set(col.all_objects) if col else None
    per_obj = defaultdict(lambda: {"instances": 0, "tris": 0, "draw_calls": 0, "materials": set()})
    mesh_cache, pairs, tris_total, naive, mats_used, slot_waste = {}, set(), 0, 0, set(), []
    geo_cache, od_items, transp = {}, [], {}
    do_od = overdraw and (camera or bpy.context.scene.camera) is not None
    for inst in dg.object_instances:
        ob = inst.object  # evaluated
        if ob.type != 'MESH': continue
        orig = ob.original
        owner = inst.parent.original if inst.is_instance and inst.parent else orig
        if allowed is not None and owner not in allowed and orig not in allowed: continue
        if not include_hidden and (owner.hide_render or orig.hide_render): continue
        key = ob.data.original.name if ob.data and ob.data.original else ob.name
        # evaluated meshes from modifiers are unique per object: key on object name when modifiers change the mesh
        if ob.data.is_evaluated and not inst.is_instance and orig.modifiers: key = "obj:" + orig.name
        if key not in mesh_cache:
            me = ob.data; me.calc_loop_triangles()
            used = sorted({p.material_index for p in me.polygons}) if len(me.polygons) else []
            slots = [s.material for s in ob.material_slots]
            mats = [(slots[i].name if i < len(slots) and slots[i] else "<none>") for i in used] or ["<none>"]
            mesh_cache[key] = (len(me.loop_triangles), mats, len(slots))
            if len(slots) > len(used): slot_waste.append({"object": orig.name, "slots": len(slots), "used": len(used)})
            for i in used:
                if i < len(slots) and slots[i]: mats_used.add(slots[i])
        t, mats, _ = mesh_cache[key]
        tris_total += t; naive += len(mats)
        for m in mats: pairs.add((key, m))
        r = per_obj[owner.name]; r["instances"] += 1; r["tris"] += t; r["draw_calls"] += len(mats); r["materials"].update(mats)
        slots = [s.material for s in ob.material_slots]
        for m in slots:
            if m is not None and m.name not in transp: transp[m.name] = material_transparency(m)
        if do_od and t:
            if key not in geo_cache:
                me = ob.data; nv = len(me.vertices)
                co = np.empty(nv * 3); me.vertices.foreach_get("co", co)
                tv = np.empty(t * 3, np.int64); me.loop_triangles.foreach_get("vertices", tv)
                tmi = np.empty(t, np.int64); me.loop_triangles.foreach_get("material_index", tmi)
                geo_cache[key] = (co.reshape(-1, 3), tv.reshape(-1, 3), tmi)
            co, tv, tmi = geo_cache[key]
            mw = np.array(inst.matrix_world)
            kinds = np.array([bool(i < len(slots) and slots[i] and transp[slots[i].name][0]) for i in range(max(len(slots), 1))])
            cull = np.array([bool(i < len(slots) and slots[i] and slots[i].use_backface_culling) for i in range(max(len(slots), 1))])
            idx = np.minimum(tmi, len(kinds) - 1)
            od_items.append((owner.name, co @ mw[:3, :3].T + mw[:3, 3], tv, kinds[idx], cull[idx]))
    images = {}
    for m in mats_used:
        for img in _images_in_tree(m.node_tree):
            images.setdefault(img.name, (img, set()))[1].add(m.name)
    tex, unloaded = [], []
    for name, (img, users) in images.items():
        w, h, ch, raw, comp = _image_mem(img)
        if w == 0: unloaded.append(name)
        tex.append({"image": name, "size": [w, h], "channels": ch, "float": img.is_float, "mb_uncompressed": round(raw / 2**20, 2),
                    "mb_compressed_est": round(comp / 2**20, 2), "materials": sorted(users)})
    tex.sort(key=lambda x: -x["mb_uncompressed"])
    mat_tex = sorted(({"material": m.name, "textures": len(_images_in_tree(m.node_tree))} for m in mats_used), key=lambda x: -x["textures"])
    objs = [{"object": k, "instances": v["instances"], "tris": v["tris"], "draw_calls": v["draw_calls"], "materials": len(v["materials"])} for k, v in per_obj.items()]
    out = {
        "blender": bpy.app.version_string, "scope": collection or bpy.context.scene.name,
        "totals": {"objects": len(objs), "instances": sum(o["instances"] for o in objs), "tris": tris_total,
                   "draw_calls_naive": naive, "draw_calls_instanced": len(pairs), "materials": len(mats_used),
                   "unique_mesh_data": len(mesh_cache), "unique_textures": len(tex),
                   "texture_mb_uncompressed": round(sum(t["mb_uncompressed"] for t in tex), 2),
                   "texture_mb_compressed_est": round(sum(t["mb_compressed_est"] for t in tex), 2)},
        "top_tris": sorted(objs, key=lambda o: -o["tris"])[:top],
        "top_draw_calls": sorted(objs, key=lambda o: -o["draw_calls"])[:top],
        "top_textures": tex[:top], "materials_by_texture_count": mat_tex[:top],
        "unused_material_slots": slot_waste[:top], "unloaded_images": unloaded,
    }
    tips = []
    T = out["totals"]
    if T["materials"] > 0 and T["draw_calls_naive"] > 2 * max(1, T["draw_calls_instanced"]): tips.append("many repeated meshes: use linked duplicates / collection instances and engine GPU instancing")
    if T["materials"] >= 8 and T["unique_textures"] >= T["materials"]: tips.append("one texture set per material: atlas small props into shared materials (merge + repack UVs + rebake)")
    if any(t["size"][0] >= 4096 for t in tex): tips.append("4K textures present: check texel density; 2K is usually enough for props")
    if slot_waste: tips.append("material slots without faces: remove unused slots (Material > Remove Unused Slots)")
    out["transparent_materials"] = [{"material": m.name, "kind": transp[m.name][0], "reasons": transp[m.name][1],
                                     "render_method": getattr(m, "surface_render_method", None)}
                                    for m in sorted(mats_used, key=lambda x: x.name) if transp.get(m.name, (None,))[0]]
    T["transparent_materials"] = len(out["transparent_materials"])
    od = overdraw_estimate(od_items, camera, overdraw_res) if do_od else {"skipped": "no camera" if overdraw else "disabled"}
    if "objects" in od: od["objects"] = od["objects"][:top]
    out["overdraw"] = od
    if od.get("overdraw_layers_mean", 0) > 0.5 or od.get("max_layers", 0) > 4:
        tips.append("transparent overdraw: trim cards to the opaque area, prefer opaque or alpha-clip, avoid stacked / "
                    "camera-filling transparent planes, merge layered decals into the base texture")
    if any(x["kind"] == 'TRANSMISSION' for x in out["transparent_materials"]):
        tips.append("transmission/glass materials: most real-time targets render them as alpha blend - author a cheap blended variant")
    out["tips"] = tips
    overrides = {k: v for k, v in (("draw_calls", max_draw_calls), ("tris", max_tris), ("texture_mb", max_texture_mb)) if v is not None}
    if budget or overrides:
        b = dict(BUDGETS[budget]) if budget else {"note": "custom limits only (no preset)"}
        b.update(overrides)
        # (value, limit, source field) - draw calls are gated on the NAIVE count (worst case), instanced is informative
        checks = {k: (val, b[k], src) for k, (val, src) in (
            ("draw_calls", (T["draw_calls_naive"], "totals.draw_calls_naive")), ("tris", (T["tris"], "totals.tris")),
            ("texture_mb", (T["texture_mb_compressed_est"], "totals.texture_mb_compressed_est"))) if k in b}
        if "overdraw_layers_mean" in od and "overdraw_layers" in b:
            checks["overdraw_layers"] = (od["overdraw_layers_mean"], b["overdraw_layers"], "overdraw.overdraw_layers_mean")
            checks["max_layers"] = (od["max_layers"], b["max_layers"], "overdraw.max_layers")
        out["budget"] = {"name": budget or "custom", "note": b["note"], "overrides": overrides,
                         "gated_on": {k: s for k, (_, _, s) in checks.items()},
                         "draw_calls_naive": T["draw_calls_naive"], "draw_calls_instanced": T["draw_calls_instanced"],
                         "checks": {k: {"value": v, "limit": l, "pass": v <= l} for k, (v, l, _) in checks.items()}}
        out["budget"]["pass"] = all(c["pass"] for c in out["budget"]["checks"].values())
    return out


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="scene_perf_report.py")
    p.add_argument("--collection"); p.add_argument("--budget", choices=sorted(BUDGETS)); p.add_argument("--top", type=int, default=10)
    p.add_argument("--include-hidden", action="store_true"); p.add_argument("--no-overdraw", action="store_true")
    p.add_argument("--overdraw-res", type=int, default=96); p.add_argument("--camera")
    p.add_argument("--max-draw-calls", type=int, help="override the preset draw-call limit (gated on draw_calls_naive)")
    p.add_argument("--max-tris", type=int, help="override the preset triangle limit")
    p.add_argument("--max-texture-mb", type=float, help="override the preset compressed texture-memory limit (MB)")
    a = p.parse_args(argv)
    return perf_report(a.collection, a.budget, a.top, a.include_hidden, not a.no_overdraw, a.overdraw_res, a.camera,
                       a.max_draw_calls, a.max_tris, a.max_texture_mb)


if "PERF_OPTS" in globals():
    result = perf_report(**PERF_OPTS)
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("SCENE_PERF_REPORT " + json.dumps(result, default=str))
else:
    result = {"defined": ["perf_report", "material_transparency", "overdraw_estimate", "BUDGETS"]}
