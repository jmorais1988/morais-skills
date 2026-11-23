"""Scripted Texture Paint in a LIVE Blender UI session (4.4+ brush assets; tested on 5.2): create/assign a paint image,
activate an Essentials texture brush, set colour / radius (metres or pixels) / strength, paint strokes along world-space
surface paths, fill, and SAVE the image. Every call returns measured pixel changes.

UI session only for strokes: paint.image_paint needs a VIEW_3D window/area/region (projection painting raycasts from the
view). Headless (`blender -b`) the stroke operator fails poll -> use fill()/numpy pixel edits or baking instead.
Image creation, fill, save and pixel statistics work headless.

Live (Blender:execute_blender_code or any bridge that execs code in the UI session): exec this file, then call:
    s = PaintSession(bpy.data.objects["Crate"], image="T_Crate_BaseColor", size=1024, base_color=(0.5, 0.5, 0.5, 1))
    s.brush("Paint Hard", radius=0.02, strength=1.0, color=(0.8, 0.1, 0.1))  # radius in metres (scene-locked)
    s.brush("Paint Soft", radius_px=30)                                         # or screen pixels (view-locked)
    s.stroke_surface([(0, -0.5, 0.2), (0.3, -0.5, 0.2)])    # snaps to surface, frames view, resamples dabs -> pixel stats
    s.fill((0.2, 0.2, 0.2, 1.0))                             # whole-image fill (numpy), returns changed pixel count
    s.save("//textures/T_Crate_BaseColor.png")               # UNSAVED PAINT IS LOST ON QUIT -> always save or pack
    s.close()                                                # object mode, restore view, unlink essentials libraries
Or set PAINT_OPS = {"object": "Crate", "image": "T_X", "size": 1024, "brush": "Paint Hard", "radius": 0.02,
    "color": [1, 0, 0], "paths": [[[x, y, z], ...]], "save": "C:/out/T_X.png"} before exec -> `result`.
Exec without PAINT_OPS only defines names and sets `result = {"defined": [...]}`.

Behaviour verified on 5.2 (GUI instance): each stroke element is one dab; projection uses the element's `mouse`
(region pixels), so the view must see the point -> strokes frame an orthographic view on the path. Hidden/back-facing
points are skipped when image_paint.use_occlude / use_backface_culling are on (defaults). Brush sizes are DIAMETERS in 5.x.
Paint mode 'IMAGE' (single canvas image, active UV map) is used by default so any image - including a Ucupaint layer
image - can be painted; mode='MATERIAL' paints the material's active paint slot instead.
Limitations: one object at a time; UDIM tiles and multiple UV maps not handled (canvas uses the active render UV map).
"""
import bpy, math, os
import numpy as np
from mathutils import Vector, geometry
from bpy_extras import view3d_utils

ESSENTIALS_TEXTURE = "brushes/essentials_brushes-mesh_texture.blend/Brush/"
BRUSHES = ["Paint Hard", "Paint Soft", "Paint Hard Pressure", "Paint Soft Pressure", "Paint Pixel Art", "Airbrush", "Blur",
           "Smear", "Clone", "Fill", "Mask", "Erase Hard", "Erase Soft", "Erase Hard Pressure", "Erase Pixel Art"]
_STROKE_KEYS = set(bpy.types.OperatorStrokeElement.bl_rna.properties.keys()) - {"rna_type"}


def find_view3d():
    wm = bpy.context.window_manager
    for w in (wm.windows if wm else []):
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                return w, a, next(r for r in a.regions if r.type == 'WINDOW')
    return None


def pixels(img):
    """(h, w, 4) float32 copy of an image's pixels (sRGB-encoded values for byte images)."""
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def pixel_diff(before, img, tol=0.5 / 255):
    """Changed-pixel count, UV bbox and centroid between a pixels() snapshot and the image now."""
    after = pixels(img)
    ch = np.any(np.abs(after - before) > tol, axis=2)
    n = int(ch.sum())
    out = {"changed_px": n, "image_px": int(ch.size)}
    if n:
        ys, xs = np.nonzero(ch)
        h, w = ch.shape
        out["uv_bbox"] = [round((xs.min() + 0.5) / w, 4), round((ys.min() + 0.5) / h, 4),
                          round((xs.max() + 0.5) / w, 4), round((ys.max() + 0.5) / h, 4)]
        out["uv_centroid"] = [round(float(xs.mean() + 0.5) / w, 4), round(float(ys.mean() + 0.5) / h, 4)]
        out["mean_rgba_changed"] = [round(float(v), 4) for v in after[ch].mean(axis=0)]
    return out


def dirty_images():
    """Images with unsaved pixel edits (painted or filled) - these are LOST when Blender quits unless saved/packed."""
    return [i.name for i in bpy.data.images if i.is_dirty]


def uv_at(obj, world_point, uv_name=None):
    """UV coordinate of the surface point closest to world_point (active UV map by default)."""
    me = obj.data
    me.calc_loop_triangles()
    uvl = me.uv_layers.get(uv_name) if uv_name else me.uv_layers.active
    if uvl is None:
        raise RuntimeError(f"{obj.name} has no UV map")
    p_local = obj.matrix_world.inverted() @ Vector(world_point)
    ok, loc, _, face = obj.closest_point_on_mesh(p_local)
    if not ok:
        return None
    best = None
    for t in me.loop_triangles:
        if t.polygon_index != face:
            continue
        v = [me.vertices[i].co for i in t.vertices]
        uv = [Vector((*uvl.uv[li].vector, 0.0)) for li in t.loops]
        bary = geometry.barycentric_transform(loc, v[0], v[1], v[2], uv[0], uv[1], uv[2])
        d = (geometry.closest_point_on_tri(loc, v[0], v[1], v[2]) - loc).length
        if best is None or d < best[0]:
            best = (d, (round(bary.x, 4), round(bary.y, 4)))
    return best[1] if best else None


def new_image(name, size=1024, color=(0.0, 0.0, 0.0, 1.0), alpha=True, float_buffer=False, non_color=False):
    """Create (or reuse) a generated image; size int or (w, h)."""
    w, h = (size, size) if isinstance(size, int) else size
    img = bpy.data.images.get(name)
    if img is None or tuple(img.size) != (w, h):
        img = bpy.data.images.new(name, w, h, alpha=alpha, float_buffer=float_buffer)
        img.generated_color = color
    if non_color:
        img.colorspace_settings.name = 'Non-Color'
    return img


def ensure_material_image(obj, img, socket="Base Color"):
    """Image Texture node for img wired into the first Principled BSDF `socket` of the active material (created if
    missing) and made the active node, so Material paint mode and renders use it. Returns the node name."""
    mat = obj.active_material
    if mat is None:
        mat = bpy.data.materials.new(f"MAT_{obj.name}")
        obj.data.materials.append(mat)
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.bl_idname == 'ShaderNodeBsdfPrincipled'), None)
    if bsdf is None:
        bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
        out = next((n for n in nt.nodes if n.bl_idname == 'ShaderNodeOutputMaterial'), None) or nt.nodes.new('ShaderNodeOutputMaterial')
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    node = next((n for n in nt.nodes if n.bl_idname == 'ShaderNodeTexImage' and n.image == img), None)
    if node is None:
        node = nt.nodes.new('ShaderNodeTexImage')
        node.image = img
        node.name = node.label = f"PAINT_{img.name}"
        node.location = (bsdf.location.x - 350, bsdf.location.y)
    if socket and bsdf.inputs.get(socket) is not None:
        nt.links.new(node.outputs["Color"], bsdf.inputs[socket])
    nt.nodes.active = node
    return node.name


def save_image(img, path, file_format='PNG'):
    """Write img to path (absolute or //relative) and make it a file-backed image. Returns existence + size."""
    ext = {'PNG': '.png', 'OPEN_EXR': '.exr', 'TARGA': '.tga', 'JPEG': '.jpg', 'TIFF': '.tif'}.get(file_format, '')
    if ext and not path.lower().endswith(ext):
        path += ext
    abspath = bpy.path.abspath(path)
    os.makedirs(os.path.dirname(abspath) or ".", exist_ok=True)
    was_dirty = img.is_dirty
    img.filepath_raw = path
    img.file_format = file_format
    img.save()
    return {"image": img.name, "path": abspath, "exists": os.path.exists(abspath),
            "bytes": os.path.getsize(abspath) if os.path.exists(abspath) else 0, "was_dirty": was_dirty, "dirty_now": img.is_dirty}


class PaintSession:
    def __init__(self, obj, image=None, size=1024, base_color=(0.8, 0.8, 0.8, 1.0), mode='IMAGE', link_socket="Base Color",
                 non_color=False, seam_bleed=None):
        if obj.type != 'MESH':
            raise TypeError(f"{obj.name} is {obj.type}; texture paint needs a MESH")
        if not obj.data.uv_layers:
            raise RuntimeError(f"{obj.name} has no UV map: unwrap first (uv-unwrapping.md) - painting needs non-overlapping UVs")
        v = find_view3d()
        if v is None:
            raise RuntimeError("no VIEW_3D area: paint strokes need a UI session with a 3D Viewport open")
        self.obj, (self.w, self.a, self.r) = obj, v
        self.rv3d = self.a.spaces.active.region_3d
        self._view = (self.rv3d.view_perspective, self.rv3d.view_rotation.copy(), self.rv3d.view_location.copy(), self.rv3d.view_distance)
        self._libs = {l.filepath for l in bpy.data.libraries}
        self.warnings = []
        if any(abs(s - 1.0) > 1e-6 for s in obj.scale):
            self.warnings.append(f"unapplied scale {tuple(round(s, 4) for s in obj.scale)}: metre radius and texel density are skewed")
        if isinstance(image, bpy.types.Image):
            self.image = image
        else:
            self.image = new_image(image or f"T_{obj.name}_BaseColor", size, base_color, non_color=non_color)
        self.node = ensure_material_image(obj, self.image, link_socket) if link_socket is not None else None
        vl = bpy.context.view_layer
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            with self.ctx(bpy.context.object):
                bpy.ops.object.mode_set(mode='OBJECT')
        for o in vl.objects:
            o.select_set(False)
        vl.objects.active = obj
        obj.select_set(True)
        ip = self.settings
        if mode == 'IMAGE':
            ip.mode, ip.canvas = 'IMAGE', self.image
        else:
            ip.mode = 'MATERIAL'
        if seam_bleed is not None:
            ip.seam_bleed = int(seam_bleed)
        self._mode('TEXTURE_PAINT')
        if mode != 'IMAGE':
            mat = obj.active_material
            imgs = list(mat.texture_paint_images)
            if self.image in imgs:
                mat.paint_active_slot = imgs.index(self.image)
            else:
                self.warnings.append("image is not a paint slot of the active material; painting the active slot instead")

    # ---- context ----
    def ctx(self, obj=None):
        o = obj or self.obj
        return bpy.context.temp_override(window=self.w, area=self.a, region=self.r, active_object=o, object=o,
                                         selected_objects=[o], selected_editable_objects=[o])

    @property
    def settings(self):
        return bpy.context.scene.tool_settings.image_paint

    def _mode(self, mode):
        if self.obj.mode != mode:
            with self.ctx():
                bpy.ops.object.mode_set(mode=mode)

    # ---- brush ----
    def brush(self, name=None, radius=None, radius_px=None, strength=None, color=None, blend=None):
        """Activate an Essentials texture brush (BRUSHES) and set its parameters. radius in metres (scene-locked) or
        radius_px in region pixels (view-locked); 5.x size fields are diameters. color is linear-ish UI RGB (0-1)."""
        self._mode('TEXTURE_PAINT')
        if name:
            with self.ctx():
                bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', asset_library_identifier="",
                                             relative_asset_identifier=ESSENTIALS_TEXTURE + name)
        b, ups = self.settings.brush, self.settings.unified_paint_settings
        if radius is not None:
            for h in (b, ups):
                h.use_locked_size = 'SCENE'
                h.unprojected_size = 2.0 * radius
        if radius_px is not None:
            for h in (b, ups):
                h.use_locked_size = 'VIEW'
                h.size = int(round(2 * radius_px))
        if strength is not None:
            b.strength = strength
            if ups.use_unified_strength:
                ups.strength = strength
        if color is not None:
            b.color = tuple(color[:3])
            if ups.use_unified_color:
                ups.color = tuple(color[:3])
        if blend is not None:
            b.blend = blend  # 'MIX', 'ADD', 'MUL', 'ERASE_ALPHA', 'ADD_ALPHA', ...
        return {"brush": b.name, "type": b.image_brush_type, "locked": b.use_locked_size, "diameter_m": round(b.unprojected_size, 5),
                "diameter_px": b.size, "strength": round(b.strength, 3), "color": [round(c, 3) for c in b.color], "blend": b.blend}

    def _radius_world(self, at=None):
        b, ups = self.settings.brush, self.settings.unified_paint_settings
        h = ups if ups.use_unified_size else b
        if h.use_locked_size == 'SCENE':
            return h.unprojected_size / 2.0
        at = Vector(at) if at is not None else self.rv3d.view_location
        right = self.rv3d.view_rotation @ Vector((1, 0, 0))
        p0, p1 = self.to_region(at), self.to_region(at + right)
        per_m = abs(p1.x - p0.x) if p0 and p1 else 1.0
        return (h.size / 2.0) / max(per_m, 1e-9)

    def _radius_px(self, at):
        """Brush radius in region pixels at world point `at` (what a stroke element's `size` carries)."""
        b, ups = self.settings.brush, self.settings.unified_paint_settings
        h = ups if ups.use_unified_size else b
        if h.use_locked_size != 'SCENE':
            return h.size / 2.0
        right = self.rv3d.view_rotation @ Vector((1, 0, 0))
        p0, p1 = self.to_region(Vector(at)), self.to_region(Vector(at) + right)
        return (h.unprojected_size / 2.0) * (abs(p1.x - p0.x) if p0 and p1 else 1.0)

    # ---- view ----
    def frame(self, point, normal, distance=None):
        """Orthographic view looking at world `point` against `normal`."""
        n = Vector(normal).normalized()
        self.rv3d.view_perspective = 'ORTHO'
        self.rv3d.view_rotation = (-n).to_track_quat('-Z', 'Y')
        self.rv3d.view_location = Vector(point)
        self.rv3d.view_distance = distance or max(self.obj.dimensions) * 1.2
        self.rv3d.update()

    def to_region(self, p):
        self.rv3d.update()
        return view3d_utils.location_3d_to_region_2d(self.r, self.rv3d, Vector(p))

    def _closest(self, p):
        mw = self.obj.matrix_world
        ok, loc, nrm, _ = self.obj.closest_point_on_mesh(mw.inverted() @ Vector(p))
        if not ok:
            raise RuntimeError("closest_point_on_mesh failed")
        return mw @ loc, (mw.to_3x3().inverted().transposed() @ nrm).normalized()

    # ---- strokes ----
    def stroke(self, points, pressure=1.0, frame=True, mode='NORMAL', distance=None, allow_off_surface=False):
        """Raw dabs at world points (should already be on the surface). Projection uses only each dab's region `mouse`
        position, so a point floating off the mesh would still paint whatever surface lies under it in the view:
        such dabs (farther than 0.25 radius from the surface) are skipped and counted unless allow_off_surface.
        Returns pixel stats."""
        self._mode('TEXTURE_PAINT')
        pts = [Vector(p) for p in points]
        if frame:
            _, n = self._closest(pts[len(pts) // 2])
            self.frame(pts[len(pts) // 2], n, distance)
        els, off, off_surface = [], 0, 0
        size_scale = getattr(self, "_size_scale", 1.0)
        for i, p in enumerate(pts):
            if not allow_off_surface and (self._closest(p)[0] - p).length > max(self._radius_world(p) * 0.25, 1e-5):
                off_surface += 1
                continue
            m = self.to_region(p)
            if m is None or not (0 <= m.x < self.r.width and 0 <= m.y < self.r.height):
                off += 1
                continue
            e = {"name": "", "location": tuple(p), "mouse": (m.x, m.y), "mouse_event": (m.x, m.y), "pressure": pressure,
                 "size": self._radius_px(p) * size_scale, "time": float(i), "is_start": not els, "x_tilt": 0.0, "y_tilt": 0.0}
            els.append({k: v for k, v in e.items() if k in _STROKE_KEYS})
        before = pixels(self.image)
        ret = set()
        if els:
            with self.ctx():
                ret = bpy.ops.paint.image_paint(stroke=els, mode=mode)
        out = {"ret": sorted(ret), "dabs": len(els), **pixel_diff(before, self.image)}
        if off:
            out["offscreen_dabs"] = off
        if off_surface:
            out["off_surface_dabs_skipped"] = off_surface
        if out["changed_px"] == 0:
            out["warning"] = ("no pixel changed: path off-surface/off-screen/occluded, strength or alpha 0, colour equals "
                              "existing pixels, or canvas image is not the one mapped on the active UV map")
        return out

    def stroke_surface(self, path, spacing=0.25, pressure=1.0, mode='NORMAL'):
        """Snap a world-space polyline to the surface and resample it every spacing*radius; also reports expected UVs."""
        pts = [Vector(p) for p in path]
        step = max(self._radius_world(pts[0]) * spacing, 1e-5)
        dense = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            k = max(1, int((b - a).length / step))
            dense += [a.lerp(b, (j + 1) / k) for j in range(k)]
        snapped = [self._closest(p)[0] for p in dense]
        span = max((snapped[-1] - snapped[0]).length, self._radius_world(snapped[0]) * 4)
        out = self.stroke(snapped, pressure=pressure, mode=mode, distance=span * 1.6)
        out["expected_uv_start_end"] = [uv_at(self.obj, snapped[0]), uv_at(self.obj, snapped[-1])]
        out["radius_m"] = round(self._radius_world(snapped[0]), 5)
        return out

    # ---- pixel ops ----
    def fill(self, color, uv_rect=None):
        """Fill the whole image (or uv_rect=(u0, v0, u1, v1)) with RGBA `color` via numpy. Values are written as stored
        (sRGB-encoded for byte sRGB images). Returns changed pixels."""
        before = pixels(self.image)
        arr = before.copy()
        h, w = arr.shape[:2]
        if uv_rect:
            x0, y0, x1, y1 = int(uv_rect[0] * w), int(uv_rect[1] * h), int(math.ceil(uv_rect[2] * w)), int(math.ceil(uv_rect[3] * h))
            arr[y0:y1, x0:x1] = color
        else:
            arr[:] = color
        self.image.pixels.foreach_set(arr.ravel())
        self.image.update()
        return pixel_diff(before, self.image)

    def save(self, path, file_format='PNG'):
        return save_image(self.image, path, file_format)

    def pack(self):
        self.image.pack()
        return {"image": self.image.name, "packed": self.image.packed_file is not None, "dirty_now": self.image.is_dirty}

    # ---- finish ----
    def close(self, restore_view=True, unlink_brushes=True):
        if self.obj.mode != 'OBJECT':
            with self.ctx():
                bpy.ops.object.mode_set(mode='OBJECT')
        if restore_view:
            self.rv3d.view_perspective, self.rv3d.view_rotation, self.rv3d.view_location, self.rv3d.view_distance = self._view
        removed = []
        if unlink_brushes:
            for l in list(bpy.data.libraries):
                if "essentials_brushes" in l.filepath and l.filepath not in self._libs:
                    removed.append(l.filepath.replace("\\", "/").rsplit("/", 1)[-1])
                    bpy.data.libraries.remove(l)
        out = {"unlinked_libraries": removed, "warnings": self.warnings, "unsaved_images": dirty_images()}
        if out["unsaved_images"]:
            out["warning"] = "unsaved painted images will be lost on quit: save() or pack() them"
        return out


def run(opts):
    obj = bpy.data.objects[opts["object"]]
    s = PaintSession(obj, image=opts.get("image"), size=opts.get("size", 1024), base_color=tuple(opts.get("base_color", (0.8, 0.8, 0.8, 1))))
    out = {"brush": s.brush(opts.get("brush", "Paint Hard"), radius=opts.get("radius"), radius_px=opts.get("radius_px"),
                            strength=opts.get("strength"), color=opts.get("color")), "strokes": []}
    for path in opts.get("paths", []):
        out["strokes"].append(s.stroke_surface(path))
    if opts.get("save"):
        out["save"] = s.save(opts["save"])
    out["close"] = s.close()
    return out


if "PAINT_OPS" in globals():
    result = run(globals()["PAINT_OPS"])
else:
    result = {"defined": ["PaintSession", "new_image", "ensure_material_image", "save_image", "pixels", "pixel_diff",
                          "dirty_images", "uv_at", "find_view3d", "BRUSHES", "run"]}
