"""Parametric PCB enclosure (base with screw bosses + snap-fit lid) in build123d -> STEP + STL + params JSON.

Use when a part is dimension-driven (PCB box, bracket, jig) and needs STEP for CAD/CNC or exact fits -- the job
Blender is wrong for. Pure Python, not Blender. All values in millimetres.

Install (Python 3.10-3.13; OCP wheels):  python -m venv .venv && .venv/Scripts/pip install build123d   (or .venv/bin/pip)
CLI (prints one line: CAD_ENCLOSURE_TEMPLATE <json>):
    python cad_enclosure_template.py --out-dir ./enclosure [--pcb 50x30x1.6] [--pcb-clearance 1.0] [--wall 2.0]
        [--floor 2.0] [--standoff 5] [--component-height 12] [--top-gap 2] [--screw-d 2.5] [--pilot-d 2.1]
        [--boss-factor 2.2] [--hole-inset 3.5] [--fit-clearance 0.3] [--lid 2.0] [--lip-h 3] [--lip-t 1.2]
        [--tab-w 6] [--tab-l 8] [--tab-t 1.2] [--hook 0.8] [--hook-ramp 1.0] [--hook-land 0.8] [--corner-r 1.5]
        [--max-strain 0.02] [--stl-tolerance 0.005] [--angular-tolerance 0.1] [--cutouts cutouts.json | '<inline JSON>']
    --cutouts: list of {"face": "+x|-x|+y|-y|bottom|lid", "shape": "rect|circle", "center": [u, v],
        "size": [w, h] | d, "r": corner radius (rect, optional), "from": "base|floor|pcb_bottom|pcb_top", "name": "usb_c"}
      walls: u = y on +-x, u = x on +-y (mm from the box centre), v = z above `from` (default base = outer bottom);
      bottom / lid: u = x, v = y (top view, assembly coordinates). Through-cut of the wall/floor/lid plate only;
      warnings when a cut-out leaves the cavity band, hits a snap window/tab, a screw boss or the lid lips.
Python:  from cad_enclosure_template import build_enclosure; info = build_enclosure(out_dir, **params)

Outputs: base.step/.stl (open top up), lid.step/.stl (print orientation: plate on the bed, tabs up),
enclosure_assembly.step (base + seated lid), enclosure_params.json (all inputs + derived dims, boss centres,
snap strain, lid print->assembly transform) for downstream checks (e.g. import STL into Blender, measure).
Design rules applied: inner cavity = PCB + 2 x clearance; boss OD = boss_factor x screw d (2-2.5x); pilot for
thread-forming screws ~0.8-0.85 x d [check screw vendor]; lid lip on the short ends and cantilever snap tabs on the
long walls engaging through-windows; snap strain eps = 1.5 * t * y / l^2 (constant-section cantilever) with
y = hook - fit_clearance, warned against --max-strain (material-specific; get it from the datasheet).
Limitations: FDM/SLA oriented (no draft); windows are plain rectangles; cut-outs are rect/rounded-rect/circle
through-cuts normal to a face (no countersinks, no cuts on filleted corners). build123d links builders only within
one Python scope, so helpers return standalone solids that the caller subtracts with bd.add(..., mode=SUBTRACT). Windows only: if build123d fails importing a malformed
system font, the import is retried with the system-font scan disabled (text features then need explicit font files).
"""
import argparse, json, math, os, platform, sys


def _import_build123d():
    try:
        import build123d as bd
        return bd, False
    except Exception:
        for k in [m for m in sys.modules if m == "build123d" or m.startswith("build123d.")]:
            del sys.modules[k]
        import lib3mf  # noqa: F401  (needs the real OS name; import before the patch)
        real = platform.system
        platform.system = lambda: "NoSystemFonts"
        try:
            import build123d as bd
        finally:
            platform.system = real
        return bd, True


DEFAULTS = dict(pcb_l=50.0, pcb_w=30.0, pcb_t=1.6, pcb_clearance=1.0, wall=2.0, floor=2.0, standoff=5.0,
                component_height=12.0, top_gap=2.0, screw_d=2.5, pilot_d=2.1, boss_factor=2.2, hole_inset=3.5,
                fit_clearance=0.3, lid=2.0, lip_h=3.0, lip_t=1.2, tab_w=6.0, tab_l=8.0, tab_t=1.2, hook=0.8,
                hook_ramp=1.0, hook_land=0.8, corner_r=1.5, max_strain=0.02, stl_tolerance=0.005,
                angular_tolerance=0.1)


def derive(p):
    d = {}
    d["inner_l"] = p["pcb_l"] + 2 * p["pcb_clearance"]
    d["inner_w"] = p["pcb_w"] + 2 * p["pcb_clearance"]
    d["outer_l"] = d["inner_l"] + 2 * p["wall"]
    d["outer_w"] = d["inner_w"] + 2 * p["wall"]
    d["pcb_bottom_z"] = p["floor"] + p["standoff"]
    d["pcb_top_z"] = d["pcb_bottom_z"] + p["pcb_t"]
    d["base_h"] = d["pcb_top_z"] + p["component_height"] + p["top_gap"]
    d["boss_od"] = p["boss_factor"] * p["screw_d"]
    hx, hy = p["pcb_l"] / 2 - p["hole_inset"], p["pcb_w"] / 2 - p["hole_inset"]
    d["boss_centers"] = [[sx * hx, sy * hy] for sx in (-1, 1) for sy in (-1, 1)]
    d["tab_x"] = [-d["inner_l"] / 4, d["inner_l"] / 4]
    d["arm_outer_y"] = d["inner_w"] / 2 - p["fit_clearance"]
    d["hook_bottom_z"] = d["base_h"] - p["tab_l"]
    d["hook_top_z"] = d["hook_bottom_z"] + p["hook_ramp"] + p["hook_land"]
    d["window_z"] = [d["hook_bottom_z"] - p["fit_clearance"], d["hook_top_z"] + p["fit_clearance"]]
    d["window_w"] = p["tab_w"] + 2 * p["fit_clearance"]
    y = p["hook"] - p["fit_clearance"]
    d["snap_deflection"] = y
    d["snap_strain"] = 1.5 * p["tab_t"] * y / p["tab_l"] ** 2
    # print orientation of the lid: rotate 180 deg about X, then lift so the plate sits on z=0
    top = d["base_h"] + p["lid"]
    d["lid_print_to_assembly"] = [[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, top], [0, 0, 0, 1]]
    warn = []
    if d["snap_strain"] > p["max_strain"]:
        warn.append(f"snap strain {d['snap_strain']:.4f} > max {p['max_strain']}: lengthen tab_l or thin tab_t")
    if y <= 0:
        warn.append("hook <= fit_clearance: tab will not retain the lid")
    if p["hook"] >= p["wall"] + p["fit_clearance"]:
        warn.append("hook deeper than wall: tip protrudes outside the case")
    if d["hook_bottom_z"] <= d["pcb_top_z"] + 0.5:
        warn.append("snap tabs reach the PCB zone: shorten tab_l or raise top_gap")
    gap = p["pcb_clearance"] + p["hole_inset"] - d["boss_od"] / 2
    if gap < 0:
        warn.append(f"boss merges into wall by {-gap:.2f} mm (acceptable if intended)")
    if d["boss_od"] < 2 * p["screw_d"]:
        warn.append("boss OD < 2x screw d: boss may split")
    if p["pilot_d"] >= p["screw_d"]:
        warn.append("pilot_d >= screw_d: thread-forming screw will not bite (use insert/nut sizes instead)")
    d["cutouts"] = [_derive_cutout(p, d, c, i, warn) for i, c in enumerate(p.get("cutouts") or [])]
    d["warnings"] = warn
    return d


CUTOUT_FACES = ("+x", "-x", "+y", "-y", "bottom", "lid")
_V_REF = {"base": lambda p, d: 0.0, "floor": lambda p, d: p["floor"], "pcb_bottom": lambda p, d: d["pcb_bottom_z"],
          "pcb_top": lambda p, d: d["pcb_top_z"]}


def parse_cutouts(spec):
    """None | list of dicts | JSON string | path to a .json file -> list of dicts."""
    if spec is None or spec == "":
        return []
    if isinstance(spec, str):
        spec = json.load(open(spec, encoding="utf-8")) if os.path.isfile(spec) else json.loads(spec)
    return [spec] if isinstance(spec, dict) else list(spec)


def _derive_cutout(p, d, c, i, warn):
    """Face-local cut-out -> world plane (assembly coordinates) + checks. Walls: u = x (+-y) or y (+-x), v = z above
    `from` (base|floor|pcb_bottom|pcb_top, default base = z 0). bottom/lid: u = x, v = y (top view)."""
    face = str(c.get("face", "")).lower()
    if face not in CUTOUT_FACES:
        raise ValueError(f"cutout {i}: face must be one of {CUTOUT_FACES}")
    shape = str(c.get("shape", "rect")).lower()
    size = c.get("size"); size = [size] if isinstance(size, (int, float)) else list(size)
    if shape == "circle":
        w = h = float(size[0]); r = w / 2
    elif shape == "rect":
        w, h = float(size[0]), float(size[1]); r = float(c.get("r", 0.0))
        if r * 2 >= min(w, h) - 1e-9 and r > 0:
            r = min(w, h) / 2 - 1e-3  # full slot; RectangleRounded needs r < half the short side
    else:
        raise ValueError(f"cutout {i}: shape must be rect or circle")
    u, v = (float(x) for x in c["center"])
    ref = str(c.get("from", "base")) if face not in ("bottom", "lid") else "top"
    if face not in ("bottom", "lid"):
        v += _V_REF[ref](p, d)
    hl, hw, H = d["outer_l"] / 2, d["outer_w"] / 2, d["base_h"]
    if face in ("+x", "-x"):
        s = 1 if face == "+x" else -1
        origin, x_dir, normal, depth = (s * (d["inner_l"] / 2 + p["wall"] / 2), u, v), (0, 1, 0), (1, 0, 0), p["wall"]
        u_lim, v_lo, v_hi = d["inner_w"] / 2, p["floor"], H - p["lip_h"] - p["fit_clearance"]
        plane_outer = ("x", s * hl)
    elif face in ("+y", "-y"):
        s = 1 if face == "+y" else -1
        origin, x_dir, normal, depth = (u, s * (d["inner_w"] / 2 + p["wall"] / 2), v), (1, 0, 0), (0, 1, 0), p["wall"]
        u_lim, v_lo, v_hi = d["inner_l"] / 2, p["floor"], H
        plane_outer = ("y", s * hw)
        for tx in d["tab_x"]:  # snap window / tab zone on the long walls
            if abs(u - tx) < w / 2 + d["window_w"] / 2 + p["wall"] and v + h / 2 > d["window_z"][0] - p["wall"]:
                warn.append(f"cutout {i} ({face}) overlaps snap window/tab at x={tx:.2f} (keep >= wall away)")
    else:
        top = face == "lid"
        z = (H + p["lid"] / 2) if top else p["floor"] / 2
        origin, x_dir, normal, depth = (u, v, z), (1, 0, 0), (0, 0, 1), p["lid"] if top else p["floor"]
        u_lim, v_lo, v_hi = d["inner_l"] / 2, -d["inner_w"] / 2, d["inner_w"] / 2
        plane_outer = ("z", H + p["lid"] if top else 0.0)
        if not top:
            for bx, by in d["boss_centers"]:
                if abs(u - bx) < w / 2 + d["boss_od"] / 2 and abs(v - by) < h / 2 + d["boss_od"] / 2:
                    warn.append(f"cutout {i} (bottom) overlaps screw boss at ({bx:.2f}, {by:.2f})")
        else:
            lx = d["inner_l"] / 2 - p["fit_clearance"] - p["lip_t"]
            if abs(u) + w / 2 > lx:
                warn.append(f"cutout {i} (lid) reaches the lid lips (|x| > {lx:.2f}): lip gets notched")
    if abs(u) + w / 2 > u_lim - (p["corner_r"] if face in ("bottom", "lid") else 0):
        warn.append(f"cutout {i} ({face}) extends past the cavity edge (|u|+w/2 = {abs(u) + w / 2:.2f} > {u_lim:.2f})")
    if face not in ("bottom", "lid") and (v - h / 2 < v_lo or v + h / 2 > v_hi):
        warn.append(f"cutout {i} ({face}) z range {v - h / 2:.2f}..{v + h / 2:.2f} leaves the free wall band "
                    f"{v_lo:.2f}..{v_hi:.2f} (floor / lid lip)")
    if face in ("bottom", "lid") and (v - h / 2 < v_lo or v + h / 2 > v_hi):
        warn.append(f"cutout {i} ({face}) y range leaves the cavity {v_lo:.2f}..{v_hi:.2f}")
    return {"name": c.get("name", f"cutout{i}"), "face": face, "shape": shape, "w": w, "h": h, "r": r,
            "center_world": list(origin), "x_dir": list(x_dir), "normal": list(normal), "depth": depth,
            "outer_plane": list(plane_outer), "v_from": ref}


def _cutter(bd, c):
    """Standalone cutter solid (through the wall + 0.5 mm each side). Built in its own BuildPart: build123d only links
    builders entered in the same Python scope, so the caller subtracts it with bd.add(..., mode=Mode.SUBTRACT)."""
    pl = bd.Plane(origin=tuple(c["center_world"]), x_dir=tuple(c["x_dir"]), z_dir=tuple(c["normal"]))
    with bd.BuildPart() as cp:
        with bd.BuildSketch(pl):
            if c["shape"] == "circle":
                bd.Circle(c["w"] / 2)
            elif c["r"] > 0:
                bd.RectangleRounded(c["w"], c["h"], c["r"])
            else:
                bd.Rectangle(c["w"], c["h"])
        bd.extrude(amount=c["depth"] / 2 + 0.5, both=True)
    return cp.part


def build_base(bd, p, d):
    C, MIN, MAX = bd.Align.CENTER, bd.Align.MIN, bd.Align.MAX
    with bd.BuildPart() as base:
        bd.Box(d["outer_l"], d["outer_w"], d["base_h"], align=(C, C, MIN))
        if p["corner_r"] > 0:
            bd.fillet(base.edges().filter_by(bd.Axis.Z), radius=p["corner_r"])
        with bd.Locations((0, 0, p["floor"])):
            bd.Box(d["inner_l"], d["inner_w"], d["base_h"], align=(C, C, MIN), mode=bd.Mode.SUBTRACT)
        with bd.Locations(*[(x, y, p["floor"]) for x, y in d["boss_centers"]]):
            bd.Cylinder(d["boss_od"] / 2, p["standoff"], align=(C, C, MIN))
        with bd.Locations(*[(x, y, d["pcb_bottom_z"]) for x, y in d["boss_centers"]]):
            bd.Cylinder(p["pilot_d"] / 2, p["standoff"], align=(C, C, MAX), mode=bd.Mode.SUBTRACT)
        wz0, wz1 = d["window_z"]
        wy = d["inner_w"] / 2 + p["wall"] / 2
        with bd.Locations(*[(x, sy * wy, wz0) for x in d["tab_x"] for sy in (-1, 1)]):
            bd.Box(d["window_w"], p["wall"] + 2.0, wz1 - wz0, align=(C, C, MIN), mode=bd.Mode.SUBTRACT)
        for c in d["cutouts"]:
            if c["face"] != "lid":
                bd.add(_cutter(bd, c), mode=bd.Mode.SUBTRACT)
    return base.part


def build_lid_assembly(bd, p, d):
    """Lid in assembly position (plate bottom on the base rim at z = base_h)."""
    C, MIN, MAX = bd.Align.CENTER, bd.Align.MIN, bd.Align.MAX
    H, fit = d["base_h"], p["fit_clearance"]
    with bd.BuildPart() as lid:
        with bd.Locations((0, 0, H)):
            bd.Box(d["outer_l"], d["outer_w"], p["lid"], align=(C, C, MIN))
        if p["corner_r"] > 0:
            bd.fillet(lid.edges().filter_by(bd.Axis.Z), radius=p["corner_r"])
        lx = d["inner_l"] / 2 - fit - p["lip_t"] / 2
        with bd.Locations((-lx, 0, H), (lx, 0, H)):
            bd.Box(p["lip_t"], d["inner_w"] - 2 * fit, p["lip_h"], align=(C, C, MAX))
        ay = d["arm_outer_y"] - p["tab_t"] / 2
        with bd.Locations(*[(x, sy * ay, H) for x in d["tab_x"] for sy in (-1, 1)]):
            bd.Box(p["tab_w"], p["tab_t"], p["tab_l"], align=(C, C, MAX))
        zb, zr, zt = d["hook_bottom_z"], d["hook_bottom_z"] + p["hook_ramp"], d["hook_top_z"]
        y0, overlap = d["arm_outer_y"], 0.1
        for x in d["tab_x"]:
            for sy in (-1, 1):
                # profile in the YZ plane (u = y, v = z): lead-in ramp below, flat catch face on top
                pts = [(sy * (y0 - overlap), zb), (sy * y0, zb), (sy * (y0 + p["hook"]), zr),
                       (sy * (y0 + p["hook"]), zt), (sy * (y0 - overlap), zt)]
                with bd.BuildSketch(bd.Plane.YZ.offset(x)):
                    bd.Polygon(*pts, align=None)
                bd.extrude(amount=p["tab_w"] / 2, both=True)
        for c in d["cutouts"]:
            if c["face"] == "lid":
                bd.add(_cutter(bd, c), mode=bd.Mode.SUBTRACT)
    return lid.part


def weld_stl(path, decimals=5):
    """Snap binary-STL vertices to a 10^-decimals mm grid so shared edges match bit-for-bit, then count open edges.
    OCC tessellation of a moved/rotated shape can leave sub-micron cracks that exact-match importers (Blender STL
    import) report as non-manifold. Pure stdlib."""
    import struct
    from collections import Counter
    with open(path, "rb") as f:
        head = f.read(80); n = struct.unpack("<I", f.read(4))[0]; body = f.read(50 * n)
    out, edges = bytearray(), Counter()
    for i in range(n):
        rec = struct.unpack_from("<12fH", body, 50 * i)
        vs = [tuple(struct.unpack("<f", struct.pack("<f", round(c, decimals) + 0.0))[0] for c in rec[3 + 3 * k:6 + 3 * k])
              for k in range(3)]
        for k in range(3):
            edges[tuple(sorted((vs[k], vs[(k + 1) % 3])))] += 1
        out += struct.pack("<12fH", *rec[:3], *vs[0], *vs[1], *vs[2], rec[12])
    with open(path, "wb") as f:
        f.write(head); f.write(struct.pack("<I", n)); f.write(out)
    return {"triangles": n, "open_edges": sum(1 for c in edges.values() if c != 2)}


def _valid(shape):
    v = shape.is_valid  # property in build123d >= 0.10, method in older releases
    return bool(v() if callable(v) else v)


def build_enclosure(out_dir, **overrides):
    bd, patched = _import_build123d()
    p = dict(DEFAULTS); p.update({k: v for k, v in overrides.items() if v is not None})
    p["cutouts"] = parse_cutouts(p.get("cutouts"))
    d = derive(p)
    os.makedirs(out_dir, exist_ok=True)
    base = build_base(bd, p, d)
    lid_asm = build_lid_assembly(bd, p, d)
    top = d["base_h"] + p["lid"]
    lid_print = bd.Location((0, 0, top)) * (bd.Rot(180, 0, 0) * lid_asm)
    files, stl_check = {}, {}
    for name, shape in (("base", base), ("lid", lid_print)):
        files[f"{name}.step"] = os.path.join(out_dir, f"{name}.step")
        files[f"{name}.stl"] = os.path.join(out_dir, f"{name}.stl")
        bd.export_step(shape, files[f"{name}.step"])
        bd.export_stl(shape, files[f"{name}.stl"], tolerance=p["stl_tolerance"], angular_tolerance=p["angular_tolerance"])
        stl_check[name] = weld_stl(files[f"{name}.stl"])
        if stl_check[name]["open_edges"]:
            d["warnings"].append(f"{name}.stl has {stl_check[name]['open_edges']} open edges after weld")
    try:
        asm = bd.Compound([base, lid_asm])
        files["enclosure_assembly.step"] = os.path.join(out_dir, "enclosure_assembly.step")
        bd.export_step(asm, files["enclosure_assembly.step"])
    except Exception as e:  # assembly is a convenience; parts are the deliverable
        d["warnings"].append(f"assembly STEP skipped: {type(e).__name__}: {e}")
    bb = lid_print.bounding_box()
    info = {"build123d": bd.__version__, "font_scan_disabled": patched, "params": p, "derived": d,
            "valid": {"base": _valid(base), "lid": _valid(lid_print)}, "stl_check": stl_check,
            "volume_mm3": {"base": round(base.volume, 3), "lid": round(lid_print.volume, 3)},
            "base_bbox_mm": [round(v, 4) for v in base.bounding_box().size.to_tuple()],
            "lid_print_bbox_min_z": round(bb.min.Z, 5), "files": files}
    with open(os.path.join(out_dir, "enclosure_params.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    files["enclosure_params.json"] = os.path.join(out_dir, "enclosure_params.json")
    return info


def _cli(argv=None):
    ap = argparse.ArgumentParser(prog="cad_enclosure_template.py")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--pcb", default=None, help="LxWxT in mm, e.g. 50x30x1.6")
    ap.add_argument("--cutouts", default=None, help="JSON list (inline or .json path) of connector cut-outs")
    for k, v in DEFAULTS.items():
        if k in ("pcb_l", "pcb_w", "pcb_t"):
            continue
        ap.add_argument("--" + k.replace("_", "-"), type=float, default=None)
    a = ap.parse_args(argv)
    kw = {k: getattr(a, k) for k in DEFAULTS if hasattr(a, k)}
    kw["cutouts"] = a.cutouts
    if a.pcb:
        l, w, t = (float(x) for x in a.pcb.lower().split("x"))
        kw.update(pcb_l=l, pcb_w=w, pcb_t=t)
    info = build_enclosure(a.out_dir, **kw)
    print("CAD_ENCLOSURE_TEMPLATE " + json.dumps(info))
    return 0 if all(info["valid"].values()) else 1


if __name__ == "__main__":
    sys.exit(_cli())
