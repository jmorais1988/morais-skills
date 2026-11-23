"""Archviz shot setup: metric units, level two-point-perspective cameras framed with lens shift, sun position
(azimuth/elevation or lat/lon/UTC time), Sky Texture / HDRI world with a matched Sun lamp, window portal lights, Cycles
render + color-management presets, an exposure probe, and batch rendering of all shot cameras.

Headless / CLI (prints one line: ARCHVIZ_SETUP <json>):
    blender -b scene.blend --python archviz_setup.py -- --preset interior_final [--sun-elev 35 --sun-azim 230 | --hdri f.exr]
        [--portals GLASS_] [--camera NAME,x,y,tx,ty,tz,lens] [--probe] [--render-dir out/] [--save out.blend]
Live (Blender:execute_blender_code): exec, then call functions (no side effects on exec):
    two_point_camera("CAM_Living", (5.4, 0.5), (0.8, 3.0, 1.2), lens=22)
    sun_and_sky(elevation=35, azimuth=230); window_portals("GLASS_"); render_preset("interior_final")
    print(exposure_probe("CAM_Living"))   -> suggested exposure (EV) from a small render
Conventions: azimuth in degrees clockwise from +Y (north) toward +X (east); elevation above the horizon.
Every function returns a dict describing what it set (and measured, for cameras/probe).
"""
import bpy, math, os, sys, json, tempfile, datetime
from mathutils import Vector, Euler
from bpy_extras.object_utils import world_to_camera_view

PRESETS = {  # Cycles; tuned for interiors lit through windows. Final = still for delivery; preview = look-dev.
    "interior_preview": dict(samples=128, adaptive_threshold=0.05, diffuse_bounces=4, glossy_bounces=4, transmission_bounces=8,
                             transparent_max_bounces=8, max_bounces=8, clamp_indirect=10.0, resolution_percentage=50),
    "interior_final": dict(samples=1024, adaptive_threshold=0.01, diffuse_bounces=6, glossy_bounces=4, transmission_bounces=12,
                           transparent_max_bounces=16, max_bounces=12, clamp_indirect=6.0, resolution_percentage=100),
    "exterior_final": dict(samples=512, adaptive_threshold=0.01, diffuse_bounces=3, glossy_bounces=4, transmission_bounces=12,
                           transparent_max_bounces=16, max_bounces=8, clamp_indirect=10.0, resolution_percentage=100),
}


def units(scene=None, length_unit='METERS'):
    sc = scene or bpy.context.scene; us = sc.unit_settings
    us.system, us.scale_length, us.length_unit = 'METRIC', 1.0, length_unit
    return {"system": us.system, "scale_length": us.scale_length, "length_unit": us.length_unit}


def two_point_camera(name, position_xy, target, lens=24.0, eye_height=1.5, floor_z=0.0, resolution=None, sensor=36.0,
                     clip_start=0.05, clip_end=500.0, set_active=True):
    """Level camera (verticals stay vertical) at eye height, yawed toward `target`, target framed vertically by shift_y.
    shift is a fraction of the larger sensor dimension (sensor_fit AUTO): shift_y = f * dz / (dist * sensor)."""
    sc = bpy.context.scene
    cam = bpy.data.objects.get(name)
    if cam is None or cam.type != 'CAMERA':
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name)); sc.collection.objects.link(cam)
    if resolution:
        sc.render.resolution_x, sc.render.resolution_y = resolution
    cd = cam.data
    cd.type, cd.lens, cd.sensor_fit, cd.sensor_width = 'PERSP', lens, 'AUTO', sensor
    cd.clip_start, cd.clip_end = clip_start, clip_end
    loc = Vector((position_xy[0], position_xy[1], floor_z + eye_height)); tgt = Vector(target)
    flat = Vector((tgt.x - loc.x, tgt.y - loc.y, 0.0)); dist = flat.length
    yaw = math.atan2(flat.y, flat.x) - math.pi / 2
    cam.location = loc; cam.rotation_euler = Euler((math.pi / 2, 0.0, yaw))
    cd.shift_x = 0.0
    cd.shift_y = lens * (tgt.z - loc.z) / (dist * sensor) if dist > 1e-6 else 0.0
    if set_active: sc.camera = cam
    bpy.context.view_layer.update()
    ndc = world_to_camera_view(sc, cam, tgt)
    return {"camera": cam.name, "location": [round(v, 3) for v in loc], "yaw_deg": round(math.degrees(yaw), 2), "lens": lens,
            "shift_y": round(cd.shift_y, 4), "target_ndc": [round(ndc.x, 4), round(ndc.y, 4)], "horizontal_fov_deg":
            round(math.degrees(2 * math.atan(sensor / 2 / lens)) if sc.render.resolution_x >= sc.render.resolution_y else 0, 1)}


def sun_angles(lat, lon, when_utc):
    """Solar elevation/azimuth (deg, azimuth clockwise from north) -- NOAA approximation, ~0.5 deg."""
    doy = when_utc.timetuple().tm_yday; hour = when_utc.hour + when_utc.minute / 60 + when_utc.second / 3600
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = hour * 60 + eqt + 4 * lon; ha = math.radians(tst / 4 - 180); la = math.radians(lat)
    cz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha); zen = math.acos(max(-1, min(1, cz)))
    az = math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(la) - math.tan(decl) * math.cos(la))) + 180
    return {"elevation": round(90 - math.degrees(zen), 2), "azimuth": round(az % 360, 2)}


def _sun_dir(elevation, azimuth):
    e, a = math.radians(elevation), math.radians(azimuth)
    return Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))  # vector TOWARD the sun


def sun_and_sky(elevation=35.0, azimuth=225.0, sky_type='MULTIPLE_SCATTERING', sun_strength=None, sun_disc=False,
                north_offset_deg=0.0, air=1.0, aerosols=1.0, ozone=1.0, angle_deg=0.526):
    """World Sky Texture + matching Sun lamp (sharper shadows, better sampling than the sky's sun disc).
    sun_strength None -> sun_strength_for_sky(elevation): matches the sky's own disc (measured, ~100-140 W/m2)."""
    sc = bpy.context.scene; az = azimuth + north_offset_deg
    w = sc.world or bpy.data.worlds.new("World"); sc.world = w
    nt = w.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld'); bg = nt.nodes.new('ShaderNodeBackground'); sky = nt.nodes.new('ShaderNodeTexSky')
    nt.links.new(sky.outputs[0], bg.inputs[0]); nt.links.new(bg.outputs[0], out.inputs[0])
    notes = []
    try: sky.sky_type = sky_type
    except TypeError: notes.append(f"sky_type {sky_type} unavailable; using {sky.sky_type}")
    for k, v in (("sun_elevation", math.radians(elevation)), ("sun_rotation", math.radians(az)), ("sun_disc", sun_disc),
                 ("air_density", air), ("aerosol_density", aerosols), ("dust_density", aerosols), ("ozone_density", ozone),
                 ("sun_size", math.radians(angle_deg))):
        if hasattr(sky, k): setattr(sky, k, v)
    sun = bpy.data.objects.get("SUN_Key")
    if sun is None:
        sun = bpy.data.objects.new("SUN_Key", bpy.data.lights.new("SUN_Key", 'SUN')); sc.collection.objects.link(sun)
    d = _sun_dir(elevation, az)
    sun.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    sun.data.angle = math.radians(angle_deg)
    sun.data.energy = sun_strength if sun_strength is not None else sun_strength_for_sky(elevation)
    return {"sky_type": sky.sky_type, "sun_elevation": elevation, "sun_azimuth": az, "sun_strength_w_m2": sun.data.energy,
            "sun_disc": getattr(sky, "sun_disc", None), "sun_direction": [round(x, 4) for x in d], "notes": notes}


# Sun lamp strength (W/m2) whose irradiance equals the MULTIPLE_SCATTERING Sky Texture's own sun disc (sun_intensity 1,
# air/aerosol/ozone 1), measured in 5.2 on a white diffuse plane: elevation deg -> W/m2. NOT the 1000 W/m2 "real sun".
SUN_MATCH_TABLE = ((15.0, 99.0), (35.0, 130.0), (60.0, 142.0))


def sun_strength_for_sky(elevation):
    t = SUN_MATCH_TABLE
    if elevation <= t[0][0]: return t[0][1]
    for (e0, s0), (e1, s1) in zip(t, t[1:]):
        if elevation <= e1: return s0 + (s1 - s0) * (elevation - e0) / (e1 - e0)
    return t[-1][1]


def hdri_world(path, strength=1.0, rotation_deg=0.0):
    sc = bpy.context.scene; w = sc.world or bpy.data.worlds.new("World"); sc.world = w
    nt = w.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld'); bg = nt.nodes.new('ShaderNodeBackground'); env = nt.nodes.new('ShaderNodeTexEnvironment')
    tc = nt.nodes.new('ShaderNodeTexCoord'); mp = nt.nodes.new('ShaderNodeMapping')
    env.image = bpy.data.images.load(bpy.path.abspath(path), check_existing=True)
    mp.inputs["Rotation"].default_value[2] = math.radians(rotation_deg); bg.inputs["Strength"].default_value = strength
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"]); nt.links.new(mp.outputs[0], env.inputs[0])
    nt.links.new(env.outputs[0], bg.inputs[0]); nt.links.new(bg.outputs[0], out.inputs[0])
    return {"hdri": env.image.name, "strength": strength, "rotation_deg": rotation_deg}


def window_portals(glass_prefix="GLASS_", outward_offset=0.05, rooms_prefix="FLR_"):
    """Cycles portal area light over each window pane, facing into the room (toward the nearest room floor centroid)."""
    sc = bpy.context.scene; made = []
    floors = [o for o in sc.objects if o.name.startswith(rooms_prefix)]
    centres = [sum((o.matrix_world @ Vector(c) for c in o.bound_box), Vector()) / 8 for o in floors]
    for g in [o for o in sc.objects if o.type == 'MESH' and o.name.startswith(glass_prefix)]:
        bb = [g.matrix_world @ Vector(c) for c in g.bound_box]; cen = sum(bb, Vector()) / 8
        ext = [max(v[i] for v in bb) - min(v[i] for v in bb) for i in range(3)]
        thin = min(range(3), key=lambda i: ext[i]); n = Vector([1.0 if i == thin else 0.0 for i in range(3)])
        if centres:
            inside = min(centres, key=lambda c: (c - cen).length)
            if (inside - cen).dot(n) < 0: n = -n
        width = max(ext[i] for i in range(2) if i != thin) if thin != 2 else ext[0]; height = ext[2] if thin != 2 else ext[1]
        name = "PORTAL_" + g.name
        lo = bpy.data.objects.get(name)
        if lo is None:
            lo = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA')); sc.collection.objects.link(lo)
        L = lo.data; L.shape = 'RECTANGLE'; L.size, L.size_y = width, height
        if hasattr(L, "cycles") and hasattr(L.cycles, "is_portal"): L.cycles.is_portal = True
        lo.location = cen - n * outward_offset
        lo.rotation_euler = n.to_track_quat('-Z', 'Y').to_euler()
        made.append({"portal": lo.name, "size": [round(width, 3), round(height, 3)], "faces_into_room": [round(x, 3) for x in n],
                     "is_portal": getattr(getattr(L, "cycles", None), "is_portal", None)})
    return {"portals": made}


def render_preset(name="interior_final", resolution=None, device=None, view="AgX", look=None, exposure=None, exr=True):
    sc = bpy.context.scene; r = sc.render; p = PRESETS[name]; c = sc.cycles
    r.engine = 'CYCLES'
    if device: c.device = device
    if resolution: r.resolution_x, r.resolution_y = resolution
    r.resolution_percentage = p["resolution_percentage"]
    c.samples, c.use_adaptive_sampling, c.adaptive_threshold = p["samples"], True, p["adaptive_threshold"]
    c.use_denoising = True
    for k in ("diffuse_bounces", "glossy_bounces", "transmission_bounces", "transparent_max_bounces", "max_bounces"):
        setattr(c, k, p[k])
    c.sample_clamp_indirect = p["clamp_indirect"]; c.sample_clamp_direct = 0.0
    c.caustics_reflective = c.caustics_refractive = False
    if hasattr(c, "use_light_tree"): c.use_light_tree = True
    if hasattr(c, "blur_glossy"): c.blur_glossy = 1.0
    vs = sc.view_settings; notes = []
    vs.view_transform = view
    if look:
        try: vs.look = look
        except TypeError: notes.append(f"look '{look}' not valid for {view}")
    if exposure is not None: vs.exposure = exposure
    if exr:
        r.image_settings.file_format = 'OPEN_EXR'; r.image_settings.color_depth = '16'
    vl = bpy.context.view_layer
    if hasattr(vl, "cycles"):
        for k in ("denoising_store_passes",):
            if hasattr(vl.cycles, k): setattr(vl.cycles, k, True)
    for k in ("use_pass_cryptomatte_object", "use_pass_cryptomatte_material"):
        if hasattr(vl, k): setattr(vl, k, True)
    return {"preset": name, "engine": r.engine, "samples": c.samples, "threshold": c.adaptive_threshold, "view": vs.view_transform,
            "look": vs.look, "exposure": vs.exposure, "resolution": [r.resolution_x, r.resolution_y, r.resolution_percentage], "notes": notes}


def _render_linear(camera, res, samples, filepath):
    """Render a small linear EXR through `camera`, return flat RGBA list (scene-linear, before the view transform)."""
    sc = bpy.context.scene; r = sc.render; c = sc.cycles
    saved = (sc.camera, r.resolution_x, r.resolution_y, r.resolution_percentage, c.samples, r.filepath,
             r.image_settings.file_format, r.image_settings.color_depth, c.use_denoising)
    try:
        if camera: sc.camera = bpy.data.objects[camera] if isinstance(camera, str) else camera
        ar = r.resolution_y / r.resolution_x
        r.resolution_x, r.resolution_y, r.resolution_percentage = res, max(1, int(res * ar)), 100
        c.samples = samples; c.use_denoising = True
        r.image_settings.file_format = 'OPEN_EXR'; r.image_settings.color_depth = '32'; r.filepath = filepath
        bpy.ops.render.render(write_still=True)
    finally:
        (sc.camera, r.resolution_x, r.resolution_y, r.resolution_percentage, c.samples, r.filepath,
         r.image_settings.file_format, r.image_settings.color_depth, c.use_denoising) = saved
    img = bpy.data.images.load(filepath); px = list(img.pixels); bpy.data.images.remove(img)
    return px


def exposure_probe(camera=None, res=240, samples=32, target_median=0.18):
    """Suggest Film exposure (EV): median luminance of a small render mapped to `target_median` (scene-linear), and
    report how much of the frame would still exceed 1.0 (windows/sky) after that exposure."""
    import numpy as np
    fp = os.path.join(tempfile.gettempdir(), "archviz_probe.exr")
    px = np.array(_render_linear(camera, res, samples, fp), dtype=np.float32).reshape(-1, 4)
    lum = 0.2126 * px[:, 0] + 0.7152 * px[:, 1] + 0.0722 * px[:, 2]
    med = float(np.median(lum)); ev = math.log2(target_median / med) if med > 0 else None
    k = 2 ** ev if ev is not None else 1.0
    return {"median_linear": round(med, 5), "p95_linear": round(float(np.percentile(lum, 95)), 4),
            "suggested_exposure_ev": round(ev, 2) if ev is not None else None,
            "fraction_above_1_after": round(float((lum * k > 1.0).mean()), 4), "pixels": int(lum.size)}


def batch_render(cameras_prefix="CAM_", out_dir="//renders", ext_png=True):
    sc = bpy.context.scene; r = sc.render; done = []
    saved = (sc.camera, r.filepath, r.image_settings.file_format, r.image_settings.color_depth)
    base = bpy.path.abspath(out_dir); os.makedirs(base, exist_ok=True)
    try:
        for cam in sorted((o for o in sc.objects if o.type == 'CAMERA' and o.name.startswith(cameras_prefix)), key=lambda o: o.name):
            sc.camera = cam
            r.filepath = os.path.join(base, cam.name); bpy.ops.render.render(write_still=True)
            files = [r.filepath + ("." + r.image_settings.file_format.lower().replace("open_", ""))]
            if ext_png:  # save_render writes in the SCENE output format whatever the extension -> switch to PNG first
                fmt, depth = r.image_settings.file_format, r.image_settings.color_depth
                r.image_settings.file_format, r.image_settings.color_depth = 'PNG', '16'
                png = os.path.join(base, cam.name + ".png")
                bpy.data.images["Render Result"].save_render(png, scene=sc)  # view transform + look + exposure applied
                r.image_settings.file_format, r.image_settings.color_depth = fmt, depth
                files.append(png)
            done.append({"camera": cam.name, "files": files})
    finally:
        sc.camera, r.filepath, r.image_settings.file_format, r.image_settings.color_depth = saved
    return {"rendered": done}


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="archviz_setup.py")
    p.add_argument("--preset", default="interior_final", choices=list(PRESETS)); p.add_argument("--sun-elev", type=float)
    p.add_argument("--sun-azim", type=float, default=225.0); p.add_argument("--hdri"); p.add_argument("--portals")
    p.add_argument("--camera", action="append", help="NAME,x,y,tx,ty,tz,lens"); p.add_argument("--probe", action="store_true")
    p.add_argument("--render-dir"); p.add_argument("--save")
    a = p.parse_args(argv); res = {"units": units(), "render": render_preset(a.preset)}
    if a.hdri: res["world"] = hdri_world(a.hdri)
    elif a.sun_elev is not None: res["world"] = sun_and_sky(a.sun_elev, a.sun_azim)
    if a.portals: res["portals"] = window_portals(a.portals)
    for spec in a.camera or []:
        n, x, y, tx, ty, tz, lens = spec.split(","); res.setdefault("cameras", []).append(
            two_point_camera(n, (float(x), float(y)), (float(tx), float(ty), float(tz)), float(lens)))
    if a.probe: res["probe"] = exposure_probe()
    if a.render_dir: res["batch"] = batch_render(out_dir=a.render_dir)
    if a.save: bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(a.save)); res["saved"] = a.save
    return res


if __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("ARCHVIZ_SETUP " + json.dumps(result, default=str))
else:
    result = {"defined": ["units", "two_point_camera", "sun_angles", "sun_and_sky", "hdri_world", "window_portals",
                          "render_preset", "exposure_probe", "batch_render", "PRESETS"]}
