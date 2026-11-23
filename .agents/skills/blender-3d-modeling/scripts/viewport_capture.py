"""Review captures of a target from fixed views (front/right/back/left/top/bottom/persp) in several shadings, framed on
the target's world bounding box -- in a live UI session (viewport OpenGL render) or headless (Workbench render).
Writes PNGs, returns their paths plus a framing check, and restores camera, view, shading and render settings.

Headless / CLI (prints one line: VIEWPORT_CAPTURE <json>):
    blender -b scene.blend --python viewport_capture.py -- --out DIR [--targets Obj1,Obj2 | --collection C]
        [--views front,right,back,left,top,persp] [--shading SOLID,WIREFRAME,MATERIAL] [--res 400] [--res-y 300]
        [--margin 1.12] [--persp-lens 50] [--isolate] [--matcap] [--transparent] [--prefix cap]
        [--mode auto|opengl|workbench|screen] [--frames 1:48[:2]]
    --res-y: frame height in px (default = --res, square). --transparent: Film > Transparent (PNG alpha; the framing
    check then masks on alpha). --frames START:END[:STEP]: playblast -- every view/shading pair is captured once per
    frame with the camera fixed per view and framed on the union of the target bbox over the range; files are
    <prefix>_<view>_<shading>_<frame:04d>.png, each image carries "frame", the result adds frames_captured / frames,
    and the current frame is restored afterwards. Off-centre warnings are suppressed for sequences (only empty frames
    are reported). Not available in screen mode.
Live (any bridge that execs code in the UI session): set before exec
    VIEWPORT_CAPTURE_OPTS = {"out": "/tmp/review", "targets": ["Crate"], "views": ["front", "persp"],
                             "shading": ["SOLID", "WIREFRAME"], "res": 400, "frames": "1:48:2"}   -> `result` dict
    ("frames" also accepts {"start": 1, "end": 48, "step": 2} or an explicit list [1, 5, 9])
    python scripts/bridge_client.py exec --port 9876 --file scripts/viewport_capture.py --opts '{"out": "..."}'
Without VIEWPORT_CAPTURE_OPTS the file only defines capture() and helpers.

Modes: `opengl` = bpy.ops.render.opengl(write_still, view_context) inside temp_override of the largest VIEW_3D area,
viewport looking through a temporary camera (UI session only; background mode has no OpenGL context).
`workbench` = BLENDER_WORKBENCH render of the temporary camera (headless ok): SOLID -> studio light, MATERIAL -> solid
with material base colours (Workbench final render has no MATERIAL shading type), WIREFRAME -> temporary Wireframe
modifiers on target meshes (Workbench final render draws nothing for WIREFRAME). `screen` = screen.screenshot_area of
the user's current 3D view as-is (overlays included, one image, may be black when the window isn't composited).
`auto` = opengl when a VIEW_3D exists and not background, else workbench.
Framing check per image: foreground = pixels differing from the corner colour; reports fill fraction and centre
offset of the foreground bbox as a fraction of the frame ("empty" warning when nothing was drawn).
Targets default to selected objects, else all visible mesh/curve objects. Unsaved changes stay unsaved but the file
is marked dirty (temporary camera datablock); nothing is saved.
"""
import bpy, json, math, os, sys
from mathutils import Vector, Matrix, Quaternion, Euler, Color
from bpy_extras.object_utils import world_to_camera_view

VIEW_DIRS = {  # direction from target centre to camera
    "front": Vector((0, -1, 0)), "back": Vector((0, 1, 0)), "right": Vector((1, 0, 0)), "left": Vector((-1, 0, 0)),
    "top": Vector((0, 0, 1)), "bottom": Vector((0, 0, -1)), "persp": Vector((1, -1, 0.75)).normalized(),
    "persp_back": Vector((-1, 1, 0.75)).normalized(),
}
ALIASES = {"three_quarter": "persp", "3q": "persp", "side": "right"}


def find_view3d():
    best = None
    wm = bpy.context.window_manager
    for w in (wm.windows if wm else []):
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                r = next((r for r in a.regions if r.type == 'WINDOW'), None)
                if r and (best is None or a.width * a.height > best[1].width * best[1].height):
                    best = (w, a, r)
    return best


def resolve_targets(targets=None, collection=None):
    sc = bpy.context.scene
    if collection:
        coll = bpy.data.collections[collection]
        return [o for o in coll.all_objects if o.type in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES')]
    if targets:
        return [bpy.data.objects[n] for n in targets]
    sel = [o for o in bpy.context.view_layer.objects if o.select_get()] if bpy.context.view_layer else []
    return sel or [o for o in sc.objects if o.type in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT') and o.visible_get()]


def _bounds(pts):
    if not pts:
        raise ValueError("no target geometry")
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def world_bbox(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        ev = o.evaluated_get(dg)
        pts += [ev.matrix_world @ Vector(c) for c in ev.bound_box]
    lo, hi = _bounds(pts)
    return lo, hi, pts


def parse_frames(spec):
    """Frame sequence spec -> sorted list of ints, or None when no sequence is requested. Accepts 'START:END[:STEP]',
    {"start", "end", "step"} or an explicit iterable of frame numbers."""
    if spec is None or spec == "" or spec == ():
        return None
    if isinstance(spec, str):
        parts = [int(x) for x in spec.split(":")]
        if len(parts) not in (2, 3):
            raise ValueError("frames expects START:END[:STEP], got %r" % spec)
        start, end, step = parts[0], parts[1], (parts[2] if len(parts) == 3 else 1)
    elif isinstance(spec, dict):
        start, end, step = int(spec["start"]), int(spec["end"]), int(spec.get("step", 1))
    else:
        frames = sorted({int(f) for f in spec})
        if not frames:
            raise ValueError("frames: empty frame list")
        return frames
    if step <= 0:
        raise ValueError("frames: STEP must be > 0")
    if end < start:
        raise ValueError("frames: END must be >= START")
    return list(range(start, end + 1, step))


def camera_rotation(view, d):
    if view == "top":
        return Matrix.Identity(3).to_quaternion()
    if view == "bottom":
        return Matrix.Rotation(math.pi, 3, 'X').to_quaternion()
    return (-d).to_track_quat('-Z', 'Y')


def frame_camera(cam, view, lo, hi, pts, res_x, res_y, margin, lens):
    d = VIEW_DIRS[view]
    c = (lo + hi) / 2
    radius = max((p - c).length for p in pts) or 1.0
    q = camera_rotation(view, d)
    rot = q.to_matrix()
    right, up = rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0))
    xs = [(p - c).dot(right) for p in pts]
    ys = [(p - c).dot(up) for p in pts]
    # centre on the projected bbox, not on the 3D bbox centre (they differ for oblique views)
    c2 = c + right * (max(xs) + min(xs)) / 2 + up * (max(ys) + min(ys)) / 2
    w, h = (max(xs) - min(xs)) * margin, (max(ys) - min(ys)) * margin
    data = cam.data
    data.sensor_fit = 'AUTO'
    data.shift_x = data.shift_y = 0.0
    cam.rotation_mode = 'QUATERNION'
    rot4 = q.to_matrix().to_4x4()

    def place(loc):
        cam.location, cam.rotation_quaternion = loc, q
        cam.matrix_world = Matrix.Translation(loc) @ rot4  # immediate, no depsgraph update needed for projection

    if view.startswith("persp"):
        data.type = 'PERSP'
        data.lens = lens
        half = math.atan(data.sensor_width / 2 / lens)  # AUTO fit: sensor_width spans the larger dimension
        aspect = min(res_x, res_y) / max(res_x, res_y)
        half_small = math.atan(math.tan(half) * aspect)
        dist = radius * margin / math.sin(half_small)
        sc, big = bpy.context.scene, max(res_x, res_y)
        for _ in range(4):  # centre the PROJECTED bbox with lens shift, then refit the distance
            place(c + d * dist)
            ndc = [world_to_camera_view(sc, cam, p) for p in pts]
            xs2, ys2 = [v.x for v in ndc], [v.y for v in ndc]
            data.shift_x += ((max(xs2) + min(xs2)) / 2 - 0.5) * res_x / big
            data.shift_y += ((max(ys2) + min(ys2)) / 2 - 0.5) * res_y / big
            fit = max(max(xs2) - min(xs2), max(ys2) - min(ys2)) * margin
            dist = max(dist * fit, radius * 1.05)
        place(c + d * dist)
        data.clip_start, data.clip_end = max(1e-4, (dist - radius) * 0.5), dist + radius * 2
    else:
        data.type = 'ORTHO'
        data.ortho_scale = max(w, h * res_x / res_y) if res_x >= res_y else max(h, w * res_y / res_x)
        data.ortho_scale = max(data.ortho_scale, 1e-4)
        dist = radius * 3
        data.clip_start, data.clip_end = max(1e-4, radius * 0.01), dist + radius * 3
        place(c2 + d * dist)
    return {"view": view, "center": [round(v, 4) for v in c2], "ortho_scale": round(data.ortho_scale, 4)
            if data.type == 'ORTHO' else None, "distance": round(dist, 4),
            "shift": [round(data.shift_x, 4), round(data.shift_y, 4)]}


def framing_check(path):
    try:
        import numpy as np
        img = bpy.data.images.load(path, check_existing=False)
        w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
        bpy.data.images.remove(img)
        px = px.reshape(h, w, 4)
        bg = np.median(np.stack([px[0, 0], px[0, -1], px[-1, 0], px[-1, -1]]), axis=0)
        diff = np.abs(px[..., :3] - bg[:3]).max(axis=2)
        if bg[3] < 0.5:  # transparent film: alpha is the cleanest mask
            diff = np.maximum(diff, px[..., 3])
        mask = diff > 0.02
        if not mask.any():
            return {"fill": 0.0, "empty": True}
        ys, xs = np.nonzero(mask)
        bx0, bx1, by0, by1 = xs.min(), xs.max(), ys.min(), ys.max()
        return {"fill": round(float(mask.mean()), 4), "bbox_px": [int(bx0), int(by0), int(bx1), int(by1)],
                "center_offset": [round(float((bx0 + bx1) / 2 / (w - 1) - 0.5), 4),
                                  round(float((by0 + by1) / 2 / (h - 1) - 0.5), 4)],
                "extent": [round(float((bx1 - bx0 + 1) / w), 4), round(float((by1 - by0 + 1) / h), 4)],
                "touches_border": bool(bx0 == 0 or by0 == 0 or bx1 == w - 1 or by1 == h - 1), "empty": False}
    except Exception as ex:  # numpy missing or unreadable file
        return {"error": str(ex)}


class _Saved:
    """Attribute snapshot/restore: add(obj, 'attr', ...) then restore()."""

    def __init__(self):
        self.items = []

    def add(self, holder, *attrs):
        for a in attrs:
            if hasattr(holder, a):
                v = getattr(holder, a)
                if isinstance(v, (Vector, Matrix, Quaternion, Euler, Color)):  # never .copy() an ID (duplicates it)
                    v = v.copy()
                self.items.append((holder, a, v))

    def restore(self):
        for holder, a, v in reversed(self.items):
            try:
                setattr(holder, a, v)
            except Exception:
                pass


def capture(out, targets=None, collection=None, views=("front", "right", "back", "left", "top", "persp"),
            shading=("SOLID",), res=400, res_y=None, margin=1.12, persp_lens=50.0, isolate=False, matcap=False,
            prefix="cap", mode="auto", check=True, transparent=False, frames=None):
    sc = bpy.context.scene
    os.makedirs(out, exist_ok=True)
    views = [ALIASES.get(v, v) for v in views]
    bad = [v for v in views if v not in VIEW_DIRS]
    if bad:
        raise ValueError("unknown views %s (use %s)" % (bad, sorted(VIEW_DIRS)))
    shading = [s.upper() for s in shading]
    frame_list = parse_frames(frames)
    v3d = find_view3d()
    if mode == "auto":
        mode = "opengl" if (v3d and not bpy.app.background) else "workbench"
    if mode in ("opengl", "screen") and (bpy.app.background or not v3d):
        raise RuntimeError("%s mode needs a UI session with a 3D Viewport (background: use mode='workbench')" % mode)
    if mode == "screen" and frame_list:
        raise ValueError("frames (sequence capture) is not available in screen mode")
    objs = resolve_targets(targets, collection)
    warnings, images = [], []
    res_x, res_y = int(res), int(res_y or res)

    if mode == "screen":
        w, a, r = v3d
        path = os.path.join(out, "%s_screen.png" % prefix)
        with bpy.context.temp_override(window=w, area=a, region=r):
            bpy.ops.screen.screenshot_area(filepath=path)
        info = {"view": "screen", "shading": a.spaces.active.shading.type, "path": path,
                "bytes": os.path.getsize(path) if os.path.exists(path) else 0}
        if check and info["bytes"]:
            info["check"] = framing_check(path)
            if info["check"].get("empty"):
                warnings.append("screen: uniform (usually black) image -- the window framebuffer isn't composited "
                                "(minimized/covered/remote); use mode='opengl'")
        return {"mode": mode, "images": [info], "warnings": warnings}

    frame0 = sc.frame_current
    if frame_list:  # fixed camera per view: frame the union of the bbox over the whole sequence
        pts = []
        for f in frame_list:
            sc.frame_set(f)
            pts += world_bbox(objs)[2]
        lo, hi = _bounds(pts)
    else:
        lo, hi, pts = world_bbox(objs)
    saved = _Saved()
    rd = sc.render
    saved.add(sc, "camera")
    saved.add(rd, "resolution_x", "resolution_y", "resolution_percentage", "filepath", "film_transparent", "engine")
    saved.add(rd.image_settings, "file_format", "color_mode")
    cam_data = bpy.data.cameras.new("_capture_cam")
    cam = bpy.data.objects.new("_capture_cam", cam_data)
    sc.collection.objects.link(cam)
    hidden, wire_mods = [], []
    try:
        rd.resolution_x, rd.resolution_y, rd.resolution_percentage = res_x, res_y, 100
        rd.image_settings.file_format = 'PNG'
        rd.image_settings.color_mode = 'RGBA'
        rd.film_transparent = transparent
        sc.camera = cam
        if isolate:
            keep = set(objs) | {cam}
            for o in sc.objects:
                if o not in keep and o.type not in ('LIGHT',) and o.visible_get():
                    hidden.append((o, o.hide_get(), o.hide_render))
                    o.hide_set(True)
                    o.hide_render = True
        if mode == "opengl":
            w, a, r = v3d
            space, rv3d = a.spaces.active, a.spaces.active.region_3d
            saved.add(space.shading, "type", "light", "color_type", "show_xray", "show_xray_wireframe")
            saved.add(space.overlay, "show_overlays")
            saved.add(space, "use_local_camera", "camera")
            saved.add(rv3d, "view_perspective", "view_rotation", "view_location", "view_distance")
            space.overlay.show_overlays = False
            space.use_local_camera = False
            rv3d.view_perspective = 'CAMERA'
        else:
            shd = sc.display.shading
            saved.add(shd, "type", "light", "color_type", "show_xray", "studio_light")
            rd.engine = 'BLENDER_WORKBENCH'
        for view in views:
            frame = frame_camera(cam, view, lo, hi, pts, res_x, res_y, margin, persp_lens)
            for s in shading:
                if mode == "opengl":
                    sh = space.shading
                    sh.type = s if s in ('WIREFRAME', 'SOLID', 'MATERIAL', 'RENDERED') else 'SOLID'
                    if s == 'SOLID':
                        sh.light = 'MATCAP' if matcap else 'STUDIO'
                else:
                    shd = sc.display.shading
                    shd.type = 'SOLID'
                    shd.light = 'MATCAP' if (matcap and s == 'SOLID') else 'STUDIO'
                    shd.color_type = 'MATERIAL' if s in ('MATERIAL', 'RENDERED') else 'SINGLE'
                    if s == 'WIREFRAME' and not wire_mods:
                        thick = max((hi - lo).length * 0.002, 1e-4)
                        for o in objs:
                            if o.type == 'MESH':
                                m = o.modifiers.new("_capture_wire", 'WIREFRAME')
                                m.thickness, m.use_relative_offset, m.use_even_offset = thick, False, True
                                wire_mods.append((o, m))
                    if s != 'WIREFRAME' and wire_mods:
                        for o, m in wire_mods:
                            o.modifiers.remove(m)
                        wire_mods = []
                    if s == 'RENDERED':
                        msg = ("workbench mode: RENDERED approximated by material colours; render with EEVEE/Cycles "
                               "for a true look check")
                        if msg not in warnings:
                            warnings.append(msg)
                for f in (frame_list or [None]):
                    if f is None:
                        path = os.path.join(out, "%s_%s_%s.png" % (prefix, view, s.lower()))
                        tag = "%s/%s" % (view, s)
                    else:
                        sc.frame_set(f)
                        path = os.path.join(out, "%s_%s_%s_%04d.png" % (prefix, view, s.lower(), f))
                        tag = "%s/%s/f%04d" % (view, s, f)
                    rd.filepath = path
                    if mode == "opengl":
                        with bpy.context.temp_override(window=w, area=a, region=r, scene=sc):
                            bpy.ops.render.opengl(write_still=True, view_context=True)
                    else:
                        bpy.ops.render.render(write_still=True)
                    info = {**frame, "shading": s, "path": path,
                            "bytes": os.path.getsize(path) if os.path.exists(path) else 0}
                    if f is not None:
                        info["frame"] = f
                    if not info["bytes"]:
                        warnings.append("no file written for %s" % tag)
                    elif check:
                        info["check"] = framing_check(path)
                        ck = info["check"]
                        if ck.get("empty"):
                            warnings.append("%s: empty frame (target hidden, off-camera or clipped)" % tag)
                        elif (f is None and ck.get("center_offset")
                              and max(abs(x) for x in ck["center_offset"]) > 0.08):
                            warnings.append("%s: target off-centre by %s of frame" % (tag, ck["center_offset"]))
                    images.append(info)
                if mode != "opengl" and s == 'WIREFRAME':
                    for o, m in wire_mods:
                        o.modifiers.remove(m)
                    wire_mods = []
    finally:
        for o, m in wire_mods:
            o.modifiers.remove(m)
        for o, hid, hr in hidden:
            o.hide_set(hid)
            o.hide_render = hr
        saved.restore()
        if frame_list:
            sc.frame_set(frame0)
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cam_data)
    out_dict = {"mode": mode, "targets": [o.name for o in objs],
                "bbox": {"min": [round(v, 4) for v in lo], "max": [round(v, 4) for v in hi]},
                "images": images, "warnings": warnings, "restored": True}
    if frame_list:
        out_dict["frames"] = frame_list
        out_dict["frames_captured"] = len(frame_list)
        out_dict["files"] = [i["path"] for i in images if i["bytes"]]
    return out_dict


def _cli():
    import argparse
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="viewport_capture.py")
    p.add_argument("--out", required=True)
    p.add_argument("--targets", default="")
    p.add_argument("--collection", default="")
    p.add_argument("--views", default="front,right,back,left,top,persp")
    p.add_argument("--shading", default="SOLID")
    p.add_argument("--res", type=int, default=400)
    p.add_argument("--res-y", type=int, default=0)
    p.add_argument("--margin", type=float, default=1.12)
    p.add_argument("--persp-lens", type=float, default=50.0)
    p.add_argument("--isolate", action="store_true")
    p.add_argument("--matcap", action="store_true")
    p.add_argument("--transparent", action="store_true")
    p.add_argument("--prefix", default="cap")
    p.add_argument("--mode", default="auto", choices=["auto", "opengl", "workbench", "screen"])
    p.add_argument("--frames", default="", help="START:END[:STEP] -> one capture per frame (playblast)")
    a = p.parse_args(argv)
    try:
        out = capture(a.out, [t for t in a.targets.split(",") if t] or None, a.collection or None,
                      [v for v in a.views.split(",") if v], [s for s in a.shading.split(",") if s], a.res,
                      a.res_y or None, a.margin, a.persp_lens, a.isolate, a.matcap, a.prefix, a.mode,
                      transparent=a.transparent, frames=a.frames or None)
    except Exception as ex:
        out = {"error": "%s: %s" % (type(ex).__name__, ex)}
    print("VIEWPORT_CAPTURE " + json.dumps(out))


if "VIEWPORT_CAPTURE_OPTS" in globals():
    _o = dict(VIEWPORT_CAPTURE_OPTS)
    result = capture(_o.pop("out"), **_o)
elif __name__ == "__main__" and "--" in sys.argv:
    _cli()
else:
    result = {"defined": ["capture", "find_view3d", "resolve_targets", "world_bbox", "frame_camera", "framing_check",
                          "parse_frames"]}
