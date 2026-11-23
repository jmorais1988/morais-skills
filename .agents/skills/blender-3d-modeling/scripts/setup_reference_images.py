"""Load orthographic reference images into Blender as aligned image empties sized to the subject's real height.

Headless / CLI (prints one line: SETUP_REFERENCE_IMAGES <json>):
    blender -b [scene.blend] --python setup_reference_images.py -- --image front=/refs/front.jpg --image side=/refs/side.jpg
        [--height-m 1.8] [--collection REF] [--opacity 0.5] [--offset-m 0] [--side-is-left] [--save out.blend]
Live (Blender:execute_blender_code): set `REF_CONFIG` before exec -> `result` dict:
    REF_CONFIG = {
        "height_m": 1.8,                       # real-world height of the subject (image will be scaled so it matches)
        "collection": "REF",
        "opacity": 0.5,
        "images": {"front": "/abs/front.jpg", "back": "...", "side": "...", "top": "..."},   # any subset
        "offset_m": 0.0,                       # push planes behind the origin so the model isn't hidden by them
        "side_is_left": False,                 # side image shows the left side (looking along +X)
    }
Exec without REF_CONFIG (and without CLI args) only defines setup_references(cfg) and sets result = {"defined": [...]}.

Views: front seen from -Y (Numpad 1), back from +Y, side from +X (Numpad 3), top from +Z (Numpad 7).
The empties display only in orthographic views (`show_empty_image_perspective=False`) and are excluded from renders.
Re-running replaces the REF_<view> empties (idempotent). Height alignment assumes the subject fills the image height
(for top: the image's larger dimension); adjust `empty_display_size` / `empty_image_offset` afterwards if padded.
"""
import bpy, math, os, sys, json

DEFAULTS = {"height_m": 1.8, "collection": "REF", "opacity": 0.5, "images": {}, "offset_m": 0.0, "side_is_left": False}
VIEWS = ("front", "back", "side", "top")
ROTATIONS = {  # euler XYZ so the image faces the numpad view that shows it correctly
    "front": (math.radians(90), 0, 0),
    "back": (math.radians(90), 0, math.radians(180)),
    "side": (math.radians(90), 0, math.radians(90)),
    "side_left": (math.radians(90), 0, math.radians(-90)),
    "top": (0, 0, 0),
}


def get_collection(name):
    col = bpy.data.collections.get(name)
    if not col:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    col.hide_render = True
    return col


def add_ref(view, path, cfg, col):
    img = bpy.data.images.load(path, check_existing=True)
    w, h = img.size
    if not w or not h:
        return None, f"{view}: image has zero size ({path})"
    key = "side_left" if (view == "side" and cfg.get("side_is_left")) else view
    name = f"REF_{view}"
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    e = bpy.data.objects.new(name, None)
    col.objects.link(e)
    e.empty_display_type = 'IMAGE'
    e.data = img
    height = float(cfg["height_m"])
    e.empty_display_size = height if h >= w else height * (w / h)   # size = image's larger dimension in world units
    e.empty_image_offset = (-0.5, -0.5) if view == "top" else (-0.5, 0.0)   # bottom edge on the ground
    e.rotation_euler = ROTATIONS[key]
    off = float(cfg.get("offset_m", 0.0))
    e.location = {"front": (0, off, 0), "back": (0, -off, 0), "top": (0, 0, -off),
                  "side": ((-off if cfg.get("side_is_left") else off), 0, 0)}[view]
    e.show_empty_image_perspective = False
    e.show_empty_image_orthographic = True
    e.show_in_front = False
    e.use_empty_image_alpha = True
    e.color[3] = cfg.get("opacity", 0.5)
    e.hide_render = True
    return e, None


def setup_references(cfg=None):
    c = dict(DEFAULTS); c.update(cfg or {})
    col = get_collection(c["collection"])
    created, warnings, info = [], [], {}
    for view, path in (c.get("images") or {}).items():
        if view not in VIEWS:
            warnings.append(f"unknown view {view!r} (use {VIEWS})"); continue
        if not path or not os.path.isfile(bpy.path.abspath(path)):
            warnings.append(f"{view}: file not found {path!r}"); continue
        try:
            e, err = add_ref(view, path, c, col)
        except RuntimeError as ex:
            warnings.append(f"{view}: cannot load {path!r}: {ex}"); continue
        if err:
            warnings.append(err); continue
        created.append(e.name)
        info[e.name] = {"image_px": list(e.data.size), "display_size_m": round(e.empty_display_size, 4),
                        "location": [round(v, 4) for v in e.location]}
    return {"created": created, "collection": c["collection"], "height_m": c["height_m"], "empties": info,
            "warnings": warnings,
            "hint": "Use numpad 1/3/7 (ortho) to model over them; tweak empty_image_offset if the subject is padded."}


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="setup_reference_images.py")
    p.add_argument("--image", action="append", default=[], help="view=path (front|back|side|top), repeatable")
    p.add_argument("--height-m", type=float, default=1.8); p.add_argument("--collection", default="REF")
    p.add_argument("--opacity", type=float, default=0.5); p.add_argument("--offset-m", type=float, default=0.0)
    p.add_argument("--side-is-left", action="store_true"); p.add_argument("--save")
    a = p.parse_args(argv)
    images = dict(s.split("=", 1) for s in a.image)
    res = setup_references({"height_m": a.height_m, "collection": a.collection, "opacity": a.opacity, "images": images,
                            "offset_m": a.offset_m, "side_is_left": a.side_is_left})
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save)); res["saved"] = os.path.abspath(a.save)
    return res


_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if globals().get("REF_CONFIG") is not None:
    result = setup_references(REF_CONFIG)
    print("SETUP_REFERENCE_IMAGES " + json.dumps(result))
elif __name__ == "__main__" and "--image" in _argv:
    result = _cli(_argv)
    print("SETUP_REFERENCE_IMAGES " + json.dumps(result))
else:
    result = {"defined": ["setup_references", "add_ref", "get_collection"]}
