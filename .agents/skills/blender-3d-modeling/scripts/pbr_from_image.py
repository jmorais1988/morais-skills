"""Turn one albedo image into a PBR map set (basecolor/height/normal/roughness/AO), or convert downloaded normal maps.

Usage (headless, runs inside Blender's Python - needs bpy + numpy, no Pillow; prints one line: PBR_REPORT <json>):
    blender -b --factory-startup --python pbr_from_image.py -- albedo.png --out maps/ [--tileable] [--delight 0.1]
        [--name stone] [--invert-height] [--height-highpass 0.15] [--normal-strength 2.0] [--directx]
        [--ao-strength 1.0] [--roughness-base 0.6] [--roughness-var 0.15] [--cavity-rough 0.1]
        [--height-exr] [--preview]
    blender -b --factory-startup --python pbr_from_image.py -- --convert-normal rock_normal_dx.png --out maps/
    blender -b scan.blend --factory-startup --python pbr_from_image.py -- scan_albedo.png --delight-atlas --ao scan_ao.png
        --out maps/ [--name scan] [--uv-object SCAN | --island-mask islands.png] [--light scan_irradiance.exr]
        [--light-k 1.0] [--ao-k 0.7] [--ao-floor 0.25] [--flatten 0.04] [--flatten-strength 1]
        [--flatten-domain auto|mesh|uv] [--max-gain 4] [--dilate 16] [--save-mask]
    (--light-k: exponent on the normalised baked-light proxy, 0 = ignore --light; the tagged output line of every mode
     is `PBR_REPORT <json>`)
Live session (exec the file, then call):
    derive_maps(src, out_dir, **opts) -> dict        convert_normal(src, dst, flip_green=True) -> dict
    delight_atlas(albedo, ao, out_dir, **opts) -> dict    uv_island_mask(obj, size, out_png=None) -> labels

Outputs in --out:
    <name>_basecolor.png (sRGB)   <name>_height.png  <name>_normal_gl.png | _normal_dx.png  <name>_roughness.png
    <name>_ao.png (data maps written/tagged Non-Color)  [<name>_height.exr 32-bit]  [<name>_preview_{basecolor,normal}.png 2x2]
    Prints one line: PBR_REPORT {json}  (paths, size, seam ratios before/after, options, round-trip errors, warnings)

HEURISTIC WARNING: height, normal, roughness and AO derived from an albedo are guesses from luminance
(bright = high, dark = cavity). They are NOT measured surface data - dark paint reads as a pit, a specular
highlight as a bump. Tune against the reference's highlights/cavities, or use --invert-height when pits are dark-rimmed bumps.

Algorithms (numpy): Gaussian blur via FFT (wrap-around when the texture tiles, mirror-padded otherwise); luminance from
linearized sRGB (Y = .2126R + .7152G + .0722B); --delight divides linear RGB by the blurred luminance (sigma = frac * size);
--tileable blends the image with its half-offset np.roll copy, one axis at a time, smooth mask = rolled copy at the edges,
original in the middle; low frequencies blend linearly, detail is variance-preserving so noise keeps its contrast. LIMITATION: strongly structured textures
(bricks, planks, tiles, text) ghost/double inside the blend band - crop a tiling-friendly region or fix by hand.
Height = luminance minus its blur (sigma = highpass * size), normalised 0..1 on the 0.01/99.99 percentiles.
Normal = normalize(-dH/du*s, -dH/dv*s, 1), s = strength*size/256 (resolution independent), encoded (n+1)/2.
Blender pixel rows run bottom->top, so row+1 is +v (up): OpenGL/Blender green = up; --directx flips green.
AO = 1 - clip(0.5*ao_strength/p99 * sum_k max(0, blur(H, s_k) - H)), s_k = .004/.016/.064 * size.
Roughness = base + var*norm|H - blur(H, .01*size)| + cavity_rough*(1 - AO), clipped 0.02..1.
Seam ratio = mean|last col - first col| / mean|adjacent interior cols| (same for rows); > 1.5 shows a seam when tiled.

ATLAS DELIGHT (--delight-atlas; for UV-unwrapped scan / AI textures, NOT tileable swatches -- --delight above blurs across
UV islands): albedo / max(AO^k, floor) [/ normalised baked-light proxy] -> low-frequency luminance flattening -> gutter
dilation per island. Flattening domain: 'mesh' (with --uv-object in the open .blend) low-passes on the mesh vertex graph
so both sides of a UV seam get the same correction; 'uv' (island mask image only) blurs inside each island separately
(no bleeding, but correction steps at seams). If the light proxy is a DIFFUSE DIRECT+INDIRECT bake it already contains
occlusion: use --ao-k 0. Flattening also removes real low-frequency albedo variation larger than sigma (--flatten x size).
Island mask PNG: id = R*65536 + G*256 + B (uv_island_mask); a binary mask is split into 4-connected components.
"""
import bpy, json, math, sys, time
import numpy as np
from pathlib import Path

HEURISTIC_WARN = "height/normal/roughness/AO derived from albedo luminance (heuristic) - tune against reference highlights/cavities"


# ---------- pixel IO ----------
def load_image(path):
    """-> (HxWxC float32 array in Blender row order (row 0 = bottom), is_linear). Raw values, no colour transform."""
    img = bpy.data.images.load(str(path), check_existing=False)
    try:
        img.colorspace_settings.name = 'Non-Color'  # before first pixel access: no transform on read
        w, h = img.size
        if not w or not h:
            raise RuntimeError(f"could not load image {path}")
        c = len(img.pixels) // (w * h)
        buf = np.empty(w * h * c, np.float32)
        img.pixels.foreach_get(buf)
        linear = img.file_format in ('OPEN_EXR', 'OPEN_EXR_MULTILAYER', 'HDR')
    finally:
        bpy.data.images.remove(img)
    return buf.reshape(h, w, c), linear


def save_image(arr, path, colorspace='Non-Color', exr=False, verify=True):
    """arr HxW or HxWx3/4 in 0..1 (Blender row order). PNG = 8-bit byte buffer, EXR = 32-bit float. Returns max round-trip error."""
    arr = np.asarray(arr, np.float32)
    h, w = arr.shape[:2]
    rgba = np.ones((h, w, 4), np.float32)
    if arr.ndim == 2:
        rgba[..., :3] = arr[..., None]
    else:
        rgba[..., :arr.shape[2]] = arr
    if not exr:
        rgba = np.clip(rgba, 0, 1)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if exr:  # Image.save() on a float buffer may write half floats; save_render with a temp scene forces 32-bit
        img = bpy.data.images.new(path.stem, w, h, alpha=False, float_buffer=True, is_data=True)
        sc = bpy.data.scenes.new("_pbr_tmp_exr")
        try:
            img.pixels.foreach_set(rgba.ravel())
            s = sc.render.image_settings
            s.file_format = 'OPEN_EXR'; s.color_depth = '32'; s.color_mode = 'RGB'; s.exr_codec = 'ZIP'
            img.save_render(str(path), scene=sc)
        finally:
            bpy.data.images.remove(img); bpy.data.scenes.remove(sc)
    else:
        img = bpy.data.images.new(path.stem, w, h, alpha=False, float_buffer=False, is_data=colorspace == 'Non-Color')
        try:
            img.colorspace_settings.name = colorspace
            img.pixels.foreach_set(rgba.ravel())  # byte buffer: stored as round(v*255), no colour transform
            img.filepath_raw = str(path); img.file_format = 'PNG'
            img.save()
        finally:
            bpy.data.images.remove(img)
    if not verify:
        return None
    back, _ = load_image(path)
    expect = rgba[..., :3] if exr else np.round(rgba[..., :3] * 255) / 255
    if back.shape[:2] != (h, w):
        return float('inf')
    return float(np.abs(back[..., :3] - expect).max())


# ---------- math ----------
def srgb_to_lin(c):
    c = np.clip(c, 0, 1); return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def lin_to_srgb(c):
    c = np.clip(c, 0, 1); return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055).astype(np.float32)


def luminance(lin):
    return (lin[..., 0] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 2] * 0.0722).astype(np.float32)


def blur(a, sigma, wrap=True):
    """Gaussian blur (sigma px) via FFT. wrap=True: periodic (tiling textures); False: mirror-padded edges;
    or a (wrap_rows, wrap_cols) pair to mix per axis."""
    if sigma <= 0:
        return a
    h, w = a.shape[:2]
    wy, wx = (wrap, wrap) if isinstance(wrap, bool) else wrap
    x = a if wy and wx else np.pad(a, ((0, 0 if wy else h), (0, 0 if wx else w)) + ((0, 0),) * (a.ndim - 2), mode='symmetric')
    H, W = x.shape[:2]
    g = np.exp(-2 * np.pi ** 2 * sigma ** 2 * (np.fft.fftfreq(H)[:, None] ** 2 + np.fft.rfftfreq(W)[None, :] ** 2))
    if x.ndim == 3:
        g = g[..., None]
    y = np.fft.irfft2(np.fft.rfft2(x, axes=(0, 1)) * g, s=(H, W), axes=(0, 1))
    return np.ascontiguousarray(y[:h, :w]).astype(np.float32)


def seam_ratio(y):
    ic, ir = np.abs(np.diff(y, axis=1)).mean(), np.abs(np.diff(y, axis=0)).mean()
    ec, er = np.abs(y[:, -1] - y[:, 0]).mean(), np.abs(y[-1] - y[0]).mean()
    return {"cols": round(float(ec / (ic + 1e-8)), 3), "rows": round(float(er / (ir + 1e-8)), 3)}


def make_tileable(rgb, blend=0.25):
    """Blend with half-offset roll per axis; mask 0 (rolled copy) at edges -> 1 (original) at blend*size from the edge."""
    out = rgb.astype(np.float32)
    for axis in (1, 0):
        n = out.shape[axis]; i = np.arange(n)
        m = np.clip(np.minimum(i, n - 1 - i) / max(1.0, n * blend), 0, 1)
        m = (m * m * (3 - 2 * m)).astype(np.float32)
        m = m.reshape([n if k == axis else 1 for k in range(out.ndim)])
        # linear blend for tone, variance-kept for detail; 2nd (row) pass keeps the column periodicity from pass 1
        lo = blur(out, 0.02 * max(out.shape[:2]), wrap=(False, axis == 0)); hi = out - lo
        rl, rh = np.roll(lo, n // 2, axis=axis), np.roll(hi, n // 2, axis=axis)
        out = m * lo + (1 - m) * rl + (m * hi + (1 - m) * rh) / np.sqrt(m * m + (1 - m) ** 2)
    return np.clip(out, 0, 1)


def normalize01(a, lo=0.01, hi=99.99):  # tight percentiles: wider clipping flattens bump tops -> flat normals
    p0, p1 = np.percentile(a, [lo, hi])
    return np.clip((a - p0) / max(p1 - p0, 1e-8), 0, 1).astype(np.float32)


def normal_from_height(H, strength=2.0, directx=False, wrap=True):
    """H: HxW 0..1 in Blender row order (row+1 = up). Returns HxWx3 encoded normal (GL unless directx)."""
    if wrap:
        du = (np.roll(H, -1, 1) - np.roll(H, 1, 1)) * 0.5
        dv = (np.roll(H, -1, 0) - np.roll(H, 1, 0)) * 0.5
    else:
        P = np.pad(H, 1, mode='edge')
        du = (P[1:-1, 2:] - P[1:-1, :-2]) * 0.5
        dv = (P[2:, 1:-1] - P[:-2, 1:-1]) * 0.5
    s = strength * max(H.shape) / 256.0
    n = np.dstack([-du * s, -dv * s, np.ones_like(H)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    if directx:
        n[..., 1] *= -1
    return (n * 0.5 + 0.5).astype(np.float32)


# ---------- main entry points ----------
def derive_maps(src, out_dir, name=None, tileable=False, delight=0.0, invert_height=False, height_highpass=0.15,
                normal_strength=2.0, directx=False, ao_strength=1.0, roughness_base=0.6, roughness_var=0.15,
                cavity_rough=0.1, height_exr=False, preview=False, blend=0.25):
    t0 = time.time()
    src, out_dir = Path(src), Path(out_dir)
    name = name or src.stem
    opts = {k: v for k, v in locals().items() if k not in ("src", "out_dir", "t0")}
    warnings = [HEURISTIC_WARN]
    px, is_lin = load_image(src)
    h, w = px.shape[:2]; size = max(w, h)
    lin = px[..., :3] if is_lin else srgb_to_lin(px[..., :3])
    if px.shape[2] < 3:
        lin = np.repeat(lin[..., :1], 3, axis=2)
    seam_before = seam_ratio(lin_to_srgb(luminance(lin)))
    periodic = max(seam_before.values()) <= 1.5

    if delight > 0:
        L = blur(luminance(lin), delight * size, wrap=periodic)
        lin = lin * (float(L.mean()) / np.maximum(L, 1e-4))[..., None]
        clipped = float((lin > 1).any(axis=2).mean())
        if clipped > 0.01:
            warnings.append(f"delight pushed {clipped:.1%} of pixels above 1.0 (clipped) - lower --delight or check highlights")
    base = lin_to_srgb(lin)
    if tileable:
        base = make_tileable(base, blend)
        periodic = True
        warnings.append("tileable blend ghosts/doubles strongly structured patterns (bricks, planks, text) - inspect the preview")
    seam_after = seam_ratio(lin_to_srgb(luminance(srgb_to_lin(base))))
    if max(seam_after.values()) > 1.5:
        warnings.append(f"seam ratio {seam_after} > 1.5: visible seams when tiled" + ("" if tileable else " - use --tileable"))

    Y = luminance(srgb_to_lin(base))
    H = normalize01(Y - blur(Y, height_highpass * size, wrap=periodic)) if height_highpass > 0 else normalize01(Y)
    if invert_height:
        H = 1 - H
    N = normal_from_height(H, normal_strength, directx, wrap=periodic)
    cav = sum(np.maximum(0, blur(H, max(1.0, f * size), wrap=periodic) - H) for f in (0.004, 0.016, 0.064))
    ao = 1 - np.clip(0.5 * ao_strength * cav / (np.percentile(cav, 99) + 1e-6), 0, 1)
    detail = np.abs(H - blur(H, max(1.0, 0.01 * size), wrap=periodic))
    detail = np.clip(detail / (np.percentile(detail, 99) + 1e-6), 0, 1)
    rough = np.clip(roughness_base + roughness_var * detail + cavity_rough * (1 - ao), 0.02, 1)

    paths, rt = {}, {}
    nkey = "normal_dx" if directx else "normal_gl"
    for key, arr, cs in (("basecolor", base, 'sRGB'), ("height", H, 'Non-Color'), (nkey, N, 'Non-Color'),
                         ("roughness", rough, 'Non-Color'), ("ao", ao, 'Non-Color')):
        p = out_dir / f"{name}_{key}.png"
        rt[key] = round(save_image(arr, p, cs), 5); paths[key] = str(p)
    if height_exr:
        p = out_dir / f"{name}_height.exr"
        rt["height_exr"] = save_image(H, p, exr=True); paths["height_exr"] = str(p)
    if preview:
        step = max(1, int(np.ceil(size / 1024)))
        for key, arr, cs in (("preview_basecolor", base, 'sRGB'), ("preview_normal", N, 'Non-Color')):
            p = out_dir / f"{name}_{key}.png"
            save_image(np.tile(arr[::step, ::step], (2, 2, 1)), p, cs, verify=False); paths[key] = str(p)
    bad = {k: v for k, v in rt.items() if v is None or v > 1.01 / 255}
    if bad:
        warnings.append(f"written files do not round-trip: {bad}")
    if w & (w - 1) or h & (h - 1):
        warnings.append(f"size {w}x{h} is not power-of-two (fine for Blender, some engines prefer POT)")
    if float(H.std()) < 0.02:
        warnings.append("height is nearly flat - albedo has little luminance detail")
    return {"src": str(src), "size": [w, h], "input_linear": is_lin, "paths": paths,
            "seam_before": seam_before, "seam_after": seam_after, "height_seam": seam_ratio(H),
            "roundtrip_max_err": rt, "normal_convention": "DirectX (Y-)" if directx else "OpenGL/Blender (Y+)",
            "options": opts, "warnings": warnings, "seconds": round(time.time() - t0, 2)}


def convert_normal(src, dst, flip_green=True):
    """Flip green of an existing normal map (DirectX <-> OpenGL). Exact on 8-bit input (G' = 255 - G)."""
    px, _ = load_image(src)
    rgb = px[..., :3].copy()
    if flip_green:
        rgb[..., 1] = 1 - rgb[..., 1]
    err = save_image(rgb, dst, 'Non-Color')
    warnings = [] if err <= 1.01 / 255 else [f"round-trip error {err:.4f} (16-bit input is quantised to 8-bit)"]
    zm = float(rgb[..., 2].mean())
    if zm < 0.6:
        warnings.append(f"mean blue {zm:.2f} < 0.6 - input may not be a tangent-space normal map")
    return {"src": str(src), "dst": str(dst), "size": [px.shape[1], px.shape[0]], "flip_green": flip_green,
            "roundtrip_max_err": round(err, 5), "warnings": warnings}


# ---------- UV-atlas delighting (scan / AI textures) ----------
def connected_components(mask):
    """mask HxW bool -> int labels (0 = outside, 1..n), 4-connected; min-label propagation + pointer jumping."""
    h, w = mask.shape
    lab = np.where(mask, np.arange(1, h * w + 1, dtype=np.int64).reshape(h, w), 0)
    big = h * w + 2
    for _ in range(h * w):
        L = np.where(mask, lab, big); m = L.copy()
        m[1:] = np.minimum(m[1:], L[:-1]); m[:-1] = np.minimum(m[:-1], L[1:])
        m[:, 1:] = np.minimum(m[:, 1:], L[:, :-1]); m[:, :-1] = np.minimum(m[:, :-1], L[:, 1:])
        flat = np.where(mask, m, 0).ravel()
        jump = np.where(flat > 0, flat[np.maximum(flat - 1, 0)], 0)  # label of the pixel my label points at
        new = np.where(mask, np.minimum(flat, jump).reshape(h, w), 0)
        if np.array_equal(new, lab):
            break
        lab = new
    _, inv = np.unique(lab, return_inverse=True)
    return inv.reshape(h, w) + (0 if (~mask).any() else 1)


def labels_from_mask(px):
    """Island mask image -> labels. Unique non-black colours = islands (uv_island_mask output); a binary mask is split
    into 4-connected components."""
    rgb = np.round(np.clip(px[..., :3], 0, 1) * 255).astype(np.int64)
    key = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
    if len(np.unique(key[key > 0])) <= 1:
        return connected_components(key > 0)
    _, inv = np.unique(key, return_inverse=True)
    return inv.reshape(key.shape) + (0 if (key == 0).any() else 1)


def uv_island_mask(obj, size, out_path=None, grow_px=1):
    """Rasterise the active UV map's islands of a mesh object -> int labels HxW (Blender row order, 0 = gutter).
    size int or (w, h). Texel centres inside a UV triangle get its island id; then grow_px of conservative growth into
    the gutter (never over another island). Optional PNG with exact id encoding (id = R*65536 + G*256 + B)."""
    w, h = (size, size) if isinstance(size, int) else size
    lab = _raster_uv(obj, w, h)[0]
    for _ in range(grow_px):
        lab = _grow_labels(lab)
    if out_path:
        enc = np.dstack([(lab >> 16) & 255, (lab >> 8) & 255, lab & 255]).astype(np.float32) / 255
        save_image(enc, out_path, 'Non-Color')
    return lab


def _raster_uv(obj, w, h):
    """-> (island labels HxW, loop-triangle index HxW (-1 gutter), barycentrics HxWx3, tri vertex ids Tx3, world co Vx3).
    Texel centres (Blender row order) inside each UV triangle. Python loop per triangle: ~1 s per 20k tris."""
    from bpy_extras import mesh_utils
    me = obj.data
    pid = np.zeros(len(me.polygons), np.int64)
    for i, isl in enumerate(mesh_utils.mesh_linked_uv_islands(me)):
        pid[list(isl)] = i + 1
    uv = np.empty(len(me.loops) * 2, np.float64); me.uv_layers.active.data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    me.calc_loop_triangles(); LT = me.loop_triangles; nt = len(LT)
    tv = np.empty(nt * 3, np.int64); LT.foreach_get("vertices", tv); tv = tv.reshape(-1, 3)
    tl = np.empty(nt * 3, np.int64); LT.foreach_get("loops", tl); tl = tl.reshape(-1, 3)
    tp = np.empty(nt, np.int64); LT.foreach_get("polygon_index", tp)
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co)
    M = np.array(obj.matrix_world); co = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
    lab = np.zeros((h, w), np.int64); tri = np.full((h, w), -1, np.int64); bary = np.zeros((h, w, 3), np.float32)
    for t in range(nt):
        P = uv[tl[t]] * (w, h) - 0.5
        x0, y0 = np.maximum(np.floor(P.min(0)).astype(int), 0); x1, y1 = np.minimum(np.ceil(P.max(0)).astype(int), (w - 1, h - 1))
        if x1 < x0 or y1 < y0:
            continue
        X, Y = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        (ax, ay), (bx, by), (cx, cy) = P
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(area) < 1e-12:
            continue
        wc = ((bx - ax) * (Y - ay) - (by - ay) * (X - ax)) / area  # weight of vertex c
        wa = ((cx - bx) * (Y - by) - (cy - by) * (X - bx)) / area
        wb = ((ax - cx) * (Y - cy) - (ay - cy) * (X - cx)) / area
        ins = (wa >= -1e-9) & (wb >= -1e-9) & (wc >= -1e-9)
        sl = (slice(y0, y1 + 1), slice(x0, x1 + 1))
        lab[sl][ins] = pid[tp[t]]; tri[sl][ins] = t; bary[sl][ins] = np.stack([wa, wb, wc], -1)[ins]
    return lab, tri, bary, tv, co


def _mesh_lowpass(Y, tri, bary, tv, co, sigma_px):
    """Seam-continuous low-pass: splat texel luminance to mesh vertices (barycentric weights), diffuse numerator and
    weight over the vertex graph (normalised convolution, Jacobi neighbour averaging, sigma_3d = sigma_px * texel size
    in world units, iterations = 2 (sigma_3d / mean edge)^2), interpolate back. Both sides of a UV seam read the same
    vertices, so the result has no step at island borders."""
    ins = tri >= 0; ti = tri[ins]; B = bary[ins].astype(np.float64); y = Y[ins].astype(np.float64)
    V = tv[ti]; nv = len(co)
    num = sum(np.bincount(V[:, k], weights=B[:, k] * y, minlength=nv) for k in range(3))
    den = sum(np.bincount(V[:, k], weights=B[:, k], minlength=nv) for k in range(3))
    A = co[tv]; area3 = 0.5 * np.linalg.norm(np.cross(A[:, 1] - A[:, 0], A[:, 2] - A[:, 0]), axis=1).sum()
    texel = math.sqrt(area3 / max(int(ins.sum()), 1))
    E = np.unique(np.sort(np.concatenate([tv[:, [0, 1]], tv[:, [1, 2]], tv[:, [2, 0]]]), axis=1), axis=0)
    elen = float(np.linalg.norm(co[E[:, 0]] - co[E[:, 1]], axis=1).mean())
    s3 = sigma_px * texel; iters = int(min(5000, max(1, round(2 * (s3 / max(elen, 1e-12)) ** 2))))
    deg = np.bincount(E.ravel(), minlength=nv).astype(np.float64)
    for _ in range(iters):
        num = (num + np.bincount(E[:, 0], weights=num[E[:, 1]], minlength=nv) + np.bincount(E[:, 1], weights=num[E[:, 0]], minlength=nv)) / (1 + deg)
        den = (den + np.bincount(E[:, 0], weights=den[E[:, 1]], minlength=nv) + np.bincount(E[:, 1], weights=den[E[:, 0]], minlength=nv)) / (1 + deg)
    val = num / np.maximum(den, 1e-12)
    low = np.zeros(Y.shape, np.float32); low[ins] = (B * val[V]).sum(1)
    return low, {"iters": iters, "sigma_3d": round(s3, 6), "mean_edge": round(elen, 6), "texel_3d": round(texel, 6)}


def _grow_labels(lab, img=None):
    """One step of island-aware growth into label-0 pixels: each gutter pixel adopts the smallest neighbouring island
    id and (if img given) the mean colour of the neighbours of that island only."""
    h, w = lab.shape; big = np.iinfo(np.int64).max
    nb_l, nb_c = [], []
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        L = np.zeros_like(lab); sl_t = (slice(max(dy, 0), h + min(dy, 0)), slice(max(dx, 0), w + min(dx, 0)))
        sl_s = (slice(max(-dy, 0), h + min(-dy, 0)), slice(max(-dx, 0), w + min(-dx, 0)))
        L[sl_t] = lab[sl_s]; nb_l.append(L)
        if img is not None:
            C = np.zeros_like(img); C[sl_t] = img[sl_s]; nb_c.append(C)
    NL = np.stack(nb_l)
    own = np.where(NL > 0, NL, big).min(0)
    grow = (lab == 0) & (own != big)
    out = lab.copy(); out[grow] = own[grow]
    if img is None:
        return out
    sel = (NL == own[None]) & (NL > 0)
    cnt = sel.sum(0); acc = sum(nb_c[k] * sel[k][..., None] for k in range(4))
    newimg = img.copy(); newimg[grow] = acc[grow] / cnt[grow][:, None]
    return out, newimg


def delight_atlas(src, ao, out_dir, name=None, island_mask=None, uv_object=None, light=None, ao_k=0.7, ao_floor=0.25,
                  light_k=1.0, light_floor=0.05, flatten=0.08, flatten_strength=1.0, max_gain=4.0, dilate=16,
                  min_island_px=16, save_mask=False, flatten_domain="auto"):
    """Delight a UV-atlas albedo (scan / AI texture) using baked data, island by island.
    1 lin /= max(AO^ao_k, ao_floor)                        (AO baked from geometry on the same UVs)
    2 lin /= max((light/median)^light_k, light_floor)      (optional baked lighting proxy, e.g. DIFFUSE DIRECT+INDIRECT)
    3 per island: low = normalised convolution of luminance inside the island (sigma = flatten * size), gain =
      clip((median_Y / low)^flatten_strength, 1/max_gain, max_gain)  -- never blurs across island borders
    4 gutter filled by island-aware dilation (dilate px), island texels untouched.
    Returns report dict; writes <name>_delit.png (sRGB) [+ <name>_islands.png]."""
    t0 = time.time(); src, out_dir = Path(src), Path(out_dir); name = name or src.stem
    opts = {k: v for k, v in locals().items() if k not in ("src", "out_dir", "t0")}
    warnings = []
    px, is_lin = load_image(src); h, w = px.shape[:2]; size = max(w, h)
    lin = px[..., :3] if is_lin else srgb_to_lin(px[..., :3])
    paths = {}; raster = None
    domain = ("mesh" if uv_object else "uv") if flatten_domain == "auto" else flatten_domain
    if domain == "mesh" and not uv_object:
        raise ValueError("flatten_domain='mesh' needs uv_object (a mesh in the open .blend with the atlas UVs)")
    if uv_object:
        raster = _raster_uv(bpy.data.objects[uv_object], w, h); labels = _grow_labels(raster[0])
        if save_mask:
            mp = out_dir / f"{name}_islands.png"; paths["islands"] = str(mp)
            save_image(np.dstack([(labels >> 16) & 255, (labels >> 8) & 255, labels & 255]).astype(np.float32) / 255, mp, 'Non-Color')
    elif island_mask:
        labels = labels_from_mask(load_image(island_mask)[0])
    else:
        labels = np.ones((h, w), np.int64)
        if flatten > 0:
            warnings.append("no island mask: flattening treats the whole atlas as one island (blurs across UV borders)")
    if labels.shape != (h, w):
        raise ValueError(f"island mask {labels.shape[::-1]} != albedo {w}x{h}")
    inside = labels > 0; n_isl = int(labels.max())
    A, _ = load_image(ao)
    if A.shape[:2] != (h, w):
        raise ValueError("AO size differs from albedo")
    out = lin / np.maximum(np.clip(A[..., 0], 0, 1) ** ao_k, ao_floor)[..., None]
    if light:
        Lp, _ = load_image(light)
        Lp = luminance(Lp[..., :3]) if Lp.shape[2] >= 3 else Lp[..., 0]
        med = float(np.median(Lp[inside])) or 1.0
        out = out / np.maximum((np.maximum(Lp, 0) / med) ** light_k, light_floor)[..., None]
    Y = luminance(out); target = float(np.median(Y[inside]))
    gain = np.ones((h, w), np.float32); cov_b, cov_a, wsum = 0.0, 0.0, 0; mesh_info = None
    if flatten > 0 and flatten_strength > 0 and domain == "mesh":
        low, mesh_info = _mesh_lowpass(Y, raster[1], raster[2], raster[3], raster[4], flatten * size)
        tin = raster[1] >= 0; lv = np.maximum(low[tin], 1e-6)
        g = np.clip((target / lv) ** flatten_strength, 1 / max_gain, max_gain).astype(np.float32)
        gain[tin] = g; out = out * gain[..., None]
        cov_b, cov_a, wsum = float(lv.std() / lv.mean()), float((lv * g).std() / (lv * g).mean()), 1
    elif flatten > 0 and flatten_strength > 0 and n_isl:
        sig = flatten * size; pad = int(3 * sig) + 1
        ys, xs = np.nonzero(inside); order = np.argsort(labels[ys, xs], kind="stable")
        ys, xs = ys[order], xs[order]; bounds = np.searchsorted(labels[ys, xs], np.arange(1, n_isl + 2))
        for i in range(n_isl):
            yy, xx = ys[bounds[i]:bounds[i + 1]], xs[bounds[i]:bounds[i + 1]]
            if len(yy) < min_island_px:
                continue
            y0, y1 = max(yy.min() - pad, 0), min(yy.max() + pad + 1, h); x0, x1 = max(xx.min() - pad, 0), min(xx.max() + pad + 1, w)
            m = (labels[y0:y1, x0:x1] == i + 1).astype(np.float32)
            low = blur(Y[y0:y1, x0:x1] * m, sig, wrap=False) / np.maximum(blur(m, sig, wrap=False), 1e-6)
            low = np.maximum(low, 1e-6)
            g = np.clip((target / low) ** flatten_strength, 1 / max_gain, max_gain).astype(np.float32)
            sel = m > 0; gain[y0:y1, x0:x1][sel] = g[sel]
            lv = low[sel]; cov_b += float(lv.std() / lv.mean()) * len(lv); cov_a += float((lv * g[sel]).std() / (lv * g[sel]).mean()) * len(lv); wsum += len(lv)
        out = out * gain[..., None]
    clipped = float((out[inside] > 1).any(axis=1).mean()) if inside.any() else 0.0
    if clipped > 0.01:
        warnings.append(f"{clipped:.1%} of island texels above 1.0 after delighting (clipped): lower ao_k / max_gain")
    base = lin_to_srgb(out) * inside[..., None]
    lab = labels.copy()
    for _ in range(dilate):
        lab2, base = _grow_labels(lab, base)
        if np.array_equal(lab2, lab):
            break
        lab = lab2
    p = out_dir / f"{name}_delit.png"; rt = save_image(base, p, 'sRGB'); paths["delit"] = str(p)
    if ao_k > 0 and float((A[..., 0][inside] < ao_floor ** (1 / ao_k)).mean()) > 0.05:
        warnings.append("over 5% of texels hit ao_floor: deep cavities stay dark (paint or lower ao_k)")
    return {"src": str(src), "size": [w, h], "islands": n_isl, "paths": paths, "gain_p1_p50_p99": [round(float(v), 3) for v in np.percentile(gain[inside], [1, 50, 99])],
            "lowfreq_cov_before": round(cov_b / wsum, 4) if wsum else None, "lowfreq_cov_after": round(cov_a / wsum, 4) if wsum else None,
            "clipped_frac": round(clipped, 4), "roundtrip_max_err": round(rt, 5), "flatten_domain": domain,
            "mesh_lowpass": mesh_info, "options": opts, "warnings": warnings,
            "seconds": round(time.time() - t0, 2)}


def _swap_suffix(stem):
    for a, b in (("_dx", "_gl"), ("_gl", "_dx"), ("_DX", "_GL"), ("_GL", "_DX")):
        if stem.endswith(a):
            return stem[:-len(a)] + b
    return stem + "_flipY"


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="pbr_from_image.py")
    ap.add_argument("albedo", nargs="?")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name")
    ap.add_argument("--tileable", action="store_true")
    ap.add_argument("--delight", type=float, default=0.0, help="sigma as fraction of image size, 0 = off")
    ap.add_argument("--invert-height", action="store_true")
    ap.add_argument("--height-highpass", type=float, default=0.15)
    ap.add_argument("--normal-strength", type=float, default=2.0)
    ap.add_argument("--directx", action="store_true")
    ap.add_argument("--ao-strength", type=float, default=1.0)
    ap.add_argument("--roughness-base", type=float, default=0.6)
    ap.add_argument("--roughness-var", type=float, default=0.15)
    ap.add_argument("--cavity-rough", type=float, default=0.1)
    ap.add_argument("--height-exr", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--convert-normal", metavar="IN_PNG")
    ap.add_argument("--delight-atlas", action="store_true", help="UV-atlas delight mode (needs --ao)")
    ap.add_argument("--ao"); ap.add_argument("--island-mask"); ap.add_argument("--uv-object"); ap.add_argument("--light")
    ap.add_argument("--ao-k", type=float, default=0.7); ap.add_argument("--ao-floor", type=float, default=0.25)
    ap.add_argument("--light-k", type=float, default=1.0); ap.add_argument("--flatten", type=float, default=0.08)
    ap.add_argument("--flatten-strength", type=float, default=1.0); ap.add_argument("--max-gain", type=float, default=4.0)
    ap.add_argument("--dilate", type=int, default=16); ap.add_argument("--save-mask", action="store_true")
    ap.add_argument("--flatten-domain", choices=("auto", "mesh", "uv"), default="auto")
    a = ap.parse_args(argv)
    if a.delight_atlas:
        if not (a.albedo and a.ao):
            ap.error("--delight-atlas needs the albedo image and --ao")
        rep = delight_atlas(a.albedo, a.ao, a.out, name=a.name, island_mask=a.island_mask, uv_object=a.uv_object,
                            light=a.light, ao_k=a.ao_k, ao_floor=a.ao_floor, light_k=a.light_k, flatten=a.flatten,
                            flatten_strength=a.flatten_strength, max_gain=a.max_gain, dilate=a.dilate, save_mask=a.save_mask,
                            flatten_domain=a.flatten_domain)
    elif a.convert_normal:
        src = Path(a.convert_normal)
        rep = convert_normal(src, Path(a.out) / f"{_swap_suffix(src.stem)}.png")
    else:
        if not a.albedo:
            ap.error("albedo image required (or --convert-normal)")
        rep = derive_maps(a.albedo, a.out, name=a.name, tileable=a.tileable, delight=a.delight,
                          invert_height=a.invert_height, height_highpass=a.height_highpass,
                          normal_strength=a.normal_strength, directx=a.directx, ao_strength=a.ao_strength,
                          roughness_base=a.roughness_base, roughness_var=a.roughness_var,
                          cavity_rough=a.cavity_rough, height_exr=a.height_exr, preview=a.preview)
    print("PBR_REPORT " + json.dumps(rep))
    return rep


if __name__ == "__main__" and "--" in sys.argv:
    main(sys.argv[sys.argv.index("--") + 1:])
