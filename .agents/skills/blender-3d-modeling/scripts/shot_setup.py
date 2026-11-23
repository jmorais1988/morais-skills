"""Product / studio shot setup: cameras fitted to a target's evaluated world-space geometry (3/4 hero perspective, true
isometric or 2:1 dimetric orthographic, front/side/top/back orthographic), a projected-frame margin check, a studio rig
(key / fill / rim area lights aimed at the target, optional reflection cards, curved cyc backdrop or shadow catcher), and a
loop-safe turntable (object or camera orbit, N frames, linear, no duplicate end frame).

Headless / CLI (prints one line: SHOT_SETUP <json>):
    blender -b scene.blend --python shot_setup.py -- --target Bottle[,Cap] [--hero --lens 100 --azimuth 35 --elevation 12 --fstop 5.6]
        [--iso true|dimetric] [--ortho FRONT|BACK|SIDE|LEFT|TOP] [--margin 0.08] [--resolution 1600x1200]
        [--rig [--shadow-catcher] [--no-backdrop] [--cards 2]]
        [--turntable 72 --turntable-mode object|camera --turntable-margin 0.02] [--check CAM_Hero] [--save out.blend]
    --fstop enables depth of field on the hero camera (focus at the target centre). --turntable-margin M samples ~24
    frames of the turn through the hero camera (falls back to the scene camera) and reports worst_margin_over_turn and
    margin_pass (worst >= M) in the turntable dict -- silhouettes change while the target spins.
Live (Blender:execute_blender_code): set before exec
    SHOT_OPTS = {"target": ["Bottle"], "hero": {"lens": 100}, "iso": "true", "ortho": "FRONT", "rig": {"shadow_catcher": False},
                 "turntable": {"frames": 72, "mode": "object", "margin_check": 0.02}, "check": "CAM_Hero", "margin": 0.08}
    -> `result` dict
Without SHOT_OPTS the file only defines functions (result = {"defined": [...]}).

Conventions: azimuth 0 = camera on the target's -Y side looking +Y ("front"), positive azimuth orbits toward +X
(camera moves to the right of the front view); elevation in degrees above the horizontal through the bbox centre.
Names: CAM_Hero / CAM_Iso / CAM_Front..., LGT_Key / LGT_Fill / LGT_Rim / LGT_Card_<n>, BG_Backdrop / BG_ShadowCatcher,
TT_Pivot; the rig lives in collection STUDIO. Every function is idempotent (re-running updates the same objects).
Limitations: fitting uses evaluated mesh vertices (curves/text/volumes fall back to their bounding box corners); light
power is an on-axis far-field estimate (probe exposure with archviz_setup.exposure_probe); the backdrop is oriented to the
hero camera azimuth; shadow catchers are Cycles-only. Pure bpy + mathutils + numpy.
"""
import bpy, math, json, sys
from mathutils import Vector, Matrix, Euler

ISO_TILT_DEG = math.degrees(math.atan(math.sqrt(2)))        # 54.7356 deg camera X rotation -> 35.2644 deg elevation
DIMETRIC_TILT_DEG = 60.0                                     # 2:1 pixel-art "isometric": 30 deg elevation, 26.565 deg lines


def area_light_power(irradiance, size_x, size_y, distance):
    """Watts for a rectangular Blender area light (spread 180) so a surface facing it on-axis at `distance` receives
    `irradiance` in Sun-strength units (white diffuse -> linear pixel value = irradiance). Exact near field: the point-to-
    rectangle form factor F (four corner rectangles); P = E * pi * area / F. Far field reduces to E * pi^2 * d^2.
    Measured in 5.2 Cycles: value/E = 1.000 for size/d = 0.05, 0.5 and 2 (see references/rendering-and-lighting.md)."""
    a, b, d = size_x / 2.0, size_y / 2.0, max(1e-9, distance)
    A, B = a / d, b / d
    f = (A / math.sqrt(1 + A * A) * math.atan(B / math.sqrt(1 + A * A)) +
         B / math.sqrt(1 + B * B) * math.atan(A / math.sqrt(1 + B * B))) / (2 * math.pi)
    return irradiance * math.pi * (size_x * size_y) / max(1e-12, 4 * f)


# ----------------------------------------------------------------------------------------------------------- geometry
def _targets(target):
    names = target.split(",") if isinstance(target, str) else list(target)
    objs = [bpy.data.objects[n] if isinstance(n, str) else n for n in names]
    if not objs:
        raise ValueError("no target objects")
    return objs


def target_points(target, max_points=20000):
    """World-space points of the evaluated targets (mesh vertices; bbox corners for other types). Includes children."""
    import numpy as np
    dg = bpy.context.evaluated_depsgraph_get(); pts = []
    seen = set(); stack = list(_targets(target))
    while stack:
        o = stack.pop()
        if o.name in seen:
            continue
        seen.add(o.name); stack.extend(o.children)
        ev = o.evaluated_get(dg); mw = np.array(ev.matrix_world)
        local = None
        if o.type == 'MESH':
            me = ev.to_mesh()
            if len(me.vertices):
                local = np.empty(len(me.vertices) * 3, dtype=np.float64); me.vertices.foreach_get("co", local)
                local = local.reshape(-1, 3)
            ev.to_mesh_clear()
        if local is None and o.type not in ('EMPTY', 'LIGHT', 'CAMERA'):
            local = np.array([tuple(c) for c in ev.bound_box], dtype=np.float64)
        if local is None:
            continue
        if len(local) > max_points:
            local = local[np.linspace(0, len(local) - 1, max_points).astype(int)]
        pts.append(local @ mw[:3, :3].T + mw[:3, 3])
    if not pts:
        raise ValueError("targets have no geometry")
    return np.concatenate(pts)


def world_bbox(target):
    p = target_points(target)
    lo, hi = p.min(0), p.max(0)
    return {"min": [float(v) for v in lo], "max": [float(v) for v in hi], "center": [float(v) for v in (lo + hi) / 2],
            "size": [float(v) for v in hi - lo], "diagonal": float(((hi - lo) ** 2).sum() ** 0.5)}


def _frame_aspect(scene):
    r = scene.render
    return (r.resolution_x * r.pixel_aspect_x) / max(1e-9, r.resolution_y * r.pixel_aspect_y)


def project_points(scene, cam, pts):
    """Camera-view coordinates of world points: x, y in frame units (0..1 inside the rendered frame, shift and ortho
    included, matching world_to_camera_view) and depth z (distance along the view axis; <= 0 = behind the camera)."""
    import numpy as np
    from bpy_extras.object_utils import world_to_camera_view
    cd = cam.data; mwi = np.array(cam.matrix_world.inverted())
    loc = pts @ mwi[:3, :3].T + mwi[:3, 3]                          # camera space, looking -Z
    frame = [v for v in cd.view_frame(scene=scene)]                   # camera-space frame corners (z = -1 plane for persp)
    xs = [v.x for v in frame]; ys = [v.y for v in frame]; fz = -frame[0].z
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    depth = -loc[:, 2]
    if cd.type == 'ORTHO':
        u, v = loc[:, 0], loc[:, 1]
    else:
        with np.errstate(divide='ignore', invalid='ignore'):
            u = loc[:, 0] / depth * fz; v = loc[:, 1] / depth * fz
    x = (u - xmin) / (xmax - xmin); y = (v - ymin) / (ymax - ymin)
    if len(pts):  # consistency with bpy_extras on one point (cheap guard against convention drift)
        ref = world_to_camera_view(scene, cam, Vector(pts[0]))
        if depth[0] > 0 and (abs(ref.x - x[0]) > 1e-4 or abs(ref.y - y[0]) > 1e-4):
            raise RuntimeError("projection mismatch vs world_to_camera_view")
    return x, y, depth


def frame_margins(camera, target, margin=0.05, scene=None, pts=None):
    """Projected target bounds inside the camera frame. Margins are fractions of frame width (left/right) and height
    (bottom/top); negative = cropped. pass = every margin >= `margin` and nothing behind the camera."""
    sc = scene or bpy.context.scene; cam = bpy.data.objects[camera] if isinstance(camera, str) else camera
    bpy.context.view_layer.update()
    p = target_points(target) if pts is None else pts
    x, y, z = project_points(sc, cam, p)
    behind = int((z <= cam.data.clip_start).sum()); beyond = int((z >= cam.data.clip_end).sum())
    m = {"left": float(x.min()), "right": float(1 - x.max()), "bottom": float(y.min()), "top": float(1 - y.max())}
    fill = {"width": float(x.max() - x.min()), "height": float(y.max() - y.min())}
    ok = behind == 0 and beyond == 0 and min(m.values()) >= margin - 1e-6
    return {"camera": cam.name, "pass": bool(ok), "margins": {k: round(v, 4) for k, v in m.items()}, "min_margin": round(min(m.values()), 4),
            "fill": {k: round(v, 4) for k, v in fill.items()}, "required_margin": margin, "points": int(len(p)),
            "behind_or_clipped_near": behind, "clipped_far": beyond}


# ------------------------------------------------------------------------------------------------------------ cameras
def _get_camera(name, scene):
    cam = bpy.data.objects.get(name)
    if cam is None or cam.type != 'CAMERA':
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name)); scene.collection.objects.link(cam)
    return cam


def _dir_from_angles(azimuth, elevation):
    a, e = math.radians(azimuth), math.radians(elevation)
    return Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))  # from target toward camera


def hero_camera(target, name="CAM_Hero", lens=100.0, azimuth=35.0, elevation=12.0, margin=0.08, resolution=None,
                sensor=36.0, dof_fstop=None, center="shift", pts=None, set_active=True):
    """Perspective 3/4 product camera. Distance is solved (bisection) so the projected target fills the frame up to
    `margin` on the tighter axis; centring by lens shift (keeps the chosen perspective) or by re-aiming (`center='aim'`).
    Product lenses: 85-135 mm (36 mm sensor) flatten proportions like catalogue photography; 50 mm looks 'closer'."""
    import numpy as np
    sc = bpy.context.scene
    if resolution: sc.render.resolution_x, sc.render.resolution_y = resolution
    p = target_points(target) if pts is None else pts
    lo, hi = p.min(0), p.max(0); c = Vector(((lo + hi) / 2).tolist()); diag = float(np.linalg.norm(hi - lo))
    cam = _get_camera(name, sc); cd = cam.data
    cd.type, cd.lens, cd.sensor_fit, cd.sensor_width, cd.shift_x, cd.shift_y = 'PERSP', lens, 'AUTO', sensor, 0.0, 0.0
    fwd = _dir_from_angles(azimuth, elevation)
    rot = (-fwd).to_track_quat('-Z', 'Y').to_euler()

    def place(dist):
        cam.location = c + fwd * dist; cam.rotation_euler = rot; bpy.context.view_layer.update()
        x, y, z = project_points(sc, cam, p)
        if (z <= 1e-6).any():
            return None
        return x, y

    def fits(dist):
        r = place(dist)
        return r is not None and np.ptp(r[0]) <= 1 - 2 * margin and np.ptp(r[1]) <= 1 - 2 * margin

    lo_d, hi_d = diag * 0.05, diag * 2.0
    while not fits(hi_d):
        hi_d *= 1.6
        if hi_d > diag * 1e4: raise RuntimeError("could not fit target")
    for _ in range(50):  # bisection: smallest distance that still fits
        mid = 0.5 * (lo_d + hi_d)
        if fits(mid): hi_d = mid
        else: lo_d = mid
    x, y = place(hi_d)
    if center == "aim":  # re-aim at the projected centre (small offsets; margins then approximately symmetric)
        for _ in range(4):
            cx, cy = (x.min() + x.max()) / 2, (y.min() + y.max()) / 2
            frame = cd.view_frame(scene=sc); fx = max(v.x for v in frame) - min(v.x for v in frame); fy = max(v.y for v in frame) - min(v.y for v in frame)
            d_world = cam.matrix_world.to_3x3() @ Vector(((cx - 0.5) * fx, (cy - 0.5) * fy, frame[0].z))
            cam.rotation_euler = d_world.normalized().to_track_quat('-Z', 'Y').to_euler(); bpy.context.view_layer.update()
            x, y, _ = project_points(sc, cam, p)
    else:  # shift is in units of the larger sensor dimension (sensor_fit AUTO)
        asp = _frame_aspect(sc); cx, cy = (x.min() + x.max()) / 2, (y.min() + y.max()) / 2
        cd.shift_x = (cx - 0.5) * (1.0 if asp >= 1 else asp)
        cd.shift_y = (cy - 0.5) * (1.0 / asp if asp >= 1 else 1.0)
    cd.clip_start = max(0.001, hi_d - diag) * 0.5 if hi_d > diag else max(0.001, hi_d * 0.02)
    cd.clip_end = hi_d + diag * 10
    if dof_fstop:
        cd.dof.use_dof = True; cd.dof.aperture_fstop = dof_fstop; cd.dof.focus_object = None
        cd.dof.focus_distance = float((c - cam.location).dot(-fwd))
    if set_active: sc.camera = cam
    check = frame_margins(cam, target, margin * 0.999, pts=p)
    return {"camera": cam.name, "lens": lens, "distance": round(hi_d, 4), "azimuth": azimuth, "elevation": elevation,
            "shift": [round(cd.shift_x, 4), round(cd.shift_y, 4)], "check": check}


def ortho_camera(target, view="FRONT", name=None, margin=0.05, resolution=None, set_active=False, pts=None, iso=None):
    """Orthographic camera fitted to the target. view FRONT (-Y looking +Y), BACK, SIDE (+X looking -X), LEFT, TOP.
    iso='true' -> true isometric (X rot 54.7356, Z rot 45: the three world axes project with equal length, 120 deg apart);
    iso='dimetric' -> 2:1 game dimetric (X rot 60, Z rot 45: ground lines at atan(1/2) = 26.565 deg)."""
    import numpy as np
    sc = bpy.context.scene
    if resolution: sc.render.resolution_x, sc.render.resolution_y = resolution
    rots = {"FRONT": (90, 0, 0), "BACK": (90, 0, 180), "SIDE": (90, 0, 90), "RIGHT": (90, 0, 90), "LEFT": (90, 0, -90),
            "TOP": (0, 0, 0)}
    if iso:
        tilt = ISO_TILT_DEG if iso in (True, "true", "iso", "isometric") else DIMETRIC_TILT_DEG
        rot_deg = (tilt, 0.0, 45.0); name = name or ("CAM_Iso" if tilt == ISO_TILT_DEG else "CAM_Dimetric")
    else:
        rot_deg = rots[view.upper()]; name = name or f"CAM_{view.title()}"
    p = target_points(target) if pts is None else pts
    cam = _get_camera(name, sc); cd = cam.data
    cd.type, cd.sensor_fit, cd.shift_x, cd.shift_y = 'ORTHO', 'AUTO', 0.0, 0.0
    cam.rotation_euler = Euler([math.radians(a) for a in rot_deg]); R = np.array(cam.rotation_euler.to_matrix())
    right, up, back = R[:, 0], R[:, 1], R[:, 2]
    u, v, w = p @ right, p @ up, p @ back
    asp = _frame_aspect(sc); width, height = np.ptp(u) / (1 - 2 * margin), np.ptp(v) / (1 - 2 * margin)
    cd.ortho_scale = float(max(width, height * asp) if asp >= 1 else max(width / asp, height))
    diag = float(np.linalg.norm(p.max(0) - p.min(0)))
    centre = right * (u.min() + u.max()) / 2 + up * (v.min() + v.max()) / 2 + back * (w.max() + diag)
    cam.location = Vector(centre.tolist()); cd.clip_start = 0.001 * max(diag, 1e-3); cd.clip_end = float(np.ptp(w) + 3 * diag)
    if set_active: sc.camera = cam
    bpy.context.view_layer.update()
    res = {"camera": cam.name, "rotation_deg": [round(a, 4) for a in rot_deg], "ortho_scale": round(cd.ortho_scale, 4),
           "check": frame_margins(cam, target, margin * 0.999, pts=p)}
    if iso:
        res["axes_on_screen"] = axis_projection(cam)
    return res


def axis_projection(cam):
    """Screen-space length and angle (deg from screen +X) of the world X, Y, Z unit axes -- proves iso/dimetric angles."""
    R = cam.matrix_world.to_3x3().normalized(); out = {}
    for n, ax in (("X", Vector((1, 0, 0))), ("Y", Vector((0, 1, 0))), ("Z", Vector((0, 0, 1)))):
        sx, sy = ax.dot(R.col[0]), ax.dot(R.col[1])
        out[n] = {"length": round(math.hypot(sx, sy), 6), "angle_deg": round(math.degrees(math.atan2(sy, sx)), 4)}
    fwd = -R.col[2]; out["view_elevation_deg"] = round(math.degrees(math.asin(-fwd.z)), 4)
    return out


# --------------------------------------------------------------------------------------------------------- studio rig
def _collection(name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name); bpy.context.scene.collection.children.link(col)
    return col


def _link(obj, col):
    for c in list(obj.users_collection):
        if c != col: c.objects.unlink(obj)
    if obj.name not in col.objects: col.objects.link(obj)


def _area_light(name, col, loc, aim, size, size_y, power, spread_deg=180.0, color=(1, 1, 1)):
    o = bpy.data.objects.get(name)
    if o is None or o.type != 'LIGHT':
        o = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA'))
    _link(o, col); L = o.data; L.type = 'AREA'
    L.shape = 'RECTANGLE'; L.size, L.size_y, L.energy, L.color = size, size_y, power, color
    L.spread = math.radians(spread_deg)
    o.location = loc; o.rotation_euler = (Vector(aim) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    return o


def _material(name, color=(0.8, 0.8, 0.8), roughness=1.0, emission=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    p = m.node_tree.nodes.get("Principled BSDF")
    if p:
        p.inputs["Base Color"].default_value = (*color, 1); p.inputs["Roughness"].default_value = roughness
        p.inputs["Specular IOR Level"].default_value = 0.5 if emission == 0 else 0.0
        p.inputs["Emission Color"].default_value = (1, 1, 1, 1); p.inputs["Emission Strength"].default_value = emission
    return m


def cyc_backdrop(center_xy, floor_z, facing_deg, width, depth, height, radius, name="BG_Backdrop", col=None, segments=16):
    """Seamless cyc: flat floor toward the camera, quarter-circle cove of `radius`, vertical wall behind the target.
    facing_deg = camera azimuth convention (0 = camera at -Y, wall at +Y behind the target)."""
    import bmesh
    prof = [(-depth, 0.0), (0.0, 0.0)]
    for i in range(1, segments + 1):
        t = i / segments * math.pi / 2
        prof.append((radius * math.sin(t), radius * (1 - math.cos(t))))
    prof.append((radius, height))
    me = bpy.data.meshes.get(name) or bpy.data.meshes.new(name)
    bm = bmesh.new(); rows = []
    for x in (-width / 2, width / 2):
        rows.append([bm.verts.new((x, y, z)) for y, z in prof])
    for i in range(len(prof) - 1):
        bm.faces.new((rows[0][i], rows[0][i + 1], rows[1][i + 1], rows[1][i]))
    bm.normal_update()
    for f in bm.faces:  # normals up / toward the camera side
        if f.normal.z < -1e-6 or (abs(f.normal.z) < 1e-6 and f.normal.y > 0): f.normal_flip()
    bm.to_mesh(me); bm.free()
    for poly in me.polygons: poly.use_smooth = True
    o = bpy.data.objects.get(name)
    if o is None:
        o = bpy.data.objects.new(name, me)
    o.data = me; _link(o, col or bpy.context.scene.collection)
    o.location = (center_xy[0], center_xy[1], floor_z); o.rotation_euler = (0, 0, math.radians(facing_deg))
    if not o.data.materials: o.data.materials.append(_material("MAT_Backdrop", (0.8, 0.8, 0.8), 0.9))
    return o


def studio_rig(target, camera="CAM_Hero", key_irradiance=3.0, fill_ratio=0.35, rim_ratio=1.2, backdrop=True,
               shadow_catcher=False, cards=0, softness=1.0, strip_rim=True, collection="STUDIO"):
    """Three-point product rig aimed at the target's bbox centre, placed relative to the camera azimuth:
    key 45 deg to camera-left, 35 deg up; fill camera-right, low, larger & weaker (fill_ratio of key); rim/strip behind,
    opposite the key. Light power from area_light_power(): on-axis irradiance at the target centre equals
    key_irradiance (Sun-strength units: 3 ~ a white card renders at 3.0 linear before exposure; the rim's reduced spread
    is not compensated). Backdrop = cyc behind the target facing the camera; shadow_catcher = floor plane that only receives
    shadows (Cycles, enables Film > Transparent). cards = N emissive planes hidden from the camera for glossy highlights."""
    import numpy as np
    sc = bpy.context.scene; col = _collection(collection)
    bb = world_bbox(target); c = Vector(bb["center"]); size = max(bb["size"]); diag = bb["diagonal"]
    cam = bpy.data.objects.get(camera) if isinstance(camera, str) else camera
    if cam is not None:
        v = cam.matrix_world.translation - c; cam_az = math.degrees(math.atan2(v.x, -v.y))
    else:
        cam_az = 0.0
    d = max(diag * 1.6, 0.3)
    made = {}

    def spot(az_off, elev, dist, sz_w, sz_h, E, name, spread=180.0):
        dirv = _dir_from_angles(cam_az + az_off, elev); loc = c + dirv * dist
        power = area_light_power(E, sz_w, sz_h, dist)
        o = _area_light(name, col, loc, c, sz_w, sz_h, power, spread)
        made[name] = {"location": [round(x, 3) for x in loc], "power_w": round(power, 2), "size": [round(sz_w, 3), round(sz_h, 3)]}
        return o

    s = size * softness
    spot(-45, 35, d, s * 1.2, s * 1.2, key_irradiance, "LGT_Key")
    spot(60, 10, d * 1.2, s * 2.0, s * 1.5, key_irradiance * fill_ratio, "LGT_Fill")
    if strip_rim:
        spot(160, 25, d, s * 0.25, s * 2.0, key_irradiance * rim_ratio, "LGT_Rim", spread=60.0)
    else:
        spot(160, 25, d, s * 0.8, s * 0.8, key_irradiance * rim_ratio, "LGT_Rim")
    # reflection cards: emissive planes invisible to camera, flanking the target (glossy/glass edge definition)
    for n in range(cards):
        side = -1 if n % 2 == 0 else 1; name = f"LGT_Card_{n + 1}"
        me = bpy.data.meshes.get(name) or bpy.data.meshes.new(name)
        if not me.vertices:
            me.from_pydata([(-0.5, 0, -0.5), (0.5, 0, -0.5), (0.5, 0, 0.5), (-0.5, 0, 0.5)], [], [(0, 1, 2, 3)])
        o = bpy.data.objects.get(name) or bpy.data.objects.new(name, me); _link(o, col)
        dirv = _dir_from_angles(cam_az + side * (100 + 15 * (n // 2)), 5); o.location = c + dirv * d * 0.8
        o.rotation_euler = (0, 0, math.radians(cam_az + side * (100 + 15 * (n // 2))))
        o.scale = (size * 0.6, 1, size * 1.8); o.visible_camera = False; o.visible_shadow = False
        if not o.data.materials: o.data.materials.append(_material("MAT_ReflectionCard", (0, 0, 0), 1.0, emission=4.0))
        made[name] = {"location": [round(x, 3) for x in o.location]}
    floor_z = bb["min"][2]
    if backdrop and not shadow_catcher:
        bd = cyc_backdrop((c.x, c.y), floor_z, cam_az, width=diag * 8, depth=diag * 5, height=diag * 4,
                          radius=diag * 1.2, col=col)
        # push the cove behind the target, away from the camera
        to_cam = Vector((math.sin(math.radians(cam_az)), -math.cos(math.radians(cam_az)), 0))
        bd.location = (c.x - to_cam.x * diag * 0.9, c.y - to_cam.y * diag * 0.9, floor_z)
        made["BG_Backdrop"] = {"floor_z": round(floor_z, 4)}
    if shadow_catcher:
        name = "BG_ShadowCatcher"; me = bpy.data.meshes.get(name) or bpy.data.meshes.new(name)
        if not me.vertices:
            me.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
        o = bpy.data.objects.get(name) or bpy.data.objects.new(name, me); _link(o, col)
        o.location = (c.x, c.y, floor_z); o.scale = (diag * 4, diag * 4, 1); o.is_shadow_catcher = True
        sc.render.film_transparent = True
        made[name] = {"is_shadow_catcher": o.is_shadow_catcher, "film_transparent": sc.render.film_transparent}
    aim_err = {}
    for n in ("LGT_Key", "LGT_Fill", "LGT_Rim"):
        o = bpy.data.objects.get(n)
        if o:
            fwd = o.rotation_euler.to_matrix() @ Vector((0, 0, -1)); to_t = (c - o.location).normalized()
            aim_err[n] = round(math.degrees(fwd.angle(to_t)), 5)
    return {"collection": col.name, "camera_azimuth": round(cam_az, 3), "objects": made, "aim_error_deg": aim_err}


# ---------------------------------------------------------------------------------------------------------- turntable
def _linearize(id_data):
    """Set LINEAR interpolation + linear extrapolation on every F-curve of the ID's assigned action (5.x slotted API,
    4.x fallback)."""
    ad = id_data.animation_data; act = ad.action if ad else None; n = 0
    if act is None: return 0
    fcurves = None
    try:
        from bpy_extras import anim_utils
        cb = anim_utils.action_get_channelbag_for_slot(act, ad.action_slot)
        fcurves = cb.fcurves if cb else []
    except (ImportError, AttributeError):
        fcurves = getattr(act, "fcurves", [])
    for fc in fcurves:
        fc.extrapolation = 'LINEAR'
        for k in fc.keyframe_points:
            k.interpolation = 'LINEAR'; n += 1
    return n


def turntable(target, frames=72, mode="object", start=1, camera="CAM_Hero", degrees=360.0, clockwise=False,
              pivot_name="TT_Pivot", margin_check=None):
    """Loop-safe turntable. A pivot empty at the target's bbox centre (XY) and floor (min Z) rotates about Z:
    key 0 at `start`, `degrees` at `start + frames`; the render range is start .. start + frames - 1, so the last
    rendered frame is one step short of the first (no duplicate frame when looping). Step = degrees / frames.
    mode 'object': root targets are parented to the pivot (world transforms kept; an existing outside parent is
    replaced and reported). mode 'camera': the camera is parented to the pivot and orbits.
    margin_check: sample ~24 frames and report the worst frame margin over the turn (silhouettes change as it spins)."""
    sc = bpy.context.scene; objs = _targets(target); bb = world_bbox(objs)
    piv = bpy.data.objects.get(pivot_name)
    if piv is None:
        piv = bpy.data.objects.new(pivot_name, None); piv.empty_display_type = 'CIRCLE'; sc.collection.objects.link(piv)
    if piv.animation_data: piv.animation_data_clear()
    # unparent previous children (keep world transform), reset pivot
    for ch in list(piv.children):
        mw = ch.matrix_world.copy(); ch.parent = None; ch.matrix_world = mw
    piv.rotation_euler = (0, 0, 0); piv.location = (bb["center"][0], bb["center"][1], bb["min"][2]); piv.scale = (1, 1, 1)
    bpy.context.view_layer.update()
    movers = objs if mode == "object" else [bpy.data.objects[camera] if isinstance(camera, str) else camera]
    reparented = {}
    for o in movers:
        if mode == "object" and o.parent is not None and o.parent in objs:
            continue  # child of another target: follows its parent
        if o.parent is not None and o.parent != piv:
            reparented[o.name] = o.parent.name
        mw = o.matrix_world.copy(); o.parent = piv; o.matrix_parent_inverse = piv.matrix_world.inverted(); o.matrix_world = mw
    sign = -1.0 if clockwise else 1.0
    piv.rotation_euler.z = 0.0; piv.keyframe_insert("rotation_euler", index=2, frame=start)
    piv.rotation_euler.z = sign * math.radians(degrees); piv.keyframe_insert("rotation_euler", index=2, frame=start + frames)
    nkeys = _linearize(piv)
    sc.frame_start, sc.frame_end = start, start + frames - 1
    sc.frame_set(start)
    out = {"pivot": piv.name, "mode": mode, "frames": frames, "frame_start": sc.frame_start, "frame_end": sc.frame_end,
           "step_deg": degrees / frames, "keys_linear": nkeys, "movers": [o.name for o in movers], "reparented_from": reparented}
    if margin_check is not None:
        cam = (bpy.data.objects.get(camera) if isinstance(camera, str) else camera) or sc.camera
        if cam is None or cam.type != 'CAMERA':
            out["margin_camera"] = None; out["worst_margin_over_turn"] = None; out["margin_pass"] = False
            out["margin_check_error"] = f"camera {camera!r} not found and the scene has no camera"
        else:
            worst = None
            for i in range(0, frames, max(1, frames // 24)):
                sc.frame_set(start + i); m = frame_margins(cam, objs, margin_check)["min_margin"]
                worst = m if worst is None else min(worst, m)
            sc.frame_set(start)
            out["margin_camera"] = cam.name; out["required_margin"] = margin_check
            out["worst_margin_over_turn"] = worst; out["margin_pass"] = bool(worst >= margin_check)
    return out


def turntable_check(target_or_camera, frames, start=1):
    """Measured loop proof: world matrix at start vs start+frames (must match) and per-frame Z-rotation steps."""
    sc = bpy.context.scene; o = bpy.data.objects[target_or_camera] if isinstance(target_or_camera, str) else target_or_camera
    mats, yaws = [], []
    for f in range(start, start + frames + 1):
        sc.frame_set(f); m = o.matrix_world.copy(); mats.append(m)
        yaws.append(math.degrees(math.atan2(m[1][0], m[0][0])))
    steps = [((yaws[i + 1] - yaws[i] + 180) % 360) - 180 for i in range(frames)]
    diff = max(abs(a - b) for ra, rb in zip(mats[0], mats[-1]) for a, b in zip(ra, rb))
    sc.frame_set(start)
    expected = 360.0 / frames
    uniform = max(abs(abs(s) - expected) for s in steps) < 1e-3
    dup = diff < 1e-5 and sc.frame_end >= start + frames
    return {"object": o.name, "loop_matrix_max_abs_diff": diff, "step_min_deg": min(steps), "step_max_deg": max(steps),
            "expected_step_deg": expected, "uniform_steps": uniform, "duplicate_last_frame": dup,
            "pass": bool(diff < 1e-5 and uniform and not dup)}


# ------------------------------------------------------------------------------------------------------------- driver
def run(opts):
    o = dict(opts); res = {"blender": bpy.app.version_string}; tgt = o["target"]; margin = o.get("margin", 0.08)
    if o.get("resolution"): bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y = o["resolution"]
    if o.get("hero") is not None:
        res["hero"] = hero_camera(tgt, margin=margin, **(o["hero"] if isinstance(o["hero"], dict) else {}))
    if o.get("iso"):
        res["iso"] = ortho_camera(tgt, iso=o["iso"], margin=margin)
    if o.get("ortho"):
        res["ortho"] = ortho_camera(tgt, view=o["ortho"], margin=margin)
    if o.get("rig") is not None:
        res["rig"] = studio_rig(tgt, **(o["rig"] if isinstance(o["rig"], dict) else {}))
    if o.get("turntable"):
        res["turntable"] = turntable(tgt, **o["turntable"])
    if o.get("check"):
        res["check"] = frame_margins(o["check"], tgt, margin)
    if o.get("save"):
        bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(o["save"])); res["saved"] = o["save"]
    return res


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="shot_setup.py")
    p.add_argument("--target", required=True); p.add_argument("--hero", action="store_true")
    p.add_argument("--lens", type=float, default=100.0); p.add_argument("--azimuth", type=float, default=35.0)
    p.add_argument("--elevation", type=float, default=12.0); p.add_argument("--fstop", type=float)
    p.add_argument("--iso", choices=["true", "dimetric"]); p.add_argument("--ortho", choices=["FRONT", "BACK", "SIDE", "LEFT", "TOP"])
    p.add_argument("--margin", type=float, default=0.08); p.add_argument("--resolution")
    p.add_argument("--rig", action="store_true"); p.add_argument("--shadow-catcher", action="store_true")
    p.add_argument("--no-backdrop", action="store_true"); p.add_argument("--cards", type=int, default=0)
    p.add_argument("--turntable", type=int); p.add_argument("--turntable-mode", default="object", choices=["object", "camera"])
    p.add_argument("--turntable-margin", type=float, help="worst frame margin over the turn -> margin_pass")
    p.add_argument("--check"); p.add_argument("--save")
    a = p.parse_args(argv)
    opts = {"target": a.target, "margin": a.margin, "check": a.check, "save": a.save, "iso": a.iso, "ortho": a.ortho}
    if a.resolution: opts["resolution"] = tuple(int(v) for v in a.resolution.lower().split("x"))
    if a.hero: opts["hero"] = {"lens": a.lens, "azimuth": a.azimuth, "elevation": a.elevation, "dof_fstop": a.fstop}
    if a.rig: opts["rig"] = {"shadow_catcher": a.shadow_catcher, "backdrop": not a.no_backdrop, "cards": a.cards}
    if a.turntable:
        opts["turntable"] = {"frames": a.turntable, "mode": a.turntable_mode}
        if a.turntable_margin is not None: opts["turntable"]["margin_check"] = a.turntable_margin
    return run(opts)


if "SHOT_OPTS" in globals():
    result = run(SHOT_OPTS)
    print("SHOT_SETUP " + json.dumps(result, default=str))
elif __name__ == "__main__" and "--" in sys.argv and "--target" in sys.argv[sys.argv.index("--") + 1:]:
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print("SHOT_SETUP " + json.dumps(result, default=str))
else:
    result = {"defined": ["target_points", "world_bbox", "project_points", "frame_margins", "hero_camera", "ortho_camera",
                          "axis_projection", "cyc_backdrop", "studio_rig", "turntable", "turntable_check", "run"]}
