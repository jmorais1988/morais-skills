"""Voxelize a mesh into a game-ready blocky mesh: world-grid-aligned cubes, inner faces culled, coplanar same-colour faces
greedy-merged, optional 1-px-per-colour palette texture (Closest), pivot on the grid; a gate for any voxel mesh; and
pixel-art helpers (snap UVs to the texel grid, Closest interpolation, crisp low-res render settings).

Headless / CLI (prints one line: VOXELIZE <json>):
    blender -b scene.blend --python voxelize.py -- --object Statue --voxel-size 0.1 \
        [--name VOX_Statue --inside parity|nearest --votes 3 --colors --max-colors 64 --no-greedy \
         --pivot BOTTOM_CENTER|CENTER|WORLD --hide-source --palette-png out.png --save out.blend
         --palette-in shared.json|shared.png --palette-out resolved.json|resolved.png --palette-warn 48]
    blender -b scene.blend --python voxelize.py -- --check VOX_Statue --voxel-size 0.1      (gate an existing voxel mesh)
    blender -b scene.blend --python voxelize.py -- --snap-uvs Crate --texels 32 32 [--closest]  (pixel-art texture prep)
Live (Blender:execute_blender_code): set before exec
    VOXELIZE_OPTS = {"object": "Statue", "voxel_size": 0.1, "colors": True}            -> `result` dict
    VOXELIZE_OPTS = {"check": "VOX_Statue", "voxel_size": 0.1}
    VOXELIZE_OPTS = {"snap_uvs": "Crate", "texels": [32, 32], "closest": True}
Without VOXELIZE_OPTS the file only defines the functions (voxelize, occupancy, greedy_quads, check_voxel_mesh,
snap_uvs, set_closest, pixel_art_render).

Inside test: `parity` (default) marches a BVH ray along every voxel-centre column on X, Y and Z and counts crossings;
the 3 axes vote (majority), which tolerates small holes and grazing hits. `nearest` uses the sign of
(centre - nearest surface point) . face normal -- faster to explain, wrong near thin parts/edges; kept for comparison.
Grid: voxel corners sit on integer multiples of voxel_size in WORLD space; the pivot (object origin) is snapped to a grid
point, so local vertices are also exact multiples. Faces are emitted only where a filled voxel touches an empty one, then
merged into maximal rectangles per slice and colour (greedy meshing). Greedy quads create T-junctions (vertices lying on
a neighbour's edge): fine for game engines' flat-shaded blocks, but not watertight for printing/booleans -- use --no-greedy
there (culled, shared-vertex cubes).
Colours: nearest-surface sample of the active colour attribute, else an image texture on the face's material (UV at the
nearest point), else the material Base Color; quantized to <= max_colors; palette image is next-power-of-two x 1 px,
every face's UVs sit on its texel centre.
Shared palette (prop sets): palette_in (JSON list / {"colors"} / PNG) snaps every sampled colour to its nearest entry
(sRGB euclidean) and writes the FULL palette in file order, so every prop gets the same texture, texel indices and
material name PAL_<palette file stem>; max_colors is ignored. palette_out writes the resolved palette (JSON or N x 1
PNG, loadable as palette_in). Result reports palette_max/mean_distance_255 (sample -> assigned colour) and warns
above palette_warn. Note: a padded --palette-png texture read back as palette_in adds its white padding as a colour.
Gate (check_voxel_mesh): all vertices within tol of the grid, all faces axis-aligned, no internal face (a face whose
front voxel is filled -- occupancy recomputed from the mesh itself by 3-axis parity), no duplicate faces.
Limitations: pure-Python greedy loop -- fine up to ~150^3 cells; source must be closed-ish (parity) -- open meshes
voxelize as their closed parts only.
"""
import bpy, bmesh, json, math, os, sys
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

UV_AX = {0: (1, 2), 1: (0, 2), 2: (0, 1)}
PARITY = {0: 1, 1: -1, 2: 1}  # sign of e_u x e_v along the slice axis


# ---------------------------------------------------------------- colour helpers
def _s2l(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _l2s(c):
    c = np.clip(np.asarray(c, float), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def _material_color_source(mat):
    """(image, None) for an image texture feeding the material, else (None, base colour rgb linear)."""
    if mat is None or mat.node_tree is None:
        return None, (0.8, 0.8, 0.8)
    nodes = mat.node_tree.nodes
    imgs = [n for n in nodes if n.type == 'TEX_IMAGE' and n.image]
    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None and bsdf.inputs["Base Color"].is_linked:
        fn = bsdf.inputs["Base Color"].links[0].from_node
        if fn.type == 'TEX_IMAGE' and fn.image:
            return fn.image, None
    if imgs:
        return imgs[0].image, None
    if bsdf is not None:
        return None, tuple(bsdf.inputs["Base Color"].default_value[:3])
    return None, tuple(mat.diffuse_color[:3])


def _eval_world(obj):
    """World-space triangles plus per-triangle colour sources for sampling."""
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    ev = obj.evaluated_get(dg); me = ev.to_mesh(); me.calc_loop_triangles()
    nv, nt = len(me.vertices), len(me.loop_triangles)
    co = np.empty(nv * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    mw = np.array(obj.matrix_world); co = co @ mw[:3, :3].T + mw[:3, 3]
    tv = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get("vertices", tv); tv = tv.reshape(-1, 3)
    tl = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get("loops", tl); tl = tl.reshape(-1, 3)
    tp = np.empty(nt, np.int64); me.loop_triangles.foreach_get("polygon_index", tp)
    info = {"corner_rgb": None, "uv": None, "poly_mat": None, "mats": [s.material for s in obj.material_slots]}
    ca = me.color_attributes.active_color if len(me.color_attributes) else None
    if ca is not None and ca.domain in ('POINT', 'CORNER'):
        c = np.empty(len(ca.data) * 4); ca.data.foreach_get("color", c); c = c.reshape(-1, 4)[:, :3]  # linear
        info["corner_rgb"] = c[tv] if ca.domain == 'POINT' else c[tl]
    else:
        if me.uv_layers.active is not None:
            uv = np.empty(len(me.loops) * 2); me.uv_layers.active.data.foreach_get("uv", uv)
            info["uv"] = uv.reshape(-1, 2)[tl]
        pm = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("material_index", pm)
        info["poly_mat"] = pm[tp]
    ev.to_mesh_clear()
    return co, tv, info


def _sample_colors(tree, co, tv, info, points):
    out = np.zeros((len(points), 3))
    img_cache = {}
    for i, p in enumerate(points):
        loc, _, ti, _ = tree.find_nearest(Vector(p))
        if loc is None:
            out[i] = 0.8; continue
        a, b, c = co[tv[ti]]
        v0, v1, v2 = b - a, c - a, np.array(loc) - a
        d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        wv = (d11 * d20 - d01 * d21) / den if den else 0.0
        ww = (d00 * d21 - d01 * d20) / den if den else 0.0
        bary = np.array([1 - wv - ww, wv, ww])
        if info["corner_rgb"] is not None:
            out[i] = bary @ info["corner_rgb"][ti]; continue
        mi = info["poly_mat"][ti] if info["poly_mat"] is not None else 0
        mat = info["mats"][mi] if mi < len(info["mats"]) else None
        img, base = _material_color_source(mat)
        if img is None or info["uv"] is None:
            out[i] = base; continue
        if img.name not in img_cache:
            w, h = img.size
            px = np.array(img.pixels[:]).reshape(h, w, -1)[:, :, :3]
            if not img.is_float and img.colorspace_settings.name.lower().startswith("srgb"):
                px = _s2l(px)
            img_cache[img.name] = px
        px = img_cache[img.name]; h, w = px.shape[:2]
        uv = bary @ info["uv"][ti]
        out[i] = px[int(uv[1] % 1.0 * h) % h, int(uv[0] % 1.0 * w) % w]
    return out


def _quantize(rgb, max_colors):
    srgb = _l2s(rgb)
    for levels in (32, 16, 8, 6, 4, 3, 2):
        q = np.round(srgb * (levels - 1)) / (levels - 1)
        pal, idx = np.unique(q, axis=0, return_inverse=True)
        if len(pal) <= max_colors:
            return _s2l(pal), idx.ravel()
    return _s2l(pal[:max_colors]), np.minimum(idx.ravel(), max_colors - 1)


def load_palette(path):
    """sRGB palette (N x 3, 0-1) from JSON ([[r,g,b],..] ints 0-255 or floats 0-1, "#rrggbb" strings, or
    {"colors": [...]}) or from an image (unique opaque pixels, top row first, left to right)."""
    path = os.path.abspath(path)
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cols = data.get("colors", []) if isinstance(data, dict) else data
        out = []
        for c in cols:
            if isinstance(c, str):
                h = c.strip().lstrip("#"); out.append([int(h[k:k + 2], 16) / 255 for k in (0, 2, 4)])
            else:
                c = list(c)[:3]
                out.append([v / 255 for v in c] if all(isinstance(v, int) for v in c) else [float(v) for v in c])
        pal = np.array(out, float)
    else:
        img = bpy.data.images.load(path, check_existing=False)
        w, h = img.size; px = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(px)  # byte image: stored sRGB
        bpy.data.images.remove(img)
        px = px.reshape(h, w, 4)[::-1].reshape(-1, 4)
        px = px[px[:, 3] > 0.5, :3]
        _, first = np.unique(np.round(px * 255).astype(int), axis=0, return_index=True)
        pal = px[np.sort(first)].astype(float)
    if not len(pal):
        raise ValueError(f"empty palette: {path}")
    return np.round(np.clip(pal, 0, 1) * 255) / 255


def write_palette(path, pal_srgb):
    """Write the resolved palette: .json -> {"colors": [[r,g,b] 0-255], "count"}; image -> N x 1 PNG (exact colours)."""
    path = os.path.abspath(path); os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    ints = np.round(np.clip(pal_srgb, 0, 1) * 255).astype(int)
    if path.lower().endswith(".json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"colors": ints.tolist(), "count": len(ints), "space": "sRGB 8-bit"}, f)
    else:
        img = bpy.data.images.new("__palette_out__", len(ints), 1, alpha=False)
        px = np.ones((1, len(ints), 4)); px[0, :, :3] = ints / 255
        img.pixels.foreach_set(px.ravel().astype(np.float32))
        img.filepath_raw, img.file_format = path, 'PNG'; img.save(); bpy.data.images.remove(img)
    return path


def _quantize_to(rgb, pal_srgb):
    """Nearest palette entry in sRGB space. Returns (palette linear, labels, distance in 0-255 units per sample)."""
    s = _l2s(rgb)
    d = np.linalg.norm(s[:, None, :] - pal_srgb[None, :, :], axis=2)
    lab = d.argmin(1)
    return _s2l(pal_srgb), lab, d[np.arange(len(s)), lab] * 255


# ---------------------------------------------------------------- occupancy
def _cast_all(tree, origin, d, length, axis, eps):
    hits, o, remaining = [], origin.copy(), length
    while remaining > 0:
        loc, _, _, dist = tree.ray_cast(o, d, remaining)
        if loc is None:
            break
        hits.append(loc[axis])
        o = loc + d * eps; remaining -= dist + eps
    return hits


def occupancy(tree, lo, dims, s, votes=3, inside="parity"):
    """Bool array [nx,ny,nz]: voxel (lo+i)*s .. (lo+i+1)*s is inside. `tree` in the same space as the grid."""
    dims = tuple(int(x) for x in dims)
    cax = [(lo[a] + np.arange(dims[a]) + 0.5) * s for a in range(3)]
    if inside == "nearest":
        occ = np.zeros(dims, bool)
        for i in range(dims[0]):
            for j in range(dims[1]):
                for k in range(dims[2]):
                    c = Vector((cax[0][i], cax[1][j], cax[2][k]))
                    loc, nrm, _, _ = tree.find_nearest(c)
                    occ[i, j, k] = loc is not None and (c - loc).dot(nrm) < 0
        return occ
    axes = [0, 1, 2] if votes >= 3 else [2]
    acc = np.zeros(dims, np.int8)
    jit = (1.3e-4 * s, 2.1e-4 * s)
    for a in axes:
        b, c = [x for x in (0, 1, 2) if x != a]
        d = Vector([1.0 if x == a else 0.0 for x in range(3)])
        for ib in range(dims[b]):
            for ic in range(dims[c]):
                o = [0.0, 0.0, 0.0]
                o[a], o[b], o[c] = (lo[a] - 1) * s, cax[b][ib] + jit[0], cax[c][ic] + jit[1]
                hits = _cast_all(tree, Vector(o), d, (dims[a] + 2) * s, a, 1e-5 * s)
                if not hits:
                    continue
                inside_col = (np.searchsorted(np.array(hits), cax[a]) % 2) == 1
                sl = [0, 0, 0]; sl[a], sl[b], sl[c] = slice(None), ib, ic
                acc[tuple(sl)] += inside_col
    return acc * 2 > len(axes)


# ---------------------------------------------------------------- meshing
def _greedy2d(L):
    H, W = L.shape; done = np.zeros((H, W), bool); rects = []
    for i, j in np.argwhere(L >= 0):
        if done[i, j]:
            continue
        lab = L[i, j]; w = 1
        while j + w < W and L[i, j + w] == lab and not done[i, j + w]:
            w += 1
        h = 1
        while i + h < H and np.all(L[i + h, j:j + w] == lab) and not done[i + h, j:j + w].any():
            h += 1
        done[i:i + h, j:j + w] = True
        rects.append((int(i), int(j), h, w, int(lab)))
    return rects


def greedy_quads(occ, labels, greedy=True):
    """Exposed faces as (axis, sign, plane, u0, v0, du, dv, label) rectangles in grid units."""
    quads = []
    for a in range(3):
        u, v = UV_AX[a]
        ot = np.moveaxis(occ, (a, u, v), (0, 1, 2)); lt = np.moveaxis(labels, (a, u, v), (0, 1, 2))
        pad = np.pad(ot, ((1, 1), (0, 0), (0, 0)))
        for sign in (1, -1):
            faces = ot & ~(pad[2:] if sign > 0 else pad[:-2])
            for k in range(ot.shape[0]):
                m = faces[k]
                if not m.any():
                    continue
                Lk = np.where(m, lt[k], -1)
                rects = _greedy2d(Lk) if greedy else [(int(i), int(j), 1, 1, int(Lk[i, j])) for i, j in np.argwhere(m)]
                plane = k + 1 if sign > 0 else k
                quads += [(a, sign, plane, *r) for r in rects]
    return quads


def build_voxel_mesh(name, quads, lo, pivot, s, n_colors=0):
    vid, verts, faces, labs = {}, [], [], []
    for a, sign, plane, i, j, h, w, lab in quads:
        u, v = UV_AX[a]
        corners = [(i, j), (i + h, j), (i + h, j + w), (i, j + w)]
        if sign * PARITY[a] < 0:
            corners.reverse()
        f = []
        for cu, cv in corners:
            g = [0, 0, 0]; g[a], g[u], g[v] = plane, cu, cv
            key = (g[0] + lo[0] - pivot[0], g[1] + lo[1] - pivot[1], g[2] + lo[2] - pivot[2])
            if key not in vid:
                vid[key] = len(verts); verts.append(key)
            f.append(vid[key])
        faces.append(f); labs.append(lab)
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x * s, y * s, z * s) for x, y, z in verts], [], faces)
    me.update()
    if n_colors:
        wpx = 1 << max(0, (n_colors - 1).bit_length())
        uvl = me.uv_layers.new(name="UVMap")
        uv = np.zeros((len(me.loops), 2))
        ls = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_start", ls)
        for fi, lab in enumerate(labs):
            uv[ls[fi]:ls[fi] + 4] = ((lab + 0.5) / wpx, 0.5)
        uvl.data.foreach_set("uv", uv.ravel().astype(np.float32))
    return me


def palette_material(name, colors_lin, png=None):
    n = len(colors_lin); w = 1 << max(0, (n - 1).bit_length())
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])
    img = bpy.data.images.new(name, w, 1, alpha=False)
    px = np.ones((1, w, 4)); px[0, :n, :3] = _l2s(colors_lin)
    img.pixels.foreach_set(px.ravel().astype(np.float32))
    if png:
        img.filepath_raw, img.file_format = os.path.abspath(png), 'PNG'; img.save()
    else:
        try:
            img.pack()
        except Exception:
            pass
    mat = bpy.data.materials.get("MAT_" + name) or bpy.data.materials.new("MAT_" + name)
    nt = mat.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tx = nt.nodes.new("ShaderNodeTexImage"); tx.image, tx.interpolation = img, 'Closest'
    bs.inputs["Roughness"].default_value = 0.8
    nt.links.new(tx.outputs["Color"], bs.inputs["Base Color"]); nt.links.new(bs.outputs[0], out.inputs["Surface"])
    out.location, bs.location, tx.location = (300, 0), (0, 0), (-350, 0)
    return mat, img


def voxelize(object, voxel_size=0.1, name=None, inside="parity", votes=3, colors=False, max_colors=64, greedy=True,
             pivot="BOTTOM_CENTER", hide_source=False, palette_png=None, save=None, palette_in=None, palette_out=None,
             palette_warn=48.0):
    src = bpy.data.objects[object]; s = float(voxel_size); name = name or "VOX_" + src.name
    shared = load_palette(palette_in) if palette_in else None
    colors = colors or shared is not None; pal_dist = None; warns = []
    co, tv, info = _eval_world(src)
    tree = BVHTree.FromPolygons(co.tolist(), tv.tolist())
    lo = np.floor(co.min(0) / s).astype(int) - 1; hi = np.ceil(co.max(0) / s).astype(int) + 1
    dims = hi - lo
    occ = occupancy(tree, lo, dims, s, votes, inside)
    filled = int(occ.sum())
    if not filled:
        return {"error": "no voxel centre inside the mesh (open mesh or voxel_size too large)", "object": object}
    labels = np.zeros(dims, np.int32); pal = None
    nb = np.pad(occ, 1)
    interior = nb[:-2, 1:-1, 1:-1] & nb[2:, 1:-1, 1:-1] & nb[1:-1, :-2, 1:-1] & nb[1:-1, 2:, 1:-1] & nb[1:-1, 1:-1, :-2] & nb[1:-1, 1:-1, 2:]
    surface = occ & ~interior
    if colors:
        idx = np.argwhere(surface)
        rgb = _sample_colors(tree, co, tv, info, (lo + idx + 0.5) * s)
        if shared is not None:  # labels = palette indices, full palette in the texture -> identical texture per prop
            pal, lab, pal_dist = _quantize_to(rgb, shared)
        else:
            pal, lab = _quantize(rgb, max_colors)
            pal_dist = np.linalg.norm(_l2s(rgb) - _l2s(pal[lab]), axis=1) * 255
        labels[tuple(idx.T)] = lab
        if pal_dist.max() > palette_warn:
            warns.append(f"{int((pal_dist > palette_warn).sum())} surface voxel(s) further than {palette_warn} (0-255 sRGB "
                         f"distance) from their palette colour: max {pal_dist.max():.1f} - extend the palette")
    filled_idx = np.argwhere(occ)
    fmin, fmax = filled_idx.min(0) + lo, filled_idx.max(0) + lo + 1
    if pivot.upper() == "WORLD":
        pv = np.zeros(3, int)
    else:
        pv = np.round((fmin + fmax) / 2).astype(int)
        if pivot.upper() in ("BOTTOM_CENTER", "CENTER_BOTTOM"):
            pv[2] = fmin[2]
    quads = greedy_quads(occ, labels, greedy)
    culled = len(greedy_quads(occ, labels, False)) if greedy else len(quads)
    if name in bpy.data.objects:
        old = bpy.data.objects[name]; om = old.data; bpy.data.objects.remove(old)
        if om and om.users == 0: bpy.data.meshes.remove(om)
    me = build_voxel_mesh(name, quads, lo, pv, s, len(pal) if pal is not None else 0)
    ob = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(ob)
    ob.location = Vector(pv * s)
    img_name = None
    if pal is not None:
        pal_name = "PAL_" + (os.path.splitext(os.path.basename(palette_in))[0] if palette_in else src.name)
        mat, img = palette_material(pal_name, pal, palette_png); me.materials.append(mat); img_name = img.name
        if palette_out:
            palette_out = write_palette(palette_out, _l2s(pal))
    if hide_source:
        src.hide_viewport = src.hide_render = True
    gate = check_voxel_mesh(ob.name, s)
    t = co[tv]; src_vol = float(abs(np.einsum('ij,ij->i', t[:, 0], np.cross(t[:, 1], t[:, 2])).sum()) / 6)
    result = {"object": ob.name, "source": src.name, "voxel_size": s, "grid_dims": dims.tolist(), "filled_voxels": filled,
              "surface_voxels": int(surface.sum()), "voxel_volume_m3": round(filled * s ** 3, 6),
              "source_volume_m3": round(src_vol, 6), "naive_faces": 6 * filled, "culled_faces": culled,
              "greedy_faces": len(quads) if greedy else None, "verts": len(me.vertices), "pivot": pivot,
              "pivot_m": [round(float(x), 6) for x in pv * s], "palette_colors": len(pal) if pal is not None else 0,
              "palette_image": img_name, "inside": inside, "votes": votes, "gate": gate, "pass": gate["pass"]}
    if pal is not None:
        result.update(palette_source=os.path.abspath(palette_in) if palette_in else "quantized",
                      palette_used_colors=int(len(np.unique(labels[surface]))), palette_out=palette_out,
                      palette_max_distance_255=round(float(pal_dist.max()), 2),
                      palette_mean_distance_255=round(float(pal_dist.mean()), 2), warnings=warns)
    if save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(save))
    return result


# ---------------------------------------------------------------- gate
def check_voxel_mesh(object, voxel_size, tol=None):
    """Gate an existing voxel mesh (local coordinates): grid snapping, axis-aligned faces, internal/duplicate faces."""
    ob = bpy.data.objects[object]; me = ob.data; s = float(voxel_size); tol = tol if tol is not None else 1e-4 * s
    nv, nf = len(me.vertices), len(me.polygons)
    co = np.empty(nv * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    q = co / s; off = np.abs(q - np.round(q)) * s
    offv = np.where(off.max(1) > tol)[0]
    nrm = np.empty(nf * 3); me.polygons.foreach_get("normal", nrm); nrm = nrm.reshape(-1, 3)
    polys = [list(p.vertices) for p in me.polygons]
    axis_ok = np.abs(nrm).max(1) > 0.999
    gi = np.round(q).astype(int)
    lo = gi.min(0); dims = gi.max(0) - lo
    tree = BVHTree.FromPolygons(co.tolist(), polys)
    occ = occupancy(tree, lo, np.maximum(dims, 1), s, 3, "parity")
    internal, orphan, dup = [], 0, 0
    seen = set()
    for fi, pv in enumerate(polys):
        key = frozenset(tuple(x) for x in np.round(co[pv] / (tol * 10)).astype(np.int64).tolist())  # by position
        if key in seen:
            dup += 1
        seen.add(key)
        if not axis_ok[fi]:
            continue
        a = int(np.abs(nrm[fi]).argmax()); sign = 1 if nrm[fi][a] > 0 else -1
        u, v = UV_AX[a]; g = gi[pv]
        plane = int(round(float(np.median(g[:, a]))))
        front = plane - lo[a] if sign > 0 else plane - 1 - lo[a]
        back = plane - 1 - lo[a] if sign > 0 else plane - lo[a]
        bad = False; backed = True
        for cu in range(g[:, u].min(), g[:, u].max()):
            for cv in range(g[:, v].min(), g[:, v].max()):
                idx = [0, 0, 0]; idx[u], idx[v] = cu - lo[u], cv - lo[v]
                idx[a] = front
                if 0 <= idx[a] < occ.shape[a] and occ[tuple(idx)]:
                    bad = True
                idx[a] = back
                if not (0 <= idx[a] < occ.shape[a] and occ[tuple(idx)]):
                    backed = False
        if bad:
            internal.append(fi)
        if not backed:
            orphan += 1
    nonman = 0
    bm = bmesh.new(); bm.from_mesh(me); nonman = sum(1 for e in bm.edges if not e.is_manifold); bm.free()
    gates = {"on_grid": len(offv) == 0, "axis_aligned": bool(axis_ok.all()), "no_internal_faces": len(internal) == 0,
             "no_duplicate_faces": dup == 0}
    return {"verts": nv, "faces": nf, "off_grid_verts": int(len(offv)), "max_off_grid_mm": round(float(off.max()) * 1000, 4) if nv else 0,
            "off_grid_sample": offv[:5].tolist(), "non_axis_faces": int((~axis_ok).sum()), "internal_faces": len(internal),
            "internal_sample": internal[:5], "unbacked_faces": orphan, "duplicate_faces": dup,
            "non_manifold_edges_info": nonman, "gates": gates, "pass": all(gates.values())}


# ---------------------------------------------------------------- pixel-art helpers
def snap_uvs(object, texels=(32, 32), uv_map=None):
    """Round every UV to the nearest texel corner of a (w, h) texture. Returns residuals in texels before/after."""
    me = bpy.data.objects[object].data
    uvl = me.uv_layers[uv_map] if uv_map else me.uv_layers.active
    uv = np.empty(len(me.loops) * 2); uvl.data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    wh = np.array(texels, float)
    before = float(np.abs(uv * wh - np.round(uv * wh)).max()) if len(uv) else 0.0
    uv = np.round(uv * wh) / wh
    uvl.data.foreach_set("uv", uv.ravel().astype(np.float32)); me.update()
    after = float(np.abs(uv * wh - np.round(uv * wh)).max()) if len(uv) else 0.0
    return {"object": object, "texels": list(texels), "max_residual_texels_before": round(before, 5),
            "max_residual_texels_after": round(after, 8)}


def set_closest(object):
    """Set every Image Texture node in the object's materials to Closest interpolation."""
    n = 0
    for sl in bpy.data.objects[object].material_slots:
        if sl.material and sl.material.node_tree:
            for nd in sl.material.node_tree.nodes:
                if nd.type == 'TEX_IMAGE':
                    nd.interpolation = 'Closest'; n += 1
    return {"image_nodes_set_closest": n}


def pixel_art_render(scene=None, width=320, height=180, samples=1):
    """Crisp low-res render: exact resolution at 100 %, minimum pixel filter, 1 AA sample, Standard view transform."""
    sc = scene or bpy.context.scene; r = sc.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = width, height, 100
    r.filter_size = r.bl_rna.properties["filter_size"].hard_min
    if hasattr(sc, "eevee"):
        sc.eevee.taa_render_samples = max(samples, sc.eevee.bl_rna.properties["taa_render_samples"].hard_min)
    if hasattr(sc, "cycles"):
        sc.cycles.filter_width = sc.cycles.bl_rna.properties["filter_width"].hard_min
        sc.cycles.samples = max(1, samples)
    sc.view_settings.view_transform = 'Standard'
    return {"resolution": [width, height], "filter_size": r.filter_size,
            "eevee_taa_render_samples": sc.eevee.taa_render_samples if hasattr(sc, "eevee") else None,
            "cycles_filter_width": sc.cycles.filter_width if hasattr(sc, "cycles") else None,
            "view_transform": sc.view_settings.view_transform}


def _run(opts):
    o = dict(opts)
    if "check" in o:
        return check_voxel_mesh(o["check"], o["voxel_size"], o.get("tol"))
    if "snap_uvs" in o:
        r = snap_uvs(o["snap_uvs"], tuple(o.get("texels", (32, 32))), o.get("uv_map"))
        if o.get("closest"):
            r.update(set_closest(o["snap_uvs"]))
        return r
    return voxelize(**o)


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="voxelize.py")
    p.add_argument("--object"); p.add_argument("--check"); p.add_argument("--snap-uvs")
    p.add_argument("--voxel-size", type=float, default=0.1); p.add_argument("--name")
    p.add_argument("--inside", choices=["parity", "nearest"], default="parity"); p.add_argument("--votes", type=int, default=3)
    p.add_argument("--colors", action="store_true"); p.add_argument("--max-colors", type=int, default=64)
    p.add_argument("--no-greedy", action="store_true"); p.add_argument("--pivot", default="BOTTOM_CENTER")
    p.add_argument("--hide-source", action="store_true"); p.add_argument("--palette-png"); p.add_argument("--save")
    p.add_argument("--palette-in"); p.add_argument("--palette-out"); p.add_argument("--palette-warn", type=float, default=48.0)
    p.add_argument("--texels", type=int, nargs=2, default=[32, 32]); p.add_argument("--closest", action="store_true")
    a = p.parse_args(argv)
    if a.check:
        return _run({"check": a.check, "voxel_size": a.voxel_size})
    if a.snap_uvs:
        return _run({"snap_uvs": a.snap_uvs, "texels": a.texels, "closest": a.closest})
    return voxelize(a.object, a.voxel_size, a.name, a.inside, a.votes, a.colors, a.max_colors, not a.no_greedy,
                    a.pivot, a.hide_source, a.palette_png, a.save, a.palette_in, a.palette_out, a.palette_warn)


if "VOXELIZE_OPTS" in globals():
    result = _run(VOXELIZE_OPTS)
    print("VOXELIZE " + json.dumps(result))
elif __name__ == "__main__" and "--" in sys.argv and any(k in sys.argv[sys.argv.index("--") + 1:] for k in ("--object", "--check", "--snap-uvs")):
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print("VOXELIZE " + json.dumps(result))
else:
    result = {"defined": ["voxelize", "occupancy", "greedy_quads", "build_voxel_mesh", "palette_material", "load_palette", "write_palette",
                          "check_voxel_mesh", "snap_uvs", "set_closest", "pixel_art_render"]}
