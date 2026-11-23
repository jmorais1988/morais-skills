"""Scripted sculpting in a LIVE Blender UI session (brush assets 4.3+, stroke pen_flip as operator argument 4.4+; tested on 5.2): brush strokes along world-space
paths with a world-unit radius, procedural masks, filters, remesh/multires helpers, and brush-library cleanup.

UI session only. Sculpt operators need a VIEW_3D window/area/region context; run headless (`blender -b`) they fail
poll (brush_stroke, detail_flood_fill) or CRASH Blender (paint.mask_flood_fill, sculpt.mask_filter, mesh_filter,
face_sets_init). For headless procedural detail use bmesh/Displace/Geometry Nodes instead.

Live (Blender:execute_blender_code or any bridge that execs code in the UI session): exec this file, then call:
    s = SculptSession(bpy.data.objects["Rock"])          # enters Sculpt mode, remembers view + libraries
    s.brush("Clay Strips", radius=0.05, strength=0.6)      # essentials brush name (see BRUSHES), radius in metres
    s.stroke_surface([(0, -1, 0.2), (0.3, -0.95, 0.2)])  # snaps path to the surface, frames view, resamples dabs
    s.set_mask(lambda co: 1.0 if co.z > 0.5 else 0.0)    # world-space function -> .sculpt_mask (1 = protected)
    s.filter('SMOOTH', strength=0.5, iterations=3)        # sculpt.mesh_filter, respects the mask
    s.remesh(0.01)                                         # voxel remesh (keeps mask/face sets/colors)
    s.close()                                              # object mode, restore view, unlink essentials library
Every call returns a stats dict (max displacement, moved vertices, warnings). Exec only defines names and sets
`result = {"defined": [...]}`.

Behaviour verified on 5.2: each stroke element is one dab applied at its world `location` (mouse is not re-raycast unless
brush_stroke(override_location=True)), so hidden/back-facing points are sculpted too; points off the surface by more than
~a quarter radius are reported as `off_surface`. No spacing interpolation between elements -> stroke_surface resamples.
The view still matters for view-dependent options (Front Faces Only, pixel-locked size, gesture/trim pixel coords), so
strokes frame an orthographic view on the path. brush() always switches to scene-locked size (pixel size varies with
zoom). Multires displacement is only visible in the evaluated mesh in Object mode (evaluated_positions switches).
paint_mask_extract / face_set_extract make the new object active and leave Sculpt mode -> use extract_mask().
Every operator pushes an undo step.
"""
import bpy, math
from mathutils import Vector
from bpy_extras import view3d_utils

ESSENTIALS_SCULPT = "brushes/essentials_brushes-mesh_sculpt.blend/Brush/"
BRUSHES = ["Draw", "Draw Sharp", "Clay", "Clay Strips", "Clay Thumb", "Layer", "Inflate/Deflate", "Blob", "Crease Polish",
           "Crease Sharp", "Smooth", "Flatten/Contrast", "Fill/Deepen", "Scrape/Fill", "Plateau", "Trim", "Scrape Multiplane",
           "Pinch/Magnify", "Grab", "Grab 2D", "Grab Silhouette", "Elastic Grab", "Snake Hook", "Elastic Snake Hook", "Pull",
           "Thumb", "Pose", "Nudge", "Twist", "Relax Slide", "Relax Pinch", "Boundary", "Density", "Mask", "Face Set Paint",
           "Erase Multires Displacement", "Smear Multires Displacement"]
_STROKE_KEYS = set(bpy.types.OperatorStrokeElement.bl_rna.properties.keys()) - {"rna_type"}


def find_view3d():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                return w, a, next(r for r in a.regions if r.type == 'WINDOW')
    raise RuntimeError("no VIEW_3D area: sculpt operators need a UI session with a 3D Viewport open")


def positions(obj):
    """World-independent snapshot (object space) of vertex positions."""
    co = [0.0] * (len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get("co", co)
    return co


def displacement(before, obj, eps=1e-6):
    after = positions(obj)
    if len(after) != len(before):
        return {"topology_changed": True, "verts": len(after) // 3}
    mx, moved = 0.0, 0
    for i in range(0, len(after), 3):
        d = math.sqrt((after[i] - before[i]) ** 2 + (after[i + 1] - before[i + 1]) ** 2 + (after[i + 2] - before[i + 2]) ** 2)
        if d > eps:
            moved += 1
            mx = max(mx, d)
    return {"max": round(mx, 6), "moved": moved, "verts": len(after) // 3}


class SculptSession:
    def __init__(self, obj, symmetry=None):
        self.obj = obj
        self.w, self.a, self.r = find_view3d()
        self.rv3d = self.a.spaces.active.region_3d
        self._view = (self.rv3d.view_perspective, self.rv3d.view_rotation.copy(), self.rv3d.view_location.copy(), self.rv3d.view_distance)
        self._libs = {l.filepath for l in bpy.data.libraries}
        self.warnings = []
        if obj.type != 'MESH':
            raise TypeError(f"{obj.name} is {obj.type}; sculpt needs a MESH")
        if any(abs(s - obj.scale[0]) > 1e-6 for s in obj.scale) or abs(obj.scale[0] - 1) > 1e-6:
            self.warnings.append(f"unapplied scale {tuple(round(s, 4) for s in obj.scale)}: dabs stretch and voxel size is in local units; apply scale first")
        vl = bpy.context.view_layer
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            with self.ctx(bpy.context.object):
                bpy.ops.object.mode_set(mode='OBJECT')
        for o in vl.objects:
            o.select_set(False)
        vl.objects.active = obj
        obj.select_set(True)
        with self.ctx():
            bpy.ops.object.mode_set(mode='SCULPT')
        if symmetry is not None:  # e.g. "X", "XY", "" -- mirrors across the OBJECT ORIGIN's local axes
            self.set_symmetry(symmetry)

    def set_symmetry(self, axes):
        """Sculpt symmetry lives on the mesh (Mesh.use_mirror_x/y/z, shared with Edit mode); Sculpt.use_symmetry_* is
        not what strokes read. Returns the flags actually set."""
        me, out = self.obj.data, {}
        for ax in "xyz":
            on = ax.upper() in axes.upper()
            for holder, prop in ((me, f"use_mirror_{ax}"), (self.settings, f"use_symmetry_{ax}")):
                if hasattr(holder, prop):
                    setattr(holder, prop, on); out[f"{type(holder).__name__}.{prop}"] = on
        return out

    # ---- context ----
    def ctx(self, obj=None):
        o = obj or self.obj
        return bpy.context.temp_override(window=self.w, area=self.a, region=self.r, active_object=o, object=o,
                                         selected_objects=[o], selected_editable_objects=[o])

    @property
    def settings(self):
        return bpy.context.scene.tool_settings.sculpt

    def _mode(self, mode):
        if self.obj.mode != mode:
            with self.ctx():
                bpy.ops.object.mode_set(mode=mode)

    # ---- brush ----
    def brush(self, name, radius=None, strength=None, direction=None):
        """Activate an Essentials sculpt brush; radius in world metres (scene-locked, set on brush + unified settings)."""
        self._mode('SCULPT')
        with self.ctx():
            bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', asset_library_identifier="",
                                         relative_asset_identifier=ESSENTIALS_SCULPT + name)
        b = self.settings.brush
        ups = self.settings.unified_paint_settings
        if radius is not None:
            for h in (b, ups):
                h.use_locked_size = 'SCENE'
                h.unprojected_size = 2.0 * radius  # 5.0+: size fields are DIAMETERS
        if strength is not None:
            b.strength = strength
            if ups.use_unified_strength:
                ups.strength = strength
        if direction is not None and hasattr(b, "direction"):
            b.direction = direction  # 'ADD' / 'SUBTRACT' (or brush-specific enum items)
        return {"brush": b.name, "type": b.sculpt_brush_type, "radius": radius, "strength": b.strength}

    @property
    def radius(self):
        ups = self.settings.unified_paint_settings
        h = ups if ups.use_unified_size else self.settings.brush
        return h.unprojected_size / 2.0

    # ---- view ----
    def frame(self, point, normal, distance=None):
        """Orthographic view looking at world `point` against `normal`, so dabs raycast straight onto it."""
        n = Vector(normal).normalized()
        self.rv3d.view_perspective = 'ORTHO'
        self.rv3d.view_rotation = (-n).to_track_quat('-Z', 'Y')
        self.rv3d.view_location = Vector(point)
        self.rv3d.view_distance = distance or max(self.obj.dimensions) * 1.5
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

    def _off_surface(self, p):
        return (self._closest(p)[0] - Vector(p)).length > max(self.radius * 0.25, 1e-5)

    # ---- strokes ----
    def stroke(self, points, invert=False, pressure=1.0, frame=True):
        """Raw dabs at world points (already on the surface). Returns displacement stats."""
        self._mode('SCULPT')
        pts = [Vector(p) for p in points]
        if frame:
            _, n = self._closest(pts[len(pts) // 2])
            self.frame(pts[len(pts) // 2], n)
        els, off, offs = [], [], 0
        multires = any(m.type == 'MULTIRES' for m in self.obj.modifiers)
        for i, p in enumerate(pts):
            m = self.to_region(p)
            if m is None or not (0 <= m.x < self.r.width and 0 <= m.y < self.r.height):
                off.append(i)
                continue
            offs += (not multires) and self._off_surface(p)
            e = {"name": "", "location": tuple(p), "mouse": (m.x, m.y), "mouse_event": (m.x, m.y), "pressure": pressure,
                 "size": 1.0, "time": float(i), "is_start": not els, "x_tilt": 0.0, "y_tilt": 0.0}
            els.append({k: v for k, v in e.items() if k in _STROKE_KEYS})
        before = positions(self.obj)
        with self.ctx():
            ret = bpy.ops.sculpt.brush_stroke(stroke=els, mode='INVERT' if invert else 'NORMAL')
        out = {"ret": sorted(ret), "dabs": len(els), **displacement(before, self.obj)}
        if off:
            out["offscreen_dabs"] = len(off)
        if offs:
            out["off_surface"] = offs
        if multires:
            out["note"] = "multires: base vertices don't move; check evaluated_positions()"
        elif out.get("moved") == 0 and self.settings.brush.sculpt_brush_type not in ('MASK', 'DRAW_FACE_SETS'):
            out["warning"] = "no vertex moved: path off-surface/off-screen, radius smaller than edge length, or fully masked"
        return out

    def stroke_surface(self, path, spacing=0.35, invert=False, pressure=1.0):
        """Snap a world-space polyline to the surface and resample it at spacing*radius between dabs."""
        pts = [Vector(p) for p in path]
        step = max(self.radius * spacing, 1e-5)
        dense = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            k = max(1, int((b - a).length / step))
            dense += [a.lerp(b, (j + 1) / k) for j in range(k)]
        snapped = [self._closest(p)[0] for p in dense]
        return self.stroke(snapped, invert=invert, pressure=pressure)

    def grab(self, start, offset, steps=8):
        """Grab-type brushes: drag from surface point `start` by world `offset` (component along the view axis is lost)."""
        s, n = self._closest(start)
        self.frame(s, n)
        return self.stroke([s + Vector(offset) * (i / steps) for i in range(steps + 1)], frame=False)

    # ---- masks / face sets ----
    def set_mask(self, fn):
        """Write .sculpt_mask from fn(world_co) -> 0..1 (1 = protected from brushes/filters)."""
        self._mode('OBJECT')
        me, mw = self.obj.data, self.obj.matrix_world
        a = me.attributes.get(".sculpt_mask") or me.attributes.new(".sculpt_mask", 'FLOAT', 'POINT')
        vals = [max(0.0, min(1.0, float(fn(mw @ v.co)))) for v in me.vertices]
        a.data.foreach_set("value", vals)
        self._mode('SCULPT')
        return {"masked": sum(1 for x in vals if x > 0.5), "verts": len(vals)}

    def mask_op(self, op, **kw):
        """e.g. mask_op('INVERT'), mask_op('CLEAR'), mask_op('GROW', iterations=2), mask_op('CAVITY', factor=0.5)."""
        self._mode('SCULPT')
        with self.ctx():
            if op == 'INVERT':
                return sorted(bpy.ops.paint.mask_flood_fill(mode='INVERT'))
            if op == 'CLEAR':
                return sorted(bpy.ops.paint.mask_flood_fill(mode='VALUE', value=0.0))
            if op == 'CAVITY':
                return sorted(bpy.ops.sculpt.mask_from_cavity(**kw))
            return sorted(bpy.ops.sculpt.mask_filter(filter_type=op, **kw))

    def face_sets(self, mode='LOOSE_PARTS', threshold=0.5):
        self._mode('SCULPT')
        with self.ctx():
            return sorted(bpy.ops.sculpt.face_sets_init(mode=mode, threshold=threshold))

    # ---- filters / topology ----
    def filter(self, type='SMOOTH', strength=0.5, iterations=1, **kw):
        """sculpt.mesh_filter: SMOOTH SCALE INFLATE SPHERE RANDOM RELAX RELAX_FACE_SETS SURFACE_SMOOTH SHARPEN ENHANCE_DETAILS ERASE_DISPLACEMENT."""
        self._mode('SCULPT')
        before = positions(self.obj)
        with self.ctx():
            ret = bpy.ops.sculpt.mesh_filter(type=type, strength=strength, iteration_count=iterations, **kw)
        return {"ret": sorted(ret), **displacement(before, self.obj)}

    def remesh(self, voxel_size, adaptivity=0.0, fix_poles=True, preserve_volume=True, preserve_attributes=True, max_verts=3_000_000):
        me = self.obj.data
        est = 1.35 * sum(f.area for f in me.polygons) * max(self.obj.scale) ** 2 / (voxel_size ** 2)  # ~verts, measured factor
        if est > max_verts:
            return {"skipped": f"~{int(est)} verts estimated > max_verts={max_verts}; raise voxel_size"}
        me.remesh_voxel_size, me.remesh_voxel_adaptivity = voxel_size, adaptivity
        me.use_remesh_fix_poles, me.use_remesh_preserve_volume, me.use_remesh_preserve_attributes = fix_poles, preserve_volume, preserve_attributes
        v0 = len(me.vertices)
        with self.ctx():
            ret = bpy.ops.object.voxel_remesh()
        return {"ret": sorted(ret), "verts_before": v0, "verts": len(self.obj.data.vertices), "estimate": int(est)}

    def dyntopo_flood(self, resolution):
        """Constant-detail dyntopo flood fill (resolution = detail per metre), then dyntopo off again."""
        self._mode('SCULPT')
        s = self.settings
        with self.ctx():
            if not self.obj.use_dynamic_topology_sculpting:
                bpy.ops.sculpt.dynamic_topology_toggle()
            s.detail_type_method, s.constant_detail_resolution = 'CONSTANT', resolution
            bpy.ops.sculpt.detail_flood_fill()
            bpy.ops.sculpt.dynamic_topology_toggle()
        self._mode('OBJECT'); self._mode('SCULPT')
        return {"verts": len(self.obj.data.vertices)}

    def multires(self, levels=2, mode='CATMULL_CLARK'):
        self._mode('OBJECT')
        m = self.obj.modifiers.get("Multires") or self.obj.modifiers.new("Multires", 'MULTIRES')
        with self.ctx():
            for _ in range(levels):
                bpy.ops.object.multires_subdivide(modifier=m.name, mode=mode)
        self._mode('SCULPT')
        return {"levels": m.levels, "sculpt_levels": m.sculpt_levels, "total_levels": m.total_levels}

    def evaluated_positions(self):
        """Evaluated (modifier/multires) positions; switches to Object mode to read them, then back."""
        mode = self.obj.mode
        self._mode('OBJECT')
        dg = bpy.context.evaluated_depsgraph_get(); dg.update()
        ev = self.obj.evaluated_get(dg)
        out = [v.co.copy() for v in ev.data.vertices]
        self._mode(mode)
        return out

    def trim_box(self, center, normal, half_size, mode='DIFFERENCE', solver='MANIFOLD', front_faces_only=False):
        """Box trim through the mesh, centred on world `center`, looking against `normal`; half_size in metres."""
        self._mode('SCULPT')
        self.frame(center, normal)
        c = self.to_region(center)
        right = self.rv3d.view_rotation @ Vector((1, 0, 0))
        px = abs(self.to_region(Vector(center) + right * half_size).x - c.x)
        f0 = len(self.obj.data.polygons)
        with self.ctx():
            ret = bpy.ops.sculpt.trim_box_gesture(xmin=int(c.x - px), xmax=int(c.x + px), ymin=int(c.y - px), ymax=int(c.y + px),
                                                  wait_for_input=False, trim_mode=mode, trim_solver=solver,
                                                  use_front_faces_only=front_faces_only)
        return {"ret": sorted(ret), "faces_before": f0, "faces": len(self.obj.data.polygons)}

    def extract_mask(self, threshold=0.5, thickness=None, smooth_iterations=4, add_boundary_loop=True):
        """Masked region -> new shell object (Solidify modifier). Restores Sculpt mode on the source object."""
        self._mode('SCULPT')
        names0 = set(bpy.data.objects.keys())
        with self.ctx():
            ret = bpy.ops.sculpt.paint_mask_extract(mask_threshold=threshold, add_boundary_loop=add_boundary_loop,
                                                    smooth_iterations=smooth_iterations, apply_shrinkwrap=True,
                                                    add_solidify=thickness is not None)
        new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in names0]
        for o in new:
            sol = next((m for m in o.modifiers if m.type == 'SOLIDIFY'), None)
            if sol and thickness is not None:
                sol.thickness = thickness
        vl = bpy.context.view_layer
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            with self.ctx(bpy.context.object):
                bpy.ops.object.mode_set(mode='OBJECT')
        for o in vl.objects:
            o.select_set(False)
        vl.objects.active = self.obj; self.obj.select_set(True)
        self._mode('SCULPT')
        return {"ret": sorted(ret), "new_objects": [o.name for o in new],
                "faces": [len(o.data.polygons) for o in new]}

    # ---- finish ----
    def close(self, restore_view=True, unlink_brushes=True):
        if self.obj.mode != 'OBJECT':
            with self.ctx():
                bpy.ops.object.mode_set(mode='OBJECT')
        if restore_view:
            self.rv3d.view_perspective, self.rv3d.view_rotation, self.rv3d.view_location, self.rv3d.view_distance = self._view
        removed = []
        if unlink_brushes:  # activated essentials brushes are linked into the file; drop libraries this session added
            for l in list(bpy.data.libraries):
                if "essentials_brushes" in l.filepath and l.filepath not in self._libs:
                    removed.append(l.filepath.replace("\\", "/").rsplit("/", 1)[-1])
                    bpy.data.libraries.remove(l)
        return {"unlinked_libraries": removed, "warnings": self.warnings}


result ={"defined": ["SculptSession", "find_view3d", "positions", "displacement", "BRUSHES"]}
