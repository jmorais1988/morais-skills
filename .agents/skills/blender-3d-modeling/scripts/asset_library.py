"""Kitbash / modular-kit library tools: mark parts as catalogued assets, audit a kit for consistency,
place linked collection instances, and snap parts together through SOCKET_* empties.

Headless / CLI (prints one line: `ASSET_LIBRARY_RESULT {json}`):
    blender -b kit.blend --python asset_library.py -- mark --names Wall_A,Floor_A [--id-type OBJECT|COLLECTION] \
        --catalog Kit/SciFi/Panels [--tags metal,wall --description "..." --author "..." --no-preview --blend-dir DIR] --save
    blender -b kit.blend --python asset_library.py -- audit --collection Kit [--texture-px 2048 --texel-target 512 \
        --texel-tolerance 0.25 --grid 0.5 --grid-axes XYZ --pivot BOTTOM_CENTER|CENTER|CORNER|NONE (alias CENTER_BOTTOM) \
        --palette M_Metal,M_Rubber --prefix SM --require-sockets --allow-boundary]
    blender -b scene.blend --python asset_library.py -- place --library //kit.blend --collection Kit_Wall \
        [--location 0,0,0 --rotation-deg 0,0,90 --append --name Wall_01] --save
    blender -b scene.blend --python asset_library.py -- snap --part Wall_01 --part-socket SOCKET_L \
        --target-socket Wall_00/SOCKET_R [--no-flip] --save
  `mark` and `place`/`snap` change the file: pass --save (or --save-as PATH) or the change is lost when Blender exits.
Live (Blender:execute_blender_code): set before exec
    ASSET_OPTS = {"op": "audit", "collection": "Kit", "grid": 0.5}   # op = mark | audit | place | snap, rest = kwargs
    -> `result` dict. Without ASSET_OPTS the file only defines the functions below.

Functions
  mark_assets(names, *, id_type, catalog, tags, description, author, preview, blend_dir)
      asset_mark() + metadata; catalog ensured in blender_assets.cats.txt next to the .blend (VERSION 1 header,
      `UUID:path:simple_name`, existing lines preserved, existing path reused); asset_data.catalog_id assigned;
      asset_generate_preview() and the resulting preview pixels are checked (status reported, never assumed).
  kit_audit(collection, *, texture_px, texel_target_px_per_m, grid, pivot, material_palette, ...)
      parts = MESH objects of the collection whose parent is not a mesh of the kit. Per part: unapplied scale/rotation,
      origin vs pivot, dims vs grid multiples, tris, ngons, non-manifold edges (boundary / wire / >2 faces), materials vs
      palette, texel density sqrt(UV area / world area) * texture_px (outlier beyond +-tolerance of target or kit median),
      missing UV map, SOCKET_* empties (descendants), name prefix consistency. Evaluated (post-modifier) mesh.
  place_instance(library_blend, collection_name, *, location, rotation_euler, link, name)
      link (or append, reusing a previously appended copy) a collection and add a collection-instance Empty.
      An already-loaded Library / linked collection is reused -> one Library datablock however many calls.
  snap_to_socket(part_name, part_socket, target_socket, *, flip=True)
      moves/rotates the part (mesh object or collection-instance Empty) so its socket lands on the target socket;
      flip=True: part socket +Z = -target +Z and +Y aligned (180 deg about socket Y); flip=False: frames equal.
      target_socket = "SceneObjectName" | "OwnerObject/SOCKET_name" | (owner, socket). Sockets inside instanced
      collections are resolved through the instance matrix and the collection's instance_offset.
      Returns measured residuals (position error, Z dot, Y dot) after the move.
"""
import bpy, os, re, sys, json, math, uuid
from mathutils import Vector, Matrix

TAG = "ASSET_LIBRARY_RESULT"
CATS_FILE = "blender_assets.cats.txt"
CATS_HEADER = ("# This is an Asset Catalog Definition file for Blender.\n#\n"
               "# Empty lines and lines starting with `#` will be ignored.\n"
               "# The first non-ignored line should be the version indicator.\n"
               "# Other lines are of the format \"UUID:catalog/path/for/assets:simple catalog name\"\n\nVERSION 1\n\n")
ID_TYPES = {"OBJECT": "objects", "COLLECTION": "collections", "MATERIAL": "materials",
            "NODETREE": "node_groups", "WORLD": "worlds", "ACTION": "actions"}


# ------------------------------------------------------------------ catalogs
def normalize_catalog_path(path):
    """Blender-style: backslash -> '/', trim components, drop empty components (no leading/trailing/double '/')."""
    parts = [p.strip() for p in str(path).replace("\\", "/").split("/")]
    return "/".join(p for p in parts if p)


def read_catalogs(cats_path):
    """-> {"version": int|None, "entries": [(uuid, path, simple)], "errors": [...]} ; strict parse of a cats file."""
    out = {"version": None, "entries": [], "errors": []}
    if not os.path.isfile(cats_path):
        return out
    with open(cats_path, "r", encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if out["version"] is None:
                m = re.match(r"^VERSION\s+(\d+)$", line)
                if not m:
                    out["errors"].append(f"line {n}: first non-comment line is not VERSION")
                    out["version"] = -1
                    continue
                out["version"] = int(m.group(1)); continue
            bits = line.split(":", 2)
            if len(bits) < 2:
                out["errors"].append(f"line {n}: malformed {line!r}"); continue
            try:
                uid = str(uuid.UUID(bits[0]))
            except ValueError:
                out["errors"].append(f"line {n}: invalid UUID {bits[0]!r}"); continue
            out["entries"].append((uid, normalize_catalog_path(bits[1]), bits[2] if len(bits) > 2 else ""))
    return out


def ensure_catalog(cats_dir, catalog_path):
    """Return (uuid, created, cats_file). Appends one line if the path is new; never rewrites existing lines."""
    path = normalize_catalog_path(catalog_path)
    if not path:
        raise ValueError("empty catalog path")
    cats = os.path.join(cats_dir, CATS_FILE)
    parsed = read_catalogs(cats)
    for uid, p, _ in parsed["entries"]:
        if p == path:
            return uid, False, cats
    uid = str(uuid.uuid4())
    simple = path.replace("/", "-")
    if not os.path.isfile(cats):
        text = CATS_HEADER
    else:
        with open(cats, "r", encoding="utf-8") as fh:
            text = fh.read()
        if parsed["version"] is None:  # file with only comments -> add header line
            text += ("" if text.endswith("\n") or not text else "\n") + "VERSION 1\n\n"
        elif not text.endswith("\n"):
            text += "\n"
    text += f"{uid}:{path}:{simple}\n"
    with open(cats, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return uid, True, cats


# ------------------------------------------------------------------ mark
def _preview_state(idb):
    p = idb.preview
    if p is None:
        return {"status": "none"}
    w, h = p.image_size
    if not w or not h:
        return {"status": "empty", "size": [w, h]}
    import numpy as np
    px = np.empty(w * h * 4, dtype=np.float32); p.image_pixels_float.foreach_get(px)
    rgba = px.reshape(-1, 4)
    lit = int(np.count_nonzero(rgba[:, 3] > 0.0))
    return {"status": "generated" if lit else "blank", "size": [w, h], "opaque_px": lit,
            "rgb_std": round(float(rgba[:, :3].std()), 4)}


def mark_assets(names, *, id_type='OBJECT', catalog="Kit/SciFi/Panels", tags=(), description="", author="",
                preview=True, blend_dir=None):
    if isinstance(names, str):
        names = [n for n in names.split(",") if n]
    coll_name = ID_TYPES.get(str(id_type).upper())
    if not coll_name:
        raise ValueError(f"id_type {id_type!r} not in {sorted(ID_TYPES)}")
    data = getattr(bpy.data, coll_name)
    res = {"id_type": id_type.upper(), "catalog": normalize_catalog_path(catalog) if catalog else None, "marked": [],
           "missing": [], "warnings": [], "blender": bpy.app.version_string}
    cat_id = None
    if catalog:
        d = blend_dir or (os.path.dirname(bpy.data.filepath) if bpy.data.filepath else None)
        if d:
            d = bpy.path.abspath(d)
            os.makedirs(d, exist_ok=True)
            cat_id, created, cats = ensure_catalog(d, catalog)
            res.update({"catalog_id": cat_id, "catalog_created": created, "cats_file": cats})
            if bpy.data.filepath and os.path.normcase(os.path.abspath(d)) != os.path.normcase(os.path.dirname(os.path.abspath(bpy.data.filepath))):
                res["warnings"].append("blend_dir is not the .blend's folder: Blender only reads the cats file at the asset library root")
        else:
            res["warnings"].append("file never saved and no blend_dir: catalog not written, catalog_id left unset (save first)")
    for n in names:
        idb = data.get(n)
        if idb is None:
            res["missing"].append(n); continue
        if idb.library is not None:
            res["warnings"].append(f"{n}: linked datablock, cannot be marked in this file"); continue
        idb.asset_mark()
        ad = idb.asset_data
        if cat_id:
            ad.catalog_id = cat_id
        if description:
            ad.description = description
        if author:
            ad.author = author
        for t in ([x for x in tags.split(",") if x] if isinstance(tags, str) else tags):
            ad.tags.new(t, skip_if_exists=True)
        entry = {"name": idb.name, "catalog_id": ad.catalog_id, "tags": [t.name for t in ad.tags]}
        if preview:
            try:
                idb.asset_generate_preview()
                entry["preview"] = _preview_state(idb)
            except Exception as e:  # RuntimeError when no GPU/context for preview rendering
                entry["preview"] = {"status": "unavailable", "error": f"{type(e).__name__}: {e}"}
        res["marked"].append(entry)
    if res["missing"]:
        res["warnings"].append(f"not found in bpy.data.{coll_name}: {res['missing']}")
    return res


# ------------------------------------------------------------------ audit
def _mesh_arrays(me):
    import numpy as np
    nv, nl, np_ = len(me.vertices), len(me.loops), len(me.polygons)
    co = np.empty(nv * 3, dtype=np.float64); me.vertices.foreach_get("co", co)
    lv = np.empty(nl, dtype=np.int64); me.loops.foreach_get("vertex_index", lv)
    le = np.empty(nl, dtype=np.int64); me.loops.foreach_get("edge_index", le)
    ls = np.empty(np_, dtype=np.int64); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(np_, dtype=np.int64); me.polygons.foreach_get("loop_total", lt)
    return co.reshape(-1, 3), lv, le, ls, lt


def _part_stats(obj, dg, texture_px):
    import numpy as np
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        co, lv, le, ls, lt = _mesh_arrays(me)
        nl = len(lv)
        st = {"verts": len(co), "faces": len(lt), "tris": int((lt - 2).clip(min=0).sum()), "ngons": int((lt > 4).sum())}
        ec = np.bincount(le, minlength=len(me.edges)) if len(me.edges) else np.zeros(0, dtype=np.int64)
        st["boundary_edges"] = int((ec == 1).sum()); st["wire_edges"] = int((ec == 0).sum())
        st["multi_face_edges"] = int((ec > 2).sum())
        st["bbox_local"] = [co.min(0).tolist(), co.max(0).tolist()] if len(co) else None
        uvl = me.uv_layers.active
        st["uv_map"] = uvl.name if uvl else None
        st["uv_maps"] = len(me.uv_layers)
        if nl and len(lt):
            nxt = np.arange(nl) + 1
            nxt[ls + lt - 1] = ls
            pid = np.repeat(np.arange(len(lt)), lt)
            mw = np.array(obj.matrix_world, dtype=np.float64)
            wco = co @ mw[:3, :3].T + mw[:3, 3]
            p = wco[lv]; q = p[nxt]
            cr = np.cross(p, q)
            nvec = np.stack([np.bincount(pid, cr[:, k], minlength=len(lt)) for k in range(3)], 1)
            area3d = float(np.linalg.norm(nvec, axis=1).sum() / 2)
            st["world_area_m2"] = round(area3d, 6)
            if uvl:
                uv = np.empty(nl * 2, dtype=np.float64)
                try:
                    uvl.uv.foreach_get("vector", uv)
                except Exception:
                    uvl.data.foreach_get("uv", uv)
                uv = uv.reshape(-1, 2)
                c2 = uv[:, 0] * uv[nxt, 1] - uv[nxt, 0] * uv[:, 1]
                uv_area = float(np.abs(np.bincount(pid, c2, minlength=len(lt))).sum() / 2)
                st["uv_area"] = round(uv_area, 6)
                st["texel_px_per_m"] = round(math.sqrt(uv_area / area3d) * texture_px, 2) if area3d > 1e-12 else None
        return st
    finally:
        ev.to_mesh_clear()


PIVOT_ALIASES = {"CENTER_BOTTOM": "BOTTOM_CENTER"}  # canonical spelling is BOTTOM_CENTER (same as tile_sockets.py)


def kit_audit(collection, *, texture_px=2048, texel_target_px_per_m=None, texel_tolerance=0.25, grid=None,
              grid_axes="XYZ", grid_tol=1e-3, pivot='BOTTOM_CENTER', pivot_tol=1e-3, material_palette=None,
              prefix=None, require_sockets=False, allow_boundary=False):
    coll = bpy.data.collections[collection] if isinstance(collection, str) else collection
    if isinstance(material_palette, str):
        material_palette = [m for m in material_palette.split(",") if m]
    if isinstance(grid, (int, float)):
        grid = (float(grid),) * 3
    pivot = None if pivot in (None, "", "NONE") else str(pivot).upper()
    pivot = PIVOT_ALIASES.get(pivot, pivot)
    if pivot not in (None, 'BOTTOM_CENTER', 'CENTER', 'CORNER'):
        raise ValueError(f"pivot {pivot!r}")
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    meshes = [o for o in coll.all_objects if o.type == 'MESH']
    mesh_set = set(meshes)
    parts = [o for o in meshes if not o.name.startswith("SOCKET_") and not _has_mesh_ancestor(o, mesh_set)]
    skipped = [o.name for o in coll.all_objects if o not in parts and not o.name.startswith("SOCKET_")
               and not (o.type == 'MESH' and _has_mesh_ancestor(o, mesh_set))]
    rows, all_mats = [], {}
    for o in sorted(parts, key=lambda x: x.name):
        st = _part_stats(o, dg, texture_px)
        issues = []
        sc = o.matrix_basis.to_scale()
        if any(abs(s - 1.0) > 1e-5 for s in sc):
            issues.append({"kind": "unapplied_scale", "detail": [round(s, 5) for s in sc]})
        ang = o.matrix_basis.to_quaternion().angle
        if ang > 1e-4:
            issues.append({"kind": "unapplied_rotation", "detail": round(math.degrees(ang), 3)})
        wsc = [abs(s) for s in o.matrix_world.to_scale()]
        if st["bbox_local"]:
            lo, hi = Vector(st["bbox_local"][0]), Vector(st["bbox_local"][1])
            dims = [(hi[i] - lo[i]) * wsc[i] for i in range(3)]
            st["dimensions_m"] = [round(d, 5) for d in dims]
            if pivot:
                c = (lo + hi) / 2
                exp = {"BOTTOM_CENTER": Vector((c.x, c.y, lo.z)), "CENTER": c, "CORNER": lo}[pivot]
                off = Vector(exp[i] * wsc[i] for i in range(3))
                st["pivot_offset_m"] = [round(v, 5) for v in off]
                if off.length > pivot_tol:
                    issues.append({"kind": "pivot", "detail": f"origin {off.length:.4f} m from {pivot}"})
            if grid:
                bad = {}
                for i, ax in enumerate("XYZ"):
                    if ax not in grid_axes.upper():
                        continue
                    r = dims[i] / grid[i]
                    if round(r) == 0 or abs(r - round(r)) * grid[i] > grid_tol:
                        bad[ax] = round(dims[i], 5)
                if bad:
                    issues.append({"kind": "off_grid", "detail": {"dims": bad, "grid": list(grid)}})
        else:
            issues.append({"kind": "empty_mesh", "detail": "no vertices"})
        if st["ngons"]:
            issues.append({"kind": "ngons", "detail": st["ngons"]})
        nm = st["wire_edges"] + st["multi_face_edges"] + (0 if allow_boundary else st["boundary_edges"])
        if nm:
            issues.append({"kind": "non_manifold", "detail": {"boundary": st["boundary_edges"], "wire": st["wire_edges"],
                                                              "multi_face": st["multi_face_edges"]}})
        mats = [s.material.name if s.material else None for s in o.material_slots]
        st["materials"] = mats
        if not mats or None in mats:
            issues.append({"kind": "material_slot_empty", "detail": mats})
        for m in mats:
            if m:
                all_mats.setdefault(m, []).append(o.name)
        if material_palette is not None:
            stray = sorted({m for m in mats if m and m not in material_palette})
            if stray:
                issues.append({"kind": "material_not_in_palette", "detail": stray})
        if not st["uv_map"]:
            issues.append({"kind": "missing_uv", "detail": None})
        socks = [c for c in o.children_recursive if c.name.startswith("SOCKET_")]
        st["sockets"] = [c.name for c in socks]
        bad_socks = [c.name for c in socks if c.type != 'EMPTY']
        if bad_socks:
            issues.append({"kind": "socket_not_empty", "detail": bad_socks})
        if require_sockets and not socks:
            issues.append({"kind": "no_sockets", "detail": None})
        rows.append({"part": o.name, "stats": st, "issues": issues})

    # kit-level: texel density outliers
    dens = sorted(r["stats"]["texel_px_per_m"] for r in rows if r["stats"].get("texel_px_per_m"))
    median = None
    if dens:
        k = len(dens)
        median = dens[k // 2] if k % 2 else (dens[k // 2 - 1] + dens[k // 2]) / 2
        ref = texel_target_px_per_m or median
        for r in rows:
            d = r["stats"].get("texel_px_per_m")
            if d and ref and abs(d / ref - 1) > texel_tolerance:
                r["issues"].append({"kind": "texel_density_outlier",
                                    "detail": f"{d:.1f} px/m vs {'target' if texel_target_px_per_m else 'median'} {ref:.1f} ({(d / ref - 1) * 100:+.0f}%)"})
            elif d == 0 or (r["stats"].get("uv_map") and not d):
                r["issues"].append({"kind": "texel_density_zero", "detail": "UV area is 0"})
    # kit-level: naming prefix
    pref = {r["part"]: (m.group(1) if (m := re.match(r"^([A-Za-z0-9]+)_", r["part"])) else None) for r in rows}
    expected = prefix
    if expected is None:
        counts = {}
        for p in pref.values():
            if p: counts[p] = counts.get(p, 0) + 1
        expected = max(counts, key=counts.get) if counts else None
    if expected:
        for r in rows:
            if pref[r["part"]] != expected:
                r["issues"].append({"kind": "name_prefix", "detail": f"{pref[r['part']]!r} != {expected!r}"})
    for r in rows:
        if re.search(r"\.\d{3}$", r["part"]):
            r["issues"].append({"kind": "duplicate_suffix_name", "detail": r["part"]})

    kinds = {}
    for r in rows:
        for i in r["issues"]:
            kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    summary = {"collection": coll.name, "parts": len(rows), "parts_with_issues": sum(1 for r in rows if r["issues"]),
               "clean_parts": [r["part"] for r in rows if not r["issues"]], "issue_counts": kinds,
               "unique_materials": len(all_mats), "materials": {m: len(v) for m, v in sorted(all_mats.items())},
               "texel_px_per_m": {"min": dens[0] if dens else None, "median": median, "max": dens[-1] if dens else None,
                                  "max_over_min": round(dens[-1] / dens[0], 3) if dens and dens[0] else None,
                                  "target": texel_target_px_per_m, "texture_px": texture_px},
               "name_prefix": expected, "total_tris": sum(r["stats"]["tris"] for r in rows),
               "skipped_non_part_objects": skipped}
    return {"summary": summary, "parts": rows, "blender": bpy.app.version_string}


def _has_mesh_ancestor(o, mesh_set):
    p = o.parent
    while p is not None:
        if p in mesh_set:
            return True
        p = p.parent
    return False


# ------------------------------------------------------------------ place
def _norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(bpy.path.abspath(p))))


def place_instance(library_blend, collection_name, *, location=(0, 0, 0), rotation_euler=(0, 0, 0), link=True,
                   name=None, parent_collection=None):
    path = bpy.path.abspath(library_blend)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    if bpy.data.filepath and _norm(path) == _norm(bpy.data.filepath):
        raise ValueError("library_blend is the currently open file")
    res = {"library_blend": path, "collection": collection_name, "link": bool(link)}
    coll, lib = None, None
    for l in bpy.data.libraries:
        if _norm(bpy.path.abspath(l.filepath, library=l.library)) == _norm(path):
            lib = l; break
    if link and lib is not None:
        coll = next((c for c in bpy.data.collections if c.library == lib and c.name == collection_name), None)
    if not link:
        coll = next((c for c in bpy.data.collections if c.library is None and c.get("_asset_library_src") == f"{_norm(path)}|{collection_name}"), None)
    res["reused"] = coll is not None
    if coll is None:
        before = set(bpy.data.collections)
        kw = {"link": bool(link), "relative": False}
        if not link:
            kw["reuse_local_id"] = True
        try:
            loader = bpy.data.libraries.load(path, **kw)
        except TypeError:  # older API without reuse_local_id
            kw.pop("reuse_local_id", None); loader = bpy.data.libraries.load(path, **kw)
        with loader as (src, dst):
            if collection_name not in src.collections:
                raise KeyError(f"collection {collection_name!r} not in {path}: {list(src.collections)[:30]}")
            dst.collections = [collection_name]
        coll = dst.collections[0]
        if coll is None:
            raise RuntimeError("library load returned no collection")
        if not link and coll not in before:
            coll["_asset_library_src"] = f"{_norm(path)}|{collection_name}"
    empty = bpy.data.objects.new(name or collection_name, None)
    empty.instance_type = 'COLLECTION'
    empty.instance_collection = coll
    empty.empty_display_size = 0.25
    empty.location = Vector(location)
    empty.rotation_euler = tuple(rotation_euler)
    target = (bpy.data.collections[parent_collection] if parent_collection else
              (bpy.context.collection or bpy.context.scene.collection))
    target.objects.link(empty)
    bpy.context.view_layer.update()
    res.update({"instance": empty.name, "collection_datablock": coll.name,
                "library_datablock": coll.library.name if coll.library else None,
                "libraries_total": len(bpy.data.libraries),
                "instances_of_collection": sum(1 for o in bpy.data.objects if o.instance_type == 'COLLECTION' and o.instance_collection == coll),
                "instance_offset": list(coll.instance_offset)})
    return res


# ------------------------------------------------------------------ snap
def _rest_world(obj):
    """World matrix as authored (works for linked objects that are not in any scene / not evaluated)."""
    if obj.parent is not None and obj.parent_type == 'OBJECT':
        return _rest_world(obj.parent) @ obj.matrix_parent_inverse @ obj.matrix_basis
    if obj.parent is not None:
        return obj.matrix_world.copy()
    return obj.matrix_basis.copy()


def _find_by_name(objs, sock_name):
    objs = list(objs)
    hit = next((o for o in objs if o.name == sock_name), None)
    if hit is None:  # tolerate .001 suffixes from appends/duplicates
        hit = next((o for o in objs if re.sub(r"\.\d{3}$", "", o.name) == sock_name), None)
    return hit


def socket_world(owner, sock_name):
    """World matrix of socket `sock_name` belonging to `owner` (object with SOCKET children, or collection-instance
    Empty whose collection holds the socket). owner=None -> a scene object called sock_name."""
    if owner is None:
        o = bpy.data.objects[sock_name]
        return o.matrix_world.copy(), o
    if owner.instance_type == 'COLLECTION' and owner.instance_collection is not None:
        coll = owner.instance_collection
        s = _find_by_name(coll.all_objects, sock_name)
        if s is None:
            raise KeyError(f"socket {sock_name!r} not in instanced collection {coll.name!r}")
        return owner.matrix_world @ Matrix.Translation(-Vector(coll.instance_offset)) @ _rest_world(s), s
    s = _find_by_name(owner.children_recursive, sock_name)
    if s is None:
        raise KeyError(f"socket {sock_name!r} is not a descendant of {owner.name!r}")
    return s.matrix_world.copy(), s


def _parse_target(target_socket):
    if isinstance(target_socket, (tuple, list)):
        return bpy.data.objects[target_socket[0]], target_socket[1]
    if target_socket in bpy.data.objects and "/" not in target_socket:
        return None, target_socket
    if "/" in target_socket:
        own, s = target_socket.rsplit("/", 1)
        return bpy.data.objects[own], s
    raise KeyError(f"target socket {target_socket!r}: not a scene object and not 'Owner/SOCKET_name'")


def snap_to_socket(part_name, part_socket, target_socket, *, flip=True):
    part = bpy.data.objects[part_name] if isinstance(part_name, str) else part_name
    bpy.context.view_layer.update()
    towner, tname = _parse_target(target_socket)
    if towner == part:
        raise ValueError("target socket belongs to the part being moved")
    P = part.matrix_world.copy()
    Sp, sp_obj = socket_world(part, part_socket)
    St, st_obj = socket_world(towner, tname)
    if towner is None and (st_obj == part or part in _ancestors(st_obj)):
        raise ValueError("target socket is parented under the part being moved")
    R = P.inverted() @ Sp                                    # socket in part space
    t_loc, t_rot, _ = St.decompose()
    _, _, s_scale = Sp.decompose()
    D = Matrix.LocRotScale(t_loc, t_rot, Vector((1, 1, 1)))
    if flip:
        D = D @ Matrix.Rotation(math.pi, 4, 'Y')            # Z -> -Z, Y stays: plug-into, roll locked by +Y
    D = D @ Matrix.LocRotScale(None, None, s_scale)
    P_new = D @ R.inverted()
    part.matrix_world = P_new
    bpy.context.view_layer.update()
    Sp2, _ = socket_world(part, part_socket)
    St2, _ = socket_world(towner, tname)
    z1, z2 = Sp2.to_3x3().col[2].normalized(), St2.to_3x3().col[2].normalized()
    y1, y2 = Sp2.to_3x3().col[1].normalized(), St2.to_3x3().col[1].normalized()
    return {"part": part.name, "part_socket": sp_obj.name, "target_socket": (towner.name + "/" if towner else "") + st_obj.name,
            "flip": bool(flip), "location": [round(v, 6) for v in part.matrix_world.translation],
            "rotation_euler_deg": [round(math.degrees(a), 4) for a in part.matrix_world.to_euler()],
            "position_error_m": (Sp2.translation - St2.translation).length, "z_dot": z1.dot(z2), "y_dot": y1.dot(y2),
            "ok": (Sp2.translation - St2.translation).length < 1e-4 and abs(z1.dot(z2) - (-1 if flip else 1)) < 1e-4 and y1.dot(y2) > 1 - 1e-4,
            "note": "part has constraints: matrix_world may be overridden" if part.constraints else None}


def _ancestors(o):
    out, p = [], o.parent
    while p is not None:
        out.append(p); p = p.parent
    return out


# ------------------------------------------------------------------ CLI / live
def _vec(s, deg=False):
    v = [float(x) for x in s.split(",")]
    return tuple(math.radians(x) for x in v) if deg else tuple(v)


def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="asset_library.py")
    ap.add_argument("--save", action="store_true", help="save the open .blend after the operation")
    ap.add_argument("--save-as")
    sub = ap.add_subparsers(dest="op", required=True)
    m = sub.add_parser("mark"); m.add_argument("--names", required=True); m.add_argument("--id-type", default="OBJECT")
    m.add_argument("--catalog", default="Kit/SciFi/Panels"); m.add_argument("--tags", default="")
    m.add_argument("--description", default=""); m.add_argument("--author", default="")
    m.add_argument("--no-preview", action="store_true"); m.add_argument("--blend-dir")
    a = sub.add_parser("audit"); a.add_argument("--collection", required=True); a.add_argument("--texture-px", type=int, default=2048)
    a.add_argument("--texel-target", type=float); a.add_argument("--texel-tolerance", type=float, default=0.25)
    a.add_argument("--grid", type=float); a.add_argument("--grid-axes", default="XYZ"); a.add_argument("--pivot", default="BOTTOM_CENTER")
    a.add_argument("--palette"); a.add_argument("--prefix"); a.add_argument("--require-sockets", action="store_true")
    a.add_argument("--allow-boundary", action="store_true")
    p = sub.add_parser("place"); p.add_argument("--library", required=True); p.add_argument("--collection", required=True)
    p.add_argument("--location", default="0,0,0"); p.add_argument("--rotation-deg", default="0,0,0")
    p.add_argument("--append", action="store_true"); p.add_argument("--name")
    s = sub.add_parser("snap"); s.add_argument("--part", required=True); s.add_argument("--part-socket", required=True)
    s.add_argument("--target-socket", required=True); s.add_argument("--no-flip", action="store_true")
    for sp in (m, a, p, s):  # allow --save after the subcommand too
        sp.add_argument("--save", action="store_true", dest="save_sub"); sp.add_argument("--save-as", dest="save_as_sub")
    o = ap.parse_args(argv)
    if o.op == "mark":
        res = mark_assets(o.names, id_type=o.id_type, catalog=o.catalog, tags=o.tags, description=o.description,
                          author=o.author, preview=not o.no_preview, blend_dir=o.blend_dir)
    elif o.op == "audit":
        res = kit_audit(o.collection, texture_px=o.texture_px, texel_target_px_per_m=o.texel_target, texel_tolerance=o.texel_tolerance,
                        grid=o.grid, grid_axes=o.grid_axes, pivot=o.pivot, material_palette=o.palette, prefix=o.prefix,
                        require_sockets=o.require_sockets, allow_boundary=o.allow_boundary)
    elif o.op == "place":
        res = place_instance(o.library, o.collection, location=_vec(o.location), rotation_euler=_vec(o.rotation_deg, True),
                             link=not o.append, name=o.name)
    else:
        res = snap_to_socket(o.part, o.part_socket, o.target_socket, flip=not o.no_flip)
    save_as = o.save_as or o.save_as_sub
    if save_as:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(save_as)); res["saved"] = save_as
    elif o.save or o.save_sub:
        if not bpy.data.filepath:
            res["saved"] = None; res.setdefault("warnings", []).append("--save on an unsaved file: use --save-as PATH")
        else:
            bpy.ops.wm.save_mainfile(); res["saved"] = bpy.data.filepath
    return res


OPS = {"mark": mark_assets, "audit": kit_audit, "place": place_instance, "snap": snap_to_socket}
_POSITIONAL = {"mark": ("names",), "audit": ("collection",), "place": ("library_blend", "collection_name"),
               "snap": ("part_name", "part_socket", "target_socket")}

if "ASSET_OPTS" in globals():  # live exec
    _o = dict(ASSET_OPTS); _op = _o.pop("op")
    _args = [_o.pop(k) for k in _POSITIONAL[_op]]
    result = OPS[_op](*_args, **_o)
    print(TAG, json.dumps(result, default=str))
elif __name__ == "__main__" and "--" in sys.argv and set(sys.argv[sys.argv.index("--") + 1:]) & set(OPS):
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print(TAG, json.dumps(result, default=str))
else:
    result = {"defined": ["mark_assets", "kit_audit", "place_instance", "snap_to_socket", "socket_world",
                          "ensure_catalog", "read_catalogs"]}
